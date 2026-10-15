"""The taker's book fill (taker_fill = book): walk the stage's book levels instead of one price. Synthetic stages;
no data."""

import pytest

from racinglines.markets.strategies import taker_weekend as RB
from racinglines.pipelines import sweep_settings as SS
from racinglines.pipelines import weekend_sweep as W

BOOK = dict(bid=0.40, ask=0.44, bids=[(0.40, 10.0), (0.38, 50.0)], asks=[(0.44, 20.0), (0.50, 30.0)])


def _stage(**kw):
    return dict(dict(label="after FP1", t=None, fair=0.70, price=0.42, tradeable=True), **kw)


def test_walk_takes_levels_best_first_and_stops_at_the_book():
    assert RB.walk(BOOK["asks"], 30) == (pytest.approx((20 * 0.44 + 10 * 0.50) / 30), 30)
    px, got = RB.walk(BOOK["asks"], 80)
    assert got == 50 and px == pytest.approx((20 * 0.44 + 30 * 0.50) / 50)
    assert RB.walk([], 5) == (None, 0.0)


def test_book_fill_walks_the_asks_with_no_cost_per_share():
    p = RB.TakerParams(min_edge=0.05, stake_per_edge=1000, max_stake=50, cost=0.01, fill="book")
    m = RB._Market([_stage(**BOOK)], p)
    m.step(0)
    (tr,) = m.trades
    assert tr["side"] == "YES" and tr["shares"] == pytest.approx(50)           # the whole book: 20 + 30 shares
    assert tr["price"] == pytest.approx((20 * 0.44 + 30 * 0.50) / 50)
    old = RB._Market([_stage(**BOOK)], RB.TakerParams(min_edge=0.05, stake_per_edge=1000, max_stake=50, cost=0.01))
    old.step(0)
    assert old.trades[0]["price"] == pytest.approx(0.45)                        # the ask plus a cent, any size
    assert old.trades[0]["shares"] > 50


def test_book_fill_buys_no_at_one_minus_the_bids():
    p = RB.TakerParams(min_edge=0.05, stake_per_edge=1000, max_stake=6, cost=0.01, fill="book")
    m = RB._Market([_stage(fair=0.20, **BOOK)], p)
    m.step(0)
    (tr,) = m.trades
    assert tr["side"] == "NO" and tr["price"] == pytest.approx(0.60)            # 10 shares at 1 - 0.40


def test_a_stage_without_levels_keeps_the_price_fill():
    p = RB.TakerParams(min_edge=0.05, stake_per_edge=1000, max_stake=50, cost=0.01, fill="book")
    m = RB._Market([_stage(bid=0.40, ask=0.44)], p)
    m.step(0)
    assert m.trades[0]["price"] == pytest.approx(0.45)


class _Venue:
    def book_at(self, token, t):
        return dict(bids=BOOK["bids"], asks=BOOK["asks"])


def test_stage_levels_adds_the_whole_book_and_leaves_our_tape_alone():
    s = W.stage_levels(_stage(), _Venue(), "tok", None)
    assert s["asks"] == BOOK["asks"] and s["bids"] == BOOK["bids"]
    assert "asks" not in W.stage_levels(_stage(), object(), "tok", None)       # our tape: no book_at


def test_book_fill_needs_probalytics_tape(monkeypatch):
    monkeypatch.delenv("RACINGLINES_TAPE_SOURCE", raising=False)
    assert not W.book_fill(SS.Settings.from_dict())
    assert not W.book_fill(SS.Settings.from_dict(dict(taker_fill="touch")))
    with pytest.raises(ValueError):
        W.book_fill(SS.Settings.from_dict(dict(taker_fill="book")))
    book = SS.Settings.from_dict(dict(taker_fill="book", tape_source="probalytics"))
    assert W.book_fill(book) and W.taker_params(book)[0].fill == "book"
    assert W.taker_params(SS.Settings.from_dict(dict(taker_fill="touch")))[0].fill == "price"
    assert W.taker_params(SS.Settings.from_dict())[0].fill == "price"


def test_book_reaches_the_cli_mcp_and_the_lab():
    import argparse

    from racinglines.mcp import tools
    from racinglines.web import jobs
    ap = argparse.ArgumentParser()
    SS.add_arguments(ap, SS.Settings)
    assert SS.from_args(ap.parse_args(["--taker-fill", "book"]), SS.Settings)["taker_fill"] == "book"
    _, p = tools._job_params("f1_sweep", {"year": "2025", "settings": {"taker_fill": "book"}})
    assert p["settings"]["taker_fill"] == "book"
    jt = jobs.CATALOG["f1_sweep"]
    p = jobs.parse(jt, {"year": "2025", "taker_fill": "book"})
    assert p["settings"]["taker_fill"] == "book" and "--taker-fill" in jt.argv(p, "/runs/jobs/job_7.csv")


def test_touch_and_book_on_probalytics_tape_read_as_of_t_never_after(tmp_path):
    from datetime import datetime

    import pandas as pd

    from racinglines.markets import probalytics as PB
    t = datetime(2026, 6, 14, 12, 0)
    (tmp_path / "stages").mkdir()
    (tmp_path / "fills").mkdir()
    pm = dict(market_platform_id="0xc1", outcome_pid="tokA")
    pd.DataFrame([
        dict(pm, timestamp="2026-06-14 11:00", bid_px=[0.40, 0.38], bid_sz=[10.0, 5.0], ask_px=[0.44, 0.50],
             ask_sz=[7.0, 9.0]),
        dict(pm, timestamp="2026-06-14 12:30", bid_px=[0.90], bid_sz=[1.0], ask_px=[0.95], ask_sz=[1.0]),  # after t
    ]).assign(timestamp=lambda d: pd.to_datetime(d["timestamp"], utc=True)).to_parquet(
        tmp_path / "stages" / "2026-07_POLYMARKET.parquet")
    links = pd.DataFrame(dict(token_id=["tokA"], condition_id=["0xc1"], prediction=["race_win"]))
    v = PB.ProbalyticsPolymarket(None, links, t.replace(hour=0), t, event_key="2026-07", base=tmp_path, levels=True)
    v.touch_quotes = True                                   # taker_fill = touch / book
    assert v.quote("tokA", t) == (pytest.approx(0.40), pytest.approx(0.44))     # the 11:00 book, not 12:30's
    b = v.book_at("tokA", t)
    assert b["ts"] <= t and b["asks"] == [(0.44, 7.0), (0.50, 9.0)]
    s = W.stage_levels(_stage(), v, "tokA", t)
    assert s["asks"][0][0] == pytest.approx(0.44) and s["bids"][0][0] == pytest.approx(0.40)
    early = datetime(2026, 6, 14, 10, 0)
    assert v.quote("tokA", early) is None and v.book_at("tokA", early) is None          # nothing yet


THIN = dict(bid=0.08, ask=0.20, bids=[(0.08, 50.0), (0.01, 500.0)], asks=[(0.20, 20.0), (0.99, 500.0)])


def test_book_walk_stops_where_the_edge_runs_out():
    # a thin book: 20 at the touch, then 0.99 asks. The order is sized at the touch ($50 / 0.21 = 238 shares) but
    # only the 20 with edge fill; the rest is not traded, as a limit order would leave it
    p = RB.TakerParams(min_edge=0.05, stake_per_edge=1000, max_stake=50, cost=0.01, fill="book")
    m = RB._Market([_stage(fair=0.30, price=0.14, **THIN)], p)
    m.step(0)
    (tr,) = m.trades
    assert tr["side"] == "YES" and tr["shares"] == pytest.approx(20) and tr["price"] == pytest.approx(0.20)


def test_book_walk_sells_no_lower_than_the_margin_under_fair():
    # long 100 YES, the fair falls to 0.10: sell down the bids only to fair - min_edge (0.05), not into 0.01
    p = RB.TakerParams(min_edge=0.05, stake_per_edge=1000, max_stake=50, cost=0.01, fill="book")
    m = RB._Market([_stage(fair=0.10, price=0.14, **THIN)], p)
    m.yes = 100.0
    m.step(0)
    sells = [t for t in m.trades if t["side"] == "YES"]
    assert len(sells) == 1 and sells[0]["shares"] == pytest.approx(-50) and sells[0]["price"] == pytest.approx(0.08)
    assert m.yes == pytest.approx(50)


def test_within_applies_the_fee_to_the_bar():
    asks = [(0.40, 10.0), (0.44, 10.0)]
    assert RB._within(asks, 0.50, 0.05, 0.0, True) == asks
    assert RB._within(asks, 0.50, 0.05, 0.07, True) == [(0.40, 10.0)]           # 0.44 + 0.017 fee leaves 0.043
