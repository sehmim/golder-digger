"""Parser and resolver for Live sets.

No .als on this machine references a sample, so the sample-ref shapes are
exercised against fixtures built from the FileRef layout Live 12.2 actually
writes (verified against a real set) plus the legacy Live 9/10 nesting.
"""
import gzip
import sqlite3

import pytest

from goldigger import ableton, db

LIVE12 = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12402" Creator="Ableton Live 12.2">
 <LiveSet>
  <InKey Value="{in_key}" />
  <ScaleInformation><Root Value="{root}" /><Name Value="{scale}" /></ScaleInformation>
  <MasterTrack><DeviceChain><Mixer>
    <Tempo><LomId Value="0" /><Manual Value="{tempo}" /></Tempo>
  </Mixer></DeviceChain></MasterTrack>
  {samples}
 </LiveSet>
</Ableton>
"""

SAMPLE_12 = """
  <SampleRef><FileRef>
    <RelativePathType Value="1" />
    <RelativePath Value="{rel}" />
    <Path Value="{abs}" />
    <Type Value="1" />
    <LivePackName Value="" />
  </FileRef></SampleRef>
"""

SAMPLE_LEGACY = """
  <SampleRef><FileRef>
    <RelativePathType Value="3" />
    <RelativePath>
      <RelativePathElement Id="1" Dir="Samples" />
      <RelativePathElement Id="2" Dir="Imported" />
    </RelativePath>
    <Name Value="{name}" />
  </FileRef></SampleRef>
"""


def write_als(tmp_path, samples="", tempo=128, root=7, scale=1, in_key="true"):
    p = tmp_path / "Set.als"
    xml = LIVE12.format(samples=samples, tempo=tempo, root=root,
                        scale=scale, in_key=in_key)
    with gzip.open(p, "wb") as f:
        f.write(xml.encode())
    return p


def test_parses_tempo_and_key(tmp_path):
    als = ableton.load_als(write_als(tmp_path))
    assert als["tempo"] == 128.0
    assert als["scale_root"] == 7          # G
    assert als["is_major"] is False        # scale index 1 == minor
    assert als["in_key"] is True
    assert als["creator"] == "Ableton Live 12.2"


def test_unknown_scale_index_does_not_claim_a_mode(tmp_path):
    """Only indices 0/1 are trusted; anything else must not guess major/minor."""
    als = ableton.load_als(write_als(tmp_path, scale=9))
    assert als["scale_index"] == 9
    assert als["is_major"] is None


def test_live12_flat_paths(tmp_path):
    wav = tmp_path / "Samples" / "kick.wav"
    wav.parent.mkdir()
    wav.write_bytes(b"RIFF")
    als = ableton.load_als(write_als(
        tmp_path, SAMPLE_12.format(rel="Samples/kick.wav", abs=str(wav))))
    cands = [str(c) for c in als["samples"][0]["candidates"]]
    assert str(wav) in cands


def test_stale_absolute_path_still_yields_a_relative_candidate(tmp_path):
    """A set moved between machines keeps the old machine's absolute path."""
    als = ableton.load_als(write_als(
        tmp_path, SAMPLE_12.format(rel="Samples/kick.wav",
                                   abs="/Users/someone-else/kick.wav")))
    cands = [str(c) for c in als["samples"][0]["candidates"]]
    assert "/Users/someone-else/kick.wav" in cands
    assert str(tmp_path / "Samples" / "kick.wav") in cands


def test_legacy_nested_path_elements(tmp_path):
    als = ableton.load_als(write_als(tmp_path, SAMPLE_LEGACY.format(name="snare.wav")))
    cands = [str(c) for c in als["samples"][0]["candidates"]]
    assert str(tmp_path / "Samples" / "Imported" / "snare.wav") in cands


def test_duplicate_sample_refs_collapse(tmp_path):
    one = SAMPLE_12.format(rel="Samples/kick.wav", abs="/x/kick.wav")
    als = ableton.load_als(write_als(tmp_path, one + one))
    assert len(als["samples"]) == 1


# ---------------------------------------------------------------- resolve

@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init(c)
    return c


def add_chunk(conn, chunk_id, path, file_hash, idx=0):
    conn.execute(
        "INSERT INTO chunks (chunk_id, path, file_hash, chunk_index, t_start, t_end)"
        " VALUES (?,?,?,?,0,1)", (chunk_id, str(path), file_hash, idx))
    conn.commit()


def test_resolves_by_content_hash_after_a_rename(tmp_path, conn):
    """The file moved since ingest; the hash still identifies it."""
    from goldigger import features
    wav = tmp_path / "Samples" / "kick.wav"
    wav.parent.mkdir()
    wav.write_bytes(b"not really audio, but hashable")
    add_chunk(conn, "abc:0", "/old/location/renamed.wav", features.file_hash(wav))

    als = ableton.load_als(write_als(
        tmp_path, SAMPLE_12.format(rel="Samples/kick.wav", abs=str(wav))))
    res = ableton.resolve(conn, als)
    assert res["context_ids"] == ["abc:0"]
    assert res["matched"][0]["method"] == "hash"


def test_missing_file_falls_back_to_path_then_basename(tmp_path, conn):
    add_chunk(conn, "def:0", "/library/pad.wav", "hash-not-checked")
    als = ableton.load_als(write_als(
        tmp_path, SAMPLE_12.format(rel="Samples/pad.wav", abs="/library/pad.wav")))
    res = ableton.resolve(conn, als)
    assert res["matched"][0]["method"] == "path"

    als2 = ableton.load_als(write_als(
        tmp_path, SAMPLE_LEGACY.format(name="pad.wav")))
    res2 = ableton.resolve(conn, als2)
    assert res2["matched"][0]["method"] == "basename"


def test_ambiguous_basename_is_refused_not_guessed(tmp_path, conn):
    add_chunk(conn, "a:0", "/packA/pad.wav", "h1")
    add_chunk(conn, "b:0", "/packB/pad.wav", "h2")
    als = ableton.load_als(write_als(tmp_path, SAMPLE_LEGACY.format(name="pad.wav")))
    res = ableton.resolve(conn, als)
    assert not res["context_ids"]
    assert "ambiguous" in res["unmatched"][0]["reason"]


def test_all_chunks_of_a_multi_chunk_file_join_the_context(tmp_path, conn):
    add_chunk(conn, "m:0", "/library/loop.wav", "h", 0)
    add_chunk(conn, "m:1", "/library/loop.wav", "h", 1)
    als = ableton.load_als(write_als(
        tmp_path, SAMPLE_12.format(rel="x.wav", abs="/library/loop.wav")))
    assert ableton.resolve(conn, als)["context_ids"] == ["m:0", "m:1"]


# ---------------------------------------------------------------- session context

def test_session_context_overrides_inferred_tempo_and_key(tmp_path):
    als = ableton.load_als(write_als(tmp_path, tempo=90, root=2))
    ctx = {"bpm": 174.0, "tonic": 11, "kconf": 0.004}
    applied = ableton.apply_session_context(ctx, als)
    assert applied == ["bpm", "tonic"]
    assert ctx["bpm"] == 90.0 and ctx["tonic"] == 2 and ctx["kconf"] == 1.0


def test_key_is_not_trusted_when_the_set_is_not_key_aware(tmp_path):
    """Root=0/Name=0 is also what an untouched set reports -- do not read it as C major."""
    als = ableton.load_als(write_als(tmp_path, root=0, scale=0, in_key="false"))
    ctx = {"bpm": 174.0, "tonic": 11, "kconf": 0.004}
    assert ableton.apply_session_context(ctx, als) == ["bpm"]
    assert ctx["tonic"] == 11 and ctx["kconf"] == 0.004


# ---------------------------------------------------------------- tempo location

MAIN_TRACK = """
  <MainTrack><DeviceChain><Mixer>
    <Tempo><Manual Value="{tempo}" /></Tempo>
  </Mixer></DeviceChain></MainTrack>
"""


def test_tempo_comes_from_the_main_track_not_document_order(tmp_path):
    """Live 12 renamed MasterTrack->MainTrack, and scenes carry a valueless <Tempo>."""
    xml = """<?xml version="1.0"?>
    <Ableton Creator="Ableton Live 12.1.1"><LiveSet>
      <Scenes><Scene><Tempo><LomId Value="0" /></Tempo></Scene></Scenes>
      <Tracks><AudioTrack><Tempo><Manual Value="999" /></Tempo></AudioTrack></Tracks>
      %s
    </LiveSet></Ableton>""" % MAIN_TRACK.format(tempo=214)
    p = tmp_path / "Set.als"
    with gzip.open(p, "wb") as f:
        f.write(xml.encode())
    assert ableton.load_als(p)["tempo"] == 214.0


def test_clip_als_with_no_track_still_reports_a_tempo(tmp_path):
    """Preset/clip .als files have no MainTrack; a scene's valueless Tempo must be skipped."""
    xml = """<?xml version="1.0"?>
    <Ableton Creator="Ableton Live 12.2"><LiveSet>
      <Scenes><Scene><Tempo><LomId Value="0" /></Tempo></Scene></Scenes>
      <Tempo><Manual Value="128" /></Tempo>
    </LiveSet></Ableton>"""
    p = tmp_path / "Clip.als"
    with gzip.open(p, "wb") as f:
        f.write(xml.encode())
    assert ableton.load_als(p)["tempo"] == 128.0


# ---------------------------------------------------------------- format variants

LIVE10 = """<?xml version="1.0"?>
<Ableton Creator="Ableton Live 10.1.35"><LiveSet>
  <InKey Value="true" />
  <ScaleInformation><RootNote Value="2" /><Name Value="{name}" /></ScaleInformation>
  <MainTrack><DeviceChain><Mixer><Tempo><Manual Value="120" /></Tempo></Mixer></DeviceChain></MainTrack>
</LiveSet></Ableton>"""


def _gz(tmp_path, xml, name="Set.als"):
    p = tmp_path / name
    with gzip.open(p, "wb") as f:
        f.write(xml.encode())
    return p


def test_live10_names_the_scale_as_a_string(tmp_path):
    """Live 10 writes <RootNote> and a scale *name*; Live 12 writes <Root> and an index."""
    als = ableton.load_als(_gz(tmp_path, LIVE10.format(name="Major")))
    assert als["scale_root"] == 2 and als["is_major"] is True
    assert als["scale_name"] == "Major" and als["scale_index"] is None


def test_live10_minor(tmp_path):
    assert ableton.load_als(_gz(tmp_path, LIVE10.format(name="Minor")))["is_major"] is False


def test_live10_exotic_scale_keeps_its_name_and_claims_no_mode(tmp_path):
    als = ableton.load_als(_gz(tmp_path, LIVE10.format(name="Minor Blues")))
    assert als["scale_name"] == "Minor Blues"
    assert als["is_major"] is None


def test_empty_set_raises_unreadable_not_parseerror(tmp_path):
    """315 of 752 sets in a real archive are zero-byte files."""
    p = tmp_path / "Empty.als"
    with gzip.open(p, "wb") as f:
        f.write(b"")
    with pytest.raises(ableton.UnreadableSet, match="empty"):
        ableton.load_als(p)


def test_non_gzip_file_raises_unreadable(tmp_path):
    p = tmp_path / "Plain.als"
    p.write_bytes(b"this is not gzip at all")
    with pytest.raises(ableton.UnreadableSet):
        ableton.load_als(p)
