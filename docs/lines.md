# Lines: the transit model

`goldigger/lines.py`, `POST /session/lines`, `golddigger lines`, and
`TransitMap.tsx` in the desktop app.

## The problem it solves

DISTANCE answers *how far*. It cannot answer *far in what respect* — and that is
not an interface omission, it is a property of the number. Novelty is one
percentile over one 512-dimensional space, so a chunk at the 90th percentile might
be there because its notes are alien, or its tempo is, or its texture is, and the
dial has collapsed those into a single scalar before the UI ever sees it.

DIGLINE names the fix as novelty computed over whichever dimensions are unlocked,
`N = Σ_{k ∈ unlocked} w_k d_k`. A **line** is that with exactly one dimension
unlocked, which is also the thing that makes it drawable:

> You are standing at a station — your session. Four coloured lines lead out of
> it. Riding one takes you somewhere further away *in that respect and no other*.

Fit still gates every stop. So the far end of a line is strange **and still
works**, which is the entire product claim in one picture.

## The four lines

| Line | Colour | Distance measured | Where the same idea lives in Fit |
|---|---|---|---|
| harmony | green | chroma cosine + circle-of-fifths, weighted as `W_CHROMA`/`W_COF` | the `H` term |
| groove | orange | ratio-aware tempo distance in octaves — the `d` inside `tempo_score` | the `R` term |
| timbre | blue | Euclidean distance over standardised spectral descriptors | *nothing* — new |
| character | yellow | cosine distance in CLAP space | what DISTANCE has always measured |

Green, orange and blue re-read terms the engine already computes; the point is
that they are read as *distances* rather than compatibilities, so they can be
ranked instead of merely gating.

The colours are Montreal's, and they are semantic tokens all the way to the CSS —
the API returns `"green"`, never a hex value. `theme.css` is the only place a line
becomes a pixel.

### Timbre was measured all along

`chunks.spectral` has held centroid / rolloff / bandwidth / flatness per chunk
since `features.spectral_stats` was written. It was never loaded into `Corpus`.
`Corpus.spectral` now loads it and `timbre_vectors()` standardises it, which
closes DIGLINE's cheapest real gap.

Two decisions inside that standardisation are worth knowing:

- **All four descriptors are logged** (`config.TIMBRE_LOG`), because all four are
  ratio quantities. For the Hz ones this is the familiar argument: the ear hears
  brightness ratios, not hertz differences, and 200 → 400 Hz is the same move as
  4 → 8 kHz. Flatness needs it more than any of them — it is a ratio of means,
  spans 2e-10 to 0.94 across a real library, and is conventionally read in dB.
  Left linear it took **92% of the squared distance**, which made the blue line a
  spectral-flatness line wearing a timbre label; every far stop was simply the
  noisiest thing in the corpus. Logged, the four contribute 22 / 24 / 29 / 25.
  `test_no_single_descriptor_owns_the_timbre_line` is the guard, and it fails at
  0.84 against the old constant.
- **Median and MAD, not mean and standard deviation.** One hyper-bright oddity in
  a library should not restate every other chunk as "average".

The result is cached on the corpus (`corpus._timbre`) for the same reason
`role_codes` is: the statistics are over the whole library, so computing them per
request would make them change with the candidate set.

## What a stop is, and what `position` is not

A stop is a chunk that (a) cleared the Fit gate, (b) is not from a context file,
(c) is inside the active folder roots, and (d) has that line's dimension actually
measured.

`position` is that chunk's percentile **within this line's own pool**. Percentile
rather than raw magnitude for the reason `novelty_all` gives: a cosine distance of
0.4 means nothing on its own and means something different in every library.

So a stop at 0.9 on green is far in harmony and says **nothing whatsoever** about
its timbre. `position` is not the DISTANCE dial, is not comparable across lines,
and is not comparable between two different sessions.

Stops are chosen at `LINE_STOPS` targets spread evenly between `LINE_STOP_MIN` and
`LINE_STOP_MAX` — not at the extremes, because the very ends of a percentile are
where the measurement errors live. Each pick takes a `LINE_REDUNDANCY` penalty for
resembling something already picked, the same MMR idea `select` uses: six stops
that are all the same loop is a line with one stop on it.

## Failure is drawn, not swallowed

Three ways a line can come up short, each visible in the payload:

- **`available: false`** — nothing on this line was measurable. A MIDI-only
  context has no sound, so it has no place in descriptor space and the timbre line
  is empty. Drawn greyed out, because "your library cannot answer this yet" is
  information.
- **`fit_floor_relaxed`** — the gate had to open below the preset's floor to find
  enough stops. Each line relaxes **independently**: a thin pool on timbre is not
  a reason to lower the bar on harmony. The UI shows a "gate opened" badge,
  because from the drawing alone a relaxed line and a held one are identical. The
  relaxation itself is `scoring.relax_floor`, shared with `select` so the two
  cannot drift, and it never goes below `FIT_FLOOR_MIN`.
- **NaN, not zero** — a chunk with no tempo has no position on the groove line. It
  drops off rather than ranking as maximally similar, which is what a zero would
  quietly claim.

## `why` is faithful by construction

DIGLINE is explicit that "Fit: 83%" is worse than useless — 83 has no calibrated
meaning. Each stop instead carries a `why` generated from the term that *actually*
moved it out.

The harmony label is the one worth reading the code for. It has two terms, so it
compares their contributions and names the winner:

```python
from_chroma = config.W_CHROMA * (1.0 - chroma_sim)
from_cof    = config.W_COF * (1.0 - scoring.cof_proximity(a, b))
```

If the interval drove it, you get "a tritone away". If the note content drove it,
you get "few shared notes". If they both did, you get both. What you never get is
a plausible sentence written after the fact — an early version happily said "a
tone up" about a stop whose interval was nearly irrelevant to its distance.

`_timbre_label` had the identical bug and the identical fix. It compared centroid
against flatness alone, so a stop pushed out almost entirely by bandwidth came
back as "brighter". It now takes the largest standardised delta across all four
descriptors and names that one — brighter/darker, more/less top end, wider/
narrower, noisier/purer — prefixed "much" past `TIMBRE_STRONG` deviations. The
distance is Euclidean over all four, so the label has to consider all four.

The character line is the exception, and deliberately so: its `why` is a flat
"further out". CLAP has no axis a producer can name, and the honest thing to do
with an uninterpretable space is say nothing rather than borrow a nearby measured
fact and imply it was the cause.

## Interchanges

A chunk that is a stop on **two** lines is an interchange: far from the session in
two different respects at once. That is precisely the find a single dial can name
but never locate, so it is drawn as a metro map draws one — a longer capsule.

They are rare on a large library, and that is the honest outcome. Four independent
rankings over 14k chunks picking six each collide seldom; when they do, it means
something.

## Relationship to `select`

Nothing here replaces `scoring.select`. The two answer different questions:

|  | `/session/analyze` | `/session/lines` |
|---|---|---|
| asks | one ranked answer at one setting | the whole axis, four times |
| takes | a `distance` | no distance at all |
| novelty | one scalar over CLAP | one per dimension, per line |
| returns | a list | a network |

In the desktop app they are two views of one overlay — Ranked and Map — because
they are two questions about the same context, not two sort orders over one
answer. The map costs its own round trip, taken only when someone asks for it.

## Tunables

All in `config.py`, all guesses to tune by ear:

| Constant | Meaning |
|---|---|
| `LINES` | the (key, colour, blurb) triples, and therefore the drawing order |
| `LINE_STOPS` | stops per line (the API's `stops` overrides, 2–12) |
| `LINE_STOP_MIN` / `LINE_STOP_MAX` | where along the percentile the first and last stop sit |
| `LINE_REDUNDANCY` | penalty for a stop resembling one already picked |
| `TIMBRE_DESCRIPTORS` | which `chunks.spectral` columns are read, in order |
| `TIMBRE_LOG` | which of those are logged before standardising — currently all four |
| `TIMBRE_STRONG` | deviations past which a `why` label says "much" |
