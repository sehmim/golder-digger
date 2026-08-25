# DIGLINE: the research brief, against what is already here

`DIGLINE: How to Build a System for Musically Useful Surprise` is an external
research review of the same product hypothesis this engine implements. This file
exists so the brief is read once and turned into decisions, rather than re-read
every time someone asks "should DISTANCE be a radius?"

Its central conclusion is the design Gold Digger already ships:

> Preserve a minimum level of musical compatibility, then let DISTANCE control the
> target percentile of novelty among the compatible candidates.

So most of the brief is not a change request. It is independent confirmation, plus
a short list of things we have not built and one experiment we have not run.

## Already true here

| Brief's recommendation | Where it lives |
|---|---|
| DISTANCE ≡ target novelty percentile, not raw vector magnitude | `scoring.novelty_all`, `select` |
| Band/annulus selection (`\|Q_N − q\|`), not a maximum radius | `select`, `config.BANDWIDTH` |
| Fit as a gate, not the opposite end of Distance | `config.FIT_FLOOR`, the relax loop in `select` |
| Geometric-style Fit so one catastrophic term is not washed away | `fit_all` |
| Soft tonal evidence, never a hard key exclusion | confidence weighting in `fit_all`, `cof_proximity` |
| Ratio-aware tempo rather than BPM difference | `tempo_score`, `config.TEMPO_RATIOS` |
| Arrangement role as a first-class constraint | `role_compat`, `config.ROLE_MODES` |
| Diversity reranking with a small redundancy penalty | greedy MMR in `select` |
| Context = the whole musical situation, not one reference file | `build_context`, `ableton.py`, `midi.py`, `context_from_rows` |
| No graph, no GNN, no vector database, no UMAP galaxy | deliberately absent |
| Baselines: random, metadata-only, nearest neighbour, inverse similarity | `strategies.py`, `scripts/baselines.py` |
| Blind study on obviousness / compatibility / inspiration / discovery / direction change | `listening.py` — the five scales match the brief exactly |
| In-memory NumPy corpus at this scale | `Corpus` |
| Tempo-aligned audition with pitch correction OFF | `audition.py` — phase-vocoder stretch, `pitch_shifted: False` |

The one place the brief and the repo openly disagree is `golders-plugin/`: the
brief says do not build a DAW plugin until the recommendation principle wins. We
built it anyway, for the hackathon demo. That is a known, accepted divergence, not
an oversight — but it does not count as evidence for anything.

## Real gaps

**1. Novelty is CLAP-only.** The brief's pilot novelty is
`0.70·pct(d_CLAP) + 0.30·pct(d_timbre)`, each independently percentile-normalized.
`novelty_all` uses the CLAP term alone. The timbre half is not missing data:
`chunks.spectral` already holds centroid / rolloff / bandwidth / flatness per
chunk (`features.spectral_stats`), it is simply never loaded into `Corpus`. This is
the cheapest genuine improvement on the list, and it makes "why it's far" say
something a producer can hear.

**2. Nothing explains itself to the user.** `select` returns `fit` and the H/R/P
components, and the brief is explicit that showing "Fit: 83%" is worse than useless
— 83 has no calibrated meaning. What it wants instead is generated from the terms
we already compute:

```
Why it fits:  82% pitch-class overlap · 2:1 tempo relation
Why it's far: timbre 78th percentile · embedding novelty 74th percentile
```

Every phrase traceable to a score component, so explanations are faithful by
construction rather than prose written after the fact.

**3. Distance has no notion of what may vary.** The brief's sharpest reframing:

> Distance tells the system how much permission it has to violate *unlocked*
> expectations.

with `N = Σ_{k ∈ unlocked} w_k d_k` and an optional `Preserve [Harmony] [Groove]
[Role]` control. Presets get partway there (`role_mode` decides how hard role
argues), but there is no per-dimension lock and novelty is not computed over a
selectable dimension set. This answers the standing weakness in "farther": farther
along *which* dimensions?

**4. The dial has never been shown to move a human.** `results/baselines.txt`
shows Gold Digger returns different material from inverse similarity and holds fit
while the dial moves. That is a property of the metric, not of the product. The
listening harness exists and is unrun at any scale. The brief's decision rule is
worth keeping literally:

> If Distance reliably controls obviousness but fails to increase inspiration
> versus nearest-neighbour, random and compatibility-only baselines, do not build
> the product merely because the metric works.

The deliverable is a five-point plot — Distance 10/30/50/70/90 against obviousness,
compatibility, inspiration — not a demo.

**5. Mock mode fakes the very thing under test.** Already recorded in `CLAUDE.md`,
worth restating in this context: under `GOLDDIGGER_MOCK=1` the CLAP vector is
synthesized from the file hash, so novelty — the whole dial — is fiction. No
listening trial may ever be generated from a corpus with `synthetic` rows in it.

**6. Model licensing is unaudited.** We depend on a LAION-CLAP checkpoint. Code
license, checkpoint license and training-data terms are three separate questions,
and the brief flags MERT/MuQ specifically as research models whose weights are
non-commercial. Worth a paragraph in the docs before anything ships.

## Positioning worth taking seriously

The brief's strongest suggested wedge is narrower than "find compatible samples":

> Rediscover your own musical history in ways that fit what you are making now.

Local-library search is established (Sononym, Live 12), and context-aware
compatibility is now commercial prior art (Splice Search with Sound, Output
Co-Producer). What none of them expose is a user-adjustable obvious → remote-but-
coherent continuum over *your own abandoned projects and forgotten ideas*. Gold
Digger is already built on a personal corpus, so this is a framing decision and a
choice of test corpus, not an architecture change.

## Order of work

1. Timbre term in novelty (data already on disk; needs `Corpus.spectral` and a
   percentile-normalized descriptor distance).
2. Faithful explanations from the existing components; stop presenting Fit as a
   number.
3. Run the listening study on a real corpus with real vectors. Everything below is
   downstream of whether the curve exists.
4. Preserve locks + dimension-scoped novelty.
5. Pareto/multi-objective view as a companion to the band, once there are two
   objectives worth trading.

## Not now

Graph traversal, a GNN, typed-edge relations, learned compatibility (COCOLA /
Stem-JEPA), automatic role classification, personalization, UMAP maps. Each is a
reasonable later experiment; each would lock an untested metaphor into the product
if built before the five-point plot exists.

Source: `DIGLINE: How to Build a System for Musically Useful Surprise`, ChatGPT
deep research, August 2026. Its own evidence labels — ESTABLISHED / SUPPORTED
INFERENCE / HYPOTHESIS / SPECULATION — are worth preserving when quoting it: most
of the scoring specifics above are labelled HYPOTHESIS by the brief itself.
