"""SQLite schema and blob helpers. Vectors are fixed-width float32 blobs."""
import sqlite3
import numpy as np
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id        TEXT PRIMARY KEY,
  path            TEXT NOT NULL,
  file_hash       TEXT NOT NULL,
  chunk_index     INTEGER NOT NULL,
  t_start         REAL NOT NULL,
  t_end           REAL NOT NULL,
  bpm             REAL,
  beats_per_bar   INTEGER,
  tonic_pc        INTEGER,
  is_major        INTEGER,
  key_confidence  REAL,
  role            TEXT,
  role_source     TEXT,
  chroma          BLOB,
  clap            BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(file_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_role ON chunks(role);

CREATE TABLE IF NOT EXISTS files (
  file_hash   TEXT PRIMARY KEY,
  path        TEXT,
  duration    REAL,
  status      TEXT,
  error       TEXT,
  ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
  job_id     TEXT PRIMARY KEY,
  root       TEXT,
  state      TEXT,
  total      INTEGER DEFAULT 0,
  done       INTEGER DEFAULT 0,
  failed     INTEGER DEFAULT 0,
  message    TEXT,
  started_at TEXT,
  finished_at TEXT
);
"""


def connect(path=None):
    conn = sqlite3.connect(str(path or config.DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def to_blob(vec) -> bytes:
    return np.ascontiguousarray(vec, dtype=np.float32).tobytes()


def from_blob(blob, dim) -> np.ndarray:
    if blob is None:
        return np.zeros(dim, dtype=np.float32)
    return np.frombuffer(blob, dtype=np.float32).reshape(dim)
