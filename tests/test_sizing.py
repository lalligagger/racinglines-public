"""Bankroll-aware sizing and the deployed-capital cap (taker_weekend.TakerParams scale / max_deployed,
weekend_sweep.bankroll_scale, the sweep settings bankroll / max_deployed). Synthetic data only: these
check the mechanics, not whether either rule makes money (that needs live weekends)."""

import pandas as pd
import pytest

from racinglines.markets.strategies import taker_weekend as RB
from racinglines.pipelines import sweep_settings as SS
from racinglines.pipelines import weekend_sweep as W
from racinglines.testing import synthetic as SY

pytestmark = pytest.mark.quick


def deployed_path(trades):
    """Capital deployed across the weekend after each trade, in time order (per market: cash out net of cash in)."""
    cash, path = {}, []
    for tr in trades.sort_values("t", kind="stable").to_dict("records"):
        cash[tr["key"]] = cash.get(tr["key"], 0.0) - tr["shares"] * tr["price"]
        path.append(sum(max(-c, 0.0) for c in cash.values()))
    return path


@pytest.mark.parametrize("mode", ["update", "hold", "last", "early"])
def test_defaults_are_fixed_sizing(mode):
    wk = SY.weekend_markets(40)
    t0, p0 = RB.run_weekend(wk, RB.TakerParams(mode=mode))
    t1, p1 = RB.run_weekend(wk, RB.TakerParams(mode=mode, scale=1.0, max_deployed=None))
    assert t0.equals(t1) and p0.equals(p1)


def test_a_cap_nobody_reaches_changes_nothing():
    wk = SY.weekend_markets(40)
    t0, p0 = RB.run_weekend(wk, RB.TakerParams())
    t1, p1 = RB.run_weekend(wk, RB.TakerParams(max_deployed=1e9))
    pd.testing.assert_frame_equal(p0, p1)
    assert len(t0) == len(t1) and t0["shares"].sum() == pytest.approx(t1["shares"].sum())


def test_scale_multiplies_stakes():
    wk = SY.weekend_markets(40)
    _, p1 = RB.run_weekend(wk, RB.TakerParams(mode="hold", min_trade=0))
    _, p2 = RB.run_weekend(wk, RB.TakerParams(mode="hold", min_trade=0, scale=2.0))
    assert p1["bought"].sum() > 0
    assert p2["bought"].sum() == pytest.approx(2 * p1["bought"].sum())
    assert p2["pnl"].sum() == pytest.approx(2 * p1["pnl"].sum())
    _, p0 = RB.run_weekend(wk, RB.TakerParams(scale=0.0))                # a bust bankroll trades nothing
    assert p0["trades"].sum() == 0


@pytest.mark.parametrize("cap", [10.0, 60.0, 150.0])
def test_cap_holds_at_every_moment(cap):
    wk = SY.weekend_markets(40)
    free_tr, free = RB.run_weekend(wk, RB.TakerParams())
    assert max(deployed_path(free_tr)) > cap                               # the cap binds
    tr, per = RB.run_weekend(wk, RB.TakerParams(max_deployed=cap))
    assert len(tr) and max(deployed_path(tr)) <= cap + 1e-9
    assert per["bought"].sum() < free["bought"].sum()


def test_cap_fills_in_time_order():
    """Two markets want $25 each; the one whose stage comes first gets the room."""
    def mk(key, t):
        return dict(key=key, kind="race_win", subject=key, outcome=True,
                    stages=[dict(label="after FP1", t=pd.Timestamp(t), fair=0.40, price=0.30, tradeable=True)])
    wk = [mk("late", "2026-10-02 12:00"), mk("early", "2026-10-02 08:00")]
    tr, per = RB.run_weekend(wk, RB.TakerParams(max_deployed=30.0))
    got = per.set_index("key")["bought"]
    assert got["early"] == pytest.approx(25.0) and got["late"] == pytest.approx(5.0)
    tr, per = RB.run_weekend(wk, RB.TakerParams(max_deployed=26.0))        # $1 left: under min_trade, skipped
    assert per.set_index("key")["trades"].to_dict() == {"late": 0, "early": 1}


def test_bankroll_scale():
    assert W.bankroll_scale(1000, 1000) == 1.0
    assert W.bankroll_scale(1000, 1500) == 1.5
    assert W.bankroll_scale(1000, -50) == 0.0


def test_settings_unset_by_default_and_keys_unchanged():
    d = SS.Settings.from_dict()
    assert d["bankroll"] is None and d["max_deployed"] is None
    s = SS.Settings.from_dict(dict(bankroll=1000, max_deployed=200))
    assert s.model_key == d.model_key and s.key != d.key                 # sizing doesn't change prices
    assert SS.Settings.from_dict(dict(bankroll="", max_deployed="")).key == d.key
    assert s.argv() == ["--bankroll", "1000.0", "--max-deployed", "200.0"]


# --- Kelly sizing (sizing.target_shares kelly / balance, TakerParams kelly / bankroll, the `kelly` setting) ----------

def test_kelly_stake_is_the_kelly_fraction_of_the_balance():
    from racinglines.markets.strategies.sizing import target_shares
    # YES at 0.20 (+0.01 cost) with fair 0.40: f* = (0.40 - 0.21) / 0.79; half Kelly on $10,000, under a $5,000 cap
    y, n = target_shares(0.40, 0.20, 0.01, 0.10, 250.0, 5000.0, kelly=0.5, balance=10_000.0)
    assert n == 0.0 and y * 0.21 == pytest.approx(0.5 * (0.19 / 0.79) * 10_000.0)
    # NO: fair 0.30 against 0.60 buys NO at 0.41 with q = 0.70
    y, n = target_shares(0.30, 0.60, 0.01, 0.10, 250.0, 5000.0, kelly=0.5, balance=10_000.0)
    assert y == 0.0 and n * 0.41 == pytest.approx(0.5 * (0.29 / 0.59) * 10_000.0)


def test_kelly_respects_the_cap_the_edge_threshold_and_a_cost_that_eats_the_edge():
    from racinglines.markets.strategies.sizing import target_shares
    assert target_shares(0.40, 0.20, 0.01, 0.10, 250.0, 500.0, kelly=0.5, balance=10_000.0)[0] * 0.21 == \
        pytest.approx(500.0)
    assert target_shares(0.25, 0.20, 0.01, 0.10, 250.0, 500.0, kelly=0.5, balance=10_000.0) == (0.0, 0.0)
    assert target_shares(0.32, 0.20, 0.13, 0.10, 250.0, 500.0, kelly=0.5, balance=10_000.0) == (0.0, 0.0)


def test_without_kelly_sizing_is_unchanged():
    from racinglines.markets.strategies.sizing import target_shares
    assert target_shares(0.40, 0.20, 0.01, 0.10, 250.0, 50.0) == \
        target_shares(0.40, 0.20, 0.01, 0.10, 250.0, 50.0, kelly=None, balance=10_000.0)
    wk = SY.weekend_markets(40)
    t0, p0 = RB.run_weekend(wk, RB.TakerParams())
    t1, p1 = RB.run_weekend(wk, RB.TakerParams(kelly=None, bankroll=10_000.0))
    assert t0.equals(t1) and p0.equals(p1)


def test_kelly_stakes_follow_the_rolling_balance():
    wk = SY.weekend_markets(40)
    big = dict(kelly=0.5, bankroll=10_000.0, max_stake=500.0)
    t_full, _ = RB.run_weekend(wk, RB.TakerParams(**big))
    t_half, _ = RB.run_weekend(wk, RB.TakerParams(scale=0.5, **big))
    assert len(t_full) and (t_full["shares"] * t_full["price"]).abs().sum() > \
        (t_half["shares"] * t_half["price"]).abs().sum()


def test_kelly_setting_is_unset_by_default_and_out_of_the_keys():
    st = SS.Settings.from_dict({})
    assert st["kelly"] is None and st.key == SS.Settings.from_dict({"kelly": None}).key
    assert SS.Settings.from_dict({"kelly": 0.5, "bankroll": 10_000}).key != st.key
