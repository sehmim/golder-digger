# Gold Digger Desktop

The Electron desktop client for Gold Digger. It contains several independent
React interfaces that render the same application state in different ways.

## Start developing

From the repository root, start the Python API and Electron together:

```bash
./start.sh
```

Or run only the desktop process when an API is already available on port 8420:

```bash
npm install
npm run dev
```

Personal development launchers and their log layout are documented separately in
[dean/README.md](dean/README.md).

## Renderer architecture

```text
ApplicationStateProvider
        │
RendererShell
        ├── Gold Digger App
        ├── Golden UI
        ├── Settings
        ├── Folder Manager overlay
        └── Direct saved-project chooser

Dev window ← snapshots from the primary renderer
```

The provider owns information shared by the application: API readiness,
persistent folder records, ingest progress, the connected project, and
configuration. The shell owns which primary interface is visible. Each primary
interface is a sibling and owns its rendering and navigation state independently.
Dev is a separate, single-instance observer window and does not create another
application-state provider.

Lightweight application settings are stored as versioned JSON beneath Electron's
per-user `userData` directory. They store folder intent, not runtime analysis
facts. Audio analysis remains in SQLite.

Current interfaces:

| Interface | Purpose |
|---|---|
| Gold Digger App | Primary product workflow: sources, project, and digging. |
| Golden UI | Minimal folders and context, release-to-rank knob, and overlaid results. |
| Settings | Application configuration, currently including knob appearance. |

The current working flow, intended Golden UI journey, open decisions, and ordered
product work are maintained in the [Golden UI roadmap](../docs/golden-ui-roadmap.md).

Dev is a developer tool rather than a primary interface. It displays live state
snapshots while the application remains interactive in its own window. Its left
column shows application state; its larger inspector has Files and Context tabs
for analyzed-library and saved-project details.

## Navigation

- `Command-Option-D` opens or focuses the single Dev window.
- `Command-Option-S` always opens Settings.
- The shared hamburger menu is currently rendered by Golden UI and Settings.
- The current interface remains visible but disabled in the menu.
- Folder Manager is a shell overlay reached beside the Golden UI hamburger, not
  another menu destination.
- Golden UI's upper-left context control opens the saved-project chooser directly.

## Shared UI rules

- Interfaces may consume `useApplication`, but must not import another
  interface's components or local state.
- Cross-interface components belong in `src/renderer/src/shared/components/`.
- Interface destinations and labels have one registry in
  `shared/interfaceNavigation.ts`.
- The five foundational application colors live in `shared/theme.css`.
- Success and error are the only deliberate palette exceptions.

See [the desktop architecture reference](../docs/desktop.md) for state ownership,
IPC, extension rules, and the complete renderer layout.

## Commands

```bash
npm run dev                          # Electron development server
npx tsc --noEmit -p tsconfig.json    # Type check
npm run build                        # Production bundles
npm run package                      # Unpacked application
npm run dist                         # Installer
```

## Packaging a macOS DMG

The app is only half the product — the DMG must also carry the Python engine,
or it is a shell that spawns nothing on any machine without this repo checkout.

```bash
./scripts/package-engine.sh            # assemble resources/engine (~1-2 GB)
./scripts/package-engine.sh --models   # …and bake the CLAP weights in
npm run dist                           # DMG in release/
```

What the packaged app does differently (all in `src/main/api.ts`):

- spawns `Resources/engine/python/bin/python3` instead of the repo venv
- sets `GOLDDIGGER_DATA` to Electron's userData directory, because the bundle
  is read-only — the database and job artifacts land there
- points `HF_HOME` at bundled weights when the engine was built with `--models`;
  without them, CLAP downloads on first run and beat-this fetches its
  checkpoint either way

The DMG is **unsigned**: a downloaded copy needs right-click → Open the first
time, or a Developer ID certificate plus notarization to skip that. Signing the
engine's dylibs (torch needs `disable-library-validation`) is part of that
errand, not this script.
