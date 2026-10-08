"""Polymarket sync for the tape-only sports (NASCAR, MotoGP, IndyCar): schema tags, additive upserts, CLI routing.
Built on a mocked Gamma API (httpx.MockTransport); the tag slugs are unverified against the live API."""
import json

import httpx
import pytest
from sqlalchemy import text

from racinglines import sports
from racinglines.markets.polymarket import sync as PS


def _market(slug, q, tokens, bid, ask):
    return dict(slug=slug, question=q, conditionId="0x" + slug, clobTokenIds=json.dumps(tokens),
                outcomes=json.dumps(["Yes", "No"]), outcomePrices=json.dumps([str(ask), str(round(1 - ask, 2))]),
                bestBid=bid, bestAsk=ask, endDate="2026-11-08T23:00:00Z", negRisk=True, volume="1200.5")


EVENT = dict(slug="nascar-cup-2026-champion", title="NASCAR Cup Series Champion", negRisk=True, markets=[
    _market("larson-champ", "Will Kyle Larson win the 2026 NASCAR Cup Series?", ["tok-larson-y", "tok-larson-n"], 0.30, 0.33),
    _market("byron-champ", "Will William Byron win the 2026 NASCAR Cup Series?", ["tok-byron-y", "tok-byron-n"], 0.10, 0.12)])


def _transport(log, events=(EVENT,)):
    def handler(req):
        q = dict(req.url.params)
        log.append((req.url.path, q))
        if req.url.path == "/events" and q.get("closed") == "false":
            return httpx.Response(200, json=list(events) if q.get("tag_slug") in ("nascar", "motogp-x") else [])
        return httpx.Response(200, json=[])
    return httpx.MockTransport(handler)


@pytest.fixture
def gamma(monkeypatch):
    log = []
    real = httpx.Client
    monkeypatch.setattr(PS.httpx, "Client", lambda **kw: real(transport=_transport(log), **kw))
    monkeypatch.setattr(PS, "Resolver", lambda conn, year: (_ for _ in ()).throw(AssertionError("no resolver for a tape-only sport")))
    monkeypatch.setattr(PS, "classify", lambda *a: (_ for _ in ()).throw(AssertionError("no classifier for a tape-only sport")))
    return log


@pytest.mark.quick
def test_polymarket_tags_per_sport():
    assert sports.polymarket_tags("nascar") == ("nascar",)
    assert sports.polymarket_tags("motogp") == ("motogp",) and sports.polymarket_tags("indycar") == ("indycar",)
    assert sports.polymarket_tags("f1") == () and sports.polymarket_tags("mtb_dh") == ()
    assert PS.TAGS == ("f1", "formula1")                       # F1 keeps its own list


@pytest.mark.quick
def test_sport_without_tags_raises():
    with pytest.raises(ValueError):
        PS.sync(None, None, sport="mtb_dh")


@pytest.mark.quick
def test_cli_routes_tape_only_sports_to_polymarket(monkeypatch, capsys):
    from racinglines.cli import markets as CM
    calls = []
    monkeypatch.setattr(CM, "polymarket", lambda db, argv, sport: calls.append((sport, argv)) or 0)
    assert CM.main(["--sport", "nascar", "sync", "--tags", "x"]) == 0
    assert calls == [("nascar", ["sync", "--tags", "x"])]
    assert CM.polymarket_sports() == ["f1", "nascar", "motogp", "indycar"]
    with pytest.raises(SystemExit):
        CM.main(["--sport", "mtb_dh", "sync"])                 # not a Polymarket sport: still refused
    monkeypatch.setattr(CM, "polymarket_sports", lambda: ["f1"])
    assert CM.main(["--sport", "motogp", "sync"]) == 2 and "only Kalshi" in capsys.readouterr().err


def test_tape_only_sync_is_additive_and_unmodeled(test_engine, gamma):
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'tok-%' OR token_id = 'pre-existing-f1'"))
        c.execute(text("""INSERT INTO market_links (token_id, exchange, event_slug, prediction, question, outcome, competition_id,
                                                    first_seen_at, synced_at, closed)
                          SELECT 'pre-existing-f1', 'polymarket', 'f1-old', 'champion', 'Old F1 market?', 'Yes', id, now(), now(), false
                          FROM competitions WHERE code = 'f1_wdc'"""))
    with test_engine.connect() as c, get_session(url) as s:
        new = []
        st = PS.sync(s, c, 2026, sport="nascar", new=new)
        assert (st["events"], st["links"], st["new"], st["modeled"]) == (1, 2, 2, 0) and len(new) == 2
        assert PS.sync(s, c, 2026, sport="nascar")["new"] == 0                       # idempotent
        assert {p["tag_slug"] for path, p in gamma if path == "/events"} == {"nascar"}
    with test_engine.connect() as c:
        rows = c.execute(text("""SELECT co.code, l.prediction, l.race_id, l.athlete_id, l.params, l.token_id, l.last_bid FROM market_links l
                                 JOIN competitions co ON co.id = l.competition_id WHERE l.token_id LIKE 'tok-%'""")).all()
        assert len(rows) == 2 and {r[0] for r in rows} == {"nascar_cup"} and {r[1] for r in rows} == {"unmodeled"}
        # no driver or race in this database to match, so none is set; the only params a NASCAR link may carry are the
        # identity pass's (sources/nascar/links.py), which never make it modeled
        assert all(r[2] is None and r[3] is None and set(r[4] or {}) <= {"kind", "nascar_series", "season"} for r in rows)
        assert {r[5]: r[6] for r in rows}["tok-larson-y"] == 0.30
        assert c.execute(text("SELECT count(*) FROM market_links WHERE token_id = 'pre-existing-f1'")).scalar() == 1   # additive
        assert PS._sport_where(None, "nascar")[1] == {"c": "nascar_cup"}


def test_tags_override_pages_the_named_slug(test_engine, gamma):
    from racinglines.db.config import get_session
    url = test_engine.url.render_as_string(hide_password=False)
    with test_engine.connect() as c, get_session(url) as s:
        st = PS.sync(s, c, 2026, sport="motogp", tags=["motogp-x"])
        assert st["events"] == 1
    assert {p["tag_slug"] for path, p in gamma if path == "/events"} == {"motogp-x"}
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'tok-%'"))


@pytest.mark.quick
def test_cli_routes_f1_trades_and_history_without_events_to_the_generic_path(monkeypatch):
    from racinglines.cli import markets as CM
    calls = []
    monkeypatch.setattr(CM, "polymarket", lambda db, argv, sport: calls.append((sport, argv)) or 0)
    assert CM.main(["--sport", "f1", "trades", "--open", "--since-hours", "2"]) == 0      # the recorder's pass
    assert CM.main(["--sport", "f1", "history", "--start", "2026-09-01T00:00", "--end", "2026-10-08T00:00"]) == 0
    assert calls == [("f1", ["trades", "--open", "--since-hours", "2"]),
                     ("f1", ["history", "--start", "2026-09-01T00:00", "--end", "2026-10-08T00:00"])]
    from racinglines.cli import f1 as F1
    monkeypatch.setattr(F1, "main", lambda argv: calls.append(("f1.py", argv)) or 0)
    assert CM.main(["--sport", "f1", "trades", "--events", "f1-singapore%"]) == 0               # named events: as before
    assert calls[-1] == ("f1.py", ["pm-trades", "--events", "f1-singapore%"])


def test_default_books_take_modeled_and_race_linked_f1_markets(test_engine, monkeypatch):
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'bk-%'"))
        c.execute(text("DELETE FROM events WHERE source_key = 'bk-upcoming'"))
        c.execute(text("""INSERT INTO seasons (competition_id, year) SELECT id, 2093 FROM competitions WHERE code = 'f1_wdc'
                          AND NOT EXISTS (SELECT 1 FROM seasons s WHERE s.competition_id = competitions.id AND s.year = 2093)"""))
        ev = c.execute(text("""INSERT INTO events (season_id, source, source_key, name, start_date, status)
                               SELECT s.id, 'test', 'bk-upcoming', 'Upcoming GP', '2093-10-11', 'scheduled' FROM seasons s
                               JOIN competitions co ON co.id = s.competition_id WHERE co.code = 'f1_wdc' AND s.year = 2093
                               RETURNING id""")).scalar()
        race = c.execute(text("""INSERT INTO races (event_id, category_id) SELECT :e, cat.id FROM categories cat
                                 JOIN competitions co ON co.id = cat.competition_id WHERE co.code = 'f1_wdc' LIMIT 1
                                 RETURNING id"""), dict(e=ev)).scalar()
        rows = [("bk-modeled-season", "champion", None, "f1_wdc"), ("bk-unmodeled-season", "unmodeled", None, "f1_wdc"),
                ("bk-unmodeled-race", "unmodeled", race, "f1_wdc"), ("bk-nascar-race", "unmodeled", race, "nascar_cup")]
        for tok, pred, rid, comp in rows:
            c.execute(text("""INSERT INTO market_links (token_id, exchange, event_slug, prediction, question, outcome, competition_id,
                                                        race_id, first_seen_at, synced_at, closed)
                              SELECT :t, 'polymarket', 'bk', :p, 'Q?', 'Yes', id, :r, now(), now(), false
                              FROM competitions WHERE code = :c"""), dict(t=tok, p=pred, r=rid, c=comp))
    asked = []
    monkeypatch.setattr(PS.http, "post", lambda c, path, json: asked.extend(x["token_id"] for x in json)
                        or type("R", (), dict(status_code=200, json=lambda self: []))())
    with test_engine.connect() as c, get_session(url) as s:
        PS.snapshot_books(s, c)
    with test_engine.begin() as c:
        n = c.execute(text("SELECT count(*) FROM market_links WHERE token_id LIKE 'bk-%'")).scalar()
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'bk-%'"))
        c.execute(text("DELETE FROM events WHERE source_key = 'bk-upcoming'"))
        c.execute(text("DELETE FROM seasons WHERE year = 2093 AND NOT EXISTS (SELECT 1 FROM events e WHERE e.season_id = seasons.id)"))
    assert n == 4                           # (2093: a far-future season no other test uses)
    # a race-linked F1 market whose kind isn't modeled yet is booked; an unmodeled season market and another sport's
    # market are not
    assert {t for t in asked if t.startswith("bk-")} == {"bk-modeled-season", "bk-unmodeled-race"}


@pytest.mark.quick
def test_history_pulls_in_short_windows_and_says_refusals(monkeypatch, capsys):
    """A 37-day /prices-history request stored nothing in the 2026-10-08 backfill: the span is cut into HISTORY_WINDOW
    pieces, and a refused piece is printed instead of counted as a silent 0."""
    from datetime import datetime, timezone
    asked, real = [], httpx.Client

    def handler(req):
        q = {k: int(v) for k, v in req.url.params.items() if k in ("startTs", "endTs")}
        asked.append((q["startTs"], q["endTs"]))
        if q["endTs"] - q["startTs"] > PS.HISTORY_WINDOW.total_seconds():
            return httpx.Response(400, json={"error": "interval too long"})
        if len(asked) == 2:
            return httpx.Response(500, text="flaky")
        return httpx.Response(200, json={"history": [{"t": q["startTs"], "p": 0.5}]})
    monkeypatch.setattr(PS.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(PS.http, "get", lambda c, path, params: c.get(path, params=params))

    class Session:
        def __init__(self):
            self.rows = 0
        def execute(self, stmt):
            self.rows += 1
        def commit(self):
            pass
    s = Session()
    start, end = datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2026, 10, 8, 7, 37, tzinfo=timezone.utc)
    n = PS.fetch_history(s, None, None, start, end, tokens=["tok"])
    assert all(b - a <= PS.HISTORY_WINDOW.total_seconds() for a, b in asked)
    assert asked[0][0] == int(start.timestamp()) and asked[-1][1] == int(end.timestamp())
    assert len(asked) == 6 and n == 5                          # 37 days in 7-day pieces; the 500 piece is skipped
    assert "HTTP 500" in capsys.readouterr().err
