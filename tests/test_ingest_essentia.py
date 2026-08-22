"""Essentia's answer wins over mock's invented one, and lands in its own table.

The extractor itself is stubbed: what is under test is which measurement the
chunk rows end up carrying, not MusicExtractor.
"""
import numpy as np
import pytest
import soundfile as sf

from goldigger import config, db, essentia_runner, ingest


RECORD = {
    "key_key": "F", "key_scale": "minor", "key_strength_raw": 0.8,
    "bpm": 174.0, "bpm_confidence": 0.62, "danceability": 1.4,
    "average_loudness": 0.7, "dynamic_complexity": 3.1, "tuning_frequency": 440.0,
}


@pytest.fixture
def library(tmp_path):
    path = tmp_path / "loop.wav"
    t = np.linspace(0, 4.0, int(4.0 * 22050), endpoint=False)
    sf.write(path, 0.2 * np.sin(2 * np.pi * 220 * t), 22050)
    conn = db.connect(tmp_path / "t.db")
    db.init(conn)
    return conn, tmp_path


def run(conn, root, monkeypatch, record):
    monkeypatch.setattr(config, "ESSENTIA_ON_INGEST", True)
    monkeypatch.setattr(essentia_runner, "essentia_available_natively", lambda: True)
    monkeypatch.setattr(essentia_runner, "extract_one", lambda path: record)
    job = ingest.new_job(conn, str(root))
    ingest.run_job(conn, job, str(root))


def test_key_and_tempo_come_from_essentia(library, monkeypatch):
    conn, root = library
    run(conn, root, monkeypatch, RECORD)

    row = conn.execute("SELECT bpm, tonic_pc, is_major, tempo_confidence FROM chunks").fetchone()
    assert row["bpm"] == 174.0
    assert row["tonic_pc"] == 5           # F
    assert not row["is_major"]
    assert row["tempo_confidence"] == pytest.approx(0.62)


def test_no_tempo_is_stored_as_none(library, monkeypatch):
    """0 BPM is Essentia saying "one-shot", not a tempo of zero."""
    conn, root = library
    run(conn, root, monkeypatch, {**RECORD, "bpm": 0.0})

    assert conn.execute("SELECT bpm FROM chunks").fetchone()["bpm"] is None


def test_the_record_is_merged_into_its_own_table(library, monkeypatch):
    conn, root = library
    run(conn, root, monkeypatch, RECORD)

    row = conn.execute("SELECT * FROM essentia").fetchone()
    assert row["key_key"] == "F" and row["key_scale"] == "minor"
    assert row["danceability"] == pytest.approx(1.4)
    # not 1: in mock mode this record IS where the chunk's key came from, so
    # there is no second opinion left to agree with
    assert row["key_agreement"] is None
    # gated by librosa's tonalness, so it is not just essentia's raw strength
    assert 0.0 <= row["key_confidence"] <= 0.8


def test_a_failing_extractor_does_not_fail_the_ingest(library, monkeypatch):
    conn, root = library

    def boom(path):
        raise RuntimeError("essentia fell over")

    monkeypatch.setattr(config, "ESSENTIA_ON_INGEST", True)
    monkeypatch.setattr(essentia_runner, "essentia_available_natively", lambda: True)
    monkeypatch.setattr(essentia_runner, "extract_one", boom)
    job = ingest.new_job(conn, str(root))
    ingest.run_job(conn, job, str(root))

    assert conn.execute("SELECT failed FROM jobs").fetchone()["failed"] == 0
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
