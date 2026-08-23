"""Ableton consolidates project audio into AIFC files stamped with a
proprietary 'able' compression type; libsndfile and CoreAudio both refuse
them, but the SSND payload is plain big-endian PCM. load_audio must rescue
exactly those files -- and keep refusing anything it cannot vouch for.
"""
import struct

import numpy as np
import pytest
import soundfile as sf

from goldigger import config
from goldigger.features import load_audio

RATE = 44100


def _extended80(rate: int) -> bytes:
    """The 80-bit extended float AIFF uses for its sample rate."""
    n = rate.bit_length()
    return struct.pack(">HQ", 16383 + n - 1, rate << (64 - n))


def _chunk(cid: bytes, body: bytes) -> bytes:
    pad = b"\x00" if len(body) & 1 else b""
    return cid + struct.pack(">I", len(body)) + body + pad


def _pack24(x: np.ndarray) -> bytes:
    u = (np.clip(x, -1.0, 1.0) * (2**23 - 1)).astype(np.int32) & 0xFFFFFF
    b = np.empty((len(u), 3), np.uint8)
    b[:, 0] = (u >> 16) & 0xFF
    b[:, 1] = (u >> 8) & 0xFF
    b[:, 2] = u & 0xFF
    return b.tobytes()


def _able_aifc(left, right, comp=b"able", drop_ssnd_bytes=0) -> bytes:
    """The chunk layout the real files have: FVER, a vendor 'able' blob,
    COMM stamped with `comp`, interleaved 24-bit PCM in SSND."""
    frames = len(left)
    inter = np.empty(frames * 2)
    inter[0::2] = left
    inter[1::2] = right
    pcm = _pack24(inter)
    if drop_ssnd_bytes:
        pcm = pcm[:-drop_ssnd_bytes]
    comm = struct.pack(">hIh", 2, frames, 24) + _extended80(RATE) + comp + b"\x00"
    body = (b"AIFC"
            + _chunk(b"FVER", struct.pack(">I", 0xA2805140))
            + _chunk(b"able", b"\x00" * 340)
            + _chunk(b"COMM", comm)
            + _chunk(b"SSND", struct.pack(">II", 0, 0) + pcm))
    return b"FORM" + struct.pack(">I", len(body)) + body


def _sine(freq=440.0, amp=1.0, dur=0.5):
    t = np.arange(int(RATE * dur)) / RATE
    return amp * np.sin(2 * np.pi * freq * t)


def test_fixture_reproduces_the_refusal(tmp_path):
    # If libsndfile ever learns to read these, the fallback stops being the
    # code under test and this file should be retired.
    p = tmp_path / "consolidated.aif"
    p.write_bytes(_able_aifc(_sine(), _sine(amp=0.5)))
    with pytest.raises(Exception):
        sf.read(str(p))


def test_able_pcm_is_rescued(tmp_path):
    p = tmp_path / "consolidated.aif"
    p.write_bytes(_able_aifc(_sine(amp=1.0), _sine(amp=0.5)))
    y, sr = load_audio(p)
    assert sr == config.SR
    assert abs(len(y) - 0.5 * config.SR) <= 2

    spectrum = np.abs(np.fft.rfft(y))
    freq = np.fft.rfftfreq(len(y), 1 / sr)[np.argmax(spectrum)]
    assert abs(freq - 440.0) < 5

    # mono mix of amp 1.0 and 0.5 channels; a sign-extension bug or a wrong
    # deinterleave both land far from 0.75
    assert abs(np.max(np.abs(y)) - 0.75) < 0.03


def test_truncated_ssnd_reraises(tmp_path):
    # SSND shorter than frames*channels*bytes: the PCM claim fails to verify,
    # so the original decoder error must surface, not a partial decode.
    p = tmp_path / "truncated.aif"
    p.write_bytes(_able_aifc(_sine(), _sine(), drop_ssnd_bytes=6))
    with pytest.raises(sf.LibsndfileError):
        load_audio(p)


def test_foreign_codec_reraises(tmp_path):
    # An AIFC whose codec libsndfile genuinely lacks (MACE here) keeps its
    # real error: the rescue only vouches for the tag it has verified is a lie.
    p = tmp_path / "mace.aif"
    p.write_bytes(_able_aifc(_sine(), _sine(), comp=b"MAC3"))
    with pytest.raises(sf.LibsndfileError):
        load_audio(p)
