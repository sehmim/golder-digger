"""The blind listening test: generate trials, serve them, record what people say.

Everything measured so far is internal to the scoring model. The baselines show
Gold Digger returns different material from inverse similarity and holds fit
while the dial moves -- they cannot show anyone finds the results useful. Only a
person can answer that, and only if they cannot see which arm produced what.

Three rules the rest of this module exists to enforce:

Nothing identifying the arm reaches the rater. `strategy` and `distance` stay in
the database; `trial_payload` is the only thing serialised outward, and a test
asserts those keys are absent from it.

Baselines are in the same blind pool. Ratings of Gold Digger alone would say
nothing comparative -- "6/7 inspiring" means little until random and
nearest-neighbour candidates have been rated by the same ears on the same day.

Every rater meets the trials in a different order, so a drift in attention over a
session cannot masquerade as an effect of the dial.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid

import numpy as np

from . import scoring, strategies

DISTANCES = (10, 30, 50, 70, 90)
PER_CELL = 3
# Baselines share the pool so the comparison is blind on both sides. `metadata`
# and `band_nofit` are omitted: with six arms the session gets long enough that
# fatigue becomes the dominant effect, and these four answer the live questions.
ARMS = ("golddigger", "random", "nearest", "inverse")
SCALES = ("obviousness", "compatibility", "inspiration", "discovery", "direction_change")


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


# ---------------------------------------------------------------- generation

def generate(conn, corpus, context_ids: list[str], batch: str | None = None,
             distances=DISTANCES, per_cell: int = PER_CELL, arms=ARMS,
             session_bpm: float | None = None, seed: int = 11) -> dict:
    """Build one batch of trials for a single session context.

    Trials are the cross product of arm x distance x per_cell. The
    distance-insensitive arms (random, nearest) would otherwise contribute the
    same candidates five times over, so they are drawn once and not repeated per
    distance -- five identical trials teach nothing and cost a rater five slots.
    """
    ctx = scoring.build_context(corpus, context_ids)
    fit = scoring.fit_all(corpus, ctx)["fit"]
    nov = scoring.novelty_all(corpus, ctx)
    batch = batch or uuid.uuid4().hex[:8]

    seen: set[int] = set()
    rows = []
    for arm in arms:
        pick = strategies.STRATEGIES[arm]
        # random and nearest ignore the dial, so asking them five times returns
        # the same thing five times
        arm_distances = distances if arm in ("golddigger", "inverse", "band_nofit") else (None,)
        for d in arm_distances:
            q = (d if d is not None else 50) / 100.0
            rng = np.random.default_rng(seed + hash(arm) % 1000)
            # over-draw, because candidates already used in this batch are skipped
            idx = pick(corpus, ctx, fit, nov, q, per_cell * 4, rng)
            taken = 0
            for i in idx:
                i = int(i)
                if i in seen:
                    continue
                seen.add(i)
                rows.append({
                    "trial_id": uuid.uuid4().hex[:12],
                    "batch": batch,
                    "context_ids": json.dumps(context_ids),
                    "candidate": corpus.ids[i],
                    "strategy": arm,
                    "distance": d,
                    "session_bpm": session_bpm,
                    "created_at": _now(),
                })
                taken += 1
                if taken >= per_cell:
                    break

    conn.executemany(
        "INSERT INTO trials (trial_id, batch, context_ids, candidate, strategy,"
        " distance, session_bpm, created_at) VALUES (:trial_id,:batch,:context_ids,"
        ":candidate,:strategy,:distance,:session_bpm,:created_at)", rows)
    conn.commit()
    return {"batch": batch, "trials": len(rows),
            "arms": sorted({r["strategy"] for r in rows})}


# ---------------------------------------------------------------- serving

def _order_key(rater: str, trial_id: str) -> str:
    """A per-rater shuffle that needs no stored ordering and survives a restart."""
    return hashlib.sha256(f"{rater}:{trial_id}".encode()).hexdigest()


def trial_payload(row) -> dict:
    """Everything the rater's browser is allowed to know.

    Deliberately excludes `strategy` and `distance`. Also excludes the
    candidate's path -- a filename like `..._Cm_90bpm.wav` would let a rater
    reason about compatibility instead of listening for it.
    """
    context_ids = json.loads(row["context_ids"])
    query = "&".join(f"context={c}" for c in context_ids)
    bpm = f"&bpm={row['session_bpm']}" if row["session_bpm"] else ""
    return {
        "trial_id": row["trial_id"],
        "mix_url": f"/session/preview?candidate={row['candidate']}&{query}{bpm}",
        "candidate_url": f"/session/preview?candidate={row['candidate']}"
                         f"&candidate_only=true{bpm}",
        "context_url": (f"/session/preview?candidate={context_ids[0]}"
                        f"&candidate_only=true{bpm}") if context_ids else None,
        "scales": list(SCALES),
    }


def next_trial(conn, rater: str, batch: str | None = None):
    """The rater's next unrated trial, in their own order. None when finished."""
    sql = ("SELECT t.* FROM trials t WHERE NOT EXISTS ("
           "  SELECT 1 FROM ratings r WHERE r.trial_id = t.trial_id AND r.rater = ?)")
    args: list = [rater]
    if batch:
        sql += " AND t.batch = ?"
        args.append(batch)
    rows = conn.execute(sql, args).fetchall()
    if not rows:
        return None
    return min(rows, key=lambda r: _order_key(rater, r["trial_id"]))


def progress(conn, rater: str, batch: str | None = None) -> dict:
    where, args = ("WHERE batch = ?", [batch]) if batch else ("", [])
    total = conn.execute(f"SELECT COUNT(*) FROM trials {where}", args).fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM ratings r JOIN trials t USING (trial_id) WHERE r.rater = ?"
        + (" AND t.batch = ?" if batch else ""),
        [rater] + ([batch] if batch else [])).fetchone()[0]
    return {"done": done, "total": total}


# ---------------------------------------------------------------- recording

def record(conn, trial_id: str, rater: str, scores: dict, note: str | None = None) -> dict:
    """Store one rating. Rejects out-of-range values rather than clamping them --
    a 9 on a 7-point scale means the client is wrong, and silently saving a 7
    would bury that."""
    if not conn.execute("SELECT 1 FROM trials WHERE trial_id=?", (trial_id,)).fetchone():
        raise KeyError(f"no such trial: {trial_id}")
    clean = {}
    for scale in SCALES:
        v = scores.get(scale)
        if v is None:
            clean[scale] = None
            continue
        v = int(v)
        if not 1 <= v <= 7:
            raise ValueError(f"{scale}={v} is outside the 1-7 scale")
        clean[scale] = v
    conn.execute(
        "INSERT OR REPLACE INTO ratings (trial_id, rater, obviousness, compatibility,"
        " inspiration, discovery, direction_change, note, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (trial_id, rater, clean["obviousness"], clean["compatibility"],
         clean["inspiration"], clean["discovery"], clean["direction_change"],
         note, _now()))
    conn.commit()
    return reveal(conn, trial_id)


def reveal(conn, trial_id: str) -> dict:
    """What the trial actually was. Only ever called after a rating is stored."""
    row = conn.execute(
        "SELECT strategy, distance, candidate FROM trials WHERE trial_id=?",
        (trial_id,)).fetchone()
    if not row:
        raise KeyError(f"no such trial: {trial_id}")
    return {"strategy": row["strategy"], "distance": row["distance"],
            "candidate": row["candidate"]}
