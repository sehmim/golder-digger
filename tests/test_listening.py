"""The listening test is the instrument that judges the product, so its own
integrity is what these tests are about.

The failure that would matter most is not a crash -- it is a harness that quietly
produces a flattering answer. A rater who can see which arm made a candidate, or
who meets every Gold Digger trial before every random one, generates data that
looks like evidence and is not. Each test below pins one way that could happen.
"""
import json

import numpy as np
import pytest

from goldigger import config, db, listening, scoring


class FakeCorpus:
    """60 chunks over 6 files, spread through CLAP space."""

    def __init__(self, n=60):
        rng = np.random.default_rng(3)
        self.rows = [{"chunk_id": f"c{i}", "path": f"/f{i // 10}.wav", "is_major": 1}
                     for i in range(n)]
        self.ids = [r["chunk_id"] for r in self.rows]
        self.index = {c: i for i, c in enumerate(self.ids)}
        v = rng.standard_normal((n, config.CLAP_DIM))
        self.clap = (v / np.linalg.norm(v, axis=1, keepdims=True)).astype(np.float32)
        ch = rng.random((n, 12)).astype(np.float32)
        self.chroma = ch / ch.sum(axis=1, keepdims=True)
        self.bpm = np.full(n, 120.0, dtype=np.float32)
        self.tonic = np.zeros(n, dtype=np.int16)
        self.kconf = np.full(n, 0.5, dtype=np.float32)
        self.roles = ["drums" if i % 3 else "bass" for i in range(n)]
        self.hashes = [f"h{i // 10}" for i in range(n)]

    def __len__(self):
        return len(self.rows)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init(c)
    return c


@pytest.fixture
def corpus():
    return FakeCorpus()


@pytest.fixture
def batch(conn, corpus):
    return listening.generate(conn, corpus, ["c0"], batch="b1", session_bpm=120.0)


# ---------------------------------------------------------------- blindness

def test_the_payload_cannot_unblind_the_rater(conn, corpus, batch):
    """The whole experiment rests on this one."""
    row = listening.next_trial(conn, "alice")
    payload = listening.trial_payload(row)
    blob = json.dumps(payload)
    assert "strategy" not in payload and "distance" not in payload
    for arm in listening.ARMS:
        assert arm not in blob, f"{arm} leaked into the payload"


def test_the_payload_does_not_leak_the_filename(conn, corpus, batch):
    """A name like `..._Cm_90bpm.wav` invites reasoning instead of listening."""
    payload = listening.trial_payload(listening.next_trial(conn, "alice"))
    assert "path" not in payload
    assert ".wav" not in json.dumps(payload)


def test_the_arm_is_revealed_only_after_a_rating_is_stored(conn, corpus, batch):
    row = listening.next_trial(conn, "alice")
    scores = {s: 4 for s in listening.SCALES}
    was = listening.record(conn, row["trial_id"], "alice", scores)
    assert was["strategy"] in listening.ARMS
    stored = conn.execute("SELECT COUNT(*) FROM ratings WHERE trial_id=?",
                          (row["trial_id"],)).fetchone()[0]
    assert stored == 1


# ---------------------------------------------------------------- balance

def test_baselines_share_the_blind_pool(conn, corpus, batch):
    """Rating only Gold Digger would produce a number with nothing to compare to."""
    arms = {r[0] for r in conn.execute("SELECT DISTINCT strategy FROM trials")}
    assert {"golddigger", "random", "nearest", "inverse"} <= arms


def test_the_dial_is_covered_across_its_range(conn, corpus, batch):
    ds = {r[0] for r in conn.execute(
        "SELECT DISTINCT distance FROM trials WHERE strategy='golddigger'")}
    assert ds == set(listening.DISTANCES)


def test_distance_blind_arms_are_not_repeated_per_position(conn, corpus, batch):
    """random and nearest ignore the dial; five identical trials waste a rater."""
    n = conn.execute("SELECT COUNT(*) FROM trials WHERE strategy='nearest'").fetchone()[0]
    assert n == listening.PER_CELL


def test_no_candidate_appears_twice_in_a_batch(conn, corpus, batch):
    rows = [r[0] for r in conn.execute("SELECT candidate FROM trials")]
    assert len(rows) == len(set(rows))


def test_no_candidate_shares_a_file_with_the_context(conn, corpus, batch):
    """Otherwise the test rates neighbouring bars of the clip already playing."""
    ctx_hash = corpus.hashes[corpus.index["c0"]]
    for (cand,) in conn.execute("SELECT candidate FROM trials"):
        assert corpus.hashes[corpus.index[cand]] != ctx_hash


# ---------------------------------------------------------------- ordering

def test_raters_meet_the_trials_in_different_orders(conn, corpus, batch):
    """Otherwise fatigue late in a session looks like an effect of the arm."""
    def order(rater):
        seen, out = set(), []
        while True:
            row = listening.next_trial(conn, rater)
            if row is None or row["trial_id"] in seen:
                break
            seen.add(row["trial_id"])
            out.append(row["trial_id"])
            listening.record(conn, row["trial_id"], rater, {s: 4 for s in listening.SCALES})
        return out

    assert order("alice") != order("bob")


def test_a_rater_is_never_shown_the_same_trial_twice(conn, corpus, batch):
    row = listening.next_trial(conn, "alice")
    listening.record(conn, row["trial_id"], "alice", {s: 4 for s in listening.SCALES})
    assert listening.next_trial(conn, "alice")["trial_id"] != row["trial_id"]


def test_progress_counts_only_this_raters_work(conn, corpus, batch):
    row = listening.next_trial(conn, "alice")
    listening.record(conn, row["trial_id"], "alice", {s: 4 for s in listening.SCALES})
    assert listening.progress(conn, "alice")["done"] == 1
    assert listening.progress(conn, "bob")["done"] == 0


def test_running_out_of_trials_is_not_an_error(conn, corpus, batch):
    while (row := listening.next_trial(conn, "alice")) is not None:
        listening.record(conn, row["trial_id"], "alice", {s: 4 for s in listening.SCALES})
    assert listening.next_trial(conn, "alice") is None


# ---------------------------------------------------------------- recording

def test_out_of_range_scores_are_refused_not_clamped(conn, corpus, batch):
    """A 9 on a 7-point scale means the client is wrong; saving 7 would hide it."""
    row = listening.next_trial(conn, "alice")
    with pytest.raises(ValueError, match="1-7"):
        listening.record(conn, row["trial_id"], "alice",
                         {**{s: 4 for s in listening.SCALES}, "obviousness": 9})


def test_a_skipped_scale_is_stored_as_missing(conn, corpus, batch):
    row = listening.next_trial(conn, "alice")
    listening.record(conn, row["trial_id"], "alice",
                     {**{s: 4 for s in listening.SCALES}, "inspiration": None})
    got = conn.execute("SELECT inspiration, obviousness FROM ratings WHERE trial_id=?",
                       (row["trial_id"],)).fetchone()
    assert got["inspiration"] is None and got["obviousness"] == 4


def test_rating_an_unknown_trial_raises(conn):
    with pytest.raises(KeyError):
        listening.record(conn, "nope", "alice", {s: 4 for s in listening.SCALES})


def test_a_rater_can_revise_a_rating(conn, corpus, batch):
    row = listening.next_trial(conn, "alice")
    listening.record(conn, row["trial_id"], "alice", {s: 2 for s in listening.SCALES})
    listening.record(conn, row["trial_id"], "alice", {s: 6 for s in listening.SCALES})
    rows = conn.execute("SELECT obviousness FROM ratings WHERE trial_id=? AND rater=?",
                        (row["trial_id"], "alice")).fetchall()
    assert len(rows) == 1 and rows[0]["obviousness"] == 6


def test_two_raters_rate_the_same_trial_independently(conn, corpus, batch):
    row = listening.next_trial(conn, "alice")
    listening.record(conn, row["trial_id"], "alice", {s: 2 for s in listening.SCALES})
    listening.record(conn, row["trial_id"], "bob", {s: 6 for s in listening.SCALES})
    assert conn.execute("SELECT COUNT(*) FROM ratings WHERE trial_id=?",
                        (row["trial_id"],)).fetchone()[0] == 2


# ---------------------------------------------------------------- audio wiring

def test_the_mix_carries_the_session_tempo_and_context(conn, corpus, batch):
    """The point of the test is judging the combination, in time."""
    payload = listening.trial_payload(listening.next_trial(conn, "alice"))
    assert "context=c0" in payload["mix_url"]
    assert "bpm=120.0" in payload["mix_url"]
    assert "candidate_only=true" in payload["candidate_url"]
    assert "context=" not in payload["candidate_url"]
