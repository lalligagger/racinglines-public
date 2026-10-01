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


# --- checkpoints (racinglines/pipelines/season_checkpoints.py) ---

def test_drift_measures_the_move_toward_our_fair():
    from racinglines.pipelines import season_checkpoints as SC
    toward = mk("t", prices=((0, 0.30), (48, 0.36)))            # fair 0.40: market closed 6 of 10 points
    away = mk("a", prices=((0, 0.50), (48, 0.55)))              # fair 0.40: market moved 5 points away
    d = dec(0, {"t": 0.40, "a": 0.40})
    r = SC.drift({"t": toward, "a": away}, d, T0, T0 + timedelta(hours=48), P)
    assert r["edged"] == 2 and r["hit"] == 0.5
    assert r["drift"] == pytest.approx((6 - 5) / 2)
    assert r["slope"] == pytest.approx((0.1 * 0.06 + -0.1 * 0.05) / (0.1 ** 2 + 0.1 ** 2))


def test_drift_uses_the_settlement_and_skips_closed_markets():
    from racinglines.pipelines import season_checkpoints as SC
    settled = mk("s", prices=((0, 0.30),), outcome=False, closed_h=24)
    gone = mk("g", prices=((0, 0.30),), outcome=False, closed_h=-1)
    r = SC.drift({"s": settled, "g": gone}, dec(0, {"s": 0.10, "g": 0.10}), T0, T0 + timedelta(hours=48), P)
    assert r["markets"] == 1 and r["drift"] == pytest.approx(30.0) and r["hit"] == 1.0


def test_checkpoint_tranches_hold_and_score_fixed_windows():
    from racinglines.pipelines import season_checkpoints as SC
    m = mk("a", prices=tuple((24 * d, 0.30 if d < 10 else 0.40 if d < 20 else 0.50) for d in range(31)))
    decisions = [dec(24 * i, {"a": 0.45}, label=f"d{i}") for i in range(8)]
    times = [(d["label"], d["t"]) for d in decisions]
    now = T0 + timedelta(days=30)
    df = SC.score({"a": m}, decisions, times, P, entries=(0, 3, 6), window=3, now=now)
    # entries 0 and 3 have a full 3-decision window; entry 6 only "to date"
    assert df.groupby("entry")["window"].apply(list).to_dict() == {
        "d0": ["next 3 GPs", "to date"], "d3": ["next 3 GPs", "to date"], "d6": ["to date"]}
    first = df[(df["entry"] == "d0") & (df["window"] == "next 3 GPs")].iloc[0]
    assert first["end"] == T0 + timedelta(days=3, hours=1) and first["pnl"] < 0   # held, marked at price - cost
    assert (df.loc[df["window"] == "to date", "pnl"] > 0).all()                    # the market came to 0.50
    assert df["bought"].max() <= P.capital / 3 + 1e-9                               # a third of the capital each
