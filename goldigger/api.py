"""Localhost HTTP surface. Electron spawns this as a child process."""
from __future__ import annotations

import asyncio
import os
import json

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from . import ableton, config, db, essentia_runner, ingest, scoring

app = FastAPI(title="Gold Digger", version="0.1.0")
state: dict = {"conn": None, "corpus": None}


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
    context_ids: list[str]
    distance: float = Field(50, ge=0, le=100,
                            description="target novelty percentile, not a threshold")
    k: int = Field(config.DEFAULT_K, ge=1, le=100)


class TagReq(BaseModel):
    role: str


class AlsReq(BaseModel):
    path: str = Field(..., description="a .als on disk")


class EssentiaReq(BaseModel):
    root: str = Field(..., description="the folder that was ingested")


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    c = state["corpus"]
    return {"ok": True, "mock": config.MOCK, "chunks": len(c) if c else 0,
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
        ingest.run_job(worker, job_id, targets)
        return ingest.load_corpus(worker)

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


@app.post("/session/analyze")
def analyze(req: AnalyzeReq):
    corpus = _corpus()
    try:
        ctx = scoring.build_context(corpus, req.context_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    results, floor = scoring.select(corpus, ctx, req.distance, req.k)
    return {"distance": req.distance, "fit_floor": round(floor, 3),
            "corpus_size": len(corpus), "count": len(results), "results": results}


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


@app.post("/session/als")
def session_als(req: AlsReq):
    """Parse a Live set and resolve its samples against the corpus.

    `unmatched` entries carry `ingest_path` when the file is on disk but absent
    from the corpus -- those are exactly the roots to feed back into POST /ingest.
    """
    conn = _conn()
    if not os.path.isfile(req.path):
        raise HTTPException(404, f"no such file: {req.path}")
    try:
        als = ableton.load_als(req.path)
    except ableton.UnreadableSet as exc:
        raise HTTPException(400, str(exc))

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


@app.get("/chunk/{chunk_id}/audio")
def audio(chunk_id: str):
    row = _conn().execute(
        "SELECT path, t_start, t_end FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such chunk")
    import io
    import librosa
    import soundfile as sf
    y, sr = librosa.load(row["path"], sr=None, mono=True,
                         offset=row["t_start"], duration=row["t_end"] - row["t_start"])
    buf = io.BytesIO()
    sf.write(buf, y, sr, format="WAV")
    buf.seek(0)
    return StreamingResponse(buf, media_type="audio/wav")
