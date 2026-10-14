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
