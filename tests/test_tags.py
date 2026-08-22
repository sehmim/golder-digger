"""Zero-shot CLAP tagging: a probability over a fixed vocabulary, not a raw
cosine similarity nobody can read.

Softmax at a low temperature turns the similarities for one clip into a
distribution summing to 1, so "62% a kick drum" means something. It also gives
the corpus a role classifier -- until now role came only from filename keywords,
which fail on any library named by catalogue number.
"""
import numpy as np
import pytest

from goldigger import config, features


def test_tag_probabilities_sum_to_one():
    sims = [0.31, 0.28, 0.11, 0.05, -0.02]
    p = features.softmax(sims, config.TAG_TEMPERATURE)
    assert p.sum() == pytest.approx(1.0)
    assert (p > 0).all()


def test_lower_temperature_sharpens_the_distribution():
    """Temperature 0.10 is chosen to make a clear winner actually look like one."""
    sims = [0.31, 0.28, 0.11]
    sharp = features.softmax(sims, 0.10).max()
    flat = features.softmax(sims, 1.0).max()
    assert sharp > flat


def test_softmax_is_shift_invariant():
    """Guards the max-subtraction that keeps exp() from overflowing."""
    a = features.softmax([0.3, 0.2, 0.1], 0.1)
    b = features.softmax([10.3, 10.2, 10.1], 0.1)
    assert np.allclose(a, b)


def test_every_vocab_entry_maps_to_a_known_role_or_none():
    for tag in config.TAG_VOCAB:
        role = config.TAG_TO_ROLE.get(tag)
        assert role is None or role in config.ROLES, f"{tag!r} -> {role!r}"


def test_every_role_is_reachable_from_the_vocabulary():
    """A role no tag can produce is a role CLAP can never infer."""
    reachable = {r for r in config.TAG_TO_ROLE.values() if r}
    assert reachable == set(config.ROLES), f"unreachable: {set(config.ROLES) - reachable}"


def test_role_from_tags_sums_probability_by_role():
    """Three drum tags at 0.25 each beat one pad tag at 0.30.

    Summing by role reads the evidence better than trusting a single top tag,
    which can split its vote across near-synonyms.
    """
    tags = [
        {"tag": "a kick drum", "confidence": 0.25},
        {"tag": "a snare drum", "confidence": 0.25},
        {"tag": "a hi-hat", "confidence": 0.20},
        {"tag": "a synth pad", "confidence": 0.30},
    ]
    assert features.role_from_tags(tags) == "drums"


def test_role_from_tags_abstains_when_no_role_is_convincing():
    """Descriptive tags carry no role, and a thin winner is not evidence."""
    tags = [
        {"tag": "a dark and moody sound", "confidence": 0.60},
        {"tag": "a bright and airy sound", "confidence": 0.35},
        {"tag": "a kick drum", "confidence": 0.05},
    ]
    assert features.role_from_tags(tags) is None


def test_tags_from_sims_returns_top_n_sorted_by_probability():
    sims = np.linspace(-0.1, 0.4, len(config.TAG_VOCAB))
    tags = features.tags_from_sims(sims)
    assert len(tags) == config.TAG_TOP_N
    assert [t["confidence"] for t in tags] == sorted(
        (t["confidence"] for t in tags), reverse=True)
    assert tags[0]["tag"] == config.TAG_VOCAB[-1], "highest similarity did not win"
    for t in tags:
        assert set(t) == {"tag", "similarity", "confidence"}
        assert 0.0 <= t["confidence"] <= 1.0


def test_tags_from_sims_rejects_a_mismatched_vocabulary_length():
    """A silent zip() truncation here would mislabel every chunk in the corpus."""
    with pytest.raises(ValueError):
        features.tags_from_sims([0.1, 0.2])
