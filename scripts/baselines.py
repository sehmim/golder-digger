"""Does the compatibility gate earn its complexity, or is this inverse similarity?

The research brief names one baseline as decisive: candidates chosen by walking
progressively *further* out in CLAP space with no compatibility gate at all. If
Gold Digger returns roughly what that returns, the whole Fit apparatus is
decoration.

What this can and cannot establish
----------------------------------
It CANNOT show that one strategy is more inspiring. That needs listeners, and
none of these numbers substitute for them.

It CAN falsify the specific claim that the strategies are interchangeable. Two
selections over the same corpus, at the same target novelty, either overlap or
they do not -- and if they overlap almost completely then the gate changes
nothing and the simpler system wins by default.

Strategies
----------
random      uniform pick, the floor for everything
metadata    highest Fit, novelty ignored -- "just give me compatible material"
nearest     highest CLAP similarity -- what a similarity search returns
inverse     target novelty percentile, NO fit gate, no diversity term
band_nofit  target novelty percentile + diversity, fit gate disabled (ablation)
golddigger  the shipped path: fit gate + novelty band + greedy MMR
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldigger import config, db, ingest, scoring  # noqa: E402
from goldigger.strategies import (  # noqa: E402  re-exported for callers and tests
    STRATEGIES, pick_band_nofit, pick_golddigger, pick_inverse, pick_metadata,
    pick_nearest, pick_random, _eligible,
)

K = 8
DISTANCES = [10, 30, 50, 70, 90]
N_CONTEXTS = 60
SEED = 7


# ---------------------------------------------------------------- strategies


# ---------------------------------------------------------------- metrics

def redundancy(corpus, idx):
    """Mean pairwise CLAP similarity inside the returned set. Lower = more varied."""
    if len(idx) < 2:
        return float("nan")
    v = corpus.clap[idx]
    sim = v @ v.T
    iu = np.triu_indices(len(idx), k=1)
    return float(sim[iu].mean())


def measure(corpus, ctx, idx, fit, nov):
    if not len(idx):
        return None
    idx = np.asarray(idx)
    ctx_roles = ctx["roles"]
    return {
        "fit_mean": float(fit[idx].mean()),
        "fit_min": float(fit[idx].min()),
        "below_floor": float(np.mean(fit[idx] < config.FIT_FLOOR)),
        "novelty_mean": float(nov[idx].mean()),
        "redundancy": redundancy(corpus, idx),
        "role_dup": float(np.mean([corpus.roles[i] in ctx_roles for i in idx])) if ctx_roles else float("nan"),
    }


def jaccard(a, b):
    sa, sb = set(map(int, a)), set(map(int, b))
    return len(sa & sb) / len(sa | sb) if (sa | sb) else float("nan")


# ---------------------------------------------------------------- run

def main():
    conn = db.connect()
    corpus = ingest.load_corpus(conn)
    rng = np.random.default_rng(SEED)

    # contexts: prefer chunks the key estimator was confident about, so the
    # harmony term is actually exercised rather than sitting at NEUTRAL
    order = np.argsort(-corpus.kconf)
    pool = [int(i) for i in order[:400]]
    contexts = list(rng.choice(pool, size=min(N_CONTEXTS, len(pool)), replace=False))

    rows = []
    for n, ci in enumerate(contexts):
        ctx = scoring.build_context(corpus, [corpus.ids[ci]])
        scores = scoring.fit_all(corpus, ctx)
        fit = scores["fit"]
        nov = scoring.novelty_all(corpus, ctx)
        for d in DISTANCES:
            q = d / 100.0
            picks = {}
            for name, fn in STRATEGIES.items():
                picks[name] = fn(corpus, ctx, fit, nov, q, K, np.random.default_rng(SEED + n))
            for name, idx in picks.items():
                m = measure(corpus, ctx, idx, fit, nov)
                if m is None:
                    continue
                rows.append({"context": corpus.ids[ci], "distance": d, "strategy": name,
                             "overlap_with_golddigger": jaccard(idx, picks["golddigger"]), **m})

    out = Path("results/csv/baselines.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ---- aggregate ----
    def agg(field, strategy, dist=None):
        v = [r[field] for r in rows if r["strategy"] == strategy
             and (dist is None or r["distance"] == dist) and not np.isnan(r[field])]
        return float(np.mean(v)) if v else float("nan")

    print(f"contexts={len(contexts)}  k={K}  corpus={len(corpus)}  "
          f"rows={len(rows)}\n")
    hdr = f"{'strategy':<12}{'fit':>8}{'fit_min':>9}{'<floor':>8}{'novelty':>9}{'redund':>8}{'roledup':>9}{'overlap':>9}"
    print(hdr); print("-" * len(hdr))
    for s in STRATEGIES:
        print(f"{s:<12}{agg('fit_mean',s):>8.3f}{agg('fit_min',s):>9.3f}"
              f"{agg('below_floor',s):>8.1%}{agg('novelty_mean',s):>9.3f}"
              f"{agg('redundancy',s):>8.3f}{agg('role_dup',s):>9.1%}"
              f"{agg('overlap_with_golddigger',s):>9.1%}")

    print("\noverlap with golddigger, by DISTANCE (Jaccard of the returned sets)")
    print(f"{'strategy':<12}" + "".join(f"{d:>9}" for d in DISTANCES))
    for s in STRATEGIES:
        if s == "golddigger":
            continue
        print(f"{s:<12}" + "".join(f"{agg('overlap_with_golddigger',s,d):>8.1%} " for d in DISTANCES))

    print("\nfit at each DISTANCE (the cost of asking for novelty)")
    print(f"{'strategy':<12}" + "".join(f"{d:>9}" for d in DISTANCES))
    for s in STRATEGIES:
        print(f"{s:<12}" + "".join(f"{agg('fit_mean',s,d):>9.3f}" for d in DISTANCES))

    summary = {s: {"fit_mean": agg("fit_mean", s), "novelty_mean": agg("novelty_mean", s),
                   "redundancy": agg("redundancy", s), "role_dup": agg("role_dup", s),
                   "overlap_with_golddigger": agg("overlap_with_golddigger", s)}
               for s in STRATEGIES}
    Path("results/baselines-summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {out} and results/baselines-summary.json")


if __name__ == "__main__":
    main()
