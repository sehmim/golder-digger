"""Every tunable in one place. The scoring constants are guesses to tune by ear."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Where the engine may write: the database and job artifacts. The repo checkout
# is the development default; a packaged app runs from a read-only bundle, so
# Electron points this at its userData directory instead.
DATA_DIR = Path(os.getenv("GOLDDIGGER_DATA", str(ROOT))).expanduser()
DB_PATH = Path(os.getenv("GOLDDIGGER_DB", str(DATA_DIR / "golddigger.db"))).expanduser()

# --- audio ---
SR = 22050                  # analysis rate
CLAP_SR = 48000             # CLAP requires 48k
PREVIEW_SR = 44100          # stable output rate lets one cached session bed serve every candidate
AUDITION_RENDER_CACHE = 128 # decoded + stretched chunks; roughly bounded to a few hundred MB
AUDITION_CONTEXT_CACHE = 8  # recent tempo-aligned session beds
CLAP_MODEL = "laion/larger_clap_music_and_speech"
CLAP_DIM = 512
CLAP_WINDOW_SEC = 10.0      # CLAP audio branch window
CLAP_BATCH = 16
HOP_LENGTH = 512           # onset envelope / autocorrelation frame hop
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

# --- filename ---
# The filename is evidence, not measurement, so it carries a certainty like
# every other estimate here. An explicit unit ("126bpm") is a statement; a bare
# number inferred from position is weaker but still far better than the nothing
# beat tracking returns on a two-second loop.
BPM_MIN, BPM_MAX = 40, 220
FILENAME_BPM_EXPLICIT = 0.95
FILENAME_BPM_BARE = 0.60
FILENAME_KEY_QUALIFIED = 0.95   # "Cm", "F#Maj7" -- the mode is stated
FILENAME_KEY_BARE = 0.55        # "G#", "_A_" -- a root, possibly a take letter
# how many files a word must appear in before it counts as this library's
# vocabulary rather than one file's catalogue number
VOCAB_MIN_FILES = 5

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
# --- zero-shot tagging ---
# CLAP projects audio and text into one space, so a fixed vocabulary turns an
# embedding into readable tags. Softmax over the vocabulary's similarities (not
# raw cosine, which has no stable scale) gives one clip's tags a distribution
# summing to 1. Every ROLE is reachable from some tag, so a library named by
# catalogue number still gets classified when the filename says nothing.
TAG_VOCAB = [
    "a kick drum", "a hi-hat", "a snare drum", "a drum loop / groove",
    "a percussive one-shot",
    "a bass sound", "a sub bass",
    "a lead synth melody", "a plucked melodic instrument",
    "a synth pad", "a warm analog pad", "a string pad", "an acoustic guitar",
    "a piano",
    "an ambient texture or drone", "a field recording",
    "a vocal / acapella", "a choir",
    "a riser or sweep effect", "an impact or transition effect",
    "a dark and moody sound", "a bright and airy sound",
    "a distorted or gritty sound", "a clean and pure tone",
]
TAG_TO_ROLE = {
    "a kick drum": "drums", "a hi-hat": "drums", "a snare drum": "drums",
    "a drum loop / groove": "drums", "a percussive one-shot": "drums",
    "a bass sound": "bass", "a sub bass": "bass",
    "a lead synth melody": "melody", "a plucked melodic instrument": "melody",
    "a synth pad": "harmony", "a warm analog pad": "harmony",
    "a string pad": "harmony", "an acoustic guitar": "harmony", "a piano": "harmony",
    "an ambient texture or drone": "texture", "a field recording": "texture",
    "a vocal / acapella": "vocal", "a choir": "vocal",
    "a riser or sweep effect": "fx", "an impact or transition effect": "fx",
    # timbre words describe the sound but name no role -- deliberately unmapped
    "a dark and moody sound": None, "a bright and airy sound": None,
    "a distorted or gritty sound": None, "a clean and pure tone": None,
}
TAG_TEMPERATURE = 0.10      # sharp enough that a clear winner reads as one
TAG_TOP_N = 5               # how many tags are kept per chunk
TAG_ROLE_MIN_PROB = 0.30    # below this the classifier abstains instead of guessing

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
MOCK = os.getenv("GOLDDIGGER_MOCK", "1") == "1"

# --- ingest ---
# Essentia holds the GIL for the whole of MusicExtractor, so a thread pool buys
# nothing: four stems measured 72.5s serial, 71.8s on four threads, 20.0s on
# four processes. The ingest pool is therefore processes, one file each.
INGEST_WORKERS = int(os.getenv("GOLDDIGGER_WORKERS", "0")) or max(1, (os.cpu_count() or 2) - 1)

# --- essentia ---
# Run the second-opinion extractor as part of ingest rather than as a separate
# pass. On by default: it needs no models, and in mock mode it is the only real
# measurement of key and tempo the pipeline has. GOLDDIGGER_ESSENTIA=0 skips it.
ESSENTIA_ON_INGEST = os.getenv("GOLDDIGGER_ESSENTIA", "1") == "1"

# Whether ingest workers run the whole extraction or only hash and Essentia.
# On: measured 217s -> 73s over 24 real files on 8 cores, because the serial half
# was 89% of the work (Essentia 47%, HPSS 35%, chroma/key 5%). Off restores the
# old split, which is worth having: a worker peaks around 2.7 GB on a long stem,
# so a machine with little RAM and many cores is better off not doing this.
POOL_ANALYZE = os.getenv("GOLDDIGGER_POOL_ANALYZE", "1") == "1"

# --- resolving a Live set ---
# Matching a set's samples to the corpus is almost entirely SHA-256 over the
# referenced audio -- 1.7 GB across 100 refs on a real project, about a second
# warm and far worse cold. hashlib releases the GIL, so this one is threads.
RESOLVE_WORKERS = min(8, (os.cpu_count() or 2))
# (path, size, mtime) -> digest. A knob session re-resolves the same set every
# time the project is reloaded, and nothing about those files has changed.
RESOLVE_HASH_CACHE = 4096

# --- role strictness ---
# How hard the role term argues. `normal` is the original behaviour and the
# numbers above are its source; the other three exist so a preset can trade
# "definitely layers" against "might surprise you" without touching scoring.py.
# A *different* role always scores 1.0 -- these only set the penalties.
#   same    the candidate does the job something in the context already does
#   pair    NEUTRAL_ROLE_PAIRS: different names, same space in the arrangement
#   unknown no role on either side, so the term has nothing to say
ROLE_MODES = {
    "strict": {"same": 0.12, "pair": 0.45, "unknown": 0.45},
    "normal": {"same": ROLE_SAME, "pair": NEUTRAL, "unknown": NEUTRAL},
    "loose":  {"same": 0.50, "pair": 0.80, "unknown": 0.80},
    # every candidate scores 1.0: role stops being part of the geometric mean at
    # all, rather than being weighted down to near-nothing and still voting
    "off":    {"same": 1.00, "pair": 1.00, "unknown": 1.00},
}

# The five presets themselves live in presets.py: they carry names and
# explanatory copy alongside their numbers, which config.py has no business
# holding. They are still tunables -- tune them there, not in scoring.py.
