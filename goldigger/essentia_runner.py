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
import shutil
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


def runner_mode() -> str | None:
    """How this machine can run the extractor, or None if it cannot.

    A caller that is not a terminal -- the desktop app -- has to be able to say
    "you cannot run this here" before it offers the button, rather than after a
    subprocess fails.
    """
    if essentia_available_natively():
        return "native"
    return "docker" if shutil.which("docker") else None


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
        path = in_dir / rec["rel_path"]
        file_hash = index.get(str(path.resolve()).lower())
        if file_hash is None:
            continue
        merge_one(conn, file_hash, path, rec, commit=False, now=now)
        written += 1

    conn.commit()
    return written


def merge_one(conn, file_hash: str, path, rec: dict, commit: bool = True,
              now: str | None = None, compare: bool = True) -> None:
    """Fold one extractor record in, for one already-ingested file.

    Split out of merge() so ingest can call it per file as it goes: the native
    extractor takes a path, and a folder-at-a-time pass would mean walking the
    library twice and holding every record in memory first.

    Must run AFTER the file's chunks are written -- the gate and the agreement
    flag are read back off them.

    `compare=False` when the chunk's key came from this same record: in mock mode
    Essentia supplies it, and scoring that as agreement would be the extractor
    agreeing with itself.
    """
    now = now or dt.datetime.now(dt.UTC).isoformat()
    tonalness, tonic_pc, is_major = _librosa_view(conn, file_hash)
    agreement = key_agreement(rec.get("key_key"), rec.get("key_scale"),
                              tonic_pc, is_major) if compare else None
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
        (file_hash, str(path), rec.get("key_key"), rec.get("key_scale"),
         rec.get("key_strength_raw"),
         gated_confidence(rec.get("key_strength_raw"), tonalness),
         None if agreement is None else int(agreement),
         rec.get("bpm"), rec.get("bpm_confidence"), rec.get("danceability"),
         rec.get("average_loudness"), rec.get("dynamic_complexity"),
         rec.get("tuning_frequency"), json.dumps(rec), now))
    if commit:
        conn.commit()


def extract_one(path) -> dict | None:
    """MusicExtractor on a single file, in-process. None when it cannot run.

    Only the native path: starting a container per file would cost more than the
    analysis. A machine without essentia falls back to the folder-at-a-time
    Docker pass, which is what `run()` is for.
    """
    if not essentia_available_natively():
        return None
    sys.path.insert(0, str(script_dir()))
    try:
        import essentia_extract
        return essentia_extract.extract_one(path)
    finally:
        sys.path.pop(0)


def load(out_path) -> list[dict]:
    return json.loads(Path(out_path).read_text())


# ---------------------------------------------------------------- job

def run_job(conn, job_id: str, root, out_path=None) -> None:
    """Synchronous body of an Essentia pass, shaped like `ingest.run_job`.

    The extractor is one subprocess over a whole directory, so there is no
    per-file progress to report: `jobs.message` names the phase instead, and
    total/done are 1 so the same progress row can render it.

    A failure is recorded on the job rather than raised: this runs in a
    background task, and "no essentia and no docker on this machine" is a
    condition the UI has to show, not a crash.
    """
    out_path = Path(out_path or (config.ROOT / "essentia.json"))
    now = dt.datetime.now(dt.UTC).isoformat()
    conn.execute(
        "UPDATE jobs SET state='running', total=1, done=0, message=?, started_at=?"
        " WHERE job_id=?", ("extracting", now, job_id))
    conn.commit()

    try:
        if runner_mode() is None:
            raise RuntimeError(
                "essentia is not installed and docker is not available -- "
                "pip install essentia (macOS/Linux) or start docker")
        run(root, out_path)
        conn.execute("UPDATE jobs SET message='merging' WHERE job_id=?", (job_id,))
        conn.commit()
        merged = merge(conn, load(out_path), root)
        conn.execute("UPDATE jobs SET done=1, message=? WHERE job_id=?",
                     (f"merged {merged} files", job_id))
    except subprocess.CalledProcessError as exc:
        # The full argv is no use to a UI; the exit status and the fix are.
        where = "docker" if runner_mode() == "docker" else "the extractor"
        hint = " -- is the docker daemon running?" if exc.returncode == 125 else ""
        conn.execute("UPDATE jobs SET failed=1, message=? WHERE job_id=?",
                     (f"{where} exited {exc.returncode}{hint}", job_id))
    except Exception as exc:
        conn.execute("UPDATE jobs SET failed=1, message=? WHERE job_id=?",
                     (str(exc)[:300], job_id))

    conn.execute("UPDATE jobs SET state='finished', finished_at=? WHERE job_id=?",
                 (dt.datetime.now(dt.UTC).isoformat(), job_id))
    conn.commit()
