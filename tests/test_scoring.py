import numpy as np
import pytest

from goldigger import config, scoring


def test_geometric_mean_cannot_mask_a_bad_component():
    eps = 1e-3
    H, R, P = 0.9, 0.9, 0.02
    fit = np.exp((np.log(H + eps) + np.log(R + eps) + np.log(P + eps)) / 3)
    # 0.9 collapsing to ~0.25 is the point; an arithmetic mean would give 0.61
    assert fit < 0.30, f"one catastrophic component was masked: {fit:.3f}"


@pytest.mark.parametrize("bpm_x,bpm_ctx", [(174, 87), (87, 174), (140, 140), (90, 60)])
def test_tempo_ratios_are_not_punished(bpm_x, bpm_ctx):
    assert scoring.tempo_score(bpm_x, bpm_ctx) >= 0.9


def test_unrelated_tempo_is_punished():
    assert scoring.tempo_score(101, 140) < 0.2


def test_missing_tempo_is_neutral_not_zero():
    assert scoring.tempo_score(None, 120) == config.NEUTRAL


def test_cof_proximity():
    assert scoring.cof_proximity(0, 0) == 1.0          # unison
    assert scoring.cof_proximity(0, 7) > 0.8           # C -> G, one fifth
    assert scoring.cof_proximity(0, 6) == 0.0          # tritone
    assert scoring.cof_proximity(-1, 0) == config.NEUTRAL  # unknown key


def test_unconfident_tempo_softens_toward_neutral():
    """The rhythm term now gets the soft-evidence treatment harmony always had:
    a beat tracker returns *a* number for steady noise, and the stored
    confidence is what separates that from a metronome."""
    corpus = scoring.Corpus([{"chunk_id": "confident"}, {"chunk_id": "unsure"}])
    corpus.bpm[:] = 101.0                       # both wrong against 140
    corpus.tconf = np.array([1.0, 0.0], dtype=np.float32)
    ctx = {"chroma": np.full(12, 1 / 12, dtype=np.float32), "tonic": -1,
           "kconf": 0.0, "bpm": 140.0, "tconf": 1.0, "roles": set()}

    R = scoring.fit_all(corpus, ctx)["R"]

    assert R[0] < 0.2, "a confident wrong tempo must still be punished"
    assert R[1] == pytest.approx(config.NEUTRAL), \
        "an unconfident tempo is absence of evidence, not a rejection"


def test_role_compat_floors_above_zero():
    # a literal 0 would annihilate the geometric mean
    assert scoring.role_compat("drums", {"drums"}) == config.ROLE_SAME > 0
    assert scoring.role_compat("bass", {"drums"}) == 1.0
    assert scoring.role_compat("vocal", {"melody"}) == config.NEUTRAL  # both want the lead
    assert scoring.role_compat(None, {"drums"}) == config.NEUTRAL
