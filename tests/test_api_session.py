"""The dial's context comes from Live when Live said something.

`POST /session/analyze` used to rebuild tempo and key from whichever samples
happened to resolve, which is the accident the set's own header exists to
settle. These pin the route to the CLI's behaviour.
"""
import gzip
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from goldigger import api, config, db, ingest

from test_ableton import LIVE12, SAMPLE_12


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A corpus of four tones, and the API pointed at it."""
    root = tmp_path / "lib"
    root.mkdir()
    for i in range(4):
        t = np.linspace(0, 2.0, int(2.0 * 22050), endpoint=False)
        sf.write(root / f"{i}.wav", 0.2 * np.sin(2 * np.pi * (200 + 60 * i) * t), 22050)

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    # thread_conn caches one connection per thread for the life of the process,
    # so without this every test after the first would read the first test's db.
    db._local.__dict__.clear()
    conn = db.thread_conn(tmp_path / "t.db")
    db.init(conn)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    api.state["conn"] = conn
    api.state["corpus"] = ingest.load_corpus(conn)
    api.state.pop("als_stamp", None)

    with TestClient(api.app) as c:
        yield c, conn, root


def write_als(path, sample_path, tempo, root_pc, in_key):
    xml = LIVE12.format(
        samples=SAMPLE_12.format(rel=sample_path.name, abs=str(sample_path)),
        tempo=tempo, root=root_pc, scale=1, in_key=in_key)
    with gzip.open(path, "wb") as f:
        f.write(xml.encode())
    return path


def ids(client, conn):
    return [r["chunk_id"] for r in conn.execute(
        "SELECT chunk_id FROM chunks ORDER BY chunk_id LIMIT 2")]


def test_live_tempo_and_key_beat_the_resolved_samples(client, tmp_path):
    c, conn, root = client
    als = write_als(tmp_path / "Set.als", root / "0.wav", tempo=174, root_pc=7, in_key="true")

    body = c.post("/session/analyze", json={
        "context_ids": ids(c, conn), "distance": 50, "session_path": str(als)}).json()

    assert body["session_context"] == ["bpm", "tonic"]
    assert body["context"]["bpm"] == 174.0
    assert body["context"]["tonic"] == "G"


def test_without_a_set_the_context_is_still_inferred(client):
    c, conn, root = client

    body = c.post("/session/analyze", json={
        "context_ids": ids(c, conn), "distance": 50}).json()

    assert body["session_context"] == []
    assert body["results"]


def test_a_set_that_never_turned_key_on_only_anchors_tempo(client, tmp_path):
    """Root=0 with InKey false is Live's default, not a deliberate C."""
    c, conn, root = client
    als = write_als(tmp_path / "Off.als", root / "0.wav", tempo=90, root_pc=0, in_key="false")

    body = c.post("/session/analyze", json={
        "context_ids": ids(c, conn), "distance": 50, "session_path": str(als)}).json()

    assert body["session_context"] == ["bpm"]


def test_a_missing_set_is_a_404_not_a_silent_fallback(client):
    c, conn, root = client

    res = c.post("/session/analyze", json={
        "context_ids": ids(c, conn), "distance": 50, "session_path": "/nope/Set.als"})

    assert res.status_code == 404


def test_the_parse_is_cached_per_file(client, tmp_path, monkeypatch):
    """A knob sweep is several requests against one unchanged file."""
    c, conn, root = client
    als = write_als(tmp_path / "Set.als", root / "0.wav", tempo=128, root_pc=2, in_key="true")

    calls = []
    real = api.ableton.load_als
    monkeypatch.setattr(api.ableton, "load_als", lambda p: (calls.append(p), real(p))[1])

    for distance in (0, 50, 100):
        c.post("/session/analyze", json={
            "context_ids": ids(c, conn), "distance": distance, "session_path": str(als)})

    assert len(calls) == 1


def test_mock_novelty_is_declared_as_synthetic(client):
    c, conn, root = client

    body = c.post("/session/analyze", json={"context_ids": ids(c, conn)}).json()

    assert body["synthetic_novelty"] is config.MOCK


def test_folder_status_counts_only_chunks_below_each_root(client, tmp_path):
    c, conn, root = client

    body = c.post("/folders/status", json={
        "roots": [str(root), str(tmp_path / "missing")]}).json()

    assert body["folders"][0]["chunks"] > 0
    assert body["folders"][1]["chunks"] == 0


def test_library_files_groups_chunks_and_paginates_within_roots(client):
    c, conn, root = client

    first = c.post("/library/files", json={
        "roots": [str(root)], "limit": 2, "offset": 0}).json()
    second = c.post("/library/files", json={
        "roots": [str(root)], "limit": 2, "offset": 2}).json()
    empty = c.post("/library/files", json={"roots": []}).json()

    assert first["total"] == 4
    assert first["count"] == 2
    assert second["count"] == 2
    assert {row["path"] for row in first["files"]}.isdisjoint(
        {row["path"] for row in second["files"]})
    assert all(row["chunks"] >= 1 for row in first["files"])
    assert empty["total"] == 0


def test_active_roots_limit_the_candidate_corpus(client, tmp_path):
    c, conn, root = client
    other = tmp_path / "other"
    other.mkdir()
    for i in range(2):
        t = np.linspace(0, 2.0, int(2.0 * 22050), endpoint=False)
        sf.write(other / f"other-{i}.wav", 0.2 * np.sin(2 * np.pi * (700 + 80 * i) * t), 22050)
    ingest.run_job(conn, ingest.new_job(conn, str(other)), str(other))
    api.state["corpus"] = ingest.load_corpus(conn)

    body = c.post("/session/analyze", json={
        "context_ids": ids(c, conn), "active_roots": [str(other)]}).json()

    assert body["corpus_size"] > 0
    assert body["results"]
    assert all(Path(result["path"]).is_relative_to(other) for result in body["results"])


def test_explicit_empty_roots_search_nothing_but_omission_keeps_legacy_corpus(client):
    c, conn, root = client

    empty = c.post("/session/analyze", json={
        "context_ids": ids(c, conn), "active_roots": []}).json()
    legacy = c.post("/session/analyze", json={"context_ids": ids(c, conn)}).json()

    assert empty["corpus_size"] == 0
    assert empty["results"] == []
    assert legacy["corpus_size"] > 0
    assert legacy["results"]
