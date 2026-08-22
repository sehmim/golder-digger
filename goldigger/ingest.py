"""Walk a folder, chunk each file, extract features, upsert into SQLite."""
from __future__ import annotations

import datetime as dt
import json
import traceback
import uuid
from pathlib import Path

import numpy as np

from . import config, db, features, mock

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


def analyze_file(path: Path) -> list[dict]:
    """One file -> chunk rows. Honours config.MOCK."""
    fh = features.file_hash(path)
    role, role_source = features.role_from_path(path)

    if config.MOCK:
        import soundfile as sf
        try:
            duration = sf.info(str(path)).duration
        except Exception:
            duration = 8.0
        rhythm = mock.rhythm(fh)
        spans = features.chunk_boundaries(duration, rhythm)
        rows = []
        for i, (t0, t1) in enumerate(spans):
            cid = f"{fh[:12]}:{i}"
            ch = mock.chroma(cid)
            tonal, tconf = mock.confidences(cid)
            pc, maj, conf = features.estimate_key(ch, gate=tonal)
            tags = features.tags_from_sims(mock.tag_sims(cid))
            r, src = _role_or_tags(role, role_source, tags)
            rows.append(dict(
                chunk_id=cid, path=str(path), file_hash=fh, chunk_index=i,
                t_start=t0, t_end=t1, bpm=rhythm["bpm"],
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


def run_job(conn, job_id: str, root: str):
    """Synchronous body of an ingest job. Called from a background task."""
    now = dt.datetime.now(dt.UTC).isoformat()
    paths = walk(root)
    conn.execute("UPDATE jobs SET state='running', total=?, started_at=? WHERE job_id=?",
                 (len(paths), now, job_id))
    conn.commit()

    seen = {r["file_hash"] for r in conn.execute("SELECT file_hash FROM files WHERE status='ok'")}
    done = failed = 0
    for path in paths:
        try:
            fh = features.file_hash(path)
            if fh in seen:                      # content-hash dedupe
                done += 1
                continue
            rows = analyze_file(path)
            upsert(conn, rows)
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

    conn.execute("UPDATE jobs SET state='finished', finished_at=? WHERE job_id=?",
                 (dt.datetime.now(dt.UTC).isoformat(), job_id))
    conn.commit()


def new_job(conn, root: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    conn.execute("INSERT INTO jobs (job_id, root, state) VALUES (?,?,'queued')",
                 (job_id, str(root)))
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
