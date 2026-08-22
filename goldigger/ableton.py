"""Read a Live set (.als): session tempo, key, and the samples it references.

Live supplies two things the extractor cannot recover from a 0.9 s one-shot --
the session tempo and (Live 12) the declared key. Those are ground truth for the
*context* side of Fit. They do not fix the corpus side: fit_all takes
min(corpus.kconf, ctx["kconf"]), so a corpus of low-confidence one-shots keeps H
pinned near NEUTRAL no matter how good the session metadata is.

An .als is gzipped XML. Sample references live under <SampleRef><FileRef>, whose
shape changed across Live versions, so every known variant is tried in turn.
"""
from __future__ import annotations

import gzip
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from . import config, features

# The scale element changed shape between Live versions, verified against real sets:
#   Live 10: <ScaleInformation><RootNote Value="0"/><Name Value="Major"/></>
#   Live 12: <ScaleInformation><Root     Value="0"/><Name Value="0"/></>
# The Live 10 string is unambiguous. The Live 12 integer is an index into Live's own
# scale list, so only 0/1 are read as major/minor -- every other index yields mode=None
# rather than guessing, since a mis-ordered table would silently flip the mode.
SCALE_MAJOR = 0
SCALE_MINOR = 1


class UnreadableSet(ValueError):
    """An .als that cannot be parsed -- truncated, empty, or not actually gzip."""


def _parse_scale_name(raw):
    """-> (scale_index|None, scale_name|None, is_major|None)."""
    if raw is None:
        return None, None, None
    if raw.lstrip("-").isdigit():
        idx = int(raw)
        return idx, None, {SCALE_MAJOR: True, SCALE_MINOR: False}.get(idx)
    mode = {"major": True, "minor": False}.get(raw.strip().lower())
    return None, raw, mode


def _val(el, tag, default=None):
    """Live wraps nearly every scalar as <Tag Value="..." />."""
    if el is None:
        return default
    child = el.find(tag)
    return default if child is None else child.get("Value", default)


def _open(path) -> ET.Element:
    """A real archive contains truncated and zero-byte sets; fail with the path named."""
    try:
        with gzip.open(str(path), "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise UnreadableSet(f"{path}: not gzip ({exc})") from exc
    if not raw.strip():
        raise UnreadableSet(f"{path}: empty file")
    try:
        return ET.fromstring(raw.decode("utf-8", "replace"))
    except ET.ParseError as exc:
        raise UnreadableSet(f"{path}: malformed XML ({exc})") from exc


# ---------------------------------------------------------------- sample refs

def _candidate_paths(fileref: ET.Element, project_dir: Path) -> list[Path]:
    """Every path shape Live has used, most authoritative first.

    Live 11/12 write a flat <RelativePath Value="a/b/c.wav" /> next to an
    absolute <Path>. Live 9/10 nested <RelativePathElement Dir="a" /> instead.
    A set moved between machines keeps a stale absolute path, so relative
    candidates are kept even when the absolute one is present.
    """
    out: list[Path] = []

    abs_path = fileref.get("Path") or _val(fileref, "Path")
    if abs_path:
        out.append(Path(abs_path))

    rel = _val(fileref, "RelativePath")
    if rel:
        out.append(Path(os.path.normpath(project_dir / rel)))

    legacy = [e.get("Dir", "") for e in fileref.iter("RelativePathElement")]
    name = _val(fileref, "Name")
    if legacy and name:
        out.append(Path(os.path.normpath(project_dir.joinpath(*legacy) / name)))

    seen, uniq = set(), []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def sample_refs(root: ET.Element, project_dir: Path) -> list[dict]:
    """One entry per <SampleRef>. Deduped -- a clip and its warp copy share a file."""
    refs, seen = [], set()
    for sr in root.iter("SampleRef"):
        fr = sr.find("FileRef")
        if fr is None:
            continue
        cands = _candidate_paths(fr, project_dir)
        if not cands:
            continue
        key = str(cands[0])
        if key in seen:
            continue
        seen.add(key)
        refs.append({
            "name": _val(fr, "Name") or cands[0].name,
            "candidates": cands,
            "relative_path_type": _val(fr, "RelativePathType"),
            "live_pack": _val(fr, "LivePackName") or None,
        })
    return refs


# ---------------------------------------------------------------- parse

def load_als(path) -> dict:
    """Parse a .als into tempo, key, and its sample references."""
    path = Path(path).expanduser().resolve()
    root = _open(path)
    project_dir = path.parent

    # Session tempo lives on the main track. Live 12 renamed MasterTrack -> MainTrack,
    # and clip/preset .als files have no track at all -- so fall back to document order
    # rather than reporting no tempo. Scenes also carry <Tempo> with no Manual value,
    # so taking the first <Tempo> blindly is not safe on every set.
    tempo_el = None
    for tag in ("MainTrack", "MasterTrack"):
        track = root.find(f".//{tag}")
        if track is not None:
            tempo_el = track.find(".//Tempo")
            if tempo_el is not None:
                break
    if tempo_el is None:
        tempo_el = next((t for t in root.iter("Tempo") if t.find("Manual") is not None), None)
    tempo = _val(tempo_el, "Manual")

    scale_el = root.find(".//ScaleInformation")
    scale_root = _val(scale_el, "Root")          # Live 12
    if scale_root is None:
        scale_root = _val(scale_el, "RootNote")  # Live 10
    idx, name, mode = _parse_scale_name(_val(scale_el, "Name"))
    in_key = (_val(root.find(".//LiveSet"), "InKey") or
              _val(root, "InKey") or "false").lower() == "true"

    return {
        "path": str(path),
        "project_dir": str(project_dir),
        "creator": root.get("Creator"),
        "tempo": float(tempo) if tempo is not None else None,
        "scale_root": int(scale_root) if scale_root is not None else None,
        "scale_index": idx,
        "scale_name": name,
        "is_major": mode,
        "in_key": in_key,
        "samples": sample_refs(root, project_dir),
    }


# ---------------------------------------------------------------- resolve

def resolve(conn, als: dict) -> dict:
    """Sample references -> corpus chunk ids.

    Content hash first: it is what ingest deduped on, so it survives a file being
    moved or renamed. Then exact path, then basename -- each weaker, and each
    labelled in the output so a match can be audited rather than trusted.
    """
    matched, unmatched = [], []
    for ref in als["samples"]:
        hit = None
        for cand in ref["candidates"]:
            if not cand.is_file():
                continue
            fh = features.file_hash(cand)
            rows = conn.execute(
                "SELECT chunk_id FROM chunks WHERE file_hash=? ORDER BY chunk_index",
                (fh,)).fetchall()
            if rows:
                hit = {"method": "hash", "resolved_path": str(cand),
                       "chunk_ids": [r["chunk_id"] for r in rows]}
            break                      # the file exists; a hash miss is a real miss

        if hit is None:
            for cand in ref["candidates"]:
                rows = conn.execute(
                    "SELECT chunk_id FROM chunks WHERE path=? ORDER BY chunk_index",
                    (str(cand),)).fetchall()
                if rows:
                    hit = {"method": "path", "resolved_path": str(cand),
                           "chunk_ids": [r["chunk_id"] for r in rows]}
                    break

        if hit is None and ref["name"]:
            rows = conn.execute(
                "SELECT chunk_id, path FROM chunks WHERE path LIKE ? ORDER BY chunk_index",
                ("%/" + ref["name"],)).fetchall()
            files = {r["path"] for r in rows}
            if len(files) == 1:
                hit = {"method": "basename", "resolved_path": rows[0]["path"],
                       "chunk_ids": [r["chunk_id"] for r in rows]}
            elif len(files) > 1:
                unmatched.append({**_ref_summary(ref),
                                  "reason": f"basename ambiguous across {len(files)} files"})
                continue

        if hit:
            matched.append({**_ref_summary(ref), **hit})
        else:
            unmatched.append({**_ref_summary(ref), "reason": "not in corpus"})

    return {
        "context_ids": [c for m in matched for c in m["chunk_ids"]],
        "matched": matched,
        "unmatched": unmatched,
    }


def _ref_summary(ref: dict) -> dict:
    return {"name": ref["name"], "candidates": [str(p) for p in ref["candidates"]]}


# ---------------------------------------------------------------- session context

def apply_session_context(ctx: dict, als: dict, key_confidence: float = 1.0) -> list[str]:
    """Overwrite inferred context metadata with what Live states outright.

    Returns the list of fields actually overridden. The key is only trusted when
    the set has key-awareness on: a set that never touched it still reports
    Root=0/Name=0, which is indistinguishable from a deliberate C major.
    """
    applied = []
    if als.get("tempo"):
        ctx["bpm"] = float(als["tempo"])
        applied.append("bpm")
    if als.get("in_key") and als.get("scale_root") is not None:
        ctx["tonic"] = int(als["scale_root"])
        ctx["kconf"] = float(key_confidence)
        applied.append("tonic")
    return applied


def describe(als: dict) -> str:
    root = als.get("scale_root")
    key = "-"
    if root is not None:
        mode = ({True: "major", False: "minor"}.get(als["is_major"])
                or als.get("scale_name") or f"scale#{als['scale_index']}")
        key = f"{config.PITCH_NAMES[root % 12]} {mode}"
    return (f"{als['creator']}  tempo={als['tempo']}  key={key}"
            f"  in_key={als['in_key']}  samples={len(als['samples'])}")
