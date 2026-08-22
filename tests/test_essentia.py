"""Essentia integration: a second opinion on key, and signals librosa has none of.

Essentia has no native Windows build path at all -- its own docs say Windows
requires cross-compiling from Linux/macOS. So the runner picks a branch per
machine: native where the module imports (macOS, Linux), the official Docker
image where it does not (Windows). Both branches run identical code, so results
do not depend on who ran them.
"""
import sys
from pathlib import Path

import pytest

from goldigger import essentia_runner as er


# ---------------------------------------------------------------- key mapping

@pytest.mark.parametrize("name,pc", [("C", 0), ("C#", 1), ("Db", 1), ("A", 9),
                                     ("Bb", 10), ("B", 11), ("F#", 6), ("Gb", 6)])
def test_pitch_names_map_to_pitch_classes(name, pc):
    """Essentia spells keys with either accidental; both must land on one class."""
    assert er.pitch_to_pc(name) == pc


def test_unparseable_key_is_none_not_zero():
    """Returning 0 here would silently claim every unreadable key is C."""
    assert er.pitch_to_pc("") is None
    assert er.pitch_to_pc(None) is None
    assert er.pitch_to_pc("H") is None


# ---------------------------------------------------------------- cross-tool

def test_essentia_key_confidence_is_gated_by_librosas_tonalness():
    """Essentia computes no tonalness of its own, so both tools share one gate.

    Otherwise a hi-hat gets a confident key from Essentia and an unconfident one
    from librosa, and the disagreement looks like a tool bug rather than what it
    is -- material with no key at all.
    """
    assert er.gated_confidence(0.8, 0.9) == pytest.approx(0.72)
    assert er.gated_confidence(0.8, 0.02) < 0.02
    assert er.gated_confidence(None, 0.9) is None
    assert er.gated_confidence(0.8, None) is None


@pytest.mark.parametrize("e_key,e_scale,pc,is_major,expected", [
    ("C", "major", 0, 1, True),
    ("C", "minor", 0, 1, False),      # same tonic, different mode
    ("A", "minor", 9, 0, True),
    ("G", "major", 0, 1, False),
])
def test_key_agreement_compares_tonic_and_mode(e_key, e_scale, pc, is_major, expected):
    assert er.key_agreement(e_key, e_scale, pc, is_major) is expected


def test_key_agreement_is_none_when_either_side_is_unknown():
    """Unknown is not disagreement -- it is absence of evidence."""
    assert er.key_agreement(None, "major", 0, 1) is None
    assert er.key_agreement("C", "major", None, 1) is None
    assert er.key_agreement("C", "major", -1, 1) is None


# ---------------------------------------------------------------- runner

def test_docker_invocation_is_an_argument_list_never_a_shell_string():
    """The Windows gotcha this design exists to avoid.

    Invoking docker through a shell string on Git Bash rewrites Unix-style
    absolute paths: "/analysis/extract.py" silently became
    "C:/Program Files/Git/analysis/extract.py". A list goes straight to the
    Windows process-creation API and never reaches Git Bash's argv rewriting,
    so no MSYS_NO_PATHCONV workaround is needed -- or wanted.
    """
    argv = er.docker_argv(Path("/lib/sounds"), Path("/out/essentia.json"),
                          Path("/repo/goldigger"))
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)
    assert argv[:3] == ["docker", "run", "--rm"]
    assert er.DOCKER_IMAGE in argv
    assert "/in/../" not in " ".join(argv)


def test_docker_mounts_the_library_read_only():
    """An ingest must never be able to write into the user's sample library."""
    argv = er.docker_argv(Path("/lib/sounds"), Path("/out/e.json"), Path("/repo/goldigger"))
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert any(m.endswith(":/in:ro") for m in mounts), mounts
    assert any(m.endswith(":/analysis:ro") for m in mounts), mounts
    assert any(m.endswith(":/out") for m in mounts), mounts


def test_docker_writes_the_output_by_name_inside_the_mounted_folder():
    argv = er.docker_argv(Path("/lib"), Path("/out/essentia.json"), Path("/repo/goldigger"))
    assert "/out/essentia.json" in argv


def test_runner_uses_the_native_branch_when_essentia_imports(monkeypatch, tmp_path):
    """On macOS this must never reach for Docker."""
    calls = []
    monkeypatch.setattr(er, "essentia_available_natively", lambda: True)
    monkeypatch.setattr(er.subprocess, "run", lambda argv, **kw: calls.append(argv))
    er.run(tmp_path, tmp_path / "out.json")
    assert len(calls) == 1
    assert "docker" not in calls[0], calls[0]
    assert calls[0][0] == sys.executable


def test_runner_falls_back_to_docker_when_essentia_is_missing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(er, "essentia_available_natively", lambda: False)
    monkeypatch.setattr(er.subprocess, "run", lambda argv, **kw: calls.append(argv))
    er.run(tmp_path, tmp_path / "out.json")
    assert len(calls) == 1
    assert calls[0][0] == "docker"


# ---------------------------------------------------------------- extractor

def test_extractor_covers_the_same_extensions_the_ingest_walks():
    """The extractor runs in a container that cannot import config, so its
    extension list is a copy -- this is the guard that it stays a faithful one.
    """
    from goldigger import config, essentia_extract
    assert set(essentia_extract.AUDIO_EXTS) == set(config.AUDIO_EXTS)


def test_extractor_imports_without_essentia_installed():
    """It must be importable on Windows for the guard above to be runnable."""
    from goldigger import essentia_extract
    assert callable(essentia_extract.stability)


def test_extractor_stability_matches_the_librosa_side():
    """Same formula on both sides, or the two tools' confidences are not
    comparable. Duplicated because the container has no goldigger package."""
    from goldigger import essentia_extract, features
    for mean, std in [(100.0, 10.0), (1.0, 3.0), (0.5, 0.0)]:
        assert essentia_extract.stability(mean, std) == pytest.approx(
            features.stability(mean, std))


# ---------------------------------------------------------------- merge

def test_merge_gates_essentia_key_by_the_files_librosa_tonalness(tmp_path):
    from goldigger import db
    conn = db.connect(tmp_path / "m.db")
    db.init(conn)
    conn.execute(
        "INSERT INTO chunks (chunk_id, path, file_hash, chunk_index, t_start,"
        " t_end, tonic_pc, is_major, key_confidence, tonalness)"
        " VALUES ('h1:0', ?, 'h1', 0, 0.0, 4.0, 0, 1, 0.5, 0.04)",
        (str(tmp_path / "hat.wav"),))
    conn.commit()

    n = er.merge(conn, [{"rel_path": "hat.wav", "key_key": "C", "key_scale": "major",
                         "key_strength_raw": 0.9, "bpm": 120.0}], tmp_path)

    assert n == 1
    row = conn.execute("SELECT * FROM essentia WHERE file_hash='h1'").fetchone()
    assert row["key_strength"] == pytest.approx(0.9)
    # 0.9 raw strength, but the file is 4% harmonic -- so it is not a key
    assert row["key_confidence"] == pytest.approx(0.036)
    assert row["key_agreement"] == 1, "both tools said C major"


def test_merge_skips_files_that_were_never_ingested(tmp_path):
    from goldigger import db
    conn = db.connect(tmp_path / "m2.db")
    db.init(conn)
    assert er.merge(conn, [{"rel_path": "ghost.wav", "key_key": "C"}], tmp_path) == 0
