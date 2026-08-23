# Golden UI roadmap

## Product promise

> Given what I am currently making, search my enabled audio folders for sounds
> that fit, then let one knob control how familiar or surprising the suggestions
> are.

Golden UI should make this journey feel simple even though analysis, context,
ranking, and auditioning happen underneath it.

```text
enabled folders ──▶ active analyzed library ──┐
                                              ├─▶ fit + novelty ─▶ suggestions
current musical context ─────────────────────┤
distance knob ───────────────────────────────┘
```

The folders answer **where to search**. The context answers **what the results
must work with**. The knob answers **how adventurous to be**.

## What exists

- [x] Persistent folder workspace.
- [x] Folder analysis, enable/disable, retry, and removal from workspace.
- [x] Active-folder filtering in the ranking backend.
- [x] Minimal Golden UI with a visual knob and folder strip.
- [x] Shared application-state provider.
- [x] Separate Dev window for inspecting state and analyzed files.
- [x] Existing Gold Digger prototype for `.als` parsing, ranking, and auditioning.

The Golden knob is still visual only. Golden UI does not yet establish musical
context, request suggestions, display results, or audition them.

## Current focus: musical context

Golden Context is the musical reference that Gold Digger compares possible
suggestions against. Its core parameters are:

1. Project audio inputs -- intentionally on hold while their selection model is defined.
2. Tempo -- the project BPM.
3. Tonal center -- the central pitch, without requiring a scale or mode.

Source paths, project names, confidence, matching status, and provenance support
those parameters but are not themselves Golden Context.

The first complete context source should probably be a saved Ableton `.als` set,
because parsing and sample resolution already exist. The state model should remain
neutral so a live DAW bridge or manually selected reference audio can be added
later without rewriting Golden UI.

Current decisions:

- [x] The first source is a saved `.als` file; live Ableton context can follow later.
- [x] Golden UI begins with a minimal `Select context` control.
- [x] A ready context is summarized as tempo and tonal center, such as `124 BPM · C`.
- [x] Dev exposes saved-project facts and referenced-audio resolution in a Context tab.
- [x] Scale/mode and conflicting-source rules remain undecided until they can be tested.

Decisions still to make:

- [ ] Are all matched project samples included automatically?
- [ ] Can the user include or exclude individual project samples?
- [ ] Does the selected project persist across application restarts?
- [ ] How does the app communicate that unsaved DAW changes are not in a saved `.als` file?

## Roadmap

### 1. Establish a neutral context model

- [ ] Represent the context source, project metadata, available inputs, included
      inputs, matching status, and resulting chunk IDs in shared application state.
- [ ] Keep source-specific Ableton data behind a neutral context boundary.
- [ ] Expose the complete context truthfully in Dev.
- [ ] Define empty, loading, ready, partial, stale, and failed states.

### 2. Connect a project in Golden UI

- [ ] Add a minimal project/context control.
- [ ] Reuse the existing `.als` chooser and parser.
- [ ] Resolve referenced audio against the analyzed corpus.
- [ ] Ingest reachable project samples that have not been analyzed.
- [ ] Provide a Context Manager overlay for inspecting and selecting inputs.
- [ ] Keep setup controls secondary to the central knob.

### 3. Connect the knob to ranking

- [ ] Disable or quiet the knob until valid context and active candidates exist.
- [ ] Map the knob to the backend novelty target without reanalyzing audio.
- [ ] Debounce or rank after the user settles on a value.
- [ ] Preserve compatibility as a gate before novelty is considered.
- [ ] Show loading, empty, and failure states without cluttering the main UI.

### 4. Present suggestions

- [ ] Decide whether a visible result represents a file or an individual chunk.
- [ ] Prevent confusing duplicate results from the same file.
- [ ] Design a minimal result list that does not compete with the knob.
- [ ] Show only the metadata that helps someone choose a sound.
- [ ] Make changes in active folders or context refresh results predictably.

### 5. Listen and act

- [ ] Audition a candidate on its own.
- [ ] Audition it against the current project context at the project tempo.
- [ ] Decide the first useful completion action: reveal in Finder, copy path,
      drag into the DAW, favorite, or another explicit handoff.
- [ ] Handle missing or moved source audio honestly.

### 6. Returning-user behavior and resilience

- [ ] Decide which context information persists across restarts.
- [ ] Revalidate persisted project and folder paths on launch.
- [ ] Detect when a saved project changes and offer or perform a refresh.
- [ ] Define behavior when every folder is disabled or no project samples resolve.
- [ ] Keep analysis data separate from removable workspace records.

### 7. Validate the real product

- [ ] Run ingestion with real extraction instead of `GOLDDIGGER_MOCK=1`.
- [ ] Confirm that knob movement produces musically meaningful progression.
- [ ] Test ranking speed against a large real corpus.
- [ ] Tune Fit, novelty bandwidth, and diversity by listening rather than by UI feel.
- [ ] Test the complete journey with real Ableton projects and missing samples.

## Definition of a complete first journey

The first Golden UI journey is complete when a user can:

1. Register audio folders and let Gold Digger analyze them.
2. Connect a musical project as context.
3. Understand which project inputs are being used.
4. Turn the knob toward familiar or unexpected results.
5. See a small, useful set of suggestions.
6. Audition a suggestion in musical context.
7. Take a clear action with the chosen audio.
8. Quit and return without losing the workspace unexpectedly.

## Guardrails

- The knob remains the primary creative interaction.
- Folder management and context setup remain supporting layers.
- UI state must not pretend runtime facts are persistent truth.
- Removing a folder from the workspace never deletes source audio or cached analysis.
- The active candidate library and the musical context remain separate concepts.
- Golden UI consumes shared state; it does not depend on another interface.
- Mock extraction proves plumbing, not recommendation quality.
