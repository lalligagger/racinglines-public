"""New-market alerts (markets/alerts.py): race matching, grouping, the message, the log."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from racinglines.markets import alerts as A


class FakeResolver:
    def __init__(self, races):
        self.races = races                           # gp name -> race id

    def race(self, gp, end=None):
        rid = self.races.get(gp.lower())
        return (rid, f"key-{rid}") if rid else (None, None)


@pytest.mark.parametrize("link, rid", [
    (dict(race_id=7, event_title="whatever"), 7),
    (dict(event_title="Will there be a safety car during the 2026 F1 Azerbaijan Grand Prix?"), 1),
    (dict(event_title="Las Vegas Grand Prix: Head-to-Head"), 2),
    (dict(event_title="Rain?", question="Rain during the Azerbaijan Grand Prix?"), 1),
    (dict(event_title="F1 Drivers' Champion"), None),
])
def test_race_for(link, rid):
    assert A.race_for(FakeResolver({"azerbaijan": 1, "las vegas": 2}), link)[0] == rid


def _g(title, upcoming, new_event=True, n=3, race=None):
    return dict(event_slug=title.lower().replace(" ", "-"), event_title=title, new_event=new_event, kinds=["race_win"],
                n=n, race=race, race_date=None, upcoming=upcoming)


def test_message_leads_with_the_upcoming_race():
    title, body, urgent = A.message([_g("Singapore Grand Prix: Winner", True, race="Singapore Grand Prix"),
                                     _g("Will Max Verstappen retire?", False, n=1)])
    assert urgent and "Singapore Grand Prix" in title
    assert "Singapore Grand Prix: Winner (new event)" in body


def test_message_without_upcoming_races():
    title, body, urgent = A.message([_g("F1 Drivers' Champion", False, new_event=False, n=2)])
    assert not urgent and title == "1 new F1 market on Polymarket"
    assert "(+2 outcomes)" in body


@pytest.mark.parametrize("short, official, name", [
    ("Singapore Grand Prix", "FORMULA 1 SINGAPORE AIRLINES SINGAPORE GRAND PRIX 2026", "Singapore Grand Prix"),
    ("FORMULA", "FORMULA 1 HEINEKEN LAS VEGAS GRAND PRIX 2026", "FORMULA 1 HEINEKEN LAS VEGAS GRAND PRIX 2026"),
])
def test_race_name(short, official, name):
    assert A._race_name(short, official) == name


def test_notify_logs_and_skips_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("RACINGLINES_NTFY_TOPIC", raising=False)
    log = tmp_path / "new.jsonl"
    assert A.notify([], log=log) == [] and not log.exists()
    assert A.notify([_g("Qatar Grand Prix: Pole", True)], log=log, mac=False) == ["log"]
    row = json.loads(log.read_text().splitlines()[0])
    assert row["event_title"] == "Qatar Grand Prix: Pole" and row["at"]


def test_summarize_orders_upcoming_first():
    """Against the local database (read-only): an upcoming F1 race resolves from a prop's title."""
    from racinglines.db.config import get_engine
    from racinglines.markets.polymarket.sync import Resolver
    try:
        with get_engine().connect() as c:
            row = c.execute(text("""SELECT r.format->>'event_name', e.name, e.start_date FROM races r
                JOIN events e ON e.id = r.event_id JOIN seasons s ON s.id = e.season_id
                JOIN competitions co ON co.id = s.competition_id
                WHERE co.code = 'f1_wdc' AND e.start_date >= current_date AND e.name ILIKE '%grand prix%'
                ORDER BY e.start_date LIMIT 1""")).first()
            if row is None:
                pytest.skip("no upcoming F1 race in the database")
            nxt = (A._race_name(row[0], row[1]), row[2])
            now = datetime.now(timezone.utc)
            end = datetime.combine(nxt[1], datetime.min.time(), timezone.utc) + timedelta(hours=14)
            new = [dict(event_slug="x-champ", event_title="F1 Drivers' Champion", prediction="champion", closed=False,
                        synced_at=now),
                   dict(event_slug="x-sc", event_title=f"Will there be a safety car during the 2026 F1 {nxt[0]}?",
                        prediction="unmodeled", closed=False, end_date=end, synced_at=now),
                   dict(event_slug="x-old", event_title="Closed", prediction="race_win", closed=True, synced_at=now)]
            groups = A.summarize(c, new, Resolver(c, nxt[1].year), today=date.today())
    except Exception as ex:                              # noqa: BLE001
        if "connect" in str(ex).lower():
            pytest.skip(f"no database: {ex}")
        raise
    assert [g["event_slug"] for g in groups] == ["x-sc", "x-champ"]
    assert groups[0]["upcoming"] and groups[0]["race"] == nxt[0] and groups[0]["new_event"]
    assert not groups[1]["upcoming"]
