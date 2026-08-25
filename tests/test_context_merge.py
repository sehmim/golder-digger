"""Tempo is picked, never averaged -- and its confidence describes what was kept.

The two sides of one session are routinely a half-time pair: an 87 BPM loop
and a 174 BPM bounce. tempo_score calls that a perfect match; their mean,
130.5, is a tempo neither side plays, and every candidate would be scored
against it.
"""
import numpy as np
import pytest

from goldigger import api, config, scoring


def ctx(bpm, tconf, tonic=-1, kconf=0.0):
    return {"idx": [], "clap": np.ones(config.CLAP_DIM, dtype=np.float32),
            "chroma": np.full(12, 1 / 12, dtype=np.float32),
            "bpm": bpm, "tconf": tconf, "tonic": tonic, "kconf": kconf,
            "roles": set(), "hashes": set()}


def test_a_half_time_pair_keeps_a_tempo_someone_plays():
    merged = api._merge_contexts(ctx(87.0, 0.9), ctx(174.0, 0.6))

    assert merged["bpm"] in (87.0, 174.0), f"invented {merged['bpm']} BPM"
    assert scoring.tempo_score(174.0, merged["bpm"]) > 0.9
    assert scoring.tempo_score(87.0, merged["bpm"]) > 0.9


def test_the_more_confident_tempo_wins():
    assert api._merge_contexts(ctx(120.0, 0.2), ctx(90.0, 0.95))["bpm"] == 90.0


def test_a_side_with_no_tempo_does_not_dilute_the_confidence():
    merged = api._merge_contexts(ctx(120.0, 1.0), ctx(None, 0.0))

    assert (merged["bpm"], merged["tconf"]) == (120.0, 1.0)


def test_neither_side_has_a_tempo():
    merged = api._merge_contexts(ctx(None, 0.0), ctx(None, 0.0))

    assert merged["bpm"] is None and merged["tconf"] == 0.0


def test_context_tempo_confidence_ignores_the_one_shots():
    """A one-shot stores tempo_confidence 0 because it has no tempo. Averaging
    those zeros in would discount the loops ctx["bpm"] was taken from."""
    corpus = scoring.Corpus([{"chunk_id": "loop"}, {"chunk_id": "oneshot"}])
    corpus.clap[:] = 1.0
    corpus.bpm[:] = [120.0, np.nan]
    corpus.tconf[:] = [0.9, 0.0]
    corpus.hashes = ["a", "b"]
    corpus.index = {"loop": 0, "oneshot": 1}

    built = scoring.build_context(corpus, ["loop", "oneshot"])

    assert built["bpm"] == 120.0
    assert built["tconf"] == pytest.approx(0.9)
