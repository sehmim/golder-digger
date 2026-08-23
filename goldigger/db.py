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
  clap            BLOB,
  tempo_confidence REAL,
  tonalness       REAL,
  spectral        TEXT,
  tags            TEXT,
  note_presence   BLOB,
  notes           TEXT
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

-- Essentia is a second opinion on whole files, not chunks: MusicExtractor takes
-- a path and characterises the file. Keyed by file_hash so it survives a move.
CREATE TABLE IF NOT EXISTS essentia (
  file_hash        TEXT PRIMARY KEY,
  path             TEXT,
  key_key          TEXT,
  key_scale        TEXT,
  key_strength     REAL,
  key_confidence   REAL,
  key_agreement    INTEGER,
  bpm              REAL,
  bpm_confidence   REAL,
  danceability     REAL,
  average_loudness REAL,
  dynamic_complexity REAL,
  tuning_frequency REAL,
  payload          TEXT,
  extracted_at     TEXT
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


# Columns added after the first release. CREATE TABLE IF NOT EXISTS does nothing
# to a table that already exists, so an older database needs them added in place
# -- otherwise adding a confidence means re-ingesting the whole library.
MIGRATIONS = {
    "chunks": {
        "tempo_confidence": "REAL",
        "tonalness": "REAL",
        "spectral": "TEXT",
        "tags": "TEXT",
        "note_presence": "BLOB",
        "notes": "TEXT",
    },
}


def init(conn):
    conn.executescript(SCHEMA)
    for table, columns in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def to_blob(vec) -> bytes:
    return np.ascontiguousarray(vec, dtype=np.float32).tobytes()


def from_blob(blob, dim) -> np.ndarray:
    if blob is None:
        return np.zeros(dim, dtype=np.float32)
    return np.frombuffer(blob, dtype=np.float32).reshape(dim)
