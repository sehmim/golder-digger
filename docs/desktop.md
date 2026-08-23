# Desktop app

`golders-desktop/` — Electron + React + TypeScript, bundled by electron-vite.

```
src/
  main/index.ts     window, IPC handlers, job polling, lifecycle
  main/api.ts       spawns Python, health-checks, HTTP client
  preload/index.ts  the entire contextBridge surface
  renderer/src/
    App.tsx         step machine + transition
    steps/          SourcesStep, ProjectStep, DigStep
    components/Knob.tsx  the DISTANCE dial
    lib/api.ts      response types mirrored from the Python API
    lib/useIngest.ts  ingest jobs as the UI sees them
    lib/usePreview.ts audition one chunk at a time
    styles.css      all styling; custom properties on :root
```

## Process model

`sandbox: true`, `contextIsolation: true`, and **the renderer never opens a socket.**
Main owns the child process and the fetch client; the renderer sees only
`window.desktop.*`.

This is not ceremony. A renderer-side fetch to `127.0.0.1:8420` is blocked by CORS —
which is exactly what happens if you try to preview the renderer in a plain browser
without proxying. In Electron the fetch runs in node, so there is no CORS story at all.

`src/main/api.ts` adopts an already-listening server instead of spawning a second one —
but only if `/health` carries the `HEALTH_MARKER` field (`essentia`). An older server
without it is refused with a message instead of being adopted and then 404-ing every
newer route. See `architecture.md` for the interpreter resolution.

## IPC surface

| Channel | Direction | |
|---|---|---|
| `directory:select` | invoke | multi-select folder dialog |
| `project:select` | invoke | `.als` file dialog |
| `api:status` | invoke | `{ready, error}` |
| `ingest:start` | invoke | `roots[]` → `job_id`, and starts a poller |
| `session:load` | invoke | path → `SessionSet` |
| `session:analyze` | invoke | `(contextIds, distance, k)` → `AnalyzeResult` |
| `chunk:audio` | invoke | `chunk_id` → WAV bytes as an `ArrayBuffer` |
| `essentia:start` | invoke | `root` → `job_id`, watched by the same poller |
| `essentia:summary` | invoke | coverage + agreement, and whether it can run here |
| `ingest:progress` | send | one per poll, per job |
| `ingest:error` | send | poller gave up |
| `api:ready` | send | Python finished booting (or failed) |

Progress is **pushed, not polled by the UI**. Main polls `/ingest/status` every 400ms
and broadcasts; `useIngest` stitches each reading onto the row that started it, keyed by
`job_id`. A reading for an unknown job is ignored, so several hook instances can coexist.

Audio arrives as **bytes over IPC, not a URL**. A `<audio src="http://127.0.0.1:8420/...">`
would work in Electron, but it is a second route from the renderer to the API and it
would outlive `contextIsolation` as the only thing keeping the two apart. `usePreview`
turns the bytes into a blob URL and keeps a bounded cache per rendered tempo/mode, because
sweeping the dial or switching solo/context re-lists the same candidates. The Python side
also caches decoded, tempo-stretched chunks and the mixed session bed, so auditioning a
second candidate does not rebuild every context chunk.

## UI flow

Three steps in `App.tsx`. `step` is where you are, `leaving` is the step still mounted
for the length of the handoff:

```
sources ──first job finishes──▶ project ──"start digging"──▶ dig
   ▲                              ▲   │                       │
   └──── back / continue ─────────┘   └───────── back ────────┘
```

During a transition both panels are mounted in the same CSS grid cell: the outgoing one
blurs and slides up, the incoming one rises from below. `hasAdvanced` is a ref so the
handoff fires exactly once — returning to step 1 and ingesting more does not yank the
screen away again, which is why the explicit "Continue to your project →" affordance
exists.

The step machine will not hand over while **any** job is still moving. Ingest now runs
Essentia per file, so a folder is characterised only when its job says finished —
advancing on the first finished row would have shown the project step over a corpus that
was still being written.

**Step 2 is automatic end to end**: resolve the set, ingest whatever it references that
the corpus lacks, resolve again, then hand over to the dig 1.4s later. The buttons stay
as manual overrides. Both automations are guarded by refs keyed on the set's path — a
failed sample cannot loop the auto-ingest, and a set that was already dug never
auto-advances again, so the dig step's back button actually goes back (`dugSet` prop
seeds the card and swaps the passive status line for a "Back to digging" button).

**Step 1** starts one job per folder, so each folder gets its own row and its own
progress. Once a folder is ingested, a **Second opinion** block offers the Essentia pass
over the same roots. Those jobs share the `IngestJob` row type — `kind` separates them,
because an Essentia job reports a phase where an ingest reports a file count — and a
failed pass shows the reason in place of the count rather than raising a banner. **Step 2** loads the set, lists matched and unmatched samples in the same row
component, and offers a single multi-root job for the missing ones. When that job
finishes, `ProjectStep` re-resolves the set and the rows flip. It then hands the whole
`SessionSet` up to `App`, which is what `DigStep` runs on.

**Step 3** is one dial and one list. The knob has eleven detents mapped onto the API's
0-100 novelty percentile: detents rather than a continuous sweep because a producer wants
to say "one notch further out" and be able to get back. Each change re-runs
`/session/analyze` after a 220ms settle, and a generation counter drops the answers to
superseded requests so a fast sweep cannot land out of order. Rows play through
`usePreview`, one at a time.

## Styling

One stylesheet, custom properties on `:root`, no framework and no CSS-in-JS. Ingest rows
and Live-set sample rows share `.selections li` / `.sample-list li` deliberately — the
two lists are meant to read as the same object.

Row states are driven by `data-status` (`scanning` / `ready` / `missing`), not by
conditional class strings.

The knob is CSS, not canvas or SVG: the face is a rotated `div` with a radial gradient,
and the eleven ticks are rotated spans placed by `transform-origin: 50% 0`. It is a
`role="slider"`, so it takes arrow keys, Home and End as well as drag and wheel.

## Commands

```bash
npm run dev                          # electron-vite, spawns the API
npm run build                        # bundle to out/
npx tsc --noEmit -p tsconfig.json    # the only static check; there is no linter
npm run package                      # electron-builder --dir
```

## Not solved yet

- **Packaging.** `config.DB_PATH` points into the repo, and the spawn assumes the repo
  checkout is the app's parent. Both need to change before a distributable build:
  `app.getPath('userData')` for the database, and a bundled interpreter (PyInstaller
  sidecar or similar) instead of `.venv`.
- **Drag-and-drop** of a `.als` opens the picker instead of reading the drop, because
  the browser hands over a filename rather than a path.
- **No cancel.** Python exposes none, so dismissing a running row only hides it.
- **Preview needs the file on disk.** `GET /chunk/{id}/audio` decodes the original
  file with librosa; a sample that moved since ingest returns 500 and the row shows the
  error rather than silently doing nothing.
- **No waveform.** Rows play, but there is no scrub bar and no visual of the chunk.
- **Tags need a re-ingest.** Chunks written before the tag classifier landed have
  `tags = NULL` and `role_source = 'mock'`; the rows simply show no chips until the
  folder is ingested again.
