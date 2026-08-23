# Scoring

All of this lives in `goldigger/scoring.py`; every constant lives in `goldigger/config.py`.
The root `README.md` gives the short rationale — this is the working reference.

## Fit and Novelty are separate constructs

*"Works with"* and *"sounds like"* are different questions. Collapsing them into one
weighted distance is exactly what the DISTANCE dial exists to avoid.

- **Fit** is a gate. It is never shown as a percentage.
- **Novelty** is a corpus-relative percentile, not a raw distance.
- **DISTANCE (0–100)** is a *target novelty percentile among things that already fit*.
  DISTANCE 70 means "the 70th percentile of non-obviousness among compatible candidates."

## Fit = geometric mean of H, R, P

```
F = exp((log(H+ε) + log(R+ε) + log(P+ε)) / 3)
```

Geometric, so one catastrophic component cannot be masked by two good ones.

**H — harmony.** `W_CHROMA · chroma_cosine + W_COF · circle_of_fifths_proximity`, then
softened by evidence:

```
c = min(corpus.kconf, ctx.kconf)
H = c · raw + (1 − c) · NEUTRAL
```

An unconfident key estimate must not hard-exclude anything. `NEUTRAL = 0.6` is the
score used when evidence is *absent* — it is not a rejection.

`cof_proximity` is 1.0 for the same key and 0.0 for a tritone, measured in
circle-of-fifths steps over 6.

**R — rhythm.** `exp(-d / TEMPO_TOL)` where `d` is the smallest `|log2(bpm_x·r / bpm_ctx)|`
over `TEMPO_RATIOS = [1, 2, 0.5, 1.5, 2/3]`. Ratio-aware on purpose: 87 against 174 BPM
is a match, and raw BPM difference would wrongly punish half- and double-time. Missing
tempo returns `NEUTRAL`, not zero.

**P — role.** Complement beats duplication; this is a layering tool, not a search box.
Same role scores `ROLE_SAME = 0.25`, a different role scores 1.0, and pairs in
`NEUTRAL_ROLE_PAIRS` (melody/vocal, harmony/texture, texture/fx) score `NEUTRAL`
because they compete for the same space without being the same role.

`ROLE_SAME` is floored **above zero deliberately**: a literal zero annihilates the
geometric mean and would turn a preference into a hard filter.

## Key confidence is a gap, scaled by tonalness

In `features.estimate_key`, raw Krumhansl-Schmuckler correlation is high for anything
tonal and does not discriminate. Confidence is the *gap* from the winner to the best
competing tonic — but a large gap can happen by chance on flat or noisy chroma, so it is
scaled by `tonalness × TONALNESS_GAIN`. `tonalness` is normalized negative entropy: 0 for
a flat chroma, approaching 1 for a peaked one. Without that second term, drums claim a
confident key, and a sample library is mostly drums.

## Novelty ranks across the whole corpus

`novelty_all()` percentile-ranks `1 − clap·ctx_clap` over **every** chunk, not over the
Fit-passing subset. The fit floor relaxes when the pool is sparse (below), which would
otherwise silently shift every novelty value for the same context.

## Selection is greedy MMR

`select()`:

1. Excludes any chunk sharing a file hash with the context — otherwise DISTANCE 10 just
   hands back the neighbouring bars of the clip you already have.
2. Relaxes `FIT_FLOOR` by `FIT_FLOOR_STEP` until the pool holds `3k` candidates or the
   floor hits `FIT_FLOOR_MIN`. The floor actually used is returned alongside the results.
3. Picks greedily on `-|novelty − q| / BANDWIDTH − REDUNDANCY · max_similarity_to_picked`.

Greedy because the redundancy term compares against what is *already picked*, which is
undefined in a one-shot top-K.

## Tuning

`FIT_FLOOR`, `BANDWIDTH` and `REDUNDANCY` are guesses to tune by ear. The regression
guard is `tests/test_acceptance.py::test_distance_ladder`: sweep DISTANCE 10→90 and
assert novelty rises monotonically while fit stays above the floor.

## Session context overrides inference

`ableton.apply_session_context()` overwrites the inferred `bpm` and `tonic` with what
Live states outright, and returns the list of fields it actually changed. The key is
only trusted when the set has key-awareness on (`InKey`), because a set that never
touched it still reports `Root=0`/`Name=0` — indistinguishable from a deliberate C major.

This fixes the *context* side only. `fit_all` takes `min(corpus.kconf, ctx.kconf)`, so a
corpus of low-confidence one-shots keeps H pinned near `NEUTRAL` no matter how good the
session metadata is.

Both callers apply it now: `golddigger als --analyze`, and `POST /session/analyze` when
given `session_path`.

## The dial is only as real as the embedding

Novelty is a percentile of CLAP distance, so under `GOLDDIGGER_MOCK=1` — where the CLAP
vector is synthesized from the file hash — every notch is arithmetic over noise. The
numbers still move monotonically, which is exactly why this needs saying out loud
rather than being left to the reader.

`chunks.synthetic` records which it was, per chunk, and `Corpus.synthetic` carries it
into scoring; `/health` and `/session/analyze` report the count. Ingest uses the same
column to decide what "already done" means: a real run re-does a file whose vectors
were synthesized, because content-hash dedupe would otherwise skip it and leave the
corpus fiction while reporting every file done.
