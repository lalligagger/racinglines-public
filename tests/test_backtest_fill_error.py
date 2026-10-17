"""scripts/probes/backtest_fill_error.py: the book walk and the error of the backtest's one-price fill against it."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("backtest_fill_error", Path(__file__).resolve().parents[1] / "scripts/probes/backtest_fill_error.py")
FE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FE)

BOOK = dict(bids=[(0.50, 100), (0.48, 200)], asks=[(0.52, 60), (0.54, 40), (0.55, 1000)])


def test_walk_takes_levels_best_first_and_reports_a_short_book():
    assert FE.walk_vwap(BOOK["asks"], 100) == (pytest.approx((60 * 0.52 + 40 * 0.54) / 100), 100)
    px, filled = FE.walk_vwap([(0.52, 10)], 25)
    assert px == pytest.approx(0.52) and filled == 10
    assert FE.walk_vwap([], 5) == (None, 0.0)


def test_no_side_walks_the_yes_bids_flipped():
    assert FE.no_levels(BOOK["bids"]) == [(pytest.approx(0.50), 100), (pytest.approx(0.52), 200)]


def test_one_price_fill_against_the_walk():
    # $52 at our ask 0.52 = 100 shares; the book fills 60 at 0.52 and 40 at 0.54; no fee, a cent of cost
    r = FE.order_rows(0.52, BOOK, "YES", 52.0, 0.01, 0.0)
    truth = (60 * 0.52 + 40 * 0.54) / 100
    assert r["full"] and r["truth"] == pytest.approx(truth) and r["ours"] == pytest.approx(0.53)
    assert r["err_pct"] == pytest.approx((0.53 - truth) / truth * 100)
    small = FE.order_rows(0.52, BOOK, "YES", 5.2, 0.0, 0.0)   # inside the touch, no cost: no error
    assert small["err_pct"] == pytest.approx(0.0)


def test_a_book_too_thin_is_marked_not_full():
    r = FE.order_rows(0.50, dict(bids=[], asks=[(0.50, 10)]), "YES", 50.0, 0.0, 0.0)
    assert not r["full"] and r["filled"] == pytest.approx(0.1)


def test_kalshi_fee_applies_to_both_prices():
    r = FE.order_rows(0.52, BOOK, "YES", 5.2, 0.0, 0.07)
    assert r["err_pct"] == pytest.approx(0.0) and r["ours"] > 0.52


def test_a_weekend_end_to_end_on_a_stage_file(tmp_path, monkeypatch):
    import pandas as pd

    from racinglines.markets import probalytics as PB
    from racinglines.pipelines import weekend_sweep as W
    (tmp_path / "stages").mkdir()
    pd.DataFrame([dict(market_platform_id="0xc1", outcome_pid="tokA", timestamp=pd.Timestamp("2026-06-14 11:00", tz="UTC"),
                       bid_px=[0.40, 0.38], bid_sz=[10.0, 50.0], ask_px=[0.44, 0.50], ask_sz=[7.0, 900.0])]).to_parquet(
        tmp_path / "stages" / "2026-07_POLYMARKET.parquet")
    monkeypatch.setattr(PB, "root", lambda: tmp_path)
    links = pd.DataFrame(dict(token_id=["tokA"], condition_id=["0xc1"], prediction=["race_win"]))
    monkeypatch.setattr(W, "_race_id", lambda conn, k: 1)
    monkeypatch.setattr(W, "_links", lambda conn, rid, venue: links if venue == "polymarket" else links.iloc[:0])

    class Ours:                                          # our tape: a 5-minute price of 0.42, no quote (Polymarket)
        def __init__(self, *a, **k):
            pass

        def quote(self, tok, t):
            return None

        def price(self, tok, t):
            return 0.42

        def view(self, m, t, vol_min):
            return 0.42, 80.0, vol_min <= 80.0

    monkeypatch.setattr(W, "_exchange", lambda venue: Ours)
    w = dict(event_key="2026-07", race_start=pd.Timestamp("2026-06-14 13:00"),
             stages=[("after Quali", pd.Timestamp("2026-06-14 12:00"))])
    rows = FE.weekend_rows(None, w, "polymarket", [2.1, 42.0], 0.01)
    yes = {r["stake"]: r for r in rows if r["side"] == "YES"}
    assert yes[2.1]["truth"] == pytest.approx(0.44) and yes[2.1]["ours"] == pytest.approx(0.43)
    assert yes[2.1]["err_pct"] < 0                       # the backtest paid less than the ask: optimistic
    assert yes[42.0]["full"] and yes[42.0]["truth"] == pytest.approx((7 * 0.44 + 93 * 0.50) / 100)
    no = {r["stake"]: r for r in rows if r["side"] == "NO"}
    assert no[2.1]["truth"] == pytest.approx(0.60)       # NO at 1 - the 0.40 bid
    s = FE.summarize(pd.DataFrame(rows))
    assert s["polymarket $42"]["all"]["compared"] == 2 and "after Quali" in s["polymarket $42"]["by_stage"]
    assert "Fill-price error" in FE.markdown(s, type("A", (), dict(year=2026)))
    assert s["polymarket $42"]["tradeable"]["compared"] == 2 and s["polymarket $42"]["fake_mid"]["orders"] == 0
    assert yes[42.0]["touch_err_pct"] == pytest.approx((0.43 - 0.44) / 0.44 * 100)   # the spread alone
    thin = FE.weekend_rows(None, w, "polymarket", [2.1], 0.01, min_volume_24h=100.0)
    assert not any(r["tradeable"] for r in thin)                       # under the volume floor: not tradeable


def test_main_reads_the_stage_files_only(tmp_path, monkeypatch):
    import os
    import sys

    from racinglines.markets import probalytics as PB
    (tmp_path / "pb" / "stages").mkdir(parents=True)
    monkeypatch.setenv("PROBALYTICS_DATA", str(tmp_path / "pb"))
    monkeypatch.setenv("PROBALYTICS_BUCKET", "gs://x/vendor/probalytics")
    monkeypatch.setattr(FE, "weekend_rows", lambda *a, **k: [])
    monkeypatch.setattr(sys, "argv", ["x", "--rounds", "1", "--out", str(tmp_path / "out")])

    class Conn:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    import racinglines.db.config as DC
    monkeypatch.setattr(DC, "get_engine", lambda: type("E", (), dict(connect=lambda self: Conn()))())
    assert FE.main() == 1                                # no orders in this empty setup
    assert PB.root() == tmp_path / "out" / "probalytics-stages" and (PB.root() / "stages").is_symlink()
    assert "PROBALYTICS_BUCKET" not in os.environ


def test_not_full_counts_only_orders_that_were_walked():
    import pandas as pd
    df = pd.DataFrame([dict(venue="polymarket", stake=50.0, stage="s", kind="race_h2h", side="YES", ours_px=0.5,
                            book=True, tradeable=True, fake_mid=False, filled=1.0, full=True, err_pct=-1.0,
                            touch_err_pct=-1.0),
                       dict(venue="polymarket", stake=50.0, stage="s", kind="race_h2h", side="NO", ours_px=0.5,
                            book=True, tradeable=True, fake_mid=False)])   # a book with no bids: nothing to walk
    a = FE.summarize(df)["polymarket $50"]
    assert a["all"]["not_full"] == 0 and a["by_kind"]["race_h2h"]["compared"] == 1
