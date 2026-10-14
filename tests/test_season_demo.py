"""The alpha's season demo (fantasy/season_demo.py, scripts/vm/season_demo.sh, the staging database switch): the draw is
deterministic and inside its ranges, nothing writes outside a demo database, and the switch only re-points staging."""
from pathlib import Path

import pandas as pd
import pytest

from racinglines.fantasy import season_demo as SD
from racinglines.pipelines import profiles as PF

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "scripts/vm/season_demo.sh").read_text()
VM_SH = (ROOT / "scripts/deploy/vm.sh").read_text()
UPDATE = (ROOT / "deploy/vm/staging/update.sh").read_text()
UNIT = (ROOT / "deploy/vm/systemd/racinglines-staging-web.service").read_text()
USERS = [(i, f"player{i}") for i in range(1, 41)]
ROUNDS = list(range(1, 19))


def code(text):
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_draw_is_deterministic_and_in_range():
    a, b = SD.draw(USERS, ROUNDS, seed=7), SD.draw(USERS, ROUNDS, seed=7)
    assert a == b
    assert SD.draw(USERS, ROUNDS, seed=8) != a
    for p in a.values():
        assert p["style"] in PF.ALPHA_ORDER
        assert SD.PLAY[0] <= p["play"] <= SD.PLAY[1]
        assert SD.FOLLOW[0] <= p["follow_rate"] <= SD.FOLLOW[1]
        assert p["kelly"] in SD.SIZINGS
        assert set(p["rounds"]) <= set(ROUNDS) and p["rounds"] == sorted(p["rounds"])
    assert len({p["style"] for p in a.values()}) > 1                     # forty players: more than one style
    assert len({len(p["rounds"]) for p in a.values()}) > 1               # and various participation


def test_a_player_keeps_their_draw_when_others_join():
    a = SD.draw(USERS[:10], ROUNDS, seed=3)
    b = SD.draw(USERS, ROUNDS, seed=3)
    assert all(a[u] == b[u] for u in a)


def test_raced_weekends_only():
    sched = {1: dict(race_start=pd.Timestamp("2026-03-08 04:00")), 2: dict(race_start=pd.Timestamp("2026-10-12 12:00"))}
    assert SD.raced(sched, pd.Timestamp("2026-10-13 06:00")) == [1]
    assert SD.raced(sched, pd.Timestamp("2026-10-13 13:00")) == [1, 2]


@pytest.mark.parametrize("url,ok", [
    ("postgresql+psycopg://u:p@127.0.0.1:5433/racinglines_staging_demo", True),
    ("postgresql+psycopg://u:p@127.0.0.1:5433/racinglines_demo_f1", True),
    ("postgresql+psycopg://u:p@127.0.0.1:5433/racinglines_staging", False),
    ("postgresql+psycopg://u:p@127.0.0.1:5433/racinglines", False),
    ("not a url", False),
])
def test_only_a_demo_database_is_written(url, ok):
    assert SD.is_demo_db(url) is ok


def test_build_refuses_to_apply_outside_a_demo_database():
    from sqlalchemy import create_engine
    eng = create_engine("postgresql+psycopg://u:p@127.0.0.1:1/racinglines_staging")
    with pytest.raises(ValueError, match="refusing"):
        SD.build(eng, str(eng.url), apply=True)


def test_script_writes_only_the_demo_database():
    s = code(SCRIPT)
    assert "DB=racinglines_staging_demo" in s
    assert 'DROP DATABASE IF EXISTS $DB WITH (FORCE)' in s
    assert "*/racinglines_staging_demo) ;;" in s                          # refuses any other DATABASE_URL
    assert "--no-subscriptions" in s and "--no-publications" in s         # a mirror's replication never follows it
    assert "users season-demo" in s and "--apply" in s
    assert "pg_dump --no-owner --no-privileges -U racinglines \"$DB\"" in s   # the backup before any write
    for forbidden in ("DROP DATABASE IF EXISTS racinglines ", "DROP DATABASE IF EXISTS racinglines_staging ",
                      "/etc/racinglines.env", "systemctl", "TRADING"):
        assert forbidden not in s, forbidden


def test_switch_is_one_override_file_the_unit_reads_last():
    assert UNIT.index("EnvironmentFile=/etc/racinglines-staging.env") < UNIT.index(
        "EnvironmentFile=-/etc/racinglines-staging-db.env")
    u = code(UPDATE)
    assert '[ -f "$DBENV" ] && . "$DBENV"' in u
    assert "*/${DB}_demo) DB=${DB}_demo" in u                              # migrates the demo database when switched
    block = code(VM_SH.split("\n      db)\n", 1)[1].split("\n      demo-db)\n", 1)[0])
    assert "/etc/racinglines-staging-db.env" in block
    assert "/etc/racinglines.env" not in block and "racinglines-web " not in block


@pytest.fixture
def players_db(test_engine, monkeypatch):
    """Four fantasy players and the demo maker (excluded), each with the 1,000 grant."""
    from sqlalchemy import text

    from racinglines.db import config
    from racinglines.web import accounts as ACC
    from racinglines.web import users as U
    with test_engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS accounts CASCADE"))
        for t in ("strategy_signals", "paper_positions"):
            c.execute(text(f"DELETE FROM {t}"))
        c.execute(text("DELETE FROM users"))
    monkeypatch.setenv("DATABASE_URL", test_engine.url.render_as_string(hide_password=False))
    config.get_engine.cache_clear()
    with config.get_session() as s:
        for name in ("ada", "bea", "cal", "dan", "maker"):
            U.create_user(s, name, f"{name}-password-1", "pro")
    ACC.setup(config.get_engine())
    yield test_engine
    with test_engine.begin() as c:                                         # leave the shared test database as found
        for t in ("strategy_signals", "paper_positions"):
            c.execute(text(f"DELETE FROM {t}"))
        c.execute(text("DROP SCHEMA IF EXISTS accounts CASCADE"))
        c.execute(text("DELETE FROM users WHERE username = ANY(:n)"), dict(n=["ada", "bea", "cal", "dan", "maker"]))
    config.get_engine.cache_clear()


def _fake_compute(calls):
    """signals.compute_all stand-in: one buy and one settled position per weekend and style (no _taker, so
    for_player keeps it as is)."""
    def compute_all(engine, url, prof, now=None, event=None, **kw):
        calls.append((prof["name"], event))
        key = f"m-{event}"
        sig = dict(market_key=key, kind="race_win", subject="Verstappen", stage="after Quali", dedupe="d1",
                   action="buy", side="YES", shares=10.0, limit_price=0.4, fair=0.5, price=0.4, edge=0.1, heat=2,
                   target_cost=4.0, signal_ts=pd.Timestamp(now) - pd.Timedelta(days=1), detail={}, status=None)
        pos = dict(market_key=key, kind="race_win", subject="Verstappen", yes_shares=10.0, no_shares=0.0, cash=-4.0,
                   mark=1.0, outcome=True)
        return [dict(profile=prof, event=dict(event_key=f"2026-{int(event.split('-')[1]):02d}", name="GP"),
                     stages=[("after Quali", None, None, None)], signals=[sig], positions=[pos], venue="polymarket")]
    return compute_all


def test_build_replays_each_players_draw(players_db, monkeypatch):
    from sqlalchemy import text

    from racinglines.pipelines import signals as SG
    from racinglines.pipelines import weekend_sweep as WS
    sched = {r: dict(event_key=f"2026-{r:02d}", name=f"GP {r}", race_start=pd.Timestamp(f"2026-0{r}-10 14:00"))
             for r in (3, 4, 5, 6)}
    sched[6]["race_start"] = pd.Timestamp("2026-12-01 14:00")              # not raced yet
    calls = []
    monkeypatch.setattr(WS, "schedule", lambda year: sched)
    monkeypatch.setattr(SG, "compute_all", _fake_compute(calls))
    monkeypatch.setattr(SD, "is_demo_db", lambda url: True)
    codes = list(PF.PROFILES)                                                # Lab candidates need the seeded sport
    monkeypatch.setattr(PF, "ensure_candidates", lambda c, history=False: {k: i + 1 for i, k in enumerate(codes)})
    monkeypatch.setattr(PF, "load", lambda c, ref: dict(candidate_id=int(ref), name=PF.PROFILES[codes[int(ref) - 1]]["name"],
                                                        strategy="update", settings={}))
    url = players_db.url.render_as_string(hide_password=False)
    plan, rep = SD.build(players_db, url, seed=11, now="2026-10-13", apply=True, echo=lambda m: None)
    names = {p["username"] for p in plan.values()}
    assert names == {"ada", "bea", "cal", "dan"}                              # the demo maker is left out
    assert all(e != "2026-6" for _, e in calls)
    with players_db.connect() as c:
        for uid, p in plan.items():
            keys = c.execute(text("SELECT event_key FROM strategy_signals WHERE user_id = :u ORDER BY event_key"),
                             dict(u=uid)).scalars().all()
            assert keys == [f"2026-{r:02d}" for r in p["rounds"]]
            prof = c.execute(text("SELECT prefs->'strategy_profile' FROM users WHERE id = :u"), dict(u=uid)).scalar()
            assert prof["follow_rate"] == p["follow_rate"] and prof["season_demo"] == 11
            assert prof["name"] == PF.PROFILES[p["style"]]["name"]
            assert (prof.get("kelly") if prof.get("sizing") == "kelly" else None) == p["kelly"]
            followed = c.execute(text("""SELECT count(*) FROM paper_positions WHERE user_id = :u"""), dict(u=uid)).scalar()
            assert followed == sum(r[3] for r in rep if r[0] == p["username"])
        n = c.execute(text("SELECT count(*) FROM strategy_signals")).scalar()
    SD.build(players_db, url, seed=11, now="2026-10-13", apply=True, echo=lambda m: None)   # rerun: same rows
    with players_db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM strategy_signals")).scalar() == n


def test_overnight_can_target_only_the_demo_database():
    s = code((ROOT / "scripts/vm/overnight.sh").read_text())
    assert "staging:racinglines_staging_demo) DB=$STAGING_DB" in s
    assert s.index("STAGING_DB") > s.index('. "$ENV_FILE"')                 # after the env file, so it overrides it
