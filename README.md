# Gold Digger

Point it at a folder of audio. It chunks each file, extracts musical metadata,
and answers: **"what else works with what I already have — at a chosen level of
non-obviousness?"**

## The idea

Two scores, kept separate on purpose:

- **Fit** — *does this work with my session?* Harmony + rhythm + role, combined as
  a **geometric mean** so one catastrophic component can't be masked by two good
  ones. Used as a gate. Never shown as a percentage.
- **Novelty** — *how non-obvious is this?* CLAP embedding distance, converted to a
  **corpus-relative percentile**, because raw cosine distance has no stable
  perceptual meaning.

The **DISTANCE** dial (0–100) is a *target novelty percentile among things that
already fit* — not a similarity threshold. DISTANCE 70 means "show me the 70th
percentile of non-obviousness among compatible candidates."

## Status

Feature extraction runs in **mock mode by default** (`GOLDDIGGER_MOCK=1`):
deterministic synthetic features seeded by file hash, same shapes and ranges as
the real thing. The full pipeline, storage, scoring, and API are real and run end
to end with no model downloads.

Set `GOLDDIGGER_MOCK=0` to use the real extractors (beat-this + CLAP). They are
implemented in `features.py` and have been run end to end on a small
ground-truth set, but not yet over a full library.

## Quickstart

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"

# ingest (mock: ~150 files/second)
.venv/bin/python -m goldigger.cli ingest ~/Music/YourSamples
.venv/bin/python -m goldigger.cli stats

# rank candidates against a context chunk
.venv/bin/python -m goldigger.cli analyze <chunk_id> --distance 70 -k 8

# optional: Essentia second opinion (native on macOS/Linux, Docker on Windows)
.venv/bin/python -m goldigger.cli essentia ~/Music/YourSamples

# or serve the API on :8420
.venv/bin/python -m goldigger.cli serve
```

## API

| Endpoint | |
|---|---|
| `POST /ingest` | `{root}` → background job → `{job_id}` |
| `GET /ingest/status/{job_id}` | `{state, total, done, failed}` |
| `GET /library` | chunks + metadata, filterable by role |
| `POST /session/analyze` | `{context_ids[], distance, k}` → ranked, each with `fit`, `novelty`, `components{H,R,P}` |
| `POST /chunk/{id}/tag` | manual role override |
| `GET /chunk/{id}/audio` | stream the chunk as WAV |
| `GET /health` | mock flag, corpus size |

## Confidence

Every estimate carries how much to trust it, because the tools themselves will
not say. librosa returns *a* key and *a* tempo for a hi-hat one-shot as readily
as for a pad.

| Estimate | Confidence is |
|---|---|
| key | candidate gap x chroma peakedness x **tonalness** |
| tempo | onset-envelope autocorrelation at the tempo's lag, mean-removed |
| spectral centroid/rolloff/bandwidth/flatness/rms/zcr | frame-to-frame stability, `1/(1+CV)` |
| CLAP tags | softmax over the tag vocabulary at T=0.10, so one chunk's tags sum to 1 |
| chords, tuning, danceability, loudness, dynamic complexity | **nothing** — single-pass globals with no per-frame variance to derive one from |

**Tonalness** is the harmonic share of energy from an HPSS split, and it is the
gate that makes the rest honest. Measured on the sample set: pads 0.99, vocal
0.88, hi-hats 0.13-0.30, kick 0.006. Key confidence multiplied by it collapses
for percussion no matter which key the correlation happened to prefer — the kick
above keeps 0.000 of a key it "found".

It is also why the key *guess* got better: chroma is computed on the HPSS
harmonic signal, not the full mix, so transients stop polluting it.

The mean-removal in tempo confidence matters more than it looks. On a raw onset
envelope the DC offset dominates `ac[lag]/ac[0]`, and steady noise scores 0.886
against a metronome's 0.773 — backwards. Mean-removed: 0.752 against -0.069.

## Note content

A key label is lossy. C minor and D# major name an *identical* set of notes, so
two loops that would layer perfectly look unrelated by key alone. The notes
themselves are what compatibility actually turns on, so they are measured and
stored directly.

```bash
golddigger notes EP1_Chord3          # chunk id, or any path substring
golddigger notes <chunk_id> --floor 0.05 --format json
```

```
soundbank\EP1_Chord3_F#Maj7.wav  [chunk 0]  9014f855d81e:0
  tonalness 0.992
    F#  1.000 ##############################  <- present
    A#  0.996 ##############################  <- present
    D#  0.981 #############################  <- present
    G#  0.888 ###########################  <- present
    C#  0.178 #####  <- present
  notes: C#, D#, F#, G#, A#   [5 of 12]
```

Octave is discarded on purpose -- pitch class is what shared-note compatibility
turns on.

**Measured per frame, then aggregated -- never median-collapsed.** A median over
the chunk answers "what is the average harmony here", which deletes any chord
holding a minority of the loop: on a Cm-Cm-Cm-Fm progression it reports only
`C D# G` and the Fm vanishes entirely. Counting frames instead recovers all five
notes, `C D# F G G#`.

So `note_presence` is a **weight, not a flag** -- the share of sounding frames
each pitch class is active in. A note held for three bars scores near 1.0 while
one passed through for half a bar scores ~0.25, which is the difference between
two loops sharing a tonal centre and merely brushing past the same pitch.

Three constants govern it, all in `config.py`:

| | |
|---|---|
| `NOTE_FRAME_THRESHOLD` 0.40 | of that frame's own peak: this note is sounding *now* |
| `NOTE_PRESENCE_FLOOR` 0.15 | share of frames before a note counts as present |
| `NOTE_SILENCE_REL` 0.05 | frames quieter than this share of the loudest do not vote |

The continuous vector is stored, not just the derived set, so `--floor` re-reads
the corpus at a different threshold with no re-analysis.

Two things that are easy to get wrong here:

- `chroma_cqt` is called with **`norm=None`**. It normalizes every frame to peak
  1.0 by default, *silence included*, which leaves the silence gate comparing
  1.0 against 1.0 and lets silent frames vote. Raw magnitudes keep the
  distinction -- measured 93.1 for sounding frames against 2.7 for silence.
- Notes are read off the **HPSS harmonic signal**, not the full mix. Percussive
  energy smears across all twelve bins.

**Percussive material still reports nonsense, on purpose.** A drum loop comes
back as all twelve notes because it genuinely has energy in every bin. The note
set is emitted anyway and paired with `tonalness` -- consistent with the rest of
the confidence work, which reports honestly rather than suppressing. The CLI
prints a warning below 0.15 tonalness. Anything consuming these for matching
should filter on `tonalness` first, or a drum loop will appear compatible with
every tonal file in the corpus.

## Essentia — a second opinion, and a Windows caveat

`golddigger essentia <root>` re-analyses the same folder with Essentia's
MusicExtractor and merges a key second opinion, dissonance, pitch salience,
danceability, and loudness into the corpus.

It is **optional enrichment, not part of ingest.** Ingest stays in-process and
model-only; nothing here is on the Fit/Novelty path.

Essentia has no native Windows build — upstream's docs say Windows requires
cross-compiling from Linux/macOS, which is a different problem from "no wheels
yet". So the runner picks a branch per machine:

| | Essentia | everything else |
|---|---|---|
| macOS / Linux | `pip install essentia` — runs in-process | pip |
| Windows | `mtgupf/essentia:latest`, mounted read-only | pip |

**Mac teammates never install Docker.** One command either way; the branch is
picked inside `essentia_runner.py`. Do not "simplify" this by putting the whole
dev setup in containers — the native path is the point.

Both tools' key answers share the one HPSS tonalness gate, since Essentia
computes no such signal itself. Otherwise they disagree on drums for reasons
that look like a bug rather than like material with no key. On the sample set
the only two files whose keys agree are the two whose filenames state their key
— and they carry the two highest gated confidences.

## Layout

```
goldigger/
  config.py     every tunable, including the scoring constants and tag vocabulary
  db.py         SQLite schema + in-place column migration; vectors are float32 blobs
  features.py   real extraction: beat-this, HPSS tonalness, chroma/Krumhansl key,
                tempo + spectral confidence, CLAP embeddings and zero-shot tags
  mock.py       deterministic fake features seeded by chunk id
  ingest.py     walk, hash-dedupe, chunk, extract, upsert, load corpus
  scoring.py    fit / novelty / greedy-MMR select
  essentia_runner.py   OS-aware branch (native vs Docker) + merge into the corpus
  essentia_extract.py  runs inside the container; stdlib + essentia only
  api.py        FastAPI
  cli.py        ingest | stats | analyze | als | essentia | notes | serve
```

Corpus lives in SQLite; on boot every embedding is loaded into one `(N, 512)`
NumPy array. At a few thousand chunks each query is a single matmul, so moving
the DISTANCE dial re-ranks from cached scores without touching a model.

## Design notes

Things that are the way they are on purpose:

- **Short files pass through whole.** At or under 12 s, or with fewer than two
  downbeats, a file *is* the chunk. Most of a sample library is one-shots and
  single loops that are already the atomic unit; bar-slicing them is destructive.
- **Key confidence is a gap, scaled by tonalness.** Raw correlation is high for
  anything tonal and doesn't discriminate. But a large gap can also happen by
  chance on flat chroma — so it's scaled by how tonal the chroma is at all.
  Without that, drums claim a confident key, and a sample library is full of drums.
- **Role comes from the filename first, CLAP second.** A filename that names its
  role is a human's own label and outranks a classifier. The zero-shot tagger
  only speaks when the filename said nothing — which is most of any library
  organised by catalogue number. It abstains rather than guessing when no role
  clears `TAG_ROLE_MIN_PROB`.
- **Unknown key is neutral, not rejection.** `H = c·raw + (1−c)·0.6`, where `c` is
  the lower of the two key confidences.
- **Tempo is ratio-aware.** 87 BPM against 174 is a match. Raw BPM difference
  wrongly punishes half- and double-time.
- **Role compatibility floors at 0.25**, never 0 — a literal zero annihilates a
  geometric mean and would turn a preference into a hard filter.
- **Novelty percentiles rank across the whole corpus**, not the Fit-passing
  subset. The fit floor relaxes when the pool is sparse, which would otherwise
  silently shift every novelty value for the same context.
- **Selection is greedy (MMR).** The redundancy term compares against what's
  *already picked*, which is undefined in a one-shot top-K.
- **Results never share a file with the context.** Otherwise DISTANCE 10 just
  hands back the neighbouring bars of the clip you already have.

## Not built yet

tension · quality scoring · layer_type · 7-mode detection (major/minor only) ·
onset-pattern correlation in the rhythm term · Preserve locks. None are on the
Fit/Novelty critical path.

Nothing yet *consumes* the new confidences — scoring still treats a 0.9-confidence
tempo the same as a 0.02 one. Weighting Fit by them is the obvious next step and
is deliberately not done here, because it changes ranking behaviour and wants
listening, not a unit test.

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

The acceptance test is `tests/test_acceptance.py`: sweep DISTANCE 10→90 and
assert novelty rises monotonically while fit stays above the floor. Then listen —
`FIT_FLOOR`, `BANDWIDTH`, and `REDUNDANCY` in `config.py` are guesses to tune by ear.
