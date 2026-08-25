# HTTP API

FastAPI in `goldigger/api.py`, served by uvicorn on `127.0.0.1:8420`. Started either by
`golddigger serve` or by Electron main (`golders-desktop/src/main/api.ts`).

Module-level `state` holds the SQLite connection and the in-memory corpus. `_corpus()`
raises **409** when the corpus is empty — that is a normal state for a fresh install,
not an error to hide from the user.

## Routes

### `GET /health`
`{ok, mock, chunks, synthetic_chunks, presets, chunk_peaks, db, essentia}`. Used by
Electron to decide whether to spawn a child process. `essentia` is `native` /
`docker` / `null` — how ingest will characterise files. `chunk_peaks` is the marker
`src/main/api.ts` checks before adopting an already-listening server; move it whenever
this payload gains a field that pins a newer build.

### `POST /ingest`
`{root}` or `{roots: [...]}` — at least one is required. Each entry may be a folder or a
single file. Returns `{job_id}` immediately; the work runs in `asyncio.to_thread`
because extraction is CPU/GPU bound and releases the GIL. Reloads the corpus on finish.

Essentia fills its table as part of the same job, but *when* depends on the mode.
Under mock it runs inline per file, because the chunk rows consume its key and tempo.
In real mode nothing on the Fit/Novelty path reads it, and inline it measured 47% of
ingest wall time — so the job publishes the corpus as soon as the chunks are final and
collects the second opinion as a tail, reporting `essentia second opinion (i/n)` in
`jobs.message`. That tail also heals files ingested with `GOLDDIGGER_ESSENTIA=0`,
without re-chunking them. A Docker-only machine still gets one folder-wide pass at the
end. `POST /essentia` is a re-run, not the only way in. A file Essentia refuses
(silent audio makes MusicExtractor abort) is still ingested; it simply has no row there.

### `GET /ingest/status/{job_id}`
The raw `jobs` row: `{state, total, done, failed, message}`. See `data-model.md`.

### `POST /essentia`
`{root}` → `{job_id}`. The second-opinion pass over an already-ingested folder, run as a
job so the desktop app can watch it on the same poller as an ingest. **503** when the
machine has neither `essentia` nor `docker`.

One subprocess covers the whole folder, so there is no per-file progress: `total`/`done`
are 1 and `jobs.message` names the phase (`extracting` → `merging` → `merged N files`).
A failure is written to the job (`failed=1`, `message`) rather than raised — "docker is
not running" is a condition the UI has to show, not a crash. Records for files that were
never ingested are skipped: the table is keyed by `file_hash`.

### `GET /essentia/summary`
`{mode, files, covered, agree, disagree, no_key}`. `mode` is `native` / `docker` /
`null`, so a UI can disable the button before offering it. `mode: "docker"` only means
the docker CLI is on PATH — the daemon might still be down, which surfaces as a failed
job.

### `GET /library`
`?limit=&offset=&role=` → `{total, count, chunks[]}`, each chunk with `tonic` resolved
to a pitch name.

### `POST /library/files`
`{roots?, limit, offset}` → `{total, count, offset, files[]}`. This is the
human-scale, file-level projection used by the Dev inspector. It groups chunks by
file and reports path, duration, chunk count, average BPM, observed keys and roles,
synthetic-vector status, Essentia coverage, and ingestion time. Results are ordered
by path and paginated; `roots: null` means the full corpus while `roots: []` means
none.

### `POST /folders/status`
`{roots: [...]}` → `{folders: [{root, chunks}]}`. Counts analyzed chunks beneath
each root using path-aware containment. The desktop uses this to reconstruct
runtime availability from the current corpus rather than persisting a status that
could become stale.

### `POST /session/als`
`{path}` → parses a Live set and resolves its samples against the corpus.

```jsonc
{
  "session": { "name", "path", "creator", "tempo", "key", "in_key", "samples" },
  "matched": [
    { "name", "method": "hash|path|basename", "resolved_path", "chunk_ids": [],
      "chunks": 3, "role": "harmony", "role_source": "clap", "bpm": 90.0, "tonic": "C",
      "tags": ["an electric piano", "a warm pad"],
      "essentia": { "key": "C minor", "bpm": 90.1, "danceability": 1.2,
                    "agrees": true } }   // null when the pass never saw this file
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

### `POST /session/midi`
`{path}` → what a standard MIDI file *states*, before it anchors anything.

```jsonc
{
  "path": "/abs/idea.mid",
  "bpm": 174.0,                  // the first set_tempo; null when the file states none
  "beats_per_bar": 4,
  "key": "E minor",
  "key_source": "stated",        // "stated" (key signature) | "estimated" (the notes)
  "key_confidence": 0.95,
  "notes": 128,
  "drum_share": 0.31,            // channel-10 weight share
  "roles": ["bass", "drums"]     // from General MIDI programs
}
```

The DAW-agnostic sibling of `/session/als`: no samples to resolve, so the payload is
just the statements. **400** if the file is not a readable SMF (`UnreadableMidi`
carries the path and the reason), **404** if it does not exist.

### `POST /session/analyze`
`{context_ids[], distance, k, session_path?, midi_path?, context_paths?, bpm?,
active_roots?}` → `{distance, fit_floor, corpus_size, count, results[],
session_context[], context{}, synthetic_novelty, synthetic_chunks, novelty_anchor}`.
Each result carries `fit`, `novelty`, `components{H,R,P}`, plus `role_source` and the
chunk's top three `tags`. **400** if no context was supplied at all or no supplied id
is known to the corpus, **404** if any named file does not exist, **409** if the
corpus is empty.

The context can arrive four ways, and they compose:

| field | what it contributes |
|---|---|
| `context_ids` | resolved corpus chunks — the original path |
| `context_paths` | audio files analyzed on request, never ingested |
| `midi_path` | tempo, key and harmony a MIDI file states |
| `bpm` | a tempo the caller read outright, e.g. a plugin's host transport |

At least one of `context_ids`, `context_paths` or `midi_path` is required. Precedence
runs from inferred to stated: resolved chunks, then the `.als` header, then the MIDI
file (the more deliberate statement — a stated key signature overrides even Live's
stated key), then `bpm`, which is the last word on tempo. `session_context` lists
every field that was overridden, whichever source did it.

`context_paths` is sample matching with no DAW at all: hand the engine a loop, a
bounce, or a stem and it ranks the library against that file directly. The rows are
cached per (path, mtime) — real-mode extraction is seconds of work, and a knob sweep
is several requests against one unchanged file. A context file that *is* in the
corpus is still excluded from its own results by the same-file hash rule.

`novelty_anchor` says what the DISTANCE dial measured against. Novelty is a distance
in CLAP space, so a context needs audio to stand on: `"context"` means the context's
own embedding, and `"corpus"` means a MIDI-only context borrowed the mean embedding
of the corpus chunks that fit it best. A borrowed anchor is honest but it is not a
measurement of a session the engine never heard, and a UI should say so.

`session_path` is the `.als` these chunks came from. Given one, the route calls
`ableton.apply_session_context` exactly as `golddigger als --analyze` does, and
`session_context` lists the fields Live actually overrode (`bpm`, `tonic`). Without it
the context is inferred from whichever samples resolved — which is the accident the
set's own header exists to settle. The parse is cached per (path, mtime): a knob sweep
is several requests against one unchanged file.

`context` is what Fit was actually matched against, so a UI can say "124 BPM, from
Live" rather than leaving the user to guess.

Completed rankings are held in a bounded in-memory cache keyed by corpus identity,
context ids, distance, result count, the path and modification time of every file the
request named (saved set, MIDI file, each context file), the stated `bpm`, and active
folder roots. A five-detent sweep therefore computes each distinct ranking once, and
returning to a previous detent reuses its exact result. Candidate-folder masks have a
separate bounded cache shared across detents. Both caches disappear when the backend
stops; SQLite remains the durable corpus, and a corpus reload or changed `.als` file
cannot reuse an old ranking.

`active_roots` limits candidate rows using path-aware containment. Omitting it or
sending `null` preserves the legacy whole corpus. Sending `[]` deliberately yields
no candidates. Context chunks remain available for building the musical context
even when their files are outside the active candidate roots.

`synthetic_novelty` is true when any ranked chunk's CLAP vector was synthesized from
its file hash (mock mode) or predates the `chunks.synthetic` column. Novelty is a
distance in that space, so the flag is the difference between a measurement and
arithmetic over noise. Read off the corpus, not off `config.MOCK`: a library ingested
under mock stays fiction long after the flag is turned off.

`fit_floor` is the floor *actually used* after relaxation, not the configured one.

### `POST /session/lines`
Same request body as `/session/analyze` minus `distance` and `k`, plus an optional
`stops` (2–12) → `{lines[], interchanges[], preset, fit_floor_requested}`. Same 400 /
404 / 409 conditions, for the same reasons — the context is built by the identical
code path.

Each line is `{key, colour, blurb, stops[], available, fit_floor,
fit_floor_requested, fit_floor_relaxed}`; each stop is `{chunk_id, path, role, bpm,
tonic, fit, position, why}`. See [lines.md](lines.md) for what a line is and why
`position` is not the DISTANCE dial.

Two things a caller must not confuse. `position` is a percentile *within this line's
own pool*, so a stop at 0.9 on green is far in harmony and says nothing at all about
its timbre. And `fit_floor` is per line — each one relaxes its own gate
independently, because a thin pool on the timbre line is not a reason to lower the
bar on harmony. `available: false` means the library cannot answer that line yet
(nothing measured), which is worth drawing greyed out rather than omitting.

There is no `distance`: a route is not scored at a target novelty, it is the whole
axis. Ask `/session/analyze` when you want one ranked answer at one setting.

### `POST /chunk/{id}/tag`
`{role}` → manual override, sets `role_source='manual'` and reloads the corpus.

### `GET /chunk/{id}/audio`
Streams the chunk's span as WAV. Imports librosa and soundfile lazily so the rest of the
API stays importable without them.

## Adding a route

- Reload the corpus if you wrote chunks: `state["corpus"] = ingest.load_corpus(conn)`.
- Mirror the response type in `golders-desktop/src/main/api.ts` **and**
  `golders-desktop/src/renderer/src/application/api.ts` — the two bundles cannot share a module,
  so the types are duplicated by design.
- Add an IPC handler in `src/main/index.ts` and a method in `src/preload/index.ts`;
  the renderer must not fetch directly.
