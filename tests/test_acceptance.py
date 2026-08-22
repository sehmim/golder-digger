"""The test that actually matters: does the DISTANCE dial do what it claims?"""
import numpy as np
import pytest

from goldigger import config, db, ingest, scoring


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    import soundfile as sf
    root = tmp_path_factory.mktemp("audio")
    rng = np.random.default_rng(0)
    for i in range(200):
        sf.write(root / f"loop_{i}.wav", rng.standard_normal(22050 * 4) * 0.05, 22050)

    conn = db.connect(tmp_path_factory.mktemp("db") / "t.db")
    db.init(conn)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    return ingest.load_corpus(conn)


def test_distance_ladder(corpus):
    assert len(corpus) >= 200
    ctx = scoring.build_context(corpus, [corpus.ids[0]])

    prev, picked, means = -1.0, {}, {}
    for d in (10, 30, 50, 70, 90):
        results, floor = scoring.select(corpus, ctx, d, k=6)
        assert results, f"no results at DISTANCE {d}"
        novelty = float(np.mean([r["novelty"] for r in results]))

        # the dial's whole claim: obviousness falls as DISTANCE rises.
        # non-decreasing per step -- at the tail the pool can run out of
        # candidates that far out and selection has to reach back down
        assert novelty >= prev, f"novelty fell at DISTANCE {d}"
        prev = novelty
        means[d] = novelty

        # high DISTANCE must stay compatible -- surprising, not incompatible
        assert min(r["fit"] for r in results) >= floor

        # never hand back the clip you already have
        assert all(r["chunk_id"] != corpus.ids[0] for r in results)
        picked[d] = {r["chunk_id"] for r in results}

    assert not (picked[10] & picked[90]), "DISTANCE 10 and 90 returned the same clips"
    assert means[90] - means[10] > 0.5, "the dial barely moved across its full range"


def test_blob_roundtrip(corpus):
    v = corpus.clap[0]
    assert np.allclose(db.from_blob(db.to_blob(v), config.CLAP_DIM), v)
    assert abs(np.linalg.norm(v) - 1.0) < 1e-5
