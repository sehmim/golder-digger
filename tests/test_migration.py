"""Adding confidence columns must not orphan an already-ingested library.

Re-ingesting a few thousand files because a column was added is a real cost, so
init() migrates in place instead of relying on CREATE TABLE IF NOT EXISTS --
which silently does nothing when the table exists with the old shape.
"""
import sqlite3

from goldigger import db

OLD_CHUNKS = """
CREATE TABLE chunks (
  chunk_id TEXT PRIMARY KEY, path TEXT NOT NULL, file_hash TEXT NOT NULL,
  chunk_index INTEGER NOT NULL, t_start REAL NOT NULL, t_end REAL NOT NULL,
  bpm REAL, beats_per_bar INTEGER, tonic_pc INTEGER, is_major INTEGER,
  key_confidence REAL, role TEXT, role_source TEXT, chroma BLOB, clap BLOB
);
"""

NEW_COLUMNS = {"tempo_confidence", "tonalness", "spectral", "tags",
               "note_presence", "notes"}


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_init_adds_confidence_columns_to_a_pre_existing_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript(OLD_CHUNKS)
    conn.execute("INSERT INTO chunks (chunk_id, path, file_hash, chunk_index,"
                 " t_start, t_end) VALUES ('abc:0','/x.wav','abc',0,0.0,4.0)")
    conn.commit()
    conn.row_factory = sqlite3.Row

    db.init(conn)

    assert NEW_COLUMNS <= _columns(conn, "chunks")
    row = conn.execute("SELECT * FROM chunks WHERE chunk_id='abc:0'").fetchone()
    assert row["path"] == "/x.wav", "migration lost the existing row"
    assert row["tempo_confidence"] is None, "back-filled a confidence it never measured"


def test_init_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "new.db")
    db.init(conn)
    db.init(conn)
    assert NEW_COLUMNS <= _columns(conn, "chunks")


def test_essentia_table_exists(tmp_path):
    conn = db.connect(tmp_path / "e.db")
    db.init(conn)
    assert "file_hash" in _columns(conn, "essentia")
