# Golden UI roadmap

This is the canonical product-flow and to-do document for Golden UI. Technical
reference documents explain how individual systems work; this file tracks how
those systems become one understandable user journey.

## Product promise

> Given what I am currently making, search my enabled audio folders for sounds
> that fit, then let one knob control how familiar or surprising the suggestions
> are.

```text
workspace folders ──▶ active analyzed library ──┐
                                                ├─▶ fit + novelty ─▶ suggestions
Golden Context ─────────────────────────────────┤
distance knob ──────────────────────────────────┘
```

- **Workspace folders** answer where candidates may come from.
- **Golden Context** answers what candidates must work with.
- **The knob** answers how familiar or surprising compatible candidates should be.
- **Suggestions** are the output the user can hear and act on.

The candidate library and Golden Context are deliberately separate. A project
sample can establish context without becoming a candidate source, and disabling a
workspace folder must not erase the context.

## What the application can do today

### Working Gold Digger prototype

The original Gold Digger interface proves the complete technical loop:

1. The user chooses one or more sample folders.
2. The backend walks, hashes, chunks, and analyzes their audio files.
3. The user chooses a saved Ableton `.als` project.
4. The app parses declared tempo and key, resolves referenced audio against the
   analyzed corpus, and ingests reachable references that are still missing.
5. All chunks from resolved project references become context input.
6. The backend gates candidates by musical Fit, targets the knob's novelty
   percentile, and diversifies the result set.
7. The UI lists candidate chunks and can audition each one alone or over a
   tempo-aligned context preview.

This is a functional engineering path, not the intended final product experience.
It has no explicit input-selection model or final handoff action, and much of its
project orchestration remains inside that interface.

### Golden UI today

Golden UI currently supports the beginning of the intended experience:

1. The user can add and inspect analyzed workspace folders.
2. Folders can be enabled, disabled, retried, or removed from the workspace.
3. The user can open Context Selector and choose a saved Ableton `.als` project.
4. The shared application state receives the resolved project.
5. Golden UI summarizes available tempo and tonal center, such as `124 BPM · C`.
6. The central knob can be manipulated and styled.
7. Releasing the knob ranks up to 30 candidates and opens a blurred, scrollable
   results layer with one visible row per source file.

Golden UI does not yet ingest missing project references, define included audio
inputs, audition suggestions, export exact chunks, support native file dragging,
or provide a completion action.

### Supporting surfaces

- Settings changes the persisted Golden knob appearance.
- Folder Manager edits the shared folder workspace without deleting source audio
  or cached analysis.
- Dev is a separate observer window. Its Files tab reads analyzed file summaries;
  its Context tab shows saved-project facts and referenced-audio resolution.
- The original and Golden interfaces share application state, but their project
  connection orchestration is not yet unified.

## Golden Context

Golden Context is the musical reference that Gold Digger compares possible
suggestions against. Its three core parameters are:

1. **Audio inputs** -- the included sounds from the current project.
2. **Tempo** -- the project BPM.
3. **Tonal center** -- the central pitch, without requiring a scale or mode.

Project name, source path, confidence, match method, loading status, and provenance
support those parameters but are not themselves Golden Context.

The first source is a saved `.als` file. The state boundary should remain neutral
enough to support a live DAW connection or manually chosen reference audio later.
Audio-input inclusion is intentionally unresolved: referenced audio is observable
in Dev, but the product does not yet claim it has been selected by the user.

## Target first journey

The first complete Golden UI journey should be:

1. **Prepare library** -- register folders and wait for analysis.
2. **Establish context** -- choose a saved project and understand whether it is usable.
3. **Confirm inputs** -- know which project sounds form Golden Context.
4. **Explore** -- turn one knob toward familiar or surprising compatible sounds.
5. **Choose** -- see and audition a small set of suggestions.
6. **Use** -- take one clear action that moves the chosen sound into the user's work.
7. **Return** -- reopen the application without unexpectedly losing the workspace.

## Gap map

| Journey stage | Truth today | Needed for Golden UI |
|---|---|---|
| Library | Persistent folder workspace and active-root filtering work. | Clear empty/busy/error behavior in Golden UI. |
| Context source | Golden UI can choose and resolve a saved `.als`. | Shared connection lifecycle instead of interface-owned orchestration. |
| Context inputs | Every matched project chunk is usable by the prototype. | Decide automatic inclusion versus explicit selection. |
| Tempo and center | Saved-project values are parsed and summarized. | Define fallbacks, provenance, partial state, and refresh behavior. |
| Knob | Five detents map to novelty 10, 30, 50, 70, and 90; release commits ranking. | Define disabled behavior and durable query ownership. |
| Suggestions | Golden UI overlays a scrollable, file-deduplicated ranked list. | Add auditioning and prepare exact chunk files for dragging. |
| Listening | Prototype auditions alone or over context. | Bring the chosen behavior into Golden UI. |
| Completion | No final handoff exists. | Choose one first action such as reveal, copy path, or drag. |
| Persistence | Folder intent and knob style persist. Context does not. | Decide context persistence and revalidation. |

## Ordered implementation milestones

### 1. Unify project connection and context lifecycle

- [x] Add a minimal Golden UI context control.
- [x] Reuse the existing `.als` chooser and parser.
- [x] Resolve referenced audio against the analyzed corpus.
- [x] Show saved-project facts and resolution details in Dev.
- [ ] Move project loading, missing-reference ingestion, and refresh behavior out
      of `ProjectStep` into shared application logic.
- [ ] Replace the shared `project` field with, or wrap it in, a neutral Golden
      Context model with source, status, observations, and provenance.
- [ ] Define empty, loading, ready, partial, stale, and failed states.

### 2. Define audio-input inclusion

- [ ] Decide whether all matched project samples are included automatically.
- [ ] Decide whether individual references can be included or excluded.
- [ ] Represent available and included inputs separately in shared state.
- [ ] Keep missing and unresolved references visible in Context Selector and Dev.
- [x] Ensure candidates never return the same source files used as context.

### 3. Connect the Golden knob and suggestions

- [ ] Quiet or disable the knob until usable context and active candidates exist.
- [ ] Move the Golden knob value into the appropriate shared query state.
- [x] Map it to backend novelty without reanalyzing audio.
- [x] Snap the Golden knob to five detents at novelty 10, 30, 50, 70, and 90.
- [x] Rank once when the user releases the knob.
- [x] Cache completed rankings per context, corpus, active folders, and detent so
      returning to a previously visited position is immediate.
- [x] Preserve Fit as a gate before novelty is considered.
- [x] Show one initial row per source file, ordered by its highest-ranked chunk.
- [x] Prevent duplicate visible suggestions from the same file.
- [x] Overlay a minimal scrollable result list without unmounting the knob UI.
- [x] Show loading, empty, and failure states with a Back path.

### 4. Listen and complete the task

- [ ] Audition a suggestion on its own.
- [ ] Audition it against Golden Context at project tempo.
- [ ] Render each ranked chunk to a temporary WAV for truthful native dragging.
- [ ] Drag the prepared WAV from Electron into a DAW.
- [ ] Choose the first completion action: reveal in Finder, copy path, drag into
      the DAW, or another explicit handoff.
- [ ] Handle missing or moved source audio honestly.

### 5. Returning-user behavior and resilience

- [ ] Decide whether the selected context persists across restarts.
- [ ] Revalidate persisted project and folder paths on launch.
- [ ] Detect when a saved project changes and offer or perform a refresh.
- [ ] Communicate that unsaved DAW changes are absent from a saved `.als` source.
- [ ] Define behavior when every folder is disabled or no project references resolve.
- [x] Keep cached analysis separate from removable workspace records.

### 6. Validate the real product

- [ ] Run ingestion with real extraction instead of `GOLDDIGGER_MOCK=1`.
- [ ] Confirm that knob movement produces a musically meaningful progression.
- [ ] Test ranking speed against a large real corpus.
- [ ] Tune Fit, novelty bandwidth, and diversity by listening rather than UI feel.
- [ ] Test the complete journey with real projects, missing samples, and moved files.

## Decisions

Settled for the first iteration:

- Saved `.als` is the first Golden Context source.
- Empty Golden UI shows `Select context`.
- Ready Golden UI shows the project name with tempo and tonal center beneath it.
- Tonal center does not require major, minor, or mode in the compact UI.
- Context Selector is a shell-level modal, not another primary interface.
- Successfully choosing a project closes Context Selector and returns to the knob.
- Dev contains detailed context truth that would clutter Golden UI.
- Folder removal means remove from workspace, never delete source audio or analysis.

Intentionally open until tested:

- Automatic versus manual project-input inclusion.
- Scale and mode presentation.
- Conflict resolution between future context sources.
- Context persistence.
- File-level versus chunk-level suggestions.
- The first useful handoff action.

## Definition of done

The first Golden UI journey is complete when a user can prepare a library, establish
understandable context, use the knob to receive musically useful suggestions,
audition one, complete a clear handoff, and return without unexpected data loss.

## Guardrails

- The knob remains the primary creative interaction.
- Folder and context management remain supporting layers.
- UI must not present inferred, stale, or runtime information as persistent truth.
- Active candidate folders and Golden Context remain separate concepts.
- Golden UI consumes shared state and never depends on another interface.
- Detailed diagnostics belong in Dev, not in the minimal product surface.
- Mock extraction proves plumbing, not recommendation quality.
