# Architecture

## The two halves

```
┌─ golders-desktop/ (Electron) ───────────────┐
│                                             │
│  renderer (React)                           │
│      │  window.desktop.*   (contextBridge)  │
│  preload                                    │
│      │  ipcMain.handle / webContents.send   │
│  main ──── spawn ──────────────────────────┐│
│      └──── fetch http://127.0.0.1:8420 ───┐││
└───────────────────────────────────────────┼┼┘
                                            ││
┌─ goldigger/ (Python) ──────────────────────▼▼┐
│  api.py      FastAPI on uvicorn              │
│  ingest.py   walk → hash → chunk → extract   │
│  features.py beat-this · chroma/KS · CLAP    │
│  mock.py     deterministic stand-ins         │
│  scoring.py  fit · novelty · greedy MMR      │
│  ableton.py  .als → tempo/key/sample refs    │
│  db.py       SQLite schema, float32 blobs    │
└───────────────────┬──────────────────────────┘
                    ▼
            golddigger.db (SQLite, WAL)
```

The renderer never opens a socket. Everything crosses one boundary: `window.desktop.*`
in the renderer, `ipcMain.handle` in main, `fetch` from main to the child process.

## The path a folder takes

1. **Pick.** `dialog.showOpenDialog` in main returns absolute paths.
2. **Job.** Renderer calls `startIngest(roots)`; main `POST /ingest {roots}`; Python
   creates a row in `jobs` and returns a `job_id` immediately.
3. **Walk.** `ingest.walk_all()` unions `walk()` over every root, deduping by path.
   `walk()` treats a *file* root as a one-element list, which is what lets a Live set's
   missing samples be ingested individually rather than by folder.
4. **Analyze.** Per file: sha256 content hash → skip if already in `files` → chunk →
   extract → upsert. `jobs.message` carries the file currently in flight; `jobs.done`
   and `jobs.total` carry progress.
5. **Poll.** Main polls `/ingest/status/{job_id}` every 400ms and pushes each reading
   to the renderer as an `ingest:progress` event. The UI does no polling of its own.
6. **Reload.** When the job finishes, the API rebuilds the in-memory corpus.

## The path a Live set takes

1. `POST /session/als {path}` → `ableton.load_als()` unzips the XML and reads tempo,
   key and every `<SampleRef>`.
2. `ableton.resolve()` matches each reference against the corpus: content hash first,
   then exact path, then unique basename. Each match is labelled with the method used.
3. The route enriches matches with chunk count, majority role, mean BPM and tonic, and
   marks unmatched references with `ingest_path` when the file is on disk but absent
   from the corpus.
4. Those `ingest_path`s feed straight back into step 2 of the ingest flow above. When
   that job finishes the set is resolved again, and previously-missing rows flip.
5. `context_ids` (every chunk of every matched sample) is the input to
   `POST /session/analyze`.

## Why the corpus is in memory

`ingest.load_corpus()` reads every chunk row and packs the embeddings into one
`(N, 512)` float32 array plus parallel arrays for chroma, bpm, tonic, key confidence,
role and file hash. At a few thousand chunks a query is a single matmul, so moving the
DISTANCE dial re-ranks from cached scores without touching a model.

The cost: **anything that writes chunks must rebuild it.** `api.py` does this after
ingest and after a manual role tag. A new write path that forgets is a stale-results
bug that will not show up in tests.

## Process lifecycle

`src/main/api.ts` health-checks `http://127.0.0.1:8420/health` before spawning. If
something already answers, it is adopted and no child is started — convenient when a
`golddigger serve` is already running, and a trap when that server predates a route you
just added. Otherwise it spawns `python -m uvicorn goldigger.api:app`, resolving the
interpreter as `GOLDDIGGER_PYTHON` → `<repo>/.venv/bin/python3` → `python3`, and polls
health for up to 90 seconds (importing the package pulls in torch even in mock mode).

`before-quit` clears the job pollers and kills the child.
