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
