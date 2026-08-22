"""The filename parser is an evaluation instrument, so a wrong label is worse
than a missing one. These tests pin the refusals as much as the parses."""
import sys
sys.path.insert(0, ".")

from scripts.filename_truth import bpm_from_name, key_from_name, truth_for


def test_roland_loop_naming():
    assert truth_for("EP1_Loop01_76_Cm.wav") == {"bpm": 76.0, "tonic_pc": 0, "is_major": False}


def test_accidentals_sharp_and_flat():
    assert key_from_name("Organ_Loop2_75_G#.wav") == (8, None)
    assert key_from_name("VE_Loop3_75_Bbm.wav") == (10, False)


def test_explicit_bpm_token_wins_over_other_numbers():
    """DKT1_15_126bpm_ Synth1_E has 1, 15, 126 and 1 in it -- only 126 is tempo."""
    assert bpm_from_name("DKT1_15_126bpm_ Synth1_E.wav") == 126.0
    assert bpm_from_name("11 SYNTH Fm 125bpm.wav") == 125.0


def test_bare_numbers_must_be_unambiguous():
    assert bpm_from_name("Clav_Loop6_86_F.wav") == 86.0        # one plausible value
    assert bpm_from_name("Kit_90_120_beat.wav") is None        # two -- refuse


def test_implausible_tempo_is_not_a_tempo():
    assert bpm_from_name("Sample_2000_long.wav") is None
    assert bpm_from_name("take_12.wav") is None                # below BPM_MIN


def test_bit_depth_does_not_become_a_key():
    """'24Bit Samples' would otherwise read as B-flat."""
    assert key_from_name("24Bit Samples EP1_Loop.wav") is None


def test_percussive_files_yield_no_key():
    assert truth_for("wa-triaz-claps-room-md_twisty.wav") == {
        "bpm": None, "tonic_pc": None, "is_major": None}


def test_chord_names_parse_to_root_and_quality():
    assert key_from_name("Organ_Chord1_Bm9.wav") == (11, False)


def test_conflicting_keys_are_refused():
    assert key_from_name("Cm_to_Gm_transition.wav") is None
