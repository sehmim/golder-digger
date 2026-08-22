"""Key estimation on synthesized cadences. A bare scale is genuinely
major/minor ambiguous, so tests use tonic-establishing progressions."""
import numpy as np
import librosa
from goldigger.features import chroma_vector, estimate_key
from goldigger.config import PITCH_NAMES, KS_MAJOR, KS_MINOR

SR = 22050


def _chord(midis, dur=0.6):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    y = sum(np.sin(2 * np.pi * librosa.midi_to_hz(m) * t) for m in midis)
    return (y / len(midis) * np.hanning(len(t))).astype(np.float32)


def _prog(chords):
    return np.concatenate([_chord(c) for c in chords])


CASES = {
    # I - IV - V - I in C
    "C major": ([[60,64,67],[65,69,72],[67,71,74],[60,64,67],[60,64,67]], 0, 1),
    # i - iv - V - i in A
    "A minor": ([[57,60,64],[62,65,69],[64,68,71],[57,60,64],[57,60,64]], 9, 0),
    # I - IV - V - I in F#
    "F# major": ([[66,70,73],[71,75,78],[73,77,80],[66,70,73],[66,70,73]], 6, 1),
}


def test_ideal_profiles_roundtrip():
    for prof, et, em in [(KS_MAJOR, 0, 1), (KS_MINOR, 9, 0)]:
        v = np.roll(np.array(prof, dtype=np.float32), et)
        pc, maj, conf = estimate_key(v / v.sum())
        # identity only: a bare KS profile is mildly peaked, so its tonalness --
        # and therefore its confidence -- is low by design
        assert (pc, maj) == (et, em)
        assert conf > 0.0


def test_cadences():
    for name, (chords, et, em) in CASES.items():
        pc, maj, conf = estimate_key(chroma_vector(_prog(chords), SR))
        assert (pc, maj) == (et, em), (
            f"{name}: got {PITCH_NAMES[pc]} {'maj' if maj else 'min'}")
        assert conf > 0.1, f"{name}: confidence {conf:.3f} too low"


def test_noise_is_low_confidence():
    rng = np.random.default_rng(0)
    _, _, conf = estimate_key(chroma_vector(rng.standard_normal(SR * 2).astype(np.float32) * 0.1, SR))
    assert conf < 0.25, f"noise scored confidence {conf:.3f}"
