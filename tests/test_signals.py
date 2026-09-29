"""Live paper signals (pipelines/signals.py): heat, taker signals = the backtest taker's trades, maker quote
state, stage truncation, idempotent storage, profiles. (Replay-vs-sweep parity on a real weekend needs the
full database and minutes of pricing, so it is a script: scripts/signals_parity.py.)"""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.markets.strategies import taker_weekend as RB
from racinglines.pipelines import signals as SG


def _mk(kind, fairs, prices, key=None, outcome=None):
    labels = ["after FP1", "after FP2", "after Quali"][:len(fairs)]
    return dict(key=key or kind, kind=kind, subject=kind, outcome=outcome,
                stages=[dict(label=lab, t=pd.Timestamp("2026-10-02") + pd.Timedelta(hours=i), fair=f, price=p,
                             tradeable=True) for i, (lab, f, p) in enumerate(zip(labels, fairs, prices))])


@pytest.mark.parametrize("args, h", [
    (("buy", "YES", 60, 0.41, 0.50), 1),        # EV 5.4
    (("buy", "YES", 100, 0.30, 0.45), 2),       # EV 15
    (("buy", "NO", 140, 0.36, 0.25), 3),        # EV 140 x (0.75 - 0.36)
    (("sell", "YES", 60, 0.41, 0.50), None),    # exits have no heat
    (("buy", "YES", 60, 0.41, None), None),
    (("buy", "YES", 60, 0.60, 0.50), None),     # negative EV (can't happen from the rule, but no heat)
])
def test_heat(args, h):
    assert SG.heat(*args) == h


def test_taker_signals_are_the_backtest_takers_trades():
    p = RB.TakerParams(min_edge=0.10, min_edge_h2h=0.05, mode="update")
    wk = [_mk("race_h2h", [0.57, 0.58], [0.50, 0.50]), _mk("race_win", [0.37, 0.25], [0.30, 0.30]),
          _mk("race_podium", [0.50, 0.30], [0.30, 0.31])]
    sigs, pos = SG.taker_signals(wk, p)
    tr, _ = RB.run_weekend(wk, p)
    assert len(sigs) == len(tr)
    got = sorted((s["market_key"], s["stage"], s["side"], s["shares"] * (1 if s["action"] == "buy" else -1),
                  s["limit_price"]) for s in sigs)
    want = sorted((r["key"], r["stage"], r["side"], r["shares"], r["price"]) for r in tr.to_dict("records"))
    assert got == want
    # the podium entry after FP1 is exited after FP2 (edge gone): a sell with no heat
    pod = [s for s in sigs if s["market_key"] == "race_podium"]
    assert [s["action"] for s in pod] == ["buy", "sell"] and pod[0]["heat"] and pod[1]["heat"] is None
    assert {p["market_key"] for p in pos} == {"race_h2h", "race_podium"}      # flat podium still listed (traded)


def test_truncate_stages():
    st = [dict(run_id=1, start=0, end=100, session_end=True), dict(run_id=2, start=100, end=200, session_end=True),
          dict(run_id=3, start=200, end=300, session_end=True)]
    out = SG.truncate_stages(st, 150)
    assert [s["run_id"] for s in out] == [1, 2] and out[1]["end"] == 150 and out[1]["session_end"] is False
    assert out[0] == st[0]


class _M:
    def __init__(self, cond):
        self.cond, self.kind, self.subject, self.fairs = cond, "race_win", cond, {7: 0.4, 8: 0.45}


def test_maker_state_signals_on_changes_only():
    q = pd.DataFrame([(1, "a", 7, 0.38, 0.42, None), (2, "a", 7, 0.38, 0.42, None), (3, "a", 7, None, None, "disagree"),
                      (4, "a", 8, None, None, "thin"), (1, "b", 7, None, None, "thin")],
                     columns=["ts", "cond", "run_id", "bid", "ask", "skip"])
    f = pd.DataFrame([dict(ts=2, cond="a", run_id=7, side="buy", price=0.38, qty=25.0, fair=0.4, mid=0.40)])
    sigs, state = SG.maker_state(q, f, [_M("a"), _M("b")], {7: "after FP1", 8: "after FP2"}, 4)
    acts = sorted((s["market_key"], s["stage"], s["action"]) for s in sigs)
    assert acts == [("a", "after FP1", "fill"), ("a", "after FP1", "pull"), ("a", "after FP1", "quote")]
    assert state["a"]["quote_state"] == "thin" and state["b"]["quote_state"] == "thin"
    fill = next(s for s in sigs if s["action"] == "fill")
    assert fill["side"] == "YES" and fill["status"] == "filled_paper" and fill["dedupe"] == "2"


def _out(signals, stage="after FP1"):
    prof = dict(candidate_id=999999, name="T · test", strategy="update")
    return dict(profile=prof, event=dict(event_key="2099-01", name="Test GP"), race_id=None,
                stages=[(stage, pd.Timestamp("2099-01-01"), None, pd.Timestamp("2099-01-01"))],
                signals=signals, positions=[dict(market_key="tok", kind="race_win", subject="X", yes_shares=10.0,
                                                 no_shares=0.0, cash=-4.1, mark=0.42, outcome=None)])


def test_store_is_idempotent(test_engine):
    s1 = dict(market_key="tok", kind="race_win", subject="X", stage="after FP1", dedupe="after FP1", action="buy",
              side="YES", shares=10.0, limit_price=0.41, fair=0.55, price=0.40, edge=0.15, heat=1, target_cost=4.1,
              signal_ts=pd.Timestamp("2099-01-01"), detail=dict(ev=np.float64(1.4)))
    with test_engine.begin() as c:
        uid = c.execute(text("""INSERT INTO users (username, password_hash, role) VALUES ('sigtest', 'x', 'taker')
                                RETURNING id""")).scalar()
        assert len(SG.store(c, uid, _out([s1]))) == 1
        assert SG.store(c, uid, _out([s1])) == []                         # same signal again: nothing new
        s2 = dict(s1, stage="after FP2", dedupe="after FP2", action="sell", heat=None)
        assert len(SG.store(c, uid, _out([s1, s2], stage="after FP2"))) == 1
        st = dict(c.execute(text("SELECT stage, status FROM strategy_signals WHERE user_id = :u"), dict(u=uid)).all())
        assert st == {"after FP1": "expired", "after FP2": "new"}          # superseded by the later stage
        assert c.execute(text("SELECT count(*) FROM paper_positions WHERE user_id = :u"), dict(u=uid)).scalar() == 1


def test_profiles_define_valid_settings():
    from racinglines.pipelines import profiles as PF
    from racinglines.pipelines import sweep_settings as SS
    a = SS.Settings.from_dict(PF.PROFILES["A"]["settings"])
    assert a["min_edge_h2h"] == 0.05 and "pre-weekend" not in a["taker_stages"]
    c = SS.Settings.from_dict(PF.PROFILES["C"]["settings"])
    assert (c["variant"], c["max_disagree"], c["size"]) == ("gbm", 0.05, 25)
    assert PF.PROFILES["A"]["strategy"] in SG.WS.TAKER_MODES and PF.PROFILES["C"]["strategy"] in SG.WS.MAKERS


def test_signal_lines_never_show_fair_or_edge():
    from racinglines.markets.alerts import signal_line
    s = dict(stage="after FP2", action="buy", side="YES", shares=62, limit_price=0.41, subject="Norris ahead of Piastri",
             heat=2, fair=0.52, edge=0.11)          # heat 2 = hot
    line = signal_line(s, "A")
    assert line == 'A · after FP2 · BUY YES 62 sh "Norris ahead of Piastri" @ 0.41 · hot'
    assert "0.52" not in line and "0.11" not in line


def test_signal_code_never_touches_the_order_path():
    """Paper only: the signal engine, profiles and alerts don't import or call the Polymarket order code."""
    import inspect

    from racinglines.markets import alerts
    from racinglines.pipelines import profiles
    for mod in (SG, profiles, alerts):
        src = inspect.getsource(mod)
        assert "polymarket.trade" not in src and "polymarket import trade" not in src and "post_order" not in src


def test_missing_sessions_include_the_race_once_it_is_over():
    from types import SimpleNamespace
    t = pd.Timestamp("2099-10-02 04:30")
    w = dict(event_key="2099-16", race_start=t + pd.Timedelta(days=2),
             stages=[("pre-weekend", t - pd.Timedelta(hours=1)), ("after FP1", t + pd.Timedelta(minutes=90)),
                     ("after FP2", t + pd.Timedelta(hours=5))])
    res = pd.DataFrame(dict(year=[2099], series_round=[16], round=["fp1"]))
    meas = SimpleNamespace(res=res)
    assert SG._missing_sessions(meas, w, t + pd.Timedelta(hours=6)) == ["after FP2"]
    assert SG._missing_sessions(meas, w, w["race_start"] + pd.Timedelta(hours=1)) == ["after FP2"]
    assert SG._missing_sessions(meas, w, w["race_start"] + pd.Timedelta(hours=4)) == ["after FP2", "Race"]
    assert SG.in_weekend(w, w["race_start"] + pd.Timedelta(hours=20))


def test_follow_rate_prefers_hotter_entries_and_follows_markets_through():
    keys = [f"m{i}" for i in range(6000)]
    heats = [1] * 3000 + [2] * 1500 + [3] * 1500                 # A's backtest mix
    took = [SG.follows(7, k, h, 0.33) for k, h in zip(keys, heats)]
    assert abs(np.mean(took) - 0.33) < 0.02
    by = {h: np.mean([t for t, hh in zip(took, heats) if hh == h]) for h in (1, 2, 3)}
    assert by[1] < by[2] < by[3]
    assert SG.follows(7, "m1", 2, 0.33) == SG.follows(7, "m1", 2, 0.33)             # deterministic
    assert all(SG.follows(7, k, 1, None) for k in keys[:50])                         # no rate: follow all
    t0 = pd.Timestamp("2026-10-02")
    sigs = [dict(market_key=k, action=a, heat=h, signal_ts=t0 + pd.Timedelta(hours=i))
            for k in keys[:200] for i, (a, h) in enumerate((("buy", 3), ("sell", None)))]
    pos = [dict(market_key=k) for k in keys[:200]]
    out, kept = SG.apply_follow(sigs, pos, 7, 0.33)
    fk = {s["market_key"] for s in out if s["followed"]}
    assert {p["market_key"] for p in kept} == fk and 0 < len(fk) < 200
    assert all(s["followed"] == (s["market_key"] in fk) for s in out)               # exits follow their entry


A_PROFILE = dict(name="A · test", strategy="update",
                 settings={"variant": "gridq+pretrain+reset", "min_edge": 0.10, "min_edge_h2h": 0.05,
                           "taker_stages": ["after FP1", "after FP2", "after FP3", "after SQ", "after Sprint", "after Quali"]})


@pytest.mark.parametrize("kind, fair, price, vol, want", [
    ("race_win", 0.45, 0.30, 500, ("buy", "YES")),
    ("race_win", 0.36, 0.30, 500, (None, "no edge")),            # 6 pts: under A's 10
    ("race_h2h", 0.57, 0.50, 500, ("buy", "YES")),               # 7 pts: over the h2h 5
    ("race_podium", 0.20, 0.40, 500, ("buy", "NO")),
    ("race_win", 0.45, 0.30, 10, (None, "too thin to trade")),
    ("race_win", 0.10, 0.01, 500, (None, "outside the price band")),
    ("race_win", None, 0.30, 500, (None, "not priced yet")),
    ("champion", 0.5, 0.3, 500, (None, "not a market this strategy trades")),
])
def test_call(kind, fair, price, vol, want):
    c = SG.call(A_PROFILE, kind, fair, price, vol)
    assert (c["action"], c["side"] if c["action"] else c["why"]) == want
    assert "fair" not in c and "edge" not in c                    # takers never get them
    if c["action"]:
        assert c["heat"] in (1, 2, 3) and c["cost"] <= 50.0 + 1e-9


def test_kalshi_profile_k_is_assigned_only_on_request(test_engine):
    """K is a Lab candidate on Kalshi; `profiles --assign-demo --venue kalshi` stores it as the demo maker's
    Kalshi profile beside (not instead of) its Polymarket profile."""
    from racinglines.pipelines import profiles as PF
    from racinglines.pipelines import sweep_settings as SS
    k = SS.Settings.from_dict(PF.PROFILES["K"]["settings"])
    assert PF.PROFILES["K"]["venue"] == "kalshi" and PF.PROFILES["K"]["strategy"] in SG.WS.MAKERS
    assert k.model_key == SS.Settings.from_dict({"variant": k["variant"]}).model_key   # a maker profile: quote settings only
    with test_engine.begin() as c:
        c.execute(text("INSERT INTO sports (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
        c.execute(text("INSERT INTO leagues (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
        c.execute(text("""INSERT INTO competitions (code, name, league_id, sport_id)
                          SELECT 'f1_wdc', 'F1', l.id, s.id FROM leagues l, sports s WHERE l.code = 'f1' AND s.code = 'f1'
                          ON CONFLICT DO NOTHING"""))
        c.execute(text("""INSERT INTO users (username, password_hash, role) VALUES ('maker', 'x', 'maker'), ('taker', 'x', 'taker')
                          ON CONFLICT DO NOTHING"""))
        ids = PF.ensure_candidates(c)
        assert set(ids) == {"A", "C", "K"} and PF.load(c, "K")["venue"] == "kalshi" and "venue" not in PF.load(c, "C")
        assert c.execute(text("SELECT params->>'venue' FROM model_runs WHERE id = :i"), dict(i=ids["K"])).scalar() == "kalshi"
        assert PF.assign_demo(c) == {"taker": PF.PROFILES["A"]["name"], "maker": PF.PROFILES["C"]["name"]}
        assert PF.assigned(c, venue="kalshi") == []                        # nothing on Kalshi until asked
        assert PF.assign_demo(c, venue="kalshi") == {"maker": PF.PROFILES["K"]["name"]}
        uid = c.execute(text("SELECT id FROM users WHERE username = 'maker'")).scalar()
        assert PF.of_user(c, uid)["name"] == PF.PROFILES["C"]["name"]        # Polymarket untouched
        kp = PF.of_user(c, uid, venue="kalshi")
        assert kp["name"] == PF.PROFILES["K"]["name"] and kp["venue"] == "kalshi" and kp["candidate_id"] == ids["K"]
        assert [u for _, u, _, _ in PF.assigned(c)] == ["maker", "taker"]   # the engine's list is as before


def test_maker_call_reads_the_profiles_volume_floor():
    """A maker profile's `maker_min_volume_24h` (K's $400) is the live volume floor, as in the replay;
    unset keeps the replay's own $100."""
    from racinglines.pipelines import profiles as PF
    k = dict(settings=PF.PROFILES["K"]["settings"])
    c = dict(settings=PF.PROFILES["C"]["settings"])
    assert SG.maker_call(k, "race_win", 0.30, 0.30, volume_24h=300)["why"] == "too thin to quote"
    assert SG.maker_call(k, "race_win", 0.30, 0.30, volume_24h=500)["action"] == "quote"
    assert SG.maker_call(c, "race_win", 0.30, 0.30, volume_24h=300)["action"] == "quote"
    assert SG.maker_call(c, "race_win", 0.30, 0.30, volume_24h=50)["why"] == "too thin to quote"
