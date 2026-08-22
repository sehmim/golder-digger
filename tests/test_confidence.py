"""Confidence scoring: every estimated value carries an honest certainty.

The problem these solve: librosa happily returns *a* key and *a* tempo for a
hi-hat one-shot. The tools do not know their answer is meaningless for
percussive, non-tonal material -- so the confidence has to say it for them.
"""
import numpy as np
import pytest

from goldigger import features

SR = 22050


def _sine(freq=220.0, dur=2.0, sr=SR):
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def _clicks(dur=2.0, sr=SR, every=0.25):
    """A click train: broadband transients, no sustained pitch."""
    y = np.zeros(int(sr * dur), dtype=np.float32)
    rng = np.random.default_rng(0)
    n = int(sr * 0.01)
    for i in range(0, len(y) - n, int(sr * every)):
        burst = rng.standard_normal(n).astype(np.float32)
        y[i:i + n] += burst * np.hanning(n).astype(np.float32)
    return y


# ---------------------------------------------------------------- tonalness

def test_hpss_tonalness_separates_tonal_from_percussive():
    """A sustained tone is nearly all harmonic energy; a click train is not.

    This is the gate that stops a hi-hat from claiming a confident key.
    """
    tonal = features.hpss_tonalness(_sine())
    percussive = features.hpss_tonalness(_clicks())
    assert tonal > 0.8, f"a pure sine measured only {tonal:.3f} tonal"
    assert percussive < 0.35, f"a click train measured {percussive:.3f} tonal"
    assert tonal > percussive


# ---------------------------------------------------------------- key gate

def test_key_confidence_is_gated_by_tonalness():
    """A hi-hat still correlates best with *some* key. The gate is what says so.

    Chroma peakedness alone cannot catch this: a filtered noise burst can have
    a perfectly peaked chroma by chance. Harmonic-energy share can.
    """
    from goldigger import config
    chroma = np.array(config.KS_MAJOR, dtype=np.float32)
    chroma = chroma / chroma.sum()

    _, _, ungated = features.estimate_key(chroma)
    _, _, tonal = features.estimate_key(chroma, gate=0.95)
    _, _, percussive = features.estimate_key(chroma, gate=0.05)

    assert percussive < tonal, "the gate did not discriminate"
    assert percussive < ungated * 0.2, (
        f"percussive material kept {percussive:.3f} of its {ungated:.3f} confidence")
    assert 0.0 <= percussive <= 1.0


def test_gate_changes_confidence_but_never_the_key_guess():
    """Tonalness says how much to trust the answer, not what the answer is."""
    from goldigger import config
    chroma = np.roll(np.array(config.KS_MINOR, dtype=np.float32), 9)
    chroma = chroma / chroma.sum()

    bare = features.estimate_key(chroma)[:2]
    for gate in (0.02, 0.5, 1.0):
        assert features.estimate_key(chroma, gate=gate)[:2] == bare


# ---------------------------------------------------------------- tempo

def _pulse(bpm=120.0, dur=8.0, sr=SR):
    """A metronome: unambiguously periodic onsets."""
    y = np.zeros(int(sr * dur), dtype=np.float32)
    n = int(sr * 0.01)
    step = int(sr * 60.0 / bpm)
    for i in range(0, len(y) - n, step):
        y[i:i + n] += np.hanning(n).astype(np.float32)
    return y


def test_tempo_confidence_is_high_for_a_steady_pulse():
    """Autocorrelation of the onset envelope at the detected tempo's lag."""
    assert features.tempo_confidence(_pulse(120.0), SR, 120.0) > 0.5


def test_tempo_confidence_is_low_for_unpitched_noise():
    rng = np.random.default_rng(0)
    y = rng.standard_normal(SR * 8).astype(np.float32) * 0.1
    assert features.tempo_confidence(y, SR, 120.0) < 0.35


def test_tempo_confidence_is_zero_when_bpm_is_unknown():
    """No tempo means no confidence in one -- not a fabricated number."""
    assert features.tempo_confidence(_pulse(), SR, None) == 0.0
    assert features.tempo_confidence(_pulse(), SR, 0.0) == 0.0


# ---------------------------------------------------------------- spectral

def test_stability_falls_as_frames_disagree():
    """100/(1+CV) in the reference; 0-1 here to match key_confidence's scale."""
    assert features.stability(1000.0, 0.0) == pytest.approx(1.0)
    assert features.stability(1000.0, 1000.0) == pytest.approx(0.5)
    assert features.stability(1000.0, 100.0) > features.stability(1000.0, 500.0)
    assert 0.0 <= features.stability(0.0, 0.0) <= 1.0


def test_spectral_stats_carry_a_mean_and_a_confidence():
    stats = features.spectral_stats(_sine(), SR)
    assert set(stats) == {"centroid", "rolloff", "bandwidth", "flatness", "rms", "zcr"}
    for name, v in stats.items():
        assert set(v) == {"mean", "confidence"}, name
        assert 0.0 <= v["confidence"] <= 1.0, name


def test_a_steady_tone_is_more_spectrally_stable_than_noise_bursts():
    """The whole point of the stability score: agreeing frames earn trust."""
    steady = features.spectral_stats(_sine(), SR)["centroid"]["confidence"]
    bursty = features.spectral_stats(_clicks(), SR)["centroid"]["confidence"]
    assert steady > bursty, f"steady {steady:.3f} !> bursty {bursty:.3f}"
