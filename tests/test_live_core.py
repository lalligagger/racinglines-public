"""The shared live core (pipelines/live.py, markets/crowd.py, markets/quoting.py): the crowd's windowed batches,
quotes, the run folder and the registry on synthetic runs; downhill's numbers pinned to what they were before
the core was split out; and Whistler's run folder (skipped when it isn't on this machine) re-derived."""

import gzip
import hashlib
import json
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from racinglines import paths
from racinglines.markets import crowd as C
from racinglines.markets import quoting as Q
from racinglines.pipelines import live as LV
from racinglines.pipelines import live_dh as L

pytestmark = pytest.mark.quick

WHISTLER = paths.DATA / "runs" / "live" / "20260925_mtb_3"


def test_downhill_numbers_unchanged():
    """Quotes, crowd fills, the book, P&L and the crowd's results on a fixed synthetic grid: the same digest
    as live_dh before the core was split out of it (28 Sep 2026)."""
    qs = []
    for fair in np.linspace(0, 1, 41):
        for st in ({"status": "NA", "next": 10}, {"status": "NA", "next": 1}, {"status": "InRace", "splits": [1]},
                   {"status": "InRace", "splits": [1, 2, 3, 4]}, {"status": "Finished"}):
            for inv in (-3000, -1250, 0, 800, 2500):
                qs.append(L.quote(float(fair), st, inv=inv))
    book = L.load_book(pathlib.Path(tempfile.mkdtemp()))
    quotes = [dict(bib=b, market=m, fair=0.2 + 0.05 * b, bid=round(0.15 + 0.05 * b, 2), ask=round(0.25 + 0.05 * b, 2))
              for b in range(1, 8) for m in ("win", "podium")] + [dict(bib=9, market="win", fair=0.004, bid=None, ask=0.02)]
    fills = []
    for i in range(40):
        fills += L.crowd_fills(quotes, book, np.random.default_rng(i), intensity=5.0)
    book["late"], book["late_left"] = True, [L.LATE_CAP] * L.CROWD
    for i in range(10):
        fills += L.crowd_fills(quotes, book, np.random.default_rng(100 + i), intensity=L.LATE_PACE, pot="late_left")
    fair = {f"{q['bib']}:{q['market']}": q["fair"] for q in quotes}
    out = {(1, "win"): True, (2, "win"): False}
    res = [qs, fills, book, L.book_pnl(book, fair, out), L.crowd_results(book, fair, out)]
    digest = hashlib.sha256(json.dumps(res, sort_keys=True, default=str).encode()).hexdigest()
    assert len(fills) == 3793
    assert digest == "b83ff67bf7ae81968ade6ecd76dbb2dba2e3689b4c01cb9654a37cc2350826ab"


def test_downhill_constants_come_from_the_schema():
    from racinglines import sports
    live = sports.load("mtb_dh")["live"]
    assert L.HALF_SPREAD == live["quoting"]["half_spread"] == 0.03
    assert (L.CROWD, L.CROWD_P, L.CROWD_BUDGET, L.MAX_POS) == (1000, 0.0004, (10.0, 200.0), 2500.0)
    assert (L.BASE_INTERVAL, L.LATE_INTERVAL, L.LATE_WHEN_LEFT, L.LATE_CAP, L.LATE_PACE) == (5, 2, 3, 100.0, 50.0)
    assert set(L.MARKETS) == {"win", "podium"}


def test_quotes_lean_cap_and_stop_near_certainty():
    assert Q.quote(0.004, 0.03) == (None, None) and Q.quote(0.996, 0.03) == (None, None)
    b0, a0 = Q.quote(0.40, 0.03)
    assert (b0, a0) == (0.37, 0.43)
    assert Q.quote(0.40, 0.03, tidy=False) == (0.37, 0.44)          # downhill's rounding, kept as it was
    b1, a1 = Q.quote(0.40, 0.03, inv=-1250)                     # short: both sides move up
    assert b1 >= b0 and a1 >= a0
    assert Q.quote(0.40, 0.03, inv=2500)[0] is None                 # long at the cap: no more buying
    assert Q.quote(0.02, 0.03)[0] is None                           # a bid below 1 cent isn't offered
    assert Q.half_spread({"pre-weekend": 0.03, "after FP1": 0.025}, "after FP1") == 0.025
    assert Q.half_spread(0.02, "anything") == 0.02


def test_window_batch_times_fills_in_order_within_budgets():
    p = C.Params(takers=200, rate_h=0.01, seed=1)
    book = C.new_book(p)
    quotes = [dict(key=f"win:{i}", fair=0.1 * i, bid=round(0.1 * i - 0.03, 2), ask=round(0.1 * i + 0.03, 2))
              for i in range(1, 6)] + [dict(key="win:9", fair=0.5, bid=None, ask=None)]
    t0 = datetime(2026, 10, 2, 3, 30, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2.5)
    fills = C.window(quotes, book, np.random.default_rng(3), p, t0, t1)
    assert fills and all("key" in f and "bib" not in f for f in fills)
    ts = [f["ts"] for f in fills]
    assert ts == sorted(ts) and t0.isoformat() <= ts[0] and ts[-1] <= t1.isoformat()
    assert not any(f["key"] == "win:9" for f in fills)             # not quoted: not traded
    assert min(book["left"]) >= -0.01
    rebuilt, _ = C.rebuild([dict(ts=t1.isoformat(), fills=fills)])
    for k, mk in book["markets"].items():                           # the book re-derives from its fills
        assert rebuilt[k]["inv"] == pytest.approx(mk["inv"]) and rebuilt[k]["cash"] == pytest.approx(mk["cash"])
    assert C.window(quotes, book, np.random.default_rng(4), p, t1, t1) == []          # an empty window
    # twice the hours, about twice the hits (a steady per-hour rate)
    n1 = sum(len(C.window(quotes, C.new_book(p), np.random.default_rng(s), p, t0, t0 + timedelta(hours=1))) for s in range(20))
    n2 = sum(len(C.window(quotes, C.new_book(p), np.random.default_rng(s), p, t0, t0 + timedelta(hours=2))) for s in range(20))
    assert 1.6 < n2 / n1 < 2.4


def test_pnl_and_crowd_results_by_key():
    p = C.Params(takers=100, rate_h=0.05, seed=2)
    book = C.new_book(p)
    quotes = [dict(key="h2h:1:2", fair=0.6, bid=0.57, ask=0.63)]
    t0 = datetime(2026, 10, 2, tzinfo=timezone.utc)
    C.window(quotes, book, np.random.default_rng(0), p, t0, t0 + timedelta(hours=10))
    picks = [dict(key="h2h:1:2", stake=25.0, shares=25 / 0.63)]
    fair = {"h2h:1:2": 0.6}
    pnl = C.book_pnl(book, fair, {}, picks)
    res = C.crowd_results(book, fair, {})
    assert pnl["crowd"] == pytest.approx(-res["total"])            # the maker's gain is the crowd's loss
    settled = C.book_pnl(book, fair, {"h2h:1:2": True}, picks)
    assert settled["taker"] == pytest.approx(25.0 - 25 / 0.63)
    mp = C.maker_positions(book, picks)
    assert mp["h2h:1:2"]["yes"] == pytest.approx(book["markets"]["h2h:1:2"]["inv"] - 25 / 0.63)


def _run(tmp, run, meta, ts, done=False, next_at=None):
    out = tmp / "runs" / "live" / run
    (out / "snaps").mkdir(parents=True)
    (out / "meta.json").write_text(json.dumps(meta))
    snap = dict(ts=ts, done=done, next_at=next_at, maker_pnl=dict(total=1.0, crowd=1.0, taker=0.0))
    with gzip.open(out / "snaps" / "20261002T033000.json.gz", "wt") as f:
        json.dump(snap, f)
    (out / "latest.json").write_text(json.dumps(snap))
    return out


def test_registry_finds_each_sport_and_its_state(tmp_path, monkeypatch):
    import os
    import time
    monkeypatch.setattr(paths, "DATA", tmp_path)
    LV.state.__dict__.pop("cache", None)
    assert LV.events() == [] and LV.state() is None
    dh = _run(tmp_path, "20260925_mtb_3", dict(slug="20260925_mtb", key="3"), "2026-09-27T23:00:55+00:00", done=True)
    os.utime(dh / "latest.json", (time.time() - 100, time.time() - 100))
    f1 = _run(tmp_path, "2026-16", dict(sport="f1", event_key="2026-16", title="Bahrain GP in Malaysia"),
              "2026-10-02T03:30:00+00:00", next_at=(datetime.now(timezone.utc) + timedelta(hours=20)).isoformat())
    evs = LV.events()
    assert [(e["run"], e["sport"], e["event_key"]) for e in evs] == [("2026-16", "f1", "2026-16"),
                                                                      ("20260925_mtb_3", "mtb_dh", "20260925_mtb")]
    assert LV.latest() == "2026-16" and LV.find("20260925_mtb")["run"] == "20260925_mtb_3"
    # F1: updated a day ago, but the next update is still ahead: live
    os.utime(f1 / "latest.json", (time.time() - 26 * 3600, time.time() - 26 * 3600))
    assert LV.state("2026-16", max_age_h=6) == "live"
    assert LV.state("20260925_mtb_3") == "replay"
    assert L.latest() == ("20260925_mtb", "3")                     # downhill's own names see downhill finals only
    assert LV.event_name("2026-16") == "Bahrain GP in Malaysia"
    assert LV.event_name("20260925_mtb") == "Whistler DH final (private book)"
    assert [v for _, v in LV.book_curve("2026-16")] == [1.0]


def test_launch_spec_merges_over_the_sport(tmp_path):
    p = tmp_path / "x.toml"
    p.write_text('sport = "f1"\nevent = "2026-16"\n[live.quoting]\nmax_pos = 1000.0\n')
    spec = LV.load_spec(p)
    assert spec["run"] == "2026-16" and spec["live"]["quoting"]["max_pos"] == 1000.0
    assert spec["live"]["quoting"]["half_spread"]["pre-weekend"] == 0.03            # the rest from sports/f1.toml
    assert LV.adapter("mtb_dh") is L


# --- Whistler's run folder (docs/live-events.md): skipped where it isn't present ------------------------

def _whistler():
    if not (WHISTLER / "book.json").exists():
        pytest.skip("Whistler's run folder isn't on this machine (data/runs/live/20260925_mtb_3: the data bucket)")


def test_whistler_book_rederives_from_its_fills():
    _whistler()
    book = json.loads((WHISTLER / "book.json").read_text())
    markets, polls = L.book_at("20260925_mtb", "3")
    assert set(markets) == set(book["markets"])
    for k, mk in book["markets"].items():
        assert markets[k]["inv"] == pytest.approx(mk["inv"], abs=1e-6)
        assert markets[k]["cash"] == pytest.approx(mk["cash"], abs=1e-6)
    assert sum(len(p["fills"]) for p in polls) == book["crowd"]["fills"] == 7703


# sha256 of the Live tab's body as rendered on 28 Sep 2026, before the live core was split out
WHISTLER_PAGES = {
    ("maker", "20260927T212117"): "6219292cc140e897010ebde9122d0add7dadc3e09b4eeff5157067d19d041210",
    ("maker", "20260927T224635"): "4f9a704be26783c925d3c654fbf48d1586230dd654e70a76ec48cb711004749b",
    ("maker", "20260927T230055"): "f6fabb42e45134a1977c203d85997f3b0bcf053a6dc817851e04c4038e095a03",
    ("taker", "20260927T212117"): "54c3fe09f1745959547071810536153e164d40108280f325be613dfe151e887f",
    ("taker", "20260927T224635"): "70e29e10bd18ff5195a40d1fd1c8deaff21f35bfa607f8246677b8470bea6ea8",
    ("taker", "20260927T230055"): "88aa5fb5411aefb74588bf62541c561cd57f808100b0539ef7ecbf95131fa403",
}


@pytest.mark.parametrize("role,t", sorted(WHISTLER_PAGES))
def test_whistler_replay_pages_unchanged(role, t):
    _whistler()
    if len(L.snap_times("20260925_mtb", "3")) != 760:
        pytest.skip("Whistler's run folder differs from the bucket's copy")
    from racinglines.web.app import templates
    from racinglines.web.views import live_context
    html = templates.get_template("live_partial.html").render(live_context("20260925_mtb_3", t, role == "maker", 1))
    assert hashlib.sha256(html.encode()).hexdigest() == WHISTLER_PAGES[(role, t)]
