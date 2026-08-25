# MIDI as context

`goldigger/midi.py`. The DAW-agnostic half of `ableton.py`: a `.als` names one DAW,
a `.mid` is what every DAW exports.

## Why MIDI outranks audio where it speaks

Everything else in this system estimates. Key comes out of an HPSS split and a
Krumhansl correlation, gated by tonalness because the estimate is only as good as the
material's willingness to have a key at all. Tempo comes out of a beat tracker that
returns *a* number for steady noise.

MIDI notes are symbolic. The pitch-class distribution is not an estimate of the
harmony, it **is** the harmony, and `set_tempo` is not a measurement of the tempo, it
is the tempo. That is why `apply_midi_context` is allowed to overwrite the context's
chroma — something the `.als` path never earns, because a Live set states its tempo
and key but says nothing about the notes inside its clips.

Precedence, inferred to stated: resolved chunks → the `.als` header → the MIDI file →
a caller-stated `bpm`. A stated key signature overrides even Live's stated key, which
a confidence comparison alone could not express (`MIDI_KEYSIG_CONFIDENCE` is 0.95 and
Live's key pins `kconf` to 1.0), so `apply_midi_context` tests *statedness*, not just
the number.

## The parser is hand-rolled

Same reason as the `'able'` AIFC decoder in `features.py`: the subset this needs —
`set_tempo`, time and key signatures, note on/off, program changes — is a page of
struct reads, and a dependency would be larger than the code it replaced.

Two decisions worth knowing:

**Running status.** Only channel messages become the running status. The spec says
meta and sysex *cancel* it; real exports (karaoke files, older sequencers) instead
continue the previous channel status across them. Remembering the last channel status
rather than clearing it reads both dialects — and, crucially, stops a `0xFF` from
becoming the running status, which turns the next note-on into a fake meta event
whose velocity byte is read as a payload length and silently eats the rest of the
track. A data byte with no running status at all is an `UnreadableMidi`, not a guess.

**Tempo is the first `set_tempo`.** A DAW export opens with the project tempo; a
ramp's later values are movement *inside* the session, not its anchor. A file with no
`set_tempo` reports `None` rather than the spec's assumed 120 — an assumption is not a
statement, and only statements anchor a context.

## Weights, not counts

Pitch classes are weighted by duration × velocity, so a held pad counts for more than
a passing sixteenth. Channel 10 is excluded from the chroma — drums name no pitch
class — but its share is kept as `drum_share`, because that names a *role*. Notes
still open at the end of a track ring to the track's end rather than being discarded.

Roles come from General MIDI program numbers via `config.MIDI_PROGRAM_ROLES`, which is
deliberately sparse in the same way `ROLE_KEYWORDS` is: a wrong role poisons the
complement-seeking term, a missing one just stays quiet.

## A MIDI-only context borrows its novelty anchor

Fit needs no audio — harmony, tempo and roles are all stated or estimated above. But
Novelty is a distance in CLAP space, and a `.mid` has no sound to embed.
`context_from_midi` therefore anchors on the mean embedding of the corpus chunks that
*fit* this context best: the sound of this session as this library would render it.

That is a borrowed anchor and the API says so — `novelty_anchor: "corpus"` rather than
`"context"`. It is honest, but it is not a measurement of a session the engine never
heard, and the dial must not be presented as if it were.

## Entry points

```bash
golddigger midi idea.mid                 # what the file states
golddigger midi idea.mid --analyze       # rank the corpus against it alone
```

`POST /session/midi` returns the statements; `POST /session/analyze` takes
`midi_path`. See [api.md](api.md).
