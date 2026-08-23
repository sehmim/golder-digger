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
        ├── Dev
        └── Settings
```

The provider owns information shared by the application: API readiness,
directories represented by ingest jobs, ingest progress, the connected project,
and configuration. The shell owns which interface is visible. Each interface is
a sibling and owns its rendering and navigation state independently.

Current interfaces:

| Interface | Purpose |
|---|---|
| Gold Digger App | Primary product workflow: sources, project, and digging. |
| Golden UI | Experimental one-knob interface. |
| Dev | Truthful inspection of application state and interface diagnostics. |
| Settings | Application configuration, currently including knob appearance. |

## Navigation

- `Command-Option-D` always opens Dev.
- `Command-Option-S` always opens Settings.
- The shared hamburger menu is currently rendered by Golden UI, Dev, and Settings.
- The current interface remains visible but disabled in the menu.

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
