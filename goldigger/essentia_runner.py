"""OS-aware Essentia runner, and the merge of its output into the corpus.

Essentia is the one dependency in this project with no native Windows build
path -- upstream's own docs say Windows requires cross-compiling from Linux or
macOS, which is a different problem from "wheels are not published yet". So:

    macOS / Linux : `pip install essentia` (or `brew install essentia`) and this
                    runs the extractor in-process. No Docker anywhere.
    Windows       : the same extractor runs inside the official mtgupf/essentia
                    image, mounted read-only.

Mac teammates never install Docker for this. The branch is picked here, so
callers run one command either way.

Essentia characterises whole *files*, not chunks -- MusicExtractor takes a path.
Its rows therefore live in their own table keyed by file_hash and are joined to
chunks by file, rather than being folded into per-chunk columns.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from . import config

DOCKER_IMAGE = "mtgupf/essentia:latest"

_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


# ---------------------------------------------------------------- key mapping

def pitch_to_pc(name) -> int | None:
    """"C#" / "Db" -> 1. None when unreadable.

    None rather than 0: a silent fallback would file every unparseable key
    under C and quietly poison the harmony term for those chunks.
    """
    if not name or not isinstance(name, str):
        return None
    text = name.strip()
    if not text or text[0].upper() not in _PC:
        return None
    pc = _PC[text[0].upper()]
    for ch in text[1:]:
        if ch in "#♯":
            pc += 1
        elif ch in "b♭":
            pc -= 1
        else:
            return None
    return pc % 12


def gated_confidence(key_strength, tonalness):
    """Essentia's own match strength x librosa's harmonic-energy gate.

    Essentia reports no tonalness signal of its own, so both tools are gated by
    the same "does this have a key at all" measurement -- otherwise the two
    disagree on drums for reasons that look like a bug.
    """
    if key_strength is None or tonalness is None:
        return None
    return float(max(0.0, min(1.0, float(key_strength)))) * float(
        max(0.0, min(1.0, float(tonalness))))


def key_agreement(e_key, e_scale, tonic_pc, is_major):
    """Do the two tools name the same key? None when either side has no answer."""
    pc = pitch_to_pc(e_key)
    if pc is None or tonic_pc is None or tonic_pc < 0 or not e_scale:
        return None
    return bool(pc == int(tonic_pc) and (e_scale.lower() == "major") == bool(is_major))


# ---------------------------------------------------------------- runner

def essentia_available_natively() -> bool:
    return importlib.util.find_spec("essentia") is not None


def script_dir() -> Path:
    """The directory mounted into the container. essentia_extract.py imports
    nothing from this package, so mounting it read-only is enough."""
    return Path(__file__).parent.resolve()


def docker_argv(in_dir: Path, out_path: Path, scripts: Path) -> list[str]:
    """The container invocation, as an argument LIST.

    Never build this as a shell string: on Git Bash, MSYS rewrites Unix-style
    absolute paths inside shell words, so "/analysis/essentia_extract.py" turns
    into "C:/Program Files/Git/analysis/essentia_extract.py" and the container
    cannot find its own script. subprocess with a list bypasses the shell
    entirely, which is why no MSYS_NO_PATHCONV workaround appears here.
    """
    return [
        "docker", "run", "--rm",
        "-v", f"{scripts}:/analysis:ro",
        "-v", f"{in_dir}:/in:ro",              # the user's library is never written to
        "-v", f"{out_path.parent}:/out",
        DOCKER_IMAGE,
        "python3", "/analysis/essentia_extract.py", "/in", f"/out/{out_path.name}",
    ]


def run(in_dir, out_path) -> Path:
    """Extract Essentia features for every audio file under in_dir.

    Same extractor either way; only the way it gets an importable `essentia`
    differs per machine.
    """
    in_dir = Path(in_dir).resolve()
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if essentia_available_natively():
        print("essentia found natively -- running in-process (no Docker)",
              file=sys.stderr)
        argv = [sys.executable, str(script_dir() / "essentia_extract.py"),
                str(in_dir), str(out_path)]
    else:
        print(f"essentia has no native build here -- running via {DOCKER_IMAGE}",
              file=sys.stderr)
        argv = docker_argv(in_dir, out_path, script_dir())

    subprocess.run(argv, check=True)
    return out_path


# ---------------------------------------------------------------- merge

def _path_index(conn) -> dict[str, str]:
    """Absolute path (normalised) -> file_hash, for every ingested chunk.

    Case-folded because Windows paths that differ only in case are one file.
    """
    return {str(Path(r["path"]).resolve()).lower(): r["file_hash"]
            for r in conn.execute("SELECT DISTINCT path, file_hash FROM chunks")}


def _librosa_view(conn, file_hash) -> tuple[float | None, int | None, int | None]:
    """(mean tonalness, tonic of the most confident chunk, its mode).

    Mean tonalness across the file, because Essentia's answer is about the whole
    file. The key comes from the single most confident chunk rather than an
    average -- averaging pitch classes is meaningless.
    """
    rows = conn.execute(
        "SELECT tonic_pc, is_major, key_confidence, tonalness FROM chunks"
        " WHERE file_hash=?", (file_hash,)).fetchall()
    if not rows:
        return None, None, None
    tonal = [r["tonalness"] for r in rows if r["tonalness"] is not None]
    best = max(rows, key=lambda r: r["key_confidence"] or 0.0)
    return (sum(tonal) / len(tonal) if tonal else None,
            best["tonic_pc"], best["is_major"])


def merge(conn, records, in_dir) -> int:
    """Fold extractor output into the essentia table. Returns rows written.

    Records for files that were never ingested are skipped, not inserted: the
    table is keyed by file_hash and there is no hash for a file the corpus has
    never seen.
    """
    in_dir = Path(in_dir).resolve()
    index = _path_index(conn)
    now = dt.datetime.now(dt.UTC).isoformat()
    written = 0

    for rec in records:
        if rec.get("error") or not rec.get("rel_path"):
            continue
        key = str((in_dir / rec["rel_path"]).resolve()).lower()
        file_hash = index.get(key)
        if file_hash is None:
            continue

        tonalness, tonic_pc, is_major = _librosa_view(conn, file_hash)
        agreement = key_agreement(rec.get("key_key"), rec.get("key_scale"),
                                  tonic_pc, is_major)
        conn.execute(
            """INSERT INTO essentia (file_hash, path, key_key, key_scale,
                   key_strength, key_confidence, key_agreement, bpm, bpm_confidence,
                   danceability, average_loudness, dynamic_complexity,
                   tuning_frequency, payload, extracted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(file_hash) DO UPDATE SET
                 key_key=excluded.key_key, key_scale=excluded.key_scale,
                 key_strength=excluded.key_strength,
                 key_confidence=excluded.key_confidence,
                 key_agreement=excluded.key_agreement, bpm=excluded.bpm,
                 bpm_confidence=excluded.bpm_confidence,
                 danceability=excluded.danceability,
                 average_loudness=excluded.average_loudness,
                 dynamic_complexity=excluded.dynamic_complexity,
                 tuning_frequency=excluded.tuning_frequency,
                 payload=excluded.payload, extracted_at=excluded.extracted_at""",
            (file_hash, str(in_dir / rec["rel_path"]), rec.get("key_key"),
             rec.get("key_scale"), rec.get("key_strength_raw"),
             gated_confidence(rec.get("key_strength_raw"), tonalness),
             None if agreement is None else int(agreement),
             rec.get("bpm"), rec.get("bpm_confidence"), rec.get("danceability"),
             rec.get("average_loudness"), rec.get("dynamic_complexity"),
             rec.get("tuning_frequency"), json.dumps(rec), now))
        written += 1

    conn.commit()
    return written


def load(out_path) -> list[dict]:
    return json.loads(Path(out_path).read_text())
