"""Per-chunk feature extraction: rhythm, key, and CLAP embedding."""
from __future__ import annotations

import hashlib
from pathlib import Path

import librosa
import numpy as np
import torch

from . import config
from .config import TONALNESS_GAIN

# ---------------------------------------------------------------- audio io

def file_hash(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_audio(path, sr=config.SR):
    y, _ = librosa.load(str(path), sr=sr, mono=True)
    if len(y) > sr * config.MAX_ANALYZE_SEC:
        y = y[: int(sr * config.MAX_ANALYZE_SEC)]
    return y, sr


# ---------------------------------------------------------------- rhythm

_a2b = None


def _beat_tracker(device: str):
    global _a2b
    if _a2b is None:
        from beat_this.inference import Audio2Beats
        _a2b = Audio2Beats(device=device)
    return _a2b


def analyze_rhythm(y, sr, device="cpu") -> dict:
    """Returns beats, downbeats, bpm, beats_per_bar. Any field may be None."""
    try:
        beats, downbeats = _beat_tracker(device)(y, sr)
    except Exception:
        beats, downbeats = np.array([]), np.array([])
    beats = np.asarray(beats, dtype=float)
    downbeats = np.asarray(downbeats, dtype=float)

    bpm = None
    if len(beats) > 2:
        ibi = np.diff(beats)
        ibi = ibi[ibi > 1e-3]
        if len(ibi):
            bpm = float(60.0 / np.median(ibi))

    # beats per bar = how many beats fall between consecutive downbeats
    bpb = None
    if len(downbeats) > 1 and len(beats) > 1:
        counts = [
            int(np.sum((beats >= downbeats[i]) & (beats < downbeats[i + 1])))
            for i in range(len(downbeats) - 1)
        ]
        counts = [c for c in counts if 1 <= c <= 12]
        if counts:
            bpb = int(round(float(np.median(counts))))

    return {"beats": beats, "downbeats": downbeats, "bpm": bpm, "beats_per_bar": bpb}


def tempo_confidence(y, sr, bpm) -> float:
    """How periodic the onset envelope actually is at the detected tempo, 0-1.

    Onset-envelope autocorrelation at the tempo's lag, relative to the zero-lag
    peak. Independent of *how* the BPM was derived, so it scores beat-this's
    answer as readily as librosa's. A one-shot with no repeating pulse scores
    near 0 -- which is the honest reading of a BPM printed next to it.
    """
    if not bpm or bpm <= 0 or not np.isfinite(bpm) or len(y) < sr // 2:
        return 0.0
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=config.HOP_LENGTH)
    if len(onset_env) < 4:
        return 0.0
    # mean-removed: on a raw envelope the DC offset dominates ac[lag]/ac[0], and
    # steady noise (flat, high mean) then outscores a metronome -- measured 0.886
    # against 0.773. Removing the mean makes this periodicity, not loudness.
    onset_env = onset_env - onset_env.mean()
    ac = librosa.autocorrelate(onset_env, max_size=len(onset_env))
    lag = int(round(60.0 / float(bpm) * sr / config.HOP_LENGTH))
    if not (0 < lag < len(ac)) or ac[0] <= 0:
        return 0.0
    return float(np.clip(ac[lag] / ac[0], 0.0, 1.0))


def chunk_boundaries(duration: float, rhythm: dict) -> list[tuple[float, float]]:
    """Downbeat-aligned bar chunks, or the whole file when it is already atomic.

    Most of a sample library is one-shots and single loops that *are* the unit --
    bar-slicing those is destructive, so short files pass through whole.
    """
    downbeats = rhythm["downbeats"]
    if duration <= config.WHOLE_FILE_MAX_SEC or len(downbeats) < 2:
        return [(0.0, duration)]

    step = config.BARS_PER_CHUNK
    spans = []
    for i in range(0, len(downbeats) - 1, step):
        start = float(downbeats[i])
        j = min(i + step, len(downbeats) - 1)
        end = float(downbeats[j])
        if end - start >= 0.5:
            spans.append((start, end))
    if not spans:  # downbeats present but unusable
        n = max(1, int(duration // config.FALLBACK_WINDOW_SEC))
        spans = [(k * config.FALLBACK_WINDOW_SEC,
                  min((k + 1) * config.FALLBACK_WINDOW_SEC, duration)) for k in range(n)]
    return spans


# ---------------------------------------------------------------- spectral

def stability(mean: float, std: float) -> float:
    """1/(1+CV): a mean is worth more when the frames behind it agree.

    The reference reported this as a 0-100 percentage; kept on 0-1 here so every
    confidence in the schema shares one scale.
    """
    cv = abs(float(std)) / (abs(float(mean)) + 1e-9)
    return float(1.0 / (1.0 + cv))


def spectral_stats(y, sr) -> dict[str, dict[str, float]]:
    """Scalar DSP descriptors, each with its frame-to-frame stability.

    Only descriptors that reduce to a scalar per frame are here. MFCC and
    spectral-contrast vectors have no single mean to score, and the CLAP
    embedding already carries timbre for anything downstream -- inventing a
    confidence for them would be exactly the fabrication this scheme avoids.
    """
    if len(y) < config.HOP_LENGTH * 2:
        y = np.pad(y, (0, config.HOP_LENGTH * 2 - len(y)))
    S = np.abs(librosa.stft(y, hop_length=config.HOP_LENGTH))
    series = {
        "centroid": librosa.feature.spectral_centroid(S=S, sr=sr)[0],
        "rolloff": librosa.feature.spectral_rolloff(S=S, sr=sr)[0],
        "bandwidth": librosa.feature.spectral_bandwidth(S=S, sr=sr)[0],
        "flatness": librosa.feature.spectral_flatness(S=S)[0],
        "rms": librosa.feature.rms(S=S)[0],
        "zcr": librosa.feature.zero_crossing_rate(y, hop_length=config.HOP_LENGTH)[0],
    }
    return {k: {"mean": float(v.mean()), "confidence": stability(v.mean(), v.std())}
            for k, v in series.items()}


# ---------------------------------------------------------------- tonalness

def hpss_split(y) -> tuple[np.ndarray, np.ndarray]:
    """Harmonic/percussive source separation. One call per file, sliced per chunk."""
    return librosa.effects.hpss(y)


def hpss_tonalness(y=None, *, harmonic=None, percussive=None) -> float:
    """Harmonic share of total energy, 0-1.

    The honest answer to "does this even have a key". A hi-hat lands near 0.05,
    a sustained pad near 0.95 -- so a key confidence multiplied by this collapses
    for percussive material regardless of which key the correlation preferred.

    Pass an already-computed split to avoid paying for HPSS twice.
    """
    if harmonic is None or percussive is None:
        harmonic, percussive = hpss_split(y)
    he = float(np.sum(np.asarray(harmonic, dtype=np.float64) ** 2))
    pe = float(np.sum(np.asarray(percussive, dtype=np.float64) ** 2))
    total = he + pe
    return float(he / total) if total > 0 else 0.5


# ---------------------------------------------------------------- key

_KS = np.array([config.KS_MAJOR, config.KS_MINOR], dtype=np.float64)
_KS = (_KS - _KS.mean(axis=1, keepdims=True))
_KS /= np.linalg.norm(_KS, axis=1, keepdims=True)


def chroma_vector(y, sr) -> np.ndarray:
    if len(y) < sr // 4:
        return np.full(12, 1 / 12, dtype=np.float32)
    c = librosa.feature.chroma_cqt(y=y, sr=sr, bins_per_octave=36)
    v = np.median(c, axis=1)
    s = v.sum()
    return (v / s if s > 0 else np.full(12, 1 / 12)).astype(np.float32)


def note_presence(y, sr=None) -> np.ndarray:
    """12 floats: the share of sounding frames each pitch class is active in.

    Per frame, not median-collapsed. The median that chroma_vector uses answers
    "what is the average harmony here", which silently deletes any chord holding
    a minority of the chunk -- a Cm|Cm|Cm|Fm loop reports only Cm. Thresholding
    each frame against its own peak and then counting frames keeps the Fm.

    The result is a weight, not a flag: a note held for three bars scores higher
    than one passed through for half of one, which is the difference between two
    loops sharing a tonal centre and merely brushing past the same pitch.

    Feed this the HPSS harmonic signal. Percussive energy smears across all
    twelve bins and will otherwise report a drum loop as every note at once.
    """
    if len(y) < config.HOP_LENGTH * 2 or not np.any(y):
        return np.zeros(12, dtype=np.float32)

    # norm=None is load-bearing: chroma_cqt normalizes every frame to peak 1.0 by
    # default, silence included, which would leave the gate below comparing 1.0
    # against 1.0 and letting silent frames vote. Raw magnitudes keep the
    # distinction -- measured 93.1 for sounding frames against 2.7 for silence.
    c = librosa.feature.chroma_cqt(y=y, sr=sr or config.SR, bins_per_octave=36,
                                   norm=None)
    peak = c.max(axis=0)
    if peak.max() <= 0:
        return np.zeros(12, dtype=np.float32)

    # silence has no notes to report; letting quiet frames vote would dilute
    # every presence fraction by however much padding the file happens to carry
    sounding = peak >= peak.max() * config.NOTE_SILENCE_REL
    if not sounding.any():
        return np.zeros(12, dtype=np.float32)

    normalized = c[:, sounding] / peak[sounding]
    active = normalized >= config.NOTE_FRAME_THRESHOLD
    return active.mean(axis=1).astype(np.float32)


def notes_from_presence(presence, floor: float | None = None) -> list[str]:
    """Pitch-class names above the presence floor, in pitch order.

    Kept separate from note_presence so the threshold can be revisited without
    re-analysing audio -- the stored vector is continuous on purpose.
    """
    floor = config.NOTE_PRESENCE_FLOOR if floor is None else floor
    return [config.PITCH_NAMES[i] for i in range(12) if presence[i] >= floor]


def tonalness(chroma: np.ndarray) -> float:
    """0 for a flat chroma, ->1 for a peaked one. Normalized negative entropy.

    Needed because a *gap* between key candidates can be large by chance on
    atonal material -- and a sample library is full of drums.
    """
    p = np.asarray(chroma, dtype=np.float64)
    p = p / (p.sum() + 1e-12)
    ent = -np.sum(p * np.log(p + 1e-12))
    return float(np.clip(1.0 - ent / np.log(12.0), 0.0, 1.0))


def estimate_key(chroma: np.ndarray, gate: float | None = None) -> tuple[int, int, float]:
    """(tonic_pc, is_major, confidence) via Krumhansl correlation over 24 candidates.

    Confidence is the gap to the best competing tonic -- raw correlation is high
    for anything tonal and carries no discriminative signal -- scaled by how
    tonal the chroma is at all. Without the second term, flat/noisy chroma
    produces a large gap by chance and drums claim a confident key.

    `gate` is the harmonic-energy share from hpss_tonalness, a second and
    independent question: chroma peakedness asks "is this pitch-class
    distribution concentrated", the gate asks "is there sustained pitch here at
    all". A filtered noise burst can pass the first and fail the second, so both
    have to hold. Omitted (None) leaves the chroma-only behaviour untouched --
    callers with no audio on hand, only a chroma vector, still work.
    """
    x = chroma.astype(np.float64) - chroma.mean()
    n = np.linalg.norm(x)
    if n < 1e-9:
        return 0, 1, 0.0
    x = x / n
    # scores[m, t] = correlation of chroma rotated to tonic t with profile m
    scores = np.array([[np.dot(np.roll(x, -t), _KS[m]) for t in range(12)]
                       for m in range(2)])
    m_best, t_best = np.unravel_index(np.argmax(scores), scores.shape)
    best = scores[m_best, t_best]
    other = scores[:, [t for t in range(12) if t != t_best]]
    gap = float(best - other.max()) if other.size else float(best)
    conf = float(np.clip(gap, 0.0, 1.0) * tonalness(chroma) * TONALNESS_GAIN)
    if gate is not None:
        conf *= float(np.clip(gate, 0.0, 1.0))
    return int(t_best), int(1 - m_best), float(np.clip(conf, 0.0, 1.0))


# ---------------------------------------------------------------- role

def role_from_path(path) -> tuple[str | None, str]:
    """Keyword match over filename + parent dir. Manual tag, no classifier."""
    text = f"{Path(path).parent.name} {Path(path).stem}".lower()
    hits = [(sum(k in text for k in kws), role)
            for role, kws in config.ROLE_KEYWORDS.items()]
    n, role = max(hits)
    return (role, "filename") if n > 0 else (None, "unknown")


# ---------------------------------------------------------------- tags

def softmax(x, temperature: float) -> np.ndarray:
    """Similarities -> a distribution over the tag vocabulary.

    Raw cosine similarity is not a certainty: it has no stable zero and no
    stable scale, so 0.31 is unreadable on its own. Softmaxed against the other
    candidates it becomes "this much of the probability mass landed here".
    """
    v = np.asarray(x, dtype=np.float64) / temperature
    e = np.exp(v - v.max())          # shift for overflow, softmax is invariant to it
    return e / e.sum()


def tags_from_sims(sims) -> list[dict]:
    """Cosine similarities against TAG_VOCAB -> the top-N tags with probabilities.

    The probabilities are computed over the *whole* vocabulary before the
    truncation, so a kept tag's number still means its share of all candidates.
    """
    sims = np.asarray(sims, dtype=np.float64)
    if sims.shape != (len(config.TAG_VOCAB),):
        raise ValueError(
            f"expected {len(config.TAG_VOCAB)} similarities, got {sims.shape}")
    probs = softmax(sims, config.TAG_TEMPERATURE)
    order = np.argsort(-probs)[: config.TAG_TOP_N]
    return [{"tag": config.TAG_VOCAB[i],
             "similarity": round(float(sims[i]), 4),
             "confidence": round(float(probs[i]), 4)} for i in order]


def role_from_tags(tags) -> str | None:
    """Best-supported role over the tag distribution, or None.

    Probability is summed per role rather than read off the single top tag: a
    drum loop splits its vote across kick/snare/hat, and any one of those alone
    can lose to a pad tag that took no such split.
    """
    totals: dict[str, float] = {}
    for t in tags:
        role = config.TAG_TO_ROLE.get(t["tag"])
        if role:
            totals[role] = totals.get(role, 0.0) + float(t["confidence"])
    if not totals:
        return None
    role, mass = max(totals.items(), key=lambda kv: kv[1])
    return role if mass >= config.TAG_ROLE_MIN_PROB else None


# ---------------------------------------------------------------- CLAP

class Clap:
    """Lazy singleton. Audio and text both project to the same 512-d space."""

    def __init__(self, device: str | None = None):
        from transformers import ClapModel, ClapProcessor
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.model = ClapModel.from_pretrained(config.CLAP_MODEL).to(self.device).eval()
        self.proc = ClapProcessor.from_pretrained(config.CLAP_MODEL)
        self._tag_vecs = None

    @torch.no_grad()
    def embed_audio(self, clips: list[np.ndarray]) -> np.ndarray:
        """clips are mono float arrays at CLAP_SR. Returns (n, 512) L2-normalized."""
        out = []
        win = int(config.CLAP_SR * config.CLAP_WINDOW_SEC)
        for clip in clips:
            if len(clip) < config.CLAP_SR // 10:
                clip = np.pad(clip, (0, config.CLAP_SR // 10 - len(clip)))
            # windows longer than CLAP's receptive field are mean-pooled
            windows = [clip[i:i + win] for i in range(0, max(1, len(clip)), win)]
            windows = [w for w in windows if len(w) > config.CLAP_SR // 10] or [clip]
            vecs = []
            for i in range(0, len(windows), config.CLAP_BATCH):
                batch = windows[i:i + config.CLAP_BATCH]
                inp = self.proc(audio=batch, sampling_rate=config.CLAP_SR,
                                return_tensors="pt")
                inp = {k: v.to(self.device) for k, v in inp.items()}
                vecs.append(self.model.get_audio_features(**inp).pooler_output.cpu().numpy())
            v = np.concatenate(vecs).mean(axis=0)
            out.append(v)
        arr = np.asarray(out, dtype=np.float32)
        return arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)

    @torch.no_grad()
    def embed_text(self, texts: list[str]) -> np.ndarray:
        inp = self.proc(text=texts, return_tensors="pt", padding=True)
        inp = {k: v.to(self.device) for k, v in inp.items()}
        v = self.model.get_text_features(**inp).pooler_output.cpu().numpy()
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)

    def tag_vectors(self) -> np.ndarray:
        """(len(TAG_VOCAB), 512), embedded once and reused for the whole corpus."""
        if self._tag_vecs is None:
            self._tag_vecs = self.embed_text(config.TAG_VOCAB)
        return self._tag_vecs

    def tags(self, audio_vecs: np.ndarray) -> list[list[dict]]:
        """Zero-shot tags per clip. Both sides are L2-normalized, so the matmul
        is cosine similarity."""
        return [tags_from_sims(row) for row in np.atleast_2d(audio_vecs) @ self.tag_vectors().T]
