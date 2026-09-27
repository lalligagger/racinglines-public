"""Season-long strategy replay (racinglines/markets/strategies/season.py): synthetic markets, no database."""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from racinglines.markets.strategies import season as SS

T0 = pd.Timestamp("2026-03-01", tz="UTC")
P = SS.SeasonParams(min_edge=0.05, stake_per_edge=100, max_stake=50, capital=1000, min_trade=0.0,
                    exec_delay=timedelta(hours=1))


def mk(key="a", prices=((0, 0.30),), cost=0.01, outcome=None, closed_h=None):
    ts = np.array([T0 + timedelta(hours=h) for h, _ in prices])
    return SS.SeasonMarket(key=key, kind="champion", subject=key, ts=ts, px=np.array([p for _, p in prices], float),
                           cost=cost, outcome=outcome, closed_at=T0 + timedelta(hours=closed_h) if closed_h else None)


def dec(h, fairs, label="d"):
    return dict(t=T0 + timedelta(hours=h), label=label, fairs=fairs)


def test_executes_at_the_price_after_the_delay_plus_cost():
    m = mk(prices=((0, 0.30), (1, 0.32), (5, 0.50)))
    r = SS.replay({"a": m}, [dec(0, {"a": 0.40})], P, now=T0 + timedelta(hours=2))
    (t,) = r["trades"].to_dict("records")
    assert t["mid"] == 0.32 and t["price"] == pytest.approx(0.33)      # price 1 h after the decision, + 1c
    assert t["shares"] == pytest.approx(8 / 0.33)                       # 8 pt edge -> $8


def test_no_future_prices_used_at_decision():
    m = mk(prices=((0, 0.30), (3, 0.90)))
    r = SS.replay({"a": m}, [dec(0, {"a": 0.40})], P, now=T0 + timedelta(hours=10))
    assert r["trades"]["mid"].iloc[0] == 0.30


def test_settles_at_close_and_liquidation_value_for_open():
    won = mk("w", prices=((0, 0.30),), outcome=True, closed_h=48)
    live = mk("o", prices=((0, 0.30), (24, 0.50)))
    r = SS.replay({"w": won, "o": live}, [dec(0, {"w": 0.40, "o": 0.40})], P, now=T0 + timedelta(hours=72),
                  marks=[T0 + timedelta(hours=72)])
    pos = r["positions"].set_index("key")
    sh_w = 10 / 0.31
    assert pos.loc["w", "pnl"] == pytest.approx(sh_w * 1.0 - 10)
    assert pos.loc["o", "value"] == pytest.approx(10 / 0.31 * (0.50 - 0.01))   # sold at price - cost
    assert r["summary"]["pnl"] == pytest.approx(pos["pnl"].sum())


def test_stale_and_extreme_prices_not_traded():
    stale = mk("s", prices=((-100, 0.30),))
    extreme = mk("x", prices=((0, 0.995),))
    r = SS.replay({"s": stale, "x": extreme}, [dec(0, {"s": 0.9, "x": 0.5})], P, now=T0 + timedelta(hours=2))
    assert len(r["trades"]) == 0


def test_capital_cap_scales_positions():
    mks = {k: mk(k, prices=((0, 0.10),)) for k in "abcdef"}
    p = SS.SeasonParams(**{**P.__dict__, "capital": 100})
    r = SS.replay(mks, [dec(0, {k: 0.90 for k in mks})], p, now=T0 + timedelta(hours=2))
    assert r["summary"]["capital_used"] == pytest.approx(100, rel=1e-6)


def test_hold_mode_trades_once():
    m = mk(prices=((0, 0.30), (30, 0.30)))
    p = SS.SeasonParams(**{**P.__dict__, "mode": "hold"})
    r = SS.replay({"a": m}, [dec(0, {"a": 0.40}), dec(29, {"a": 0.20})], p, now=T0 + timedelta(hours=40))
    assert set(r["trades"]["decision"]) == {"d"} and len(r["trades"]) == 1


def test_can_close_a_position_below_the_price_band():
    """A long shot that collapses below 1c can still be sold (only opening is blocked there)."""
    m = mk(prices=((0, 0.06), (30, 0.004)))
    r = SS.replay({"a": m}, [dec(0, {"a": 0.20}), dec(29, {"a": 0.0})], P, now=T0 + timedelta(hours=40))
    sides = r["trades"]["shares"].tolist()
    assert sides[0] > 0 and sides[1] < 0 and r["positions"].empty or (r["positions"]["shares"] == 0).all()
