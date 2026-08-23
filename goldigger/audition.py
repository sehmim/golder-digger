"""Render a chunk so it can be judged against the session, not imagined.

A candidate at 90 BPM auditioned against a 120 BPM session tells you nothing --
you end up assessing the tempo mismatch instead of the musical relationship. So
the candidate is time-stretched to the session tempo before it is heard, and the
two can be mixed into one file so the *combination* is what reaches the ear.

Two decisions worth stating outright:

Pitch is never shifted. `librosa.effects.time_stretch` is a phase vocoder: it
changes duration and leaves pitch alone. Transposing candidates into the session
key would make the harmony scoring look far better than it is, because every
harmonic error would be corrected by the audition layer before anyone heard it.
Pitch correction belongs in a separate experimental condition, not in the
default path.

Stretching is ratio-aware, for the same reason `scoring.tempo_score` is. A 174
BPM break against an 87 BPM session already fits -- its beats land on the
eighths. Stretching it by 0.5 would wreck it to fix a problem it does not have.
"""
from __future__ import annotations

import functools
import io
from pathlib import Path

import numpy as np

from . import config

# How far the source may be stretched before it is better left alone.
MAX_STRETCH = 2.0
# Simply matching the session tempo wins unless it costs more than this much
# stretch. Chasing the *least* stretch alone picks exotic relationships -- 90
# against 120 would play at 80, a 2:3 polyrhythm, because that stretches less
# than matching outright. Compatible in the scoring sense; not what you want in
# your ears when auditioning.
DIRECT_MAX = 1.5
PEAK = 0.89          # leave headroom so a sum of two loud loops cannot clip


def stretch_rate(src_bpm: float | None, target_bpm: float | None) -> tuple[float, float]:
    """-> (rate, effective_bpm). rate > 1 speeds up.

    Matching the session tempo outright wins whenever it costs less than
    DIRECT_MAX of stretch. Only past that does it look for a half-, double- or
    triplet-time relationship the material already has -- so a 174 BPM break
    against an 87 BPM session plays untouched instead of being halved.
    """
    if not src_bpm or not target_bpm or src_bpm <= 0 or target_bpm <= 0:
        return 1.0, float(src_bpm or 0.0)

    direct = target_bpm / src_bpm
    if abs(np.log2(direct)) <= np.log2(DIRECT_MAX):
        best = direct
    else:
        # too far to stretch outright, so look for a half/double/triplet
        # relationship the material already has
        best = min((abs(np.log2((target_bpm * m) / src_bpm)), (target_bpm * m) / src_bpm)
                   for m in config.TEMPO_RATIOS)[1]

    if not (1 / MAX_STRETCH <= best <= MAX_STRETCH):
        return 1.0, float(src_bpm)
    return float(best), float(src_bpm * best)


class ChunkOutsideAudio(Exception):
    """A stored span that is not inside the file it names.

    Carries both numbers, because the only useful next question is which of the
    two is wrong: chunk grids written under mock came from an invented beat grid
    that took no account of the file's length, and a file replaced in place can
    simply be shorter than the spans already stored against it.
    """

    def __init__(self, path: str, t_start: float, duration: float):
        self.path, self.t_start, self.duration = path, t_start, duration
        super().__init__(f"chunk starts at {t_start:.2f}s but {path} is only "
                         f"{duration:.2f}s long")


def load_chunk(path: str, t_start: float, t_end: float, sr: int | None = None):
    """The span, clamped to what the file actually holds.

    Without the clamp librosa's seek raises `LibsndfileError: Internal
    psf_fseek() failed` from inside soundfile, which reaches the desktop as a
    bare "500 could not render <chunk_id>" -- naming neither the file nor the
    reason. A span that merely overruns the end is playable and is trimmed; one
    that begins past the end has no audio at all and is named instead.
    """
    import librosa
    import soundfile as sf

    duration = float(sf.info(path).duration)
    if t_start >= duration:
        raise ChunkOutsideAudio(path, t_start, duration)

    y, sr = librosa.load(path, sr=sr, mono=True,
                         offset=t_start, duration=max(0.05, min(t_end, duration) - t_start))
    return y, sr


def time_stretch(y: np.ndarray, rate: float) -> np.ndarray:
    """Phase-vocoder stretch. Duration changes; pitch does not."""
    if abs(rate - 1.0) < 1e-3 or len(y) < 64:
        return y
    import librosa
    return librosa.effects.time_stretch(y=np.ascontiguousarray(y), rate=rate)


def tile_to(y: np.ndarray, length: int) -> np.ndarray:
    """Repeat a loop to fill `length`. A one-bar loop should keep playing under
    a four-bar context rather than leaving three bars of silence."""
    if len(y) == 0:
        return np.zeros(length, dtype=np.float32)
    if len(y) >= length:
        return y[:length]
    reps = int(np.ceil(length / len(y)))
    return np.tile(y, reps)[:length]


def mix(context: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    """Sum both from t=0, shorter one tiled, normalised to leave headroom.

    Both parts are laid down from the same instant because the chunk boundaries
    are already downbeat-aligned -- offsetting them would introduce a phase
    relationship nobody asked for.
    """
    n = max(len(context), len(candidate))
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    out = tile_to(context, n).astype(np.float32) + tile_to(candidate, n).astype(np.float32)
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > PEAK:
        out *= PEAK / peak
    return out.astype(np.float32)


def to_wav(y: np.ndarray, sr: int) -> io.BytesIO:
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, y, sr, format="WAV")
    buf.seek(0)
    return buf


def _row_key(row) -> tuple:
    """Hashable audio identity, including the source file's current version.

    Chunk ids are content-derived, but previews still read the path on disk. The
    stat fields keep a replaced file from receiving audio cached for its former
    contents without putting file bytes in the key.
    """
    path = str(row["path"])
    stat = Path(path).stat()
    return (
        path,
        float(row["t_start"]),
        float(row["t_end"]),
        float(row["bpm"]) if row["bpm"] is not None else None,
        stat.st_mtime_ns,
        stat.st_size,
    )


@functools.lru_cache(maxsize=config.AUDITION_RENDER_CACHE)
def _render_cached(key: tuple, target_bpm: float | None, sr: int | None):
    """Decode and stretch once for every (chunk, tempo, sample-rate) render."""
    path, t_start, t_end, source_bpm, _mtime_ns, _size = key
    y, actual_sr = load_chunk(path, t_start, t_end, sr)
    rate, effective = stretch_rate(source_bpm, target_bpm)
    y = time_stretch(y, rate)
    # Cache entries are shared across requests. All mixing paths copy before
    # arithmetic, and read-only arrays make that contract explicit.
    y.setflags(write=False)
    return y, actual_sr, rate, effective


def render_chunk(row, target_bpm: float | None, sr: int | None = None):
    """One chunk, stretched to the session tempo. -> (audio, sr, meta)."""
    y, sr, rate, effective = _render_cached(_row_key(row), target_bpm, sr)
    return y, sr, {
        "source_bpm": row["bpm"],
        "target_bpm": target_bpm,
        "rate": round(rate, 4),
        "effective_bpm": round(effective, 1) if effective else None,
        "stretched": abs(rate - 1.0) >= 1e-3,
        "pitch_shifted": False,
    }


@functools.lru_cache(maxsize=config.AUDITION_CONTEXT_CACHE)
def _render_context_cached(keys: tuple[tuple, ...], target_bpm: float | None, sr: int):
    """Build the reusable session bed once instead of once per candidate."""
    bed = np.zeros(0, dtype=np.float32)
    for key in keys:
        try:
            part, _actual_sr, _rate, _effective = _render_cached(key, target_bpm, sr)
        except ChunkOutsideAudio:
            # The bed is a mix of several chunks and survives losing one. Failing
            # the whole preview would let a single unplayable context chunk make
            # every candidate in the session unauditionable.
            continue
        bed = part if not len(bed) else mix(bed, part)
    bed.setflags(write=False)
    return bed


def render_context(rows, target_bpm: float | None, sr: int = config.PREVIEW_SR):
    """Tempo-align and mix a session context, with a bounded file-aware cache."""
    keys = tuple(_row_key(row) for row in rows)
    return _render_context_cached(keys, target_bpm, sr), sr


def clear_caches() -> None:
    """Drop cached audio, primarily for tests and an explicit future reload path."""
    _render_context_cached.cache_clear()
    _render_cached.cache_clear()
