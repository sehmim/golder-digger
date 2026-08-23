"""SQLite schema and blob helpers. Vectors are fixed-width float32 blobs."""
import sqlite3
import threading
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
  -- 1 when the CLAP vector was synthesized from the file hash (mock mode). NULL
  -- on rows written before this column existed, which is not the same as 0: an
  -- unknown vector is no more trustworthy than a synthetic one.
  synthetic       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(file_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_role ON chunks(role);
-- ingest asks "what does this path claim?" once per walked file, and resolve()
-- matches a Live sample by exact path. Without this both are a full scan.
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);

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

-- The listening test. Trials are generated ahead of time so the same set of
-- candidates can be shown to several raters, and so `strategy` and `distance`
-- live here rather than travelling to the browser: a rater who can see which
-- arm produced a candidate is no longer blind, and the experiment is spoiled.
CREATE TABLE IF NOT EXISTS trials (
  trial_id     TEXT PRIMARY KEY,
  batch        TEXT NOT NULL,
  context_ids  TEXT NOT NULL,          -- JSON list of chunk ids
  candidate    TEXT NOT NULL,
  strategy     TEXT NOT NULL,          -- never serialised to a rater
  distance     REAL,                   -- never serialised to a rater
  session_bpm  REAL,
  created_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_trials_batch ON trials(batch);

-- One row per (trial, rater). Scores are 1-7; a rater may skip a scale, so the
-- columns are nullable and the report counts what it actually has.
CREATE TABLE IF NOT EXISTS ratings (
  trial_id         TEXT NOT NULL,
  rater            TEXT NOT NULL,
  obviousness      INTEGER,
  compatibility    INTEGER,
  inspiration      INTEGER,
  discovery        INTEGER,
  direction_change INTEGER,
  note             TEXT,
  created_at       TEXT,
  PRIMARY KEY (trial_id, rater)
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
    # an ingest holds the write lock in bursts; a reader waits rather than raising
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


_local = threading.local()


def thread_conn(path=None):
    """One connection per thread, to the same WAL database.

    A single sqlite3 connection shared across threads interleaves cursors: with
    ingest committing on a worker thread, a `SELECT ... WHERE job_id=?` on a
    request thread would intermittently come back empty and the API answered
    "404 no such job" for a job that was plainly running. WAL gives concurrent
    readers alongside the one writer, so a connection each is the fix.
    """
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _local.conn = connect(path)
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
        "synthetic": "INTEGER",
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
