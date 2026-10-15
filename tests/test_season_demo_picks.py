"""The season demo's Jev options (fantasy/season_demo.py: picks_plan, apply_picks, export_styles, read_only;
reports/2026-10-15-jev-player/PREREG.md): one player's rows follow a picks file round by round, the export never
writes, and both stay inside a demo database."""
import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.fantasy import season_demo as SD
from racinglines.pipelines import profiles as PF
from test_season_demo import _fake_compute, players_db  # noqa: F401  (the shared fixture)

PICKS = {"rounds": {"3": {"code": "T8", "sizing": "kelly", "kelly": 0.25},
                    "4": {"code": "T1", "sizing": "standard", "kelly": None},
                    "5": {"code": "T5", "sizing": "kelly", "kelly": 0.5},
                    "6": {"code": "T2", "sizing": "standard", "kelly": None}}}


def test_picks_plan_maps_each_raced_round():
    assert SD.picks_plan(PICKS, [3, 4, 5]) == {3: ("T8", 0.25), 4: ("T1", None), 5: ("T5", 0.5)}
    assert SD.picks_plan(PICKS, [1, 2]) == {}
    with pytest.raises(ValueError, match="style"):
        SD.picks_plan({"rounds": {"1": {"code": "A", "sizing": "standard"}}}, [1])
    with pytest.raises(ValueError, match="round 2"):
        SD.picks_plan({"rounds": {"2": {"sizing": "standard"}}}, [2])
    with pytest.raises(ValueError, match="sizing"):
        SD.picks_plan({"rounds": {"1": {"code": "T1", "sizing": "kelly", "kelly": 3}}}, [1])


def _setup(monkeypatch):
    from racinglines.pipelines import signals as SG
    from racinglines.pipelines import weekend_sweep as WS
    sched = {r: dict(event_key=f"2026-{r:02d}", name=f"GP {r}", race_start=pd.Timestamp(f"2026-0{r}-10 14:00"),
                     format="conventional") for r in (3, 4, 5, 6)}
    sched[6]["race_start"] = pd.Timestamp("2026-12-01 14:00")              # not raced yet
    calls = []
    monkeypatch.setattr(WS, "schedule", lambda year: sched)
    monkeypatch.setattr(SG, "compute_all", _fake_compute(calls))
    codes = list(PF.PROFILES)
    monkeypatch.setattr(PF, "ensure_candidates", lambda c, history=False: {k: i + 1 for i, k in enumerate(codes)})
    monkeypatch.setattr(PF, "load", lambda c, ref: dict(
        candidate_id=int(ref) if str(ref).isdigit() else codes.index(ref) + 1,
        name=PF.PROFILES[codes[int(ref) - 1] if str(ref).isdigit() else ref]["name"], strategy="update", settings={}))
    return calls, codes


def test_apply_picks_writes_each_round_with_its_style(players_db, monkeypatch):  # noqa: F811
    calls, codes = _setup(monkeypatch)
    url = players_db.url.render_as_string(hide_password=False)
    with pytest.raises(ValueError, match="demo"):
        SD.apply_picks(players_db, url, "ada", PICKS, now="2026-10-13", apply=True, echo=lambda m: None)
    monkeypatch.setattr(SD, "is_demo_db", lambda url: True)
    plan, rep = SD.apply_picks(players_db, url, "ada", PICKS, now="2026-10-13", apply=False, echo=lambda m: None)
    assert plan == {3: ("T8", 0.25), 4: ("T1", None), 5: ("T5", 0.5)} and rep == [] and calls == []
    with players_db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM strategy_signals")).scalar() == 0
    plan, rep = SD.apply_picks(players_db, url, "ada", PICKS, now="2026-10-13", apply=True, echo=lambda m: None)
    assert [e for _, e in calls] == ["2026-3", "2026-4", "2026-5"]           # round 6 is not raced
    assert [r[1] for r in rep] == ["T8", "T1", "T5"]
    with players_db.connect() as c:
        uid = c.execute(text("SELECT id FROM users WHERE username = 'ada'")).scalar()
        rows = c.execute(text("""SELECT event_key, candidate_id FROM strategy_signals WHERE user_id = :u
                                 ORDER BY event_key"""), dict(u=uid)).all()
        assert [(e, codes[cid - 1]) for e, cid in rows] == [("2026-03", "T8"), ("2026-04", "T1"), ("2026-05", "T5")]
        prof = c.execute(text("SELECT prefs->'strategy_profile' FROM users WHERE id = :u"), dict(u=uid)).scalar()
        assert prof["name"] == PF.PROFILES["T5"]["name"] and prof["sizing"] == "kelly" and prof["kelly"] == 0.5
        assert prof["season_demo"] == "jev" and "follow_rate" not in prof
        others = c.execute(text("SELECT count(*) FROM strategy_signals WHERE user_id <> :u"), dict(u=uid)).scalar()
        assert others == 0
        n = c.execute(text("SELECT count(*) FROM paper_positions WHERE user_id = :u"), dict(u=uid)).scalar()
    SD.apply_picks(players_db, url, "ada", PICKS, now="2026-10-13", apply=True, echo=lambda m: None)   # rerun: same rows
    with players_db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM paper_positions WHERE user_id = :u"), dict(u=uid)).scalar() == n
    with pytest.raises(ValueError, match="no active player"):
        SD.apply_picks(players_db, url, "nobody", PICKS, now="2026-10-13", echo=lambda m: None)


def test_export_styles_is_read_only_and_per_style(players_db, monkeypatch):  # noqa: F811
    calls, _ = _setup(monkeypatch)
    url = players_db.url.render_as_string(hide_password=False)
    with pytest.raises(ValueError, match="demo database only"):
        SD.export_styles(url, now="2026-10-13", echo=lambda m: None)
    monkeypatch.setattr(SD, "is_demo_db", lambda url: True)
    seen = []
    from racinglines.pipelines import signals as SG
    fake = SG.compute_all

    def spy(engine, u, prof, **kw):
        seen.append(u)
        return fake(engine, u, prof, **kw)
    monkeypatch.setattr(SG, "compute_all", spy)
    res = SD.export_styles(url, now="2026-10-13", echo=lambda m: None)
    assert res["meta"]["rounds"] == [3, 4, 5]
    assert set(res["styles"]) == set(PF.ALPHA_ORDER)
    assert res["styles"]["T8"][4]["pnl"] == pytest.approx(6.0)               # 10 shares won at a cost of 4
    assert res["styles"]["T8"][4]["bought"] == pytest.approx(4.0)
    assert len(calls) == 3 * len(PF.ALPHA_ORDER)
    assert all("default_transaction_read_only" in u for u in seen)          # every replay runs read-only
    with players_db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM strategy_signals")).scalar() == 0


def test_read_only_engine_refuses_writes(players_db):  # noqa: F811
    from sqlalchemy.exc import DBAPIError
    eng, _ = SD.read_only(players_db.url.render_as_string(hide_password=False))
    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM users")).scalar() >= 1
    with pytest.raises(DBAPIError, match="read-only"):
        with eng.begin() as c:
            c.execute(text("UPDATE users SET prefs = prefs WHERE false"))
    eng.dispose()


def test_outcome_pnl():
    pos = [dict(cash=-4.0, yes_shares=10.0, no_shares=0.0, outcome=True),
           dict(cash=-3.0, yes_shares=0.0, no_shares=5.0, outcome=False),
           dict(cash=-2.0, yes_shares=5.0, no_shares=0.0, outcome=False),
           dict(cash=-9.0, yes_shares=5.0, no_shares=0.0, outcome=None)]
    assert SD.outcome_pnl(pos) == pytest.approx(6.0 + 2.0 - 2.0)
