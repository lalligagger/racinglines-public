"""Unit tests for the maker replay (racinglines/markets/strategies/maker_replay.py) on synthetic tapes: no database."""

from dataclasses import replace

import numpy as np
import pytest

from racinglines.markets.strategies import maker_replay as R

MIN = int(60e9)
HOUR = 60 * MIN


def market(cond="c1", fair=0.5, mids=((0, 0.5),), trades=(), outcome=True, kind="race_win", run_id=1):
    """trades: (t_ns, yes_price, size, taker_bought_yes)"""
    tr = np.array(trades, dtype=float).reshape(-1, 4)
    return R.Market(cond=cond, kind=kind, subject=cond, question=cond, fairs={run_id: fair}, outcome=outcome,
                    mid_ts=np.array([m[0] for m in mids], dtype="int64"), mid_px=np.array([m[1] for m in mids], float),
                    tr_ts=tr[:, 0].astype("int64"), tr_px=tr[:, 1], tr_sz=tr[:, 2], tr_buy=tr[:, 3].astype(bool))


def liquid(t0=-24 * HOUR):
    """Background volume so the 'thin' filter doesn't skip: $600 traded a day earlier."""
    return [(t0 + 1, 0.5, 1000, 1), (t0 + 2, 0.5, 200, 0)]


def data(*mks, start=0, end=2 * HOUR, run_id=1, session_end=True):
    return dict(markets=list(mks), stages=[dict(run_id=run_id, start=start, end=end, session_end=session_end)])


P = R.Params(pull_min=0, min_volume_24h=0)


# --- what the maker can see ------------------------------------------------

def test_public_view_excludes_future():
    mk = market(mids=[(0, 0.4), (10 * MIN, 0.9)], trades=[(5 * MIN, 0.4, 10, 1), (20 * MIN, 0.9, 10, 1)])
    v = R.PublicView(mk, 5 * MIN)
    assert v.mid() == 0.4 and len(v.tr_ts) == 1


def test_quote_ignores_everything_after_t():
    """Changing the tape after t can't change the quote at t."""
    base = dict(fair=0.5, mids=[(0, 0.5)], trades=liquid(0) + [(HOUR, 0.5, 10, 1)])
    a = market(**base)
    b = market(fair=0.5, mids=[(0, 0.5), (HOUR, 0.99)], trades=liquid(0) + [(HOUR, 0.99, 1e6, 1)])
    t = 30 * MIN
    assert R.quote(0.5, R.PublicView(a, t), 0, P) == R.quote(0.5, R.PublicView(b, t), 0, P)


def test_stages_use_each_runs_fair_only_after_its_cutoff():
    runs = [dict(run_id=11, cutoff=0), dict(run_id=12, cutoff=5 * HOUR)]
    st = R.stages_for(runs, sessions=[3 * HOUR, 10 * HOUR])
    assert st == [dict(run_id=11, start=0, end=3 * HOUR, session_end=True),
                  dict(run_id=12, start=5 * HOUR, end=10 * HOUR, session_end=True)]
    # a run whose cutoff is after the last session prices nothing
    assert R.stages_for([dict(run_id=1, cutoff=11 * HOUR)], [10 * HOUR]) == []


# --- quoting rules ----------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_quotes_never_cross_and_yes_plus_no_below_one(seed):
    rng = np.random.default_rng(seed)
    for _ in range(50):
        fair, mid, inv = rng.uniform(0.05, 0.95), rng.uniform(0.04, 0.96), rng.uniform(-240, 240)
        mk = market(fair=fair, mids=[(0, mid)])
        bid, ask, _ = R.quote(fair, R.PublicView(mk, 1), inv, replace(P, max_disagree=None))
        if bid is not None:
            assert bid < mid + 1e-9                      # post-only: doesn't take the market
        if ask is not None:
            assert ask > mid - 1e-9
        if bid is not None and ask is not None:
            assert bid + (1 - ask) < 1                   # YES bid + NO bid < $1
            assert ask - bid >= 2 * P.half_spread - P.tick - 1e-9


def test_skew_moves_quotes_against_inventory():
    mk = market(mids=[(0, 0.5)])
    p = replace(P, half_spread=0.04)
    flat = R.quote(0.5, R.PublicView(mk, 1), 0, p)
    long_ = R.quote(0.5, R.PublicView(mk, 1), 200, p)
    assert long_[1] < flat[1]            # long YES -> cheaper ask to sell it down


@pytest.mark.parametrize("mid,fair,why", [(0.01, 0.02, "outside price band"), (0.99, 0.98, "outside price band"),
                                          (0.60, 0.30, "disagree")])
def test_skips(mid, fair, why):
    mk = market(fair=fair, mids=[(0, mid)])
    assert R.quote(fair, R.PublicView(mk, 1), 0, P)[2] == why


def test_thin_market_skipped():
    mk = market(mids=[(0, 0.5)], trades=[(-HOUR, 0.5, 10, 1)])       # $5 in 24 h
    assert R.quote(0.5, R.PublicView(mk, 0), 0, R.Params())[2] == "thin"


# --- fills --------------------------------------------------------------------

def test_fill_needs_a_trade_after_the_quote():
    # quote placed at t=0 at bid 0.48; a sell at exactly t=0 was before we were there
    mk = market(trades=[(0, 0.40, 10, 0), (MIN, 0.40, 10, 0)])
    f = R.replay(data(mk), P)["fills"]
    assert len(f) == 1 and f["ts"].iloc[0] == MIN and f["price"].iloc[0] == 0.48 and f["side"].iloc[0] == "buy"


def test_touch_vs_through():
    mk = market(trades=[(MIN, 0.48, 10, 0)])                       # trades exactly at our bid
    assert len(R.replay(data(mk), replace(P, fill="touch"))["fills"]) == 1
    assert len(R.replay(data(mk), replace(P, fill="through"))["fills"]) == 0


def test_taker_buy_fills_our_ask_not_our_bid():
    mk = market(trades=[(MIN, 0.60, 10, 1)])
    f = R.replay(data(mk), P)["fills"]
    assert list(f["side"]) == ["sell"] and f["price"].iloc[0] == 0.52


def test_fill_size_capped_by_trade_quote_and_limits():
    mk = market(trades=[(MIN, 0.40, 30, 0), (2 * MIN, 0.40, 1000, 0)])
    f = R.replay(data(mk, end=4 * MIN), replace(P, size=50, step_min=60))["fills"]
    assert list(f["qty"]) == [30, 20]                              # one quote of 50 per step
    many = [(k * MIN, 0.40, 1000, 0) for k in range(1, 120)]
    res = R.replay(data(market(trades=many)), replace(P, size=50, max_pos=120, step_min=1))
    assert res["positions"]["inventory"].max() <= 120


def test_capital_limit_never_exceeded():
    rng = np.random.default_rng(0)
    mks = []
    for i in range(10):
        tr = [(int(t), float(px), float(sz), int(b)) for t, px, sz, b in
              zip(np.sort(rng.integers(1, 2 * HOUR, 200)), rng.uniform(0.3, 0.7, 200), rng.uniform(1, 80, 200),
                  rng.integers(0, 2, 200))]
        mks.append(market(cond=f"c{i}", fair=rng.uniform(0.35, 0.65), trades=tr, outcome=bool(i % 2)))
    p = replace(P, max_capital=150, max_disagree=None, fill="touch", step_min=1)
    res = R.replay(data(*mks), p)
    assert -res["positions"]["worst_case"].clip(upper=0).sum() <= 150 + 1e-6
    assert len(res["fills"]) > 0


def test_quotes_pulled_before_session():
    mk = market(trades=[(k * MIN, 0.40, 10, 0) for k in range(1, 120)])
    f = R.replay(data(mk, end=2 * HOUR), replace(P, pull_min=15))["fills"]
    assert f["ts"].max() < 2 * HOUR - 15 * MIN + 5 * MIN     # last quote placed before the pull, filled within its step
    assert R.replay(data(mk, end=2 * HOUR), replace(P, pull_min=15))["quotes"]["ts"].max() < 2 * HOUR - 15 * MIN


def test_no_token_trades_map_to_yes():
    px, buy = R.to_yes(np.array([0, 1, 1]), np.array(["BUY", "BUY", "SELL"]), np.array([0.3, 0.3, 0.3]))
    assert np.allclose(px, [0.3, 0.7, 0.7]) and list(buy) == [True, False, True]


# --- accounting -------------------------------------------------------------

def test_pnl_identity_and_resolution():
    mk = market(trades=[(MIN, 0.40, 10, 0), (2 * MIN, 0.60, 4, 1)], outcome=True)
    res = R.replay(data(mk), P)
    f, pos = res["fills"], res["positions"].iloc[0]
    assert pos["inventory"] == 6
    assert pos["pnl"] == pytest.approx(10 * (1 - 0.48) - 4 * (1 - 0.52))
    assert f["pnl"].sum() == pytest.approx(pos["pnl"])             # per-fill P&L adds up to the position
    assert R.summary(res).loc["total", "pnl"] == pytest.approx(pos["pnl"])


def test_deterministic():
    mk = market(trades=[(k * MIN, 0.4 + 0.2 * (k % 2), 7, k % 2) for k in range(1, 60)])
    a, b = R.replay(data(mk), P), R.replay(data(mk), P)
    assert a["fills"].equals(b["fills"])


# --- options (F1-4): flatten before qualifying, info-timed skew, per-kind spreads --

def test_flatten_before_qualifying_closes_inventory_at_market():
    """Filled on the bid, then flattened at the pull before qualifying (mid - taker cost)."""
    mk = market(fair=0.6, mids=[(0, 0.55)], trades=liquid() + [(10 * MIN, 0.50, 40, 0)])
    d = dict(data(mk), qual_start=2 * HOUR)
    p = replace(P, flatten_before_qual=True, taker_cost=0.01)
    res = R.replay(d, p)
    f = res["fills"]
    assert list(f["side"]) == ["buy", "sell"]
    assert f["price"].iloc[1] == pytest.approx(0.54)                  # mid 0.55 - 1c
    assert res["positions"]["inventory"].iloc[0] == 0
    # without the option the position is held to the result
    assert R.replay(d, P)["positions"]["inventory"].iloc[0] == pytest.approx(40)


def test_flatten_only_before_qualifying():
    mk = market(fair=0.6, mids=[(0, 0.55)], trades=liquid() + [(10 * MIN, 0.50, 40, 0)])
    d = dict(data(mk), qual_start=9 * HOUR)                           # this stage ends at another session
    assert R.replay(d, replace(P, flatten_before_qual=True))["positions"]["inventory"].iloc[0] == pytest.approx(40)


def test_info_skew_grows_toward_the_session():
    """Long 40 after an early fill: far from the session the quotes match the plain maker;
    close to it they sit lower (skewed harder to shed the inventory)."""
    mk = market(fair=0.5, mids=[(0, 0.5)], trades=liquid() + [(1 * MIN, 0.40, 40, 0)])
    d = data(mk, end=6 * HOUR)
    base = replace(P, half_spread=0.04, tick=0.001)
    plain = R.replay(d, base)["quotes"].dropna(subset=["bid"]).set_index("ts")["bid"]
    timed = R.replay(d, replace(base, info_skew=3.0, info_tau_h=1.0))["quotes"].dropna(subset=["bid"]).set_index("ts")["bid"]
    assert timed.iloc[1] == pytest.approx(plain.iloc[1], abs=0.001)     # 5 min in: session far away
    assert timed.iloc[-1] < plain.iloc[-1] - 0.01                        # just before the session


def test_per_kind_half_spread():
    mk = market(fair=0.5, mids=[(0, 0.5)], trades=liquid(0), kind="race_podium")
    q = R.replay(data(mk), replace(P, half_spread_by_kind={"race_podium": 0.06}))["quotes"].dropna(subset=["bid"])
    assert (q["bid"] <= 0.44 + 1e-9).all()
    q0 = R.replay(data(mk), P)["quotes"].dropna(subset=["bid"])
    assert (q0["bid"] >= 0.47).all()


def test_weekend_with_no_markets_summarises_to_zero():
    """A sweep filtered to kinds a weekend doesn't list (h2h-only on 2025 rounds 1-7) used to raise KeyError 'cond'."""
    res = R.replay(data(), R.Params())
    s = R.summary(res)
    assert list(s.index) == ["total"] and s.loc["total", "markets"] == 0 and s.loc["total", "pnl"] == 0.0
    assert res["positions"].empty and "cond" in res["positions"].columns
