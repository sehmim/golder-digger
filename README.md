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

One dial can say *how far* but never *far in what respect* — it has collapsed
every dimension into one number before you see it. So there is a second view.
**Lines** are the same question asked one dimension at a time: your session is an
interchange, and four coloured routes lead out of it — harmony, groove, timbre,
character. Ride green and the notes move away; ride orange and the pulse does.
Fit still gates every stop, so the far end of a line is strange *and still works*.
See [docs/lines.md](docs/lines.md).

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

## Essentia — a second opinion, and a Windows caveat

Essentia's MusicExtractor supplies a key second opinion, dissonance, pitch
salience, danceability and loudness, keyed by file hash in its own table.

**Ingest runs it per file** when the machine can import essentia
(`GOLDDIGGER_ESSENTIA=0` opts out; a Docker-only machine gets one folder-wide
pass at the end of the job), spread over a process pool — it is the slowest thing
in an ingest by an order of magnitude, and it holds the GIL, so threads buy
nothing. `GOLDDIGGER_WORKERS` sets the pool size; the default is cpu_count-1.

**In real mode it runs as a tail, not a gate.** Measured inline it was 47% of
ingest wall time, ahead of chunk rows it never changes — nothing on the
Fit/Novelty path reads it there. So the job publishes the corpus as soon as the
chunks are done and collects the second opinion afterwards, under the same
progress row (`essentia second opinion (i/n)`); a folder ingested with
`GOLDDIGGER_ESSENTIA=0` is healed by the next ingest's tail without re-chunking
anything. Mock keeps it inline because there the chunk rows themselves consume
the record. `golddigger essentia <root>` still exists as a re-run over a folder
that was ingested without it.

Under `GOLDDIGGER_MOCK=1` it is also the only real measurement in the pipeline,
so its key and tempo replace the hash-derived ones on the chunk rows — a 0 BPM
answer means "one-shot" and is stored as NULL rather than as a tempo. Chroma and
the CLAP vector stay synthetic, so Fit's harmony term and Novelty remain fiction
until `GOLDDIGGER_MOCK=0`. In real mode beat-this and librosa stay authoritative
and Essentia goes back to being the second opinion: nothing here is on the
Fit/Novelty path.

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
  cli.py        ingest | stats | analyze | als | essentia | serve
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
- **Novelty percentiles rank across the active candidate corpus**, not the
  Fit-passing subset. Changing enabled folders can therefore change the percentile
  represented by a knob position. The fit floor relaxes when the pool is sparse,
  which would otherwise shift it again according to which candidates passed Fit.
- **Selection is greedy (MMR).** The redundancy term compares against what's
  *already picked*, which is undefined in a one-shot top-K.
- **Results never share a file with the context.** Otherwise DISTANCE 10 just
  hands back the neighbouring bars of the clip you already have.
- **Re-ingesting a finished library costs a stat per file, not a hash.** The
  stored (size, mtime) vouches for the bytes; anything touched, edited, failed,
  or below the current standard (synthetic vectors, a missing second opinion
  under mock) still takes the slow path and gets repaired.

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
