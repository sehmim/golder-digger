# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Gold Digger answers one question: *"what else in my sample library works with what I
already have — at a chosen level of non-obviousness?"* Read `README.md` first for the
Fit/Novelty idea and the design rationale; it is the authoritative statement of intent.

Two halves, two languages (plus a thin third):

- `goldigger/` — the Python engine. Ingestion, feature extraction, scoring, FastAPI.
  Context can come from a Live set (`ableton.py`), a standard MIDI file (`midi.py`),
  audio files directly (`context_paths` / `golddigger match`), or a caller-stated
  tempo — the engine is DAW-agnostic; `.als` is just the richest provider.
- `golders-desktop/` — the Electron + React desktop app. Spawns the engine and talks
  to it over localhost.
- `golders-plugin/` — a JUCE AU/VST3 bridge (C++). Captures what the host plays,
  states the transport tempo, asks the running engine, and hands results back as
  files draggable onto the host's timeline. No analysis lives in it.

`docs/` holds the deeper references. Start at `docs/README.md`.

## Naming trap

Three spellings, all intentional, all different:

| Name | What |
|---|---|
| `goldigger/` | the Python **package** (one `d`) |
| `golddigger` | the **project/dist name** and CLI entry point (two `d`s) |
| `golders-desktop/` | the Electron app |

`golddigger-genai/` is out of scope — it is gitignored and not part of this system.

## Commands

```bash
./start.sh              # API + desktop app; --backend, --frontend, --restart, --real

# --- engine ---
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"

PYTHONPATH=. .venv/bin/python -m pytest -q                       # all tests
PYTHONPATH=. .venv/bin/python -m pytest tests/test_scoring.py -q # one file
PYTHONPATH=. .venv/bin/python -m pytest -q -k tempo_ratios       # one test

.venv/bin/python -m goldigger.cli ingest ~/Music/Samples
.venv/bin/python -m goldigger.cli stats
.venv/bin/python -m goldigger.cli als "~/Music/Set.als" --analyze
.venv/bin/python -m goldigger.cli midi "~/Music/idea.mid" --analyze  # DAW-agnostic context
.venv/bin/python -m goldigger.cli match ~/Music/loop.wav             # no DAW, no ingest
.venv/bin/python -m goldigger.cli lines <chunk-id> [<chunk-id>...]   # the transit map
.venv/bin/python -m goldigger.cli serve                          # API on :8420

# --- plugin (AU/VST3 bridge; engine must be running) ---
cd golders-plugin && cmake -B build && cmake --build build -j
auval -v aufx Gdig Gldg

# --- desktop ---
cd golders-desktop
npm run dev            # electron-vite; also spawns the Python API
npm run build          # typecheck-free bundle to out/
npx tsc --noEmit -p tsconfig.json   # there is no lint script; this is the check
```

There is no linter or formatter configured in either half.

## Mock mode is the default

`GOLDDIGGER_MOCK=1` is the default in `config.py`. Feature extraction is synthesized
deterministically from the file hash — same shapes and ranges as the real thing, no
beat-this or CLAP, no model downloads. The rest of the pipeline (chunking, storage,
scoring, API, desktop) is real and runs end to end.

**Ingest runs Essentia in-process when it can import it** (`ESSENTIA_ON_INGEST`, on by
default). That makes key and tempo real measurements even in mock mode — Essentia's
answer overrides the hash-derived one, and 0 BPM is stored as `NULL` because it means
"one-shot", not "no tempo". Chroma and the CLAP vector stay synthetic, so **Fit's
harmony term and Novelty are still fiction under mock**. It also dominates ingest time
— a second on a short sample, ~20s on a seven-minute stem — so
`GOLDDIGGER_ESSENTIA=0` restores the ~150 files/second mock speed. **Only mock runs it
inline**: in real mode nothing on the Fit/Novelty path reads it, so `run_job` publishes
the corpus first (`on_corpus_ready`) and collects the second opinion as a tail of the
same job, healing files ingested with the flag off along the way.

**Re-ingests skip unchanged files without hashing them.** `files.size`/`files.mtime`
are the voucher: a path whose stat matches skips straight to done, so re-walking a
finished library is near-instant instead of re-reading every byte. NULL stat columns
(failed files, pre-migration rows) never skip.

**Ingest spreads hashing and Essentia over a process pool** (`INGEST_WORKERS`, default
cpu_count-1; `GOLDDIGGER_WORKERS` overrides). Processes, not threads: MusicExtractor
holds the GIL for its whole run, so four threads measured no faster than serial while
four processes were 3.6x. `ingest.prepared()` yields in walk order, so the loop that
writes to SQLite is unchanged and single-threaded — the connection never leaves the
job's thread. A test that stubs `extract_one` must set `INGEST_WORKERS = 1`; a
monkeypatch does not cross a process boundary.

Build and test against mock. **The app is not mock**: `start.sh` and the Electron spawn
both set `GOLDDIGGER_MOCK=0`, because under mock the CLAP vector is synthesized from the
file hash and "sounds like" — the entire DISTANCE dial — means nothing. `./start.sh
--mock` opts back out. Loading torch costs ~19s once; after that a short sample is
~0.3s.

`chunks.synthetic` records which kind of vector each row carries (1 mock, 0 measured,
NULL predates the column and is treated as untrusted). Ingest's dedupe reads it: a real
run re-does a file whose vectors were synthesized, or switching the flag off would be a
silent no-op. `/health` and `/session/analyze` report the count so the UI can say the
dial is not a measurement.

## Architecture in one pass

```
Electron main  ──spawn──▶  uvicorn goldigger.api:app  ──▶  SQLite (golddigger.db)
      │                            │
      │ IPC                        │ in-memory Corpus: (N, 512) float32
      ▼                            ▼
   renderer                   scoring.select()
```

Three things that explain most of the code:

1. **Fit and Novelty are kept separate on purpose.** Fit is a geometric mean of
   harmony/rhythm/role used as a *gate*; Novelty is a corpus-relative percentile of
   CLAP distance. The DISTANCE dial targets a novelty percentile *among things that
   already fit* — it is not a similarity threshold. Collapsing them into one weighted
   distance is the thing this design exists to avoid. See `docs/scoring.md`.

   `lines.py` is the other half of that argument: DISTANCE can say how far but not
   *in what respect*, so the transit map ranks a scoped distance one dimension at a
   time — harmony, groove, timbre, character — and draws them as four metro lines
   out of your session. It does not change `novelty_all` and is not a second dial.
   A stop's `position` is a percentile *within its own line only*. See
   `docs/lines.md`.

2. **The corpus lives in RAM.** On boot every embedding is loaded into one `(N, 512)`
   NumPy array, so moving DISTANCE re-ranks from cached scores without touching a
   model. Anything that writes chunks must reload it (`state["corpus"] = ingest.load_corpus(conn)`).

3. **The renderer never speaks HTTP.** Electron main owns the child process and the
   fetch client; the renderer only sees `window.desktop.*` over IPC. This keeps
   `contextIsolation` intact and sidesteps CORS entirely. Chunk previews follow the same
   rule: `/chunk/{id}/audio` is fetched in main and the bytes cross IPC, rather than
   pointing a media element at localhost — a browser-side fetch to the
   API is blocked, which is a real trap when previewing the renderer outside Electron.
   See `docs/desktop.md`.

## House style

The existing code is written a particular way, and new code should match it:

- **Module docstrings state the reasoning, not the contents.** Every module opens by
  explaining why it exists or what constraint shaped it.
- **Comments justify non-obvious choices, and only those.** `ROLE_SAME` is floored
  above zero "because a literal zero annihilates a geometric mean" — that is the level
  of comment this codebase wants. No comment restates what the line does.
- **Every tunable lives in `config.py`.** The scoring constants are explicitly guesses
  to tune by ear; do not scatter magic numbers into `scoring.py`.
- **Failure modes are named, not swallowed.** `UnreadableSet` carries the offending
  path; `resolve()` labels every match with the method that found it (`hash` / `path` /
  `basename`) so a match can be audited rather than trusted.
- Renderer CSS uses the custom properties on `:root` in `styles.css`. No CSS framework,
  no CSS-in-JS.

## Gotchas

- `config.DB_PATH` defaults to `<repo>/golddigger.db`; `GOLDDIGGER_DATA` (or
  `GOLDDIGGER_DB`) points the engine's writes elsewhere. The dev spawn in
  `src/main/api.ts` still assumes the repo checkout is the app's parent directory,
  but a packaged app spawns the self-contained engine in `Resources/engine`
  (assembled by `golders-desktop/scripts/package-engine.sh`, see the desktop
  README) and writes to `userData` via `GOLDDIGGER_DATA`.
- `src/main/api.ts` **reuses an already-listening server on :8420** rather than
  spawning a second one. A stale `golddigger serve` from an earlier session gets adopted
  silently and then 404s every route added since it started. `/health` reports its own
  route table and `start()` refuses to adopt a server missing anything in
  `REQUIRED_ROUTES`; add a route there when you add a call, and
  `tests/test_health_contract.py` fails if the engine does not serve it. This replaced a
  single marker key that had to be moved by hand and never was — it was in the payload
  from the first commit, so it was present in every build and pinned nothing.
- Drag-and-drop of a `.als` opens the file picker instead of reading the drop. The
  browser hands over a filename, not a path, and `ableton.resolve()` needs a real one.
