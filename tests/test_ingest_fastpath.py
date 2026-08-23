"""An unchanged file skips even the hash on re-ingest.

Dedupe by content hash is correct but not free: it reads every byte of every
file to conclude "already done". The stored (size, mtime) pair vouches for the
bytes instead, so re-ingesting a finished library costs a stat per file -- and
anything touched, edited, or below today's standard still takes the slow path.
"""
import os

import numpy as np
import pytest
import soundfile as sf

from goldigger import config, db, features, ingest


def tone(path, freq=220.0):
    t = np.linspace(0, 1.0, 22050, endpoint=False)
    sf.write(path, 0.2 * np.sin(2 * np.pi * freq * t), 22050)
    return path


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "INGEST_WORKERS", 1)
    root = tmp_path / "lib"
    root.mkdir()
    for i in range(3):
        tone(root / f"{i}.wav", 200 + 40 * i)
    conn = db.connect(tmp_path / "t.db")
    db.init(conn)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    return conn, root


def counting_hash(monkeypatch):
    calls = []
    real = features.file_hash
    monkeypatch.setattr(features, "file_hash",
                        lambda p: calls.append(str(p)) or real(p))
    return calls


def test_a_second_ingest_hashes_nothing(library, monkeypatch):
    conn, root = library
    calls = counting_hash(monkeypatch)

    job = ingest.new_job(conn, str(root))
    ingest.run_job(conn, job, str(root))

    assert calls == []
    row = conn.execute("SELECT done, total FROM jobs WHERE job_id=?", (job,)).fetchone()
    assert (row["done"], row["total"]) == (3, 3)


def test_a_touched_file_is_rehashed_once(library, monkeypatch):
    """utime changes the stat but not the bytes: one hash to rediscover the
    dedupe, and a refreshed stat so the next ingest skips it again."""
    conn, root = library
    os.utime(root / "0.wav", (1, 1))

    calls = counting_hash(monkeypatch)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    assert calls == [str(root / "0.wav")]

    calls.clear()
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    assert calls == []


def test_an_edited_file_takes_the_slow_path(library, monkeypatch):
    conn, root = library
    analyzed = []
    real = ingest.analyze_file
    monkeypatch.setattr(ingest, "analyze_file",
                        lambda p, e=None: analyzed.append(str(p)) or real(p, e))
    tone(root / "0.wav", 330.0)

    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))

    assert analyzed == [str(root / "0.wav")]


def test_a_pre_migration_row_never_skips(library, monkeypatch):
    """NULL size/mtime is a row from before the columns existed: no stat can
    vouch for it, so it is hashed like any unknown file."""
    conn, root = library
    conn.execute("UPDATE files SET size=NULL, mtime=NULL")
    conn.commit()
    calls = counting_hash(monkeypatch)

    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))

    assert len(calls) == 3
