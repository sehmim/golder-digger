# Gold Digger — roadmap: expansive controls

The framing that makes this a roadmap and not a wishlist: DISTANCE already
proved the interaction. One dial steers *overall* contrast with the session,
among things that fit. The next controls generalize exactly that — every
perceptual axis becomes something you can match or contrast against the
session — and the effect chain closes whatever gap remains. Fit stays the
gate; ears stay the judge.

## Now (weeks 1–2) — measure the new axes

New per-chunk extractors, each with an honest confidence, house-style:

- **Density** — onset rate + spectral-flux activity. Cheap: falls out of the
  librosa pass we already run per chunk.
- **Transient sharpness** — attack time, crest factor, HPSS percussive share
  (the percussive twin of the tonalness we already compute).
- **Fluidity** — the sustain/legato axis: low flux variance, harmonic
  continuity across frames. Roughly the inverse of the two above, but not
  reducible to them (a busy arp is dense *and* fluid).
- **Reverberation amount** — envelope decay slope / early-vs-late energy
  (clarity-style ratio). The research-y one on mixed material.

Validation before UI, same pattern as the filename-truth study: synthetic
ground truth first — convolve dry one-shots with known IRs for reverb, click
trains vs pads for transients and density — so each axis ships with its
accuracy measured or it doesn't ship.

## Next (weeks 3–6) — browse by contrast

- Each axis gets a **bipolar match ↔ contrast dial**, detented like DISTANCE.
  Center = match the session's own measured value (the default target *is*
  your session); dial away from center to demand contrast on that axis.
  "Something that fits, but sparser and drier than what I have."
- Semantics compose with what exists: Fit still gates candidates; the axis
  targets reshape selection *inside* the compatible pool — per-axis target
  bands in the MMR objective, exactly how the novelty band works today.
  DISTANCE stays the master contrast control; the axes are its decomposition.
- UI home: the Golden interface — the big DISTANCE dial ringed by the four
  small axis knobs. One faceplate.

## Later (months 2–3) — chains that close the gap

- **Auto effect-chain building**: compute the delta between a candidate and
  the dialed target on the controlled axes, assemble a preview chain — gain,
  EQ tilt toward the spectral target, transient shaping, reverb send — and
  render it in the audition layer, mixed under the session like previews are
  today. Non-destructive, same philosophy as tempo-stretch: pitch stays
  untouched by default, and any correction is opt-in and labeled, so the
  chain never launders a bad harmonic match into a fake good one.
- **Export the chain into Live**: write the sample plus its device chain into
  the project (device-rack preset beside the sample), so a find lands in the
  session already dressed. We already parse `.als` deeply enough to know
  where it goes.

## Constant threads

Confidence-weighted Fit (deferred on purpose — it changes ranking and wants
listening, not unit tests) · listener studies to tune `FIT_FLOOR`,
`BANDWIDTH`, `REDUNDANCY` · packaging for a distributable build. And the
rule above everything: a new axis ships with its validation, or it doesn't
ship.

## Where this appears today

For the 3-minute pitch this is a **Q&A / backup slide**, not spoken time —
if a judge asks "what's next," the one-sentence answer is: *"Every axis of
the sound becomes a match-or-contrast dial against your session — density,
fluidity, transients, reverb — and an automatic effect chain closes the gap
so the find lands in Live already dressed."* It's also now the "What's next"
section of the submission text.
