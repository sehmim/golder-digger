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



def tag_sims(key: str) -> np.ndarray:
    """Similarities with one clear winner, so tags_from_sims -- the real
    function -- produces a realistically peaked distribution."""
    r = _rng(key + ":tags")
    sims = r.uniform(-0.05, 0.15, len(config.TAG_VOCAB))
    sims[int(r.integers(0, len(config.TAG_VOCAB)))] += 0.30
    return sims


def confidences(key: str) -> tuple[float, float]:
    """(tonalness, tempo_confidence) -- plausible spreads, not all-1.0."""
    r = _rng(key + ":conf")
    return float(r.uniform(0.02, 0.95)), float(r.uniform(0.0, 0.9))


def spectral(key: str) -> dict:
    r = _rng(key + ":spectral")
    ranges = {"centroid": (400, 6000), "rolloff": (800, 11000),
              "bandwidth": (300, 4000), "flatness": (1e-4, 0.4),
              "rms": (0.01, 0.4), "zcr": (0.01, 0.35)}
    return {k: {"mean": float(r.uniform(*lohi)),
                "confidence": float(r.uniform(0.25, 0.98))}
            for k, lohi in ranges.items()}


def note_presence(key: str) -> np.ndarray:
    """A sparse, realistically-shaped presence vector: a few notes held for most
    of the chunk, a few passing through, the rest absent."""
    r = _rng(key + ":notes")
    v = np.zeros(12, dtype=np.float32)
    tonic = int(r.integers(0, 12))
    scale = [0, 2, 4, 5, 7, 9, 11] if r.random() < 0.6 else [0, 2, 3, 5, 7, 8, 10]
    for deg in r.choice(scale, size=int(r.integers(3, 6)), replace=False):
        v[(tonic + int(deg)) % 12] = float(r.uniform(0.2, 1.0))
    return v
