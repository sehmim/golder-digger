"""Parse BPM and key out of sample filenames.

Roland and similar libraries name files like EP1_Loop01_76_Cm.wav or
11 SYNTH Fm 125bpm.wav. That is free ground truth for exactly the two fields
the extractors are least trusted on -- so it can be used to score them without
hand-labelling anything.

Deliberately conservative: a token only counts when it is unambiguous. A file
that yields no label is reported as such rather than guessed at, because a
wrong label is worse than a missing one when the point is measuring accuracy.
"""
from __future__ import annotations

import re
from pathlib import Path

PITCH = {"c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "f": 5,
         "f#": 6, "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11}

# 76, 126bpm, 120_bpm -- bounded to a musically plausible range
_BPM = re.compile(r"(?<![\d.])(\d{2,3})\s*(?:bpm)?(?![\d.])", re.I)
# Cm, F#maj, Bbm, Bm9, A -- letter, optional accidental, optional quality
_KEY = re.compile(r"(?<![A-Za-z])([A-Ga-g])([#b])?\s*(maj|min|m|M)?(?![A-Za-z])")

BPM_MIN, BPM_MAX = 40, 220


def bpm_from_name(name: str) -> float | None:
    """Only accept an unambiguous tempo: exactly one plausible candidate."""
    explicit = re.findall(r"(\d{2,3})\s*bpm", name, re.I)
    if explicit:
        vals = {int(v) for v in explicit if BPM_MIN <= int(v) <= BPM_MAX}
        return float(vals.pop()) if len(vals) == 1 else None
    vals = {int(m.group(1)) for m in _BPM.finditer(name)
            if BPM_MIN <= int(m.group(1)) <= BPM_MAX}
    return float(vals.pop()) if len(vals) == 1 else None


def key_from_name(name: str) -> tuple[int, bool | None] | None:
    """-> (tonic_pc, is_major|None). None when absent or ambiguous."""
    stem = Path(name).stem
    # strip tokens that would produce phantom key letters (Bb in "24Bit", e in "Loop3e")
    stem = re.sub(r"\d+\s*bit", " ", stem, flags=re.I)
    found = []
    for m in _KEY.finditer(stem):
        letter, acc, qual = m.group(1), m.group(2) or "", m.group(3)
        pc = PITCH.get((letter + acc).lower())
        if pc is None:
            continue
        # a bare capital letter alone is too weak unless it carries a quality or accidental
        if qual is None and not acc and not letter.isupper():
            continue
        major = None
        if qual:
            major = qual.lower() in ("maj", "m") and qual != "m"
            if qual in ("m", "min"):
                major = False
            elif qual.lower() == "maj" or qual == "M":
                major = True
        found.append((pc, major))
    uniq = set(found)
    return found[0] if len(uniq) == 1 else None


def truth_for(path) -> dict:
    name = Path(path).stem
    key = key_from_name(name)
    return {"bpm": bpm_from_name(name),
            "tonic_pc": key[0] if key else None,
            "is_major": key[1] if key else None}
