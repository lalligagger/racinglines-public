"""The synthetic taker pool (markets/synthetic_takers.py) on synthetic tapes: no database."""

import numpy as np
import pytest

from racinglines.markets import synthetic_takers as ST
from racinglines.markets.strategies import maker_replay as R

pytestmark = pytest.mark.quick
HOUR = ST.HOUR
MIN = int(60e9)


def market(cond="T1", kind="race_win", hours=48, rate=4.0, drift=0.0, seed=1):
    """A recorded market: a minute mid path (random walk + drift) and Poisson trades printing near it."""
    rng = np.random.default_rng(seed)
    mid_ts = np.arange(0, hours * HOUR, MIN, dtype="int64")
    mid = np.clip(0.4 + np.cumsum(rng.normal(drift, 0.002, len(mid_ts))), 0.05, 0.95)
    n = rng.poisson(rate * hours)
    ts = np.sort(rng.integers(0, hours * HOUR, n)).astype("int64")
    i = np.searchsorted(mid_ts, ts, side="right") - 1
    buy = rng.random(n) < 0.55
    px = np.clip(mid[i] + np.where(buy, 0.01, -0.01), 0.01, 0.99)
    return R.Market(cond=cond, kind=kind, subject=cond, question=cond, fairs={1: None}, outcome=True,
                    mid_ts=mid_ts, mid_px=mid, tr_ts=ts, tr_px=px, tr_sz=rng.integers(1, 200, n).astype(float),
                    tr_buy=buy)


def event(mks, hours=48):
    return dict(markets=mks, stages=[dict(run_id=1, start=0, end=hours * HOUR, session_end=True)],
                sessions=[hours * HOUR])


def test_fit_recovers_the_tape():
    mks = [market(f"T{i}", seed=i) for i in range(5)]
    cal = ST.fit([(mks, 48 * HOUR)])["race_win"]
    assert cal["markets"] == 5 and cal["trades"] == sum(len(m.tr_ts) for m in mks)
    assert np.mean(cal["rate"][:6]) == pytest.approx(4.0, rel=0.25)          # trades per market-hour
    assert cal["buy"] == pytest.approx(0.55, abs=0.05) and 0.005 < cal["noise"] < 0.05


def test_retape_is_seeded_and_keeps_the_prices():
    ev = event([market("T1"), market("T2", seed=2)])
    cal = ST.fit([(ev["markets"], 48 * HOUR)])
    a, b = ST.retape(ev, cal), ST.retape(ev, cal)
    for x, y, m in zip(a["markets"], b["markets"], ev["markets"]):
        assert np.array_equal(x.tr_ts, y.tr_ts) and np.array_equal(x.tr_px, y.tr_px)
        assert np.array_equal(x.mid_px, m.mid_px) and len(x.tr_ts) > 50
        assert np.all(np.diff(x.tr_ts) >= 0) and np.all((x.tr_px >= 0.01) & (x.tr_px <= 0.99))
    c = ST.retape(ev, cal, ST.Params(seed=7))
    assert not np.array_equal(c["markets"][0].tr_ts, a["markets"][0].tr_ts)
    rows = ST.compare(ev["markets"], a["markets"])
    assert rows[0]["synth_trades"] == pytest.approx(rows[0]["real_trades"], rel=0.3)


def test_budgets_cap_spending():
    ev = event([market("T1", rate=40.0)])
    cal = ST.fit([(ev["markets"], 48 * HOUR)])
    p = ST.Params(takers=5, budget=(10.0, 10.0))
    out = ST.retape(ev, cal, p)
    mk = out["markets"][0]
    spent = np.where(mk.tr_buy, mk.tr_px, 1 - mk.tr_px) * mk.tr_sz
    who = out["takers"]["T1"]
    assert all(spent[who == k].sum() <= 10.0 + 1e-9 for k in range(5))


def test_informed_takers_hurt_a_maker_quoting_the_mid():
    """A maker quoting a tight spread around the exchange's own mid (refreshed hourly) does worse once part of
    the crowd trades on where the price goes next than against noise traders alone."""
    from dataclasses import replace
    hours = 48
    mks = [market(f"T{i}", drift=0.0003, seed=i) for i in range(6)]
    cal = ST.fit([(mks, hours * HOUR)])
    stages = [dict(run_id=h, start=h * HOUR, end=(h + 1) * HOUR, session_end=False) for h in range(hours)]
    mks = [replace(m, fairs={h: float(m.mid_px[h * 60]) for h in range(hours)}) for m in mks]
    ev = dict(markets=mks, stages=stages, sessions=[hours * HOUR])
    p = R.Params(pull_min=0, min_volume_24h=0, max_disagree=None, half_spread=0.01, size=50, max_pos=5000,
                 max_capital=1e9, fill="touch", price_band=(0.0, 1.0))

    def pnl(informed):
        syn = ST.retape(ev, cal, ST.Params(informed=informed))
        pos = R.replay(syn, p)["positions"]
        end = {m.cond: float(m.mid_px[-1]) for m in mks}
        return sum(r["cash"] + r["inventory"] * end[r["cond"]] for r in pos.to_dict("records"))
    a, b = pnl(0.6), pnl(0.0)
    assert a < b
