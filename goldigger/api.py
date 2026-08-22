"""Localhost HTTP surface. Electron spawns this as a child process."""
from __future__ import annotations

import asyncio
import os

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from . import ableton, audition, config, db, ingest, scoring

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


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    c = state["corpus"]
    return {"ok": True, "mock": config.MOCK, "chunks": len(c) if c else 0,
            "db": str(config.DB_PATH)}


@app.post("/ingest")
async def start_ingest(req: IngestReq):
    conn = state["conn"]
    targets = req.targets()
    job_id = ingest.new_job(conn, targets)

    async def _run():
        # extraction is CPU/GPU bound and releases the GIL, so a thread is enough
        await asyncio.to_thread(ingest.run_job, conn, job_id, targets)
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


def _session_key(als: dict) -> str | None:
    """Live's declared key, or None when the set never turned key-awareness on."""
    root = als.get("scale_root")
    if root is None or not als.get("in_key"):
        return None
    mode = ({True: "maj", False: "min"}.get(als["is_major"])
            or als.get("scale_name") or f"scale#{als['scale_index']}")
    return f"{config.PITCH_NAMES[root % 12]} {mode}"


def _chunk_digest(conn, chunk_ids: list[str]) -> dict:
    """What the UI shows for one resolved sample: its role, tempo and key."""
    if not chunk_ids:
        return {"chunks": 0, "role": None, "bpm": None, "tonic": None}
    marks = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"SELECT bpm, tonic_pc, role FROM chunks WHERE chunk_id IN ({marks})",
        chunk_ids).fetchall()
    roles = [r["role"] for r in rows if r["role"]]
    bpms = [r["bpm"] for r in rows if r["bpm"] is not None]
    tonics = [r["tonic_pc"] for r in rows if r["tonic_pc"] is not None and r["tonic_pc"] >= 0]
    return {
        "chunks": len(rows),
        "role": max(set(roles), key=roles.count) if roles else None,
        "bpm": round(sum(bpms) / len(bpms), 1) if bpms else None,
        "tonic": config.PITCH_NAMES[max(set(tonics), key=tonics.count)] if tonics else None,
    }


@app.post("/session/als")
def session_als(req: AlsReq):
    """Parse a Live set and resolve its samples against the corpus.

    `unmatched` entries carry `ingest_path` when the file is on disk but absent
    from the corpus -- those are exactly the roots to feed back into POST /ingest.
    """
    conn = state["conn"]
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
    cur = state["conn"].execute(
        "UPDATE chunks SET role=?, role_source='manual' WHERE chunk_id=?",
        (req.role, chunk_id))
    state["conn"].commit()
    if not cur.rowcount:
        raise HTTPException(404, "no such chunk")
    state["corpus"] = ingest.load_corpus(state["conn"])
    return {"chunk_id": chunk_id, "role": req.role, "role_source": "manual"}


def _chunk_row(chunk_id: str):
    row = state["conn"].execute(
        "SELECT path, t_start, t_end, bpm FROM chunks WHERE chunk_id=?",
        (chunk_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"no such chunk: {chunk_id}")
    return row


def _audio_response(y, sr, meta):
    """Render meta travels in headers so the caller can show what was done to
    the audio -- a stretched preview should never be mistaken for the raw file."""
    headers = {f"x-audition-{k.replace('_', '-')}": str(v) for k, v in meta.items()}
    return StreamingResponse(audition.to_wav(y, sr), media_type="audio/wav",
                             headers=headers)


@app.get("/chunk/{chunk_id}/audio")
def audio(chunk_id: str, bpm: float | None = Query(None, gt=20, le=300,
                                                   description="session tempo to align to")):
    """The chunk, time-stretched to `bpm` when given. Pitch is never shifted."""
    row = _chunk_row(chunk_id)
    y, sr, meta = audition.render_chunk(row, bpm)
    return _audio_response(y, sr, meta)


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

    y, sr, meta = audition.render_chunk(cand_row, target)
    if not candidate_only and ctx_rows:
        bed = np.zeros(0, dtype=np.float32)
        for r in ctx_rows:
            part, sr_c, _ = audition.render_chunk(r, target, sr=sr)
            bed = part if not len(bed) else audition.mix(bed, part)
        y = audition.mix(bed, y)
        meta = {**meta, "mixed_with": len(ctx_rows)}
    return _audio_response(y, sr, {**meta, "target_bpm": target})
