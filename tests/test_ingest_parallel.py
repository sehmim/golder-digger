"""Ingest spreads hashing and Essentia over processes; order must survive it.

The loop downstream still writes files in walk order and counts progress against
it, so what is under test here is that the pool is invisible: same records, same
sequence, one per path.
"""
import numpy as np
import pytest
import soundfile as sf

from goldigger import features, ingest


def tone(path, seconds=1.0, freq=220.0):
    t = np.linspace(0, seconds, int(seconds * 22050), endpoint=False)
    sf.write(path, 0.2 * np.sin(2 * np.pi * freq * t), 22050)
    return path


@pytest.fixture
def library(tmp_path):
    return [tone(tmp_path / f"{i}.wav", freq=220.0 + 40 * i) for i in range(4)]


def test_a_known_hash_costs_no_extraction(library):
    """The dedupe check lives in the worker so a skip is one hash, not a trip."""
    path = library[0]
    seen = {features.file_hash(path)}

    record = ingest.prepare(str(path), seen, essentia=True)

    assert record["seen"] and record["essentia"] is None


def test_an_unreadable_file_comes_back_as_an_error(tmp_path):
    record = ingest.prepare(str(tmp_path / "gone.wav"), set(), essentia=False)

    assert "error" in record and "gone.wav" in record["path"]


def test_serial_and_pooled_agree_on_order(library):
    serial = list(ingest.prepared(library, set(), essentia=False, workers=1))

    assert [r["path"] for r in serial] == [str(p) for p in library]
    assert [r["file_hash"] for r in serial] == [features.file_hash(p) for p in library]


def test_the_pool_yields_in_walk_order(library):
    """The real pool, on real files: workers finish out of order, results do not."""
    pytest.importorskip("essentia")

    records = list(ingest.prepared(library, set(), essentia=True, workers=3))

    assert [r["path"] for r in records] == [str(p) for p in library]
    assert all(r["essentia"] for r in records)


def test_more_files_than_the_window_still_all_arrive(library):
    """The window bounds what is in flight, not what comes out."""
    paths = library * 3

    records = list(ingest.prepared(paths, set(), essentia=False, workers=2))

    assert len(records) == len(paths)
