"""MotoGP qualifying and sprints (racinglines/sources/motogp, package C12b): the API's Q1 / Q2 sessions (type "Q",
number 1 / 2 in the 2026-09-29 probe, tests/fixtures/market/motogp_sessions_2026_tha_motogp.json) are stored as
rounds qual1 / qual2 plus the combined qualifying order "qual"; the sprint as round "sprint". The session list is the
real fixture; the Q1 / Q2 / sprint classifications reuse the race fixture's rows (same shape, the only classification
JSON the probe kept) with positions set here. No network."""

import copy
import json

import pytest
from conftest import FIX, require_market_fixtures

from racinglines.sources.motogp import ingest as I

require_market_fixtures("motogp_events_2026", "motogp_classification_2026_tha_motogp_race",
                        "motogp_sessions_2026_tha_motogp")

MKT = FIX / "market"


def fx(name):
    return json.loads((MKT / f"motogp_{name}.json").read_text())


def tha_event():
    return next(e for e in fx("events_2026") if e["short_name"] == "THA")


def sessions():
    return fx("sessions_2026_tha_motogp")


def sid(type_, number=None):
    return next(s["id"] for s in sessions() if s["type"] == type_ and s.get("number") == number)


def classification(order):
    """The race fixture's rows re-placed: `order` lists (race-fixture row index, position or None)."""
    race = fx("classification_2026_tha_motogp_race")
    rows = []
    for i, pos in order:
        r = copy.deepcopy(race["classification"][i])
        r["position"], r["status"] = pos, "INSTND" if pos is not None else "OUTSTND"
        rows.append(r)
    return {"classification": rows}


# rider index into the race fixture (6 rows: the top 5 and the last). Q2: riders 0-3; Q1: riders 3-5, rider 3 went
# through to Q2 from Q1, rider 5 set no time
Q2 = [(1, 1), (0, 2), (3, 3), (2, 4)]
Q1 = [(3, 1), (4, 2), (5, None)]
SPR = [(0, 1), (2, 2), (1, 3), (3, 4), (4, 5), (5, None)]


def payloads():
    return {sid("Q", 1): classification(Q1), sid("Q", 2): classification(Q2), sid("SPR"): classification(SPR),
            sid("RAC"): fx("classification_2026_tha_motogp_race")}


def rider(i):
    return fx("classification_2026_tha_motogp_race")["classification"][i]["rider"]["id"]


@pytest.mark.quick
def test_the_api_types_q1_and_q2_as_q_with_a_number():
    kinds = [I.session_round_kind(s) for s in sessions()]
    assert kinds == ["fp1", "practice", "fp2", "qual1", "qual2", "sprint", "warmup", "race"]
    assert I.session_round_kind({"type": "Q", "number": None}) == "qual"      # a single qualifying session


@pytest.mark.quick
def test_parse_event_stores_q1_q2_the_sprint_and_the_combined_qualifying_order():
    p = I.parse_event(2026, tha_event(), payloads(), sessions=sessions())
    by = {r["kind"]: r for r in p["rounds"]}
    assert set(by) == {"qual1", "qual2", "qual", "sprint", "race"}
    assert [r["rider_id"] for r in by["sprint"]["rows"]][:3] == [rider(0), rider(2), rider(1)]
    q = by["qual"]
    assert q["extra"]["derived_from"] == ["qual1", "qual2"]
    # Q2's order, then the Q1 riders who didn't reach Q2 (rider 3 did), the rider with no time last
    assert [(r["rider_id"], r["position"], r["status"]) for r in q["rows"]] == [
        (rider(1), 1, "OK"), (rider(0), 2, "OK"), (rider(3), 3, "OK"), (rider(2), 4, "OK"),
        (rider(4), 5, "OK"), (rider(5), 6, "DNS")]
    assert [r["extra"]["session"] for r in q["rows"]] == ["q2"] * 4 + ["q1"] * 2
    assert q["rows"][4]["extra"]["session_position"] == 2


@pytest.mark.quick
def test_combined_qualifying_with_only_q2_or_only_q1():
    rows = I._rows_from_classification(classification(Q2))
    assert [r["position"] for r in I.combined_qualifying([], rows)] == [1, 2, 3, 4]
    rows = I._rows_from_classification(classification(Q1))
    assert [(r["position"], r["status"]) for r in I.combined_qualifying(rows, [])] == [(1, "OK"), (2, "OK"), (3, "DNS")]


@pytest.mark.quick
def test_a_race_fetched_before_session_files_keeps_its_race():
    """sessions.json is stored but only <event>/classification.json (the race): the race round is still written."""
    p = I.parse_event(2026, tha_event(), {I.LEGACY: fx("classification_2026_tha_motogp_race")}, sessions=sessions())
    assert [r["kind"] for r in p["rounds"]] == ["race"] and len(p["rounds"][0]["rows"]) == 6


@pytest.mark.quick
def test_a_stopped_and_restarted_race_listed_twice_keeps_the_restart():
    """2016 NED lists two RAC sessions (14:00 with no number, 15:00 numbered 2: the race was stopped and restarted).
    Rounds are UNIQUE on race and kind, so one race round is kept: the later session's."""
    first = copy.deepcopy(next(s for s in sessions() if s["type"] == "RAC"))
    restart = copy.deepcopy(first)
    first.update(id="stopped-race", number=None, date="2026-03-01T14:00:00+07:00")
    restart.update(number=2, date="2026-03-01T15:00:00+07:00")
    got = {"stopped-race": classification(SPR), restart["id"]: fx("classification_2026_tha_motogp_race")}
    for order in ([first, restart], [restart, first]):
        p = I.parse_event(2026, tha_event(), got, sessions=order)
        races = [r for r in p["rounds"] if r["kind"] == "race"]
        assert len(races) == 1
        assert [r["rider_id"] for r in races[0]["rows"]] == [
            r["rider"]["id"] for r in fx("classification_2026_tha_motogp_race")["classification"]]
        assert races[0]["extra"]["number"] == 2
        assert races[0]["extra"]["superseded"] == ["2026-03-01T14:00:00+07:00"]


# --- into a database ------------------------------------------------------------------------------------------------

@pytest.fixture
def raw(tmp_path, monkeypatch):
    from racinglines.sources.motogp import fetch as F
    monkeypatch.setattr(F, "OUT", tmp_path)
    ev = tmp_path / "2026" / "THA"
    ev.mkdir(parents=True)
    (tmp_path / "2026" / "events.json").write_text(json.dumps(fx("events_2026")))
    (ev / "sessions.json").write_text(json.dumps(sessions()))
    for k, v in payloads().items():
        (ev / f"{k}.classification.json").write_text(json.dumps(v))
    return tmp_path


@pytest.fixture
def db(test_engine, raw):
    from sqlalchemy import delete, select
    from sqlalchemy.orm import sessionmaker

    from racinglines.db import models as m
    S = sessionmaker(test_engine)

    def clean():
        with S() as s:
            s.execute(delete(m.Event).where(m.Event.source == I.SOURCE))
            s.execute(delete(m.SourceFile).where(m.SourceFile.parser == I.PARSER))
            ids = s.scalars(select(m.AthleteIdentifier.athlete_id).where(m.AthleteIdentifier.scheme == I.SCHEME)).all()
            s.execute(delete(m.AthleteIdentifier).where(m.AthleteIdentifier.scheme == I.SCHEME))
            s.execute(delete(m.Athlete).where(m.Athlete.id.in_(ids)))
            s.commit()

    clean()
    yield S
    clean()


def test_ingest_writes_qualifying_and_sprint_rounds_and_settles_the_pole(db, test_engine):
    from sqlalchemy import select

    from racinglines.db import models as m
    from racinglines.db.ingest import ensure_competition
    from racinglines.markets import kinds as K
    from racinglines.markets.private_book import race_outcomes
    with db() as s:
        assert I.ingest_event(s, *ensure_competition(s, I.SPORT), 2026, "THA") == "25 results"   # Q1 3 + Q2 4 + qual 6 + sprint 6 + race 6
        s.commit()
        race = s.scalars(select(m.Race).join(m.Event).where(m.Event.source == I.SOURCE)).one()
        kinds = {r.kind: r for r in s.scalars(select(m.Round).filter_by(race_id=race.id))}
        assert set(kinds) == {"qual1", "qual2", "qual", "sprint", "race"}
        ids = dict(s.execute(select(m.AthleteIdentifier.value, m.AthleteIdentifier.athlete_id)
                             .where(m.AthleteIdentifier.scheme == I.SCHEME)).all())
    with test_engine.connect() as conn:
        res = race_outcomes(conn, race.id)
    pole = ids[rider(1)]
    assert K.settle("race_pole", pole, {}, res) is True
    assert K.settle("race_pole", ids[rider(0)], {}, res) is False
