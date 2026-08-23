"""Walk a folder, chunk each file, extract features, upsert into SQLite."""
from __future__ import annotations

import datetime as dt
import json
import multiprocessing as mp
import traceback
import uuid
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from . import config, db, essentia_runner, features, mock

_clap = None


def _clap_model():
    global _clap
    if _clap is None:
        _clap = features.Clap()
    return _clap


def walk(root) -> list[Path]:
    root = Path(root).expanduser()
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and p.suffix.lower() in config.AUDIO_EXTS)


def walk_all(roots) -> list[Path]:
    """Union of walk() over several roots. Deduped, first-seen order kept.

    A Live set's missing samples arrive as a list of individual files rather than
    a folder, and walk() already treats a file as a one-element root.
    """
    if isinstance(roots, (str, Path)):
        roots = [roots]
    seen, out = set(), []
    for root in roots:
        for path in walk(root):
            if str(path) not in seen:
                seen.add(str(path))
                out.append(path)
    return out


def _role_or_tags(role, role_source, tags) -> tuple[str | None, str]:
    """Filename first, tag classifier second.

    A filename that names its role is a human's own label and outranks a model;
    the classifier only speaks when the filename said nothing, which is most of
    any library organised by catalogue number.
    """
    if role:
        return role, role_source
    inferred = features.role_from_tags(tags)
    return (inferred, "clap") if inferred else (None, "unknown")


def analyze_file(path: Path, essentia: dict | None = None) -> list[dict]:
    """One file -> chunk rows. Honours config.MOCK.

    `essentia` is that file's MusicExtractor record when the pass ran. It is
    only consulted in mock mode, where a real measurement of key and tempo beats
    a number synthesized from the file hash. In real mode beat-this and librosa
    stay authoritative and Essentia remains the second opinion it was built as.
    """
    fh = features.file_hash(path)
    role, role_source = features.role_from_path(path)

    if config.MOCK:
        import soundfile as sf
        try:
            duration = sf.info(str(path)).duration
        except Exception:
            duration = 8.0
        rhythm = mock.rhythm(fh)
        # a real tempo also re-cuts the chunks: the spans are bar-aligned
        if essentia and essentia.get("bpm"):
            rhythm = {**rhythm, "bpm": round(float(essentia["bpm"]), 2)}
        # Essentia reporting 0 BPM means "no tempo here" -- a one-shot, not a
        # loop. Storing the hash's invented tempo instead would feed a made-up
        # number into the rhythm term; None reads as NEUTRAL there.
        bpm = rhythm["bpm"] if not essentia else (
            round(float(essentia["bpm"]), 2) if essentia.get("bpm") else None)
        e_pc = essentia_runner.pitch_to_pc(essentia.get("key_key")) if essentia else None
        spans = features.chunk_boundaries(duration, rhythm)
        rows = []
        for i, (t0, t1) in enumerate(spans):
            cid = f"{fh[:12]}:{i}"
            ch = mock.chroma(cid)
            tonal, tconf = mock.confidences(cid)
            pc, maj, conf = features.estimate_key(ch, gate=tonal)
            if e_pc is not None:
                pc = e_pc
                maj = (essentia.get("key_scale") or "").lower() == "major"
                # same gate both tools answer through, so the two stay comparable
                conf = essentia_runner.gated_confidence(
                    essentia.get("key_strength_raw"), tonal) or conf
            if essentia and essentia.get("bpm_confidence") is not None:
                tconf = float(essentia["bpm_confidence"])
            tags = features.tags_from_sims(mock.tag_sims(cid))
            r, src = _role_or_tags(role, role_source, tags)
            rows.append(dict(
                chunk_id=cid, path=str(path), file_hash=fh, chunk_index=i,
                t_start=t0, t_end=t1, bpm=bpm,
                beats_per_bar=rhythm["beats_per_bar"],
                tonic_pc=pc, is_major=maj, key_confidence=conf,
                role=r, role_source=src, tonalness=tonal, tempo_confidence=tconf,
                spectral=mock.spectral(cid), tags=tags,
                chroma=ch, clap=mock.clap(cid)))
        return rows

    y, sr = features.load_audio(path)
    duration = len(y) / sr
    rhythm = features.analyze_rhythm(y, sr, device=_clap_model().device)
    spans = features.chunk_boundaries(duration, rhythm)

    import librosa
    # one HPSS pass per file, sliced per chunk: the separation needs surrounding
    # context to be meaningful, and it is far too slow to repeat per chunk
    y_harm, y_perc = features.hpss_split(y)

    rows, clips = [], []
    for i, (t0, t1) in enumerate(spans):
        a, b = int(t0 * sr), int(t1 * sr)
        seg, seg_h, seg_p = y[a:b], y_harm[a:b], y_perc[a:b]
        tonal = features.hpss_tonalness(harmonic=seg_h, percussive=seg_p)
        # chroma off the harmonic signal only: percussive transients pollute it,
        # and on the reference set this moved match strength 0.71->0.85 and
        # 0.70->0.92 and corrected one outright wrong key
        ch = features.chroma_vector(seg_h, sr)
        pc, maj, conf = features.estimate_key(ch, gate=tonal)
        rows.append(dict(
            chunk_id=f"{fh[:12]}:{i}", path=str(path), file_hash=fh, chunk_index=i,
            t_start=t0, t_end=t1, bpm=rhythm["bpm"],
            beats_per_bar=rhythm["beats_per_bar"],
            tonic_pc=pc, is_major=maj, key_confidence=conf,
            role=role, role_source=role_source, tonalness=tonal,
            tempo_confidence=features.tempo_confidence(seg, sr, rhythm["bpm"]),
            spectral=features.spectral_stats(seg, sr), tags=None,
            chroma=ch, clap=None))
        clips.append(librosa.resample(seg, orig_sr=sr, target_sr=config.CLAP_SR))

    clap = _clap_model()
    vecs = clap.embed_audio(clips)
    for row, vec, tags in zip(rows, vecs, clap.tags(vecs)):
        row["clap"] = vec
        row["tags"] = tags
        row["role"], row["role_source"] = _role_or_tags(role, role_source, tags)
    return rows


# ------------------------------------------------------- the parallel stage

# Hashing and Essentia are the only per-file costs worth spreading. Everything
# else a file needs -- chunking, the mock features, the upserts -- is
# milliseconds and has to touch the connection, which stays on the job's own
# thread. So a worker gets the two expensive halves and hands back plain data.

_SEEN: set[str] = set()
_ESSENTIA = False


def _worker_init(seen: set[str], essentia: bool) -> None:
    global _SEEN, _ESSENTIA
    _SEEN, _ESSENTIA = seen, essentia


def prepare(path_str: str, seen: set[str], essentia: bool) -> dict:
    """One file's hash and Essentia record, or the error that stopped it.

    The dedupe check happens here rather than in the caller so an already-known
    file costs one hash instead of a round trip: the worker holds a copy of the
    hashes that were present when the job started.
    """
    try:
        fh = features.file_hash(path_str)
    except Exception as exc:
        return dict(path=path_str, error=f"{exc}\n{traceback.format_exc(limit=3)}")

    if fh in seen:
        return dict(path=path_str, file_hash=fh, seen=True, essentia=None)

    rec = None
    if essentia:
        try:
            rec = essentia_runner.extract_one(path_str)
        except Exception:
            rec = None          # a file essentia cannot read is not a failed ingest
    return dict(path=path_str, file_hash=fh, seen=False, essentia=rec)


def _prepare_pooled(path_str: str) -> dict:
    return prepare(path_str, _SEEN, _ESSENTIA)


def prepared(paths, seen, essentia: bool, workers: int):
    """Yield one prepare() record per path, in walk order.

    Order is what makes the pool invisible to the caller: the loop downstream
    still writes files in the order they were walked, and its progress counter
    still means what it did. Only `workers * 4` files are ever in flight, so a
    library of thousands does not queue thousands of records into memory.

    Serial when there is nothing to spread: without Essentia the per-file cost is
    a hash, and a process pool costs more than it saves.
    """
    if workers <= 1 or not essentia:
        for path in paths:
            yield prepare(str(path), seen, essentia)
        return

    # spawn, not fork: this runs on a background thread of the API process, and
    # forking a threaded parent is unsafe on macOS.
    with ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn"),
                             initializer=_worker_init,
                             initargs=(seen, essentia)) as pool:
        remaining = iter(paths)
        inflight: deque = deque()

        def top_up() -> None:
            while len(inflight) < workers * 4:
                nxt = next(remaining, None)
                if nxt is None:
                    return
                inflight.append(pool.submit(_prepare_pooled, str(nxt)))

        top_up()
        while inflight:
            future = inflight.popleft()
            top_up()
            yield future.result()


def upsert(conn, rows):
    conn.executemany(
        """INSERT INTO chunks (chunk_id, path, file_hash, chunk_index, t_start, t_end,
                               bpm, beats_per_bar, tonic_pc, is_major, key_confidence,
                               role, role_source, chroma, clap,
                               tempo_confidence, tonalness, spectral, tags)
           VALUES (:chunk_id,:path,:file_hash,:chunk_index,:t_start,:t_end,:bpm,
                   :beats_per_bar,:tonic_pc,:is_major,:key_confidence,:role,
                   :role_source,:chroma,:clap,
                   :tempo_confidence,:tonalness,:spectral,:tags)
           ON CONFLICT(chunk_id) DO UPDATE SET
             bpm=excluded.bpm, tonic_pc=excluded.tonic_pc, is_major=excluded.is_major,
             key_confidence=excluded.key_confidence, role=excluded.role,
             role_source=excluded.role_source, chroma=excluded.chroma,
             clap=excluded.clap, tempo_confidence=excluded.tempo_confidence,
             tonalness=excluded.tonalness, spectral=excluded.spectral,
             tags=excluded.tags""",
        [{**r,
          "chroma": db.to_blob(r["chroma"]),
          "clap": db.to_blob(r["clap"]),
          "spectral": json.dumps(r["spectral"]) if r["spectral"] else None,
          "tags": json.dumps(r["tags"]) if r["tags"] else None}
         for r in rows])
    conn.commit()


def run_job(conn, job_id: str, roots):
    """Synchronous body of an ingest job. Called from a background task.

    `roots` is one folder/file or a list of them. `jobs.message` carries the file
    currently being analyzed so a UI can name it while it waits.
    """
    now = dt.datetime.now(dt.UTC).isoformat()
    paths = walk_all(roots)
    conn.execute("UPDATE jobs SET state='running', total=?, started_at=? WHERE job_id=?",
                 (len(paths), now, job_id))
    conn.commit()

    # Native only: a container per file would cost more than the analysis, so a
    # Docker-only machine gets one folder-wide pass after the loop instead.
    inline_essentia = (config.ESSENTIA_ON_INGEST
                       and essentia_runner.essentia_available_natively())

    # "Already done" means done to the current standard. A file ingested before
    # Essentia was part of ingest still has hash-derived key and tempo, so it is
    # not skipped -- otherwise the dedupe would permanently freeze a stale corpus.
    if inline_essentia:
        seen = {r["file_hash"] for r in conn.execute(
            "SELECT f.file_hash FROM files f JOIN essentia e ON e.file_hash = f.file_hash"
            " WHERE f.status='ok'")}
    else:
        seen = {r["file_hash"] for r in conn.execute(
            "SELECT file_hash FROM files WHERE status='ok'")}
    done = failed = 0
    # The message now names the file that just came back rather than the one
    # about to start: with a pool ahead of this loop there are several of those.
    for record in prepared(paths, seen, inline_essentia, config.INGEST_WORKERS):
        path = Path(record["path"])
        conn.execute("UPDATE jobs SET message=? WHERE job_id=?", (str(path), job_id))
        try:
            if record.get("error"):
                raise RuntimeError(record["error"])
            fh = record["file_hash"]
            # A skip still falls through to the progress write below: `continue`
            # here froze the bar at zero for any folder already ingested.
            if fh not in seen:                  # content-hash dedupe
                essentia = record["essentia"]
                rows = analyze_file(path, essentia)
                upsert(conn, rows)
                if essentia:
                    # after upsert: the gate and the agreement flag read off the
                    # chunks. In mock mode the key in those chunks came from this
                    # same record, so there is nothing to agree with.
                    seeded = config.MOCK and essentia_runner.pitch_to_pc(
                        essentia.get("key_key")) is not None
                    essentia_runner.merge_one(conn, fh, path, essentia, commit=False,
                                              compare=not seeded)
                conn.execute(
                    "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?)",
                    (fh, str(path), rows[-1]["t_end"], "ok", None,
                     dt.datetime.now(dt.UTC).isoformat()))
                seen.add(fh)
            done += 1
        except Exception as exc:
            failed += 1
            conn.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?)",
                         (str(path), str(path), None, "failed",
                          f"{exc}\n{traceback.format_exc(limit=3)}",
                          dt.datetime.now(dt.UTC).isoformat()))
        conn.execute("UPDATE jobs SET done=?, failed=? WHERE job_id=?", (done, failed, job_id))
        conn.commit()

    if config.ESSENTIA_ON_INGEST and not inline_essentia and essentia_runner.runner_mode():
        conn.execute("UPDATE jobs SET message='essentia (docker)' WHERE job_id=?", (job_id,))
        conn.commit()
        for root in (roots if isinstance(roots, (list, tuple)) else [roots]):
            if not Path(root).expanduser().is_dir():
                continue        # the container pass takes a directory, not a file
            try:
                out = essentia_runner.run(root, config.ROOT / "essentia.json")
                essentia_runner.merge(conn, essentia_runner.load(out), root)
            except Exception:
                pass            # recorded by the standalone pass; never fails an ingest

    conn.execute(
        "UPDATE jobs SET state='finished', message=NULL, finished_at=? WHERE job_id=?",
        (dt.datetime.now(dt.UTC).isoformat(), job_id))
    conn.commit()


def new_job(conn, roots) -> str:
    """`jobs.root` is display only, so a multi-root job stores its list as JSON."""
    job_id = uuid.uuid4().hex[:12]
    label = str(roots) if isinstance(roots, (str, Path)) else json.dumps([str(r) for r in roots])
    conn.execute("INSERT INTO jobs (job_id, root, state) VALUES (?,?,'queued')",
                 (job_id, label))
    conn.commit()
    return job_id


def load_corpus(conn):
    from .scoring import Corpus
    rows = conn.execute("SELECT * FROM chunks ORDER BY chunk_id").fetchall()
    c = Corpus(rows)
    for i, r in enumerate(rows):
        c.clap[i] = db.from_blob(r["clap"], config.CLAP_DIM)
        c.chroma[i] = db.from_blob(r["chroma"], 12)
        c.bpm[i] = r["bpm"] if r["bpm"] is not None else np.nan
        c.tonic[i] = r["tonic_pc"] if r["tonic_pc"] is not None else -1
        c.kconf[i] = r["key_confidence"] or 0.0
        c.roles[i] = r["role"]
        c.hashes[i] = r["file_hash"]
    return c
