# Desktop app

`golders-desktop/` is the Electron, React, and TypeScript client. Electron is
bundled by electron-vite; the engine remains a Python FastAPI process.

## Process boundary

```text
React renderer
    │ window.desktop.*
preload context bridge
    │ IPC
Electron main process
    │ HTTP on 127.0.0.1:8420
Python API
```

The renderer never opens a socket. `sandbox: true` and
`contextIsolation: true` remain enabled. Main owns dialogs, API requests, job
polling, and the Python child-process lifecycle. Preload exposes the deliberately
small `window.desktop` surface.

Main adopts a compatible API already listening on port 8420; otherwise it starts
one. See [architecture.md](architecture.md) for the complete engine lifecycle and
[api.md](api.md) for HTTP routes.

## Renderer architecture

The primary renderer has three layers. Dev is a separate read-only renderer:

```text
App
├── ApplicationStateProvider       shared information and actions
│   └── RendererShell              active interface and application overlays
│       ├── GoldDiggerApp          sibling interface
│       ├── GoldenApp              sibling interface
│       ├── SettingsApp            sibling interface
│       └── FolderManager          shell-level overlay
└── DevWindow                      separate Electron window; snapshot observer
```

The three primary interface roots stay mounted. The shell uses `hidden` to expose
one at a time, allowing interface-local state to survive while comparing UIs
back-to-back. Dev never creates its own `ApplicationStateProvider`; the primary
renderer publishes snapshots that Electron main caches and forwards.

An interface may depend on the application layer and shared components. It must
not import UI components, styling, or local navigation state from another
interface.

## Source layout

```text
src/renderer/src/
  App.tsx
  main.tsx

  application/
    ApplicationState.tsx    provider, shared state, shared actions
    api.ts                   renderer-side API response types
    useIngest.ts             ingest jobs and progress events

  shell/
    FolderManager.tsx        folder controls above every interface
    RendererShell.tsx        selects and keeps interfaces mounted

  interfaces/
    gold-digger/
      GoldDiggerApp.tsx
      types.ts
      usePreview.ts
      components/Knob.tsx
      steps/
        SourcesStep.tsx
        ProjectStep.tsx
        DigStep.tsx
    golden/
      FolderStrip.tsx
      GoldenApp.tsx
      GoldenKnob.tsx
    dev/
      AnalysisFilesTab.tsx
      DevApp.tsx
      DevWindow.tsx
      types.ts
    settings/
      SettingsApp.tsx
    README.md

  shared/
    components/InterfaceMenu.tsx
    interfaceNavigation.ts
    theme.css

  styles.css
  vite-env.d.ts
```

## State ownership

State belongs at the lowest layer that truthfully owns it.

### Shared application state

`ApplicationStateProvider` currently owns:

- API readiness and startup errors.
- Persistent folder intent plus analysis and reachability verified at runtime.
- Ingest and Essentia job rows, progress, and errors.
- The connected Ableton project (`SessionSet`).
- Application settings: Golden knob style and persisted folder intent.

It also exposes the actions that operate on this information: choose directories,
start ingest, retry, enable, disable, or remove a folder, run Essentia, dismiss or
clear jobs, connect a project, and select a knob style.

The legacy `directories` collection is now a compatibility view over reachable
folder records. New UI should consume `folders` directly.

### Persistent application settings

Electron main stores a versioned `settings.json` beneath `app.getPath('userData')`.
On macOS this normally resolves beneath `~/Library/Application Support/`. Writes
go to a temporary file and rename into place so an interrupted write cannot leave
partially written JSON.

The file stores user intent only: knob style, registered paths, enabled state,
timestamps, and whether folder filtering has ever been established. Reachability
and analysis status are runtime facts and are never persisted. On launch the
provider validates the settings shape, checks each path on disk, asks the backend
how many analyzed chunks fall below it, and hides unreachable folders.

`folderFilteringEnabled` preserves an important distinction. Before a user has
ever registered a folder, `activeFolderRoots: null` retains the legacy whole-corpus
behavior. After registration, an empty active list means the user has disabled or
removed everything and analysis must return no candidates.

Removing a folder record means removing it from the application workspace only.
It never deletes audio files or cached SQLite analysis.

### Shell state

`RendererShell` owns:

- The active primary `InterfaceId` (Dev is excluded).
- The latest Gold Digger diagnostic snapshot published to Dev.
- Whether Folder Manager is open and which folder it should focus.
- Shortcut subscriptions and their development fallback.

The destination union and labels live in `shared/interfaceNavigation.ts`, not in
individual interfaces.

### Interface-local state

- Gold Digger owns its current workflow step, leaving panel, transition timers,
  and one-time advancement guards.
- Golden UI owns the knob's current numeric position. Its folder strip renders
  shared state and opens the shell overlay; it does not own folder data.
- The shared interface menu owns whether its dropdown is open.

Gold Digger's current step is useful to Dev, but it is not application state. The
shell publishes it under a namespaced `interfaces.goldDigger` snapshot instead of
moving UI-local state into the application provider.

## Interfaces

### Gold Digger App

The primary product interface has three steps:

```text
sources ── ingest ready ──▶ project ── project connected ──▶ dig
```

`SourcesStep` chooses and ingests directories. `ProjectStep` connects an Ableton
set, resolves its samples, and ingests missing files. `DigStep` ranks and auditions
candidate chunks. This workflow and its knob are intentionally isolated inside
`interfaces/gold-digger/`.

### Golden UI

Golden UI is an experimental interface built from a blank canvas. It contains one
centered, draggable knob, a compact recent-folder strip, a Folder Manager trigger,
and the shared interface menu. Folder buttons show short names, keep full paths in
their title, and open Folder Manager focused on the selected record.

The knob responds to vertical pointer dragging and arrow keys. It has no engine
behavior yet.

### Folder Manager

Folder Manager is a shell-level modal overlay, not a fifth interface and not a
hamburger destination. It can render above any sibling without depending on that
interface. The first trigger lives beside Golden UI's hamburger. It supports add,
enable, disable, retry, and “Remove from workspace.” Removal deletes only the
settings record; source audio and SQLite analysis are untouched.

### Dev

Dev is a single-instance Electron window for observing truthful state while the
primary UI remains usable. `Command-Option-D` and the hamburger's Dev destination
open it or focus the existing instance. It is read-only, has no interface menu,
and closes with the primary window.

The primary renderer publishes `{application, interfaces}` snapshots. Electron
main retains the newest snapshot and forwards updates to Dev. This avoids a
second provider, duplicate ingest subscriptions, and state that only appears to
match the primary application.

Its workspace has two columns. The narrower left column renders the live state
snapshot. The wider right column is a tabbed inspector. The first `Files` tab
requests paginated file-level summaries through main rather than embedding the
chunk corpus in application state. Folder filters come from the snapshot, while
the analysis rows come from SQLite through `POST /library/files`.

### Settings

Settings owns configuration UI, not the configuration itself. Selecting Classic,
Dark, or Minimal updates shared application settings, which Golden UI consumes.

## Interface navigation

`InterfaceMenu` is the first shared renderer component. Golden UI and Settings
currently render it in the top-right. Gold Digger and the Dev window have no
interface menu.

The component reads its destinations from the shared registry. It always keeps
the same destination order, disables the current interface, closes after
navigation, closes on outside click, and closes on Escape.

Keyboard destinations are fixed:

| Shortcut | Destination |
|---|---|
| `Command-Option-D` | Dev |
| `Command-Option-S` | Settings |

Electron main captures these combinations in whichever application window is
focused. Dev opens or focuses directly; Settings focuses the primary window and
sends its navigation event. The primary shell also has a renderer `keydown`
fallback. Main and preload changes still require an Electron restart.

## Theme

`shared/theme.css` is the single source of palette truth. It defines five
foundational colors:

```css
--color-background
--color-surface
--color-text
--color-muted
--color-accent
```

Borders, hover states, shadows, disabled states, and transparency derive from
those values. `--color-success` and `--color-error` are explicit semantic
exceptions. Renderer CSS contains no other literal colors.

New interfaces should use these tokens directly. A new literal belongs in the
theme only when it communicates meaning that the five colors cannot.

## IPC surface

| Channel | Direction | Purpose |
|---|---|---|
| `directory:select` | invoke | Multi-select folder dialog. |
| `project:select` | invoke | Ableton `.als` file dialog. |
| `api:status` | invoke | API readiness and startup error. |
| `folders:status` | invoke | Verify analyzed chunk counts for registered roots. |
| `settings:load` | invoke | Load versioned user-level application settings. |
| `settings:save` | invoke | Atomically replace the user settings file. |
| `path:exists` | invoke | Check folder reachability during hydration. |
| `ingest:start` | invoke | Start ingest and return a job ID. |
| `session:load` | invoke | Resolve an Ableton set. |
| `session:analyze` | invoke | Rank candidates within the active folder roots. |
| `chunk:audio` | invoke | Return preview WAV bytes. |
| `essentia:start` | invoke | Start an Essentia job. |
| `essentia:summary` | invoke | Return coverage and availability. |
| `ingest:progress` | send | Push a polled job reading to the renderer. |
| `ingest:error` | send | Report that a job poller failed. |
| `api:ready` | send | Report Python startup completion or failure. |
| `dev:open` | invoke | Open or focus the single Dev window. |
| `dev:snapshot:get` | invoke | Read the newest cached Dev snapshot. |
| `dev:snapshot:publish` | send | Publish primary renderer state to main. |
| `dev:snapshot` | send | Forward a new snapshot to the Dev renderer. |
| `dev:analysis-files` | invoke | Read one paginated page of analyzed file summaries. |
| `settings:open` | send | Open Settings. |

Progress is pushed to the renderer. Main polls the API every 400 ms, and
`useIngest` stitches readings onto jobs started by the UI.

## Adding another interface

1. Create a new sibling directory under `interfaces/`.
2. Give it a root component and keep its rendering state inside that directory.
3. Consume shared information and actions through `useApplication`.
4. Add its ID and label to `shared/interfaceNavigation.ts`.
5. Mount it as a sibling in `RendererShell`.
6. Add the shared menu only when the interface design calls for it.
7. If Dev needs local diagnostics, add them to the typed Dev snapshot rather
   than moving UI state into the application provider.
8. Use the shared theme tokens and add no new literal color casually.

## Development and verification

From `golders-desktop/`:

```bash
npm run dev
npx tsc --noEmit -p tsconfig.json
npm run build
npm run package
```

For the complete stack, use the repository `start.sh`. Personal launchers and
timestamped frontend, backend, and master logs are documented in
`golders-desktop/dean/README.md`.

When main or preload changes, restart Electron before diagnosing a missing IPC
method. Renderer-only edits hot-reload.

## Known limitations

- Packaging still assumes a repository checkout and local Python environment.
- Python exposes no ingest cancellation; dismissing a row only removes it from
  the renderer.
- Golden UI's knob is visual and has no engine action yet.
- Most interface styling still resides in `styles.css`; component and
  interface-specific stylesheet extraction remains future cleanup.
