"""The baseline harness is the instrument that judges the product, so its own
invariants matter: a strategy that cheats would manufacture the conclusion."""
import sys

import numpy as np
import pytest

sys.path.insert(0, ".")

from goldigger import config, scoring
from scripts import baselines


class FakeCorpus:
    """Small deterministic corpus: 40 chunks, 4 files, spread over CLAP space."""

    def __init__(self, n=40):
        rng = np.random.default_rng(0)
        self.rows = [{"chunk_id": f"c{i}", "path": f"/f{i//10}.wav", "is_major": 1}
                     for i in range(n)]
        self.ids = [r["chunk_id"] for r in self.rows]
        self.index = {c: i for i, c in enumerate(self.ids)}
        v = rng.standard_normal((n, config.CLAP_DIM))
        self.clap = (v / np.linalg.norm(v, axis=1, keepdims=True)).astype(np.float32)
        ch = rng.random((n, 12)).astype(np.float32)
        self.chroma = ch / ch.sum(axis=1, keepdims=True)
        self.bpm = np.full(n, 120.0, dtype=np.float32)
        self.tonic = np.zeros(n, dtype=np.int16)
        self.kconf = np.full(n, 0.5, dtype=np.float32)
        self.roles = ["drums" if i % 2 else "bass" for i in range(n)]
        self.hashes = [f"h{i//10}" for i in range(n)]

    def __len__(self):
        return len(self.rows)


@pytest.fixture
def setup():
    corpus = FakeCorpus()
    ctx = scoring.build_context(corpus, ["c0"])
    scores = scoring.fit_all(corpus, ctx)
    nov = scoring.novelty_all(corpus, ctx)
    return corpus, ctx, scores["fit"], nov


@pytest.mark.parametrize("name", list(baselines.STRATEGIES))
def test_no_strategy_returns_the_contexts_own_file(setup, name):
    """Otherwise DISTANCE 10 just hands back neighbouring bars of the same clip."""
    corpus, ctx, fit, nov = setup
    idx = baselines.STRATEGIES[name](corpus, ctx, fit, nov, 0.5, 8,
                                     np.random.default_rng(0))
    assert idx, f"{name} returned nothing"
    assert not any(corpus.hashes[i] in ctx["hashes"] for i in idx)


@pytest.mark.parametrize("name", list(baselines.STRATEGIES))
def test_every_strategy_returns_k_distinct_items(setup, name):
    corpus, ctx, fit, nov = setup
    idx = baselines.STRATEGIES[name](corpus, ctx, fit, nov, 0.5, 8,
                                     np.random.default_rng(0))
    assert len(idx) == 8 and len(set(map(int, idx))) == 8


def test_nearest_really_is_the_nearest(setup):
    """If this drifts, the comparison stops being against similarity search."""
    corpus, ctx, fit, nov = setup
    idx = baselines.pick_nearest(corpus, ctx, fit, nov, 0.5, 5, np.random.default_rng(0))
    assert nov[idx].mean() < 0.2


def test_inverse_tracks_the_requested_percentile(setup):
    """The inverse baseline must honour DISTANCE, or it is not a fair comparator."""
    corpus, ctx, fit, nov = setup
    for q in (0.1, 0.5, 0.9):
        idx = baselines.pick_inverse(corpus, ctx, fit, nov, q, 5, np.random.default_rng(0))
        assert abs(nov[idx].mean() - q) < 0.15


def test_the_ablation_differs_from_the_real_thing_only_by_the_gate(setup):
    corpus, ctx, fit, nov = setup
    gated = baselines.pick_golddigger(corpus, ctx, fit, nov, 0.5, 8, np.random.default_rng(0))
    ungated = baselines.pick_band_nofit(corpus, ctx, fit, nov, 0.5, 8, np.random.default_rng(0))
    assert min(fit[gated]) >= min(fit[ungated]) - 1e-9


def test_jaccard_is_a_set_measure():
    assert baselines.jaccard([1, 2, 3], [1, 2, 3]) == 1.0
    assert baselines.jaccard([1, 2], [3, 4]) == 0.0
    assert baselines.jaccard([1, 2], [2, 3]) == pytest.approx(1 / 3)


def test_redundancy_is_high_for_identical_vectors(setup):
    corpus, _, _, _ = setup
    corpus.clap[:3] = corpus.clap[0]
    assert baselines.redundancy(corpus, [0, 1, 2]) == pytest.approx(1.0, abs=1e-5)
