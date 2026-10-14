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


# --- square-root staking (the bankroll_growth setting: weekend_sweep.bankroll_scale growth "sqrt") ----------------

def test_sqrt_scale_grows_sub_linearly_and_falls_gently():
    assert W.bankroll_scale(1000, 1000, "sqrt") == 1.0
    assert W.bankroll_scale(1000, 4000, "sqrt") == pytest.approx(2.0)      # 4x the bankroll: 2x the stakes
    assert W.bankroll_scale(1000, 250, "sqrt") == pytest.approx(0.5)       # down 75%: stakes halve, not quarter
    assert W.bankroll_scale(1000, -50, "sqrt") == 0.0                      # bust: no more trading
    for b in (100, 500, 2000, 9000):                                        # under linear above the start, over below
        lin, sq = W.bankroll_scale(1000, b), W.bankroll_scale(1000, b, "sqrt")
        assert (sq < lin) if b > 1000 else (sq > lin)
    assert W.bankroll_scale(1000, 1500, None) == W.bankroll_scale(1000, 1500, "linear") == 1.5


def test_bankroll_growth_setting_is_out_of_the_keys_until_sqrt():
    d = SS.Settings.from_dict()
    assert d["bankroll_growth"] is None
    assert SS.Settings.from_dict(dict(bankroll_growth="linear")).key == d.key        # "linear" = unset
    s = SS.Settings.from_dict(dict(bankroll=1000, bankroll_growth="sqrt"))
    assert s.model_key == d.model_key and s.argv() == ["--bankroll", "1000.0", "--bankroll-growth", "sqrt"]
    with pytest.raises(ValueError):
        SS.Settings.from_dict(dict(bankroll_growth="log"))


def _season(growth, pnls):
    """weekend_sweep.season over len(pnls) fake events with a fixed P&L each; returns the scale each event was sized at."""
    seen = []
    p = RB.TakerParams(mode="update")

    def trade_event(ev, plist, widen):
        seen.append(plist[0].scale)
        return dict(modes={"update": dict(pnl=pnls[ev["round"] - 1])}, markout_by_kind={}, makers={}, markets=1,
                    tradeable_first=1, tradeable_last=1, trades={"update": pd.DataFrame()}, scores=[], calib=[])
    events = [dict(round=i + 1, event_key=f"e{i}", event=f"E{i}", format="std", stages=1, last_run_id=None)
              for i in range(len(pnls))]
    st = SS.Settings.from_dict(dict(bankroll=1000, bankroll_growth=growth))
    out = W.season(events, trade_event, st, [p], echo=lambda *a: None)
    return seen, out["weekends"]["update_balance"].tolist()


def test_season_sizes_each_event_on_the_rolling_balance_by_the_growth_rule():
    pnls = [3000.0, -3750.0, 0.0]                 # 1000 -> 4000 -> 250 -> 250
    lin, bal = _season("linear", pnls)
    sq, bal_sq = _season("sqrt", pnls)
    assert bal == bal_sq == [4000.0, 250.0, 250.0]
    assert lin == pytest.approx([1.0, 4.0, 0.25]) and sq == pytest.approx([1.0, 2.0, 0.5])


def test_bankroll_growth_reaches_the_lab_form_mcp_and_every_sport():
    from racinglines.pipelines import season_sweep as SW
    from racinglines.web import jobs
    assert jobs.parse_sweep_settings({"bankroll": "1000", "bankroll_growth": "sqrt"}) == \
        dict(bankroll=1000.0, bankroll_growth="sqrt")
    for sport in ("nascar", "motogp"):
        assert "bankroll_growth" in SW.settings_class(sport).BY
    from racinglines.mcp import tools as T
    listed = {s["name"]: s for s in T.list_job_types()["sweep_settings"]}      # MCP and `racinglines remote job`
    assert listed["bankroll_growth"]["choices"] == ["linear", "sqrt"]
    assert listed["root_unit"]["type"] == "float"
    assert jobs.parse_sweep_settings({"root_unit": "20"}) == dict(root_unit=20.0)
    for sport in ("nascar", "motogp"):
        assert "root_unit" in SW.settings_class(sport).BY


# --- the root unit system (the root_unit setting: stake = unit x sqrt(c / (1 - c)), sizing.target_shares) ----------

def test_root_unit_stake_is_the_unit_over_the_root_of_the_odds():
    from racinglines.markets.strategies.sizing import target_shares
    def cost(y):                                                          # stake = shares x cost per share
        return y[0] * c if y[0] else y[1] * c
    for price, fair, units in ((0.50, 0.60, 1.0), (0.20, 0.30, 0.5), (0.80, 0.90, 2.0)):   # evens, 4/1, 1/4
        c = price
        y = target_shares(fair, price, 0.0, 0.05, 250.0, 500.0, root_unit=20.0)
        assert cost(y) == pytest.approx(20.0 * units)
    c = 1 - 0.80                                                          # NO at 0.20 (fair 0.70 vs 0.80): 4/1
    y = target_shares(0.70, 0.80, 0.0, 0.05, 250.0, 500.0, root_unit=20.0)
    assert y[0] == 0.0 and cost(y) == pytest.approx(10.0)
    assert target_shares(0.52, 0.50, 0.0, 0.05, 250.0, 500.0, root_unit=20.0) == (0.0, 0.0)   # under min edge
    c = 0.8
    assert cost(target_shares(0.90, 0.80, 0.0, 0.05, 250.0, 30.0, root_unit=20.0)) == pytest.approx(30.0)   # capped


def test_root_unit_is_off_by_default_out_of_the_keys_and_not_with_kelly():
    d = SS.Settings.from_dict()
    assert d["root_unit"] is None
    wk = SY.weekend_markets(40)
    t0, p0 = RB.run_weekend(wk, RB.TakerParams())
    t1, p1 = RB.run_weekend(wk, RB.TakerParams(root_unit=None))
    assert t0.equals(t1) and p0.equals(p1)
    s = SS.Settings.from_dict(dict(root_unit=20))
    assert s.model_key == d.model_key and s.key != d.key and s.argv() == ["--root-unit", "20.0"]
    base, plist = W.taker_params(s)
    assert base.root_unit == 20.0 and all(q.root_unit == 20.0 for q in plist)
    with pytest.raises(ValueError, match="kelly or root_unit"):
        W.taker_params(SS.Settings.from_dict(dict(root_unit=20, kelly=0.5, bankroll=1000)))


def test_root_unit_stakes_follow_the_bankroll_scale():
    wk = SY.weekend_markets(40)
    t_full, _ = RB.run_weekend(wk, RB.TakerParams(root_unit=20.0))
    t_half, _ = RB.run_weekend(wk, RB.TakerParams(root_unit=20.0, scale=0.5))
    assert len(t_full) and (t_full["shares"] * t_full["price"]).abs().sum() > \
        (t_half["shares"] * t_half["price"]).abs().sum()
