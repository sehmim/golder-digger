"""Real mode collects the Essentia second opinion after the corpus is live.

Inline, the per-file pass was 47% of ingest wall time -- ahead of chunk rows it
never changes, since nothing on the Fit/Novelty path reads it in real mode. So
run_job publishes the corpus first (on_corpus_ready) and runs Essentia as a
tail of the same job. The extractor and the analyzer are both stubbed: what is
under test is the ordering and the merge, not the models.
"""
import numpy as np
import pytest
import soundfile as sf

from goldigger import config, db, essentia_runner, features, ingest

RECORD = {
    "key_key": "F", "key_scale": "minor", "key_strength_raw": 0.8,
    "bpm": 174.0, "bpm_confidence": 0.62,
}


def tone(path):
    t = np.linspace(0, 1.0, 22050, endpoint=False)
    sf.write(path, 0.2 * np.sin(2 * np.pi * 220 * t), 22050)
    return path


def canned_rows(path, essentia=None):
    fh = features.file_hash(path)
    return [dict(
        chunk_id=f"{fh[:12]}:0", path=str(path), file_hash=fh, chunk_index=0,
        t_start=0.0, t_end=1.0, bpm=120.0, beats_per_bar=4,
        tonic_pc=0, is_major=1, key_confidence=0.5,
        role="melody", role_source="test", tonalness=0.9, tempo_confidence=0.5,
        spectral=None, tags=None, chroma=np.full(12, 1 / 12, dtype=np.float32),
        clap=np.zeros(config.CLAP_DIM, dtype=np.float32), synthetic=0,
        bpm_source="audio", key_source="audio")]


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(config, "MOCK", False)
    monkeypatch.setattr(config, "POOL_ANALYZE", False)
    monkeypatch.setattr(config, "INGEST_WORKERS", 1)
    monkeypatch.setattr(config, "ESSENTIA_ON_INGEST", True)
    monkeypatch.setattr(essentia_runner, "essentia_available_natively", lambda: True)
    monkeypatch.setattr(ingest, "analyze_file", canned_rows)


def test_corpus_is_published_before_the_tail(tmp_path, real_mode, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    tone(root / "a.wav")
    conn = db.connect(tmp_path / "t.db")
    db.init(conn)

    order = []
    monkeypatch.setattr(essentia_runner, "extract_one",
                        lambda p: order.append("essentia") or RECORD)

    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root),
                   on_corpus_ready=lambda: order.append("corpus"))

    assert order[0] == "corpus", f"tail ran ahead of the corpus: {order}"
    assert order.count("essentia") == 1
    row = conn.execute("SELECT bpm, key_key FROM essentia").fetchone()
    assert (row["bpm"], row["key_key"]) == (174.0, "F")


def test_the_tail_heals_a_missing_second_opinion(tmp_path, real_mode, monkeypatch):
    """A file ingested with GOLDDIGGER_ESSENTIA=0 gets its record on the next
    ingest without being re-chunked."""
    root = tmp_path / "lib"
    root.mkdir()
    tone(root / "a.wav")
    conn = db.connect(tmp_path / "t.db")
    db.init(conn)

    monkeypatch.setattr(config, "ESSENTIA_ON_INGEST", False)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    assert conn.execute("SELECT COUNT(*) FROM essentia").fetchone()[0] == 0

    monkeypatch.setattr(config, "ESSENTIA_ON_INGEST", True)
    monkeypatch.setattr(essentia_runner, "extract_one", lambda p: RECORD)
    monkeypatch.setattr(ingest, "analyze_file",
                        lambda *a, **k: pytest.fail("re-chunked a done file"))

    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))

    assert conn.execute("SELECT COUNT(*) FROM essentia").fetchone()[0] == 1
