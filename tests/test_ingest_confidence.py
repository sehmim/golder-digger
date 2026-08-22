"""Ingest has to actually persist the new measurements, in mock mode too.

Mock mode exists so the pipeline runs with no model downloads -- which is only
worth anything if it exercises the same code path, including tag-derived roles.
"""
import json

import numpy as np
import pytest

from goldigger import config, db, ingest


@pytest.fixture
def ingested(tmp_path):
    import soundfile as sf
    root = tmp_path / "audio"
    root.mkdir()
    rng = np.random.default_rng(0)
    for i in range(3):
        sf.write(root / f"clip_{i}.wav", rng.standard_normal(22050 * 3) * 0.05, 22050)

    conn = db.connect(tmp_path / "t.db")
    db.init(conn)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    return conn


def test_every_chunk_carries_the_new_confidences(ingested):
    rows = ingested.execute("SELECT * FROM chunks").fetchall()
    assert rows
    for r in rows:
        assert 0.0 <= r["tonalness"] <= 1.0
        assert 0.0 <= r["tempo_confidence"] <= 1.0

        spectral = json.loads(r["spectral"])
        assert set(spectral) == {"centroid", "rolloff", "bandwidth",
                                 "flatness", "rms", "zcr"}
        assert all(0.0 <= v["confidence"] <= 1.0 for v in spectral.values())

        tags = json.loads(r["tags"])
        assert len(tags) == config.TAG_TOP_N
        assert all(t["tag"] in config.TAG_VOCAB for t in tags)


def test_role_falls_back_to_the_tag_classifier(ingested):
    """These filenames say nothing, so any role can only have come from tags.

    "unknown" is a legitimate outcome -- role_from_tags abstains rather than
    guessing when no role clears TAG_ROLE_MIN_PROB.
    """
    rows = ingested.execute("SELECT role, role_source FROM chunks").fetchall()
    assert {r["role_source"] for r in rows} <= {"clap", "unknown"}
    assert any(r["role_source"] == "clap" for r in rows), "classifier never fired"
    for r in rows:
        if r["role_source"] == "clap":
            assert r["role"] in config.ROLES
        else:
            assert r["role"] is None
