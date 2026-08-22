"""Localhost HTTP surface. Electron spawns this as a child process."""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import config, db, ingest, scoring

app = FastAPI(title="Gold Digger", version="0.1.0")
state: dict = {"conn": None, "corpus": None}


@app.on_event("startup")
def _startup():
    conn = db.connect()
    db.init(conn)
    state["conn"] = conn
    state["corpus"] = ingest.load_corpus(conn)


def _corpus():
    if state["corpus"] is None or len(state["corpus"]) == 0:
        raise HTTPException(409, "corpus is empty -- POST /ingest first")
    return state["corpus"]


# ---------------------------------------------------------------- models

class IngestReq(BaseModel):
    root: str = Field(..., description="folder (or file) to ingest")


class AnalyzeReq(BaseModel):
    context_ids: list[str]
    distance: float = Field(50, ge=0, le=100,
                            description="target novelty percentile, not a threshold")
    k: int = Field(config.DEFAULT_K, ge=1, le=100)


class TagReq(BaseModel):
    role: str


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    c = state["corpus"]
    return {"ok": True, "mock": config.MOCK, "chunks": len(c) if c else 0,
            "db": str(config.DB_PATH)}


@app.post("/ingest")
async def start_ingest(req: IngestReq):
    conn = state["conn"]
    job_id = ingest.new_job(conn, req.root)

    async def _run():
        # extraction is CPU/GPU bound and releases the GIL, so a thread is enough
        await asyncio.to_thread(ingest.run_job, conn, job_id, req.root)
        state["corpus"] = ingest.load_corpus(conn)

    asyncio.create_task(_run())
    return {"job_id": job_id}


@app.get("/ingest/status/{job_id}")
def ingest_status(job_id: str):
    row = state["conn"].execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such job")
    return dict(row)


@app.get("/library")
def library(limit: int = Query(100, le=1000), offset: int = 0,
            role: str | None = None):
    sql = ("SELECT chunk_id, path, chunk_index, t_start, t_end, bpm, beats_per_bar,"
           " tonic_pc, is_major, key_confidence, role, role_source FROM chunks")
    args: list = []
    if role:
        sql += " WHERE role=?"
        args.append(role)
    sql += " ORDER BY path, chunk_index LIMIT ? OFFSET ?"
    args += [limit, offset]
    rows = [dict(r) for r in state["conn"].execute(sql, args)]
    for r in rows:
        r["tonic"] = (config.PITCH_NAMES[r["tonic_pc"]]
                      if r["tonic_pc"] is not None and r["tonic_pc"] >= 0 else None)
    total = state["conn"].execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
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


@app.post("/chunk/{chunk_id}/tag")
def tag(chunk_id: str, req: TagReq):
    if req.role not in config.ROLES:
        raise HTTPException(400, f"role must be one of {config.ROLES}")
    cur = state["conn"].execute(
        "UPDATE chunks SET role=?, role_source='manual' WHERE chunk_id=?",
        (req.role, chunk_id))
    state["conn"].commit()
    if not cur.rowcount:
        raise HTTPException(404, "no such chunk")
    state["corpus"] = ingest.load_corpus(state["conn"])
    return {"chunk_id": chunk_id, "role": req.role, "role_source": "manual"}


@app.get("/chunk/{chunk_id}/audio")
def audio(chunk_id: str):
    row = state["conn"].execute(
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
