"""Localhost HTTP surface. Electron spawns this as a child process."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import os
import json
from pathlib import Path
from threading import Lock

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field, model_validator

from . import (ableton, audition, config, db, essentia_runner, ingest, lines,
               listening, midi, presets, scoring)

app = FastAPI(title="Gold Digger", version="0.1.0")
state: dict = {"conn": None, "corpus": None}

# A knob session revisits a very small set of queries. Keep those results in the
# backend so every renderer gets the same behaviour and returning to a detent is
# independent of UI lifetime. These are deliberately bounded runtime caches;
# SQLite remains the durable source of truth.
_ANALYSIS_CACHE_LIMIT = 32
_ROOT_MASK_CACHE_LIMIT = 16
# a knob session revisits one context file at every detent, and real-mode
# extraction of that file is seconds of work per request without this
_CONTEXT_ROWS_CACHE_LIMIT = 8
_analysis_cache: OrderedDict[tuple, dict] = OrderedDict()
_als_cache: OrderedDict[tuple, dict] = OrderedDict()
_root_mask_cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
_context_rows_cache: OrderedDict[tuple, list] = OrderedDict()
_midi_cache: OrderedDict[tuple, dict] = OrderedDict()
_cache_lock = Lock()


def _cache_get(cache: OrderedDict, key: tuple):
    with _cache_lock:
        value = cache.get(key)
        if value is not None:
            cache.move_to_end(key)
        return value


def _cache_put(cache: OrderedDict, key: tuple, value, limit: int):
    with _cache_lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)


@app.on_event("startup")
def _startup():
    conn = db.thread_conn()
    db.init(conn)
    state["corpus"] = ingest.load_corpus(conn)


def _conn():
    """This thread's connection. FastAPI runs sync handlers on a threadpool and
    ingest runs on another thread again -- see db.thread_conn."""
    return db.thread_conn()


def _corpus():
    if state["corpus"] is None or len(state["corpus"]) == 0:
        raise HTTPException(409, "corpus is empty -- POST /ingest first")
    return state["corpus"]


# ---------------------------------------------------------------- models

class IngestReq(BaseModel):
    root: str | None = Field(None, description="folder (or file) to ingest")
    roots: list[str] | None = Field(
        None, description="several folders/files in one job; a Live set's missing samples")

    @model_validator(mode="after")
    def _one_of(self):
        if not self.root and not self.roots:
            raise ValueError("pass root or roots")
        return self

    def targets(self) -> list[str]:
        return list(self.roots) if self.roots else [self.root]


class AnalyzeReq(BaseModel):
    # empty is legal now that a context can also arrive as files: the handler
    # requires at least one of context_ids / context_paths / midi_path
    context_ids: list[str] = Field(default_factory=list)
    distance: float | None = Field(
        None, ge=0, le=100,
        description="target novelty percentile, not a threshold;"
                    " null means the preset's own position")
    preset: str | None = Field(
        None, description="one of GET /presets; null scores with the config defaults")
    k: int = Field(config.DEFAULT_K, ge=1, le=100)
    session_path: str | None = Field(
        None, description="the .als these chunks came from; anchors tempo and key")
    midi_path: str | None = Field(
        None, description="a standard MIDI file; states tempo, key and harmony --"
                          " the DAW-agnostic session header, usable alone")
    context_paths: list[str] | None = Field(
        None, description="audio files used directly as the context, ingested or"
                          " not -- sample matching without any DAW")
    bpm: float | None = Field(
        None, gt=0, description="tempo stated by the caller -- e.g. a plugin"
                                " reading the host transport; beats everything inferred")
    active_roots: list[str] | None = Field(
        None, description="candidate folders; null means the full legacy corpus")


class FolderStatusReq(BaseModel):
    roots: list[str]


class LibraryFilesReq(BaseModel):
    roots: list[str] | None = None
    limit: int = Field(100, ge=1, le=250)
    offset: int = Field(0, ge=0)


class TagReq(BaseModel):
    role: str


class AlsReq(BaseModel):
    path: str = Field(..., description="a .als on disk")


class EssentiaReq(BaseModel):
    root: str = Field(..., description="the folder that was ingested")


# ---------------------------------------------------------------- routes

@app.exception_handler(audition.ChunkOutsideAudio)
def _chunk_outside_audio(request, exc: audition.ChunkOutsideAudio):
    """410, not 500: the row is wrong about the file, and the fix is a re-ingest.

    Raised from inside the render, so it is handled here rather than at each of
    the two audio routes -- and the desktop shows the message instead of a bare
    "500 could not render <chunk_id>".
    """
    return JSONResponse(status_code=410,
                        content={"detail": f"{exc} -- re-ingest the folder to rebuild"
                                           " its chunks"})


@app.get("/health")
def health():
    c = state["corpus"]
    return {"ok": True, "mock": config.MOCK, "chunks": len(c) if c else 0,
            "synthetic_chunks": int(c.synthetic.sum()) if c else 0,
            "presets": [p.key for p in presets.PRESETS],
            # WHAT THIS BUILD CAN ACTUALLY DO. src/main/api.ts adopts an
            # already-listening server rather than spawning a second one, which
            # is right for a `golddigger serve` you left in a terminal and wrong
            # for one older than the routes the app needs; it checks its
            # REQUIRED_ROUTES against this list and refuses the ones that would
            # 404. Derived from the app, so it cannot be forgotten -- the marker
            # key it replaces was added in the first commit, never moved, and so
            # was present in every build from 20 routes to 22, discriminating
            # nothing. tests/test_health_contract.py holds the two sides
            # together.
            "routes": sorted({r.path for r in app.routes
                              if getattr(r, "methods", None)}),
            # kept because the desktop still reads it; no longer load-bearing
            "chunk_peaks": True,
            "db": str(config.DB_PATH),
            # how ingest will characterise files, before anything is ingested
            "essentia": essentia_runner.runner_mode() if config.ESSENTIA_ON_INGEST else None}


@app.post("/ingest")
async def start_ingest(req: IngestReq):
    conn = _conn()
    targets = req.targets()
    job_id = ingest.new_job(conn, targets)

    def _work():
        # its own connection: this runs on a worker thread -- see db.thread_conn
        worker = db.thread_conn()

        def _publish():
            # the chunks are final before the Essentia tail runs, so the corpus
            # goes live here -- results are askable while the second opinion
            # is still being collected
            state["corpus"] = ingest.load_corpus(worker)

        ingest.run_job(worker, job_id, targets, on_corpus_ready=_publish)
        return state["corpus"]

    async def _run():
        # extraction is CPU/GPU bound and releases the GIL, so a thread is enough
        state["corpus"] = await asyncio.to_thread(_work)

    asyncio.create_task(_run())
    return {"job_id": job_id}


@app.get("/ingest/status/{job_id}")
def ingest_status(job_id: str):
    row = _conn().execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such job")
    return dict(row)


@app.post("/essentia")
async def start_essentia(req: EssentiaReq):
    """Second-opinion pass over an already-ingested folder.

    A job like any other, so the desktop app can watch it on the same poller --
    but a single subprocess over the whole folder, so it reports phases rather
    than a file count.
    """
    conn = _conn()
    if essentia_runner.runner_mode() is None:
        raise HTTPException(
            503, "essentia is not installed and docker is not available here")
    job_id = ingest.new_job(conn, req.root)

    def _work():
        essentia_runner.run_job(db.thread_conn(), job_id, req.root)

    async def _run():
        await asyncio.to_thread(_work)

    asyncio.create_task(_run())
    return {"job_id": job_id}


@app.get("/essentia/summary")
def essentia_summary():
    """Coverage and agreement, for a UI that has to say whether it is worth running."""
    conn = _conn()
    counts = {r["a"]: r["c"] for r in conn.execute(
        "SELECT key_agreement a, COUNT(*) c FROM essentia GROUP BY a")}
    return {
        "mode": essentia_runner.runner_mode(),
        "files": conn.execute("SELECT COUNT(DISTINCT file_hash) FROM chunks").fetchone()[0],
        "covered": conn.execute("SELECT COUNT(*) FROM essentia").fetchone()[0],
        "agree": counts.get(1, 0),
        "disagree": counts.get(0, 0),
        "no_key": counts.get(None, 0),
    }


@app.get("/presets")
def list_presets():
    """The five postures, safest first, with the copy that explains them.

    Served rather than duplicated in the renderer so the numbers the UI displays
    are provably the numbers the engine scored with.
    """
    return {"presets": [p.as_dict() for p in presets.PRESETS],
            "default": presets.DEFAULT.as_dict(),
            "role_modes": config.ROLE_MODES,
            "fit_floor_min": config.FIT_FLOOR_MIN}


@app.get("/corpus/stats")
def corpus_stats():
    """Whether the corpus can support the scoring at all, in one payload.

    Every number here answers a question the Fit/Novelty design raises and that
    a paginated file list cannot: how much of the library carries a *measured*
    embedding, how much of it has key evidence strong enough for H to be
    anything other than NEUTRAL, and how many chunks the role term has nothing
    to say about. A UI that shows only totals will report a healthy library that
    the engine cannot discriminate within.
    """
    conn = _conn()
    row = conn.execute("""
        SELECT COUNT(*)                                             AS chunks,
               COUNT(DISTINCT file_hash)                            AS files,
               SUM(synthetic = 0)                                   AS measured,
               SUM(synthetic = 1)                                   AS synthetic,
               SUM(synthetic IS NULL)                               AS unknown,
               SUM(bpm IS NOT NULL)                                 AS with_bpm,
               SUM(role IS NULL)                                    AS no_role,
               SUM(COALESCE(key_confidence, 0) >= 0.30)             AS key_strong,
               SUM(COALESCE(key_confidence, 0) <  0.05)             AS key_absent,
               AVG(COALESCE(key_confidence, 0))                     AS key_mean
        FROM chunks""").fetchone()

    # Buckets, not a mean: the distribution is what says whether harmony is doing
    # work. A library split between confident pads and silent drums averages to
    # a number that describes neither.
    edges = [0.0, 0.05, 0.15, 0.30, 0.60, 1.01]
    key_hist = [
        {"from": lo, "to": hi,
         "count": conn.execute(
             "SELECT COUNT(*) FROM chunks WHERE COALESCE(key_confidence,0) >= ?"
             " AND COALESCE(key_confidence,0) < ?", (lo, hi)).fetchone()[0]}
        for lo, hi in zip(edges, edges[1:])]

    roles = [{"role": r["role"], "source": r["role_source"], "count": r["c"]}
             for r in conn.execute(
                 "SELECT role, role_source, COUNT(*) c FROM chunks"
                 " GROUP BY role, role_source ORDER BY c DESC")]

    tempo = [{"label": lab, "count": conn.execute(
                  "SELECT COUNT(*) FROM chunks WHERE bpm IS NOT NULL"
                  " AND bpm >= ? AND bpm < ?", (lo, hi)).fetchone()[0]}
             for lab, lo, hi in (("<90", 0, 90), ("90-110", 90, 110),
                                 ("110-130", 110, 130), ("130-150", 130, 150),
                                 (">=150", 150, 1e6))]
    tempo.append({"label": "none",
                  "count": conn.execute(
                      "SELECT COUNT(*) FROM chunks WHERE bpm IS NULL").fetchone()[0]})

    return {
        "chunks": row["chunks"], "files": row["files"],
        "provenance": {"measured": row["measured"] or 0,
                       "synthetic": row["synthetic"] or 0,
                       "unknown": row["unknown"] or 0},
        "key": {"strong": row["key_strong"] or 0, "absent": row["key_absent"] or 0,
                "mean_confidence": round(row["key_mean"] or 0.0, 4),
                "histogram": key_hist},
        "tempo": {"with_bpm": row["with_bpm"] or 0, "histogram": tempo},
        "roles": {"unassigned": row["no_role"] or 0, "breakdown": roles},
        "essentia": essentia_summary(),
    }


@app.get("/library")
def library(limit: int = Query(100, le=1000), offset: int = 0,
            role: str | None = None):
    sql = ("SELECT chunk_id, path, chunk_index, t_start, t_end, bpm, beats_per_bar,"
           " tonic_pc, is_major, key_confidence, role, role_source,"
           " tempo_confidence, tonalness, spectral, tags FROM chunks")
    args: list = []
    if role:
        sql += " WHERE role=?"
        args.append(role)
    sql += " ORDER BY path, chunk_index LIMIT ? OFFSET ?"
    args += [limit, offset]
    rows = [dict(r) for r in _conn().execute(sql, args)]
    for r in rows:
        r["tonic"] = (config.PITCH_NAMES[r["tonic_pc"]]
                      if r["tonic_pc"] is not None and r["tonic_pc"] >= 0 else None)
        # stored as JSON text; hand the client objects, not strings
        for k in ("spectral", "tags"):
            r[k] = json.loads(r[k]) if r[k] else None
    total = _conn().execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    return {"total": total, "count": len(rows), "chunks": rows}


@app.post("/library/files")
def library_files(req: LibraryFilesReq):
    """Human-scale, file-level summaries for inspection tools.

    The corpus is chunk-oriented. Group here so a developer window can paginate
    files without copying every chunk through shared application state.
    """
    if req.roots == []:
        return {"total": 0, "count": 0, "offset": req.offset, "files": []}

    where = ""
    args: list[str] = []
    if req.roots is not None:
        clauses = []
        for root in req.roots:
            normalized = str(Path(root).resolve(strict=False)).rstrip(os.sep)
            escaped = (normalized.replace("\\", "\\\\")
                       .replace("%", "\\%").replace("_", "\\_"))
            clauses.append("(c.path = ? OR c.path LIKE ? ESCAPE '\\')")
            args.extend((normalized, f"{escaped}{os.sep}%"))
        where = f" WHERE {' OR '.join(clauses)}"

    conn = _conn()
    total = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT 1 FROM chunks c{where} GROUP BY c.path, c.file_hash)",
        args).fetchone()[0]
    sql = f"""SELECT c.path, c.file_hash, f.duration, f.status, f.ingested_at,
                     COUNT(*) AS chunks, AVG(c.bpm) AS bpm,
                     GROUP_CONCAT(DISTINCT c.tonic_pc) AS tonic_pcs,
                     GROUP_CONCAT(DISTINCT c.role) AS roles,
                     MAX(COALESCE(c.synthetic, 1)) AS synthetic,
                     MAX(CASE WHEN e.file_hash IS NULL THEN 0 ELSE 1 END) AS essentia
              FROM chunks c
              LEFT JOIN files f ON f.file_hash = c.file_hash
              LEFT JOIN essentia e ON e.file_hash = c.file_hash
              {where}
              GROUP BY c.path, c.file_hash
              ORDER BY c.path
              LIMIT ? OFFSET ?"""
    page = [dict(row) for row in conn.execute(sql, [*args, req.limit, req.offset])]
    for row in page:
        pcs = [int(value) for value in (row.pop("tonic_pcs") or "").split(",") if value]
        row["keys"] = [config.PITCH_NAMES[pc] for pc in pcs if pc >= 0]
        row["roles"] = [value for value in (row["roles"] or "").split(",") if value]
        row["synthetic"] = bool(row["synthetic"])
        row["essentia"] = bool(row["essentia"])
        row["bpm"] = round(row["bpm"], 1) if row["bpm"] is not None else None

    return {"total": total, "count": len(page), "offset": req.offset, "files": page}


def _under_root(path: str, root: str) -> bool:
    """Path-aware containment: `/samples/a` must not match `/samples/able`."""
    try:
        Path(path).resolve(strict=False).relative_to(Path(root).resolve(strict=False))
        return True
    except ValueError:
        return False


def _normalized_roots(roots: list[str]) -> tuple[str, ...]:
    """Canonicalize a root set without touching the filesystem.

    Root order and duplicates cannot change a candidate set, so they must not
    create separate cache entries. Avoiding ``Path.resolve`` here is also
    important: a large corpus may live on slow or disconnected volumes.
    """
    return tuple(sorted({
        os.path.normcase(os.path.abspath(os.path.expanduser(root)))
        for root in roots
    }))


def _under_normalized_root(path: str, root: str) -> bool:
    return path == root or path.startswith(root if root.endswith(os.sep) else root + os.sep)


def _root_mask(corpus: scoring.Corpus, roots: list[str] | None) -> np.ndarray | None:
    if roots is None:
        return None
    normalized_roots = _normalized_roots(roots)
    key = (corpus.cache_token, normalized_roots)
    cached = _cache_get(_root_mask_cache, key)
    if cached is not None:
        return cached

    mask = np.array([
        any(_under_normalized_root(path, root) for root in normalized_roots)
        for path in (
            os.path.normcase(os.path.abspath(os.path.expanduser(row["path"])))
            for row in corpus.rows
        )
    ], dtype=bool)
    mask.setflags(write=False)
    _cache_put(_root_mask_cache, key, mask, _ROOT_MASK_CACHE_LIMIT)
    return mask


@app.post("/folders/status")
def folder_status(req: FolderStatusReq):
    corpus = state["corpus"]
    rows = corpus.rows if corpus is not None else []
    return {
        "folders": [
            {
                "root": root,
                "chunks": sum(_under_root(row["path"], root) for row in rows),
            }
            for root in req.roots
        ]
    }


def _load_als_cached(path: str) -> dict:
    """The set behind the dial, reparsed only when the file changes.

    A knob sweep asks for the same set several times a second and a large project
    is tens of milliseconds of XML each time. One entry is enough: the app digs
    against one set at a time.
    """
    if not os.path.isfile(path):
        raise HTTPException(404, f"no such file: {path}")
    stamp = (path, os.path.getmtime(path))

    cached = _cache_get(_als_cache, stamp)
    if cached is not None:
        return cached
    try:
        als = ableton.load_als(path)
    except ableton.UnreadableSet as exc:
        raise HTTPException(400, str(exc))
    # Two entries, and stamp-keyed rather than a pair of module globals. The
    # globals were written one after the other with no lock: FastAPI runs sync
    # handlers on a threadpool, and opening one set while another was mid-parse
    # could leave the stamp naming set A next to set B's parse -- after which
    # every request for A was answered with B until the file changed. Two,
    # because opening a set and ranking against it are separate requests and a
    # single slot makes them evict each other.
    _cache_put(_als_cache, stamp, als, 2)
    return als


def _stamp(path: str) -> tuple:
    """(abspath, mtime): identity for anything cached off a file on disk."""
    if not os.path.isfile(path):
        raise HTTPException(404, f"no such file: {path}")
    return (os.path.abspath(path), os.path.getmtime(path))


def _load_midi_cached(path: str) -> dict:
    stamp = _stamp(path)
    cached = _cache_get(_midi_cache, stamp)
    if cached is not None:
        return cached
    try:
        mid = midi.load_midi(path)
    except midi.UnreadableMidi as exc:
        raise HTTPException(400, str(exc))
    _cache_put(_midi_cache, stamp, mid, 4)
    return mid


def _context_rows_cached(path: str) -> list[dict]:
    """Analyzed rows for an audio file used directly as context, never ingested."""
    stamp = _stamp(path)
    cached = _cache_get(_context_rows_cache, stamp)
    if cached is not None:
        return cached
    try:
        rows = ingest.analyze_file(Path(path))
    except Exception as exc:
        raise HTTPException(400, f"could not analyze {path}: {exc}")
    _cache_put(_context_rows_cache, stamp, rows, _CONTEXT_ROWS_CACHE_LIMIT)
    return rows


def _merge_contexts(a: dict, b: dict) -> dict:
    """Resolved chunks and direct audio files, one context: means where both
    sides measured the same thing, the more confident side where they disagree
    on a single answer.

    Tempo is picked, never averaged. The two sides of one session are routinely
    a half-time pair -- an 87 BPM loop and a 174 BPM bounce -- which
    tempo_score calls a perfect match and whose mean, 130.5, is a tempo neither
    side plays and every candidate is then scored against.
    """
    clap = a["clap"] + b["clap"]
    chroma = a["chroma"] + b["chroma"]
    tonic, kconf = max((a["tonic"], a["kconf"]), (b["tonic"], b["kconf"]),
                       key=lambda t: t[1])
    timed = [(x["bpm"], x.get("tconf", 1.0)) for x in (a, b) if x["bpm"]]
    bpm, tconf = max(timed, key=lambda t: t[1]) if timed else (None, 0.0)
    return {
        "idx": a["idx"],
        "clap": (clap / (np.linalg.norm(clap) + 1e-9)).astype(np.float32),
        "chroma": (chroma / (chroma.sum() + 1e-9)).astype(np.float32),
        "bpm": float(bpm) if bpm else None,
        # the confidence of the tempo actually kept, not a blend with a side
        # that had nothing to say about tempo
        "tconf": float(tconf),
        "tonic": int(tonic), "kconf": float(kconf),
        "roles": a["roles"] | b["roles"],
        "hashes": a["hashes"] | b["hashes"],
    }


def _build_context(corpus: scoring.Corpus, req: AnalyzeReq) -> tuple[dict, str, list]:
    """(context, novelty anchor, fields that were stated rather than inferred).

    Shared by every route that ranks: one place decides how the four context
    sources compose, so a map and a list can never disagree about what session
    they are describing.
    """
    if not (req.context_ids or req.context_paths or req.midi_path):
        raise HTTPException(400, "no context: give context_ids, context_paths"
                                 " or midi_path")
    # Novelty is a distance in CLAP space, so the context needs audio to stand
    # on. Chunks and direct files both carry their own; a MIDI-only context
    # borrows the corpus's best-fitting chunks as its anchor instead, and the
    # response says so -- the dial must not present a borrowed anchor as a
    # measurement of a session it never heard.
    novelty_anchor = "context"
    try:
        if req.context_paths:
            rows = [r for p in req.context_paths for r in _context_rows_cached(p)]
            ctx = scoring.context_from_rows(rows)
            if req.context_ids:
                ctx = _merge_contexts(scoring.build_context(corpus, req.context_ids), ctx)
        elif req.context_ids:
            ctx = scoring.build_context(corpus, req.context_ids)
        else:
            ctx = midi.context_from_midi(corpus, _load_midi_cached(req.midi_path))
            novelty_anchor = "corpus"
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # What Live states outright beats what the resolved chunks imply: a set at
    # 174 whose only matched samples are two 87 BPM one-shots is still at 174,
    # and inferring the context from that accident is how Fit's rhythm term ends
    # up scoring against the wrong tempo.
    applied = ableton.apply_session_context(
        ctx, _load_als_cached(req.session_path)) if req.session_path else []
    if req.midi_path:
        # after the .als: an exported MIDI file is the more deliberate statement.
        # On a MIDI-only context this re-applies onto its own numbers, which is
        # how the response learns which fields were stated rather than inferred.
        for field in midi.apply_midi_context(ctx, _load_midi_cached(req.midi_path)):
            if field not in applied:
                applied.append(field)
    if req.bpm:
        # the caller heard it from the transport itself: the last word on tempo
        ctx["bpm"] = float(req.bpm)
        ctx["tconf"] = 1.0
        if "bpm" not in applied:
            applied.append("bpm")
    return ctx, novelty_anchor, applied


def _analysis_cache_key(corpus: scoring.Corpus, req: AnalyzeReq) -> tuple:
    """Everything that can alter a completed ranking.

    Corpus identity changes whenever ingestion or a manual tag reloads it. The
    file stamps invalidate a ranking when the saved set, the MIDI file, or a
    direct context file changes. Keep context order because it is part of the
    request's exact semantics.
    """
    session_stamp = _stamp(req.session_path) if req.session_path else None
    midi_stamp = _stamp(req.midi_path) if req.midi_path else None
    path_stamps = (tuple(_stamp(p) for p in req.context_paths)
                   if req.context_paths else None)
    roots = None if req.active_roots is None else _normalized_roots(req.active_roots)
    return (
        corpus.cache_token, tuple(req.context_ids),
        None if req.distance is None else float(req.distance), req.preset, req.k,
        session_stamp, midi_stamp, path_stamps,
        None if req.bpm is None else float(req.bpm), roots,
    )


@app.post("/session/analyze")
def analyze(req: AnalyzeReq):
    corpus = _corpus()
    cache_key = _analysis_cache_key(corpus, req)
    cached = _cache_get(_analysis_cache, cache_key)
    if cached is not None:
        return cached

    allowed = _root_mask(corpus, req.active_roots)
    ctx, novelty_anchor, applied = _build_context(corpus, req)

    try:
        preset = presets.get(req.preset)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    results, floor = scoring.select(corpus, ctx, req.distance, req.k, allowed, preset)
    candidate_count = int(allowed.sum()) if allowed is not None else len(corpus)
    candidate_synthetic = corpus.synthetic[allowed] if allowed is not None else corpus.synthetic
    distance = preset.distance if req.distance is None else req.distance
    response = {"distance": distance, "fit_floor": round(floor, 3),
                "preset": preset.key,
                # `fit_floor` above is what the gate *ended up* at. A UI that only
                # shows the preset's own number cannot tell a preset that held from
                # one whose pool was too thin and quietly relaxed.
                "fit_floor_requested": preset.fit_floor,
                "fit_floor_relaxed": floor < preset.fit_floor,
                "bandwidth": preset.bandwidth,
                "redundancy": preset.redundancy,
                "role_mode": preset.role_mode,
                "corpus_size": candidate_count, "count": len(results), "results": results,
                "session_context": applied,
                "context": {"bpm": ctx["bpm"],
                            "tonic": (config.PITCH_NAMES[ctx["tonic"]]
                                      if ctx["tonic"] >= 0 else None),
                            "roles": sorted(ctx["roles"])},
                # Read off the corpus, not off config.MOCK: what matters is how the
                # rows being ranked were written, and a library ingested under mock
                # stays fiction long after the flag is turned off.
                "synthetic_novelty": bool(candidate_synthetic.any()),
                "synthetic_chunks": int(candidate_synthetic.sum()),
                "novelty_anchor": novelty_anchor}
    _cache_put(_analysis_cache, cache_key, response, _ANALYSIS_CACHE_LIMIT)
    return response


def _session_key(als: dict) -> str | None:
    """Live's declared key, or None when the set never turned key-awareness on."""
    root = als.get("scale_root")
    if root is None or not als.get("in_key"):
        return None
    mode = ({True: "maj", False: "min"}.get(als["is_major"])
            or als.get("scale_name") or f"scale#{als['scale_index']}")
    return f"{config.PITCH_NAMES[root % 12]} {mode}"


def _top_tags(rows, limit: int = 3) -> list[str]:
    """The file's tags, summed over its chunks.

    Summed rather than taken from the loudest chunk: a loop whose tags split
    between "kick" and "hi-hat" is still a drum loop, and either name alone
    would misdescribe it.
    """
    totals: dict[str, float] = {}
    for row in rows:
        for tag in json.loads(row["tags"]) if row["tags"] else []:
            totals[tag["tag"]] = totals.get(tag["tag"], 0.0) + tag["confidence"]
    return [name for name, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:limit]]


def _essentia_view(conn, file_hashes: set[str]) -> dict | None:
    """Essentia's answer for this sample, or None if the pass never saw it."""
    hashes = [h for h in file_hashes if h]
    if not hashes:
        return None
    marks = ",".join("?" * len(hashes))
    row = conn.execute(
        f"SELECT key_key, key_scale, key_confidence, bpm, bpm_confidence,"
        f" danceability, key_agreement FROM essentia WHERE file_hash IN ({marks})",
        hashes).fetchone()
    if not row:
        return None
    return {
        "key": f"{row['key_key']} {row['key_scale']}" if row["key_key"] else None,
        "key_confidence": row["key_confidence"],
        "bpm": round(row["bpm"], 1) if row["bpm"] is not None else None,
        "bpm_confidence": row["bpm_confidence"],
        "danceability": row["danceability"],
        # None means neither tool named a key, which is not the same as a clash
        "agrees": None if row["key_agreement"] is None else bool(row["key_agreement"]),
    }


def _chunk_digest(conn, chunk_ids: list[str]) -> dict:
    """What the UI shows for one resolved sample: its role, tempo and key."""
    if not chunk_ids:
        return {"chunks": 0, "role": None, "bpm": None, "tonic": None,
                "role_source": None, "tags": [], "essentia": None}
    marks = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"SELECT bpm, tonic_pc, role, role_source, file_hash, tags FROM chunks"
        f" WHERE chunk_id IN ({marks})", chunk_ids).fetchall()
    roles = [r["role"] for r in rows if r["role"]]
    sources = [r["role_source"] for r in rows if r["role_source"]]
    bpms = [r["bpm"] for r in rows if r["bpm"] is not None]
    tonics = [r["tonic_pc"] for r in rows if r["tonic_pc"] is not None and r["tonic_pc"] >= 0]
    return {
        "chunks": len(rows),
        "role": max(set(roles), key=roles.count) if roles else None,
        "role_source": max(set(sources), key=sources.count) if sources else None,
        "bpm": round(sum(bpms) / len(bpms), 1) if bpms else None,
        "tonic": config.PITCH_NAMES[max(set(tonics), key=tonics.count)] if tonics else None,
        "tags": _top_tags(rows),
        "essentia": _essentia_view(conn, {r["file_hash"] for r in rows}),
    }


class LinesReq(AnalyzeReq):
    """The same context as a ranking, asked for as routes rather than a list.

    Inherits every context field so a caller that can build a context can draw
    the map -- `distance` is simply unused: a line's stops span the range that
    one dial would have picked a single point from.
    """
    stops: int | None = Field(None, ge=2, le=12)


@app.post("/session/lines")
def session_lines(req: LinesReq):
    """Every line out of this session, with its stops and the interchanges.

    The map DIGLINE asks for: novelty scoped to one dimension at a time, so
    "farther" can say *farther in what respect*. Fit gates every stop, so the
    end of a line is strange but still works.
    """
    corpus = _corpus()
    ctx, _anchor, _applied = _build_context(corpus, req)
    try:
        preset = presets.get(req.preset)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return lines.network(corpus, ctx, _root_mask(corpus, req.active_roots),
                         preset, req.stops)


class MidiReq(BaseModel):
    path: str


@app.post("/session/midi")
def session_midi(req: MidiReq):
    """What a MIDI file states, before it anchors anything.

    The DAW-agnostic sibling of /session/als: no samples to resolve, so the
    payload is just the statements -- tempo, key (stated signature or estimated
    from the notes, labelled which), and the roles the programs imply.
    """
    mid = _load_midi_cached(req.path)
    pc, is_major, conf = midi.estimate_key(mid)
    return {
        "path": mid["path"],
        "bpm": mid["bpm"],
        "beats_per_bar": mid["beats_per_bar"],
        "key": (f"{config.PITCH_NAMES[pc]} {'major' if is_major else 'minor'}"
                if pc is not None else None),
        "key_source": ("stated" if mid["tonic_pc"] is not None
                       else "estimated" if pc is not None else None),
        "key_confidence": round(float(conf), 3),
        "notes": mid["notes"],
        "drum_share": round(float(mid["drum_share"]), 3),
        "roles": mid["roles"],
    }


@app.post("/session/als")
def session_als(req: AlsReq):
    """Parse a Live set and resolve its samples against the corpus.

    `unmatched` entries carry `ingest_path` when the file is on disk but absent
    from the corpus -- those are exactly the roots to feed back into POST /ingest.
    """
    conn = _conn()
    # Same one-entry cache the ranking path uses: opening a set and then digging
    # against it reparsed the same XML twice, and reopening it after a knob
    # session reparsed it again.
    als = _load_als_cached(req.path)

    res = ableton.resolve(conn, als)

    matched = [{**m, **_chunk_digest(conn, m["chunk_ids"])} for m in res["matched"]]
    unmatched = []
    for u in res["unmatched"]:
        on_disk = next((c for c in u["candidates"] if os.path.isfile(c)), None)
        unmatched.append({**u, "ingest_path": on_disk})

    return {
        "session": {
            "name": os.path.splitext(os.path.basename(als["path"]))[0],
            "path": als["path"],
            "creator": als["creator"],
            "tempo": als["tempo"],
            "key": _session_key(als),
            "in_key": als["in_key"],
            "samples": len(als["samples"]),
        },
        "matched": matched,
        "unmatched": unmatched,
        "context_ids": res["context_ids"],
    }


@app.post("/chunk/{chunk_id}/tag")
def tag(chunk_id: str, req: TagReq):
    if req.role not in config.ROLES:
        raise HTTPException(400, f"role must be one of {config.ROLES}")
    cur = _conn().execute(
        "UPDATE chunks SET role=?, role_source='manual' WHERE chunk_id=?",
        (req.role, chunk_id))
    _conn().commit()
    if not cur.rowcount:
        raise HTTPException(404, "no such chunk")
    state["corpus"] = ingest.load_corpus(_conn())
    return {"chunk_id": chunk_id, "role": req.role, "role_source": "manual"}


def _chunk_row(chunk_id: str):
    row = _conn().execute(
        "SELECT path, t_start, t_end, bpm FROM chunks WHERE chunk_id=?",
        (chunk_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"no such chunk: {chunk_id}")
    # A row can outlive its file: a folder moved while its drive was unmounted,
    # or a delete no walk has passed over since. Named here because the loader
    # raising through the handler reaches the desktop as a bare "500 Internal
    # Server Error", which says nothing about which file or why.
    if not os.path.isfile(row["path"]):
        raise HTTPException(410, f"the file this chunk came from is gone: {row['path']}"
                                 " -- re-ingest the folder to relink it")
    return row


def _audio_response(y, sr, meta):
    """Render meta travels in headers so the caller can show what was done to
    the audio -- a stretched preview should never be mistaken for the raw file."""
    headers = {f"x-audition-{k.replace('_', '-')}": str(v) for k, v in meta.items()}
    # The WAV already exists completely in memory. Streaming a BytesIO makes
    # Starlette iterate it through a worker thread; one Response avoids that
    # per-chunk handoff and reaches Electron noticeably sooner.
    return Response(content=audition.to_wav(y, sr).getvalue(), media_type="audio/wav",
                    headers=headers)


@app.get("/chunk/{chunk_id}/audio")
def audio(chunk_id: str, bpm: float | None = Query(None, gt=20, le=300,
                                                   description="session tempo to align to")):
    """The chunk, time-stretched to `bpm` when given. Pitch is never shifted."""
    row = _chunk_row(chunk_id)
    y, sr, meta = audition.render_chunk(row, bpm)
    return _audio_response(y, sr, meta)


@app.get("/chunk/{chunk_id}/peaks")
def chunk_peaks(chunk_id: str, buckets: int = Query(240, ge=16, le=2000),
                bpm: float | None = Query(None, gt=20, le=300,
                                          description="session tempo, as for playback")):
    """The waveform of the audio that will actually sound.

    `bpm` is passed through to the same renderer the audio routes use, and at the
    same PREVIEW_SR, so a drawn shape and the sound behind it are one render
    rather than two that merely resemble each other. Drawing an unstretched
    waveform over a stretched preview meant the playhead reached the end of the
    picture before the audio finished, which reads as playing the wrong sound.

    Renders through the same LRU as playback, so asking for a waveform warms the
    cache for the play that usually follows it.
    """
    row = _chunk_row(chunk_id)
    y, sr, meta = audition.render_chunk(row, bpm, sr=config.PREVIEW_SR)
    return {"chunk_id": chunk_id, "buckets": buckets,
            "duration": round(len(y) / sr, 3),
            "bpm": row["bpm"], "target_bpm": bpm, "stretched": meta["stretched"],
            "peaks": audition.peaks(y, buckets)}


@app.get("/session/preview")
def preview(candidate: str = Query(..., description="chunk to audition"),
            context: list[str] = Query(default_factory=list,
                                       description="chunk ids already in the session"),
            bpm: float | None = Query(None, gt=20, le=300),
            candidate_only: bool = False):
    """Context and candidate mixed into one tempo-aligned file.

    The point of the product is whether two things work together, so the default
    is to hand back the combination rather than two clips the listener has to
    assemble in their head.
    """
    cand_row = _chunk_row(candidate)
    ctx_rows = [_chunk_row(c) for c in context]

    # the session tempo wins; without one, the context's own tempo is the anchor
    target = bpm
    if target is None:
        bpms = [r["bpm"] for r in ctx_rows if r["bpm"]]
        target = float(np.median(bpms)) if bpms else None

    # A stable output rate makes the context bed reusable across candidates.
    # The chunk endpoint above remains native-rate for callers asking for raw audio.
    y, sr, meta = audition.render_chunk(cand_row, target, sr=config.PREVIEW_SR)
    if not candidate_only and ctx_rows:
        bed, _ = audition.render_context(ctx_rows, target, sr=sr)
        y = audition.mix(bed, y)
        meta = {**meta, "mixed_with": len(ctx_rows)}
    return _audio_response(y, sr, {**meta, "target_bpm": target})


# ---------------------------------------------------------------- listening test

class TrialsReq(BaseModel):
    context_ids: list[str]
    batch: str | None = None
    session_bpm: float | None = None


class RatingReq(BaseModel):
    rater: str
    scores: dict[str, int | None] = Field(default_factory=dict)
    note: str | None = None


@app.post("/trials/generate")
def trials_generate(req: TrialsReq):
    """Build a blind batch for one session context."""
    corpus = _corpus()
    try:
        return listening.generate(_conn(), corpus, req.context_ids,
                                  batch=req.batch, session_bpm=req.session_bpm)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/trials/next")
def trials_next(rater: str = Query(..., min_length=1), batch: str | None = None):
    """The next unrated trial for this rater.

    The response carries audio URLs and nothing else. Which arm produced the
    candidate, and at what DISTANCE, stay in the database -- putting either on
    the wire would unblind the experiment.
    """
    row = listening.next_trial(_conn(), rater, batch)
    prog = listening.progress(_conn(), rater, batch)
    if row is None:
        return {"trial": None, "progress": prog, "done": True}
    return {"trial": listening.trial_payload(row), "progress": prog, "done": False}


@app.post("/trials/{trial_id}/rate")
def trials_rate(trial_id: str, req: RatingReq):
    """Record a rating, then reveal what the trial was -- in that order."""
    try:
        return listening.record(_conn(), trial_id, req.rater, req.scores, req.note)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/rate", response_class=HTMLResponse)
def rate_page():
    """The rating surface. Deliberately plain: it is an instrument, not a product."""
    return RATE_HTML


RATE_HTML = """<!doctype html>
<meta charset="utf-8">
<title>Gold Digger listening test</title>
<style>
  :root { color-scheme: dark; --bg:#141613; --fg:#e9ebe4; --dim:#8b9184; --line:#2b302a; --accent:#c9a227; }
  body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.6 system-ui,sans-serif; }
  main { max-width:640px; margin:0 auto; padding:32px 20px 64px; }
  h1 { font-size:15px; letter-spacing:.14em; text-transform:uppercase; color:var(--dim); margin:0 0 4px; }
  .bar { height:3px; background:var(--line); border-radius:2px; margin:14px 0 26px; }
  .bar i { display:block; height:100%; background:var(--accent); border-radius:2px; transition:width .2s; }
  .players { display:flex; gap:8px; margin-bottom:26px; flex-wrap:wrap; }
  button { font:inherit; color:var(--fg); background:#20241e; border:1px solid var(--line);
           border-radius:6px; padding:10px 14px; cursor:pointer; }
  button:hover { border-color:var(--accent); }
  button[data-on] { background:var(--accent); color:#141613; border-color:var(--accent); }
  fieldset { border:0; border-top:1px solid var(--line); margin:0 0 18px; padding:16px 0 0; }
  legend { padding:0; font-size:14px; color:var(--fg); }
  .hint { color:var(--dim); font-size:12.5px; margin:2px 0 10px; }
  .scale { display:flex; gap:6px; }
  .scale label { flex:1; text-align:center; }
  .scale input { position:absolute; opacity:0; pointer-events:none; }
  .scale span { display:block; padding:9px 0; border:1px solid var(--line); border-radius:6px; cursor:pointer; }
  .scale input:checked + span { background:var(--accent); color:#141613; border-color:var(--accent); }
  .scale input:focus-visible + span { outline:2px solid var(--accent); outline-offset:2px; }
  .ends { display:flex; justify-content:space-between; color:var(--dim); font-size:12px; margin-top:5px; }
  textarea { width:100%; background:#20241e; color:var(--fg); border:1px solid var(--line);
             border-radius:6px; padding:10px; font:inherit; }
  #submit { width:100%; padding:13px; margin-top:8px; background:var(--accent); color:#141613; border:0; font-weight:600; }
  #submit:disabled { opacity:.4; cursor:not-allowed; }
  #reveal { margin-top:18px; color:var(--dim); font-size:13px; min-height:1.6em; }
  #done { text-align:center; padding:60px 0; color:var(--dim); }
</style>
<main>
  <h1>Listening test</h1>
  <div id="who" class="hint"></div>
  <div class="bar"><i id="prog" style="width:0%"></i></div>

  <div id="trial">
    <div class="players">
      <button id="p-context" type="button">Your session</button>
      <button id="p-mix" type="button">Session + candidate</button>
      <button id="p-solo" type="button">Candidate alone</button>
    </div>
    <form id="form"></form>
    <div id="reveal"></div>
  </div>
  <div id="done" hidden>Nothing left to rate. Thank you.</div>
</main>
<script>
const QUESTIONS = {
  obviousness:      ["How obvious or expected was this suggestion?", "surprising", "obvious"],
  compatibility:    ["How well could this material work with the session?", "not at all", "very well"],
  inspiration:      ["Does hearing this make you want to try something?", "not at all", "very much"],
  discovery:        ["Would you have been likely to find this yourself?", "never", "certainly"],
  direction_change: ["Does it suggest a direction you had not considered?", "no", "strongly"]
};
const params = new URLSearchParams(location.search);
let rater = params.get("rater") || localStorage.getItem("gd-rater");
if (!rater) { rater = prompt("Your name or initials:") || "anon"; }
localStorage.setItem("gd-rater", rater);
document.getElementById("who").textContent = "rating as " + rater;

const audio = new Audio();
let current = null, playing = null;

function play(kind, url, button) {
  if (playing === kind) { audio.pause(); playing = null; paint(); return; }
  audio.src = url; audio.currentTime = 0;
  audio.play().then(() => { playing = kind; paint(); }).catch(() => {});
}
audio.addEventListener("ended", () => { playing = null; paint(); });
function paint() {
  for (const [kind, id] of [["context","p-context"],["mix","p-mix"],["solo","p-solo"]]) {
    const b = document.getElementById(id);
    if (playing === kind) b.setAttribute("data-on",""); else b.removeAttribute("data-on");
  }
}

function renderForm() {
  const form = document.getElementById("form");
  form.innerHTML = Object.entries(QUESTIONS).map(([key, [q, lo, hi]]) => `
    <fieldset>
      <legend>${q}</legend>
      <div class="scale">
        ${[1,2,3,4,5,6,7].map(n => `
          <label><input type="radio" name="${key}" value="${n}"><span>${n}</span></label>
        `).join("")}
      </div>
      <div class="ends"><span>${lo}</span><span>${hi}</span></div>
    </fieldset>
  `).join("") + `
    <fieldset>
      <legend>Anything worth saying about this one?</legend>
      <p class="hint">Especially if it was unusually good or unusually wrong.</p>
      <textarea name="note" rows="2"></textarea>
    </fieldset>
    <button id="submit" type="submit" disabled>Submit and continue</button>`;

  form.addEventListener("change", () => {
    const answered = Object.keys(QUESTIONS).every(k => form.elements[k].value);
    document.getElementById("submit").disabled = !answered;
  });
}

async function load() {
  const res = await fetch(`/trials/next?rater=${encodeURIComponent(rater)}`);
  const data = await res.json();
  document.getElementById("prog").style.width =
    data.progress.total ? (100 * data.progress.done / data.progress.total) + "%" : "0%";
  if (data.done) {
    document.getElementById("trial").hidden = true;
    document.getElementById("done").hidden = false;
    return;
  }
  current = data.trial;
  playing = null; paint();
  document.getElementById("reveal").textContent = "";
  renderForm();
  document.getElementById("p-context").onclick = () => play("context", current.context_url);
  document.getElementById("p-mix").onclick     = () => play("mix", current.mix_url);
  document.getElementById("p-solo").onclick    = () => play("solo", current.candidate_url);
}

document.getElementById("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const scores = {};
  for (const k of Object.keys(QUESTIONS)) scores[k] = Number(form.elements[k].value);
  audio.pause(); playing = null;
  const res = await fetch(`/trials/${current.trial_id}/rate`, {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({ rater, scores, note: form.elements.note.value || null })
  });
  const was = await res.json();
  document.getElementById("reveal").textContent =
    `that was: ${was.strategy}${was.distance != null ? " @ distance " + was.distance : ""}`;
  setTimeout(load, 900);
});

document.addEventListener("submit", e => e.preventDefault());
load();
</script>
"""
