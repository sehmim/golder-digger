"""Five named points on the dial, each a whole scoring posture rather than a position.

DISTANCE alone only moves the novelty target. It cannot make the *gate* more
permissive, so at DISTANCE 92 the strangest thing returned is still the
strangest thing that passed the same compatibility bar as DISTANCE 10 -- and on
a library with weak key evidence that bar is the binding constraint, not the
dial. A preset therefore carries four numbers, not one:

  distance    where in the novelty ranking to aim
  fit_floor   how compatible a candidate must be to be considered at all
  bandwidth   how tightly to hold that novelty target
  role_mode   how hard the instrument term argues against duplication
              (the UI calls this "instrument"; the field keeps the schema's name)

Ordered safest first. `PRESETS[0]` is the one to reach for when the track
already works and needs glue; `PRESETS[-1]` is the one that will hand back
something wrong on purpose.

`notes` is written for the Dev UI and is the honest description, including what
each preset gives up. A preset that only ever gets described by its name teaches
nobody what moved.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from . import config


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    distance: float
    fit_floor: float
    bandwidth: float
    redundancy: float
    role_mode: str
    blurb: str              # one line, for the knob face
    notes: str              # the paragraph, for the Dev UI

    def as_dict(self) -> dict:
        return asdict(self)


PRESETS: tuple[Preset, ...] = (
    Preset(
        key="glue",
        name="Glue",
        distance=10,
        fit_floor=0.55,
        bandwidth=0.10,
        redundancy=0.20,
        role_mode="strict",
        blurb="Nearest thing that still adds a part",
        notes=(
            "Aims at the 10th percentile of CLAP distance, so candidates sound like "
            "material already in the set. The floor is raised to 0.55 -- above the "
            "0.45 default -- so a candidate has to be genuinely compatible in key, "
            "tempo and instrument, not merely not-terrible. The instrument term is "
            "strict: something doing a job the arrangement already has scores 0.12 "
            "and effectively "
            "cannot win. The narrow band (0.10) and low redundancy penalty (0.20) "
            "mean the twelve results will resemble each other; that is the point. "
            "Gives up: any chance of surprise. On a sparse library the floor will "
            "relax anyway and this behaves like Companion."
        ),
    ),
    Preset(
        key="companion",
        name="Companion",
        distance=30,
        fit_floor=0.45,
        bandwidth=0.12,
        redundancy=0.30,
        role_mode="normal",
        blurb="Obvious partner, one step sideways",
        notes=(
            "The default posture, and the only preset whose numbers are the ones the "
            "scoring constants were originally tuned to. Distance 30 sits just "
            "outside the immediately-obvious neighbourhood. Floor stays at 0.45, "
            "instrument at normal (same job 0.25, competing pair 0.6). Use this as "
            "the "
            "reference when judging whether another preset actually changed "
            "anything -- if a preset returns the same twelve files as Companion, its "
            "numbers are not doing work on this library."
        ),
    ),
    Preset(
        key="sideways",
        name="Sideways",
        distance=50,
        fit_floor=0.40,
        bandwidth=0.15,
        redundancy=0.35,
        role_mode="normal",
        blurb="Half the library away, still fits",
        notes=(
            "The midpoint, and the honest test of the whole design: distance 50 "
            "targets the median of the corpus by sound, while the floor only drops "
            "0.05 to 0.40. If results here are both unexpected and usable, Fit and "
            "Novelty really are separable on this library. If they are unusable, the "
            "fit gate is not holding -- check whether the floor relaxed, which the "
            "Dev UI reports per rank."
        ),
    ),
    Preset(
        key="wildcard",
        name="Wildcard",
        distance=75,
        fit_floor=0.30,
        bandwidth=0.20,
        redundancy=0.45,
        role_mode="loose",
        blurb="Wrong on paper, right in the track",
        notes=(
            "Distance 75 with the floor dropped to 0.30 lets through candidates that "
            "disagree on key or sit at an unrelated tempo. The instrument term goes "
            "loose (same job 0.50), so a second pad or a competing lead is now allowed "
            "to win -- which "
            "is often what a stuck arrangement actually needs. Redundancy rises to "
            "0.45 so the twelve spread out instead of clustering around one lucky "
            "region. Gives up: reliability. Expect a third of these to be unusable, "
            "and that is the correct trade at this position."
        ),
    ),
    Preset(
        key="rupture",
        name="Rupture",
        distance=92,
        fit_floor=0.20,
        bandwidth=0.28,
        redundancy=0.60,
        role_mode="off",
        blurb="Break the track on purpose",
        notes=(
            "Distance 92 with the floor at FIT_FLOOR_MIN (0.20) -- the gate is as open "
            "as the engine allows without being removed. The instrument term is off "
            "entirely: every candidate scores 1.0 on it, so it leaves the geometric mean "
            "rather than being weighted down and still quietly voting. The wide band "
            "(0.28) and heavy redundancy penalty (0.60) make the twelve results as "
            "unlike each other as they are unlike the set. This is closest to the "
            "'inverse' baseline in the listening test and should be judged against it: "
            "if Rupture is not preferred to inverse, the fit gate is contributing "
            "nothing at this end of the dial."
        ),
    ),
)

BY_KEY: dict[str, Preset] = {p.key: p for p in PRESETS}

# What `scoring.select` falls back to when no preset is passed. Built from the
# config constants rather than from PRESETS[1] so that changing Companion cannot
# silently change the behaviour every existing caller and test depends on.
DEFAULT = Preset(
    key="default",
    name="Default",
    distance=50,
    fit_floor=config.FIT_FLOOR,
    bandwidth=config.BANDWIDTH,
    redundancy=config.REDUNDANCY,
    role_mode="normal",
    blurb="The config constants, unmodified",
    notes="Not offered in the UI. The behaviour of every call that names no preset.",
)


def get(key: str | None) -> Preset:
    """Look up by key. None means DEFAULT; an unknown key is an error, not a
    silent fallback -- a typo that quietly scored as Default would be invisible."""
    if key is None:
        return DEFAULT
    try:
        return BY_KEY[key]
    except KeyError:
        raise ValueError(
            f"unknown preset {key!r}; expected one of {sorted(BY_KEY)}") from None
