"""Candidate-selection strategies, including the ones Gold Digger is judged against.

These live in the package rather than the evaluation script because two callers
need exactly the same definitions: `scripts/baselines.py`, which measures them
against each other, and `goldigger/listening.py`, which puts their output in
front of a human. If the two ever drifted apart, the listening test would be
rating something other than what the numbers describe.

`pick_golddigger` deliberately re-implements the body of `scoring.select` over
raw indices instead of calling it: `select` returns display dictionaries, and a
comparison harness needs corpus positions. The selection rule is the same one --
relax the fit floor until the pool is deep enough, then greedy MMR against the
target novelty band.
"""
from __future__ import annotations

import numpy as np

from . import config


def _eligible(corpus, ctx):
    """Never return the context's own file -- every strategy honours this."""
    return ~np.array([h in ctx["hashes"] for h in corpus.hashes])


def pick_random(corpus, ctx, fit, nov, q, k, rng):
    pool = np.where(_eligible(corpus, ctx))[0]
    return list(rng.choice(pool, size=min(k, len(pool)), replace=False))


def pick_metadata(corpus, ctx, fit, nov, q, k, rng):
    pool = np.where(_eligible(corpus, ctx))[0]
    return list(pool[np.argsort(-fit[pool])[:k]])


def pick_nearest(corpus, ctx, fit, nov, q, k, rng):
    pool = np.where(_eligible(corpus, ctx))[0]
    sim = corpus.clap[pool] @ ctx["clap"]
    return list(pool[np.argsort(-sim)[:k]])


def pick_inverse(corpus, ctx, fit, nov, q, k, rng):
    """Walk outward to the requested novelty. No fit gate, no diversity term."""
    pool = np.where(_eligible(corpus, ctx))[0]
    return list(pool[np.argsort(np.abs(nov[pool] - q))[:k]])


def _greedy_band(corpus, pool, nov, q, k):
    picked = []
    pool = pool.copy()
    while len(picked) < k and len(pool):
        band = -np.abs(nov[pool] - q) / config.BANDWIDTH
        red = (corpus.clap[pool] @ corpus.clap[picked].T).max(axis=1) if picked \
            else np.zeros(len(pool))
        best = pool[int(np.argmax(band - config.REDUNDANCY * red))]
        picked.append(best)
        pool = pool[pool != best]
    return picked


def pick_band_nofit(corpus, ctx, fit, nov, q, k, rng):
    return _greedy_band(corpus, np.where(_eligible(corpus, ctx))[0], nov, q, k)


def pick_golddigger(corpus, ctx, fit, nov, q, k, rng):
    ok = _eligible(corpus, ctx)
    floor = config.FIT_FLOOR
    while True:
        pool = np.where((fit >= floor) & ok)[0]
        if len(pool) >= 3 * k or floor <= config.FIT_FLOOR_MIN:
            break
        floor -= config.FIT_FLOOR_STEP
    return _greedy_band(corpus, pool, nov, q, k)


STRATEGIES = {
    "random": pick_random,
    "metadata": pick_metadata,
    "nearest": pick_nearest,
    "inverse": pick_inverse,
    "band_nofit": pick_band_nofit,
    "golddigger": pick_golddigger,
}
