"""Re-walking a folder repairs rows instead of re-extracting them.

Dedupe is by content hash, so a moved file is correctly recognised as already
done -- and used to be left with rows naming the path it moved away from, which
is a chunk that cannot be played. A file edited in place has the opposite
problem: its old rows stay behind describing audio no longer at that path.
"""
import numpy as np
import pytest
import soundfile as sf

from goldigger import db, ingest


def tone(path, freq=220.0):
    t = np.linspace(0, 1.0, 22050, endpoint=False)
    sf.write(path, 0.2 * np.sin(2 * np.pi * freq * t), 22050)
    return path


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    for i in range(3):
        tone(root / f"{i}.wav", 200 + 40 * i)
    conn = db.connect(tmp_path / "t.db")
    db.init(conn)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    return conn, root


def paths(conn):
    return sorted(r["path"] for r in conn.execute("SELECT DISTINCT path FROM chunks"))


def test_a_renamed_file_is_relinked_not_reanalysed(library, monkeypatch):
    conn, root = library
    monkeypatch.setattr(ingest, "analyze_file", lambda *a, **k: pytest.fail("re-extracted"))
    (root / "0.wav").rename(root / "moved.wav")

    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))

    assert str(root / "moved.wav") in paths(conn)
    assert str(root / "0.wav") not in paths(conn)
    assert conn.execute("SELECT path FROM files WHERE path LIKE '%moved.wav'").fetchone()


def test_two_copies_are_not_a_move(library):
    """Both paths exist, so neither row is wrong and nothing should be rewritten."""
    conn, root = library
    before = paths(conn)
    (root / "copy.wav").write_bytes((root / "0.wav").read_bytes())

    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))

    assert paths(conn) == before, "a duplicate stole the original's rows"


def test_an_edited_file_loses_its_old_chunks(library):
    conn, root = library
    old = {r["chunk_id"] for r in conn.execute(
        "SELECT chunk_id FROM chunks WHERE path=?", (str(root / "1.wav"),))}
    tone(root / "1.wav", freq=999.0)

    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))

    now = {r["chunk_id"] for r in conn.execute(
        "SELECT chunk_id FROM chunks WHERE path=?", (str(root / "1.wav"),))}
    assert now and not (now & old), "the replaced audio kept its old chunks"
    assert len(paths(conn)) == 3, "one path, one set of chunks"


def test_an_untouched_folder_is_left_alone(library, monkeypatch):
    conn, root = library
    monkeypatch.setattr(ingest, "analyze_file", lambda *a, **k: pytest.fail("re-extracted"))
    before = {r["chunk_id"] for r in conn.execute("SELECT chunk_id FROM chunks")}

    job = ingest.new_job(conn, str(root))
    ingest.run_job(conn, job, str(root))

    assert {r["chunk_id"] for r in conn.execute("SELECT chunk_id FROM chunks")} == before
    row = conn.execute("SELECT done, message FROM jobs WHERE job_id=?", (job,)).fetchone()
    assert row["done"] == 3
    assert row["message"] is None, "reported repairs it did not make"


def test_the_repairs_are_reported_on_the_finished_job(library):
    conn, root = library
    (root / "0.wav").rename(root / "moved.wav")

    job = ingest.new_job(conn, str(root))
    ingest.run_job(conn, job, str(root))

    assert "1 moved" in conn.execute(
        "SELECT message FROM jobs WHERE job_id=?", (job,)).fetchone()["message"]
