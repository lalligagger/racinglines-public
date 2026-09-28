"""Live downhill final (pipelines/live_dh.py): rank probabilities, quotes, the crowd, P&L. Synthetic riders,
no network."""

import numpy as np
import pytest

from racinglines.pipelines import live_dh as L

pytestmark = pytest.mark.quick


def _riders():
    base = dict(nation="X", team=None, uci_rank=1, split_pos=[], sort=None)
    return [dict(base, bib=1, name="A", status="Finished", time=200_000, splits=[50_000, 200_000], next=None),
            dict(base, bib=2, name="B", status="InRace", time=None, splits=[49_000], next=None),
            dict(base, bib=3, name="C", status="NA", time=None, splits=[], next=0),
            dict(base, bib=4, name="D", status="DNS", time=None, splits=[], next=None)]


def test_rank_probabilities_are_distributions():
    rows, factor = L.simulate(_riders(), {1: 205_000, 2: 204_000, 3: 199_000}, {0: 4.0, 1: 1.0}, n=4000)
    by = {r["bib"]: r for r in rows}
    assert by[4]["p1"] == 0 and by[4]["top10"] == 0                        # did not start
    assert abs(sum(r["p1"] for r in rows) - 1) < 1e-9                      # exactly one winner per simulation
    for r in rows:
        assert r["p1"] <= r["top3"] <= r["top5"] <= r["top10"] + 1e-12
    assert by[3]["p1"] > by[1]["p1"]                                       # the fast qualifier still to come


def test_quotes_widen_on_course_lean_against_inventory_and_stop_at_certainty():
    on, waiting = dict(status="InRace"), dict(status="NA", next=10)
    b1, a1 = L.quote(0.40, waiting)
    b2, a2 = L.quote(0.40, on)
    assert a2 - b2 > a1 - b1
    b3, a3 = L.quote(0.40, waiting, inv=-L.MAX_POS / 2)                   # short: quotes move up
    assert a3 >= a1 and b3 >= b1
    assert L.quote(0.999, waiting) == (None, None)
    assert L.quote(0.40, waiting, inv=-L.MAX_POS)[1] is None               # at the limit: no more selling


def test_safe_riders_slow_qualifying_adds_spread_not_speed():
    riders = [dict(bib=i, name=n, status="NA") for i, n in enumerate(["fast", "star", "mid", "low", "tail"])]
    q = {0: 200_000, 1: 212_000, 2: 205_000, 3: 208_000, 4: 210_000}
    prior = {"fast": (0.3, 0.6), "star": (0.9, 0.95), "mid": (0.1, 0.5), "low": (0.05, 0.4), "tail": (0.01, 0.3)}
    base, extra = L.blended_pace(riders, q, prior)
    assert extra[1] > 0 and extra[0] == 0                                  # the star cruised; the fast run is genuine
    assert base[1] > 200_000                                               # not pulled to the top


def test_crowd_budgets_and_book_pnl(tmp_path):
    book = L.load_book(tmp_path)
    assert len(book["ids"]) == L.CROWD and all(L.CROWD_BUDGET[0] - 0.01 <= b <= L.CROWD_BUDGET[1] + 0.01 for b in book["budget"])
    quotes = [dict(bib=1, market="win", fair=0.3, bid=0.27, ask=0.33)]
    fills = []
    for i in range(30):
        fills += L.crowd_fills(quotes, book, np.random.default_rng(i))
    assert fills and all(f["taker"] in book["ids"] for f in fills)
    assert all(left >= -0.01 for left in book["left"])                     # nobody bets beyond their event budget
    for i in range(5):                                                      # not even at the late-window push pace
        L.crowd_fills(quotes, book, np.random.default_rng(100 + i), intensity=L.LATE_PACE)
    wagered = [b - left for b, left in zip(book["budget"], book["left"])]
    assert max(wagered) <= L.CROWD_BUDGET[1] + 0.01 and all(w <= b + 0.01 for w, b in zip(wagered, book["budget"]))
    pnl = L.book_pnl(book, {"1:win": 0.3}, {})
    res = L.crowd_results(book, {"1:win": 0.3}, {})
    assert abs(pnl["crowd"] + res["total"]) < 1e-6                         # the maker's gain is the crowd's loss
    assert pnl["crowd"] > 0                                                # the spread, marked at fair


def test_late_window_caps_each_taker_at_100(tmp_path):
    book = L.load_book(tmp_path)
    book["late"], book["late_left"] = True, [L.LATE_CAP] * L.CROWD
    left_before = list(book["left"])
    quotes = [dict(bib=1, market="win", fair=0.3, bid=0.27, ask=0.33)]
    for i in range(20):
        L.crowd_fills(quotes, book, np.random.default_rng(i), intensity=L.LATE_PACE, pot="late_left")
    spent = [L.LATE_CAP - x for x in book["late_left"]]
    assert max(spent) <= L.LATE_CAP + 0.01 and min(book["late_left"]) >= -0.01
    assert book["left"] == left_before                                      # the event budgets are untouched


def test_replay_state_snapshots_and_book(tmp_path, monkeypatch):
    import gzip
    import json
    monkeypatch.setattr(L.paths, "DATA", tmp_path)
    assert L.state() is None                                            # nothing recorded: no Live tab
    out = L.outdir("ev", "3")
    (out / "snaps").mkdir()
    for name, ts in (("20260927T220000", "2026-09-27T22:00:00+00:00"), ("20260927T220010", "2026-09-27T22:00:10+00:00")):
        with gzip.open(out / "snaps" / f"{name}.json.gz", "wt") as f:
            json.dump(dict(ts=ts, maker_pnl=dict(total=1.0, crowd=1.0, taker=0.0)), f)
    (out / "latest.json").write_text(json.dumps(dict(ts="2026-09-27T22:00:10+00:00", done=False)))
    assert L.state() == "live"
    (out / "latest.json").write_text(json.dumps(dict(ts="2026-09-27T22:00:10+00:00", done=True)))
    assert L.state() == "replay"                                        # over: the grey tab, a replay
    assert L.snap_times("ev", "3") == ["20260927T220000", "20260927T220010"]
    assert L.load_at("ev", "3", "20260927T220005")[0]["ts"] == "2026-09-27T22:00:00+00:00"   # the last one before t
    fills = [dict(bib=1, market="win", side="buy", price=0.4, shares=10.0), dict(bib=1, market="win", side="sell", price=0.3, shares=4.0)]
    with (out / "crowd.jsonl").open("w") as f:
        f.write(json.dumps(dict(ts="2026-09-27T22:00:00+00:00", fills=fills[:1])) + "\n")
        f.write(json.dumps(dict(ts="2026-09-27T22:00:10+00:00", fills=fills[1:])) + "\n")
    mk, polls = L.book_at("ev", "3", "2026-09-27T22:00:00+00:00")
    assert len(polls) == 1 and mk["1:win"] == dict(inv=-10.0, cash=4.0)   # the crowd bought YES: the maker is short
    mk, _ = L.book_at("ev", "3")
    assert mk["1:win"]["inv"] == pytest.approx(-6.0) and mk["1:win"]["cash"] == pytest.approx(2.8)
    assert L.book_opened("ev", "3") == "2026-09-27T22:00:00+00:00"


def test_reprice_from_the_logged_raw_feed(tmp_path, monkeypatch):
    """live_dh.reprice: every logged feed response re-priced from the recorded inputs (no network)."""
    import gzip
    import json
    monkeypatch.setattr(L.paths, "DATA", tmp_path)
    out = L.outdir("ev", "3")
    (out / "raw").mkdir()
    riders = {str(b): dict(PrintName=n) for b, n in ((1, "A"), (2, "B"), (3, "C"))}

    def feed(done):
        res = [dict(RaceNr=1, Status="Finished", RaceTime=200_000, Times=[dict(RaceTime=50_000)], ExpectedStartTime=1),
               dict(RaceNr=2, Status="Finished" if done else "InRace", RaceTime=199_000 if done else None,
                    Times=[dict(RaceTime=49_000)], ExpectedStartTime=2),
               dict(RaceNr=3, Status="Finished" if done else "NA", RaceTime=201_000 if done else None, Times=[],
                    ExpectedStartTime=3)]
        return dict(Results=res, Riders=riders, NextToStart=[] if done else [3])
    for name, done in (("20260927T220000", False), ("20260927T220005", False), ("20260927T220010", True)):
        with gzip.open(out / "raw" / f"{name}.json.gz", "wt") as f:
            json.dump(feed(done), f)
    (out / "meta.json").write_text(json.dumps(dict(qbest={"1": 205_000, "2": 204_000, "3": 199_000},
                                                   qratio={"0": 4.0}, prior={}, conditions="")))
    (out / "latest.json").write_text(json.dumps(dict(done=True, outcomes=[dict(bib=2, market="win", yes=True),
                                                                          dict(bib=1, market="win", yes=False)])))
    res = L.reprice("ev", "3", label="t", n_sims=2000, echo=lambda m: None)
    assert [r["stamp"] for r in res["rows"]] == ["20260927T220000", "20260927T220005", "20260927T220010"]
    for r in res["rows"]:
        assert sum(v for k, v in r["fair"].items() if k.endswith(":win")) == pytest.approx(1, abs=1e-3)
    assert res["rows"][-1]["fair"]["2:win"] == 1.0                     # over: the winner is certain
    assert (out / "reprice" / "t.jsonl").exists() and res["scorecard"]["live"] == {}   # no snapshots: nothing to compare
