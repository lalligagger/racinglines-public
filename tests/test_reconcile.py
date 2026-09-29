"""Per-weekend reconciliation (pipelines/reconcile.py): one fill shape for live rows and replay signals, markouts
from the tape, P&L to resolution, the noise band from seed replicates, the +-25% and band rules, the backfill
self-check, and reading an account's stored weekend. (The full command on a real weekend needs the database and
the tape: the PR that added it shows its output on the 2026 rounds.)"""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.pipelines import reconcile as RC
from racinglines.pipelines import signals as SG

T0 = pd.Timestamp("2026-10-03 12:00")


def _taker_signals():
    return [dict(market_key="tokA", kind="race_win", subject="A", stage="after FP1", dedupe="after FP1", action="buy", side="YES",
                 shares=100.0, limit_price=0.31, price=0.30, signal_ts=T0, detail=dict(followed=True)),
            dict(market_key="tokB", kind="race_podium", subject="B", stage="after FP1", dedupe="after FP1", action="buy", side="NO",
                 shares=50.0, limit_price=0.61, price=0.40, signal_ts=T0, detail=dict(followed=False)),
            dict(market_key="tokA", kind="race_win", subject="A", stage="after Quali", dedupe="after Quali", action="sell", side="YES",
                 shares=40.0, limit_price=0.34, price=0.35, signal_ts=T0 + pd.Timedelta(hours=5),
                 detail=dict(followed=True)),
            dict(market_key="tokC", kind="race_win", subject="C", stage="after Quali", action="quote", side="both")]


def test_fills_one_shape_for_takers_and_makers():
    f = RC.fills_of(_taker_signals(), "update")
    assert f["key"].tolist() == ["tokA", "tokB", "tokA"]                 # the quote row isn't a taker fill
    assert f["sign"].tolist() == [1.0, -1.0, -1.0]                        # YES buy, NO buy, YES sell
    assert f["entry"].tolist() == [True, True, False] and f["followed"].tolist() == [True, False, True]
    top = RC.fills_of([dict(_taker_signals()[0], followed=False, detail={})], "update")   # apply_follow puts it on top
    assert not top["followed"].iloc[0]
    assert f["ts"].iloc[0] == T0 and f["ts"].dtype.kind == "M"
    m = [dict(market_key="0xc", kind="race_win", subject="X", stage="after FP2", action="fill", side="NO", shares=25.0,
              limit_price=0.42, price=0.40, signal_ts=T0.tz_localize("UTC"), status="filled_paper"),
         dict(market_key="0xc", kind="race_win", subject="X", stage="after FP2", action="pull", side="both")]
    g = RC.fills_of(m, "maker")
    assert len(g) == 1 and g["sign"].iloc[0] == -1.0 and g["entry"].iloc[0] and g["ts"].iloc[0] == T0   # UTC -> naive


def test_markouts_read_the_mid_an_hour_later():
    mids = {"tokA": {T0 + pd.Timedelta(hours=1): 0.36, T0 + pd.Timedelta(hours=6): 0.30},
            "tokB": {T0 + pd.Timedelta(hours=1): 0.45}}

    def mid_at(key, ts):
        s = mids.get(key, {})
        at = [v for t, v in s.items() if t <= ts]
        return at[-1] if at else None
    f = RC.markouts(RC.fills_of(_taker_signals(), "update"), mid_at)
    assert f["markout_60m"].round(4).tolist() == [pytest.approx(6.0), pytest.approx(-2.5), pytest.approx(2.0)]
    # +100 x (0.36 - 0.30); NO buy: -50 x (0.45 - 0.40); YES sell at 12:00+5h: -40 x (0.30 - 0.35)
    g = RC.markouts(RC.fills_of(_taker_signals(), "update"), lambda k, t: None)
    assert g["markout_60m"].isna().all() and RC.summarize(g, None)["markout_60m"] == 0.0


def test_calls_pnl_is_the_takers_rule():
    f = RC.fills_of(_taker_signals(), "update")
    pnl, missing = RC.calls_pnl(f, {"tokA": True, "tokB": False})
    # YES buy: 100 x (1 - 0.31); NO buy (B lost, NO pays 1): 50 x (1 - 0.61); YES sell: -40 x (1 - 0.34)
    assert pnl == pytest.approx(69.0 + 19.5 - 26.4) and missing == 0
    pnl, missing = RC.calls_pnl(f, {"tokA": True})
    assert pnl == pytest.approx(69.0 - 26.4) and missing == 1


def test_as_stored_collapses_same_timestamp_fills_like_the_store():
    f = dict(market_key="0xc", kind="race_win", subject="X", stage="after FP2", action="fill", side="YES", shares=25.0,
             limit_price=0.42, price=0.40, signal_ts=T0, dedupe="1700000000000000000")
    sigs = [f, dict(f, shares=10.0), dict(f, side="NO"), dict(f, dedupe="1700000000000000001")]
    kept, n = RC.as_stored(sigs)
    assert n == 1 and [k["shares"] for k in kept] == [25.0, 25.0, 25.0]           # the first of a key wins
    assert RC.as_stored([])[1] == 0


def test_positions_pnl():
    pos = [dict(cash=-31.0, yes_shares=100.0, no_shares=0.0, outcome=True),
           dict(cash=-30.5, yes_shares=0.0, no_shares=50.0, outcome=False),
           dict(cash=5.0, yes_shares=0.0, no_shares=0.0, outcome=None)]
    assert RC.positions_pnl(pos[:2]) == (pytest.approx(69.0 + 19.5), 0)
    assert RC.positions_pnl(pos) == (pytest.approx(88.5), 1)


def test_noise_band_is_the_replicates_range_at_least_the_floor():
    lo, hi = RC.noise_band([10.0, 20.0, 30.0], "taker")
    assert lo == pytest.approx(20 - RC.NOISE_FLOOR["taker"]) and hi == pytest.approx(20 + RC.NOISE_FLOOR["taker"])
    lo, hi = RC.noise_band([-300.0, 0.0, 300.0], "maker")
    assert (lo, hi) == (-300.0, 300.0)                     # a spread wider than the floor is the band
    assert RC.noise_band([], "maker") is None and RC.noise_band([None, 5.0], "taker")[0] < 5.0
    assert RC.seeds(2) == (43, 44) and RC.seeds(4) == (43, 44, 45, 46) and RC.seeds(0) == ()


def test_within_pct():
    assert RC.within_pct(12, 10) and not RC.within_pct(13, 10) and RC.within_pct(0, 0) and not RC.within_pct(1, 0)
    assert RC.within_pct(0.5, 0.0, abs_floor=1.0) and RC.within_pct(-11.0, -9.0, abs_floor=1.0)


def _summary(fills, markout, pnl, notional=100.0):
    return dict(fills=fills, notional=notional, markout_60m=markout, markouts_known=fills, pnl=pnl)


def test_compare_flags_the_rules():
    ok = RC.compare(_summary(11, -8.0, 40.0), _summary(10, -7.0, 20.0), [-10.0, 50.0], "taker")
    assert ok["ok"] and ok["flags"] == []
    bad = RC.compare(_summary(14, -20.0, 60.0), _summary(10, -7.0, 20.0), [-10.0, 50.0], "taker")
    assert not bad["ok"] and bad["flags"] == ["fills", "markout", "P&L"]
    rows = {r["measure"]: r for r in bad["rows"]}
    assert rows["notional $"]["ok"] is None and rows["fills"]["diff"] == 4
    # no band: the P&L can't be judged; unsettled: neither
    assert {r["measure"]: r["ok"] for r in RC.compare(_summary(10, 0.0, 1.0), _summary(10, 0.0, 2.0), None, "maker")["rows"]}["P&L $"] is None
    assert RC.compare(_summary(10, 0.0, None), _summary(10, 0.0, 2.0), [0, 1], "maker")["ok"]


def test_compare_exact_for_a_backfilled_weekend():
    same = RC.compare(_summary(10, -7.004, 20.001), _summary(10, -7.0, 20.0), None, "maker", exact=True)
    assert same["ok"]
    off = RC.compare(_summary(10, -7.0, 20.0), _summary(11, -7.5, 20.0), None, "maker", exact=True)
    assert off["flags"] == ["fills", "markout"] and all(r["rule"] in ("exact", "shown") for r in off["rows"])


def _out(signals, positions, strategy="update"):
    prof = dict(candidate_id=999998, name="R · test", strategy=strategy)
    return dict(profile=prof, event=dict(event_key="2099-02", name="Test GP"), race_id=None,
                stages=[("after FP1", pd.Timestamp("2099-01-01"), None, pd.Timestamp("2099-01-01"))],
                signals=signals, positions=positions)


def test_live_rows_reads_the_account_and_tells_a_backfill(test_engine):
    sig = [dict(s, detail=dict(s.get("detail") or {}, ev=np.float64(1.0))) for s in _taker_signals()[:3]]
    pos = [dict(market_key="tokA", kind="race_win", subject="A", yes_shares=60.0, no_shares=0.0, cash=-17.4, mark=0.3,
                outcome=True)]
    with test_engine.begin() as c:
        uid = c.execute(text("INSERT INTO users (username, password_hash, role) VALUES ('rectest', 'x', 'taker') RETURNING id")).scalar()
        SG.store(c, uid, _out(sig, pos), follow_rate=None, history=True)
        got = RC.live_rows(c, uid, 999998, "2099-02", "polymarket")
        assert got["backfill"] and not got["mixed"] and len(got["positions"]) == 1
        assert [s["action"] for s in got["signals"]] == ["buy", "buy", "sell"]
        assert RC.live_rows(c, uid, 999998, "2099-02", "kalshi")["signals"] == []
        assert RC.live_rows(c, uid, 1, "2099-02", "polymarket")["signals"] == []          # another candidate's rows
        # a live (not backfilled) weekend, stored the way the signal engine stores it
        uid2 = c.execute(text("INSERT INTO users (username, password_hash, role) VALUES ('rectest2', 'x', 'taker') RETURNING id")).scalar()
        SG.store(c, uid2, _out(sig, pos))
        live = RC.live_rows(c, uid2, 999998, "2099-02", "polymarket")
        assert not live["backfill"] and not live["mixed"] and len(live["signals"]) == 3
        f = RC.fills_of(live["signals"], "update")
        assert f["qty"].tolist() == [100.0, 50.0, 40.0] and f["ts"].iloc[0] == T0
        assert RC.positions_pnl(live["positions"]) == (pytest.approx(60.0 - 17.4), 0)


def test_reconcile_module_never_writes_the_records():
    """Read-only on the accounts' records: the module never issues an INSERT, UPDATE or DELETE."""
    import inspect
    src = inspect.getsource(RC)
    assert not any(w in src.upper() for w in ("INSERT ", "UPDATE ", "DELETE "))
