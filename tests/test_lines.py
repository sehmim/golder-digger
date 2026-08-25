"""Riding a line goes further in one respect and no other.

That is the whole claim the transit model makes, and the one DIGLINE says a
single DISTANCE dial cannot: "farther" has to be able to say farther in what.
So these assert per-line monotonicity, that the gate still holds at the far end,
and that a line nobody can measure says so instead of inventing stops.
"""
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from goldigger import api, config, db, ingest, lines, scoring


def corpus_of(specs):
    """specs: (chunk_id, tonic, bpm, centroid, clap_seed)."""
    corpus = scoring.Corpus([{"chunk_id": c, "path": f"/lib/{c}.wav", "role": None,
                              "role_source": None, "tags": None, "is_major": 1,
                              "spectral": None} for c, *_ in specs])
    corpus.index = {c: i for i, (c, *_) in enumerate(specs)}
    corpus.ids = [c for c, *_ in specs]
    for i, (cid, tonic, bpm, centroid, seed) in enumerate(specs):
        rng = np.random.default_rng(seed)
        v = rng.standard_normal(config.CLAP_DIM).astype(np.float32)
        corpus.clap[i] = v / np.linalg.norm(v)
        corpus.chroma[i] = 1 / 12
        if tonic >= 0:
            corpus.chroma[i, tonic] = 0.5
        corpus.tonic[i] = tonic
        corpus.bpm[i] = bpm
        corpus.kconf[i] = 0.9
        corpus.tconf[i] = 0.9
        corpus.roles[i] = "melody"
        corpus.hashes[i] = cid
        corpus.spectral[i] = [centroid, centroid * 2, centroid * 0.9, 0.01]
    return corpus


def context(corpus, tonic=0, bpm=120.0):
    """A context standing where the library's first chunk stands, which is what
    a real one built from resolved chunks looks like."""
    ctx = {"idx": [], "clap": corpus.clap[0].copy(),
           "chroma": np.full(12, 1 / 12, dtype=np.float32),
           "bpm": bpm, "tconf": 1.0, "tonic": tonic, "kconf": 0.9,
           "roles": set(), "hashes": set()}
    ctx["chroma"][tonic] = 0.5
    ctx["timbre"] = lines.timbre_vectors(corpus)[0].copy()
    return ctx


@pytest.fixture
def library():
    # tonic walks around the circle, tempo walks away, centroid brightens
    return corpus_of([
        ("a", 0, 120.0, 1000.0, 1), ("b", 7, 121.0, 1200.0, 2),
        ("c", 2, 122.0, 1600.0, 3), ("d", 9, 123.0, 2200.0, 4),
        ("e", 4, 124.0, 3000.0, 5), ("f", 11, 125.0, 4200.0, 6),
        ("g", 6, 126.0, 6000.0, 7), ("h", 1, 127.0, 8000.0, 8),
    ])


def test_stops_go_outward_along_their_own_line(library):
    ctx = context(library)
    for key in lines.line_keys():
        route = lines.stops(library, ctx, key, count=4)
        if not route:
            continue
        positions = [s["position"] for s in route]
        assert positions == sorted(positions), f"{key} doubles back: {positions}"


def test_the_harmony_line_actually_walks_away_from_the_key(library):
    ctx = context(library, tonic=0)
    route = lines.stops(library, ctx, "harmony", count=4)

    d = lines.harmony_distance(library, ctx)
    rode = [d[library.index[s["chunk_id"]]] for s in route]
    assert rode[-1] > rode[0], f"the far stop is no further: {rode}"


def test_the_groove_line_is_ratio_aware(library):
    """A half-time chunk is at the near end of the groove line, not the far end
    -- the same reason Fit's rhythm term is ratio-aware."""
    corpus = corpus_of([("half", 0, 60.0, 1000.0, 1), ("odd", 0, 101.0, 1000.0, 2)])
    ctx = context(corpus, bpm=120.0)

    d = lines.groove_distance(corpus, ctx)

    assert d[0] < d[1], "60 against 120 should be nearer than 101 against 120"
    assert d[0] < 0.05


def test_a_chunk_with_no_tempo_has_no_place_on_the_groove_line(library):
    corpus = corpus_of([("timed", 0, 120.0, 1000.0, 1), ("oneshot", 0, np.nan, 1000.0, 2)])
    ctx = context(corpus, bpm=120.0)

    d = lines.groove_distance(corpus, ctx)

    assert np.isfinite(d[0]) and np.isnan(d[1])
    assert all(s["chunk_id"] != "oneshot" for s in lines.stops(corpus, ctx, "groove"))


def test_an_unmeasured_timbre_drops_off_the_line_rather_than_ranking_nearest(library):
    library.spectral[3] = np.nan
    library._timbre = None
    ctx = context(library)

    route = lines.stops(library, ctx, "timbre", count=8)

    assert all(s["chunk_id"] != "d" for s in route)


def test_no_single_descriptor_owns_the_timbre_line(library):
    """The blue line is timbre, not whichever descriptor has the fattest tail.

    Flatness is a ratio spanning nine orders of magnitude in a real library.
    Standardised linearly it carried 92% of the squared distance, so every far
    stop was simply the noisiest thing in the corpus and the other three
    descriptors were decoration. Logging it is what fixed that, and this is the
    assertion that keeps a future descriptor from doing the same thing.
    """
    rng = np.random.default_rng(11)
    corpus = corpus_of([(f"c{i}", i % 12, 120.0, 400.0 * (1.2 ** i), i)
                        for i in range(60)])
    # a realistic flatness spread: mostly tonal, a handful of noisy chunks
    corpus.spectral[:, 3] = np.exp(rng.normal(np.log(0.01), 2.0, len(corpus)))
    corpus._timbre = None

    vectors = lines.timbre_vectors(corpus)
    per_axis = np.zeros(len(config.TIMBRE_DESCRIPTORS))
    for i in range(len(corpus)):
        per_axis += ((vectors - vectors[i]) ** 2).sum(axis=0)

    share = per_axis / per_axis.sum()
    assert share.max() < 0.6, dict(zip(config.TIMBRE_DESCRIPTORS, share.round(3)))


def test_the_timbre_label_names_the_descriptor_that_actually_moved(library):
    """Not the one it happens to check first. An early version compared centroid
    against flatness alone, so a stop pushed out entirely by bandwidth was
    reported as "brighter" -- faithful-sounding and wrong."""
    corpus = corpus_of([("ref", 0, 120.0, 1000.0, 1), ("wide", 0, 120.0, 1000.0, 2)])
    ctx = context(corpus)
    # identical but for bandwidth, which is corpus.spectral column 2
    corpus.spectral[1] = corpus.spectral[0]
    corpus.spectral[1, 2] = corpus.spectral[0, 2] * 8
    corpus._timbre = None
    ctx["timbre"] = lines.timbre_vectors(corpus)[0].copy()

    assert "wider" in lines._timbre_label(corpus, 1, ctx)


def test_the_gate_never_opens_below_the_engines_hard_minimum(library):
    """0.45 minus 0.05, six times, is 0.20000000000000007 -- which is not
    `<= 0.20`. The naive loop took one more step and admitted candidates a full
    step below FIT_FLOOR_MIN, on the default preset, on any thin pool."""
    reached = []
    scoring.relax_floor(config.FIT_FLOOR, 99,
                        lambda f: reached.append(f) or np.array([], dtype=int))

    assert min(reached) >= config.FIT_FLOOR_MIN - 1e-9, reached
    assert any(abs(f - config.FIT_FLOOR_MIN) < 1e-9 for f in reached), \
        f"never actually tried the minimum: {reached}"


def test_a_line_relaxed_to_the_minimum_admits_nothing_below_it(library):
    ctx = context(library)
    # nothing can clear any floor, so the loop runs all the way down
    route = lines.route(library, ctx, "character",
                        allowed=np.zeros(len(library), dtype=bool), count=6)

    assert route["fit_floor"] >= config.FIT_FLOOR_MIN
    assert route["stops"] == []


def test_the_log_transform_keeps_the_smallest_real_values(library):
    """Flatness reaches 2e-10 in a real library. A clamp sized for hertz would
    collapse the very tail the timbre line exists to reach."""
    corpus = corpus_of([("tiny", 0, 120.0, 1000.0, 1), ("small", 0, 120.0, 1000.0, 2),
                        ("mid", 0, 120.0, 1000.0, 3)])
    corpus.spectral[:, 3] = [2.0e-10, 6.0e-10, 1.0e-2]
    corpus._timbre = None

    flatness = lines.timbre_vectors(corpus)[:, 3]

    assert flatness[0] < flatness[1], "two distinct values collapsed onto one"


def test_a_line_with_nothing_to_measure_reports_unavailable(library):
    """A MIDI-only context has no sound, so it has no position in descriptor
    space. Drawing that line greyed out is information; inventing stops is not."""
    ctx = context(library)
    ctx["idx"] = []
    ctx.pop("timbre")

    net = lines.network(library, ctx)
    timbre = next(r for r in net["lines"] if r["key"] == "timbre")

    assert timbre["available"] is False and timbre["stops"] == []
    assert any(r["available"] for r in net["lines"]), "no line survived at all"


def test_every_stop_clears_the_floor_its_line_actually_used(library):
    """And a line that had to relax its gate to fill up says so -- from the
    drawing alone, a line that held and one that quietly opened look the same."""
    ctx = context(library)
    net = lines.network(library, ctx)

    for route in net["lines"]:
        for stop in route["stops"]:
            assert stop["fit"] >= route["fit_floor"] - 1e-9, \
                f"{route['key']} stop below its own floor: {stop}"
        assert route["fit_floor_relaxed"] == (
            route["fit_floor"] < route["fit_floor_requested"])


def test_a_relaxed_line_is_reported_not_hidden(library):
    """Ask for more stops than the library can supply above the floor."""
    ctx = context(library)
    net = lines.network(library, ctx, count=8)

    relaxed = [r for r in net["lines"] if r["fit_floor_relaxed"]]
    for route in relaxed:
        assert route["fit_floor"] < net["fit_floor_requested"]


def test_the_context_never_rides_its_own_file(library):
    ctx = context(library)
    ctx["hashes"] = {"a"}

    net = lines.network(library, ctx)

    assert all(s["chunk_id"] != "a" for r in net["lines"] for s in r["stops"])


def test_interchanges_are_stops_on_more_than_one_line(library):
    net = lines.network(library, context(library))

    counted = {}
    for route in net["lines"]:
        for stop in route["stops"]:
            counted.setdefault(stop["chunk_id"], set()).add(route["key"])
    expected = {cid for cid, keys in counted.items() if len(keys) > 1}

    assert {i["chunk_id"] for i in net["interchanges"]} == expected


def test_labels_say_something_a_listener_could_check(library):
    ctx = context(library, tonic=0, bpm=120.0)

    fifth = corpus_of([("up", 7, 120.0, 1000.0, 1)])
    assert lines._harmony_label(fifth, 0, ctx).startswith("a fifth up")

    double = corpus_of([("dbl", 0, 240.0, 1000.0, 1)])
    assert "2:1" in lines._groove_label(double, 0, ctx)


def test_the_harmony_label_names_whichever_term_moved_it():
    """Naming the key relation alone can call the furthest stop "a tone up"
    when what put it there is sharing no notes. An explanation that names the
    smaller term is worse than none -- the listener will test it and find it
    false."""
    corpus = corpus_of([("shifted", 7, 120.0, 1000.0, 1),
                        ("scattered", 0, 120.0, 1000.0, 2)])
    ctx = context(corpus, tonic=0)
    # same notes as the context, only the tonic moved -> the key is the reason
    corpus.chroma[0] = ctx["chroma"]
    # same tonic, unrelated notes -> the notes are the reason
    corpus.chroma[1] = np.full(12, 1 / 12, dtype=np.float32)
    corpus.chroma[1, 6] = 0.5

    assert lines._harmony_label(corpus, 0, ctx) == "a fifth up"
    assert "notes" in lines._harmony_label(corpus, 1, ctx)
    assert lines._harmony_label(corpus, 1, ctx).startswith("same key")


def test_an_unknown_line_is_a_named_failure(library):
    with pytest.raises(ValueError, match="no such line"):
        lines.stops(library, context(library), "vermilion")


# ------------------------------------------------------------------- api

@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    root.mkdir()
    for i in range(6):
        t = np.linspace(0, 2.0, int(2.0 * 22050), endpoint=False)
        sf.write(root / f"{i}.wav", (0.2 * np.sin(2 * np.pi * (180 + 70 * i) * t)
                                     ).astype("float32"), 22050)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db._local.__dict__.clear()
    conn = db.thread_conn(tmp_path / "t.db")
    db.init(conn)
    ingest.run_job(conn, ingest.new_job(conn, str(root)), str(root))
    api.state["conn"] = conn
    api.state["corpus"] = ingest.load_corpus(conn)
    with TestClient(api.app) as c:
        yield c, conn, root


def test_spectral_reaches_the_corpus(client):
    """DIGLINE's cheapest gap: the descriptors were measured all along and
    never loaded, so the timbre line had nothing to stand on."""
    c, conn, root = client
    corpus = api.state["corpus"]

    assert corpus.spectral.shape == (len(corpus), len(config.TIMBRE_DESCRIPTORS))
    assert np.isfinite(corpus.spectral).any(), "no chunk carried its descriptors"


def test_the_route_endpoint_draws_a_network(client):
    c, conn, root = client
    ids = [r["chunk_id"] for r in conn.execute(
        "SELECT chunk_id FROM chunks ORDER BY chunk_id LIMIT 2")]

    body = c.post("/session/lines", json={"context_ids": ids, "stops": 3}).json()

    assert [r["key"] for r in body["lines"]] == lines.line_keys()
    assert {r["colour"] for r in body["lines"]} == {"green", "orange", "blue", "yellow"}
    assert any(r["stops"] for r in body["lines"]), "every line came back empty"
    for route in body["lines"]:
        for stop in route["stops"]:
            assert stop["chunk_id"] not in ids
            assert stop["why"]


def test_a_context_free_request_is_a_400(client):
    c, conn, root = client
    assert c.post("/session/lines", json={"context_ids": []}).status_code == 400
