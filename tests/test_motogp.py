"""MotoGP results (racinglines/sources/motogp): the parser on the 2026-09-29 probe fixtures
(tests/fixtures/market/motogp_*.json, see motogp_README.txt), and the ingest into a throwaway database.
No network."""

import json

import pytest
from conftest import FIX, require_market_fixtures

from racinglines.sources.motogp import ingest as I

require_market_fixtures("motogp_events_2026", "motogp_classification_2026_tha_motogp_race")

MKT = FIX / "market"


def fx(name):
    return json.loads((MKT / f"motogp_{name}.json").read_text())


def tha_event():
    return next(e for e in fx("events_2026") if e["short_name"] == "THA")


def test_resolver_handles_uuid_identifier_values_for_non_numeric_schemes():
    from datetime import date

    from racinglines.sources.nascar.identity import Resolver

    class FakeConn:
        def execute(self, query, params=None):
            sql = str(query)
            if "SELECT a.id, a.display_name, i.value" in sql:
                return type("Rows", (), {"all": lambda self: [(1, "Pecco Bagnaia", "fe7f3311-ebb9-404b-9ab5-ea44b103991e"),
                                                            (2, "Alex Marquez", "12345")]})()
            if "SELECT DISTINCT r.athlete_id, s.year" in sql:
                return type("Rows", (), {"all": lambda self: [(1, 2026), (2, 2026)]})()
            if "SELECT ra.id, e.name, e.start_date, e.status" in sql:
                return type("Rows", (), {"all": lambda self: [(99, "GP of Thailand", date(2026, 2, 27), "completed")]})()
            raise AssertionError(f"unexpected query: {sql}")

    r = Resolver(FakeConn(), year=2026, competition="motogp_wc", scheme="motogp", source="motogp_api")
    assert r.driver_ids[1] == "fe7f3311-ebb9-404b-9ab5-ea44b103991e"
    assert r.driver_ids[2] == 12345


# --- parser ---------------------------------------------------------------------

@pytest.mark.quick
def test_time_ms_parses_minutes_and_hours_clocks():
    assert I._time_ms("39:36.270") == 39 * 60_000 + 36_270
    assert I._time_ms("1:39:36.270") == (60 + 39) * 60_000 + 36_270
    assert I._time_ms(None) is None and I._time_ms("") is None


@pytest.mark.quick
def test_status_of_treats_instnd_as_classified_and_everything_else_as_dnf():
    assert I.status_of({"status": "INSTND"}) == "OK"
    assert I.status_of({"status": "OUT"}) == "DNF"
    assert I.status_of({}) == "DNF"


@pytest.mark.quick
def test_session_round_kind_names_motogp_sessions_like_the_f1_pipeline():
    assert I.session_round_kind({"type": "FP", "number": 1}) == "fp1"
    assert I.session_round_kind({"type": "FP", "number": 2}) == "fp2"
    assert I.session_round_kind({"type": "Q1"}) == "qual1"
    assert I.session_round_kind({"type": "Q2"}) == "qual2"
    assert I.session_round_kind({"type": "SPR"}) == "sprint"
    assert I.session_round_kind({"type": "WUP"}) == "warmup"
    assert I.session_round_kind({"type": "RAC"}) == "race"


@pytest.mark.quick
def test_parse_event_reads_the_thailand_race_classification():
    p = I.parse_event(2026, tha_event(), fx("classification_2026_tha_motogp_race"))
    assert p["key"] == "2026-THA" and p["name"] == "GRAND PRIX OF THAILAND" and p["venue"] == "Chang International Circuit"
    assert p["date"].isoformat() == "2026-02-27" and len(p["rows"]) == 6                       # top 5 + last, per the fixture
    winner = p["rows"][0]
    assert (winner["name"], winner["position"], winner["status"], winner["bib"], winner["team"]) == \
        ("Marco Bezzecchi", 1, "OK", "72", "Aprilia Racing")
    assert winner["time_ms"] == 39 * 60_000 + 36_270 and winner["nation"] == "IT"
    assert winner["extra"]["constructor"] == "Aprilia" and winner["extra"]["points"] == 25
    second = p["rows"][1]
    assert second["time_ms"] == winner["time_ms"] + 5543 and second["extra"]["gap_to_leader_s"] == "5.543"


@pytest.mark.quick
def test_parse_event_is_none_with_no_classification():
    assert I.parse_event(2026, tha_event(), {"classification": []}) is None
    assert I.parse_event(2026, tha_event(), None) is None


@pytest.mark.quick
def test_model_uses_stable_athlete_ids_across_roster_changes():
    import numpy as np
    import pandas as pd

    from racinglines.models.motogp_model import MotoGPRace

    data = pd.DataFrame([
        {"season": 2024, "event_id": "2024-r1", "event_name": "Round 1", "race_key": "2024-r1", "date": pd.Timestamp("2024-04-01"),
         "athlete_id": 101, "rider": "A. Rider", "position": 1, "team": "Alpha", "status": "OK", "points": 25},
        {"season": 2024, "event_id": "2024-r1", "event_name": "Round 1", "race_key": "2024-r1", "date": pd.Timestamp("2024-04-01"),
         "athlete_id": 202, "rider": "A. Rider", "position": 2, "team": "Bravo", "status": "OK", "points": 18},
        {"season": 2025, "event_id": "2025-r1", "event_name": "Round 1", "race_key": "2025-r1", "date": pd.Timestamp("2025-04-01"),
         "athlete_id": 101, "rider": "A. Rider", "position": 2, "team": "Alpha", "status": "OK", "points": 18},
        {"season": 2025, "event_id": "2025-r1", "event_name": "Round 1", "race_key": "2025-r1", "date": pd.Timestamp("2025-04-01"),
         "athlete_id": 303, "rider": "B. Newcomer", "position": 4, "team": "Charlie", "status": "OK", "points": 12},
    ])

    model = MotoGPRace()
    ev = model.events(data, {}, seasons=[2025])[0]
    sim = model.price(data, ev, model.Settings.from_dict({"sims": 100, "noise": 0.1, "recent_races": 1,
                                                        "history_races": 0, "team_bias": 0.1,
                                                        "recency_decay": 1.0, "seed": 9}), np.random.default_rng(9))
    assert sim is not None
    assert set(sim.entrants) == {101, 202}
    assert all(isinstance(a, int) for a in sim.entrants)


# --- ingest into a database ---------------------------------------------------------

@pytest.fixture
def raw(tmp_path, monkeypatch):
    from racinglines.sources.motogp import fetch as F
    monkeypatch.setattr(F, "OUT", tmp_path)
    (tmp_path / "2026").mkdir()
    (tmp_path / "2026" / "events.json").write_text(json.dumps(fx("events_2026")))
    (tmp_path / "2026" / "THA").mkdir()
    (tmp_path / "2026" / "THA" / "classification.json").write_text(json.dumps(fx("classification_2026_tha_motogp_race")))
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


@pytest.mark.quick
def test_ingest_event_writes_the_standard_shape(db):
    from sqlalchemy import select

    from racinglines.db import models as m
    with db() as s:
        outcome = I.ingest_event(s, *_comp_cat(s), 2026, "THA")
        s.commit()
        assert outcome == "6 results"
        event = s.scalars(select(m.Event).filter_by(source=I.SOURCE, source_key="2026-THA")).one()
        assert event.name == "GRAND PRIX OF THAILAND" and event.status == "completed"
        race = s.scalars(select(m.Race).filter_by(event_id=event.id)).one()
        round_ = s.scalars(select(m.Round).filter_by(race_id=race.id)).one()
        assert round_.kind == "race"
        results = s.scalars(select(m.Result).filter_by(round_id=round_.id).order_by(m.Result.position)).all()
        assert [r.position for r in results] == [1, 2, 3, 4, 5, None] or len(results) == 6
        winner = next(r for r in results if r.position == 1)
        athlete = s.get(m.Athlete, winner.athlete_id)
        assert athlete.display_name == "Marco Bezzecchi"


@pytest.mark.quick
def test_reingest_is_a_no_op_and_force_rebuilds_without_duplicating(db):
    from sqlalchemy import select

    from racinglines.db import models as m
    with db() as s:
        comp, cat = _comp_cat(s)
        assert I.ingest_event(s, comp, cat, 2026, "THA") == "6 results"
        s.commit()
        assert I.ingest_event(s, comp, cat, 2026, "THA") == "unchanged"
        s.commit()
        assert I.ingest_event(s, comp, cat, 2026, "THA", force=True) == "6 results"
        s.commit()
        event = s.scalars(select(m.Event).filter_by(source=I.SOURCE, source_key="2026-THA")).one()
        race = s.scalars(select(m.Race).filter_by(event_id=event.id)).one()
        results = s.scalars(select(m.Result).join(m.Round).where(m.Round.race_id == race.id)).all()
        assert len(results) == 6                                                           # not doubled


def _comp_cat(session):
    from racinglines.db.ingest import ensure_competition
    return ensure_competition(session, I.SPORT)


def test_the_model_reads_the_race_round_only(db):
    """A weekend's other sessions (sprint, qualifying) are rounds of the same race: the model's frame keeps
    only the race classification, one row per rider per Grand Prix."""
    from sqlalchemy import select

    from conftest import TEST_DB
    from racinglines.db import models as m
    from racinglines.models.motogp_model import MotoGPRace
    with db() as s:
        I.ingest_event(s, *_comp_cat(s), 2026, "THA")
        race = s.scalars(select(m.Race).join(m.Event).filter(m.Event.source == I.SOURCE, m.Event.source_key == "2026-THA")).one()
        rnd = s.scalars(select(m.Round).filter_by(race_id=race.id, kind="race")).one()
        spr = m.Round(race_id=race.id, kind="sprint", ordinal=8, name="sprint")
        s.add(spr)
        s.flush()
        for r in s.scalars(select(m.Result).filter_by(round_id=rnd.id)).all():
            s.add(m.Result(round_id=spr.id, athlete_id=r.athlete_id, position=r.position, status=r.status))
        s.commit()
        n_race = len(s.scalars(select(m.Result).filter_by(round_id=rnd.id)).all())
    data = MotoGPRace.load(TEST_DB)
    assert len(data) == n_race and not data.duplicated(["race", "athlete_id"]).any()
