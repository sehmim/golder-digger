"""Tempo-synced audition.

The reason this exists is that a candidate heard at the wrong tempo gets judged
on the mismatch rather than the music. So the tests care about two things: that
the stretch lands on the session tempo, and that nothing secretly improves the
audio in ways that would flatter the scoring.
"""
import numpy as np
import pytest

from goldigger import audition, config


def tone(freq=220.0, seconds=1.0, sr=22050):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), sr


# ---------------------------------------------------------------- rate choice

def test_same_tempo_needs_no_stretch():
    rate, eff = audition.stretch_rate(120, 120)
    assert rate == pytest.approx(1.0) and eff == pytest.approx(120)


def test_plain_mismatch_stretches_to_target():
    rate, eff = audition.stretch_rate(90, 120)
    assert rate == pytest.approx(120 / 90) and eff == pytest.approx(120)


def test_double_time_is_left_alone():
    """174 against 87 already fits -- its beats land on the eighths."""
    rate, _ = audition.stretch_rate(174, 87)
    assert rate == pytest.approx(1.0)


def test_half_time_is_left_alone():
    rate, _ = audition.stretch_rate(70, 140)
    assert rate == pytest.approx(1.0)


def test_ratio_aware_choice_beats_the_naive_one():
    """Naive would stretch 160->85 by 0.53; the metric answer is ~1.06."""
    rate, _ = audition.stretch_rate(160, 85)
    assert 0.9 < rate < 1.2


def test_absurd_stretch_is_refused_rather_than_mangled():
    rate, eff = audition.stretch_rate(30, 200)
    assert rate == pytest.approx(1.0)
    assert eff == pytest.approx(30)


def test_missing_tempo_is_not_an_error():
    assert audition.stretch_rate(None, 120)[0] == 1.0
    assert audition.stretch_rate(120, None)[0] == 1.0
    assert audition.stretch_rate(0, 120)[0] == 1.0


# ---------------------------------------------------------------- stretching

def test_stretching_changes_duration_by_the_rate():
    y, sr = tone(seconds=2.0)
    out = audition.time_stretch(y, 2.0)
    assert len(out) == pytest.approx(len(y) / 2, rel=0.05)


def test_stretching_does_not_change_pitch():
    """A phase vocoder must preserve pitch -- transposing candidates into key
    would make the harmony score look better than the scoring earned."""
    import librosa
    y, sr = tone(freq=440.0, seconds=1.5)
    out = audition.time_stretch(y, 1.5)
    before = librosa.feature.spectral_centroid(y=y, sr=sr).mean()
    after = librosa.feature.spectral_centroid(y=out, sr=sr).mean()
    assert after == pytest.approx(before, rel=0.12)


def test_rate_of_one_returns_the_input_untouched():
    y, _ = tone()
    assert audition.time_stretch(y, 1.0) is y


# ---------------------------------------------------------------- mixing

def test_short_loop_is_tiled_under_a_longer_context():
    short, _ = tone(seconds=0.5)
    long, _ = tone(seconds=2.0)
    out = audition.mix(long, short)
    assert len(out) == len(long)
    assert np.abs(out[-1000:]).max() > 0.01, "the loop fell silent under the context"


def test_mix_never_clips():
    loud = np.ones(1000, dtype=np.float32) * 0.95
    out = audition.mix(loud, loud)
    assert np.abs(out).max() <= audition.PEAK + 1e-6


def test_mix_contains_both_parts():
    a, sr = tone(freq=220.0, seconds=1.0)
    b, _ = tone(freq=880.0, seconds=1.0)
    out = audition.mix(a, b)
    import librosa
    spec = np.abs(librosa.stft(out, n_fft=2048)).mean(axis=1)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    for f in (220.0, 880.0):
        band = spec[(freqs > f * 0.9) & (freqs < f * 1.1)]
        assert band.max() > spec.mean(), f"{f} Hz missing from the mix"


def test_empty_input_does_not_crash():
    assert len(audition.mix(np.zeros(0), np.zeros(0))) == 0


# ---------------------------------------------------------------- render meta

def test_render_reports_what_it_did(tmp_path):
    import soundfile as sf
    y, sr = tone(seconds=1.0)
    p = tmp_path / "loop.wav"
    sf.write(p, y, sr)
    row = {"path": str(p), "t_start": 0.0, "t_end": 1.0, "bpm": 90.0}
    _, _, meta = audition.render_chunk(row, 120.0)
    assert meta["stretched"] is True
    assert meta["pitch_shifted"] is False
    assert meta["effective_bpm"] == pytest.approx(120.0, rel=0.01)


def test_chunk_render_is_cached_by_audio_and_target(tmp_path, monkeypatch):
    path = tmp_path / "loop.wav"
    path.write_bytes(b"cache-key")
    row = {"path": str(path), "t_start": 0.0, "t_end": 1.0, "bpm": 90.0}
    calls = 0

    def fake_load(*_args):
        nonlocal calls
        calls += 1
        return np.ones(100, dtype=np.float32), 22050

    audition.clear_caches()
    monkeypatch.setattr(audition, "load_chunk", fake_load)
    monkeypatch.setattr(audition, "time_stretch", lambda y, _rate: y)
    audition.render_chunk(row, 120.0, sr=22050)
    audition.render_chunk(row, 120.0, sr=22050)
    audition.render_chunk(row, 100.0, sr=22050)
    assert calls == 2
    path.write_bytes(b"cache-key-with-new-contents")
    audition.render_chunk(row, 120.0, sr=22050)
    assert calls == 3, "replacing the source file must invalidate its cached audio"
    audition.clear_caches()


def test_context_bed_is_built_once(tmp_path, monkeypatch):
    paths = [tmp_path / "a.wav", tmp_path / "b.wav"]
    for path in paths:
        path.write_bytes(b"context-cache")
    rows = [
        {"path": str(path), "t_start": 0.0, "t_end": 1.0, "bpm": 120.0}
        for path in paths
    ]
    calls = 0

    def fake_load(*_args):
        nonlocal calls
        calls += 1
        return np.ones(100, dtype=np.float32), 22050

    audition.clear_caches()
    monkeypatch.setattr(audition, "load_chunk", fake_load)
    monkeypatch.setattr(audition, "time_stretch", lambda y, _rate: y)
    first, _ = audition.render_context(rows, 120.0, sr=22050)
    second, _ = audition.render_context(rows, 120.0, sr=22050)
    assert calls == len(rows)
    assert first is second
    audition.clear_caches()


# ---------------------------------------------------------------- waveform peaks

def test_peaks_returns_exactly_the_buckets_asked_for():
    """The drawing code indexes by bucket, so a short file must still fill them.

    A file whose length does not divide evenly is padded, not truncated -- a
    truncated last bucket would draw a waveform that ends before the audio does.
    """
    assert len(audition.peaks(np.ones(7, dtype=np.float32), 4)) == 4
    assert len(audition.peaks(np.ones(4000, dtype=np.float32), 200)) == 200


def test_peaks_keeps_both_signs():
    """Min and max, not one absolute amplitude: the asymmetry is the shape.

    A kick drawn from absolute peaks alone looks like a symmetrical blob, which
    is precisely the visual cue that tells one sample from another in a list.
    """
    y = np.concatenate([np.full(10, 0.9, np.float32), np.full(10, -0.2, np.float32)])

    assert audition.peaks(y, 2) == [[0.9, 0.9], [-0.2, -0.2]]


def test_peaks_of_nothing_is_flat_rather_than_an_error():
    """An empty render is a silent chunk, not a failure -- draw a flat line."""
    assert audition.peaks(np.zeros(0, dtype=np.float32), 3) == [[0.0, 0.0]] * 3
