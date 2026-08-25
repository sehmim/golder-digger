"""MIDI as session context: statements, not estimates.

A .mid states tempo, key and the notes themselves, so the parser's job is to
read those statements faithfully -- and the context glue's job is to let them
overrule what audio inference guessed, the same way a Live set's header does.
"""
import struct

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from goldigger import api, config, db, ingest, midi, scoring


# ------------------------------------------------------------- SMF builder

def _meta(mtype: int, body: bytes, dt: int = 0) -> bytes:
    return bytes([dt, 0xFF, mtype, len(body)]) + body


def _ev(status: int, *data: int, dt: int = 0) -> bytes:
    return bytes([dt, status, *data])


def _track(*events: bytes) -> bytes:
    body = b"".join(events) + bytes([0, 0xFF, 0x2F, 0])
    return b"MTrk" + struct.pack(">I", len(body)) + body


def _smf(*tracks: bytes) -> bytes:
    return (b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), 96)
            + b"".join(tracks))


def _tempo(bpm: int) -> bytes:
    return _meta(0x51, int(60_000_000 / bpm).to_bytes(3, "big"))


def _keysig(sf_count: int, minor: bool) -> bytes:
    return _meta(0x59, struct.pack(">bB", sf_count, int(minor)))


def _note(pitch: int, channel: int = 0, vel: int = 100, ticks: int = 96) -> bytes:
    return (_ev(0x90 | channel, pitch, vel)
            + _ev(0x80 | channel, pitch, 0, dt=ticks))


def write_mid(path, *tracks) -> str:
    path.write_bytes(_smf(*tracks))
    return str(path)


# ------------------------------------------------------------- parsing

def test_statements_are_read(tmp_path):
    path = write_mid(tmp_path / "s.mid", _track(
        _tempo(174), _meta(0x58, bytes([3, 3, 24, 8])), _keysig(-1, True),
        _note(60)))

    mid = midi.load_midi(path)

    assert mid["bpm"] == pytest.approx(174, abs=0.01)
    assert mid["beats_per_bar"] == 3
    # one flat, minor: D minor
    assert (mid["tonic_pc"], mid["is_major"]) == (2, False)


@pytest.mark.parametrize("sf_count,minor,pc", [
    (0, False, 0),    # C major
    (-1, False, 5),   # F major
    (1, True, 4),     # E minor
    (3, False, 9),    # A major
])
def test_key_signature_circle_of_fifths(tmp_path, sf_count, minor, pc):
    mid = midi.load_midi(write_mid(tmp_path / "k.mid",
                                   _track(_keysig(sf_count, minor), _note(60))))
    assert mid["tonic_pc"] == pc


def test_no_tempo_statement_is_none_not_the_spec_default(tmp_path):
    mid = midi.load_midi(write_mid(tmp_path / "n.mid", _track(_note(60))))
    assert mid["bpm"] is None


def test_drums_carry_no_pitch_but_do_carry_a_role(tmp_path):
    mid = midi.load_midi(write_mid(tmp_path / "d.mid", _track(
        _note(36, channel=9), _note(42, channel=9))))

    assert mid["chroma"] is None            # nothing tonal was played
    assert mid["drum_share"] == 1.0
    assert mid["roles"] == ["drums"]


def test_programs_map_to_roles(tmp_path):
    mid = midi.load_midi(write_mid(tmp_path / "p.mid", _track(
        _ev(0xC1, 33), _note(40, channel=1),          # fingered bass
        _ev(0xC2, 81), _note(76, channel=2))))        # saw lead

    assert mid["roles"] == ["bass", "melody"]


def test_key_is_estimated_from_notes_when_unstated(tmp_path):
    scale = [60, 62, 64, 65, 67, 69, 71, 72, 64, 60]   # C major, tonic-heavy
    mid = midi.load_midi(write_mid(tmp_path / "e.mid",
                                   _track(*[_note(p) for p in scale])))

    pc, is_major, conf = midi.estimate_key(mid)
    assert (pc, is_major) == (0, True)
    assert conf > 0.0


def test_running_status_survives_a_meta_event(tmp_path):
    """Karaoke and older-sequencer exports interleave meta events between
    running-status note data. A parser that lets 0xFF *become* the running
    status reads the next note number as a meta type and its velocity as a
    payload length, silently eating the rest of the track."""
    # note-off as note-on velocity 0, which is what keeps a running status of
    # 0x90 alive across the marker -- the shape these files actually have
    explicit = write_mid(tmp_path / "explicit.mid", _track(
        _ev(0x90, 60, 100), _ev(0x90, 60, 0, dt=96),
        _meta(0x06, b"AAA"),
        _ev(0x90, 64, 100), _ev(0x90, 64, 0, dt=96)))
    interleaved = write_mid(tmp_path / "interleaved.mid", _track(
        _ev(0x90, 60, 100), _ev(0x90, 60, 0, dt=96),
        _meta(0x06, b"AAA"),                        # marker between the notes
        bytes([0, 64, 100]), bytes([96, 64, 0])))   # running status, no 0x90

    a, b = midi.load_midi(explicit), midi.load_midi(interleaved)

    assert b["notes"] == a["notes"] == 2
    assert np.allclose(b["chroma"], a["chroma"])


def test_a_data_byte_with_no_running_status_is_named(tmp_path):
    path = tmp_path / "bad.mid"
    path.write_bytes(_smf(_track(bytes([0, 60, 100]))))
    with pytest.raises(midi.UnreadableMidi) as err:
        midi.load_midi(str(path))
    assert "running status" in str(err.value)


def test_garbage_is_a_named_failure(tmp_path):
    bad = tmp_path / "not.mid"
    bad.write_bytes(b"RIFF this is not midi")
    with pytest.raises(midi.UnreadableMidi) as err:
        midi.load_midi(str(bad))
    assert "not.mid" in str(err.value)


# ------------------------------------------------------------- context glue

def test_statements_overrule_the_inferred_context(tmp_path):
    path = write_mid(tmp_path / "s.mid", _track(
        _tempo(174), _keysig(0, False), *[_note(p) for p in (60, 64, 67, 72,
                                                             60, 64, 67, 72)]))
    ctx = {"bpm": 120.0, "tconf": 0.4, "tonic": 7, "kconf": 0.3,
           "chroma": np.full(12, 1 / 12, dtype=np.float32), "roles": set()}

    applied = midi.apply_midi_context(ctx, midi.load_midi(path))

    assert set(applied) == {"bpm", "tonic", "chroma"}
    assert (ctx["bpm"], ctx["tconf"]) == (174.0, 1.0)
    assert (ctx["tonic"], ctx["kconf"]) == (0, config.MIDI_KEYSIG_CONFIDENCE)
    assert ctx["chroma"][0] > ctx["chroma"][1]


# ------------------------------------------------------------- api

@pytest.fixture
def client(tmp_path, monkeypatch):
    """A corpus of four tones, and the API pointed at it."""
    root = tmp_path / "lib"
    root.mkdir()
    for i in range(4):
        t = np.linspace(0, 2.0, int(2.0 * 22050), endpoint=False)
        sf.write(root / f"{i}.wav", 0.2 * np.sin(2 * np.pi * (200 + 60 * i) * t), 22050)

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db._local.__dict__.clear()
    conn = db.thread_conn(tmp_path / "t.db")
    db.init(conn)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    api.state["conn"] = conn
    api.state["corpus"] = ingest.load_corpus(conn)

    with TestClient(api.app) as c:
        yield c, conn, root


def test_a_midi_file_alone_is_a_context(client, tmp_path):
    c, conn, root = client
    path = write_mid(tmp_path / "s.mid", _track(
        _tempo(140), _keysig(0, False), *[_note(p) for p in (60, 64, 67, 72,
                                                             60, 64, 67, 72)]))

    body = c.post("/session/analyze", json={"midi_path": path, "distance": 50}).json()

    assert body["count"] > 0
    assert body["novelty_anchor"] == "corpus"   # no audio: the anchor is borrowed
    assert body["context"]["bpm"] == 140.0
    assert "bpm" in body["session_context"] and "tonic" in body["session_context"]


def test_an_audio_file_alone_is_a_context(client):
    c, conn, root = client

    body = c.post("/session/analyze", json={
        "context_paths": [str(root / "0.wav")], "distance": 50}).json()

    assert body["count"] > 0
    assert body["novelty_anchor"] == "context"  # its own audio anchors the dial
    # matching against a file the corpus holds must never return that file
    assert all(r["path"] != str(root / "0.wav") for r in body["results"])


def test_a_stated_midi_key_overrides_a_stated_live_key(client, tmp_path):
    """The handler applies the .als first so the exported MIDI -- the more
    deliberate statement -- wins. Live's key pins kconf to 1.0, so comparing
    confidences alone could never express that."""
    ctx = {"bpm": 120.0, "tconf": 1.0, "tonic": 0, "kconf": 1.0,
           "chroma": np.full(12, 1 / 12, dtype=np.float32), "roles": set()}
    path = write_mid(tmp_path / "s.mid", _track(_keysig(1, True), _note(64)))

    applied = midi.apply_midi_context(ctx, midi.load_midi(path))

    assert "tonic" in applied
    assert ctx["tonic"] == 4                    # E minor, not Live's C


def test_an_estimated_midi_key_still_defers_to_stronger_evidence(client, tmp_path):
    ctx = {"bpm": 120.0, "tconf": 1.0, "tonic": 7, "kconf": 1.0,
           "chroma": np.full(12, 1 / 12, dtype=np.float32), "roles": set()}
    scale = [60, 62, 64, 65, 67, 69, 71, 72, 64, 60]    # no key signature
    path = write_mid(tmp_path / "e.mid", _track(*[_note(p) for p in scale]))

    applied = midi.apply_midi_context(ctx, midi.load_midi(path))

    assert "tonic" not in applied and ctx["tonic"] == 7


def test_a_stated_bpm_beats_everything_inferred(client):
    """The field a plugin uses: it read the transport, so it gets the last word."""
    c, conn, root = client

    body = c.post("/session/analyze", json={
        "context_paths": [str(root / "0.wav")], "bpm": 174, "distance": 50}).json()

    assert body["context"]["bpm"] == 174.0
    assert "bpm" in body["session_context"]


def test_no_context_at_all_is_a_400(client):
    c, conn, root = client
    res = c.post("/session/analyze", json={"context_ids": [], "distance": 50})
    assert res.status_code == 400


def test_session_midi_reports_the_statements(client, tmp_path):
    c, conn, root = client
    path = write_mid(tmp_path / "s.mid",
                     _track(_tempo(174), _keysig(1, True), _note(64)))

    body = c.post("/session/midi", json={"path": path}).json()

    assert body["bpm"] == pytest.approx(174, abs=0.01)
    assert body["key"] == "E minor"
    assert body["key_source"] == "stated"
