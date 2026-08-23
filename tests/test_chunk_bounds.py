"""A chunk may not describe audio the file does not contain.

`377cb3116e44:2` spanned 22.59-31.06s of a 21.85s file and reached the desktop as
"500 could not render" -- soundfile raising from a seek past the end. The grid
that produced it was mock's, which invents 16-64 beats without ever consulting
the file's length, but a real tracker on a truncated file would do the same.
"""
import numpy as np
import pytest
import soundfile as sf

from goldigger import audition, features


def grid(bpm=85.0, beats=44, bpb=4):
    beats = np.arange(beats) * (60.0 / bpm)
    return {"beats": beats, "downbeats": beats[::bpb], "bpm": bpm, "beats_per_bar": bpb}


def test_no_span_starts_after_the_audio_ends():
    """The reported case: a 31s beat grid over a 21.85s file."""
    spans = features.chunk_boundaries(21.85, grid())

    assert spans, "clamping must not throw the file away"
    assert all(start < 21.85 for start, _ in spans)


def test_no_span_overruns_the_end():
    spans = features.chunk_boundaries(21.85, grid())

    assert max(end for _, end in spans) <= 21.85


def test_a_grid_inside_the_file_is_untouched():
    """The clamp must not re-cut a file whose downbeats fit."""
    duration = 60.0
    assert features.chunk_boundaries(duration, grid()) == \
        features.chunk_boundaries(duration, grid())
    assert all(e <= duration for _, e in features.chunk_boundaries(duration, grid()))


@pytest.fixture
def short_file(tmp_path):
    path = tmp_path / "short.wav"
    t = np.linspace(0, 3.0, int(3.0 * 22050), endpoint=False)
    sf.write(path, 0.2 * np.sin(2 * np.pi * 220 * t), 22050)
    return str(path)


def test_a_span_that_overruns_is_trimmed_not_refused(short_file):
    """Playable audio, just less of it than the row claimed."""
    y, sr = audition.load_chunk(short_file, 2.0, 9.0)

    assert 0 < len(y) <= sr * 1.01


def test_a_span_that_starts_past_the_end_is_named(short_file):
    with pytest.raises(audition.ChunkOutsideAudio) as caught:
        audition.load_chunk(short_file, 22.59, 31.06)

    assert "short.wav" in str(caught.value)
    assert caught.value.t_start == 22.59
    assert round(caught.value.duration, 1) == 3.0


def test_one_unplayable_context_chunk_does_not_kill_the_bed(short_file, tmp_path):
    """Losing a chunk of the bed is survivable; losing every preview is not."""
    audition.clear_caches()
    rows = [{"path": short_file, "t_start": 0.0, "t_end": 2.0, "bpm": 120.0},
            {"path": short_file, "t_start": 90.0, "t_end": 98.0, "bpm": 120.0}]

    bed, sr = audition.render_context(rows, None)

    assert len(bed) > 0
