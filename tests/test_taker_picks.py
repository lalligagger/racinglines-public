"""The taker shortlist (profiles.TAKER_TOP / T1..T10), blends (profiles.COMBOS, signals.compute_all), a basic
account's draw of three (roles.basic_members) and what basic accounts see of their picks (roles.basic_*, the MCP
tools), and the demo follow rates (profiles.DEMO_FOLLOW)."""

import json
from dataclasses import replace

import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.markets.strategies import taker_weekend as RB
from racinglines.pipelines import profiles as PF
from racinglines.pipelines import signals as SG
from racinglines.web import roles as R


def _mk(kind, fairs, prices, key=None):
    labels = ["after FP1", "after FP2", "after Quali"][:len(fairs)]
    return dict(key=key or kind, kind=kind, subject=kind, outcome=None,
                stages=[dict(label=lab, t=pd.Timestamp("2026-10-02") + pd.Timedelta(hours=i), fair=f, price=p,
                             tradeable=True) for i, (lab, f, p) in enumerate(zip(labels, fairs, prices))])


# --- config ---------------------------------------------------------------------------------------------------

def test_shortlist_is_ten_valid_taker_profiles_and_blends_name_them():
    from racinglines.pipelines import sweep_settings as SS
    assert len(PF.TAKER_TOP) == 10 and len(set(PF.TAKER_TOP)) == 10
    for code in PF.TAKER_TOP:
        pr = PF.PROFILES[code]
        assert pr["strategy"] in SG.WS.TAKER_MODES and pr["name"].startswith(code + " ")
        SS.Settings.from_dict(pr["settings"])                                   # valid settings, strictly
    assert PF.PROFILES["T1"]["settings"] == PF.PROFILES["A"]["settings"]
    assert PF.PROFILES["T8"]["strategy"] == "early" and PF.PROFILES["T8"]["settings"] == PF.PROFILES["T1"]["settings"]
    tb = PF.PROFILES["TB"]
    assert PF.is_combo(tb) and tb["members"] == [("T1", 0.5), ("T8", 0.5)] and not PF.is_combo(PF.PROFILES["A"])
    for pr in PF.COMBOS.values():
        assert all(code in PF.TAKER_TOP for code, _ in pr["members"])
        assert abs(sum(w for _, w in pr["members"]) - 1.0) < 1e-9


def test_demo_follow_rates_by_account_and_strategy_kind():
    assert PF.follow_rate("taker", "update") == 0.33 and PF.follow_rate("taker", "early") == 0.33
    assert PF.follow_rate("maker", "update") == 1.0 and PF.follow_rate("maker", "early") == 1.0
    assert PF.follow_rate("maker", "maker") is None                   # the pro demo's maker strategy: untouched
    assert PF.follow_rate("someone", "update") is None
    assert SG.follow_prob(3, PF.follow_rate("maker", "update")) == 1.0   # fills every pick


# --- the basic draw -------------------------------------------------------------------------------------------

def test_basic_draw_is_three_distinct_codes_stable_per_account():
    for uid in range(1, 60):
        d = R.basic_members(uid)
        assert len(d) == R.BASIC_PICKS == 3 and len(set(d)) == 3 and set(d) <= set(PF.TAKER_TOP)
        assert list(d) == sorted(d, key=PF.TAKER_TOP.index)
        assert R.basic_members(uid) == d                                 # never re-rolled
    assert len({R.basic_members(u) for u in range(1, 60)}) > 10         # accounts differ


def test_basic_draw_follows_the_seed(monkeypatch):
    before = [R.basic_members(u) for u in range(1, 30)]
    monkeypatch.setattr(R, "BASIC_SEED", "another-seed")
    assert [R.basic_members(u) for u in range(1, 30)] != before


# --- blends ---------------------------------------------------------------------------------------------------

def test_taker_scale_multiplies_stakes():
    p = RB.TakerParams(min_edge=0.10, min_edge_h2h=0.05, mode="update")
    # entries only (one stage each): the $2 minimum rebalance isn't scaled, so small resizes can differ
    wk = [_mk("race_h2h", [0.62], [0.50]), _mk("race_win", [0.45], [0.30]), _mk("race_podium", [0.10], [0.30])]
    full, fpos = SG.taker_signals(wk, p)
    half, hpos = SG.taker_signals(wk, replace(p, scale=0.5))
    assert [(s["market_key"], s["stage"], s["action"], s["side"]) for s in full] == \
        [(s["market_key"], s["stage"], s["action"], s["side"]) for s in half]
    for a, b in zip(full, half):
        assert b["shares"] == pytest.approx(a["shares"] * 0.5)
    for a, b in zip(fpos, hpos):
        assert b["cash"] == pytest.approx(a["cash"] * 0.5)


def _fake_compute(calls):
    def compute(engine, engine_url, profile, **kw):
        calls.append((profile["name"], kw))
        sig = dict(market_key="tok", kind="race_win", subject="X", stage="after FP1", dedupe="after FP1", action="buy",
                   side="YES", shares=100.0 * kw.get("scale", 1.0), limit_price=0.41, fair=0.61, price=0.40, edge=0.21,
                   heat=2, detail=dict(ev=1.0))
        return dict(profile=profile, event=dict(event_key="2099-01", name="Test GP"), stages=[], signals=[sig],
                    positions=[], venue="polymarket")
    return compute


def test_compute_all_runs_each_member_scaled_and_tagged(monkeypatch):
    calls = []
    monkeypatch.setattr(SG, "compute", _fake_compute(calls))
    m1 = dict(candidate_id=11, name=PF.PROFILES["T1"]["name"], strategy="update", settings=PF.PROFILES["T1"]["settings"])
    m8 = dict(candidate_id=18, name=PF.PROFILES["T8"]["name"], strategy="early", settings=PF.PROFILES["T8"]["settings"])
    blend = dict(name="TB · test", strategy="update", settings=m1["settings"], candidate_id=None,
                 members=[dict(code="T1", weight=0.5, member=m1), dict(code="T8", weight=0.5, member=m8)])
    outs = SG.compute_all(None, None, blend, now="2099-01-01", live=False)
    assert [c[1]["scale"] for c in calls] == [0.5, 0.5] and [c[0] for c in calls] == [m1["name"], m8["name"]]
    assert [o["signals"][0]["shares"] for o in outs] == [50.0, 50.0]
    assert [o["signals"][0]["detail"]["member"] for o in outs] == ["T1", "T8"]
    assert [o["profile"]["candidate_id"] for o in outs] == [11, 18]            # each member keeps its own rows
    assert all(o["profile"]["name"] == "TB · test" for o in outs)
    assert [o["profile"]["strategy"] for o in outs] == ["update", "early"]
    assert SG.combo_key(blend) == ("combo", ("T1", 0.5), ("T8", 0.5))


def test_single_strategy_profile_takes_the_old_path(monkeypatch):
    calls = []
    fake = _fake_compute(calls)
    monkeypatch.setattr(SG, "compute", fake)
    a = dict(candidate_id=7, name=PF.PROFILES["A"]["name"], strategy="update", settings=PF.PROFILES["A"]["settings"])
    outs = SG.compute_all(None, None, a, now="2099-01-01", live=False)
    assert len(outs) == 1 and calls == [(a["name"], dict(now="2099-01-01", live=False))]     # no scale passed
    assert outs[0]["profile"] is a and outs[0]["signals"][0]["shares"] == 100.0
    assert "member" not in outs[0]["signals"][0]["detail"]
    assert SG.combo_key(a) == 7


# --- what basic sees ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("edge, min_edge, want", [(0.20, 0.10, 3), (-0.21, 0.10, 3), (0.15, 0.10, 2), (0.19, 0.10, 2),
                                                  (0.12, 0.10, 1), (0.05, 0.05, 1), (None, 0.10, None),
                                                  (float("nan"), 0.10, None)])
def test_pick_stars(edge, min_edge, want):
    assert R.pick_stars(edge, min_edge) == want


def test_basic_signal_hides_the_strategy_and_our_numbers():
    s = dict(id=1, profile="TB · blended taker (update + stage-aware)", strategy="early", candidate_id=18, run_id=5,
             market_key="tok", kind="race_h2h", subject="Zed ahead of Yan", stage="after FP2", action="buy", side="YES",
             shares=62.0, limit_price=0.41, fair=0.5234, price=0.40, edge=0.1234, heat=2,
             detail=dict(member="T8", ev=1.4, side_prob=0.5234, followed=True, backfill=True))
    b = R.basic_signal(s)
    assert b["profile"] == R.BASIC_NAME and b["strategy"] == "taker"
    assert b["detail"] == dict(followed=True, backfill=True)
    for k in ("fair", "edge", "candidate_id", "run_id"):
        assert k not in b
    assert b["stars"] == 3                                  # 12.3 pts over T8's h2h bar of 5 pts
    text_ = json.dumps(b, default=str)
    for leak in ("T8", "TB", "early", "0.5234", "0.1234", "member", "side_prob"):
        assert leak not in text_, leak
    assert R.basic_signal(dict(s, action="sell"))["stars"] is None
    # a member's own bar: T5 trades from 8 pts everywhere, so 12.3 pts is 1.5x -> 2 stars
    assert R.basic_signal(dict(s, kind="race_win", detail=dict(member="T5")))["stars"] == 2
    # no member (a single-strategy basic profile, e.g. legacy A): the account's profile's bar
    assert R.basic_signal(dict(s, kind="race_win", detail={}), dict(settings=PF.PROFILES["A"]["settings"]))["stars"] == 1


def test_basic_rows_and_profile_view():
    assert R.basic_row(dict(profile="T4 · update, gbm", strategy="update", pnl=1.0)) == \
        dict(profile=R.BASIC_NAME, strategy="taker", pnl=1.0)
    assert R.basic_row(dict(profile="Private book", strategy="private"))["profile"] == "Private book"
    v = R.basic_view_profile(dict(name="Your picks", strategy="update", settings={"variant": "gbm"}, follow_rate=0.33,
                                  members=[dict(code="T4")], candidate_id=None))
    assert v == dict(name=R.BASIC_NAME, strategy="taker", basic=True, follow_rate=0.33)
    assert R.basic_position(dict(market_key="tok", candidate_id=18)) == dict(market_key="tok")


# --- database: blends as Lab candidates, the MCP tools for a basic caller ---------------------------------------

def _seed(c):
    c.execute(text("INSERT INTO sports (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
    c.execute(text("INSERT INTO leagues (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
    c.execute(text("""INSERT INTO competitions (code, name, league_id, sport_id)
                      SELECT 'f1_wdc', 'F1', l.id, s.id FROM leagues l, sports s WHERE l.code = 'f1' AND s.code = 'f1'
                      ON CONFLICT DO NOTHING"""))


def test_blends_and_basic_draws_load_from_the_candidates(test_engine):
    with test_engine.begin() as c:
        _seed(c)
        ids = PF.ensure_candidates(c)
        assert set(PF.TAKER_TOP) <= set(ids) and "TB" not in ids
        src = c.execute(text("SELECT params->>'source', params->>'year' FROM model_runs WHERE id = :i"),
                        dict(i=ids["T3"])).one()
        assert tuple(src) == ("taker-resweep", "2026")
        tb = PF.load(c, "TB")
        assert tb["candidate_id"] is None and [m["code"] for m in tb["members"]] == ["T1", "T8"]
        assert [m["member"]["candidate_id"] for m in tb["members"]] == [ids["T1"], ids["T8"]]
        assert tb["strategy"] == "update" and tb["name"] == PF.PROFILES["TB"]["name"]
        uid = c.execute(text("""INSERT INTO users (username, password_hash, role) VALUES ('picks_basic', 'x', 'basic')
                                RETURNING id""")).scalar()
        bp = R.basic_profile(c, uid)
        assert bp["name"] == R.BASIC_NAME and bp["basic"] and tuple(m["code"] for m in bp["members"]) == R.basic_members(uid)
        assert all(abs(m["weight"] - 1 / 3) < 1e-12 for m in bp["members"])
        assert R.allowed_profile("basic", bp, user_id=uid) and not R.allowed_profile("basic", tb, user_id=uid)
        PF.assign(c, uid, bp)
        assert PF.of_user(c, uid)["members"] == json.loads(json.dumps(bp["members"]))
        c.execute(text("DELETE FROM users WHERE id = :u"), dict(u=uid))


def _member_out(code, cid, shares):
    sig = dict(market_key=f"tok-{cid}", kind="race_h2h", subject="Zed ahead of Yan", stage="after FP2",
               dedupe="after FP2", action="buy", side="YES", shares=shares, limit_price=0.41, fair=0.5234, price=0.40,
               edge=0.1234, heat=2, target_cost=shares * 0.41, signal_ts=pd.Timestamp("2099-01-01"),
               detail=dict(ev=1.4, side_prob=0.5234, member=code))
    prof = dict(candidate_id=cid, name=R.BASIC_NAME, strategy="early" if code == "T8" else "update", member=code)
    return dict(profile=prof, event=dict(event_key="2099-02", name="Test GP"), race_id=None,
                stages=[("after FP2", pd.Timestamp("2099-01-01"), None, pd.Timestamp("2099-01-01"))],
                signals=[sig], positions=[dict(market_key=f"tok-{cid}", kind="race_h2h", subject="Zed ahead of Yan",
                                               yes_shares=shares, no_shares=0.0, cash=-shares * 0.41, mark=0.42,
                                               outcome=None)])


def test_mcp_tools_hide_the_strategy_from_a_basic_caller(test_engine):
    from racinglines.mcp import tools as T
    with test_engine.begin() as c:
        uid = c.execute(text("""INSERT INTO users (username, password_hash, role) VALUES ('picks_mcp', 'x', 'basic')
                                RETURNING id""")).scalar()
        other = c.execute(text("""INSERT INTO users (username, password_hash, role) VALUES ('picks_other', 'x', 'pro')
                                  RETURNING id""")).scalar()
        for code, cid in (("T4", 900004), ("T8", 900008)):
            SG.store(c, uid, _member_out(code, cid, 30.0), follow_rate=None, history=True)
        SG.store(c, other, _member_out("T2", 900002, 30.0), follow_rate=None, history=True)
    try:
        with test_engine.connect() as c:
            me = dict(id=uid, username="picks_mcp", role="basic")
            sig = T.list_signals(c, viewer=me)
            out = json.dumps(sig, default=str)
            assert '"Your picks"' in out and '"stars"' in out
            for leak in ("T4", "T8", "T2", '"early"', '"update"', "0.5234", "0.1234", '"fair"', '"edge"', "member",
                         "picks_other"):
                assert leak not in out, leak
            pos = json.dumps(T.list_positions(c, "picks_other", viewer=me), default=str)   # its own, whoever it names
            assert "picks_mcp" in pos and "tok-900002" not in pos and "candidate" not in pos
            tr = json.dumps(T.track_record(c, "picks_other", venue="all", viewer=me), default=str)
            assert "T4" not in tr and "T8" not in tr and "picks_other" not in tr
            # pro / admin (and stdio, viewer None): as before, every column, no rating
            full = json.dumps(T.list_signals(c, user="picks_mcp", viewer=dict(id=other, username="picks_other", role="pro")),
                              default=str)
            assert '"fair"' in full and '"edge"' in full and "stars" not in full and "_member" not in full
            assert full == json.dumps(T.list_signals(c, user="picks_mcp"), default=str)
    finally:
        with test_engine.begin() as c:
            c.execute(text("DELETE FROM strategy_signals WHERE user_id IN (:a, :b)"), dict(a=uid, b=other))
            c.execute(text("DELETE FROM paper_positions WHERE user_id IN (:a, :b)"), dict(a=uid, b=other))
            c.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), dict(a=uid, b=other))
