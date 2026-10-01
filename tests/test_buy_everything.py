"""The debug "buy one of everything" strategy (markets/strategies/buy_everything.py) and its switch in the replays."""

from datetime import timedelta

import pandas as pd
import pytest

from racinglines.markets import settlement_rules as SR
from racinglines.markets.strategies import buy_everything as BA
from racinglines.markets.strategies import taker_weekend as RB
from racinglines.markets import venue_replay as VR
from racinglines.pipelines import position_replay as P

T0 = pd.Timestamp("2026-09-26 18:00")


def _st(price, i=0, **kw):
    return dict(dict(label=f"s{i}", t=T0 + timedelta(hours=i), fair=None, price=price, tradeable=False), **kw)


@pytest.mark.quick
def test_switch_is_off_by_default(monkeypatch):
    monkeypatch.delenv(BA.ENV, raising=False)
    assert not BA.enabled() and BA.enabled(True) and not BA.enabled(False)
    monkeypatch.setenv(BA.ENV, "1")
    assert BA.enabled() and not BA.enabled(False)
    monkeypatch.setenv(BA.ENV, "0")
    assert not BA.enabled()


@pytest.mark.quick
def test_buys_one_yes_and_one_no_at_the_first_open_priced_stage_with_no_filters():
    markets = [
        dict(key="a", kind="race_win", subject="A", outcome=True,               # unpriced, then closed, then priced
             stages=[_st(None, 0), _st(0.2, 1, open=False), _st(0.30, 2), _st(0.9, 3)]),
        dict(key="b", kind="race_win", subject="B", outcome=False, stages=[_st(0.001, 0)]),   # a long shot, no fair
        dict(key="c", kind="race_win", subject="C", outcome=False, stages=[_st(0.0, 0), _st(1.0, 1)]),  # never inside
        dict(key="d", kind="race_top5", subject="D", outcome=None, stages=[_st(0.5, 0)]),     # unresolved
    ]
    tr, per = BA.run_weekend(markets, cost=0.01)
    a = tr[tr["key"] == "a"].set_index("side")
    assert list(a.index) == ["YES", "NO"] and set(a["stage"]) == {"s2"} and (a["shares"] == 1).all()
    assert a.loc["YES", "price"] == pytest.approx(0.31) and a.loc["NO", "price"] == pytest.approx(0.71)
    assert a.loc["YES", "pnl"] == pytest.approx(0.69) and a.loc["NO", "pnl"] == pytest.approx(-0.71)
    p = per.set_index("key")
    assert p.loc["a", "pnl"] == pytest.approx(-0.02)                 # a pair loses exactly its costs
    assert p.loc["b", "trades"] == 2 and p.loc["b", "pnl"] == pytest.approx(-0.02)
    assert p.loc["c", "trades"] == 0 and p.loc["c", "pnl"] == 0
    assert p.loc["d", "trades"] == 2 and pd.isna(p.loc["d", "pnl"])
    s = RB.summarize(tr, per)
    assert s["traded"] == 3 and s["trades"] == 6 and s["pnl"] == pytest.approx(-0.04)


@pytest.mark.quick
def test_fees_book_depth_and_cancelled_races():
    one = [dict(key="k", kind="race_win", subject="K", outcome=True, stages=[_st(0.5, 0)])]
    tr, per = BA.run_weekend(one, cost=0.0, taker_fee=0.07)          # Kalshi: ceil(0.07 x 0.25 x 100) = 2 cents a side
    assert per["pnl"].iloc[0] == pytest.approx(-0.04)
    thin = [dict(key="k", kind="race_win", subject="K", outcome=True, stages=[_st(0.5, 0, depth_yes=3.0, depth_no=0.0)])]
    tr, _ = BA.run_weekend(thin)
    assert list(tr["side"]) == ["YES"]                               # no size at the NO side's touch
    assert BA.run_market([_st(0.4)], SR.VOID)["pnl"] == 0.0
    assert BA.run_market([_st(0.4)], SR.FAIR)["pnl"] is None
    assert BA.run_market([_st(0.4)], 0.5)["pnl"] == pytest.approx(-0.02)


def _venue(prices, volume):
    v = VR.Kalshi.__new__(VR.Kalshi)
    v.links = pd.DataFrame(dict(token_id=list(prices), prediction="race_win"))
    v.prices = {k: pd.DataFrame(dict(ts=[T0 - timedelta(minutes=30)], price=[p])) for k, p in prices.items()}
    v.trades = {k: pd.DataFrame(dict(ts=[T0 - timedelta(hours=1)], usd=[volume])) for k in prices}
    v.stale, v.coherence_tol, v.group_target = timedelta(hours=6), 0.25, {"race_win": 1}
    return v


@pytest.mark.quick
def test_the_replay_buys_markets_the_taker_may_not_touch():
    """Thin, incoherent and unmodelled markets are untradeable for the taker, bought by buy_all; a closed one is not."""
    links = pd.DataFrame(dict(token_id=["a", "b", "c"], prediction="race_win", athlete_id=[1, 2, 3], params=[{}] * 3,
                              athlete=["A", "B", "C"], group_title=None,
                              end_date=[None, None, pd.Timestamp("2026-09-26 12:00", tz="UTC")]))
    res = pd.DataFrame(dict(athlete_id=[1, 2, 3], position=[1, 2, 3], status="OK"))
    v = _venue({"a": 0.9, "b": 0.9, "c": 0.9}, volume=1.0)          # $1 traded, sums to 2.7
    mk = P.race_markets(v, links, None, res, [("race eve", T0)])
    assert not any(s["tradeable"] for m in mk for s in m["stages"])
    assert RB.run_weekend(mk, RB.TakerParams())[0].empty
    tr, per = BA.run_weekend(mk)
    assert sorted(set(tr["key"])) == ["a", "b"] and len(tr) == 4     # c closed before the stage
    assert P.kalshi_fees(tr) > 0


@pytest.mark.quick
def test_f1_weekend_adds_buy_all_only_when_switched_on(monkeypatch):
    from racinglines.pipelines import weekend_sweep as WS
    from racinglines.testing import synthetic as SY
    markets = SY.weekend_markets(n=6)
    monkeypatch.setattr(WS, "_memo", lambda key, make: make())
    monkeypatch.setattr(WS, "weekend_markets", lambda *a, **k: [dict(m) for m in markets])
    w = dict(event_key="x", name="X")
    runs = [(s["label"], s["t"], 0) for s in markets[0]["stages"]]
    plist = [RB.TakerParams(mode=m) for m in WS.TAKER_MODES]
    monkeypatch.delenv(BA.ENV, raising=False)
    off = WS.weekend(None, w, runs, plist, echo=lambda *a: None)
    assert set(off["modes"]) == set(WS.TAKER_MODES)
    monkeypatch.setenv(BA.ENV, "1")
    on = WS.weekend(None, w, runs, plist, echo=lambda *a: None)
    assert {k: on["modes"][k] for k in WS.TAKER_MODES} == off["modes"]            # the taker's results are unchanged
    assert on["modes"]["buy_all"]["traded"] == 6 and on["modes"]["buy_all"]["pnl"] == pytest.approx(-6 * 0.02)


@pytest.mark.quick
def test_season_futures_take_the_first_price_found_and_hold_the_pair():
    t = pd.Timestamp("2026-09-01", tz="UTC")
    obs = [(None, 0.3, "sync quote"), (t + timedelta(days=2), 0.05, "trade"), (t, 1.0, "book"), (t + timedelta(days=1), 0.02, "minute price")]
    assert BA.first_price(obs) == (t + timedelta(days=1), 0.02, "minute price")     # 1.0 isn't inside (0, 1)
    assert BA.first_price([(None, 0.3, "sync quote")])[2] == "sync quote"
    assert BA.first_price([(t, 0.0, "book")]) is None
    h = BA.hold_pair(0.02, outcome=None, mark=0.10, cost=0.01, fee=0.02)
    assert h["status"] == "marked" and h["pnl"] == pytest.approx(-0.06) and h["pnl_yes"] == pytest.approx(0.05)
    assert BA.hold_pair(0.02, outcome=True, cost=0.0)["pnl_yes"] == pytest.approx(0.98)
    assert BA.hold_pair(0.5)["status"] == "open"
