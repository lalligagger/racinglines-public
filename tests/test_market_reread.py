"""Closing decided markets: the Polymarket and Kalshi syncs list only open events, so a market that closes between
passes (pole after qualifying) used to stay open in market_links with its last quote. Each sync now re-reads the
open links its listing stopped returning. Mocked responses only (the tape-only NASCAR path, no driver or race lookup)."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from racinglines.markets.kalshi import client as K
from racinglines.markets.kalshi import sync as KS
from racinglines.markets.polymarket import sync as PS


def _db(test_engine):
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'rr-%'"))
    return url


def _links(c):
    return {r["token_id"]: r for r in c.execute(text("""SELECT token_id, closed, active, resolved_yes, last_bid, last_ask,
                                                        last_price, synced_at FROM market_links
                                                        WHERE token_id LIKE 'rr-%'""")).mappings().all()}


# Polymarket: the event leaves the active listing once it closes; /events?slug= still returns it, closed.

def _pm_market(slug, tokens, closed, prices, bid=None, ask=None):
    return dict(slug=slug, question=f"Will {slug} take pole?", conditionId="0x" + slug, clobTokenIds=json.dumps(tokens),
                outcomes=json.dumps(["Yes", "No"]), outcomePrices=json.dumps(prices), bestBid=bid, bestAsk=ask,
                endDate="2026-11-07T20:00:00Z", closed=closed, volume="500")


def _pm_event(closed):
    return dict(slug="rr-pole", title="Pole Position", markets=[
        _pm_market("rr-a", ["rr-a-y", "rr-a-n"], closed, ["1", "0"] if closed else ["0.6", "0.4"],
                   *((None, None) if closed else (0.58, 0.62))),
        _pm_market("rr-b", ["rr-b-y", "rr-b-n"], closed, ["0", "1"] if closed else ["0.4", "0.6"],
                   *((None, None) if closed else (0.38, 0.42)))])


def _slugs(gamma):
    return [q["slug"] for q in gamma["log"] if q.get("slug", "").startswith("rr-")]


@pytest.fixture
def gamma(monkeypatch):
    state = dict(listed=True, log=[])

    def handler(req):
        q = dict(req.url.params)
        state["log"].append(q)
        if q.get("closed") == "false" and q.get("tag_slug") == "nascar":
            return httpx.Response(200, json=[_pm_event(False)] if state["listed"] else [])
        if q.get("slug") == "rr-pole":
            return httpx.Response(200, json=[_pm_event(not state["listed"])])
        if q.get("slug") == "rr-gone":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=[])
    real = httpx.Client
    monkeypatch.setattr(PS.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return state


def test_polymarket_closes_an_event_that_left_the_active_listing(test_engine, gamma):
    from racinglines.db.config import get_session
    url = _db(test_engine)
    with test_engine.begin() as c:     # an open link whose event Gamma can't serve right now: left as it is
        c.execute(text("""INSERT INTO market_links (token_id, exchange, event_slug, prediction, question, outcome, competition_id,
                                                    first_seen_at, synced_at, closed)
                          SELECT 'rr-gone-y', 'polymarket', 'rr-gone', 'unmodeled', 'Gone?', 'Yes', id, now(),
                                 now() - interval '1 day', false FROM competitions WHERE code = 'nascar_cup'"""))
    with test_engine.connect() as c, get_session(url) as s:
        st = PS.sync(s, c, 2026, sport="nascar")
        assert st["reread"] == 0 and "rr-pole" not in _slugs(gamma)        # still listed: no re-read
    with test_engine.connect() as c:
        before = _links(c)
    assert not before["rr-a-y"]["closed"] and before["rr-a-y"]["last_bid"] == 0.58

    gamma["listed"], gamma["log"] = False, []     # qualifying is over: the event is closed and off the active listing
    with test_engine.connect() as c, get_session(url) as s:
        st = PS.sync(s, c, 2026, sport="nascar")
    assert st["reread"] == 1 and st["links"] == 2
    assert _slugs(gamma) == ["rr-pole", "rr-gone"]
    with test_engine.connect() as c:
        after = _links(c)
    a, b = after["rr-a-y"], after["rr-b-y"]
    assert a["closed"] and not a["active"] and a["resolved_yes"] is True and a["last_price"] == 1.0
    assert b["closed"] and b["resolved_yes"] is False and b["last_price"] == 0.0
    assert a["synced_at"] > before["rr-a-y"]["synced_at"]
    assert not after["rr-gone-y"]["closed"] and after["rr-gone-y"]["synced_at"] == before["rr-gone-y"]["synced_at"]

    gamma["log"].clear()               # closed now: never re-read again
    with test_engine.connect() as c, get_session(url) as s:
        assert PS.sync(s, c, 2026, sport="nascar")["reread"] == 0
    assert _slugs(gamma) == ["rr-gone"]


@pytest.mark.quick
def test_polymarket_reread_skips_listed_slugs_and_caps():
    class Conn:
        def execute(self, *a):
            class R:
                def scalars(self):
                    return iter(["listed", "x1", "x2", "x3"])
            return R()
    assert PS._vanished(Conn(), 1, {"listed": {}}, limit=2) == ["x1", "x2"]
    assert PS._by_slug([]) == {}


# Kalshi: the event leaves status=open once its markets close; /markets/{ticker} still serves each one.

def _k_market(ticker, **kw):
    return dict(dict(ticker=ticker, event_ticker="RRPOLE-26", title="Pole position", yes_sub_title=ticker[-1],
                     status="active", close_time="2026-11-07T20:00:00Z", yes_bid=55, yes_ask=58, last_price=56,
                     volume=100, tick_size=1, result=""), **kw)


class Kalshi:
    """KS.sync's client: one open event while `listed`; afterwards only /markets/{ticker} answers."""

    def __init__(self):
        self.listed, self.asked = True, []

    def events(self, series_ticker=None, status=None):
        if status != "open" or not self.listed or series_ticker != "RRPOLE":
            return []
        return [dict(event_ticker="RRPOLE-26", series_ticker="RRPOLE", title="Pole position",
                     markets=[_k_market("rr-k-A"), _k_market("rr-k-B", yes_bid=40, yes_ask=44)])]

    def market(self, ticker):
        self.asked.append(ticker)
        if ticker in ("rr-k-old", "rr-k-later"):   # settled before Kalshi's historical cutoff: a 404 on the live endpoint
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "http://k"), response=httpx.Response(404))
        won = ticker.endswith("A")
        return _k_market(ticker, status="finalized", result="yes" if won else "no",
                         yes_bid=99 if won else 0, yes_ask=100 if won else 1, last_price=99 if won else 1)


def test_kalshi_closes_markets_that_left_the_open_listing(test_engine):
    from racinglines.db.config import get_session
    url = _db(test_engine)
    kc = Kalshi()
    with test_engine.connect() as c, get_session(url) as s:
        st = KS.sync(s, c, 2026, kc=kc, sport="nascar", series=["RRPOLE"])
        assert (st["links"], st["reread"]) == (2, 0) and kc.asked == []
    with test_engine.begin() as c:     # two open links Kalshi 404s: one ended last week, one ends next week
        for tok, end in (("rr-k-old", datetime.now(timezone.utc) - timedelta(days=7)),
                         ("rr-k-later", datetime.now(timezone.utc) + timedelta(days=7))):
            c.execute(text("""INSERT INTO market_links (token_id, exchange, event_slug, prediction, question, outcome,
                                                        competition_id, params, end_date, first_seen_at, synced_at, closed)
                              SELECT :t, 'kalshi', 'RRPOLE-25', 'unmodeled', 'Old?', 'Yes', id, '{"series": "RRPOLE"}',
                                     :e, now(), now() - interval '7 days', false FROM competitions WHERE code = 'nascar_cup'"""),
                      dict(t=tok, e=end))
    with test_engine.connect() as c:
        before = _links(c)

    kc.listed = False                  # the markets closed: the open listing no longer returns the event
    with test_engine.connect() as c, get_session(url) as s:
        st = KS.sync(s, c, 2026, kc=kc, sport="nascar", series=["RRPOLE"])
    assert (st["links"], st["reread"]) == (0, 3)
    assert kc.asked == ["rr-k-A", "rr-k-B", "rr-k-old", "rr-k-later"]        # most recently synced first
    with test_engine.connect() as c:
        after = _links(c)
    a, b = after["rr-k-A"], after["rr-k-B"]
    assert a["closed"] and not a["active"] and a["resolved_yes"] is True and a["last_bid"] == pytest.approx(0.99)
    assert b["closed"] and b["resolved_yes"] is False and a["synced_at"] > before["rr-k-A"]["synced_at"]
    assert after["rr-k-old"]["closed"] and after["rr-k-old"]["resolved_yes"] is None
    assert not after["rr-k-later"]["closed"]                                  # not ended yet: a 404 proves nothing

    kc.asked.clear()                   # only the still-open one is asked again; another series' links never are
    with test_engine.connect() as c, get_session(url) as s:
        assert KS.sync(s, c, 2026, kc=kc, sport="nascar", series=["OTHER"])["reread"] == 0
        assert kc.asked == []
        assert KS.sync(s, c, 2026, kc=kc, sport="nascar", series=["RRPOLE"])["reread"] == 0
        assert kc.asked == ["rr-k-later"]
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'rr-%'"))


def test_kalshi_client_market_reads_one_ticker():
    log = []

    def handler(req):
        log.append(req.url.path)
        return httpx.Response(200, json=dict(market=_k_market("rr-k-A", status="finalized", result="yes")))
    with K.Client(transport=httpx.MockTransport(handler)) as kc:
        mk = kc.market("rr-k-A")
    assert log == ["/trade-api/v2/markets/rr-k-A"] and mk["status"] == "finalized"
    assert KS._quote(mk)[0] == pytest.approx(0.55)
