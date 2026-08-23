"""What the listeners said.

Three questions, in the order they matter:

1. Does DISTANCE control perceived obviousness? Measured per rater, as a
   Spearman correlation between the requested position and the rating. If this
   is not negative, the dial does not do the one thing it claims to and nothing
   below is worth reading.

2. Does compatibility survive being dialled toward the strange? A dial that
   trades away usability as it goes up is just a randomiser with a ramp.

3. Does Gold Digger beat the baselines on inspiration and direction change?
   This is the product question, and the only one the internal metrics could
   never reach.

Correlations are computed per rater and then averaged, not pooled across
everyone. Pooling would let one prolific rater's habits stand in for the group,
and people differ in how much novelty they want -- which is itself a finding
rather than noise to average away.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldigger import db, listening  # noqa: E402

MIN_PAIRS = 4          # below this a per-rater correlation is not worth printing


def spearman(x, y) -> float:
    """Rank correlation, without pulling in scipy for one function."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2:
        return float("nan")
    rx, ry = _rank(x), _rank(y)
    sx, sy = rx.std(), ry.std()
    if sx == 0 or sy == 0:
        return float("nan")
    return float(((rx - rx.mean()) * (ry - ry.mean())).mean() / (sx * sy))


def _rank(a):
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), float)
    ranks[order] = np.arange(len(a), dtype=float)
    # average ties, so a rater who used only 3 of the 7 points is not penalised
    for v in np.unique(a):
        m = a == v
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    return ranks


def fetch(conn):
    return conn.execute(
        "SELECT r.rater, r.obviousness, r.compatibility, r.inspiration,"
        "       r.discovery, r.direction_change, r.note,"
        "       t.strategy, t.distance, t.batch"
        "  FROM ratings r JOIN trials t USING (trial_id)").fetchall()


def mean(rows, field, **where):
    vals = [r[field] for r in rows if r[field] is not None
            and all(r[k] == v for k, v in where.items())]
    return (float(np.mean(vals)), len(vals)) if vals else (float("nan"), 0)


def main():
    conn = db.connect()
    db.init(conn)
    rows = fetch(conn)
    if not rows:
        print("No ratings yet. Generate a batch, then rate at /rate.")
        return

    raters = sorted({r["rater"] for r in rows})
    print(f"ratings={len(rows)}  raters={len(raters)}  "
          f"trials rated={len({(r['rater'], r['strategy'], r['distance']) for r in rows})}\n")

    # ---- 1. does the dial control obviousness ----
    print("1. DISTANCE vs perceived obviousness (Gold Digger arm, per rater)")
    print("   negative = turning the dial up made things less obvious, as claimed")
    per_rater = []
    for rater in raters:
        pairs = [(r["distance"], r["obviousness"]) for r in rows
                 if r["rater"] == rater and r["strategy"] == "golddigger"
                 and r["distance"] is not None and r["obviousness"] is not None]
        if len(pairs) < MIN_PAIRS:
            print(f"   {rater:<12} n={len(pairs):<3} too few to correlate")
            continue
        rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        per_rater.append(rho)
        print(f"   {rater:<12} n={len(pairs):<3} rho={rho:+.3f}")
    if per_rater:
        print(f"   {'mean':<12} n={len(per_rater):<3} rho={np.mean(per_rater):+.3f}")

    # ---- 2. does compatibility hold as novelty rises ----
    print("\n2. Ratings across the dial (Gold Digger arm)")
    print(f"   {'distance':<10}{'obvious':>9}{'compat':>9}{'inspire':>9}{'n':>5}")
    for d in listening.DISTANCES:
        o, n = mean(rows, "obviousness", strategy="golddigger", distance=d)
        c, _ = mean(rows, "compatibility", strategy="golddigger", distance=d)
        i, _ = mean(rows, "inspiration", strategy="golddigger", distance=d)
        print(f"   {d:<10}{o:>9.2f}{c:>9.2f}{i:>9.2f}{n:>5}")

    # ---- 3. the product question ----
    print("\n3. Gold Digger against the blind baselines")
    print(f"   {'arm':<12}{'obvious':>9}{'compat':>9}{'inspire':>9}{'discover':>10}{'direction':>11}{'n':>5}")
    for arm in listening.ARMS:
        vals = [mean(rows, f, strategy=arm)[0] for f in
                ("obviousness", "compatibility", "inspiration", "discovery", "direction_change")]
        n = mean(rows, "inspiration", strategy=arm)[1]
        print(f"   {arm:<12}" + "".join(f"{v:>9.2f}" if f < 3 else f"{v:>10.2f}"
                                        for f, v in enumerate(vals[:4]))
              + f"{vals[4]:>11.2f}{n:>5}")

    gd, _ = mean(rows, "inspiration", strategy="golddigger")
    best_base = max(((a, mean(rows, "inspiration", strategy=a)[0])
                     for a in listening.ARMS if a != "golddigger"),
                    key=lambda kv: (kv[1] if kv[1] == kv[1] else -1))
    print(f"\n   inspiration: golddigger {gd:.2f} vs best baseline "
          f"{best_base[0]} {best_base[1]:.2f}  ->  {gd - best_base[1]:+.2f}")

    notes = [(r["strategy"], r["note"]) for r in rows if r["note"]]
    if notes:
        print(f"\n4. What people wrote ({len(notes)})")
        for arm, note in notes[:15]:
            print(f"   [{arm}] {note.strip()[:100]}")

    print("\nRead this as formative, not conclusive. A handful of raters can "
          "falsify an obvious failure;\nit cannot validate the product. Every "
          "figure above carries its own n for that reason.")


if __name__ == "__main__":
    main()
