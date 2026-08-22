# HTTP API

FastAPI in `goldigger/api.py`, served by uvicorn on `127.0.0.1:8420`. Started either by
`golddigger serve` or by Electron main (`golders-desktop/src/main/api.ts`).

Module-level `state` holds the SQLite connection and the in-memory corpus. `_corpus()`
raises **409** when the corpus is empty — that is a normal state for a fresh install,
not an error to hide from the user.

## Routes

### `GET /health`
`{ok, mock, chunks, db}`. Used by Electron to decide whether to spawn a child process.

### `POST /ingest`
`{root}` or `{roots: [...]}` — at least one is required. Each entry may be a folder or a
single file. Returns `{job_id}` immediately; the work runs in `asyncio.to_thread`
because extraction is CPU/GPU bound and releases the GIL. Reloads the corpus on finish.

### `GET /ingest/status/{job_id}`
The raw `jobs` row: `{state, total, done, failed, message}`. See `data-model.md`.

### `GET /library`
`?limit=&offset=&role=` → `{total, count, chunks[]}`, each chunk with `tonic` resolved
to a pitch name.

### `POST /session/als`
`{path}` → parses a Live set and resolves its samples against the corpus.

```jsonc
{
  "session": { "name", "path", "creator", "tempo", "key", "in_key", "samples" },
  "matched": [
    { "name", "method": "hash|path|basename", "resolved_path", "chunk_ids": [],
      "chunks": 3, "role": "harmony", "bpm": 90.0, "tonic": "C" }
  ],
  "unmatched": [
    { "name", "candidates": [], "reason": "not in corpus",
      "ingest_path": "/abs/path.wav" }   // null when the file is not on disk
  ],
  "context_ids": []
}
```

`ingest_path` is the whole point of the unmatched list: those paths go straight back
into `POST /ingest` as roots. **404** if the path does not exist, **400** if the file is
not a readable `.als`.

Note this route hashes every referenced file that exists on disk — see `ableton.md`.

### `POST /session/analyze`
`{context_ids[], distance, k}` → `{distance, fit_floor, corpus_size, count, results[]}`.
Each result carries `fit`, `novelty`, and `components{H,R,P}`. **400** if no supplied id
is known to the corpus, **409** if the corpus is empty.

`fit_floor` is the floor *actually used* after relaxation, not the configured one.

### `POST /chunk/{id}/tag`
`{role}` → manual override, sets `role_source='manual'` and reloads the corpus.

### `GET /chunk/{id}/audio`
Streams the chunk's span as WAV. Imports librosa and soundfile lazily so the rest of the
API stays importable without them.

## Adding a route

- Reload the corpus if you wrote chunks: `state["corpus"] = ingest.load_corpus(conn)`.
- Mirror the response type in `golders-desktop/src/main/api.ts` **and**
  `golders-desktop/src/renderer/src/lib/api.ts` — the two bundles cannot share a module,
  so the types are duplicated by design.
- Add an IPC handler in `src/main/index.ts` and a method in `src/preload/index.ts`;
  the renderer must not fetch directly.
