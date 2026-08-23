"""Fit (compatibility gate) and Novelty (corpus-relative percentile), then
greedy MMR selection against a target novelty band.

Fit and Novelty are deliberately separate: "works with" and "sounds like" are
different constructs, and collapsing them into one weighted distance is what the
DISTANCE dial exists to avoid.
"""
from __future__ import annotations

import json

import numpy as np

from . import config


# ---------------------------------------------------------------- corpus

class Corpus:
    """All chunks in memory. At a few thousand rows every query is one matmul."""

    def __init__(self, rows):
        self.rows = list(rows)
        n = len(self.rows)
        self.ids = [r["chunk_id"] for r in self.rows]
        self.index = {cid: i for i, cid in enumerate(self.ids)}
        self.clap = np.zeros((n, config.CLAP_DIM), dtype=np.float32)
        self.chroma = np.zeros((n, 12), dtype=np.float32)
        self.bpm = np.full(n, np.nan, dtype=np.float32)
        self.tonic = np.full(n, -1, dtype=np.int16)
        self.kconf = np.zeros(n, dtype=np.float32)
        self.roles = [None] * n
        self.hashes = [None] * n
        # False for a measured CLAP vector, True for a synthesized or unknown one.
        # Novelty is a distance in this space, so a corpus with any of these in it
        # cannot report the dial as a measurement.
        self.synthetic = np.zeros(n, dtype=bool)

    def __len__(self):
        return len(self.rows)


# ---------------------------------------------------------------- helpers

def cof_proximity(a: int, b: int) -> float:
    """1.0 for the same key, 0.0 for a tritone. Circle-of-fifths steps / 6."""
    if a < 0 or b < 0:
        return config.NEUTRAL
    d = ((a * 7) - (b * 7)) % 12
    return 1.0 - min(d, 12 - d) / 6.0


def role_compat(candidate: str | None, context_roles: set[str]) -> float:
    """Complement beats duplication -- this is a layering tool, not a search box.

    Floored at ROLE_SAME rather than 0: a literal zero annihilates the geometric
    mean and would make role a hard filter instead of a preference.
    """
    if not candidate or not context_roles:
        return config.NEUTRAL
    if candidate in context_roles:
        return config.ROLE_SAME
    for other in context_roles:
        if frozenset((candidate, other)) in config.NEUTRAL_ROLE_PAIRS:
            return config.NEUTRAL
    return 1.0


def tempo_score(bpm_x, bpm_ctx) -> float:
    """Ratio-aware: 87 against 174 BPM is a match, not maximum distance."""
    if not bpm_x or not bpm_ctx or np.isnan(bpm_x) or np.isnan(bpm_ctx):
        return config.NEUTRAL
    d = min(abs(np.log2((bpm_x * r) / bpm_ctx)) for r in config.TEMPO_RATIOS)
    return float(np.exp(-d / config.TEMPO_TOL))


# ---------------------------------------------------------------- context

def build_context(corpus: Corpus, chunk_ids: list[str]) -> dict:
    idx = [corpus.index[c] for c in chunk_ids if c in corpus.index]
    if not idx:
        raise ValueError("no known chunk ids in context")
    clap = corpus.clap[idx].mean(axis=0)
    clap /= np.linalg.norm(clap) + 1e-9
    chroma = corpus.chroma[idx].mean(axis=0)
    chroma /= chroma.sum() + 1e-9
    bpms = corpus.bpm[idx]
    bpms = bpms[~np.isnan(bpms)]
    kc = corpus.kconf[idx]
    return {
        "idx": idx,
        "clap": clap,
        "chroma": chroma,
        "bpm": float(np.median(bpms)) if len(bpms) else None,
        # tonic of the most confident member, not a meaningless average
        "tonic": int(corpus.tonic[idx[int(np.argmax(kc))]]) if len(kc) else -1,
        "kconf": float(kc.mean()) if len(kc) else 0.0,
        "roles": {corpus.roles[i] for i in idx if corpus.roles[i]},
        "hashes": {corpus.hashes[i] for i in idx},
    }


# ---------------------------------------------------------------- fit

def fit_all(corpus: Corpus, ctx: dict) -> dict[str, np.ndarray]:
    n = len(corpus)
    cn = corpus.chroma / (np.linalg.norm(corpus.chroma, axis=1, keepdims=True) + 1e-9)
    qn = ctx["chroma"] / (np.linalg.norm(ctx["chroma"]) + 1e-9)
    chroma_sim = np.clip(cn @ qn, 0.0, 1.0)

    cof = np.array([cof_proximity(int(t), ctx["tonic"]) for t in corpus.tonic])
    raw = config.W_CHROMA * chroma_sim + config.W_COF * cof

    # soft evidence: an unconfident key estimate must not hard-exclude anything
    c = np.minimum(corpus.kconf, ctx["kconf"])
    H = c * raw + (1.0 - c) * config.NEUTRAL

    R = np.array([tempo_score(b, ctx["bpm"]) for b in corpus.bpm])
    P = np.array([role_compat(r, ctx["roles"]) for r in corpus.roles])

    eps = 1e-3
    # geometric mean: one catastrophic component cannot be masked by two good ones
    F = np.exp((np.log(H + eps) + np.log(R + eps) + np.log(P + eps)) / 3.0)
    return {"fit": F, "H": H, "R": R, "P": P}


# ---------------------------------------------------------------- novelty

def novelty_all(corpus: Corpus, ctx: dict) -> np.ndarray:
    """Percentile of CLAP distance ranked across the WHOLE corpus.

    Not across the Fit-passing subset: FIT_FLOOR relaxes when the pool is sparse,
    which would silently shift every novelty value for the same context.
    """
    d = 1.0 - corpus.clap @ ctx["clap"]
    order = np.argsort(d)
    pct = np.empty(len(d), dtype=np.float64)
    pct[order] = np.linspace(0.0, 1.0, len(d))
    return pct


# ---------------------------------------------------------------- select

def select(corpus: Corpus, ctx: dict, distance: float, k: int = config.DEFAULT_K):
    """Greedy MMR against a target novelty band.

    Greedy because the redundancy term compares against what is *already picked* --
    undefined in a one-shot top-K.
    """
    scores = fit_all(corpus, ctx)
    fit, nov = scores["fit"], novelty_all(corpus, ctx)
    q = np.clip(distance / 100.0, 0.0, 1.0)

    # never return the context's own file: otherwise DISTANCE 10 just hands back
    # the neighbouring bars of the clip you already have
    same_file = np.array([h in ctx["hashes"] for h in corpus.hashes])

    floor = config.FIT_FLOOR
    while True:
        pool = np.where((fit >= floor) & ~same_file)[0]
        if len(pool) >= 3 * k or floor <= config.FIT_FLOOR_MIN:
            break
        floor -= config.FIT_FLOOR_STEP

    picked: list[int] = []
    while len(picked) < k and len(pool):
        band = -np.abs(nov[pool] - q) / config.BANDWIDTH
        if picked:
            red = (corpus.clap[pool] @ corpus.clap[picked].T).max(axis=1)
        else:
            red = np.zeros(len(pool))
        best = pool[int(np.argmax(band - config.REDUNDANCY * red))]
        picked.append(best)
        pool = pool[pool != best]

    return [
        {
            "chunk_id": corpus.ids[i],
            "path": corpus.rows[i]["path"],
            "role": corpus.roles[i],
            # provenance, so a UI can distinguish a human's filename from a guess
            "role_source": corpus.rows[i]["role_source"],
            "tags": [t["tag"] for t in json.loads(corpus.rows[i]["tags"] or "[]")][:3],
            "bpm": None if np.isnan(corpus.bpm[i]) else round(float(corpus.bpm[i]), 1),
            "tonic": (config.PITCH_NAMES[corpus.tonic[i]] if corpus.tonic[i] >= 0 else None),
            "is_major": bool(corpus.rows[i]["is_major"]),
            "key_confidence": round(float(corpus.kconf[i]), 3),
            "fit": round(float(fit[i]), 3),
            "novelty": round(float(nov[i]), 3),
            "components": {"H": round(float(scores["H"][i]), 3),
                           "R": round(float(scores["R"][i]), 3),
                           "P": round(float(scores["P"][i]), 3)},
        }
        for i in picked
    ], floor
