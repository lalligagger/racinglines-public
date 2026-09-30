"""The NASCAR / MotoGP demo paper portfolio (pipelines/sport_paper.py): the selection from a settings grid, the rows it
stores (never the debug buy_all mode), and the app's reading of them behind RACINGLINES_SPORT_PAPER."""

import json

import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.pipelines import position_replay as P
from racinglines.pipelines import sport_paper as SP


def _grid(folder, nets):
    """A grid folder: nets = {(year, edge, vol): {kind: pnl}} -> <year>-e<edge>-v<vol>/kalshi/{summary.json,trades.csv}.
    One trade per kind at 0.99 (so Kalshi's fee is a cent), plus a buy_all_trades.csv that must never count."""
    for (y, e, v), by in nets.items():
        d = folder / f"{y}-e{e}-v{v}" / "kalshi"
        d.mkdir(parents=True)
        (d / "summary.json").write_text(json.dumps(dict(params=dict(kinds=["race_win", "race_top10"]), totals={})))
        pd.DataFrame([dict(kind=k, pnl=p, mid=0.99, shares=1.0, side="YES") for k, p in by.items()]).to_csv(d / "trades.csv", index=False)
        pd.DataFrame([dict(kind="race_win", pnl=1e6, mid=0.5, shares=1.0, side="YES")]).to_csv(d / "buy_all_trades.csv", index=False)


@pytest.mark.quick
def test_the_best_setting_per_kind_is_the_best_worse_season_and_buy_all_never_counts(tmp_path):
    _grid(tmp_path, {(2025, 0.05, 50): dict(race_win=100, race_top10=-50), (2026, 0.05, 50): dict(race_win=10, race_top10=-20),
                     (2025, 0.1, 200): dict(race_win=40, race_top10=-5), (2026, 0.1, 200): dict(race_win=30, race_top10=-1),
                     (2026, 0.15, 50): dict(race_win=500)})           # one season only: never picked
    sel = SP.pick(tmp_path)
    assert sel["seasons"] == [2025, 2026]
    assert (sel["kinds"]["race_win"]["edge"], sel["kinds"]["race_win"]["volume"]) == (0.1, 200)   # worse season 30 > 10
    assert sel["kinds"]["race_top10"]["worse"] < 0 and set(sel["traded"]) == {"race_win"}          # a loser isn't traded
    assert (sel["blend"]["edge"], sel["blend"]["volume"]) == (0.1, 200)
    assert SP.settings_for(sel) == {(0.1, 200.0): ["race_win"]}
    assert SP.settings_for(sel, "blend") == {(0.1, 200.0): ["race_top10", "race_win"]}
    assert abs(sel["kinds"]["race_win"]["seasons"][2025] - (40 - 0.01)) < 1e-9                     # net of Kalshi's fee
    md = SP.selection_md("nascar", sel)
    assert "In-sample" in md and "buy_all mode is never included" in md and "1000000" not in md.replace(",", "")
    with pytest.raises(ValueError):
        SP.pick(tmp_path / "empty")


@pytest.mark.quick
def test_a_season_with_no_markets_is_left_out_of_the_worse_season_test(tmp_path):
    """MotoGP 2025: the grid ran it, but Kalshi listed no race markets, so no setting traded; the pick rests on 2026
    (a $0 season would otherwise veto every kind)."""
    _grid(tmp_path, {(2025, 0.05, 50): {}, (2026, 0.05, 50): dict(race_win=20),
                     (2025, 0.1, 200): {}, (2026, 0.1, 200): dict(race_win=5)})
    sel = SP.pick(tmp_path)
    assert sel["seasons"] == [2025, 2026] and set(sel["traded"]) == {"race_win"}
    assert sel["kinds"]["race_win"]["edge"] == 0.05 and list(sel["kinds"]["race_win"]["seasons"]) == [2026]
    assert sel["kinds"]["race_top10"] is None and sel["blend"]["edge"] == 0.05
    assert "no markets" in SP.selection_md("motogp", sel)


@pytest.mark.quick
def test_best_effort_always_gives_a_sport_a_record(tmp_path):
    """--book best: kinds with a positive total at their best setting; with none positive, every kind at the one
    setting with the best total, a loss shown as a loss (the strict rule would trade nothing here)."""
    _grid(tmp_path, {(2025, 0.05, 50): dict(race_win=-30, race_top10=-5), (2026, 0.05, 50): dict(race_win=20, race_top10=-5),
                     (2025, 0.1, 200): dict(race_win=-50, race_top10=-2), (2026, 0.1, 200): dict(race_win=60, race_top10=-1)})
    sel = SP.pick(tmp_path)
    assert not sel["traded"] and SP.settings_for(sel) == {}
    assert set(sel["best_traded"]) == {"race_win"} and SP.settings_for(sel, "best") == {(0.1, 200.0): ["race_win"]}
    _grid(tmp_path / "loss", {(2025, 0.05, 50): dict(race_win=-30), (2026, 0.05, 50): dict(race_win=-5),
                              (2025, 0.1, 200): dict(race_win=-50), (2026, 0.1, 200): dict(race_win=-1)})
    sel = SP.pick(tmp_path / "loss")
    assert not sel["best_traded"] and SP.settings_for(sel, "best") == {(0.05, 50.0): ["race_win"]}   # a kind with no markets stays out
    assert "nothing positive" in SP.selection_md("nascar", sel)


@pytest.mark.quick
def test_a_race_stores_the_takers_update_trades_net_of_fees_only():
    t0 = pd.Timestamp("2026-09-26 18:00")
    markets = [dict(key="K-1", kind="race_win", subject="A", outcome=True,
                    stages=[dict(label="race eve", t=t0, fair=0.5, price=0.2, tradeable=True, open=True)]),
               dict(key="K-2", kind="race_win", subject="B", outcome=False,
                    stages=[dict(label="race eve", t=t0, fair=0.21, price=0.2, tradeable=True, open=True)])]   # no edge
    sigs, pos = SP.race_rows({(0.05, 50.0): markets}, "kalshi", "nascar", "kinds")
    assert {s["market_key"] for s in sigs} == {"K-1"} and [p["market_key"] for p in pos] == ["K-1"]
    d = sigs[0]["detail"]
    assert d["sport"] == "nascar" and d["mode"] == "update" and d["in_sample"] and d["setting"]["min_edge"] == 0.05
    assert d["fee"] > 0 and abs(pos[0]["cash"] + sigs[0]["shares"] * sigs[0]["limit_price"] + d["fee"]) < 1e-9
    assert SP.MODE != SP.BUY_ALL


@pytest.mark.quick
def test_the_switch_is_off_by_default(monkeypatch):
    monkeypatch.delenv(SP.SWITCH, raising=False)
    assert not SP.enabled()
    monkeypatch.setenv(SP.SWITCH, "1")
    assert SP.enabled()
    assert SP.event_sources()[0] == "f1timing" and {"nascar_cf", "motogp_api"} <= set(SP.event_sources())


# --- on the test database: a NASCAR race, the demo account's rows, and the app ----------------------------------

from test_nascar import db, raw  # noqa: E402,F401  (fixtures)
from test_nascar_links import world  # noqa: E402,F401
from test_position_replay import _seed, _wipe  # noqa: E402


def test_the_demo_rows_reach_the_app_only_with_the_switch_and_never_buy_all(world, test_engine, monkeypatch):
    from racinglines.pipelines import story
    from racinglines.web import app as A
    monkeypatch.setenv("RACINGLINES_BUY_ALL", "1")                    # the writer switches it off regardless
    monkeypatch.setenv(SP.SWITCH, "1")
    with world() as s:
        rs = P.races(s.connection(), P.spec("nascar"), [2026])
        race = rs.iloc[-1]
        res = P.race_results(s.connection(), race.race_id)
        top = res.sort_values("position")["athlete_id"].astype(int).tolist()
        _wipe(s)
        _seed(s, race, res, {top[0]: 0.05, top[1]: 0.40, top[2]: 0.25, top[-1]: 0.30})
        s.execute(text("DELETE FROM users WHERE username = 'sptest'"))
        uid = s.execute(text("""INSERT INTO users (username, password_hash, role, prefs) VALUES ('sptest', 'x', 'taker',
                                '{"strategy_profile": {"name": "A", "strategy": "update", "settings": {}}}') RETURNING id""")).scalar()
        s.commit()
        try:
            rep = SP.backfill(test_engine, "nascar", {(0.05, 50.0): ["race_win"]}, usernames=["sptest"], seasons=[2026],
                              echo=lambda *a: None)
            assert [r[1] for r in rep] == [race.event_key]
            sig = s.execute(text("SELECT strategy, detail FROM strategy_signals WHERE user_id = :u"), dict(u=uid)).all()
            assert sig and {x[0] for x in sig} == {"update"} and all(x[1]["mode"] == "update" and x[1]["sport"] == "nascar"
                                                                     and x[1]["venue"] == "kalshi" for x in sig)
            pos = s.execute(text("SELECT venue, event_key, outcome FROM paper_positions WHERE user_id = :u"), dict(u=uid)).all()
            assert pos and {p[0] for p in pos} == {"kalshi"} and {p[1] for p in pos} == {race.event_key}
            pnl = rep[0][4]
            again = SP.backfill(test_engine, "nascar", {(0.05, 50.0): ["race_win"]}, usernames=["sptest"], seasons=[2026],
                                echo=lambda *a: None)
            assert again == rep and s.execute(text("SELECT count(*) FROM strategy_signals WHERE user_id = :u"),
                                              dict(u=uid)).scalar() == len(sig)          # a rebuild replaces its rows
            # a buy_all row (as a debug run might leave it) never reaches the record or the nav
            s.execute(text("""INSERT INTO strategy_signals (user_id, profile, strategy, event_key, market_key, kind, stage,
                                  dedupe, action, side, shares, limit_price, detail, status)
                              VALUES (:u, 'debug', 'buy_all', '2026-9999', 'BA-1', 'race_win', 'x', 'x', 'buy', 'YES', 1, 0.5,
                                      '{"sport": "nascar", "mode": "buy_all", "backfill": true, "venue": "kalshi"}', 'new')"""),
                      dict(u=uid))
            s.execute(text("""INSERT INTO paper_positions (user_id, event_key, market_key, kind, yes_shares, no_shares, cash,
                                  outcome, venue) VALUES (:u, '2026-9999', 'BA-1', 'race_win', 1000, 0, 0, true, 'kalshi')"""),
                      dict(u=uid))
            s.commit()
            with test_engine.connect() as c:
                on = story.track_record(c, uid, sports=True)
                off = story.track_record(c, uid)
                keys = set(c.execute(text(SP.SPORT_KEYS), dict(u=uid)).scalars())
            assert keys == {race.event_key}
            assert [r["event_key"] for r in on] == [race.event_key] and on[0]["demo"] and on[0]["event_name"]
            assert abs(on[0]["pnl"] - pnl) < 1e-6 and not off                       # switch off: the record as before
            monkeypatch.setattr(A, "get_engine", lambda: test_engine)
            user = dict(id=uid, role="taker", username="sptest")
            assert abs(A._signals_nav(user)["pnl"] - pnl) < 1e-6                     # Kalshi demo rows, no buy_all
            _pages(monkeypatch, uid, race)
            _status_and_pro(monkeypatch, s, uid, race)
            monkeypatch.setenv(SP.SWITCH, "0")
            assert A._signals_nav(user)["pnl"] == 0.0
            assert SP.reset(test_engine, ["sptest"], "nascar") == (len(sig), len(pos))
        finally:
            s.rollback()
            s.execute(text("DELETE FROM users WHERE username = 'sptest'"))
            s.commit()
            _wipe(s)


def _pages(monkeypatch, uid, race):
    """Positions and Signals as the account sees them: the NASCAR race labelled a demo replay (switch on), or absent."""
    from fastapi.testclient import TestClient

    from conftest import TEST_DB
    from racinglines.db import config
    from racinglines.web import users as U
    from racinglines.web.app import app
    with config.get_engine(TEST_DB).begin() as c:
        c.execute(text("UPDATE users SET password_hash = :h WHERE id = :u"), dict(h=U.hash_password("pw"), u=uid))
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    config.get_engine.cache_clear()
    try:
        cl = TestClient(app)
        cl.post("/login", data=dict(username="sptest", password="pw"))
        for on in ("1", "0"):
            monkeypatch.setenv(SP.SWITCH, on)
            pos, st = cl.get("/positions"), cl.get("/strategy")
            assert pos.status_code == 200 and st.status_code == 200
            ev = cl.get(f"/positions?event={race.event_key}")
            assert ev.status_code == 200
            for page in (pos.text, st.text):
                assert ("demo replay, in-sample" in page) == (on == "1")
            assert (race["name"] in st.text) == (on == "1")
            assert "2026-9999" not in pos.text + st.text                          # the buy_all row, never shown
    finally:
        monkeypatch.setenv(SP.SWITCH, "1")
        config.get_engine.cache_clear()


def _status_and_pro(monkeypatch, s, uid, race):
    """RACINGLINES_SPORT_STATUS=1: Markets lists every sport with its race data, markets, model, backtests and paper
    record (NASCAR's demo rows counted, the buy_all row not); off, the page is as before. A Pro account running the
    taker on NASCAR sees its record split by sport and strategy on Strategy."""
    from fastapi.testclient import TestClient

    from conftest import TEST_DB
    from racinglines import sports
    from racinglines.db import config
    from racinglines.web import sport_status as SS
    from racinglines.web.app import app
    with config.get_engine(TEST_DB).connect() as c:
        st = {r["sport"]: r for r in SS.status(c)}
    assert set(st) == set(sports.SPORT_CODES)                                   # every sport, data or not
    assert st["nascar"]["races"]["state"] in ("ok", "partial") and st["nascar"]["paper"]["state"] == "ok"
    assert "sptest 1 races" in st["nascar"]["paper"]["text"]                    # the buy_all race is not counted
    assert st["indycar"]["model"]["state"] == "na" and st["mtb_dh"]["paper"]["state"] == "none"
    s.execute(text("UPDATE users SET role = 'pro' WHERE id = :u"), dict(u=uid))
    s.commit()
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    config.get_engine.cache_clear()
    try:
        cl = TestClient(app)
        cl.post("/login", data=dict(username="sptest", password="pw"))
        for on in ("1", "0"):
            monkeypatch.setenv(SS.SWITCH, on)
            page = cl.get("/markets")
            assert page.status_code == 200
            assert ("Every sport: status" in page.text) == (on == "1")
            if on == "1":
                assert "NASCAR" in page.text and "tape only" in page.text and "buy_all" not in page.text
        # a replay save (`nascar replay --save`: an as-of run before the race) puts NASCAR's model on the board: the
        # section says so, and the recent race shows what the model had on its winner
        res = P.race_results(s.connection(), race.race_id).sort_values("position")
        winner = int(res["athlete_id"].iloc[0])
        comp = s.execute(text("SELECT id FROM competitions WHERE code = 'nascar_cup'")).scalar()
        cutoff = pd.Timestamp(race.start) - pd.Timedelta(days=1)
        rid = s.execute(text("""INSERT INTO model_runs (competition_id, model, kind, params) VALUES (:c, 'test', 'diagnostic',
                                  CAST(:p AS jsonb)) RETURNING id"""),
                        dict(c=comp, p=json.dumps(dict(replay_batch="replay-test", event_key=race.event_key,
                                                       cutoff=str(cutoff))))).scalar()
        s.execute(text("""INSERT INTO race_predictions (model_run_id, race_id, target, athlete_id, win_prob)
                          VALUES (:m, :r, 'asof:test', :a, 0.123)"""), dict(m=rid, r=int(race.race_id), a=winner))
        s.commit()
        try:
            monkeypatch.setenv(SS.SWITCH, "1")
            page = cl.get("/markets")
            assert page.status_code == 200 and "pre-race prices for 1 past races" in page.text
            assert "we had <b>12%</b>" in page.text or "we had 12%" in page.text
            monkeypatch.setenv(SS.SWITCH, "0")
            assert "pre-race prices for" not in cl.get("/markets").text                  # switch off: as before
        finally:
            s.execute(text("DELETE FROM model_runs WHERE id = :m"), dict(m=rid))
            s.commit()
        st = cl.get("/strategy")
        assert st.status_code == 200 and "Where the P&amp;L came from" in st.text and ">taker<" in st.text
    finally:
        s.execute(text("UPDATE users SET role = 'taker' WHERE id = :u"), dict(u=uid))
        s.commit()
        config.get_engine.cache_clear()
