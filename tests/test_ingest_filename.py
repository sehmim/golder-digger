"""Ingest has to actually record what the filename claimed, and say so.

Beat tracking returns nothing at all on short loops -- most of a sample library
-- so a tempo printed in the filename is often the only one there is. Storing it
without recording where it came from would make a parsed label indistinguishable
from a measurement.
"""
import numpy as np
import pytest

from goldigger import db, ingest


@pytest.fixture
def ingested(tmp_path):
    import soundfile as sf
    root = tmp_path / "audio"
    root.mkdir()
    rng = np.random.default_rng(0)
    for name in ("Loop_126bpm_Cm.wav", "clip_nameless.wav", "Stab_130bpm_G#.wav"):
        sf.write(root / name, rng.standard_normal(22050 * 3) * 0.05, 22050)

    conn = db.connect(tmp_path / "t.db")
    db.init(conn)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    return conn


def row(conn, like):
    return conn.execute(
        "SELECT * FROM chunks WHERE path LIKE ?", (f"%{like}%",)).fetchone()


def test_a_stated_tempo_is_used_and_attributed(ingested):
    """Mock tempo confidence tops out below an explicitly written "126bpm",
    so the filename wins here deterministically."""
    r = row(ingested, "126bpm")
    assert r["bpm"] == 126.0
    assert r["bpm_source"] == "filename"


def test_a_silent_filename_leaves_the_audio_estimate_alone(ingested):
    r = row(ingested, "nameless")
    assert r["bpm_source"] == "audio"
    assert r["bpm"] is not None


def test_a_stated_key_is_attributed_too(ingested):
    r = row(ingested, "Loop_126bpm")
    assert r["key_source"] in ("filename", "audio")
    if r["key_source"] == "filename":
        assert (r["tonic_pc"], r["is_major"]) == (0, 0)   # Cm


def test_a_root_only_name_takes_the_root_and_leaves_the_mode(ingested):
    """"G#" names a root and says nothing about major or minor. Taking the root
    while keeping the estimate's mode beats discarding either one whole."""
    r = row(ingested, "Stab")
    if r["key_source"] == "filename":
        assert r["tonic_pc"] == 8
        assert r["is_major"] in (0, 1)      # kept from the estimate, not invented
