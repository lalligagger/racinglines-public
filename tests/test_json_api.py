"""The read-only JSON API (web/api.py): off by default (404), then events and athletes as JSON behind the usual
login, with no model prices. The database reads are stubbed: no database needed."""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from racinglines.db import reads as data
from racinglines.web import app as A


@pytest.fixture
def client(monkeypatch):
    A.app.dependency_overrides[A.authenticate] = lambda: None
    A.app.dependency_overrides[A.conn] = lambda: None
    ev = pd.DataFrame(dict(id=[7], season=[2026], start_date=[pd.Timestamp("2026-09-25").date()], name=["Whistler"],
                           venue=["Whistler"], country=["CAN"], series_round=[7], status=["completed"],
                           source_key=["20260925_mtb"], races=[2]))
    res = pd.DataFrame(dict(race_id=[1, 1], category=["ME", "ME"], round=["final", "final"], ordinal=[5, 5],
                            position=[1, None], athlete_id=[11, 12], athlete=["A", "B"], nation=["CAN", None],
                            team=[None, None], status=["OK", "DNF"], time_s=[181.2, None]))
    monkeypatch.setattr(data, "events", lambda c, competition=None, season=None: ev)
    monkeypatch.setattr(data, "event", lambda c, i: dict(ev.iloc[0].to_dict(), competition="uci_dhi_wc",
                                                         source="chronorace", venue_id=3) if i == 7 else None)
    monkeypatch.setattr(data, "event_results", lambda c, i: res)
    monkeypatch.setattr(data, "athletes", lambda c, q, limit=200: pd.DataFrame(dict(id=[11], athlete=["A"], nation=["CAN"],
                                                                                    results=[3], last_race=[None], wins=[1])))
    monkeypatch.setattr(data, "athlete", lambda c, i: dict(id=11, display_name="A", nation="CAN", birth_year=1999,
                                                           gender="M", identifiers=[]) if i == 11 else None)
    monkeypatch.setattr(data, "athlete_results", lambda c, i: res.drop(columns=["athlete"]))
    try:
        yield TestClient(A.app)
    finally:
        A.app.dependency_overrides.clear()


@pytest.mark.quick
def test_off_by_default(client, monkeypatch):
    monkeypatch.delenv("RACINGLINES_JSON_API", raising=False)
    for path in ("/api/v1/events", "/api/v1/events/7", "/api/v1/athletes", "/api/v1/athletes/11"):
        assert client.get(path).status_code == 404


@pytest.mark.quick
def test_events_and_athletes_as_json(client, monkeypatch):
    monkeypatch.setenv("RACINGLINES_JSON_API", "1")
    evs = client.get("/api/v1/events?season=2026").json()["events"]
    assert evs[0]["name"] == "Whistler" and evs[0]["start_date"].startswith("2026-09-25")
    e = client.get("/api/v1/events/7").json()
    assert e["event"]["competition"] == "uci_dhi_wc" and "venue_id" not in e["event"]
    assert e["results"][1]["position"] is None and e["results"][0]["time_s"] == 181.2
    assert client.get("/api/v1/events/8").status_code == 404
    a = client.get("/api/v1/athletes/11").json()
    assert a["athlete"] == dict(id=11, display_name="A", nation="CAN", identifiers=[]) and len(a["results"]) == 2
    assert client.get("/api/v1/athletes?q=a").json()["athletes"][0]["wins"] == 1
    body = str(client.get("/api/v1/events/7").json())
    assert "prob" not in body and "fair" not in body                     # no model prices


def test_needs_the_login(monkeypatch):
    monkeypatch.setenv("RACINGLINES_JSON_API", "1")
    r = TestClient(A.app).get("/api/v1/events", headers={"accept": "application/json"})
    assert r.status_code == 401
