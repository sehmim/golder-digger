"""A mock-ingested library must not survive the switch to real extraction.

Dedupe is by content hash, so re-ingesting the same folder with GOLDDIGGER_MOCK
off would otherwise skip every file and leave the corpus full of vectors
synthesized from file hashes -- while reporting every file done.
"""
import numpy as np
import pytest
import soundfile as sf

from goldigger import config, db, ingest


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    for i in range(3):
        t = np.linspace(0, 1.0, 22050, endpoint=False)
        sf.write(root / f"{i}.wav", 0.2 * np.sin(2 * np.pi * (200 + 40 * i) * t), 22050)
    conn = db.connect(tmp_path / "t.db")
    db.init(conn)
    return conn, root


def ingest_once(conn, root):
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))


def test_mock_rows_are_marked_synthetic(library):
    conn, root = library
    ingest_once(conn, root)

    marks = {r["synthetic"] for r in conn.execute("SELECT synthetic FROM chunks")}
    assert marks == {1}


def test_a_real_run_does_not_skip_synthetic_files(library, monkeypatch):
    """The dedupe's 'already done' has to mean done to the current standard."""
    conn, root = library
    ingest_once(conn, root)
    before = conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]

    # Real extraction itself is out of scope here -- what is under test is that
    # the file is offered to it at all rather than skipped as already ingested.
    # One worker so the extraction happens in this process: with a pool, run_job
    # extracts inside the workers and the spy below would never be called -- a
    # monkeypatch does not cross a process boundary.
    monkeypatch.setattr(config, "INGEST_WORKERS", 1)
    monkeypatch.setattr(config, "MOCK", False)
    seen_paths = []
    real = ingest.analyze_file

    def spy(path, essentia=None):
        seen_paths.append(str(path))
        monkeypatch.setattr(config, "MOCK", True)      # produce rows without torch
        try:
            return [{**row, "synthetic": 0} for row in real(path, essentia)]
        finally:
            monkeypatch.setattr(config, "MOCK", False)

    monkeypatch.setattr(ingest, "analyze_file", spy)
    ingest_once(conn, root)

    assert len(seen_paths) == 3, "a real run skipped files carrying mock vectors"
    assert conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"] == before
    assert {r["synthetic"] for r in conn.execute("SELECT synthetic FROM chunks")} == {0}


def test_a_mock_run_still_skips_what_it_already_did(library):
    """The rule is one-directional: mock must not re-do its own work."""
    conn, root = library
    ingest_once(conn, root)

    job = ingest.new_job(conn, str(root))
    ingest.run_job(conn, job, str(root))

    row = conn.execute("SELECT done, failed FROM jobs WHERE job_id=?", (job,)).fetchone()
    assert (row["done"], row["failed"]) == (3, 0)
    assert conn.execute(
        "SELECT COUNT(*) c FROM chunks WHERE synthetic=1").fetchone()["c"] == 3


def test_rows_written_before_the_column_read_as_untrusted(library):
    """NULL is absence of evidence, and novelty cannot be reported off it."""
    conn, root = library
    ingest_once(conn, root)
    conn.execute("UPDATE chunks SET synthetic=NULL")
    conn.commit()

    corpus = ingest.load_corpus(conn)

    assert corpus.synthetic.all()
