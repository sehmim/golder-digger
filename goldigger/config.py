"""Every tunable in one place. The scoring constants are guesses to tune by ear."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "golddigger.db"

# --- audio ---
SR = 22050                  # analysis rate
CLAP_SR = 48000             # CLAP requires 48k
CLAP_MODEL = "laion/larger_clap_music_and_speech"
CLAP_DIM = 512
CLAP_WINDOW_SEC = 10.0      # CLAP audio branch window
CLAP_BATCH = 16
AUDIO_EXTS = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".m4a"}

# --- chunking ---
WHOLE_FILE_MAX_SEC = 12.0   # at or under this, the file is one chunk
BARS_PER_CHUNK = 4
FALLBACK_WINDOW_SEC = 4.0   # used when no beats are found at all
MAX_ANALYZE_SEC = 600.0     # guard against accidental full-album ingests

# --- key ---
# Krumhansl-Schmuckler tonal hierarchy profiles
KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# --- fit ---
FIT_FLOOR = 0.45
FIT_FLOOR_MIN = 0.20
FIT_FLOOR_STEP = 0.05
W_CHROMA = 0.6              # harmony: chroma cosine vs circle-of-fifths split
W_COF = 0.4
NEUTRAL = 0.6               # score used when evidence is absent, not a rejection
TEMPO_TOL = 0.06            # exp(-d/tol); ~1.0 inside 4%
TEMPO_RATIOS = [1.0, 2.0, 0.5, 1.5, 2 / 3]
ROLE_SAME = 0.25            # floored above 0 on purpose: 0 annihilates a geometric mean

# --- novelty / selection ---
BANDWIDTH = 0.15            # width of the target novelty band
REDUNDANCY = 0.35           # mu: penalty for resembling something already picked
DEFAULT_K = 12

# --- roles ---
ROLES = ["drums", "bass", "melody", "harmony", "texture", "vocal", "fx"]
ROLE_KEYWORDS = {
    "drums":   ["drum", "kick", "snare", "hat", "hihat", "perc", "clap", "tom",
                "cymbal", "ride", "crash", "beat", "break", "808", "rim", "shaker"],
    "bass":    ["bass", "sub", "808bass", "bassline", "upright"],
    "melody":  ["melody", "lead", "arp", "riff", "top", "flute", "sax", "trumpet",
                "violin", "pluck", "bell", "marimba"],
    "harmony": ["chord", "harmony", "pad", "keys", "piano", "rhodes", "organ",
                "guitar", "gtr", "strings", "synth"],
    "texture": ["texture", "amb", "ambient", "noise", "field", "drone", "atmos"],
    "vocal":   ["vocal", "vox", "voice", "acap", "sing", "choir", "adlib"],
    "fx":      ["fx", "riser", "sweep", "impact", "downlifter", "uplifter",
                "transition", "whoosh", "foley"],
}
# Pairs that are *different* roles but still compete for the same space.
NEUTRAL_ROLE_PAIRS = {
    frozenset(("melody", "vocal")),      # both want the lead
    frozenset(("harmony", "texture")),   # both want the pad bed
    frozenset(("texture", "fx")),
}
TONALNESS_GAIN = 4.0        # tonalness is small even for clear keys; rescale

# --- mock mode ---
# GOLDDIGGER_MOCK=1 skips beat-this and CLAP entirely and synthesizes deterministic
# features from the file hash. Lets the whole pipeline + API run with no models.
import os
MOCK = os.getenv("GOLDDIGGER_MOCK", "1") == "1"
