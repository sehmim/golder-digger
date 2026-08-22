# Desktop app

`golders-desktop/` — Electron + React + TypeScript, bundled by electron-vite.

```
src/
  main/index.ts     window, IPC handlers, job polling, lifecycle
  main/api.ts       spawns Python, health-checks, HTTP client
  preload/index.ts  the entire contextBridge surface
  renderer/src/
    App.tsx         step machine + transition
    steps/          SourcesStep, ProjectStep
    lib/api.ts      response types mirrored from the Python API
    lib/useIngest.ts  ingest jobs as the UI sees them
    styles.css      all styling; custom properties on :root
```

## Process model

`sandbox: true`, `contextIsolation: true`, and **the renderer never opens a socket.**
Main owns the child process and the fetch client; the renderer sees only
`window.desktop.*`.

This is not ceremony. A renderer-side fetch to `127.0.0.1:8420` is blocked by CORS —
which is exactly what happens if you try to preview the renderer in a plain browser
without proxying. In Electron the fetch runs in node, so there is no CORS story at all.

`src/main/api.ts` adopts an already-listening server instead of spawning a second one.
See `architecture.md` for the interpreter resolution and the stale-server trap.

## IPC surface

| Channel | Direction | |
|---|---|---|
| `directory:select` | invoke | multi-select folder dialog |
| `project:select` | invoke | `.als` file dialog |
| `api:status` | invoke | `{ready, error}` |
| `ingest:start` | invoke | `roots[]` → `job_id`, and starts a poller |
| `session:load` | invoke | path → `SessionSet` |
| `session:analyze` | invoke | `(contextIds, distance, k)` |
| `ingest:progress` | send | one per poll, per job |
| `ingest:error` | send | poller gave up |
| `api:ready` | send | Python finished booting (or failed) |

Progress is **pushed, not polled by the UI**. Main polls `/ingest/status` every 400ms
and broadcasts; `useIngest` stitches each reading onto the row that started it, keyed by
`job_id`. A reading for an unknown job is ignored, so several hook instances can coexist.

## UI flow

Two steps, one `phase` state machine in `App.tsx`:

```
sources ──first job finishes──▶ advancing (700ms) ──▶ project
   ▲                                                    │
   └──────────────── back / continue ───────────────────┘
```

During `advancing` both panels are mounted in the same CSS grid cell: the outgoing one
blurs and slides up, the incoming one rises from below. `hasAdvanced` is a ref so the
handoff fires exactly once — returning to step 1 and ingesting more does not yank the
screen away again, which is why the explicit "Continue to your project →" affordance
exists.

**Step 1** starts one job per folder, so each folder gets its own row and its own
progress. **Step 2** loads the set, lists matched and unmatched samples in the same row
component, and offers a single multi-root job for the missing ones. When that job
finishes, `ProjectStep` re-resolves the set and the rows flip.

## Styling

One stylesheet, custom properties on `:root`, no framework and no CSS-in-JS. Ingest rows
and Live-set sample rows share `.selections li` / `.sample-list li` deliberately — the
two lists are meant to read as the same object.

Row states are driven by `data-status` (`scanning` / `ready` / `missing`), not by
conditional class strings.

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
- **No results UI.** "Start digging" calls `/session/analyze` and reports the count and
  fit floor; the ranked list itself is not rendered yet.
