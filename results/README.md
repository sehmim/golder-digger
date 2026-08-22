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
