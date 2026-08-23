"""What the filename itself claims, and how sure that claim is.

A sample library names its own tempo and key more often than not, and that label
is a human's statement rather than an estimate -- free, exact, and available
before a single sample is decoded. It is also the only source that survives when
the audio tools have nothing to say: beat tracking returns no tempo at all on
short one-shots and loops, which is most of a library.

Everything here reports a certainty alongside its answer, because the evidence
genuinely differs in strength. "126bpm" is a statement. A bare "93" sitting among
a catalogue number and a take number is an inference from context.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import config

_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# 126bpm / 126 bpm / 126_BPM -- the number carries an explicit unit
_BPM_AFTER = re.compile(r"(?<!\d)(\d{2,3})\s*[-_]?\s*bpm", re.I)
# BPM120 / bpm_095 -- the same statement written the other way round
_BPM_BEFORE = re.compile(r"bpm\s*[-_]?\s*(\d{2,3})(?!\d)", re.I)
# bare candidate: any plausible number not glued to another number
_BPM_BARE = re.compile(r"(?<![\d.])(\d{2,3})(?![\d.])")


def parse_bpm(name: str) -> tuple[float | None, float]:
    """-> (bpm, certainty). (None, 0.0) when the name says nothing usable.

    An explicit unit outranks a bare number, and a bare number is only taken
    when it is the single plausible candidate in the name -- "Kit_90_120_beat"
    names two tempos and therefore names none.

    Read off the stem, never the whole path: the extension's dot would end a
    trailing number's boundary, and "Loop_110.wav" is how a library most often
    writes a tempo down.
    """
    stem = Path(name).stem
    explicit = {int(v) for v in _BPM_AFTER.findall(stem) + _BPM_BEFORE.findall(stem)
                if config.BPM_MIN <= int(v) <= config.BPM_MAX}
    if len(explicit) == 1:
        return float(explicit.pop()), config.FILENAME_BPM_EXPLICIT

    bare = {int(m.group(1)) for m in _BPM_BARE.finditer(stem)
            if config.BPM_MIN <= int(m.group(1)) <= config.BPM_MAX}
    if len(bare) == 1:
        return float(bare.pop()), config.FILENAME_BPM_BARE

    return None, 0.0


# ---------------------------------------------------------------- fusion

def resolve(audio_value, audio_confidence, name_value, name_confidence):
    """-> (value, source, confidence). source is "audio", "filename", or None.

    Whichever side is more sure wins, which follows the rule the role
    classifier already applies -- a filename is a human's own label and outranks
    a model that is guessing. The difference is that here both sides carry a
    number, so the precedence is measured rather than assumed, and a genuinely
    confident measurement still beats a tempo inferred from a bare number.

    Ties go to the filename: a person wrote it down.
    """
    have_audio = audio_value is not None
    have_name = name_value is not None
    if not have_audio and not have_name:
        return None, None, 0.0
    if not have_name:
        return audio_value, "audio", audio_confidence
    if not have_audio or name_confidence >= audio_confidence:
        return name_value, "filename", name_confidence
    return audio_value, "audio", audio_confidence


# ---------------------------------------------------------------- vocabulary

_WORD = re.compile(r"[A-Za-z]{2,}|808")


def words_in(name: str) -> set[str]:
    """The distinct lowercase words in one filename.

    A set, not a list: a word is evidence about the file, and saying "dusty"
    twice in one name does not make the file twice as dusty.
    """
    return {w.lower() for w in _WORD.findall(Path(name).stem)}


def discover_vocabulary(paths, min_files: int = None) -> dict[str, int]:
    """-> {word: how many files contain it}, for words that recur.

    No fixed list can keep up with how libraries are named -- Clav, Wurli,
    Dusty, a pack name, a producer's initials -- so the vocabulary is read off
    the corpus instead of enumerated. The threshold is what separates a facet
    from an accident: a token appearing once is a catalogue number, the same
    token across forty files is how this library says something.

    Corpus-relative by construction, which is the same reason novelty here is a
    percentile rather than a distance.
    """
    min_files = config.VOCAB_MIN_FILES if min_files is None else min_files
    counts: dict[str, int] = {}
    for path in paths:
        for word in words_in(path):
            counts[word] = counts.get(word, 0) + 1
    return {w: n for w, n in sorted(counts.items(), key=lambda kv: -kv[1])
            if n >= min_files}


# ---------------------------------------------------------------- key

# letter, optional accidental, optional quality. Only the words are case-folded:
# a blanket flag would let the flat marker "b" match a capital B and read "CB"
# -- an abbreviation, not C-flat -- as a key.
_KEY = re.compile(
    r"(?<![A-Za-z])([A-Ga-g])"
    r"\s*(#|♯|(?i:sharp)|b|♭|(?i:flat))?"
    r"\s*[-_]?\s*"
    r"((?i:maj(?:or)?|min(?:or)?)|m|M)?"
    r"(?![A-Za-z])"
)
# "24Bit Samples" would otherwise read as B-flat
_BIT_DEPTH = re.compile(r"\d+\s*bit", re.I)


def _mode(quality: str | None) -> bool | None:
    """maj/major/M -> True, min/minor/m -> False, absent -> None."""
    if not quality:
        return None
    low = quality.lower()
    if low.startswith("maj"):
        return True
    if low.startswith("min"):
        return False
    return quality == "M"          # a lone letter: case is the whole signal


def parse_key(name: str) -> tuple[int | None, bool | None, float]:
    """-> (tonic_pc, is_major, certainty). is_major is None when only a root is named.

    Two names for the same key are one answer; two different keys are none. A
    file called "Cm_to_Gm" is a transition and belongs to neither, and a wrong
    tonic here would feed the harmony term as though it were measured.
    """
    stem = _BIT_DEPTH.sub(" ", Path(name).stem)
    found = []
    for letter, accidental, quality in _KEY.findall(stem):
        pc = _PC[letter.upper()]
        acc = accidental.lower()
        if acc in ("#", "♯", "sharp"):
            pc += 1
        elif acc in ("b", "♭", "flat"):
            pc -= 1
        # a bare lowercase letter is a syllable far more often than a key
        elif not quality and not letter.isupper():
            continue
        found.append((pc % 12, _mode(quality), bool(quality)))

    if len({(pc, mode) for pc, mode, _ in found}) != 1:
        return None, None, 0.0
    pc, mode, qualified = found[0]
    return pc, mode, (config.FILENAME_KEY_QUALIFIED if qualified
                      else config.FILENAME_KEY_BARE)
