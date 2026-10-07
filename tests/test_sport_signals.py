"""Live paper signals for every sport and venue (pipelines/sport_signals.py), each venue's paper rows kept apart
(signals.store), and the board-update log: `f1 forecast --save` and a live reprice each write one data_changes row."""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.pipelines import position_replay as P
from racinglines.pipelines import profiles as PF
from racinglines.pipelines import signals as SG
from racinglines.pipelines import sport_signals as SPS

from test_nascar import db, raw  # noqa: F401  (fixtures)
from test_nascar_links import world  # noqa: F401  (fixture: the fixtures' 2026 Cup races and drivers)
from test_position_replay import _seed, _wipe


def _user(c, name):
    return c.execute(text("""INSERT INTO users (username, password_hash, role) VALUES (:n, 'x', 'taker')
                             RETURNING id"""), dict(n=name)).scalar()


# --- each venue's positions are its own -------------------------------------------------------------------

def test_a_run_replaces_only_its_own_venues_positions(test_engine):
    """The bug from PR #85: a Polymarket run deleted every venue's rows but Kalshi's (OG.com's, the live maker's)."""
    prof = dict(candidate_id=999998, name="V · test", strategy="maker")    # a maker: every position kept
    pos = dict(market_key="tok", kind="race_win", subject="X", yes_shares=10.0, no_shares=0.0, cash=-4.1, mark=0.42,
               outcome=None)
    out = lambda venue, key: dict(profile=prof, event=dict(event_key="2099-02", name="Test GP"), race_id=None,   # noqa: E731
                                  stages=[], signals=[], positions=[dict(pos, market_key=key)], venue=venue)
    with test_engine.begin() as c:
        uid = _user(c, "venuetest-og")
        c.execute(text("""INSERT INTO paper_positions (user_id, candidate_id, event_key, market_key, kind, yes_shares,
                          no_shares, cash, venue) VALUES (:u, 999998, '2099-02', 'live-maker', 'race_win', 1, 0, 0,
                          'private')"""), dict(u=uid))
        rows = lambda: sorted(c.execute(text("SELECT market_key, venue FROM paper_positions WHERE user_id = :u"),  # noqa: E731
                                        dict(u=uid)).all())
        SG.store(c, uid, out("polymarket", "pm-tok"))
        SG.store(c, uid, out("og", "og-tok"))
        SG.store(c, uid, out("kalshi", "kx-tok"))
        want = [("kx-tok", "kalshi"), ("live-maker", "private"), ("og-tok", "og"), ("pm-tok", "polymarket")]
        assert rows() == want
        SG.store(c, uid, dict(out("og", "og-tok"), positions=[]))          # an OG.com run: OG.com's rows only
        assert rows() == [w for w in want if w[1] != "og"]
        SG.store(c, uid, dict(out("polymarket", "pm-tok"), positions=[]))  # a Polymarket run: Polymarket's only
        assert rows() == [("kx-tok", "kalshi"), ("live-maker", "private")]
        SG.store(c, uid, out("og", "og-tok"))
        SG.store(c, uid, dict(out("polymarket", "pm-tok"), positions=[]))
        assert ("og-tok", "og") in rows()                                   # and vice versa


# --- profiles per sport ---------------------------------------------------------------------------------

@pytest.mark.quick
def test_a_sports_profile_lives_under_its_own_key_and_f1s_are_unchanged():
    assert PF.pref() == "strategy_profile" and PF.pref("kalshi") == "strategy_profile_kalshi"
    assert PF.pref("kalshi", "nascar") == "strategy_profile_nascar_kalshi"
    assert PF.pref("og", "motogp") == "strategy_profile_motogp_og"
    assert SPS.sport_of({}) == "f1" and SPS.sport_of(dict(sport="nascar")) == "nascar"


# --- a NASCAR signals pass on Kalshi ------------------------------------------------------------------

def test_a_nascar_signals_pass_writes_paper_rows_tagged_with_sport_and_venue(world, test_engine, monkeypatch, tmp_path):
    from conftest import TEST_DB
    monkeypatch.setenv("RACINGLINES_RECORDS_DIR", str(tmp_path))
    with world() as s:
        rs = P.races(s.connection(), P.spec("nascar"), [2026])
        race = rs.iloc[-1]
        res = P.race_results(s.connection(), race.race_id)
        top = res.sort_values("position")["athlete_id"].astype(int).tolist()
        _wipe(s)
        _seed(s, race, res, {top[0]: 0.05, top[1]: 0.40, top[2]: 0.25, top[-1]: 0.30})      # a coherent group
    now = pd.Timestamp(race.start) + pd.Timedelta(hours=1)          # every [replay] stage has passed
    settings = {"venue": "kalshi", "sims": 500, "market_kinds": "race_win"}
    taker = dict(candidate_id=999990, name="N · nascar taker (test)", strategy="update", settings=settings)
    maker = dict(candidate_id=999991, name="NM · nascar maker (test)", strategy="maker", settings=settings)
    try:
        with test_engine.begin() as c:
            ut, um = _user(c, "nascar-taker-test"), _user(c, "nascar-maker-test")
            PF.assign(c, ut, taker, venue="kalshi", sport="nascar")
            PF.assign(c, um, maker, venue="kalshi", sport="nascar")
            assert PF.of_user(c, ut, venue="kalshi", sport="nascar")["sport"] == "nascar"
            assert PF.of_user(c, ut, venue="kalshi") is None                   # F1's Kalshi profile: untouched
            n0 = c.execute(text("SELECT count(*) FROM data_changes WHERE kind = 'live-price'")).scalar()
        for _, t in P.stage_times(race.start, P.spec("nascar")):        # the 5-minute timer's pass after each stage
            SPS.run_all(test_engine, TEST_DB, "nascar", venues=["kalshi"], now=t + pd.Timedelta(minutes=5),
                        fetch=False, alert=False, echo=lambda *a: None)
        rep = SPS.run_all(test_engine, TEST_DB, "nascar", venues=["kalshi"], now=now, fetch=False, alert=False,
                          echo=lambda *a: None)                         # after the race: settled
        assert {r["profile"] for r in rep} == {taker["name"], maker["name"]}
        with test_engine.connect() as c:
            runs = c.execute(text("""SELECT id, params FROM model_runs WHERE params->>'mode' = :m
                                     AND params->>'event_key' = :k ORDER BY id"""),
                             dict(m=SPS.LIVE_MODE, k=race.event_key)).all()
            assert [r[1]["sweep_stage"] for r in runs] == ["T-3d", "T-1d", "race eve"]      # one stored run per stage
            assert all(r[1]["sport"] == "nascar" and r[1]["live"] for r in runs)
            logged = c.execute(text("SELECT sport, detail FROM data_changes WHERE kind = 'live-price' ORDER BY id")).all()
            assert len(logged) - n0 == 3 and logged[-1][0] == "nascar"                  # one row per new run
            d = logged[-1][1]
            assert d["run"] == runs[-1][0] and d["events"] == [race.event_key] and d["sims"] == 500
            assert {"variant", "code_version", "data_key"} <= set(d)
            sig = c.execute(text("""SELECT detail->>'sport', detail->>'venue', event_key, run_id FROM strategy_signals
                                    WHERE user_id = :u"""), dict(u=ut)).all()
            assert sig and {(a, b, e) for a, b, e, _ in sig} == {("nascar", "kalshi", race.event_key)}
            assert {r for *_, r in sig} <= {r[0] for r in runs}
            pos = c.execute(text("SELECT venue, event_key, outcome FROM paper_positions WHERE user_id = :u"),
                            dict(u=ut)).all()
            assert pos and {(v, e) for v, e, _ in pos} == {("kalshi", race.event_key)}
            assert all(o is not None for *_, o in pos)                    # the race is run: settled on the result
            mk = c.execute(text("SELECT venue, event_key FROM paper_positions WHERE user_id = :u"), dict(u=um)).all()
            assert {tuple(r) for r in mk} <= {("kalshi", race.event_key)}
        n_sig = len(sig)
        SPS.run_all(test_engine, TEST_DB, "nascar", venues=["kalshi"], now=now, fetch=False, alert=False,
                    echo=lambda *a: None)                                     # the next 5-minute pass
        with test_engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM data_changes WHERE kind = 'live-price'")).scalar() - n0 == 3
            assert c.execute(text("SELECT count(*) FROM model_runs WHERE params->>'mode' = :m AND params->>'event_key' = :k"),
                             dict(m=SPS.LIVE_MODE, k=race.event_key)).scalar() == 3      # reused, not re-stored
            assert c.execute(text("SELECT count(*) FROM strategy_signals WHERE user_id = :u"), dict(u=ut)).scalar() == n_sig
        replay = SPS.compute(test_engine, TEST_DB, dict(taker, sport="nascar"), now=now, event=race.event_key,
                             live=False, fetch=False, echo=lambda *a: None)
        assert replay["sport"] == "nascar" and replay["venue"] == "kalshi" and [x[2] for x in replay["stages"]] == [None] * 3
        assert "N · nascar taker" in SG.format_replay(replay)
    finally:
        with test_engine.begin() as c:
            c.execute(text("""DELETE FROM users WHERE username IN ('nascar-taker-test', 'nascar-maker-test')"""))
            ids = c.execute(text("SELECT id FROM model_runs WHERE params->>'mode' = :m"), dict(m=SPS.LIVE_MODE)).scalars().all()
            c.execute(text("DELETE FROM race_predictions WHERE model_run_id = ANY(:i)"), dict(i=ids))
            c.execute(text("DELETE FROM model_runs WHERE id = ANY(:i)"), dict(i=ids))
            c.execute(text("DELETE FROM data_changes WHERE kind = 'live-price' AND sport = 'nascar'"))
        with world() as s:
            _wipe(s)


# --- the board-update log ---------------------------------------------------------------------------------

def test_f1_forecast_save_and_a_live_reprice_each_log_one_change(test_engine, monkeypatch):
    from types import SimpleNamespace

    from conftest import TEST_DB
    from racinglines.cli import f1 as CLI
    from racinglines.models.position_sim import pricing as run
    from racinglines.pipelines import sweep_settings as SS
    view = SimpleNamespace(res=pd.DataFrame(dict(position=[1.0, 2.0])))
    meas = SimpleNamespace(view=lambda cutoff: view)
    monkeypatch.setattr(run.Measurements, "load", staticmethod(lambda engine: meas))
    monkeypatch.setattr(run, "history", lambda meas, use_track: None)
    summ = pd.DataFrame(dict(driver=["A"], team_key=["t"], win_prob=[0.5], podium_prob=[0.9], top10_prob=[1.0],
                             dnf_prob=[0.0], exp_points=[20.0]))
    model = SimpleNamespace(coef=np.zeros(len(run.M.FEATURES)), sigma=1.0, sigma_q=1.0)
    extras = dict(model=model, cutoff="2099-03-01 00:00:00", latest_data="x", drift=0.0, race_constructor_top={},
                  constructors=pd.DataFrame(dict(team=["t"], current_points=[0], exp_points=[1.0], champion_prob=[1.0])))
    per_event = [dict(round=1, name="Test GP", date=pd.Timestamp("2099-03-02"), summary=summ)]
    standings = pd.DataFrame(dict(driver=["A"], current_points=[0], exp_points=[20.0], champion_prob=[1.0], top3_prob=[1.0]))
    monkeypatch.setattr(run, "forecast", lambda *a, **k: (per_event, standings, extras))
    monkeypatch.setattr(run, "save_forecast", lambda *a, **k: 424242)
    count = lambda c, kind: c.execute(text("SELECT count(*) FROM data_changes WHERE kind = :k"), dict(k=kind)).scalar()  # noqa: E731
    with test_engine.connect() as c:
        n0 = count(c, "forecast")
    CLI.main(["--db", TEST_DB, "forecast", "--year", "2099", "--sims", "100", "--save"])
    with test_engine.connect() as c:
        assert count(c, "forecast") - n0 == 1
        sport, d = c.execute(text("SELECT sport, detail FROM data_changes WHERE kind = 'forecast' ORDER BY id DESC LIMIT 1")).one()
    assert sport == "f1" and d["run"] == 424242 and d["events"] == ["2099-01"] and d["sims"] == 100
    assert d["variant"] == "baseline" and d["data_key"] == SS.data_key(view) and "code_version" in d
    CLI.main(["--db", TEST_DB, "forecast", "--year", "2099", "--sims", "100"])          # no --save: nothing logged
    with test_engine.connect() as c:
        assert count(c, "forecast") - n0 == 1
        n1 = count(c, "live-price")
    st = SS.Settings.from_dict({"variant": "gbm"})
    SG.log_live_price(TEST_DB, "2099-01", 77, st, "dk", stage=SG.NOW_STAGE)
    with test_engine.connect() as c:
        assert count(c, "live-price") - n1 == 1
        d = c.execute(text("SELECT detail FROM data_changes WHERE kind = 'live-price' ORDER BY id DESC LIMIT 1")).scalar()
    assert d["run"] == 77 and d["variant"] == "gbm" and d["sims"] == st["sims"] and d["data_key"] == "dk"
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM data_changes WHERE detail->>'run' IN ('424242', '77')"))


def test_the_signal_engine_logs_a_live_reprice_only_when_it_stores_a_run(monkeypatch):
    """price_upcoming and price_stages_now call log_live_price right after save_diagnostic, and only there."""
    import inspect
    for fn in (SG.price_upcoming, SG.price_stages_now):
        src = inspect.getsource(fn)
        assert src.count("log_live_price(") == 1 and src.index("save_diagnostic(") < src.index("log_live_price(")
