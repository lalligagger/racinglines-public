"""MotoGP's calendar: events not run yet are filed as scheduled (so scripts/vm/race_weekend.sh motogp can open), and
fetch --refresh asks again for the calendar and for a weekend that has run since it was stored. Hand-written JSON in
the API's shape (fields the fetch and ingest read only); no fixture files, no network."""

import json
from datetime import date

import pytest

from racinglines.sources.motogp import fetch as F
from racinglines.sources.motogp import ingest as I

TODAY = date(2026, 10, 11)
EVENTS = [
    {"id": "e-past", "short_name": "AAA", "name": "PAST GRAND PRIX", "date_start": "2026-09-18T00:00:00+00:00",
     "test": False, "circuit": {"name": "Hand-written Circuit A"}, "country": {"iso": "XA"}},
    {"id": "e-next", "short_name": "BBB", "name": "NEXT GRAND PRIX", "date_start": "2026-10-16T00:00:00+00:00",
     "test": False, "circuit": {"name": "Hand-written Circuit B"}, "country": {"iso": "XB"}},
    {"id": "e-later", "short_name": "CCC", "name": "LATER GRAND PRIX", "date_start": "2026-11-06T00:00:00+00:00",
     "test": False, "circuit": {}, "country": {}},
    {"id": "e-test", "short_name": "TST", "name": "A TEST", "date_start": "2026-11-20T00:00:00+00:00", "test": True},
]


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "OUT", tmp_path)
    (tmp_path / "2026").mkdir()
    (tmp_path / "2026" / "events.json").write_text(json.dumps(EVENTS))
    return tmp_path


@pytest.fixture
def db(test_engine, raw):
    from sqlalchemy import delete, select
    from sqlalchemy.orm import sessionmaker

    from racinglines.db import models as m
    S = sessionmaker(test_engine)

    def clean():
        with S() as s:
            ev = s.scalars(select(m.Event.id).where(m.Event.source == I.SOURCE)).all()
            s.execute(delete(m.Race).where(m.Race.event_id.in_(ev)))
            s.execute(delete(m.Event).where(m.Event.id.in_(ev)))
            s.execute(delete(m.SourceFile).where(m.SourceFile.parser == I.PARSER))
            s.commit()

    clean()
    yield S
    clean()


def _events(s):
    from sqlalchemy import select

    from racinglines.db import models as m
    return {e.source_key: e for e in s.scalars(select(m.Event).where(m.Event.source == I.SOURCE))}


@pytest.mark.quick
def test_events_still_to_run_are_filed_as_scheduled_and_a_completed_one_is_left_alone(db):
    from sqlalchemy import select

    from racinglines.db import models as m
    from racinglines.db.ingest import ensure_competition
    with db() as s:
        comp, cat = ensure_competition(s, I.SPORT)
        assert I.ingest_schedule(s, comp, cat, 2026, today=TODAY) == 2              # BBB, CCC; not the past one or the test
        s.commit()
        ev = _events(s)
        assert set(ev) == {"2026-BBB", "2026-CCC"}
        assert ev["2026-BBB"].status == "scheduled" and ev["2026-BBB"].start_date == date(2026, 10, 16)
        assert ev["2026-BBB"].name == "NEXT GRAND PRIX"
        race = s.scalars(select(m.Race).filter_by(event_id=ev["2026-BBB"].id)).one()
        assert race.format == {"kind": "motogp"}
        assert not s.scalars(select(m.Round).filter_by(race_id=race.id)).all()      # no rounds, no results
        assert I.ingest_schedule(s, comp, cat, 2026, today=TODAY) == 0              # unchanged: nothing written
        ev["2026-BBB"].status = "completed"                                          # its results arrived
        s.commit()
        assert I.ingest_schedule(s, comp, cat, 2026, today=TODAY, force=True) == 1  # CCC only
        s.commit()
        assert _events(s)["2026-BBB"].status == "completed"


@pytest.mark.quick
def test_ingest_files_the_schedule_and_skips_events_with_no_classification(db):
    with db() as s:
        report = I.ingest(s, [2026], today=TODAY, echo=lambda *_: None)
        assert report == {"2026-AAA": "no classification", "2026-BBB": "no classification",
                          "2026-CCC": "no classification"}
        assert set(_events(s)) == {"2026-BBB", "2026-CCC"}


class FakeHTTP:
    """Answers fetch's calls from a dict of path -> JSON, and records them."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, c, path, **params):
        self.calls.append(path)
        return self.routes[path]


def _routes(rac_status, sprint_status="FINISHED"):
    return {
        "/results/seasons": [{"id": "s26", "year": 2026}],
        "/results/events": EVENTS,
        "/results/categories": [{"id": "cat-motogp", "name": "MotoGP™"}],
        "/results/sessions": [{"id": "spr", "type": "SPR", "status": sprint_status},
                              {"id": "rac", "type": "RAC", "status": rac_status}],
        "/results/session/spr/classification": {"classification": []},
        "/results/session/rac/classification": {"classification": []},
    }


def test_refresh_asks_again_for_the_calendar_and_a_weekend_run_since_and_takes_finished_sessions_only(raw, monkeypatch):
    # first pass (no refresh): every session listed as not started; nothing classified
    http = FakeHTTP(_routes("NOT-STARTED", "NOT-STARTED"))
    monkeypatch.setattr(F, "get", http)
    F.fetch([2026], today=TODAY)
    assert not list(raw.glob("2026/*/*.classification.json"))
    # without refresh, the stored sessions are never asked for again: the stale "NOT-STARTED" would stand forever
    http = FakeHTTP(_routes("FINISHED"))
    monkeypatch.setattr(F, "get", http)
    F.fetch([2026], today=TODAY)
    assert "/results/events" not in http.calls and "/results/sessions" not in http.calls
    # refresh mid-race on AAA (started): calendar and AAA's sessions asked again; the finished sprint is taken, the
    # running race is not
    http = FakeHTTP(_routes("IN-PROGRESS"))
    monkeypatch.setattr(F, "get", http)
    F.fetch([2026], refresh=True, today=TODAY)
    assert http.calls.count("/results/events") == 1
    assert http.calls.count("/results/sessions") == 1                       # AAA only: BBB and CCC haven't started
    assert (raw / "2026" / "AAA" / "spr.classification.json").exists()
    assert not (raw / "2026" / "AAA" / "rac.classification.json").exists()
    # refresh after the race: the race is taken; a later refresh leaves the finished weekend alone
    http = FakeHTTP(_routes("FINISHED"))
    monkeypatch.setattr(F, "get", http)
    F.fetch([2026], refresh=True, today=TODAY)
    assert (raw / "2026" / "AAA" / "rac.classification.json").exists()
    assert (raw / "2026" / "AAA" / "classification.json").exists()
    http = FakeHTTP(_routes("FINISHED"))
    monkeypatch.setattr(F, "get", http)
    F.fetch([2026], refresh=True, today=TODAY)
    assert http.calls == ["/results/events"]                                # categories stay cached
