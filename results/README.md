# Test-run results

Output from running the pipeline against real material on this machine.
Every number here comes from a command in this repo; nothing is hand-edited.

## Read this first: the features are mocked

All runs below used the default `GOLDDIGGER_MOCK=1`. Feature extraction is
deterministic synthetic data seeded by file hash — **the rankings carry no
musical meaning.** What these runs verify is the mechanism: ingest, chunking,
storage, corpus load, scoring, the DISTANCE band, MMR selection, and the
Ableton resolver all work end to end on real files at real scale.

The giveaway is visible in the data: `Clav_Loop6_86_F.wav` is assigned 174 BPM
and `Organ_Chord1_Bm9.wav` 90 BPM. The filenames carry the true tempo; mock
mode invents its own. Re-running with `GOLDDIGGER_MOCK=0` requires the
beat-this and CLAP checkpoints (~2 GB) and has not been done.

## Corpora

| | Wave Alchemy (Triaz) | Roland Samples |
|---|---|---|
| Path | `~/Music/Wave Alchemy` | `/Volumes/Mac-Storage/Samples/Keys & Synths/Roland Samples` |
| Files / chunks | 8,394 / 8,531 | 2,043 / 2,122 |
| Median duration | 0.86 s | 6.18 s |
| Files bar-sliced | 60 (0.7%) | 36 (1.8%) |
| Drums share of roles | 73% | 44% |

Wave Alchemy is a one-shot library: 99.4% of files are at or under
`WHOLE_FILE_MAX_SEC`, so chunking is a near no-op and beat tracking has
nothing to work with. Measured real key confidence over a 60-file sample was
median **0.004**, with 88% below 0.05 — which pins `H` at `NEUTRAL` through
`H = c·raw + (1−c)·0.6` regardless of the candidate. Roland Samples is loop
material and is the better fit for the design's assumptions.

## DISTANCE sweep

`csv/roland-samples-distance-sweep.csv` — context `c11dee4d031c:0`
(`Organ_Chord1_Bm9.wav`), k=6 at each of five DISTANCE positions.

| DISTANCE | mean novelty | mean fit | min fit |
|---:|---:|---:|---:|
| 10 | 0.107 | 0.648 | 0.526 |
| 30 | 0.298 | 0.630 | 0.527 |
| 50 | 0.501 | 0.626 | 0.539 |
| 70 | 0.697 | 0.588 | 0.532 |
| 90 | 0.902 | 0.606 | 0.526 |

Novelty tracks the requested percentile closely and fit never approaches the
`FIT_FLOOR` of 0.45, so the floor-relaxation path was never triggered. This is
the acceptance property from `tests/test_acceptance.py`, reproduced on real
files rather than fixtures — but see the mock caveat above.

## Ableton session context

`csv/als-session-context-distance70.csv` — a set referencing three real corpus
files, resolved by content hash, then scored with and without Live's stated
tempo and key.

| | context BPM | top-5 `R` | top hit |
|---|---|---|---|
| With session context | 92 (stated in the set) | 0.589 / 0.164 | 90 BPM |
| `--no-session-context` | 174 (inferred from corpus) | 1.0 / 0.19 | 150 BPM |

Live's tempo makes the rhythm term discriminate. `H` moved from ~0.61 to ~0.70
and no further, because `fit_all` uses `min(corpus.kconf, ctx["kconf"])` — the
session key cannot lift harmony past what the corpus side supports.

## What is still unmeasured

No baselines exist yet: random, metadata-only, nearest-CLAP-neighbour, and
inverse-similarity (progressively farther neighbours with no compatibility
gate). Until the last one is run, nothing here distinguishes this system from
sorting a similarity list backwards.

## Real extraction, measured against filename ground truth

`real-vs-mock-validation.txt`. 202 files through beat-this + LAION-CLAP on MPS,
0 failed, 73 s (~0.36 s/file). Scored against BPM and key parsed out of the
filenames by `scripts/filename_truth.py`, with the same harness run over mock
features as a chance-level control.

| Measure | chance | mock | real |
|---|---:|---:|---:|
| Tempo, exact ±2% | 3% | 6.7% | **23.1%** |
| Tempo, ratio-aware | 12% | 16.4% | **40.4%** |
| Key, pitch class | 8.3% | 9.3% | **38.3%** |
| Key, pitch class + mode | 4.2% | 1.6% | **21.0%** |
| `key_confidence` separation | 0 | −0.0037 | **+0.0654** |

The last row is the load-bearing one. `key_confidence` claims to be high when
the key estimate is right; on mock features the separation is negative, i.e.
the number is noise. On real features correct estimates carry 0.155 against
0.090 for wrong ones — so the confidence is informative, which is what makes
`H = c·raw + (1−c)·NEUTRAL` a meaningful fallback rather than an arbitrary one.

Beat-this is clearly fallible: on `EP1_Loop01_76_Cm.wav` it reported 51.7 BPM
against a filename that says 76. 23.1% exact is well above chance and well
below trustworthy.

## Page

`what-changed.html` — the original brief line by line against what exists now,
published at https://claude.ai/code/artifact/5d693ae2-5f09-4687-8aeb-636c66cedea6

## Full real-mode ingest

2,041 files through beat-this + LAION-CLAP on MPS in ~13 minutes; **2 failed**,
both `.m4a` — `config.AUDIO_EXTS` advertises the extension but libsndfile
cannot decode AAC, so `load_audio` raises. Mock mode hid this: `sf.info` fails
the same way but the `except` defaults duration to 8.0, so the file entered the
corpus with fabricated features.

| Measure | chance | mock | real (2,041 files) |
|---|---:|---:|---:|
| Tempo, exact ±2% | 3% | 6.7% | **48.5%** |
| Tempo, ratio-aware | 12% | 16.4% | **58.8%** |
| Key, pitch class | 8.3% | 9.3% | **45.3%** |
| Key, pitch class + mode | 4.2% | 1.6% | **13.3%** |
| `key_confidence` separation | 0 | −0.0037 | **+0.2102** |

Correct key estimates carry 0.277 confidence against 0.067 for wrong ones — a
4× ratio. That is the property `H = c·raw + (1−c)·NEUTRAL` depends on, and it
now holds.

**The 202-file subset was not representative.** Tempo exact went 23.1% → 48.5%,
key pitch class 38.3% → 45.3%, but pitch class + mode fell 21.0% → 13.3%. Mode
detection is the weak half, and the small sample flattered it.

**Role tagging is worse than the mock run suggested.** Mock filled unmatched
files with `mock.role()`, which manufactured a balanced-looking distribution.
Real tagging is filename-only, and leaves **428 of 2,181 chunks (20%) with no
role at all**; texture drops from 69 to 4 and vocal from 54 to 2.

### Sweep on real features

`csv/roland-real-features-sweep.csv`, context `372e5978f706:0`
(`DKT1_18_126bpm_ Pad_F#.wav`, key confidence 0.795).

| DISTANCE | mean novelty | mean fit | mean H | min fit |
|---:|---:|---:|---:|---:|
| 10 | 0.096 | 0.567 | 0.490 | 0.467 |
| 30 | 0.305 | 0.617 | 0.551 | 0.465 |
| 50 | 0.500 | 0.660 | 0.531 | 0.533 |
| 70 | 0.700 | 0.678 | 0.604 | 0.494 |
| 90 | 0.899 | 0.712 | 0.600 | 0.712 |

The harmony term finally moves. On mock features `H` sat pinned near the 0.6
neutral for every candidate; with a confident context and real corpus
confidences it ranges 0.490–0.604, meaning harmony is now contributing to the
ranking instead of being a constant.

Note the extractor is still plainly fallible: that context file is named
`126bpm` and beat-this called it 75.0.

## Baselines: is this just inverse similarity?

`scripts/baselines.py` → `baselines.txt`, `csv/baselines.csv`. 60 contexts
(sampled from the 400 highest key-confidence chunks, so the harmony term is
actually exercised), k=8, five DISTANCE positions, 1,800 selections.

**What this can and cannot show.** It cannot show that any strategy is more
*inspiring* — that needs listeners. It can falsify the claim that the
strategies are interchangeable, which is the specific risk the research brief
flags as likely.

| strategy | fit | fit min | below floor | novelty | redundancy | role dup | overlap w/ GD |
|---|---:|---:|---:|---:|---:|---:|---:|
| random | 0.546 | 0.344 | 27.9% | 0.501 | 0.325 | 19.9% | 0.1% |
| metadata (fit only) | **0.758** | 0.750 | 0.0% | 0.440 | 0.554 | 0.0% | 0.4% |
| nearest neighbour | 0.413 | 0.305 | 62.1% | 0.002 | **0.891** | **96.3%** | 0.0% |
| inverse similarity | 0.545 | 0.372 | 26.3% | 0.500 | 0.418 | 18.0% | **26.6%** |
| band, no fit gate | 0.558 | 0.357 | 24.8% | 0.500 | 0.300 | 17.6% | 60.1% |
| **gold digger** | 0.644 | 0.539 | **0.0%** | 0.500 | 0.316 | 5.7% | — |

**The central claim survives.** Gold Digger and inverse similarity overlap on
only **26.6%** of returned items (24–29% across the whole DISTANCE range), so
roughly three-quarters of what the system returns is material that walking
outward in CLAP space does not surface. "Sorting the similarity list backwards"
produces a different answer.

**The gate does measurable work.** At the same achieved novelty (0.500), Gold
Digger holds fit at 0.644 against 0.545 for inverse similarity, and **no
selection falls below `FIT_FLOOR`** where inverse similarity puts 26.3% below
it. The ablation isolates this: keeping the novelty band and the diversity term
but removing only the gate drops fit to 0.558 and pushes 24.8% below the floor,
changing about 40% of the selection.

**Nearest-neighbour retrieval is actively wrong for this task,** which is the
most useful negative result here. It scores the *lowest* fit of any strategy —
below random — because it returns the same role as the context 96.3% of the
time, and `role_compat` floors same-role at 0.25, which the geometric mean then
punishes. Its intra-set redundancy is 0.891: eight near-identical items. A
similarity search hands you another snare when you wanted something to put
*next to* the snare.

**The metadata baseline is the honest competitor.** It posts the highest fit
(0.758) by construction, since it optimises fit and nothing else. But its fit
is flat at 0.758 across every DISTANCE position because it cannot be steered at
all, its redundancy is 0.554, and its novelty is whatever falls out. It is the
"compatible but obvious" option — exactly the thing the product exists to
improve on.

### Fit across the dial

| strategy | 10 | 30 | 50 | 70 | 90 |
|---|---:|---:|---:|---:|---:|
| inverse similarity | 0.480 | 0.501 | 0.551 | 0.584 | 0.608 |
| band, no fit gate | 0.488 | 0.531 | 0.572 | 0.591 | 0.607 |
| gold digger | 0.615 | 0.635 | 0.651 | 0.655 | 0.663 |

Gold Digger holds a fit advantage at every position, largest at the obvious end
(0.615 vs 0.480). Fit does not decay as novelty is dialled up — which means the
dial is not simply trading compatibility away.

**Still missing: a listener.** Every number above is internal to the scoring
model. `FIT_FLOOR`, `BANDWIDTH` and `REDUNDANCY` remain guesses, and tempo-
synced audition — the thing that would let anyone judge a result — still does
not exist.
