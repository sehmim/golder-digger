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

from . import config, db, essentia_runner, features, filename, mock

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


def _apply_filename(path, row: dict) -> None:
    """Fold what the filename claims into a row, recording which side won.

    Applied to both branches on purpose: mock mode is only worth having if it
    runs the same code, and this path is reachable with no model loaded at all.

    The stored confidence always describes the stored value -- a tempo taken
    from the filename carries the filename's certainty, not the confidence of
    the beat tracker that failed to find one.
    """
    name = str(path)
    bpm, bpm_c = filename.parse_bpm(name)
    row["bpm"], row["bpm_source"], row["tempo_confidence"] = filename.resolve(
        row["bpm"], row["tempo_confidence"] or 0.0, bpm, bpm_c)

    pc, is_major, key_c = filename.parse_key(name)
    if pc is not None and key_c >= (row["key_confidence"] or 0.0):
        row["tonic_pc"] = pc
        # a name like "G#" states a root and no mode; the estimate keeps the
        # half the filename was silent about rather than being discarded whole
        if is_major is not None:
            row["is_major"] = int(is_major)
        row["key_confidence"] = key_c
        row["key_source"] = "filename"
    else:
        row["key_source"] = "audio"


def extract_local(path: Path, essentia: dict | None = None,
                  device: str | None = None) -> tuple[list[dict], list | None]:
    """One file -> (chunk rows, CLAP clips). Everything that is not CLAP.

    Split out of analyze_file so an ingest worker can run it. Measured over ten
    real files, the stages below are 89% of ingest wall time -- Essentia 47%,
    HPSS 35%, chroma/key 5% -- and none of them need a model that would have to
    be loaded once per worker process. CLAP is the exception and stays with the
    caller: it is one model, on one device, and seven copies of it is not a
    speed-up.

    Returns `clips` as None in mock mode, where the rows are already complete.

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
                chroma=ch, clap=mock.clap(cid), synthetic=1))
        for r in rows:
            _apply_filename(path, r)
        return rows, None

    y, sr = features.load_audio(path)
    duration = len(y) / sr
    # beat-this is small (0.5s to load, 5% of ingest) so a worker can afford its
    # own copy; CLAP is not, which is why its device is not asked for here.
    rhythm = features.analyze_rhythm(y, sr, device=device or _clap_model().device)
    spans = features.chunk_boundaries(duration, rhythm)

    import librosa
    # one HPSS pass per file, sliced per chunk: the separation needs surrounding
    # context to be meaningful, and it is far too slow to repeat per chunk
    y_harm, y_perc = features.hpss_split(y)
    # and one resample: per chunk it re-ran the same filter once per bar
    y_clap = librosa.resample(y, orig_sr=sr, target_sr=config.CLAP_SR)

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
            chroma=ch, clap=None, synthetic=0))
        clips.append(y_clap[int(t0 * config.CLAP_SR):int(t1 * config.CLAP_SR)])

    return rows, clips


def apply_clap(path, rows: list[dict], clips: list) -> list[dict]:
    """Fill in the embedding and everything downstream of it.

    Kept apart from extract_local because this is the half that must run in the
    process that owns the model. Role is decided here rather than in the worker:
    the tag classifier only speaks when the filename said nothing, and its vote
    does not exist until the embedding does.
    """
    role, role_source = features.role_from_path(path)
    clap = _clap_model()
    vecs = clap.embed_audio(clips)
    for row, vec, tags in zip(rows, vecs, clap.tags(vecs)):
        row["clap"] = vec
        row["tags"] = tags
        row["role"], row["role_source"] = _role_or_tags(role, role_source, tags)
        _apply_filename(path, row)
    return rows


def analyze_file(path: Path, essentia: dict | None = None) -> list[dict]:
    """One file -> chunk rows, done entirely in this process.

    The single-process path: the CLI, the tests, and any caller that is not the
    pooled ingest loop.
    """
    rows, clips = extract_local(path, essentia)
    return rows if clips is None else apply_clap(path, rows, clips)


# ------------------------------------------------------- the parallel stage

# What a worker does, and why it stops where it does. Timed over ten real files:
# Essentia 47%, HPSS 35%, chroma+key 5%, spectral 2%, decode 1% -- 89% of ingest,
# none of it needing a model that would have to be loaded seven times. beat-this
# (5%) is small enough to give every worker its own copy, on CPU so the processes
# do not contend for one MPS device. CLAP (6%) is the line: one model, one
# device, and the caller keeps it. The upserts stay on the job's thread too --
# they are milliseconds, and the connection never leaves that thread.

_SEEN: set[str] = set()
_ESSENTIA = False
_ANALYZE = False


def _worker_init(seen: set[str], essentia: bool, analyze: bool) -> None:
    global _SEEN, _ESSENTIA, _ANALYZE
    _SEEN, _ESSENTIA, _ANALYZE = seen, essentia, analyze


def prepare(path_str: str, seen: set[str], essentia: bool,
            analyze: bool = False) -> dict:
    """One file's hash, Essentia record and -- with `analyze` -- its chunk rows.

    The dedupe check happens here rather than in the caller so an already-known
    file costs one hash instead of a round trip: the worker holds a copy of the
    hashes that were present when the job started.

    `analyze` off is the original contract, and the CLI and tests still use it.
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

    record = dict(path=path_str, file_hash=fh, seen=False, essentia=rec)
    if analyze:
        try:
            rows, clips = extract_local(Path(path_str), rec, device="cpu")
            record["rows"], record["clips"] = rows, clips
        except Exception as exc:
            # The whole file failed, not just its features: report it the same way
            # a bad hash is reported so the caller has one error path, not two.
            return dict(path=path_str,
                        error=f"{exc}\n{traceback.format_exc(limit=3)}")
    return record


def _prepare_pooled(path_str: str) -> dict:
    return prepare(path_str, _SEEN, _ESSENTIA, _ANALYZE)


def prepared(paths, seen, essentia: bool, workers: int, analyze: bool = False):
    """Yield one prepare() record per path, in walk order.

    Order is what makes the pool invisible to the caller: the loop downstream
    still writes files in the order they were walked, and its progress counter
    still means what it did. Only `workers * 4` files are ever in flight, so a
    library of thousands does not queue thousands of records into memory.

    Serial when there is nothing to spread: with neither Essentia nor analysis
    the per-file cost is a hash, and a process pool costs more than it saves.
    """
    if workers <= 1 or not (essentia or analyze):
        for path in paths:
            yield prepare(str(path), seen, essentia, analyze)
        return

    # spawn, not fork: this runs on a background thread of the API process, and
    # forking a threaded parent is unsafe on macOS.
    with ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn"),
                             initializer=_worker_init,
                             initargs=(seen, essentia, analyze)) as pool:
        remaining = iter(paths)
        inflight: deque = deque()
        # A hash-and-Essentia record is a few hundred bytes, so the original
        # window could be generous. An analysed one carries every chunk's audio
        # at CLAP_SR -- a seven-minute stem came back as 42 clips, tens of
        # megabytes -- and `workers * 4` of those in flight exhausted memory and
        # took the pool down with it. Keep just enough queued to stay saturated.
        window = (workers + 2) if analyze else (workers * 4)

        def top_up() -> None:
            while len(inflight) < window:
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
                               tempo_confidence, tonalness, spectral, tags, synthetic,
                               bpm_source, key_source)
           VALUES (:chunk_id,:path,:file_hash,:chunk_index,:t_start,:t_end,:bpm,
                   :beats_per_bar,:tonic_pc,:is_major,:key_confidence,:role,
                   :role_source,:chroma,:clap,
                   :tempo_confidence,:tonalness,:spectral,:tags,:synthetic,
                   :bpm_source,:key_source)
           ON CONFLICT(chunk_id) DO UPDATE SET
             bpm=excluded.bpm, tonic_pc=excluded.tonic_pc, is_major=excluded.is_major,
             key_confidence=excluded.key_confidence, role=excluded.role,
             role_source=excluded.role_source, chroma=excluded.chroma,
             clap=excluded.clap, tempo_confidence=excluded.tempo_confidence,
             tonalness=excluded.tonalness, spectral=excluded.spectral,
             tags=excluded.tags, synthetic=excluded.synthetic,
             bpm_source=excluded.bpm_source, key_source=excluded.key_source""",
        [{**r,
          "chroma": db.to_blob(r["chroma"]),
          "clap": db.to_blob(r["clap"]),
          "spectral": json.dumps(r["spectral"]) if r["spectral"] else None,
          "tags": json.dumps(r["tags"]) if r["tags"] else None}
         for r in rows])
    conn.commit()


# ---------------------------------------------------- keeping rows and disk in step

def relink(conn, path: str, file_hash: str) -> bool:
    """Point an already-ingested file's rows at where the file actually is.

    Content-hash dedupe correctly recognises a moved or renamed file as already
    done -- and then leaves its rows naming a path that no longer exists, which
    is a chunk that cannot be previewed and a result that cannot be opened.

    Only rewritten when the stored path is gone. Two copies of one file are not
    a move: rewriting on every walk would make them trade the rows back and
    forth, and neither path would be wrong to begin with.
    """
    rows = conn.execute("SELECT DISTINCT path FROM chunks WHERE file_hash=?",
                        (file_hash,)).fetchall()
    stale = [r["path"] for r in rows if r["path"] != path and not Path(r["path"]).exists()]
    if not stale:
        return False
    marks = ",".join("?" * len(stale))
    conn.execute(f"UPDATE chunks SET path=? WHERE file_hash=? AND path IN ({marks})",
                 (path, file_hash, *stale))
    conn.execute("UPDATE files SET path=? WHERE file_hash=?", (path, file_hash))
    return True


def drop_stale(conn, path: str, file_hash: str) -> int:
    """Chunks that claim this path but not the bytes now at it.

    A file edited in place gets a new hash and a new set of chunks, and the old
    set stays behind describing audio that is no longer there -- surfacing in
    results under the same filename with a different key and tempo. Only ever
    called for a file just walked, so `file_hash` is what is on disk right now.
    """
    cur = conn.execute("DELETE FROM chunks WHERE path=? AND file_hash<>?", (path, file_hash))
    if cur.rowcount:
        conn.execute("DELETE FROM files WHERE path=? AND file_hash<>?", (path, file_hash))
    return cur.rowcount


def _stat_pair(path) -> tuple[int | None, float | None]:
    """(size, mtime) exactly as the fast-path will compare them; Nones when the
    file cannot be statted, which reads as "never skip"."""
    try:
        st = Path(path).stat()
        return st.st_size, st.st_mtime
    except OSError:
        return None, None


def _extract_essentia(item: tuple[str, str]) -> tuple[str, str, dict | None]:
    fh, path = item
    try:
        return fh, path, essentia_runner.extract_one(path)
    except Exception:
        return fh, path, None   # a file essentia cannot read is not a failed ingest


def _essentia_records(items, workers: int):
    """(file_hash, path, record) per item, for the deferred second-opinion tail.

    Pooled for the same reason the inline pass was: MusicExtractor holds the GIL
    for its whole run, so processes are the only parallelism that counts."""
    if workers <= 1 or len(items) <= 1:
        for item in items:
            yield _extract_essentia(item)
        return
    with ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn")) as pool:
        yield from pool.map(_extract_essentia, items)


def run_job(conn, job_id: str, roots, on_corpus_ready=None):
    """Synchronous body of an ingest job. Called from a background task.

    `roots` is one folder/file or a list of them. `jobs.message` carries the file
    currently being analyzed so a UI can name it while it waits.

    `on_corpus_ready` fires once the chunk rows are final -- before the Essentia
    tail, whose second opinion never changes them -- so the caller can publish
    the corpus while that tail is still running.
    """
    now = dt.datetime.now(dt.UTC).isoformat()
    paths = walk_all(roots)
    conn.execute("UPDATE jobs SET state='running', total=?, started_at=? WHERE job_id=?",
                 (len(paths), now, job_id))
    conn.commit()

    # Native only: a container per file would cost more than the analysis, so a
    # Docker-only machine gets one folder-wide pass after the loop instead.
    # Inline only under mock, where the chunk rows themselves consume the record
    # (it is the one real measurement mock has). In real mode nothing on the
    # Fit/Novelty path reads it -- it was measured at 47% of ingest wall time and
    # buys the user nothing until they ask for a second opinion -- so it runs as
    # a tail, after the corpus is already live.
    native = essentia_runner.essentia_available_natively()
    inline_essentia = config.ESSENTIA_ON_INGEST and native and config.MOCK
    deferred_essentia = config.ESSENTIA_ON_INGEST and native and not config.MOCK

    # "Already done" means done to the current standard. A file ingested before
    # Essentia was part of ingest still has hash-derived key and tempo, so it is
    # not skipped -- otherwise the dedupe would permanently freeze a stale corpus.
    # The deferred tail is not part of the chunk standard: it repairs a missing
    # second opinion on its own, without re-chunking anything.
    if inline_essentia:
        seen = {r["file_hash"] for r in conn.execute(
            "SELECT f.file_hash FROM files f JOIN essentia e ON e.file_hash = f.file_hash"
            " WHERE f.status='ok'")}
    else:
        seen = {r["file_hash"] for r in conn.execute(
            "SELECT file_hash FROM files WHERE status='ok'")}

    # The same rule, applied to the embedding: a real run must not skip a file
    # whose CLAP vector was synthesized under mock (or written before the column
    # existed, which is the same lack of evidence). Without this, switching
    # GOLDDIGGER_MOCK off and re-ingesting is a no-op and every distance stays
    # fiction -- silently, because the job still reports every file done.
    if not config.MOCK:
        seen -= {r["file_hash"] for r in conn.execute(
            "SELECT DISTINCT file_hash FROM chunks"
            " WHERE synthetic IS NULL OR synthetic = 1")}
    done = failed = relinked = dropped = 0

    # A file whose stored (size, mtime) still matches disk skips even the hash:
    # re-ingesting an already-done library costs a stat per file instead of
    # reading every byte back to conclude nothing changed. The stat only vouches
    # for a row that meets today's standard -- `seen` -- so anything substandard
    # (synthetic vectors, a pre-Essentia mock row) still takes the slow path and
    # gets repaired. Same path, same bytes: nothing for relink or drop_stale.
    known = {r["path"]: (r["file_hash"], r["size"], r["mtime"])
             for r in conn.execute(
                 "SELECT path, file_hash, size, mtime FROM files WHERE status='ok'")}
    todo = []
    for p in paths:
        fh, size, mtime = known.get(str(p), (None, None, None))
        try:
            st = p.stat() if fh in seen and size is not None else None
        except OSError:
            st = None           # vanished since the walk: let the slow path name it
        if st is not None and st.st_size == size and st.st_mtime == mtime:
            done += 1
        else:
            todo.append(p)
    if done:
        conn.execute("UPDATE jobs SET done=? WHERE job_id=?", (done, job_id))
        conn.commit()

    # The workers extract as well as hash. Without this the serial loop below is
    # 89% of ingest -- Essentia 47%, HPSS 35%, chroma/key 5% -- and the pool
    # covers only the hash; with it the split inverts and CLAP is all that is
    # left serial. Never under mock: there the features are a few milliseconds of
    # arithmetic off the file hash, and handing that to a spawned process costs
    # more than doing it. Essentia still pools there, which is what it is for.
    analyze_in_pool = (config.POOL_ANALYZE and config.INGEST_WORKERS > 1
                       and not config.MOCK)

    # The message now names the file that just came back rather than the one
    # about to start: with a pool ahead of this loop there are several of those.
    for record in prepared(todo, seen, inline_essentia, config.INGEST_WORKERS,
                           analyze=analyze_in_pool):
        path = Path(record["path"])
        conn.execute("UPDATE jobs SET message=? WHERE job_id=?", (str(path), job_id))
        try:
            if record.get("error"):
                raise RuntimeError(record["error"])
            fh = record["file_hash"]
            # Before the dedupe decides: the rows for this content may name a
            # path it has since moved away from, and the path may still carry
            # rows from bytes that have since been replaced. Both are cheap
            # statements against an index, and neither re-extracts anything.
            moved = relink(conn, str(path), fh)
            orphans = drop_stale(conn, str(path), fh)
            relinked += moved
            dropped += orphans

            # A skip still falls through to the progress write below: `continue`
            # here froze the bar at zero for any folder already ingested.
            if fh not in seen:                  # content-hash dedupe
                essentia = record["essentia"]
                if "rows" in record:
                    # A worker already did everything but the embedding. `clips`
                    # is None under mock, where the rows came back complete.
                    rows = (record["rows"] if record["clips"] is None
                            else apply_clap(path, record["rows"], record["clips"]))
                else:
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
                size, mtime = _stat_pair(path)
                conn.execute(
                    "INSERT OR REPLACE INTO files"
                    " (file_hash, path, duration, status, error, ingested_at, size, mtime)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (fh, str(path), rows[-1]["t_end"], "ok", None,
                     dt.datetime.now(dt.UTC).isoformat(), size, mtime))
                seen.add(fh)
            else:
                # A dedupe skip still refreshes the stat: a touched file keeps
                # its content hash, and without this it would be re-hashed on
                # every future ingest to rediscover that. Keyed by path too --
                # a duplicate of this content elsewhere has its own stat.
                size, mtime = _stat_pair(path)
                if size is not None:
                    conn.execute("UPDATE files SET size=?, mtime=?"
                                 " WHERE file_hash=? AND path=?",
                                 (size, mtime, fh, str(path)))
            done += 1
        except Exception as exc:
            failed += 1
            # size/mtime stay NULL on purpose: a failed file never fast-paths,
            # so it is retried on every ingest until it succeeds or is removed.
            conn.execute("INSERT OR REPLACE INTO files"
                         " (file_hash, path, duration, status, error, ingested_at)"
                         " VALUES (?,?,?,?,?,?)",
                         (str(path), str(path), None, "failed",
                          f"{exc}\n{traceback.format_exc(limit=3)}",
                          dt.datetime.now(dt.UTC).isoformat()))
        conn.execute("UPDATE jobs SET done=?, failed=? WHERE job_id=?", (done, failed, job_id))
        conn.commit()

    # Every chunk row is final from here on: the tails below only write the
    # essentia table. This is the moment the corpus is worth publishing.
    if on_corpus_ready is not None:
        on_corpus_ready()

    if deferred_essentia:
        walked = {str(p) for p in paths}
        missing = [(r["file_hash"], r["path"]) for r in conn.execute(
            "SELECT f.file_hash, f.path FROM files f"
            " LEFT JOIN essentia e ON e.file_hash = f.file_hash"
            " WHERE f.status='ok' AND e.file_hash IS NULL")
            if r["path"] in walked]
        for i, (fh, path, rec) in enumerate(
                _essentia_records(missing, config.INGEST_WORKERS), 1):
            if rec:
                essentia_runner.merge_one(conn, fh, path, rec, commit=False)
            conn.execute("UPDATE jobs SET message=? WHERE job_id=?",
                         (f"essentia second opinion ({i}/{len(missing)})", job_id))
            conn.commit()

    if config.ESSENTIA_ON_INGEST and not native and essentia_runner.runner_mode():
        conn.execute("UPDATE jobs SET message='essentia (docker)' WHERE job_id=?", (job_id,))
        conn.commit()
        for root in (roots if isinstance(roots, (list, tuple)) else [roots]):
            if not Path(root).expanduser().is_dir():
                continue        # the container pass takes a directory, not a file
            try:
                out = essentia_runner.run(root, config.DATA_DIR / "essentia.json")
                essentia_runner.merge(conn, essentia_runner.load(out), root)
            except Exception:
                pass            # recorded by the standalone pass; never fails an ingest

    # The message doubles as the finished job's footnote. Worth saying: from the
    # progress bar alone, a library that was silently repaired and one that was
    # skipped wholesale look identical.
    repairs = ([f"{relinked} moved"] if relinked else []) + \
              ([f"{dropped} stale chunks dropped"] if dropped else [])
    conn.execute(
        "UPDATE jobs SET state='finished', message=?, finished_at=? WHERE job_id=?",
        (" · ".join(repairs) or None, dt.datetime.now(dt.UTC).isoformat(), job_id))
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
        c.tconf[i] = r["tempo_confidence"] or 0.0
        c.roles[i] = r["role"]
        c.hashes[i] = r["file_hash"]
        c.synthetic[i] = r["synthetic"] != 0 if r["synthetic"] is not None else True
    return c
