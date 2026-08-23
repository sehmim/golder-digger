# Development

## Setup

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"

cd golders-desktop && npm install
```

## Running

```bash
./start.sh              # both halves, real extractors
./start.sh --mock       # both halves, synthesized features
./start.sh --restart    # same, but replace an API already on the port
./start.sh --backend    # API only, foreground
./start.sh --frontend   # Electron only
./start.sh --real       # explicit alias for the default
```

`start.sh` starts the API first on purpose: the desktop app adopts a listening server
rather than spawning its own, so this keeps both sets of logs together (API output goes
to `.logs/api.log`) and turns the stale-server trap below into a printed warning. It
only ever kills a process it can confirm is our uvicorn.

The engine and CLI default to mock extraction, but the application launcher
defaults to real extraction because the DISTANCE dial depends on measured CLAP
vectors. Use `--mock` for fast UI development when ranking quality is irrelevant.

Or run the halves by hand:

```bash
# engine only
.venv/bin/python -m goldigger.cli serve            # :8420
.venv/bin/python -m goldigger.cli ingest ~/Music/Samples
.venv/bin/python -m goldigger.cli stats

# whole app (spawns the engine itself, or adopts a running one)
cd golders-desktop && npm run dev
```

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q                        # all
PYTHONPATH=. .venv/bin/python -m pytest tests/test_ableton.py -q  # one file
PYTHONPATH=. .venv/bin/python -m pytest -q -k basename            # one test
```

- `test_scoring.py` — the invariants: geometric mean cannot be masked, tempo ratios are
  not punished, missing evidence is neutral, role never scores zero.
- `test_key.py` — Krumhansl round-trips and the low-confidence-on-noise guard.
- `test_ableton.py` — every FileRef shape and every broken-file failure mode.
- `test_acceptance.py::test_distance_ladder` — the real regression guard: sweep DISTANCE
  10→90, assert novelty rises monotonically while fit stays above the floor.

Ingest calls Essentia per file, which the test suite cannot afford — `tests/conftest.py`
turns `ESSENTIA_ON_INGEST` off for the whole session (session-scoped, because the
corpora other tests build are session-scoped too and would otherwise ingest first).
`tests/test_ingest_essentia.py` covers the inline path with the extractor stubbed.

`scripts/smoke.py <audio-file>` is a step-0 gate that proves beat-this and CLAP actually
run on this machine. It is not part of the suite and needs `GOLDDIGGER_MOCK=0` deps.

## Mock mode

`GOLDDIGGER_MOCK=1` is the **default**. `mock.py` synthesizes chroma, CLAP vectors,
rhythm and role deterministically from the chunk id — same shapes and ranges as the real
extractors, clustered so novelty percentiles are not uniform noise.

Everything downstream is real. Build and test against mock; flip to `GOLDDIGGER_MOCK=0`
only to exercise `features.py` itself. This paragraph describes the engine default;
the application `start.sh` deliberately defaults to `GOLDDIGGER_MOCK=0`.

## Traps

**A stale server gets adopted.** Electron reuses anything answering on :8420. If you add
a route and it 404s, check for an old `golddigger serve` still running:

```bash
lsof -nP -iTCP:8420 -sTCP:LISTEN
```

Restart it. uvicorn is not started with `--reload`, so it will not pick up your edits.

**Ingest writes to the real database.** `config.DB_PATH` is `<repo>/golddigger.db` for
the CLI, the API and the desktop app alike. Ingesting scratch audio to try something out
puts scratch rows in your library; clean up by `path` afterwards. The test suite is safe
— every fixture connects to a `tmp_path` database.

**Two lockfiles.** `golders-desktop/` has both `package-lock.json` and `pnpm-lock.yaml`.
The current scripts use npm and `package-lock.json`; do not update the pnpm lockfile
unless the project formally changes package managers.

**The package name has one `d`.** `goldigger/`, but `golddigger` everywhere else. See
`CLAUDE.md`.

## Out of scope

`golddigger-genai/` is gitignored and not part of this system.
