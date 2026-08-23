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

The renderer has three layers:

```text
App
└── ApplicationStateProvider       shared information and actions
    └── RendererShell              active interface and interface diagnostics
        ├── GoldDiggerApp          sibling interface
        ├── GoldenApp              sibling interface
        ├── DevApp                 sibling interface
        └── SettingsApp            sibling interface
```

All four interface roots stay mounted. The shell uses `hidden` to expose one at
a time, allowing interface-local state to survive while comparing UIs
back-to-back.

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
      GoldenApp.tsx
      GoldenKnob.tsx
    dev/
      DevApp.tsx
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
- Directory roots represented by tracked ingest jobs.
- Ingest and Essentia job rows, progress, and errors.
- The connected Ableton project (`SessionSet`).
- Application settings, currently the selected Golden knob style.

It also exposes the actions that operate on this information: choose directories,
start ingest, run Essentia, dismiss or clear jobs, connect a project, and select a
knob style.

The `directories` collection is not a persisted folder registry. It is derived
from roots attached to currently tracked ingest jobs. Dev labels it accordingly.

### Shell state

`RendererShell` owns:

- The active `InterfaceId`.
- The latest Gold Digger diagnostic snapshot shown by Dev.
- Shortcut subscriptions and their development fallback.

The destination union and labels live in `shared/interfaceNavigation.ts`, not in
individual interfaces.

### Interface-local state

- Gold Digger owns its current workflow step, leaving panel, transition timers,
  and one-time advancement guards.
- Golden UI owns the knob's current numeric position.
- The shared interface menu owns whether its dropdown is open.

Gold Digger's current step is useful to Dev, but it is not application state. It
is passed to the shell as namespaced `GoldDiggerDiagnostics` and displayed as
interface state.

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

Golden UI is an experimental interface built from a blank canvas. It currently
contains one centered, draggable knob and the shared interface menu. Its knob
position is local UI state; its visual style comes from shared application
settings.

The knob responds to vertical pointer dragging and arrow keys. It has no engine
behavior yet.

### Dev

Dev is the developer-facing view of truthful state. It shows shared application
state and explicitly namespaced Gold Digger diagnostics. It should not manufacture
placeholder values merely to fill the page.

### Settings

Settings owns configuration UI, not the configuration itself. Selecting Classic,
Dark, or Minimal updates shared application settings, which Golden UI consumes.

## Interface navigation

`InterfaceMenu` is the first shared renderer component. Golden UI, Dev, and
Settings currently render it in the top-right. Gold Digger has no interface menu
yet.

The component reads its destinations from the shared registry. It always keeps
the same destination order, disables the current interface, closes after
navigation, closes on outside click, and closes on Escape.

Keyboard destinations are fixed:

| Shortcut | Destination |
|---|---|
| `Command-Option-D` | Dev |
| `Command-Option-S` | Settings |

The focused Electron window captures these combinations in main and sends an IPC
event through preload. The shell also has a renderer `keydown` fallback. The
fallback matters during development because renderer code hot-reloads while a
new main/preload bridge normally requires restarting Electron.

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
| `ingest:start` | invoke | Start ingest and return a job ID. |
| `session:load` | invoke | Resolve an Ableton set. |
| `session:analyze` | invoke | Rank candidates for context and distance. |
| `chunk:audio` | invoke | Return preview WAV bytes. |
| `essentia:start` | invoke | Start an Essentia job. |
| `essentia:summary` | invoke | Return coverage and availability. |
| `ingest:progress` | send | Push a polled job reading to the renderer. |
| `ingest:error` | send | Report that a job poller failed. |
| `api:ready` | send | Report Python startup completion or failure. |
| `dev:toggle` | send | Open Dev. The historical channel name remains. |
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
7. If Dev needs local diagnostics, expose a separately named snapshot rather
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

- Application settings are in memory and are not persisted across launches.
- Packaging still assumes a repository checkout and local Python environment.
- Python exposes no ingest cancellation; dismissing a row only removes it from
  the renderer.
- Golden UI's knob is visual and has no engine action yet.
- Most interface styling still resides in `styles.css`; component and
  interface-specific stylesheet extraction remains future cleanup.
