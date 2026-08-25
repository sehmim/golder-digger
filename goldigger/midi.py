"""Standard MIDI files as session context: the DAW-agnostic half of ableton.py.

A .als names one DAW; a .mid is what every DAW can export. And it is *better*
evidence than audio where it speaks: notes are symbolic, so the pitch-class
distribution is a statement of the session's harmony rather than an estimate
squeezed through HPSS and chroma -- which is why apply_midi_context is allowed
to overwrite the chroma the matched chunks implied, something the .als path
never does.

The parser is hand-rolled for the same reason the 'able' AIFC decoder is: the
subset this needs (tempo, signatures, notes, programs) is a page of struct
reads, and a dependency would be larger than the code it replaced.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from . import config


class UnreadableMidi(Exception):
    """Named, and carries the path: 'a MIDI file failed' is not actionable."""

    def __init__(self, path, why: str):
        super().__init__(f"{path}: {why}")
        self.path = str(path)


def _varlen(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos


def _track_events(data: bytes):
    """(ticks, status, payload) per event, running status resolved.

    Only channel messages become the running status. The spec says meta and
    sysex cancel it; real exports (karaoke files, older sequencers) instead
    continue the previous channel status across them. Remembering the last
    channel status rather than clearing it reads both dialects correctly --
    and, crucially, stops a 0xFF from *becoming* the running status, which
    turns the next note-on into a fake meta event whose velocity is read as a
    payload length and silently eats the rest of the track.
    """
    pos, ticks, status, running = 0, 0, 0, 0
    while pos < len(data):
        delta, pos = _varlen(data, pos)
        ticks += delta
        byte = data[pos]
        if byte & 0x80:
            status = byte
            pos += 1
            if status < 0xF0:
                running = status
        else:
            if not running:
                raise ValueError(f"data byte {byte:#04x} with no running status")
            status = running
        if status == 0xFF:                      # meta: type, varlen, payload
            mtype = data[pos]
            size, pos = _varlen(data, pos + 1)
            yield ticks, 0xFF, (mtype, data[pos:pos + size])
            pos += size
        elif status in (0xF0, 0xF7):            # sysex: skipped, but consumed
            size, pos = _varlen(data, pos)
            pos += size
        else:
            width = 1 if (status & 0xF0) in (0xC0, 0xD0) else 2
            yield ticks, status, data[pos:pos + width]
            pos += width


def load_midi(path) -> dict:
    """Parse a .mid into tempo, signatures, pitch-class weights and roles.

    Tempo is the *first* set_tempo: a DAW export opens with the project tempo,
    and a ramp's later values are movement inside the session, not its anchor.
    No set_tempo at all reports None rather than the spec's assumed 120 -- an
    assumption is not a statement, and only statements anchor the context.

    Pitch-class weights are duration x velocity, channel 10 excluded: drums
    name no pitch class, but their share is kept because it names a role.
    """
    data = Path(path).expanduser().read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise UnreadableMidi(path, "not a standard MIDI file")
    _, ntrks, division = struct.unpack(">HHH", data[8:14])

    bpm = beats_per_bar = None
    keysig: tuple[int, bool] | None = None
    pc = np.zeros(12, dtype=np.float64)
    drum_weight = total_weight = 0.0
    programs: set[int] = set()
    notes = 0

    pos = 14
    for _ in range(ntrks):
        if pos + 8 > len(data) or data[pos:pos + 4] != b"MTrk":
            break                       # a truncated tail loses tracks, not the file
        size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        track = data[pos + 8:pos + 8 + size]
        pos += 8 + size

        open_notes: dict[tuple[int, int], tuple[int, int]] = {}
        end = 0
        try:
            for ticks, status, payload in _track_events(track):
                end = max(end, ticks)
                if status == 0xFF:
                    mtype, body = payload
                    if mtype == 0x51 and bpm is None and len(body) == 3:
                        uspq = int.from_bytes(body, "big")
                        if uspq:
                            bpm = round(60_000_000 / uspq, 2)
                    elif mtype == 0x58 and beats_per_bar is None and body:
                        beats_per_bar = body[0]
                    elif mtype == 0x59 and keysig is None and len(body) >= 2:
                        sf = struct.unpack(">b", body[:1])[0]
                        keysig = (sf, body[1] == 0)
                    continue
                kind, channel = status & 0xF0, status & 0x0F
                if kind == 0xC0:
                    programs.add(payload[0])
                elif kind == 0x90 and payload[1] > 0:
                    open_notes[(channel, payload[0])] = (ticks, payload[1])
                    notes += 1
                elif kind == 0x80 or (kind == 0x90 and payload[1] == 0):
                    started = open_notes.pop((channel, payload[0]), None)
                    if started:
                        t0, vel = started
                        w = (ticks - t0) * (vel / 127.0)
                        total_weight += w
                        if channel == 9:
                            drum_weight += w
                        else:
                            pc[payload[0] % 12] += w
        except (IndexError, ValueError) as exc:
            raise UnreadableMidi(path, f"malformed track data: {exc}") from exc
        for (channel, pitch), (t0, vel) in open_notes.items():
            w = (end - t0) * (vel / 127.0)      # never released: rings to track end
            total_weight += w
            if channel == 9:
                drum_weight += w
            else:
                pc[pitch % 12] += w

    if notes == 0 and bpm is None and keysig is None:
        raise UnreadableMidi(path, "no notes and no statements: nothing to anchor")

    tonic_pc = is_major = None
    if keysig is not None:
        sf, major = keysig
        # circle of fifths from C; the relative minor sits three semitones down
        tonic_pc = (sf * 7) % 12 if major else (sf * 7 + 9) % 12
        is_major = major

    s = pc.sum()
    return {
        "path": str(path),
        "bpm": bpm,
        "beats_per_bar": beats_per_bar,
        "tonic_pc": tonic_pc,
        "is_major": is_major,
        "chroma": (pc / s).astype(np.float32) if s > 0 else None,
        "notes": notes,
        "drum_share": (drum_weight / total_weight) if total_weight > 0 else 0.0,
        "programs": sorted(programs),
        "roles": _roles(programs, drum_weight, total_weight),
    }


def _roles(programs: set[int], drum_weight: float, total_weight: float) -> list[str]:
    """General MIDI programs mapped into the corpus role vocabulary.

    Only ranges whose role is unambiguous are mapped -- config.MIDI_PROGRAM_ROLES
    is deliberately sparse the same way the filename vocabulary is: a wrong role
    poisons the complement-seeking term, a missing one just stays quiet.
    """
    roles = {role for lo, hi, role in config.MIDI_PROGRAM_ROLES
             for p in programs if lo <= p <= hi}
    if total_weight > 0 and drum_weight / total_weight >= config.MIDI_DRUM_SHARE:
        roles.add("drums")
    return sorted(roles)


def estimate_key(mid: dict) -> tuple[int | None, bool | None, float]:
    """The stated signature when there is one, else the notes' own answer.

    gate=1.0 for the estimate: tonalness measures whether audio *has* pitches
    to read, and symbolic notes always do.
    """
    if mid["tonic_pc"] is not None:
        return mid["tonic_pc"], bool(mid["is_major"]), config.MIDI_KEYSIG_CONFIDENCE
    if mid["chroma"] is not None and mid["notes"] >= config.MIDI_MIN_NOTES:
        from . import features
        return features.estimate_key(mid["chroma"], gate=1.0)
    return None, None, 0.0


def apply_midi_context(ctx: dict, mid: dict) -> list[str]:
    """Overwrite inferred context metadata with what the MIDI file states.

    The mirror of ableton.apply_session_context, plus the one override the .als
    path can never make: harmony. Matched chunks *estimate* the session's
    chroma through audio; the file's notes state it.
    """
    applied = []
    if mid["bpm"]:
        ctx["bpm"] = float(mid["bpm"])
        ctx["tconf"] = 1.0
        applied.append("bpm")
    pc, is_major, conf = estimate_key(mid)
    # A stated signature always lands, including over a Live set's own stated
    # key (which pins kconf to 1.0): the handler applies the .als first
    # precisely so the exported MIDI -- the more deliberate statement -- wins.
    # Comparing confidences alone could never express that, since 0.95 < 1.0.
    stated = mid["tonic_pc"] is not None
    if pc is not None and (stated or conf >= (ctx.get("kconf") or 0.0)):
        ctx["tonic"] = int(pc)
        ctx["kconf"] = float(conf)
        applied.append("tonic")
    if mid["chroma"] is not None and mid["notes"] >= config.MIDI_MIN_NOTES:
        ctx["chroma"] = mid["chroma"]
        applied.append("chroma")
    added = set(mid["roles"]) - ctx["roles"]
    if added:
        ctx["roles"] |= added
        applied.append("roles")
    return applied


def context_from_midi(corpus, mid: dict) -> dict:
    """A full scoring context from a MIDI file alone -- no chunks resolved.

    Fit needs no audio: harmony, tempo and roles are all stated or estimated
    above. Novelty does -- it is a distance in CLAP space -- so the context
    borrows an anchor: the mean embedding of the corpus chunks that fit this
    context best, i.e. the sound of this session as this library could render
    it. That anchor is honest about being borrowed: the API reports
    novelty_anchor="corpus" so a UI never presents the dial as a measurement
    of a session it has not heard.
    """
    from . import scoring
    pc, _, conf = estimate_key(mid)
    chroma = (mid["chroma"] if mid["chroma"] is not None
              else np.full(12, 1 / 12, dtype=np.float32))
    ctx = {
        "idx": [],
        "chroma": chroma,
        "bpm": float(mid["bpm"]) if mid["bpm"] else None,
        "tconf": 1.0 if mid["bpm"] else 0.0,
        "tonic": int(pc) if pc is not None else -1,
        "kconf": float(conf),
        "roles": set(mid["roles"]),
        "hashes": set(),
    }
    fit = scoring.fit_all(corpus, ctx)["fit"]
    top = np.argsort(fit)[-min(config.MIDI_ANCHOR_TOP, len(fit)):]
    clap = corpus.clap[top].mean(axis=0)
    ctx["clap"] = clap / (np.linalg.norm(clap) + 1e-9)
    return ctx


def describe(mid: dict) -> str:
    key = "-"
    pc, is_major, conf = estimate_key(mid)
    if pc is not None:
        mode = "major" if is_major else "minor"
        stated = "stated" if mid["tonic_pc"] is not None else f"estimated {conf:.2f}"
        key = f"{config.PITCH_NAMES[pc]} {mode} ({stated})"
    return (f"tempo={mid['bpm'] or '-'}  key={key}  notes={mid['notes']}"
            f"  drums={mid['drum_share']:.0%}  roles={','.join(mid['roles']) or '-'}")
