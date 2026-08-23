"""The filename read used at ingest time.

Distinct from scripts/filename_truth, which is a measuring instrument: this one
feeds the corpus, so what it reports has to carry how sure it is. A tempo spelled
"126bpm" is a statement; a bare "93" sitting among other numbers is an inference.
"""
import sys

sys.path.insert(0, ".")

from goldigger import config, filename


def test_explicit_bpm_token_is_more_certain_than_a_bare_number():
    explicit, c_explicit = filename.parse_bpm("Loop_126bpm.wav")
    bare, c_bare = filename.parse_bpm("Clav_Loop9_93_Cm.wav")
    assert (explicit, bare) == (126.0, 93.0)
    assert c_explicit > c_bare > 0.0


def test_unit_may_precede_the_number():
    """'BPM 120 Drums' is as explicit as '120bpm' and must score the same."""
    assert filename.parse_bpm("BPM120_Drums.wav") == (120.0, config.FILENAME_BPM_EXPLICIT)
    assert filename.parse_bpm("Kit bpm 095 loop.wav") == (95.0, config.FILENAME_BPM_EXPLICIT)


def test_an_explicit_unit_outranks_competing_bare_numbers():
    """Bare numbers that would otherwise be ambiguous stop mattering once one
    of them names itself: 'DKT1_02_126bpm_Synth2' has 1, 2 and 126 in it."""
    assert filename.parse_bpm("DKT1_02_126bpm_ Synth2_A.wav") == (
        126.0, config.FILENAME_BPM_EXPLICIT)


def test_a_tempo_at_the_end_of_the_name_survives_the_extension():
    """"Loop_110.wav" puts the tempo hard against the dot. Reading the whole
    path instead of the stem let the extension's '.' break the number boundary,
    and the tempo went missing on exactly the files most likely to state one."""
    assert filename.parse_bpm("Perc_Drum_Loop_7_110.wav") == (
        110.0, config.FILENAME_BPM_BARE)
    assert filename.parse_bpm("/a/b/Kit_128.aiff") == (128.0, config.FILENAME_BPM_BARE)


def test_ambiguous_or_implausible_numbers_are_refused():
    assert filename.parse_bpm("Kit_90_120_beat.wav") == (None, 0.0)
    assert filename.parse_bpm("Sample_2000_long.wav") == (None, 0.0)
    assert filename.parse_bpm("take_12.wav") == (None, 0.0)


# ------------------------------------------------------------------ key

def test_accidentals_may_be_spelled_out():
    """Libraries that cannot put '#' in a path write it as a word instead."""
    assert filename.parse_key("Bass_Fsharp_min_128.wav") == (
        6, False, config.FILENAME_KEY_QUALIFIED)
    assert filename.parse_key("Pad_Eflat_major.wav") == (
        3, True, config.FILENAME_KEY_QUALIFIED)


def test_resolve_prefers_whichever_source_is_more_confident():
    assert filename.resolve(174.0, 0.9, 87.0, 0.6) == (174.0, "audio", 0.9)
    assert filename.resolve(214.0, 0.36, 110.0, 0.95) == (110.0, "filename", 0.95)


def test_resolve_falls_back_when_a_side_has_nothing():
    """Beat tracking returns no tempo at all on short loops, which is most of a
    sample library -- the filename is then the only source there is."""
    assert filename.resolve(None, 0.0, 93.0, 0.6) == (93.0, "filename", 0.6)
    assert filename.resolve(120.0, 0.4, None, 0.0) == (120.0, "audio", 0.4)
    assert filename.resolve(None, 0.0, None, 0.0) == (None, None, 0.0)


def test_vocabulary_counts_files_not_occurrences():
    """A word repeated inside one filename is still one file's worth of evidence.

    The reference implementation counted regex matches instead, across three
    overlapping patterns, so a single occurrence reported as several and every
    frequency was inflated by an arbitrary factor.
    """
    vocab = filename.discover_vocabulary(
        ["Dusty_Dusty_Kick.wav", "Dusty_Snare.wav"], min_files=1)
    assert vocab["dusty"] == 2


def test_vocabulary_keeps_only_what_recurs():
    """A word in one file is a catalogue number; a word in many is a facet."""
    paths = [f"CR78_{i:03d}_Vinyl_Kick.wav" for i in range(4)] + ["ZZ9_Oddity.wav"]
    vocab = filename.discover_vocabulary(paths, min_files=3)
    assert set(vocab) == {"cr", "vinyl", "kick"}
    assert "oddity" not in vocab


def test_vocabulary_drops_bare_numbers_but_keeps_808():
    vocab = filename.discover_vocabulary(
        ["808_Sub_01.wav", "808_Sub_02.wav"], min_files=2)
    assert set(vocab) == {"808", "sub"}


def test_a_named_quality_is_more_certain_than_a_bare_letter():
    """'Cm' states the mode. A lone 'A' only states a root, and could as easily
    be a take letter -- worth recording, worth trusting less."""
    pc_bare, mode_bare, c_bare = filename.parse_key("DKT1_02_126bpm_ Synth2_A.wav")
    pc_qual, mode_qual, c_qual = filename.parse_key("Clav_Loop9_93_Cm.wav")
    assert (pc_bare, mode_bare) == (9, None)
    assert (pc_qual, mode_qual) == (0, False)
    assert c_qual > c_bare > 0.0
