"""Parse BPM and key out of sample filenames, as evaluation labels.

Roland and similar libraries name files like EP1_Loop01_76_Cm.wav or
11 SYNTH Fm 125bpm.wav. That is free ground truth for exactly the two fields
the extractors are least trusted on -- so it can be used to score them without
hand-labelling anything.

The parsing itself lives in goldigger.filename, which the shipped package needs
at ingest time; scripts/ is not part of the installed package and cannot be the
home for logic the library depends on. What stays here is the *evaluation* view
of it: a label or nothing, with the certainties dropped. A measuring instrument
that reported its own confidence would invite weighting the answer key by it.

Deliberately conservative: a token only counts when it is unambiguous. A file
that yields no label is reported as such rather than guessed at, because a
wrong label is worse than a missing one when the point is measuring accuracy.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from goldigger.filename import parse_bpm, parse_key      # noqa: E402

BPM_MIN, BPM_MAX = 40, 220


def bpm_from_name(name: str) -> float | None:
    """Only accept an unambiguous tempo: exactly one plausible candidate."""
    return parse_bpm(name)[0]


def key_from_name(name: str) -> tuple[int, bool | None] | None:
    """-> (tonic_pc, is_major|None). None when absent or ambiguous."""
    pc, is_major, _ = parse_key(name)
    return None if pc is None else (pc, is_major)


def truth_for(path) -> dict:
    name = Path(path).stem
    key = key_from_name(name)
    return {"bpm": bpm_from_name(name),
            "tonic_pc": key[0] if key else None,
            "is_major": key[1] if key else None}
