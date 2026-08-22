"""Score whatever is in the database against the labels in the filenames.

Run it on mock features to see what chance looks like, then again after a real
ingest. The gap between the two runs is the measurement; either number alone
says very little.

Tempo is scored ratio-aware, because 87 against 174 is a match by the same
argument scoring.tempo_score already makes. Key is scored twice -- pitch class
alone, and pitch class with mode -- since a library labels the root far more
often than the quality.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldigger import config, db                      # noqa: E402
from scripts.filename_truth import truth_for          # noqa: E402

RATIOS = config.TEMPO_RATIOS
TOL = 0.02          # 2% -- tighter than TEMPO_TOL, this is accuracy not compatibility


def tempo_hit(est, true) -> tuple[bool, bool]:
    """-> (exact, ratio_aware)."""
    if est is None or true is None or np.isnan(est):
        return False, False
    exact = abs(est - true) / true <= TOL
    ratio = any(abs(est * r - true) / true <= TOL for r in RATIOS)
    return exact, ratio


def main():
    conn = db.connect()
    rows = conn.execute(
        "SELECT path, bpm, tonic_pc, is_major, key_confidence FROM chunks "
        "WHERE chunk_index = 0").fetchall()

    t_n = t_exact = t_ratio = 0
    k_n = k_pc = k_full = 0
    conf_right, conf_wrong = [], []

    for r in rows:
        truth = truth_for(r["path"])
        if truth["bpm"] is not None:
            t_n += 1
            e, ra = tempo_hit(r["bpm"], truth["bpm"])
            t_exact += e
            t_ratio += ra
        if truth["tonic_pc"] is not None:
            k_n += 1
            right = r["tonic_pc"] == truth["tonic_pc"]
            k_pc += right
            if truth["is_major"] is not None:
                k_full += right and bool(r["is_major"]) == truth["is_major"]
            (conf_right if right else conf_wrong).append(r["key_confidence"] or 0.0)

    # config.MOCK reflects THIS process, not the ingest that wrote these rows --
    # printing it as if it described the data has already misreported one run.
    print(f"corpus: {len(rows)} files   (feature source is whatever "
          f"GOLDDIGGER_MOCK was set to at ingest time, not now)\n")
    print(f"tempo   labelled={t_n}")
    if t_n:
        print(f"  exact  (±{TOL:.0%})      {t_exact:5d}  {100*t_exact/t_n:5.1f}%   (chance ≈ 3%)")
        print(f"  ratio-aware          {t_ratio:5d}  {100*t_ratio/t_n:5.1f}%   (chance ≈ 12%)")
    print(f"\nkey     labelled={k_n}")
    if k_n:
        print(f"  pitch class          {k_pc:5d}  {100*k_pc/k_n:5.1f}%   (chance ≈ 8.3%)")
        print(f"  pitch class + mode   {k_full:5d}  {100*k_full/k_n:5.1f}%   (chance ≈ 4.2%)")
    if conf_right and conf_wrong:
        cr, cw = np.mean(conf_right), np.mean(conf_wrong)
        print(f"\nkey_confidence   correct={cr:.4f}   wrong={cw:.4f}   separation={cr-cw:+.4f}")
        print("  (a confidence that means anything should be higher when the key is right)")


if __name__ == "__main__":
    main()
