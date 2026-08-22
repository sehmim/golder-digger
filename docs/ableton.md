# Reading Ableton sets

`goldigger/ableton.py`. An `.als` is gzipped XML. Everything here exists because Live's
format drifted across versions and real archives contain broken files.

## What Live gives that audio cannot

Session **tempo** and (Live 12) declared **key** are ground truth for the *context* side
of Fit — a 0.9s one-shot cannot recover them. `apply_session_context()` applies them and
returns the fields it changed. See `scoring.md` for why this does not fix the corpus side.

## Version variance, all handled by trying every shape

**Tempo.** Live 12 renamed `MasterTrack` → `MainTrack`, and clip/preset `.als` files
have no track at all. The lookup tries both tag names, then falls back to the first
`<Tempo>` that has a `Manual` child — scenes also carry `<Tempo>` without one, so
grabbing the first blindly is not safe.

**Scale.** Live 10 writes `<RootNote>` and a string name (`"Major"`). Live 12 writes
`<Root>` and an integer index into its own scale list. Only indices 0 and 1 are read as
major/minor; every other index yields `mode=None` rather than guessing, because a
mis-ordered table would silently flip the mode.

**Sample paths.** Live 11/12 write a flat `<RelativePath Value="a/b/c.wav">` next to an
absolute `<Path>`; Live 9/10 nested `<RelativePathElement Dir="a">` instead. A set moved
between machines keeps a stale absolute path, so `_candidate_paths()` keeps relative
candidates even when an absolute one is present, ordered most-authoritative first.

**Broken files.** `UnreadableSet` names the offending path for truncated, empty, and
not-actually-gzip files. A real archive contains all three.

## Resolution is three strategies, each labelled

`resolve(conn, als)` tries, per reference:

1. **Content hash** — what ingest deduped on, so it survives a move or rename. If the
   file exists, this is the only attempt: a hash miss on an existing file is a *real*
   miss, not a reason to fall through.
2. **Exact path** against `chunks.path`.
3. **Unique basename**. If more than one file matches, the reference is refused with
   `"basename ambiguous across N files"` rather than guessed.

Every match records the `method` that found it, so a weak match can be audited rather
than trusted. `context_ids` is the flattened chunk ids of every match — all chunks of a
multi-chunk file join the context.

## Cost

Strategy 1 sha256s every referenced file that exists, in 1 MB blocks, whole file. A set
with a couple hundred samples is real seconds of disk. The desktop shows a spinner for
this. If it becomes a problem, cache the hash keyed on `(path, mtime, size)` — the
`files` table is most of that already.

## CLI

```bash
.venv/bin/python -m goldigger.cli als "~/Music/Set.als"
.venv/bin/python -m goldigger.cli als "~/Music/Set.als" --analyze --distance 70
.venv/bin/python -m goldigger.cli als "~/Music/Set.als" --analyze --no-session-context
```

`tests/test_ableton.py` builds fixtures from the FileRef layouts Live 12.2 actually
writes plus the legacy Live 9/10 nesting — extend those rather than inventing a shape.
