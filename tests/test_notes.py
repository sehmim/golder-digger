"""Which pitch classes actually sound in a chunk, and for how much of it.

The key label alone is lossy: C minor and Eb major are different labels over an
identical set of notes, so two loops that would layer perfectly look unrelated.
Note content is the thing that actually decides whether they fit.

Octave is deliberately discarded -- pitch class is what shared-note compatibility
turns on.
"""
import numpy as np
import pytest
import librosa

from goldigger import config, features

SR = 22050


def _tone(midi, dur, harmonics=6, sr=SR):
    """A note with overtones, so the tests face real harmonic bleed."""
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    f = librosa.midi_to_hz(midi)
    y = sum((1.0 / h) * np.sin(2 * np.pi * f * h * t) for h in range(1, harmonics + 1))
    return (y / np.abs(y).max()).astype(np.float32)


def _chord(midis, dur):
    return (sum(_tone(m, dur) for m in midis) / len(midis)).astype(np.float32)


def _names(presence):
    return set(features.notes_from_presence(presence))


def test_a_note_that_sounds_for_only_part_of_the_loop_is_still_found():
    """The whole reason this exists.

    Cm for 3s then Fm for 1s. A median over the chunk averages the Fm away
    entirely and reports only C/D#/G -- the second chord vanishes.
    """
    loop = np.concatenate([_chord([48, 51, 55], 3.0), _chord([53, 56, 60], 1.0)])
    found = _names(features.note_presence(loop, SR))
    assert found == {"C", "D#", "F", "G", "G#"}, found


def test_overtones_do_not_register_as_played_notes():
    """A sawtooth C is one note, not a C major triad.

    Its 3rd harmonic lands on G and its 5th on E; both must stay below the bar.
    """
    assert _names(features.note_presence(_tone(48, 2.0))) == {"C"}


def test_two_notes_actually_played_both_register():
    y = (_tone(48, 2.0) + _tone(55, 2.0)).astype(np.float32)
    assert _names(features.note_presence(y)) == {"C", "G"}


def test_silence_does_not_dilute_presence():
    """Trailing silence is not a passage where the notes stopped being played."""
    chord = _chord([48, 51, 55], 2.0)
    padded = np.concatenate([chord, np.zeros(SR * 2, dtype=np.float32)])
    assert _names(features.note_presence(padded)) == _names(features.note_presence(chord))


def test_presence_is_a_bounded_fraction_per_pitch_class():
    p = features.note_presence(_chord([48, 51, 55], 2.0), SR)
    assert p.shape == (12,)
    assert np.all((p >= 0.0) & (p <= 1.0))


def test_a_sustained_note_outranks_a_passing_one():
    """Presence is a weight, not a flag -- 3s of C must beat 1s of F."""
    loop = np.concatenate([_chord([48, 51, 55], 3.0), _chord([53, 56, 60], 1.0)])
    p = features.note_presence(loop, SR)
    assert p[config.PITCH_NAMES.index("C")] > p[config.PITCH_NAMES.index("F")]


def test_silent_audio_yields_no_notes():
    p = features.note_presence(np.zeros(SR, dtype=np.float32), SR)
    assert p.sum() == 0.0
    assert features.notes_from_presence(p) == []


# ---------------------------------------------------------------- persistence

@pytest.fixture
def ingested(tmp_path):
    import soundfile as sf
    from goldigger import db, ingest
    root = tmp_path / "audio"
    root.mkdir()
    rng = np.random.default_rng(0)
    for i in range(3):
        sf.write(root / f"loop_{i}.wav", rng.standard_normal(SR * 3) * 0.05, SR)
    conn = db.connect(tmp_path / "t.db")
    db.init(conn)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    return conn


def test_ingest_stores_presence_and_the_derived_note_set(ingested):
    """Mock mode has to exercise this path too, or it proves nothing."""
    import json
    from goldigger import db as _db
    rows = ingested.execute("SELECT note_presence, notes FROM chunks").fetchall()
    assert rows
    for r in rows:
        presence = _db.from_blob(r["note_presence"], 12)
        assert presence.shape == (12,)
        assert np.all((presence >= 0.0) & (presence <= 1.0))

        notes = json.loads(r["notes"])
        assert set(notes) <= set(config.PITCH_NAMES)
        # the stored set must be the one the stored vector implies
        assert notes == features.notes_from_presence(presence)
