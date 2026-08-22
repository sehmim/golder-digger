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


def tonalness(chroma: np.ndarray) -> float:
    """0 for a flat chroma, ->1 for a peaked one. Normalized negative entropy.

    Needed because a *gap* between key candidates can be large by chance on
    atonal material -- and a sample library is full of drums.
    """
    p = np.asarray(chroma, dtype=np.float64)
    p = p / (p.sum() + 1e-12)
    ent = -np.sum(p * np.log(p + 1e-12))
    return float(np.clip(1.0 - ent / np.log(12.0), 0.0, 1.0))


def estimate_key(chroma: np.ndarray) -> tuple[int, int, float]:
    """(tonic_pc, is_major, confidence) via Krumhansl correlation over 24 candidates.

    Confidence is the gap to the best competing tonic -- raw correlation is high
    for anything tonal and carries no discriminative signal -- scaled by how
    tonal the chroma is at all. Without the second term, flat/noisy chroma
    produces a large gap by chance and drums claim a confident key.
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
    return int(t_best), int(1 - m_best), float(np.clip(conf, 0.0, 1.0))


# ---------------------------------------------------------------- role

def role_from_path(path) -> tuple[str | None, str]:
    """Keyword match over filename + parent dir. Manual tag, no classifier."""
    text = f"{Path(path).parent.name} {Path(path).stem}".lower()
    hits = [(sum(k in text for k in kws), role)
            for role, kws in config.ROLE_KEYWORDS.items()]
    n, role = max(hits)
    return (role, "filename") if n > 0 else (None, "unknown")


# ---------------------------------------------------------------- CLAP

class Clap:
    """Lazy singleton. Audio and text both project to the same 512-d space."""

    def __init__(self, device: str | None = None):
        from transformers import ClapModel, ClapProcessor
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        self.model = ClapModel.from_pretrained(config.CLAP_MODEL).to(self.device).eval()
        self.proc = ClapProcessor.from_pretrained(config.CLAP_MODEL)

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
