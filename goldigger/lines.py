"""The transit model: four lines out of your session, and the stops along them.

DISTANCE answers "how far", and DIGLINE names the weakness in that honestly --
farther along *which* dimension? A single dial cannot say. Its proposed fix is a
novelty computed over whichever dimensions you left unlocked,
`N = sum_k w_k d_k` for k in unlocked.

A line is that idea with one dimension unlocked at a time, which is also what
makes it drawable: you are at a station (your session), four coloured lines lead
out of it, and riding one takes you somewhere further away *in that respect and
no other*. Fit still gates every stop, so the far end of a line is strange but
still works -- which is the whole product in one picture.

Nothing here replaces `scoring.select`. The character line is the existing
DISTANCE dimension; the other three are the same corpus asked different
questions.
"""
from __future__ import annotations

import numpy as np

from . import config, presets, scoring


def line_keys() -> list[str]:
    return [key for key, _colour, _blurb in config.LINES]


def _percentile(distance: np.ndarray, pool: np.ndarray) -> np.ndarray:
    """Rank `distance` within `pool` and return each pool member's position.

    Percentile rather than raw magnitude for the reason novelty_all gives: a
    cosine distance of 0.4 means nothing on its own, and means something
    different in every library.
    """
    out = np.zeros(len(distance), dtype=np.float64)
    if len(pool) == 0:
        return out
    order = pool[np.argsort(distance[pool], kind="stable")]
    out[order] = np.linspace(0.0, 1.0, len(order))
    return out


def harmony_distance(corpus, ctx: dict) -> np.ndarray:
    """How far the notes are from the context's, 0 near to 1 far.

    Chroma cosine and circle-of-fifths distance, the same two terms Fit's H
    combines -- read as a distance here instead of a compatibility. Weighted
    the same way, so a candidate cannot be close on this line and far on H.
    """
    cn = corpus.chroma / (np.linalg.norm(corpus.chroma, axis=1, keepdims=True) + 1e-9)
    qn = ctx["chroma"] / (np.linalg.norm(ctx["chroma"]) + 1e-9)
    chroma_sim = np.clip(cn @ qn, 0.0, 1.0)
    cof = scoring.cof_proximity_all(corpus.tonic, ctx["tonic"])
    return 1.0 - (config.W_CHROMA * chroma_sim + config.W_COF * cof)


def groove_distance(corpus, ctx: dict) -> np.ndarray:
    """Ratio-aware tempo distance in octaves: the `d` inside tempo_score.

    Ratio-aware for the same reason Fit is -- 87 against 174 is a match, not
    the far end of the line. A chunk with no tempo has no position on this
    line at all, which is NaN, not zero.
    """
    x = np.asarray(corpus.bpm, dtype=np.float64)
    out = np.full(len(x), np.nan)
    if not ctx["bpm"] or np.isnan(ctx["bpm"]):
        return out
    usable = np.isfinite(x) & (x > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.asarray(config.TEMPO_RATIOS, dtype=np.float64)
        d = np.abs(np.log2(np.outer(x, ratios) / ctx["bpm"])).min(axis=1)
    out[usable] = d[usable]
    return out


def timbre_vectors(corpus) -> np.ndarray:
    """The spectral descriptors, log-scaled and standardised across the corpus.

    Cached on the corpus like role_codes: the standardisation is over the whole
    library, so it cannot be computed per request without changing with the
    candidate set. Hz descriptors are logged first -- see config.TIMBRE_LOG.
    """
    cached = getattr(corpus, "_timbre", None)
    if cached is not None:
        return cached

    raw = np.array(corpus.spectral, dtype=np.float64, copy=True)
    for j, name in enumerate(config.TIMBRE_DESCRIPTORS):
        if name in config.TIMBRE_LOG:
            # a non-positive centroid is a silent chunk, not a very dark one
            column = raw[:, j]
            raw[:, j] = np.where(column > 0, np.log(np.maximum(column, 1e-9)), np.nan)
    with np.errstate(invalid="ignore"):
        centre = np.nanmedian(raw, axis=0)
        # median absolute deviation: a library with one hyper-bright oddity
        # should not restate every other chunk as "average"
        spread = np.nanmedian(np.abs(raw - centre), axis=0) * 1.4826
    spread = np.where(np.isfinite(spread) & (spread > 1e-9), spread, 1.0)
    centre = np.where(np.isfinite(centre), centre, 0.0)
    corpus._timbre = ((raw - centre) / spread).astype(np.float64)
    return corpus._timbre


def timbre_distance(corpus, ctx: dict) -> np.ndarray:
    """Euclidean distance in standardised descriptor space.

    The novelty half DIGLINE asks for and this engine measured but never read.
    NaN where a chunk was never measured, so it drops off the line instead of
    ranking as maximally similar.
    """
    vectors = timbre_vectors(corpus)
    reference = ctx.get("timbre")
    if reference is None:
        return np.full(len(vectors), np.nan)
    d = np.sqrt(np.sum((vectors - reference) ** 2, axis=1))
    return d


def character_distance(corpus, ctx: dict) -> np.ndarray:
    """Cosine distance in CLAP space -- what DISTANCE has always measured."""
    return 1.0 - corpus.clap @ ctx["clap"]


DISTANCES = {
    "harmony": harmony_distance,
    "groove": groove_distance,
    "timbre": timbre_distance,
    "character": character_distance,
}


def context_timbre(corpus, ctx: dict) -> np.ndarray | None:
    """The context's own position in descriptor space.

    Contexts built from corpus chunks have indices to average; one built from a
    MIDI file has no sound at all and therefore no place on this line.
    """
    idx = ctx.get("idx") or []
    if not idx:
        return None
    vectors = timbre_vectors(corpus)[idx]
    with np.errstate(invalid="ignore"):
        mean = np.nanmean(vectors, axis=0)
    return None if not np.all(np.isfinite(mean)) else mean


_INTERVALS = {1: "a semitone up", 2: "a tone up", 3: "a minor third up",
              4: "a major third up", 5: "a fourth up", 6: "a tritone away",
              7: "a fifth up", 8: "a minor sixth up", 9: "a sixth up",
              10: "a seventh up", 11: "a major seventh up"}


def _harmony_label(corpus, i: int, ctx: dict) -> str:
    """Name the term that actually moved this stop out.

    harmony_distance is `W_CHROMA · chroma + W_COF · fifths`, so naming the key
    relation alone can call the furthest stop "a tone up" while what really put
    it there is that it shares almost no notes. An explanation that names the
    smaller term is worse than none: it is wrong in a way the listener will
    test and disbelieve.
    """
    a, b = int(corpus.tonic[i]), int(ctx["tonic"])
    cn = corpus.chroma[i] / (np.linalg.norm(corpus.chroma[i]) + 1e-9)
    qn = ctx["chroma"] / (np.linalg.norm(ctx["chroma"]) + 1e-9)
    chroma_sim = float(np.clip(cn @ qn, 0.0, 1.0))
    from_chroma = config.W_CHROMA * (1.0 - chroma_sim)
    from_cof = config.W_COF * (1.0 - scoring.cof_proximity(a, b))

    if a < 0 or b < 0:
        key = "key unknown"
    else:
        steps = (a - b) % 12
        key = "same key" if steps == 0 else _INTERVALS.get(steps, f"{steps} semitones up")
    if from_chroma <= from_cof:
        return key
    notes = "few shared notes" if chroma_sim < 0.5 else "different notes"
    return notes if key == "key unknown" else f"{key}, {notes}"


def _groove_label(corpus, i: int, ctx: dict) -> str:
    bpm, ref = float(corpus.bpm[i]), ctx["bpm"]
    if not np.isfinite(bpm) or not ref:
        return "no tempo"
    ratio = bpm / ref
    for name, value in (("2:1", 2.0), ("1:2", 0.5), ("3:2", 1.5), ("2:3", 2 / 3)):
        if abs(np.log2(ratio / value)) < 0.04:
            return f"{name} against the session"
    if abs(np.log2(ratio)) < 0.04:
        return "same tempo"
    return f"{round(bpm)} against {round(ref)} BPM"


# What a move along each descriptor sounds like, (up, down). Descriptors with no
# entry here are still measured and still move the line -- they just have no
# phrase, and _timbre_label says nothing rather than borrowing a neighbour's.
_TIMBRE_MOVES = {
    "centroid": ("brighter", "darker"),
    "rolloff": ("more top end", "less top end"),
    "bandwidth": ("wider", "narrower"),
    "flatness": ("noisier", "purer"),
}


def _timbre_label(corpus, i: int, ctx: dict) -> str:
    """Name the descriptor that actually moved this stop out.

    Same discipline as _harmony_label. An earlier version compared centroid
    against flatness alone and so described stops whose distance came almost
    entirely from bandwidth as "brighter" -- a sentence the listener will test
    and disbelieve. The distance is Euclidean over all four, so the label has to
    consider all four.
    """
    reference = ctx.get("timbre")
    if reference is None or not np.all(np.isfinite(corpus.spectral[i])):
        return "timbre unmeasured"
    delta = timbre_vectors(corpus)[i] - reference
    j = int(np.argmax(np.abs(delta)))
    moves = _TIMBRE_MOVES.get(config.TIMBRE_DESCRIPTORS[j])
    if moves is None:
        return "a different texture"
    word = moves[0] if delta[j] > 0 else moves[1]
    # the units are MADs of the whole library, so two of them is a move nobody
    # would call subtle
    return f"much {word}" if abs(delta[j]) >= config.TIMBRE_STRONG else word


LABELS = {
    "harmony": _harmony_label,
    "groove": _groove_label,
    "timbre": _timbre_label,
    "character": lambda corpus, i, ctx: "further out",
}


def stops(corpus, ctx: dict, key: str, allowed: np.ndarray | None = None,
          preset: presets.Preset | None = None, count: int | None = None) -> list[dict]:
    """The stations along one line, nearest first."""
    return route(corpus, ctx, key, allowed, preset, count)["stops"]


def route(corpus, ctx: dict, key: str, allowed: np.ndarray | None = None,
          preset: presets.Preset | None = None,
          count: int | None = None) -> dict:
    """One line: its stations, and the floor they actually cleared.

    Each stop is the best-fitting candidate sitting near its target percentile
    of *this line's* distance, with a redundancy penalty so consecutive stops
    are not the same idea twice. The gate is `select`'s, floor relaxation
    included -- and the relaxation is reported, because a line that had to open
    its gate to find six stops is a different claim from one that did not, and
    from the drawing alone the two are identical.
    """
    if key not in DISTANCES:
        raise ValueError(f"no such line: {key}")
    preset = preset or presets.DEFAULT
    count = count or config.LINE_STOPS
    allowed = np.ones(len(corpus), dtype=bool) if allowed is None else allowed

    fit = scoring.fit_all(corpus, ctx, preset)["fit"]
    same_file = scoring.same_file_mask(corpus, ctx)
    distance = DISTANCES[key](corpus, ctx)
    measured = np.isfinite(distance)

    floor = preset.fit_floor
    while True:
        pool = np.where((fit >= floor) & ~same_file & allowed & measured)[0]
        if len(pool) >= count or floor <= config.FIT_FLOOR_MIN:
            break
        floor -= config.FIT_FLOOR_STEP
    summary = {"key": key, "fit_floor": round(float(floor), 3),
               "fit_floor_requested": preset.fit_floor,
               "fit_floor_relaxed": floor < preset.fit_floor}
    if len(pool) == 0:
        return {**summary, "stops": []}

    position = _percentile(distance, pool)
    targets = np.linspace(config.LINE_STOP_MIN, config.LINE_STOP_MAX, count)

    picked: list[int] = []
    remaining = pool.copy()
    for target in targets:
        if not len(remaining):
            break
        score = -np.abs(position[remaining] - target)
        if picked:
            score = score - config.LINE_REDUNDANCY * (
                corpus.clap[remaining] @ corpus.clap[picked].T).max(axis=1)
        best = remaining[int(np.argmax(score))]
        picked.append(best)
        remaining = remaining[remaining != best]

    picked.sort(key=lambda i: position[i])
    label = LABELS[key]
    return {**summary, "stops": [
        {
            "chunk_id": corpus.ids[i],
            "path": corpus.rows[i]["path"],
            "role": corpus.roles[i],
            "bpm": None if np.isnan(corpus.bpm[i]) else round(float(corpus.bpm[i]), 1),
            "tonic": (config.PITCH_NAMES[corpus.tonic[i]]
                      if corpus.tonic[i] >= 0 else None),
            "fit": round(float(fit[i]), 3),
            # where this stop sits along *this* line, which is the only novelty
            # claim a single-dimension route is entitled to make
            "position": round(float(position[i]), 3),
            "why": label(corpus, i, ctx),
        }
        for i in picked
    ]}


def network(corpus, ctx: dict, allowed: np.ndarray | None = None,
            preset: presets.Preset | None = None,
            count: int | None = None) -> dict:
    """Every line out of this session, plus the interchanges between them.

    A chunk that is a stop on two lines is an interchange in the useful sense:
    it is far from the session in two different respects at once, which is
    exactly the find a single dial can name but never locate.
    """
    preset = preset or presets.DEFAULT
    ctx = dict(ctx)
    if "timbre" not in ctx:
        ctx["timbre"] = context_timbre(corpus, ctx)

    routes = []
    for key, colour, blurb in config.LINES:
        drawn = route(corpus, ctx, key, allowed, preset, count)
        routes.append({**drawn, "colour": colour, "blurb": blurb,
                       # a line with nothing measured is drawn greyed out rather
                       # than silently missing: "we cannot ask this of your
                       # library yet" is information
                       "available": bool(drawn["stops"])})

    seen: dict[str, list[str]] = {}
    for drawn in routes:
        for stop in drawn["stops"]:
            seen.setdefault(stop["chunk_id"], []).append(drawn["key"])
    interchanges = [{"chunk_id": cid, "lines": keys}
                    for cid, keys in seen.items() if len(keys) > 1]

    return {"lines": routes, "interchanges": interchanges,
            "preset": preset.key,
            # per line above; here only as the posture's own number
            "fit_floor_requested": preset.fit_floor}
