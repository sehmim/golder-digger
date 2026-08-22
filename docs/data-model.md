# Data model

SQLite at `config.DB_PATH` (`<repo>/golddigger.db`), WAL mode, `synchronous=NORMAL`.
Schema is one string in `goldigger/db.py`; `db.init()` is idempotent.

## chunks

The unit of everything. One row per analyzed span of audio.

| Column | Note |
|---|---|
| `chunk_id` | `f"{file_hash[:12]}:{chunk_index}"` — derived, not random |
| `path`, `file_hash` | `file_hash` is sha256 of the file contents |
| `chunk_index`, `t_start`, `t_end` | position within the file, in seconds |
| `bpm`, `beats_per_bar` | from beat-this, or mock |
| `tonic_pc`, `is_major`, `key_confidence` | `tonic_pc` is `-1` when unknown |
| `role`, `role_source` | `role_source` ∈ `filename` \| `mock` \| `manual` |
| `chroma`, `clap` | float32 blobs, 12 and 512 wide |

Vectors go in and out through `db.to_blob` / `db.from_blob`. `from_blob(None, dim)`
returns zeros rather than failing, so a half-extracted row cannot crash corpus load.

Indexed on `file_hash` and `role`.

## files

One row per ingested file, keyed by content hash. This is the **dedupe ledger**: an
ingest skips any file whose hash is already present with `status='ok'`, so re-ingesting
an overlapping folder is cheap and moving or renaming a file does not duplicate it.

A failed file is recorded with `status='failed'` and the traceback in `error`. Note the
failure path writes `str(path)` into the `file_hash` primary key, since hashing may be
what failed.

## jobs

| Column | Note |
|---|---|
| `root` | display only; a multi-root job stores its list as JSON |
| `state` | `queued` → `running` → `finished` |
| `total`, `done`, `failed` | counters; `total` is 0 until the walk completes |
| `message` | the file currently being analyzed, `NULL` when finished |

`total` being 0 mid-walk is why the desktop shows "Walking folder…" instead of a
progress bar for the first moment of a job.

There is no cancel. Dismissing a row in the UI only stops showing it; the job runs on.

## Chunking

`features.chunk_boundaries` decides the spans:

- At or under `WHOLE_FILE_MAX_SEC` (12s), or with fewer than two downbeats, **the file
  is the chunk.** Most of a sample library is one-shots and single loops that are
  already the atomic unit; bar-slicing them is destructive.
- Otherwise, `BARS_PER_CHUNK` (4) bars per chunk, falling back to
  `FALLBACK_WINDOW_SEC` (4s) windows when no beats are found at all.
- `MAX_ANALYZE_SEC` (600s) guards against an accidental full-album ingest.

## The in-memory corpus

`ingest.load_corpus(conn)` builds a `scoring.Corpus`: parallel NumPy arrays indexed by
row order, plus `index` mapping `chunk_id → i`. See `architecture.md` for why, and for
the rule that any new write path must rebuild it.
