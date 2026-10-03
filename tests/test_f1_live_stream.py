"""Live F1 timing on the Live page (web/f1_live.py): off except on staging, and a websocket the app's HTTP-only
dependencies don't break."""
from contextlib import contextmanager
from types import SimpleNamespace

import pandas as pd
import pytest

from racinglines.web import f1_live as FL


def test_on_only_on_staging_unless_switched(monkeypatch):
    monkeypatch.delenv("RACINGLINES_F1_STREAM", raising=False)
    monkeypatch.delenv("RACINGLINES_ENV", raising=False)
    assert not FL.enabled()
    monkeypatch.setenv("RACINGLINES_ENV", "staging")
    assert FL.enabled()
    monkeypatch.setenv("RACINGLINES_F1_STREAM", "0")
    assert not FL.enabled()
    monkeypatch.delenv("RACINGLINES_ENV")
    monkeypatch.setenv("RACINGLINES_F1_STREAM", "1")
    assert FL.enabled()


def test_latest_started_session():
    ev = {"Session1": "Practice 3", "Session1DateUtc": pd.Timestamp("2026-10-03 04:30"),
          "Session2": "Qualifying", "Session2DateUtc": pd.Timestamp("2026-10-03 08:00"),
          "Session3": "Race", "Session3DateUtc": pd.Timestamp("2026-10-04 07:00"),
          "Session4": "None", "Session4DateUtc": pd.NaT}
    assert FL.latest_session(ev, pd.Timestamp("2026-10-03 07:00"))[0] == "Practice 3"
    assert FL.latest_session(ev, pd.Timestamp("2026-10-03 17:00"))[0] == "Qualifying"
    assert FL.latest_session(ev, pd.Timestamp("2026-10-02 00:00")) is None


@pytest.fixture
def ws_client(monkeypatch):
    from fastapi.testclient import TestClient

    from racinglines.web import app as A

    @contextmanager
    def no_db():
        yield None

    monkeypatch.setattr(A, "get_session", no_db)
    monkeypatch.setattr(A.U, "get_user", lambda s, user_id: SimpleNamespace(
        id=user_id, username="maker", role="pro", display_name=None, active=True))
    return A, TestClient(A.app)


def _logs(ws, n):
    return [ws.receive_json() for _ in range(n)]


def test_websocket_off_says_so(ws_client, monkeypatch):
    A, client = ws_client
    monkeypatch.setenv("RACINGLINES_F1_STREAM", "0")
    with client.websocket_connect("/ws/f1/live") as ws:
        m = ws.receive_json()
    assert m["type"] == "log" and m["level"] == "error" and "off on this site" in m["msg"]


def test_websocket_needs_a_session_cookie(ws_client, monkeypatch):
    A, client = ws_client
    monkeypatch.setenv("RACINGLINES_F1_STREAM", "1")
    with client.websocket_connect("/ws/f1/live") as ws:
        m = ws.receive_json()
    assert m["level"] == "error" and m["msg"] == "not signed in"


def test_websocket_streams_a_poll_and_stops(ws_client, monkeypatch):
    A, client = ws_client
    monkeypatch.setenv("RACINGLINES_F1_STREAM", "1")
    monkeypatch.setenv("RACINGLINES_F1_STREAM_SEC", "30")
    calls = []

    async def fake_poll(year, rnd):
        calls.append((year, rnd))
        return dict(event="Bahrain Grand Prix", session="Qualifying", start="2026-10-03T08:00:00", laps=312,
                    note=None, drivers=[dict(pos=1, code="RUS", name="George Russell", team="Mercedes",
                                             status="Finished", best=88.1, last=90.2, laps=18)]), None, 1.5

    monkeypatch.setattr(FL, "poll", fake_poll)
    client.cookies.set(A.SESSION_COOKIE, "signed-cookie")
    monkeypatch.setattr(A, "_session_user_id", lambda cookie: 7)
    with client.websocket_connect("/ws/f1/live") as ws:
        assert "connected as maker" in ws.receive_json()["msg"]
        ws.send_json({"type": "start", "event": "2026-16"})
        assert "poll 1" in ws.receive_json()["msg"]
        timing = ws.receive_json()
        assert timing["type"] == "timing" and timing["data"]["drivers"][0]["code"] == "RUS"
        assert "Qualifying, 1 drivers, 312 laps" in ws.receive_json()["msg"]
        assert "next poll in 30 s" in ws.receive_json()["msg"]
        ws.send_json({"type": "stop"})
        assert ws.receive_json()["msg"] == "stopped"
    assert calls == [(2026, 16)]
