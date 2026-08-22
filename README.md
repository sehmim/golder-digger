# Gold Digger

Point it at a folder of audio. It chunks each file, extracts musical metadata,
and answers: **"what else works with what I already have — at a chosen level of
non-obviousness?"**

## The idea

Two scores, kept separate on purpose:

- **Fit** — *does this work with my session?* Harmony + rhythm + role, combined as
  a **geometric mean** so one catastrophic component can't be masked by two good
  ones. Used as a gate. Never shown as a percentage.
- **Novelty** — *how non-obvious is this?* CLAP embedding distance, converted to a
  **corpus-relative percentile**, because raw cosine distance has no stable
  perceptual meaning.

The **DISTANCE** dial (0–100) is a *target novelty percentile among things that
already fit* — not a similarity threshold. DISTANCE 70 means "show me the 70th
percentile of non-obviousness among compatible candidates."

## Status

Feature extraction runs in **mock mode by default** (`GOLDDIGGER_MOCK=1`):
deterministic synthetic features seeded by file hash, same shapes and ranges as
the real thing. The full pipeline, storage, scoring, and API are real and run end
to end with no model downloads.

Set `GOLDDIGGER_MOCK=0` to use the real extractors (beat-this + CLAP). They are
implemented in `features.py` and smoke-tested, but have not been run over a full
library yet.

## Quickstart

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"

# ingest (mock: ~150 files/second)
.venv/bin/python -m goldigger.cli ingest ~/Music/YourSamples
.venv/bin/python -m goldigger.cli stats

# rank candidates against a context chunk
.venv/bin/python -m goldigger.cli analyze <chunk_id> --distance 70 -k 8

# or serve the API on :8420
.venv/bin/python -m goldigger.cli serve
```

## API

| Endpoint | |
|---|---|
| `POST /ingest` | `{root}` → background job → `{job_id}` |
| `GET /ingest/status/{job_id}` | `{state, total, done, failed}` |
| `GET /library` | chunks + metadata, filterable by role |
| `POST /session/analyze` | `{context_ids[], distance, k}` → ranked, each with `fit`, `novelty`, `components{H,R,P}` |
| `POST /chunk/{id}/tag` | manual role override |
| `GET /chunk/{id}/audio` | stream the chunk as WAV |
| `GET /health` | mock flag, corpus size |

## Layout

```
goldigger/
  config.py     every tunable, including the scoring constants
  db.py         SQLite schema; vectors are float32 blobs
  features.py   real extraction: beat-this, chroma/Krumhansl key, CLAP
  mock.py       deterministic fake features seeded by chunk id
  ingest.py     walk, hash-dedupe, chunk, extract, upsert, load corpus
  scoring.py    fit / novelty / greedy-MMR select
  api.py        FastAPI
  cli.py        ingest | stats | analyze | serve
```

Corpus lives in SQLite; on boot every embedding is loaded into one `(N, 512)`
NumPy array. At a few thousand chunks each query is a single matmul, so moving
the DISTANCE dial re-ranks from cached scores without touching a model.

## Design notes

Things that are the way they are on purpose:

- **Short files pass through whole.** At or under 12 s, or with fewer than two
  downbeats, a file *is* the chunk. Most of a sample library is one-shots and
  single loops that are already the atomic unit; bar-slicing them is destructive.
- **Key confidence is a gap, scaled by tonalness.** Raw correlation is high for
  anything tonal and doesn't discriminate. But a large gap can also happen by
  chance on flat chroma — so it's scaled by how tonal the chroma is at all.
  Without that, drums claim a confident key, and a sample library is full of drums.
- **Unknown key is neutral, not rejection.** `H = c·raw + (1−c)·0.6`, where `c` is
  the lower of the two key confidences.
- **Tempo is ratio-aware.** 87 BPM against 174 is a match. Raw BPM difference
  wrongly punishes half- and double-time.
- **Role compatibility floors at 0.25**, never 0 — a literal zero annihilates a
  geometric mean and would turn a preference into a hard filter.
- **Novelty percentiles rank across the whole corpus**, not the Fit-passing
  subset. The fit floor relaxes when the pool is sparse, which would otherwise
  silently shift every novelty value for the same context.
- **Selection is greedy (MMR).** The redundancy term compares against what's
  *already picked*, which is undefined in a one-shot top-K.
- **Results never share a file with the context.** Otherwise DISTANCE 10 just
  hands back the neighbouring bars of the clip you already have.

## Not built yet

tension · quality scoring · layer_type · instrument classification · 7-mode
detection (major/minor only) · onset-pattern correlation in the rhythm term ·
Preserve locks. None are on the Fit/Novelty critical path.

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

The acceptance test is `tests/test_acceptance.py`: sweep DISTANCE 10→90 and
assert novelty rises monotonically while fit stays above the floor. Then listen —
`FIT_FLOOR`, `BANDWIDTH`, and `REDUNDANCY` in `config.py` are guesses to tune by ear.
