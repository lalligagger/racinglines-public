"""Sessions still to run are stored as scheduled rounds (db/schedule.py) so a market on an upcoming session has a close."""
from datetime import date

import pandas as pd
import pytest


def test_nascar_sessions_come_only_from_utc_entries():
    from racinglines.sources.nascar import ingest as NI
    row = dict(race_id=5633, race_date="2026-10-18T14:00:00", schedule=[
        dict(event_name="Practice", start_time_utc="2026-10-17T17:35:00", run_type=1),
        dict(event_name="Qualifying", start_time_utc="2026-10-17T18:40:00Z", run_type=2),
        dict(event_name="Race", start_time_utc="2026-10-18T19:30:00", run_type=3),
        dict(event_name="Driver intros", start_time_utc="2026-10-18T19:00:00", run_type=0),
        dict(event_name="Race", start_time_utc=None, run_type=3)])
    assert [(s["kind"], s["start"]) for s in NI.schedule_sessions(row)] == [
        ("fp1", "2026-10-17T17:35:00"), ("qual", "2026-10-17T18:40:00"), ("race", "2026-10-18T19:30:00")]
    assert NI.schedule_sessions(dict(race_id=1, race_date="2026-10-18T14:00:00")) == []      # never from local time


def _schedule(rows):
    cols = {}
    for r in rows:
        for k, v in r.items():
            cols.setdefault(k, []).append(v)
    return pd.DataFrame(cols)


def _ev(rnd, day, sessions):
    r = dict(RoundNumber=rnd, EventName=f"GP {rnd}", EventDate=pd.Timestamp(day))
    for i in range(1, 6):
        name, t = sessions[i - 1] if i <= len(sessions) else (None, None)
        r[f"Session{i}"] = name
        r[f"Session{i}DateUtc"] = pd.Timestamp(t) if t else pd.NaT
    return r


@pytest.fixture
def f1_events(test_engine):
    from sqlalchemy import delete, select
    from sqlalchemy.orm import sessionmaker

    from racinglines.db import models as m
    from racinglines.db.ingest import _upsert
    from racinglines.sources.fastf1 import ingest as I
    with sessionmaker(test_engine)() as s:
        I.seed(s)
        comp = s.scalars(select(m.Competition).filter_by(code=I.COMPETITION)).one()
        cat = s.scalars(select(m.Category).filter_by(competition_id=comp.id, code=I.CATEGORY)).one()
        season = _upsert(s, m.Season, dict(competition_id=comp.id, year=2026))
        ids = {}
        for key, day, status in (("2026-18", date(2026, 10, 25), "scheduled"), ("2026-19", date(2026, 11, 1), "scheduled"),
                                 ("2026-17", date(2026, 10, 11), "completed"), ("2026-23", date(2026, 12, 6), "scheduled")):
            ev = _upsert(s, m.Event, dict(season_id=season.id, source=I.SOURCE, source_key=key), name=f"GP {key}",
                         start_date=day, series_round=int(key[-2:]), status=status)
            race = _upsert(s, m.Race, dict(event_id=ev.id, category_id=cat.id))
            s.execute(delete(m.Round).where(m.Round.race_id == race.id))
            ids[key] = race.id
        s.commit()
        yield s, ids


def test_f1_schedule_writes_upcoming_sessions_and_keeps_what_ran(f1_events):
    from sqlalchemy import select

    from racinglines.db import models as m
    from racinglines.pipelines import clv
    from racinglines.sources.fastf1 import ingest as I
    s, ids = f1_events
    s.add(m.Round(race_id=ids["2026-19"], kind="fp1", ordinal=-3, name="fp1",
                  extra=dict(session_date="2026-10-30 18:30:00")))                         # stored by the ingest: it ran
    s.flush()
    sch = _schedule([
        _ev(17, "2026-10-11", [("Practice 1", "2026-10-09 08:30")]),
        _ev(18, "2026-10-25", [("Practice 1", "2026-10-23 17:30"), ("Sprint Qualifying", "2026-10-23 21:30"),
                               ("Sprint", "2026-10-24 17:00"), ("Qualifying", "2026-10-24 21:00"),
                               ("Race", "2026-10-25 19:00")]),
        _ev(19, "2026-11-01", [("Practice 1", "2026-10-30 18:30"), ("Qualifying", "2026-10-31 21:00"),
                               ("Race", "2026-11-01 20:00")]),
        _ev(23, "2026-12-06", [("Race", "2026-12-06 13:00")])])
    today = date(2026, 10, 12)
    n = I.write_schedule(s, sch, 2026, date(2026, 11, 30), today, echo=lambda *_: None)
    assert n == dict(added=7, moved=0, unchanged=0, ran=1)
    got = {(r.race_id, r.kind): r.extra for r in s.scalars(select(m.Round))}
    assert got[(ids["2026-18"], "sprint_qual")] == dict(session_date="2026-10-23 21:30:00", scheduled=True,
                                                         source="fastf1 event schedule")
    assert got[(ids["2026-19"], "fp1")] == dict(session_date="2026-10-30 18:30:00")      # untouched
    assert not any(rid in (ids["2026-17"], ids["2026-23"]) for rid, _ in got)              # completed / past --through

    # the closes the Trade page reads (pipelines/clv.closes) now exist for qualifying and the race
    links = [dict(race_id=ids["2026-18"], prediction=k, competition="f1_wdc", start_date=date(2026, 10, 25))
             for k in ("race_winner", "race_pole")]
    closes = clv.closes(s.connection(), links)
    assert closes[(ids["2026-18"], "race_winner")][0] == pd.Timestamp("2026-10-25 19:00")
    assert closes[(ids["2026-18"], "race_pole")][0] == pd.Timestamp("2026-10-24 21:00")

    # again: nothing new; a moved session is updated in place
    assert I.write_schedule(s, sch, 2026, date(2026, 11, 30), today, echo=lambda *_: None) == dict(
        added=0, moved=0, unchanged=7, ran=1)
    sch.loc[sch["RoundNumber"] == 18, "Session5DateUtc"] = pd.Timestamp("2026-10-25 20:00")
    assert I.write_schedule(s, sch, 2026, date(2026, 11, 30), today, echo=lambda *_: None)["moved"] == 1

    # a stored date that disagrees with the schedule is left alone
    sch.loc[sch["RoundNumber"] == 19, "EventDate"] = pd.Timestamp("2026-11-08")
    out = []
    I.write_schedule(s, sch, 2026, date(2026, 11, 30), today, echo=out.append)
    assert any("skipped: stored date 2026-11-01" in line for line in out)

    from racinglines.db import schedule as SCH
    assert SCH.undo(s, I.SOURCE) == 7
    s.rollback()


def test_an_ingest_keeps_the_sessions_still_to_come(f1_events):
    """A mid-weekend ingest (FP1 in) rebuilds the race's rounds but keeps the scheduled ones not yet run; the race's
    ingest (the event completes) clears whatever is still flagged scheduled (a cancelled session)."""
    from sqlalchemy import select

    from racinglines.db import models as m
    from racinglines.db import schedule as SCH
    s, ids = f1_events
    rid = ids["2026-18"]
    SCH.write_sessions(s, rid, [dict(kind=k, ordinal=o, name=k, start=f"2026-10-2{d} 18:00:00")
                                for k, o, d in (("fp1", -3, 3), ("qual", 2, 4), ("race", 5, 5))], "session_date", "test")
    assert SCH.clear_for_ingest(s, rid, {"fp1"}) == 2
    s.add(m.Round(race_id=rid, kind="fp1", ordinal=-3, name="fp1", extra=dict(session_date="2026-10-23 18:00:00")))
    s.flush()
    kinds = lambda: {r.kind: bool((r.extra or {}).get("scheduled")) for r in s.scalars(select(m.Round).filter_by(race_id=rid))}
    assert kinds() == dict(fp1=False, qual=True, race=True)
    assert SCH.clear_for_ingest(s, rid, {"fp1", "qual"}) == 1                            # qual in: only the race is left
    assert kinds() == dict(race=True)
    assert SCH.clear_for_ingest(s, rid, {"fp1", "race"}, final=True) == 0
    assert kinds() == {}
    s.rollback()
