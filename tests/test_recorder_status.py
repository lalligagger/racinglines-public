"""The per-venue recorder line (board.recorder_status and _recorders.html), without a database: whatever data arrived
shows per venue, a venue with nothing reads "no data yet", an old one "synced ..." coloured by minutes elapsed
(green under 5, yellow 5-10, red 10+), and a failing status query still lets the page load. The Kalshi and OG.com
recorder itself is scripts/vm/record_venues.sh (vm.sh record)."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

pytestmark = pytest.mark.quick

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _status(monkeypatch, rows, codes=("polymarket", "kalshi", "og")):
    from racinglines.web import board as B
    monkeypatch.setattr(B.data, "q", lambda conn, sql, **kw: pd.DataFrame(rows, columns=["exchange", "linked", "last", "recent"]))
    return {r["code"]: r for r in B.recorder_status(None, list(codes), now=NOW)}


def test_empty_every_venue_reads_no_data_yet(monkeypatch):
    st = _status(monkeypatch, [])
    assert [r["state"] for r in st.values()] == ["none", "none", "none"]
    assert st["kalshi"]["name"] == "Kalshi" and st["og"]["linked"] == 0


def test_partial_shows_what_arrived_and_marks_the_rest(monkeypatch):
    st = _status(monkeypatch, [("polymarket", 40, pd.Timestamp(NOW - timedelta(minutes=2)), 38),
                               ("kalshi", 120, pd.Timestamp(NOW - timedelta(hours=3)), 0),
                               ("og", 20, None, 0)])                      # linked, never recorded
    assert st["polymarket"]["state"] == "live" and st["polymarket"]["recent"] == 38
    assert st["kalshi"]["state"] == "stale" and st["kalshi"]["last"] == NOW - timedelta(hours=3)
    assert st["og"]["state"] == "none" and st["og"]["linked"] == 20


def test_a_failing_query_is_unknown_not_an_error(monkeypatch):
    from racinglines.web import board as B

    class Conn:
        rolled = False

        def rollback(self):
            Conn.rolled = True

    def boom(conn, sql, **kw):
        raise RuntimeError("relation does not exist")
    monkeypatch.setattr(B.data, "q", boom)
    out = B.recorder_status(Conn(), ["kalshi", "og"], now=NOW)
    assert [r["state"] for r in out] == ["unknown", "unknown"] and Conn.rolled


def test_the_line_renders_every_state():
    from racinglines.web.app import templates
    recs = [dict(name="Polymarket", state="live", recent=38, linked=40, last=NOW - timedelta(minutes=2), minutes=2),
            dict(name="Kalshi", state="live", recent=40, linked=120, last=NOW - timedelta(minutes=7), minutes=7),
            dict(name="OG.com", state="stale", recent=0, linked=120, last=NOW - timedelta(hours=3), minutes=180),
            dict(name="IndyCar", state="none", recent=0, linked=0, last=None, minutes=None),
            dict(name="Other", state="unknown", recent=0, linked=0, last=None, minutes=None)]
    html = templates.env.get_template("_recorders.html").render(recorders=recs)
    assert "<span class=\"good\">38 of 40 open markets, synced" in html and "2026-10-02 11:58 UTC" in html
    assert "<span class=\"warn\">40 of 120 open markets, synced" in html and "2026-10-02 11:53 UTC" in html
    assert "<span class=\"bad\">synced" in html and "2026-10-02 09:00 UTC" in html
    assert "IndyCar <span class=\"muted\">no data yet" in html and "status unavailable" in html
    assert templates.env.get_template("_recorders.html").render(recorders=None).strip() == ""


def test_exchange_pages_load_with_no_data_at_all(monkeypatch):
    """/markets/kalshi with nothing linked and the status query failing (no database): the page loads and says so."""
    from fastapi.testclient import TestClient
    from starlette.requests import Request

    from racinglines.markets import venues as V
    from racinglines.web import app as A

    def as_maker(request: Request):
        request.state.user = dict(id=1, username="tester", role="maker", sid=None)
        return request.state.user
    monkeypatch.setitem(A.app.dependency_overrides, A.authenticate, as_maker)
    monkeypatch.setitem(A.app.dependency_overrides, A.conn, lambda: None)
    monkeypatch.setattr(A, "_signals_nav", lambda user: None)
    monkeypatch.setattr(V, "KALSHI_VENUE", True)

    def q(conn, sql, **kw):
        if "market_book_snapshots" in sql:
            raise RuntimeError("no database")
        if "max(synced_at)" in sql:
            return pd.DataFrame({"t": [None]})
        if "house_markets" in sql:
            return pd.DataFrame({"market_link_id": pd.Series([], dtype=float)})
        return pd.DataFrame(columns=["id", "token_id", "event_slug", "athlete", "params", "last_price", "tick_size"])
    monkeypatch.setattr(A.data, "q", q)
    from racinglines.web import board as B
    monkeypatch.setattr(B.data, "q", q)
    from racinglines.markets import alerts
    monkeypatch.setattr(alerts, "new_links", lambda conn: set())
    r = TestClient(A.app).get("/markets/kalshi")
    assert r.status_code == 200, r.text[:500]
    assert "No open Kalshi markets linked" in r.text and "Order books recorded: Kalshi" in r.text and "status unavailable" in r.text
