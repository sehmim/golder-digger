"""Deterministic fake features, seeded by chunk id.

Same shape and ranges as the real extractors, so scoring/API can be exercised
end to end without loading beat-this or CLAP. Swap off with GOLDDIGGER_MOCK=0.
"""
import hashlib
import numpy as np

from . import config


def _rng(key: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))


def rhythm(key: str) -> dict:
    r = _rng(key + ":rhythm")
    bpm = float(r.choice([70, 85, 90, 100, 120, 128, 140, 150, 174]))
    n = int(r.integers(16, 64))
    beats = np.arange(n) * (60.0 / bpm)
    bpb = int(r.choice([4, 4, 4, 3]))
    return {"beats": beats, "downbeats": beats[::bpb], "bpm": bpm, "beats_per_bar": bpb}


def chroma(key: str) -> np.ndarray:
    """A real-looking chroma: a diatonic set around a tonic plus noise."""
    r = _rng(key + ":chroma")
    tonic = int(r.integers(0, 12))
    scale = [0, 2, 4, 5, 7, 9, 11] if r.random() < 0.6 else [0, 2, 3, 5, 7, 8, 10]
    v = np.full(12, 0.02)
    for i, deg in enumerate(scale):
        v[(tonic + deg) % 12] += 0.3 if i == 0 else r.uniform(0.05, 0.2)
    v += r.uniform(0, 0.03, 12)
    return (v / v.sum()).astype(np.float32)


def clap(key: str) -> np.ndarray:
    """Clustered so novelty percentiles are not uniform noise."""
    r = _rng(key + ":clap")
    centroid = np.random.default_rng(int(r.integers(0, 8))).standard_normal(config.CLAP_DIM)
    v = centroid + r.standard_normal(config.CLAP_DIM) * 0.8
    return (v / np.linalg.norm(v)).astype(np.float32)


def role(key: str) -> str:
    return str(_rng(key + ":role").choice(config.ROLES))
