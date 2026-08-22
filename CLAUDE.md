# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Gold Digger answers one question: *"what else in my sample library works with what I
already have — at a chosen level of non-obviousness?"* Read `README.md` first for the
Fit/Novelty idea and the design rationale; it is the authoritative statement of intent.

Two halves, two languages:

- `goldigger/` — the Python engine. Ingestion, feature extraction, scoring, FastAPI.
- `golders-desktop/` — the Electron + React desktop app. Spawns the engine and talks
  to it over localhost.

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
.venv/bin/python -m goldigger.cli serve                          # API on :8420

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
beat-this or CLAP, no model downloads, ~150 files/second. The rest of the pipeline
(chunking, storage, scoring, API, desktop) is real and runs end to end.

Build and test against mock. Set `GOLDDIGGER_MOCK=0` only when deliberately exercising
the real extractors — the first call loads torch and takes minutes.

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

2. **The corpus lives in RAM.** On boot every embedding is loaded into one `(N, 512)`
   NumPy array, so moving DISTANCE re-ranks from cached scores without touching a
   model. Anything that writes chunks must reload it (`state["corpus"] = ingest.load_corpus(conn)`).

3. **The renderer never speaks HTTP.** Electron main owns the child process and the
   fetch client; the renderer only sees `window.desktop.*` over IPC. This keeps
   `contextIsolation` intact and sidesteps CORS entirely — a browser-side fetch to the
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

- `config.DB_PATH` is `<repo>/golddigger.db` — a dev-time choice. A packaged app needs
  `app.getPath('userData')`, and the spawn in `src/main/api.ts` assumes the repo
  checkout is the app's parent directory.
- `src/main/api.ts` **reuses an already-listening server on :8420** rather than
  spawning a second one. A stale `golddigger serve` from an earlier session will be
  adopted silently and will 404 any route added since it started.
- Drag-and-drop of a `.als` opens the file picker instead of reading the drop. The
  browser hands over a filename, not a path, and `ableton.resolve()` needs a real one.
