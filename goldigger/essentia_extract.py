"""Essentia MusicExtractor features, with a confidence on every estimate.

Runs EITHER natively (macOS, Linux) or inside the mtgupf/essentia container
(Windows) -- essentia_runner.py picks. Both paths execute this same file, so a
result does not depend on which machine produced it.

Deliberately self-contained: stdlib + essentia only, no `goldigger` imports.
The container has this directory mounted read-only and the package is not
installed there, so anything imported from the package would fail. That is why
`stability` and AUDIO_EXTS are duplicated from features.py / config.py -- with
tests asserting the copies stay faithful.

What gets a confidence, and what deliberately does not:
- key       : MusicExtractor's own key_strength. The tonalness gate is applied
              later, in essentia_runner.merge, because it comes from librosa's
              HPSS split -- both tools' key answers share one gate.
- bpm       : bpm_histogram_first_peak_weight, the share of the histogram's
              vote going to the winning tempo. Already a scalar -- an earlier
              version appended `.mean` to this field and silently read null.
- lowlevel  : frame-to-frame stability from the extractor's own mean/stdev.
- danceability, loudness, dynamic complexity, tuning frequency, chords:
              single-pass global measurements with no per-frame variance.
              Reported with no confidence rather than a fabricated one.

    python3 essentia_extract.py <in_dir> <out.json>
"""
import json
import sys
from pathlib import Path

# Mirrors goldigger.config.AUDIO_EXTS -- kept in step by test_essentia.py.
AUDIO_EXTS = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".m4a"}


def stability(mean, std):
    """1/(1+CV). Mirrors goldigger.features.stability; tested to agree."""
    if mean is None or std is None:
        return None
    cv = abs(float(std)) / (abs(float(mean)) + 1e-9)
    return float(1.0 / (1.0 + cv))


def _native(v):
    return v.tolist() if hasattr(v, "tolist") else v


def extract_one(path):
    import essentia
    import essentia.standard as es

    # MusicExtractor narrates every stage to stderr; the runner's own progress
    # line is the only thing worth reading in a batch of thousands
    essentia.log.infoActive = False
    essentia.log.warningActive = False

    features, _ = es.MusicExtractor(
        lowlevelStats=["mean", "stdev"],
        rhythmStats=["mean", "stdev"],
        tonalStats=["mean", "stdev"],
    )(str(path))

    def get(key, default=None):
        try:
            return _native(features[key])
        except Exception:
            return default

    def stat(key):
        return stability(get(key + ".mean"), get(key + ".stdev"))

    return {
        "length_s": get("metadata.audio_properties.length"),
        "sample_rate": get("metadata.audio_properties.sample_rate"),
        # edma is the better-performing profile; krumhansl is the fallback
        "key_key": get("tonal.key_edma.key") or get("tonal.key_krumhansl.key"),
        "key_scale": get("tonal.key_edma.scale") or get("tonal.key_krumhansl.scale"),
        "key_strength_raw": get("tonal.key_edma.strength",
                                get("tonal.key_krumhansl.strength")),
        "chords_key": get("tonal.chords_key"),
        "chords_scale": get("tonal.chords_scale"),
        "chords_changes_rate": get("tonal.chords_changes_rate"),
        "tuning_frequency": get("tonal.tuning_frequency"),
        "bpm": get("rhythm.bpm"),
        # already a scalar: no .mean/.stdev suffix on this field
        "bpm_confidence": get("rhythm.bpm_histogram_first_peak_weight"),
        "beats_count": get("rhythm.beats_count"),
        "danceability": get("rhythm.danceability"),
        "onset_rate": get("rhythm.onset_rate"),
        "average_loudness": get("lowlevel.average_loudness"),
        "dynamic_complexity": get("lowlevel.dynamic_complexity"),
        "spectral_centroid": get("lowlevel.spectral_centroid.mean"),
        "spectral_centroid_confidence": stat("lowlevel.spectral_centroid"),
        "spectral_complexity": get("lowlevel.spectral_complexity.mean"),
        "spectral_complexity_confidence": stat("lowlevel.spectral_complexity"),
        "dissonance": get("lowlevel.dissonance.mean"),
        "dissonance_confidence": stat("lowlevel.dissonance"),
        "pitch_salience": get("lowlevel.pitch_salience.mean"),
        "pitch_salience_confidence": stat("lowlevel.pitch_salience"),
    }


def main():
    in_dir = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    paths = sorted(p for p in in_dir.rglob("*")
                   if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
    results = []
    for i, f in enumerate(paths, 1):
        # relative, not basename: drums/kick.wav and bass/kick.wav are two files
        rel = f.relative_to(in_dir).as_posix()
        print(f"[{i}/{len(paths)}] {rel}", file=sys.stderr)
        try:
            results.append({"rel_path": rel, **extract_one(f)})
        except Exception as exc:
            results.append({"rel_path": rel, "error": str(exc)})

    out_path.write_text(json.dumps(results, indent=2))
    ok = sum("error" not in r for r in results)
    print(f"wrote {ok}/{len(results)} records to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
