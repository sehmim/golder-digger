"""Localhost HTTP surface. Electron spawns this as a child process."""
from __future__ import annotations

import asyncio
import os
import json

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, model_validator

from . import ableton, audition, config, db, essentia_runner, ingest, listening, scoring

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


def _chunk_row(chunk_id: str):
    row = _conn().execute(
        "SELECT path, t_start, t_end, bpm FROM chunks WHERE chunk_id=?",
        (chunk_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"no such chunk: {chunk_id}")
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
