"""The race-weekend gate (scripts/vm/race_weekend.sh) and the FastF1 recorder's race-week lookup
(racinglines/cli/f1.py fastf1_target): both read events by the competition code in sports/<sport>.toml and keep
race day itself inside the window."""

import os
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from racinglines import sports
from racinglines.cli.f1 import fastf1_target, race_week

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "vm" / "race_weekend.sh"


def _epoch(y, m, d, h=12):
    return str(int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp()))


def gate(tmp_path, sport, now, count="1", *args, env_extra=None):
    """Run the gate with a fake `docker` that records the query and prints `count`; returns (exit code, query)."""
    log = tmp_path / "query.sql"
    log.unlink(missing_ok=True)
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "docker").write_text(f'#!/usr/bin/env bash\nprintf "%s" "${{@: -1}}" > "{log}"\necho " {count}"\n')
    (fake / "docker").chmod(0o755)
    env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", ENV_FILE="/dev/null", APP=str(ROOT),
               RACE_WEEKEND_NOW=now, **(env_extra or {}))
    rc = subprocess.run(["bash", str(GATE), sport, *args], env=env, capture_output=True, text=True).returncode
    return rc, (log.read_text() if log.exists() else None)


@pytest.mark.parametrize("sport", sports.SPORT_CODES)
def test_gate_uses_each_sports_competition_code(tmp_path, sport):
    rc, q = gate(tmp_path, sport, _epoch(2026, 10, 11))          # a Sunday
    assert rc == 0
    assert f"c.code = '{sports.load(sport)['competition']['code']}'" in q


def test_gate_counts_the_whole_weekend_but_not_last_weeks_event(tmp_path):
    _, q = gate(tmp_path, "motogp", _epoch(2026, 10, 11))       # Sunday: a Friday start_date still counts
    assert "e.start_date >= '2026-10-08'::date" in q and "e.start_date < '2026-10-18'::date" in q
    _, q = gate(tmp_path, "f1", _epoch(2026, 10, 15))           # Thursday: last Sunday's race no longer counts
    assert "e.start_date >= '2026-10-12'::date" in q


def test_gate_off_week_and_unknown_sport(tmp_path):
    assert gate(tmp_path, "f1", _epoch(2026, 10, 7)) == (1, None)        # Wednesday: no query at all
    assert gate(tmp_path, "f1", _epoch(2026, 10, 11), count="0")[0] == 1  # no event this week
    assert gate(tmp_path, "cycling", _epoch(2026, 10, 11)) == (1, None)  # not a sport code


def test_lead_runs_any_day_with_an_event_ahead(tmp_path):
    rc, q = gate(tmp_path, "f1", _epoch(2026, 10, 7), "1", "--lead")   # Wednesday: the lead sync runs
    assert rc == 0
    assert "e.start_date >= '2026-10-04'::date" in q and "e.start_date < '2026-10-14'::date" in q
    _, q = gate(tmp_path, "f1", _epoch(2026, 10, 5), "1", "--lead", env_extra={"LEAD_DAYS": "10"})   # Monday
    assert "e.start_date < '2026-10-15'::date" in q
    assert gate(tmp_path, "f1", _epoch(2026, 10, 7), "0", "--lead")[0] == 1      # no event ahead
    assert gate(tmp_path, "f1", _epoch(2026, 10, 7), "1", "--verbose") == (1, None)   # no --lead: still Thu to Sun


def test_race_week_is_wednesday_to_tuesday():
    assert race_week(date(2026, 10, 11)) == (date(2026, 10, 7), date(2026, 10, 13))    # Sunday race
    assert race_week(date(2026, 11, 21)) == (date(2026, 11, 18), date(2026, 11, 24))   # Saturday (Las Vegas)


@pytest.fixture
def f1_events(test_engine):
    """Two F1 rounds in a far-future season, removed afterwards."""
    code = sports.load("f1")["competition"]["code"]
    with test_engine.begin() as c:
        comp = c.execute(text("SELECT id FROM competitions WHERE code = :c"), dict(c=code)).scalar()
        if comp is None:
            sport = c.execute(text("INSERT INTO sports (code, name) VALUES ('f1', 'F1') "
                                   "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id")).scalar()
            league = c.execute(text("INSERT INTO leagues (code, name) VALUES ('fia', 'FIA') "
                                    "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id")).scalar()
            comp = c.execute(text("INSERT INTO competitions (code, name, league_id, sport_id) "
                                  "VALUES (:c, 'F1', :l, :s) RETURNING id"), dict(c=code, l=league, s=sport)).scalar()
        season = c.execute(text("INSERT INTO seasons (competition_id, year) VALUES (:c, 2099) RETURNING id"),
                           dict(c=comp)).scalar()
        for rnd, d, status in ((1, date(2099, 3, 8), "completed"), (2, date(2099, 3, 22), "scheduled"),
                               (3, date(2099, 4, 5), "cancelled")):
            c.execute(text("INSERT INTO events (season_id, source, source_key, name, start_date, series_round, status) "
                           "VALUES (:s, 'test', :k, 'GP', :d, :r, :st)"),
                      dict(s=season, k=f"2099-{rnd}", d=d, r=rnd, st=status))
    yield test_engine
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM events WHERE season_id = :s"), dict(s=season))
        c.execute(text("DELETE FROM seasons WHERE id = :s"), dict(s=season))


def test_fastf1_target_finds_the_race_week(f1_events):
    with f1_events.connect() as c:
        assert fastf1_target(c, date(2099, 3, 4)) == (2099, 1)    # Wednesday before round 1
        assert fastf1_target(c, date(2099, 3, 8)) == (2099, 1)    # race day
        assert fastf1_target(c, date(2099, 3, 10)) == (2099, 1)   # Tuesday after
        assert fastf1_target(c, date(2099, 3, 22)) == (2099, 2)   # a scheduled round
        assert fastf1_target(c, date(2099, 3, 13)) is None        # between race weeks
        assert fastf1_target(c, date(2099, 4, 5)) is None         # cancelled round


def test_gate_query_runs_and_counts_race_day(tmp_path, f1_events):
    _, q = gate(tmp_path, "f1", _epoch(2099, 3, 8))               # Sunday, race day of round 1
    with f1_events.connect() as c:
        assert c.execute(text(q.rstrip(";"))).scalar() == 1


TAPE = ROOT / "scripts" / "vm" / "tape_check.sh"


def tape(tmp_path, exchange, ever, rows):
    """Run tape_check.sh with a fake `docker`: `ever` race links for the competition, then the per-event `rows`."""
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "docker").write_text('#!/usr/bin/env bash\ncase "${@: -1}" in\n'
                                 f'  *"SELECT count(*) FROM market_links"*) echo "{ever}" ;;\n'
                                 f"  *) printf '{rows}' ;;\nesac\n")
    (fake / "docker").chmod(0o755)
    env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", ENV_FILE="/dev/null", APP=str(ROOT))
    out = subprocess.run(["bash", str(TAPE), exchange, "f1"], env=env, capture_output=True, text=True)
    return out.returncode, out.stdout.splitlines()


def test_tape_check_flags_missing_and_stale_links(tmp_path):
    rc, lines = tape(tmp_path, "kalshi", 5, r"e1|Event one|0|\ne2|Event two|12|5.2\ne3|Event three|9|1.0\n")
    assert rc == 1
    assert lines[0] == "WARN kalshi f1 e1 Event one: no links with this race (sync, then link)"
    assert lines[1].startswith("WARN kalshi f1 e2 Event two: 12 links, last sync 5.2 h ago")
    assert lines[2].startswith("OK   kalshi f1 e3")
    assert tape(tmp_path, "kalshi", 5, r"e3|Event three|9|1.0\n")[0] == 0


def test_tape_check_skips_an_exchange_without_race_markets(tmp_path):
    assert tape(tmp_path, "og", 0, "") == (0, ["SKIP og f1: no race market on this exchange for this sport yet"])
    assert tape(tmp_path, "k;x", 5, "")[0] == 2
