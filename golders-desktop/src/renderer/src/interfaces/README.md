# Renderer interfaces

The detailed reference is [docs/desktop.md](../../../../../docs/desktop.md). This
local file keeps the rules that matter while adding or editing an interface.

Each folder in this directory is a complete renderer UI. Interfaces may consume
the shared application provider and application services, but must not import
components, styles, or navigation state from another interface.

`dev/` is the deliberate exception to the sibling-interface pattern. It is a
separate, read-only Electron window that receives typed snapshots from the primary
renderer and must not initialize its own application provider.

The neutral shell owns which interface is visible and application-level overlays
that must render above multiple interfaces. It keeps every interface mounted so
local UI state survives while comparing interfaces back-to-back.

To add another interface:

1. Create a sibling folder here with its own root component and UI-local state.
2. Read shared data and actions through `useApplication`.
3. Register its identifier and root component in `shell/RendererShell.tsx`.
4. Expose diagnostics separately if Dev needs to observe its UI-local state.

Use the five foundational color tokens in `shared/theme.css`. Borders, hover
states, shadows, and transparency should be derived from those colors. Add a
separate literal only when it carries necessary meaning, such as success or error;
do not copy palette hex values into individual interface styles.
