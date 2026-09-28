"""Backtest venues (racinglines/markets/venue_replay.py): a live downhill final's private book, recorded by
live_dh.update on a synthetic feed, replays exactly from its polls and seeds, and another quoting rule
replays against the same crowd draws. No network, no database."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from racinglines.markets import crowd as C
from racinglines.markets import venue_replay as VR
from racinglines.pipelines import live_dh as L

pytestmark = pytest.mark.quick

N = 12                                                   # riders in the final, one starting every two polls


def _feed(poll):
    res = []
    for i in range(N):
        bib = i + 1
        started = poll >= 2 * i
        finished = poll >= 2 * i + 2
        t = 200_000 + 700 * ((i * 7) % N)
        res.append(dict(RaceNr=bib, ExpectedStartTime=i,
                        Status="Finished" if finished else ("InRace" if started else "NA"),
                        RaceTime=t if finished else None, Times=[dict(RaceTime=t // 4)] if started else []))
    nxt = [r["RaceNr"] for r in res if r["Status"] == "NA"]
    return dict(Results=res, Riders={str(i + 1): dict(PrintName=f"R{i + 1}") for i in range(N)}, NextToStart=nxt)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("live")
    mp = pytest.MonkeyPatch()
    mp.setattr(L.paths, "DATA", tmp)
    clock = dict(t=datetime(2026, 9, 27, 22, 0, tzinfo=timezone.utc), poll=0)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["t"]
    mp.setattr(L, "datetime", Clock)
    mp.setattr(L, "fetch", lambda slug, key, session=None: _feed(clock["poll"]))
    mp.setattr(L, "quali_best", lambda slug, keys, session=None: ({i + 1: 199_000 + 500 * i for i in range(N)}, {0: 4.0}))
    mp.setattr(L, "season_prior", lambda slug, category="ME": {})
    mp.setattr(L, "sync_positions", lambda *a, **k: None)
    mp.setattr(L, "N_SIMS", 2000)
    mp.setattr(L, "CROWD_P", 0.01)                        # a busy crowd, so a short final has plenty of fills
    L.update.__dict__.pop("cache", None)
    for poll in range(2 * N + 3):
        clock["poll"] = poll
        L.update("synth", "3", ["2"], interval=L.BASE_INTERVAL)
        clock["t"] += timedelta(seconds=L.BASE_INTERVAL)
    L.update.__dict__.pop("cache", None)
    yield L.outdir("synth", "3")
    mp.undo()


def test_the_recorded_book_replays_exactly(run):
    book = json.loads((run / "book.json").read_text())
    rep = VR.PrivateBook.from_run(run).replay()
    assert book["crowd"]["fills"] > 50 and rep["book"]["crowd"]["fills"] == book["crowd"]["fills"]
    assert set(rep["book"]["markets"]) == set(book["markets"])
    for k, m in book["markets"].items():
        for f in ("inv", "cash", "crowd_inv", "crowd_cash"):
            assert rep["book"]["markets"][k][f] == pytest.approx(m[f], abs=1e-9), (k, f)
    assert rep["book"]["left"] == book["left"] and rep["book"]["late"] is book["late"] is True    # the late window ran
    latest = json.loads((run / "latest.json").read_text())
    assert rep["pnl"]["crowd"] == pytest.approx(latest["maker_pnl"]["crowd"], abs=1e-9)


def test_another_quoting_rule_replays_against_the_same_crowd(run):
    pb = VR.PrivateBook.from_run(run)
    narrow, wide = (pb.replay(VR.spread_quoter(hs, max_pos=pb.params.max_pos)) for hs in (0.01, 0.10))
    assert narrow["book"]["crowd"]["fills"] > 0 and wide["book"]["crowd"]["fills"] > 0
    # the same draws decide who trades; a wider spread earns more per fill from a crowd that trades at random
    per = lambda r: r["pnl"]["crowd"] / max(r["book"]["crowd"]["volume"], 1e-9)          # noqa: E731
    assert per(wide) > per(narrow)
    again = pb.replay(VR.spread_quoter(0.10, max_pos=pb.params.max_pos))
    assert again["fills"] == wide["fills"]                                              # deterministic


def test_a_replay_starts_from_a_fresh_book_each_time(run):
    pb = VR.PrivateBook.from_run(run)
    a, b = pb.replay(), pb.replay()
    assert a["book"]["markets"] == b["book"]["markets"] and a["book"] is not b["book"]
    assert C.new_book(pb.params)["left"] == a["book"]["budget"]


def test_whistler_book_replays_as_a_backtest():
    """The real Whistler final (data bucket: data/runs/live/20260925_mtb_3), where it's on this machine."""
    from racinglines.pipelines import live as LV
    run = LV.base() / "20260925_mtb_3"
    if not (run / "book.json").exists():
        pytest.skip("Whistler's run folder isn't on this machine (the data bucket)")
    book = json.loads((run / "book.json").read_text())
    rep = VR.PrivateBook.from_run(run).replay()
    assert rep["book"]["crowd"]["fills"] == book["crowd"]["fills"]
    for k, m in book["markets"].items():
        assert rep["book"]["markets"][k]["inv"] == pytest.approx(m["inv"], abs=1e-6)
        assert rep["book"]["markets"][k]["cash"] == pytest.approx(m["cash"], abs=1e-6)


def test_window_batches_replay_like_the_f1_engine(tmp_path):
    """F1's book (live_f1._crowd): one batch per window between updates, at the quotes posted when it opened,
    late from the pre-race push. A run folder written the same way replays to the same book."""
    import gzip
    from racinglines.pipelines import live as LV
    live = dict(crowd=dict(takers=200, rate_h=0.02, seed=5, late_cap=100.0, late_pace=20.0), quoting=dict(max_loss=None))
    cp = C.Params.from_dict(dict(live["crowd"], max_loss=None))
    (tmp_path / "snaps").mkdir()
    LV.write_meta(tmp_path, dict(sport="f1", event_key="2026-99", settings=live), "20261001T000000")
    book = C.new_book(cp)
    t = [datetime(2026, 10, 1, h, tzinfo=timezone.utc) for h in (8, 12, 16, 20)]
    quotes = None
    for i, ts in enumerate(t):
        if quotes is not None:
            late = i == len(t) - 1
            if late:
                C.open_late(book, cp, ts.isoformat())
            f = C.window(quotes, book, __import__("numpy").random.default_rng(100 + i), cp, t[i - 1], ts,
                         pace=cp.late_pace if late else 1.0, pot="late_left" if late else "left")
            LV.append(tmp_path, "crowd.jsonl", dict(ts=ts.isoformat(timespec="seconds"), seed=100 + i, late=late,
                                                    window=[t[i - 1].isoformat(timespec="seconds"),
                                                            ts.isoformat(timespec="seconds")], fills=f))
        fair = [0.5 - 0.1 * i, 0.3, 0.2 + 0.1 * i]
        quotes = [dict(key=f"race_win:{k}", fair=p, bid=round(p - 0.03, 2), ask=round(p + 0.03, 2)) for k, p in enumerate(fair)]
        snap = dict(ts=ts.isoformat(timespec="seconds"), sport="f1", markets=[dict(q, kind="race_win") for q in quotes],
                    outcomes=[dict(key="race_win:0", yes=True)] if i == len(t) - 1 else [])
        with gzip.open(tmp_path / "snaps" / f"{ts:%Y%m%dT%H%M%S}.json.gz", "wt") as g:
            json.dump(snap, g)
        (tmp_path / "latest.json").write_text(json.dumps(snap))
    rep = VR.PrivateBook.from_run(tmp_path).replay()
    assert book["crowd"]["fills"] > 20 and rep["book"]["crowd"]["fills"] == book["crowd"]["fills"]
    for k, m in book["markets"].items():
        assert rep["book"]["markets"][k]["inv"] == pytest.approx(m["inv"], abs=1e-9)
        assert rep["book"]["markets"][k]["cash"] == pytest.approx(m["cash"], abs=1e-9)
    assert rep["book"]["late_left"] == book["late_left"]
