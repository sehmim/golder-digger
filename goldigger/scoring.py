"""Fit (compatibility gate) and Novelty (corpus-relative percentile), then
greedy MMR selection against a target novelty band.

Fit and Novelty are deliberately separate: "works with" and "sounds like" are
different constructs, and collapsing them into one weighted distance is what the
DISTANCE dial exists to avoid.

Every per-candidate term here is computed over the whole corpus at once. The
readable scalar forms (`cof_proximity`, `tempo_score`, `role_compat`) are kept
because they are what the tests assert against and what a reader should look at
first, but the scoring path calls the array forms beside them: at 100k chunks the
four Python comprehensions this replaced were the entire cost of a rank, while
the 512-wide matmul they surrounded was microseconds.
"""
from __future__ import annotations

import json

import numpy as np

from . import config, presets


# ---------------------------------------------------------------- corpus

class Corpus:
    """All chunks in memory. At a few thousand rows every query is one matmul."""

    def __init__(self, rows):
        self.rows = list(rows)
        # A lightweight identity that can safely outlive this object in bounded
        # cache keys. Unlike id(self), it can never be reused for a later corpus.
        self.cache_token = object()
        n = len(self.rows)
        self.ids = [r["chunk_id"] for r in self.rows]
        self.index = {cid: i for i, cid in enumerate(self.ids)}
        self.clap = np.zeros((n, config.CLAP_DIM), dtype=np.float32)
        self.chroma = np.zeros((n, 12), dtype=np.float32)
        self.bpm = np.full(n, np.nan, dtype=np.float32)
        self.tonic = np.full(n, -1, dtype=np.int16)
        self.kconf = np.zeros(n, dtype=np.float32)
        self.tconf = np.zeros(n, dtype=np.float32)
        self.roles = [None] * n
        self.hashes = [None] * n
        # False for a measured CLAP vector, True for a synthesized or unknown one.
        # Novelty is a distance in this space, so a corpus with any of these in it
        # cannot report the dial as a measurement.
        self.synthetic = np.zeros(n, dtype=bool)

    def __len__(self):
        return len(self.rows)


# The two derived encodings below are functions rather than methods, and cache
# onto whatever object they are handed. A "corpus" here is a structural type --
# the baseline and listening tests pass their own stand-ins -- and a method would
# quietly make Corpus the only thing that can be scored.

def role_codes(corpus) -> tuple[list, np.ndarray]:
    """(distinct roles, per-chunk index into it).

    A corpus of any size holds at most eight distinct roles, so the role term
    becomes eight lookups and one fancy-index rather than a call per chunk.
    """
    cached = getattr(corpus, "_role_codes", None)
    if cached is None:
        distinct = sorted({r for r in corpus.roles if r is not None}, key=str)
        order = {r: i for i, r in enumerate(distinct)}
        # None takes the trailing slot: "no role recorded" is its own case in
        # role_compat, not a role that happens to match nothing
        codes = np.fromiter((order.get(r, len(distinct)) for r in corpus.roles),
                            dtype=np.int32, count=len(corpus.roles))
        cached = (distinct, codes)
        corpus._role_codes = cached
    return cached


def hash_codes(corpus) -> tuple[dict, np.ndarray]:
    """(file_hash -> code, per-chunk code). Turns the same-file exclusion from a
    string `in` per chunk into one np.isin."""
    cached = getattr(corpus, "_hash_codes", None)
    if cached is None:
        order: dict = {}
        codes = np.empty(len(corpus.hashes), dtype=np.int32)
        for i, h in enumerate(corpus.hashes):
            codes[i] = order.setdefault(h, len(order))
        cached = (order, codes)
        corpus._hash_codes = cached
    return cached


# ---------------------------------------------------------------- helpers

def cof_proximity(a: int, b: int) -> float:
    """1.0 for the same key, 0.0 for a tritone. Circle-of-fifths steps / 6."""
    if a < 0 or b < 0:
        return config.NEUTRAL
    d = ((a * 7) - (b * 7)) % 12
    return 1.0 - min(d, 12 - d) / 6.0


def cof_proximity_all(tonics: np.ndarray, b: int) -> np.ndarray:
    """cof_proximity over a whole corpus at once."""
    t = np.asarray(tonics, dtype=np.int32)
    d = ((t * 7) - (b * 7)) % 12
    cof = 1.0 - np.minimum(d, 12 - d) / 6.0
    # a missing tonic on either side is absence of evidence, not a tritone
    return np.where((t < 0) | (b < 0), config.NEUTRAL, cof)


def role_compat(candidate: str | None, context_roles: set[str],
                mode: str = "normal") -> float:
    """Complement beats duplication -- this is a layering tool, not a search box.

    Floored above 0 rather than at it: a literal zero annihilates the geometric
    mean and would make role a hard filter instead of a preference. `mode` picks
    how hard the preference argues -- see config.ROLE_MODES.
    """
    w = config.ROLE_MODES[mode]
    if not candidate or not context_roles:
        return w["unknown"]
    if candidate in context_roles:
        return w["same"]
    for other in context_roles:
        if frozenset((candidate, other)) in config.NEUTRAL_ROLE_PAIRS:
            return w["pair"]
    return 1.0


def role_compat_all(corpus: "Corpus", context_roles: set[str],
                    mode: str = "normal") -> np.ndarray:
    """role_compat over a whole corpus, via the eight-entry lookup table."""
    distinct, codes = role_codes(corpus)
    # the trailing entry is the None case, which role_compat already answers
    lut = np.array([role_compat(r, context_roles, mode) for r in distinct]
                   + [role_compat(None, context_roles, mode)])
    return lut[codes]


def tempo_score(bpm_x, bpm_ctx) -> float:
    """Ratio-aware: 87 against 174 BPM is a match, not maximum distance."""
    if not bpm_x or not bpm_ctx or np.isnan(bpm_x) or np.isnan(bpm_ctx):
        return config.NEUTRAL
    d = min(abs(np.log2((bpm_x * r) / bpm_ctx)) for r in config.TEMPO_RATIOS)
    return float(np.exp(-d / config.TEMPO_TOL))


def tempo_score_all(bpms: np.ndarray, bpm_ctx) -> np.ndarray:
    """tempo_score over a whole corpus at once."""
    x = np.asarray(bpms, dtype=np.float64)
    if not bpm_ctx or np.isnan(bpm_ctx):
        return np.full(len(x), config.NEUTRAL)
    usable = np.isfinite(x) & (x > 0)
    # log2 of a zero or NaN tempo warns and yields -inf; both are masked back to
    # NEUTRAL below, so the arithmetic is allowed to produce them quietly
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.asarray(config.TEMPO_RATIOS, dtype=np.float64)
        d = np.abs(np.log2(np.outer(x, ratios) / bpm_ctx)).min(axis=1)
    return np.where(usable, np.exp(-d / config.TEMPO_TOL), config.NEUTRAL)


# ---------------------------------------------------------------- context

def build_context(corpus: Corpus, chunk_ids: list[str]) -> dict:
    idx = [corpus.index[c] for c in chunk_ids if c in corpus.index]
    if not idx:
        raise ValueError("no known chunk ids in context")
    clap = corpus.clap[idx].mean(axis=0)
    clap /= np.linalg.norm(clap) + 1e-9
    chroma = corpus.chroma[idx].mean(axis=0)
    chroma /= chroma.sum() + 1e-9
    has_bpm = ~np.isnan(corpus.bpm[idx])
    bpms = corpus.bpm[idx][has_bpm]
    kc = corpus.kconf[idx]
    tc = getattr(corpus, "tconf", None)
    # over the members that *have* a tempo, matching how ctx["bpm"] is taken:
    # a one-shot stores tempo_confidence 0 because it has no tempo, and letting
    # those zeros average in would discount the loops the median came from
    tconf = 1.0
    if tc is not None:
        member_tconf = tc[idx][has_bpm]
        tconf = float(member_tconf.mean()) if len(member_tconf) else 0.0
    return {
        "idx": idx,
        "clap": clap,
        "chroma": chroma,
        "bpm": float(np.median(bpms)) if len(bpms) else None,
        "tconf": tconf,
        # tonic of the most confident member, not a meaningless average
        "tonic": int(corpus.tonic[idx[int(np.argmax(kc))]]) if len(kc) else -1,
        "kconf": float(kc.mean()) if len(kc) else 0.0,
        "roles": {corpus.roles[i] for i in idx if corpus.roles[i]},
        "hashes": {corpus.hashes[i] for i in idx},
    }


def context_from_rows(rows: list[dict]) -> dict:
    """A context from analyzed rows that were never ingested.

    The DAW-free path: hand the engine an audio file -- a loop, a bounce, a
    stem from any DAW or none -- and rank the library against it directly.
    Same aggregation as build_context, but the evidence arrives straight from
    the extractors instead of as corpus indices, so nothing needs to have been
    ingested and the novelty anchor is the file's own measured embedding.
    """
    rows = [r for r in rows if r.get("clap") is not None]
    if not rows:
        raise ValueError("no analyzable audio in context")
    clap = np.mean([r["clap"] for r in rows], axis=0)
    clap = clap / (np.linalg.norm(clap) + 1e-9)
    chroma = np.mean([np.asarray(r["chroma"], dtype=np.float32) for r in rows], axis=0)
    chroma = chroma / (chroma.sum() + 1e-9)
    timed = [r for r in rows if r["bpm"]]
    bpms = [r["bpm"] for r in timed]
    kc = [r["key_confidence"] or 0.0 for r in rows]
    best = int(np.argmax(kc))
    return {
        "idx": [],
        "clap": clap.astype(np.float32),
        "chroma": chroma.astype(np.float32),
        "bpm": float(np.median(bpms)) if bpms else None,
        # over the rows that have a tempo, for the reason build_context gives
        "tconf": float(np.mean([r["tempo_confidence"] or 0.0 for r in timed]))
                 if timed else 0.0,
        "tonic": int(rows[best]["tonic_pc"]) if rows[best]["tonic_pc"] is not None else -1,
        "kconf": float(np.mean(kc)),
        "roles": {r["role"] for r in rows if r["role"]},
        "hashes": {r["file_hash"] for r in rows},
    }


# ---------------------------------------------------------------- fit

def fit_all(corpus: Corpus, ctx: dict, preset: presets.Preset | None = None
            ) -> dict[str, np.ndarray]:
    preset = preset or presets.DEFAULT
    cn = corpus.chroma / (np.linalg.norm(corpus.chroma, axis=1, keepdims=True) + 1e-9)
    qn = ctx["chroma"] / (np.linalg.norm(ctx["chroma"]) + 1e-9)
    chroma_sim = np.clip(cn @ qn, 0.0, 1.0)

    cof = cof_proximity_all(corpus.tonic, ctx["tonic"])
    raw = config.W_CHROMA * chroma_sim + config.W_COF * cof

    # soft evidence: an unconfident key estimate must not hard-exclude anything
    c = np.minimum(corpus.kconf, ctx["kconf"])
    H = c * raw + (1.0 - c) * config.NEUTRAL

    R = tempo_score_all(corpus.bpm, ctx["bpm"])
    # the same treatment for tempo: beat trackers return *a* number for steady
    # noise, and the stored confidence is what separates that from a metronome.
    # getattr because a corpus here is a structural type -- the baseline and
    # listening stand-ins predate the array and keep their old behaviour.
    tc = getattr(corpus, "tconf", None)
    if tc is not None:
        ct = np.minimum(tc, ctx.get("tconf", 1.0))
        R = ct * R + (1.0 - ct) * config.NEUTRAL

    P = role_compat_all(corpus, ctx["roles"], preset.role_mode)

    eps = 1e-3
    # geometric mean: one catastrophic component cannot be masked by two good ones
    F = np.exp((np.log(H + eps) + np.log(R + eps) + np.log(P + eps)) / 3.0)
    return {"fit": F, "H": H, "R": R, "P": P}


# ---------------------------------------------------------------- novelty

def novelty_all(corpus: Corpus, ctx: dict, allowed: np.ndarray | None = None) -> np.ndarray:
    """Percentile of CLAP distance ranked across the active candidate corpus.

    Still not across the Fit-passing subset: FIT_FLOOR relaxes when the pool is
    sparse, which would silently shift every novelty value for the same context.
    """
    d = 1.0 - corpus.clap @ ctx["clap"]
    indices = np.where(allowed)[0] if allowed is not None else np.arange(len(d))
    pct = np.zeros(len(d), dtype=np.float64)
    order = indices[np.argsort(d[indices])]
    if len(order):
        pct[order] = np.linspace(0.0, 1.0, len(order))
    return pct


# ---------------------------------------------------------------- select

def same_file_mask(corpus: Corpus, ctx: dict) -> np.ndarray:
    """True for every chunk cut from a file the context already uses."""
    order, codes = hash_codes(corpus)
    ctx_codes = [order[h] for h in ctx["hashes"] if h in order]
    return np.isin(codes, ctx_codes)


def select(corpus: Corpus, ctx: dict, distance: float | None = None,
           k: int = config.DEFAULT_K, allowed: np.ndarray | None = None,
           preset: presets.Preset | None = None):
    """Greedy MMR against a target novelty band.

    Greedy because the redundancy term compares against what is *already picked* --
    undefined in a one-shot top-K.

    `preset` supplies the floor, band width, redundancy penalty and role mode.
    `distance` still overrides the preset's own position, because the dial keeps
    moving after a preset is chosen -- passing neither uses the preset's.
    """
    preset = preset or presets.DEFAULT
    scores = fit_all(corpus, ctx, preset)
    allowed = np.ones(len(corpus), dtype=bool) if allowed is None else allowed
    fit, nov = scores["fit"], novelty_all(corpus, ctx, allowed)
    q = np.clip((preset.distance if distance is None else distance) / 100.0, 0.0, 1.0)

    # never return the context's own file: otherwise DISTANCE 10 just hands back
    # the neighbouring bars of the clip you already have
    same_file = same_file_mask(corpus, ctx)

    floor = preset.fit_floor
    while True:
        pool = np.where((fit >= floor) & ~same_file & allowed)[0]
        if len(pool) >= 3 * k or floor <= config.FIT_FLOOR_MIN:
            break
        floor -= config.FIT_FLOOR_STEP

    picked: list[int] = []
    while len(picked) < k and len(pool):
        band = -np.abs(nov[pool] - q) / preset.bandwidth
        if picked:
            red = (corpus.clap[pool] @ corpus.clap[picked].T).max(axis=1)
        else:
            red = np.zeros(len(pool))
        best = pool[int(np.argmax(band - preset.redundancy * red))]
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
