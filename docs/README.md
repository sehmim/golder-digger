# Docs

Reference material for working on Gold Digger. `README.md` at the repo root states the
idea and the design rationale; `CLAUDE.md` is the orientation page for coding agents.
These files go deeper on one area each.

| File | Read it when |
|---|---|
| [architecture.md](architecture.md) | You need the whole path: a folder on disk → ranked candidates on screen. |
| [scoring.md](scoring.md) | You are touching Fit, Novelty, DISTANCE, or any constant in `config.py`. |
| [data-model.md](data-model.md) | You are writing SQL, adding a column, or wondering what a `chunk_id` is. |
| [api.md](api.md) | You are adding or calling an HTTP route. |
| [ableton.md](ableton.md) | You are working on `.als` parsing or sample resolution. |
| [desktop.md](desktop.md) | You are in `golders-desktop/` — renderer layers, interfaces, state, theme, and IPC. |
| [golden-ui-roadmap.md](golden-ui-roadmap.md) | You need the current user flow, target journey, decisions, or ordered product to-do list. |
| [development.md](development.md) | Setup, running things, and the traps that cost an hour. |

Out of scope everywhere: `golddigger-genai/`.
