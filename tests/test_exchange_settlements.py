"""Settlement outcomes for a schema exchange (exchanges/og.toml endpoints.settlements, markets/exchange_driver.settle).

OG.com drops an instrument from its listing once it settles, so the outcome comes from a separate feed of every
instrument it settles (mostly FX and crypto). These tests serve that feed from an httpx.MockTransport: three pages
of FX noise with our instruments inside, paged by cursor. No network, and no database except the last test (the
Postgres test database, skipped without one)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest

from racinglines import exchanges as EX
from racinglines.markets import exchange_driver as D

YES, NO, VOID, NEVER = (f"NX.F.OPT.F1-00099-2026.O.1.{n}" for n in (13, 14, 15, 16))
T0 = datetime(2026, 10, 4, 11, 36, tzinfo=timezone.utc)


def ms(t):
    return int(t.timestamp() * 1000)


def row(sym, v, t):
    return {"i": sym, "x": ms(datetime(2026, 11, 30, tzinfo=timezone.utc)), "v": v, "t": ms(t)}


def noise(n, t):
    return [row(f"EURUSD.OPT.{t:%H%M}.{i}", "1.00" if i % 2 else "0.00", t) for i in range(n)]


PAGES = {                                                # cursor -> (rows, next cursor)
    None: (noise(5, T0) + [row(YES, "1.00", T0), row(NO, "0.00", T0)], "c2"),
    "c2": (noise(5, T0 + timedelta(minutes=5)) + [row(VOID, "0.50", T0 + timedelta(minutes=5))], "c3"),
    "c3": (noise(5, T0 + timedelta(hours=2)), None),
}


def transport(log):
    def handler(req):
        assert req.method == "GET"                                   # read-only
        q = dict(req.url.params)
        log.append((req.url.path, q))
        assert req.url.path == "/fcm/v1/public/get-expired-settlement-price"
        assert q["limit"] == "1000" and int(q["since"]) > 0
        rows, nxt = PAGES[q.get("cursor")]
        return httpx.Response(200, json={"id": -1, "code": 0, "result": {"data": rows, **({"next_cursor": nxt} if nxt else {})}})
    return httpx.MockTransport(handler)


def client(log):
    return D.Client("og", transport=transport(log))


@pytest.mark.quick
def test_the_schema_describes_the_feed():
    s = EX.load("og")
    ep, f = s["endpoints"]["settlements"], s["fields"]["settlement"]
    assert ep["path"] == "/get-expired-settlement-price" and ep["start_unit"] == "ns" and ep["cursor_param"] == "cursor"
    assert (f["instrument"], f["value"], f["ts"], f["ts_unit"]) == ("i", "v", "t", "ms")


@pytest.mark.quick
def test_a_row_is_yes_no_or_void():
    s = EX.load("og")
    assert D.settlement(s, row(YES, "1.00", T0)) == (YES, True, 1.0, T0)
    assert D.settlement(s, row(NO, "0.00", T0))[1] is False
    assert D.settlement(s, row(VOID, "0.50", T0))[1:3] == (None, 0.5)
    assert D.settlement(s, {"i": YES}) is None and D.settlement(s, {"v": "1.00"}) is None


@pytest.mark.quick
def test_the_scan_pages_by_cursor_and_stops_once_everything_is_found():
    log = []
    since = pd.Timestamp("2026-10-03", tz="UTC")
    with client(log) as c:
        found, st = D.scan_settlements(c, [YES, NO, VOID], since)
    assert found == {YES: (True, 1.0, T0), NO: (False, 0.0, T0), VOID: (None, 0.5, T0 + timedelta(minutes=5))}
    assert st["pages"] == 2 and not st["exhausted"] and st["scanned"] == 13          # page 3 never asked for
    assert [q.get("cursor") for _, q in log] == [None, "c2"]
    assert int(log[0][1]["since"]) == D.epoch(since, "ns")                          # nanoseconds


@pytest.mark.quick
def test_the_scan_reads_to_the_end_for_a_token_that_never_settles_and_honours_max_pages():
    log = []
    with client(log) as c:
        found, st = D.scan_settlements(c, [YES, NEVER], "2026-10-03")
        assert set(found) == {YES} and st["pages"] == 3 and st["exhausted"]
        assert st["last_ts"] == T0 + timedelta(hours=2)
        found, st = D.scan_settlements(c, [NEVER], "2026-10-03", max_pages=1)
    assert found == {} and st["pages"] == 1 and not st["exhausted"] and st["last_ts"] == T0


def _links():
    seen = T0 - timedelta(hours=3)
    return [SimpleNamespace(token_id=t, params={"contract": "Race Winner"}, resolved_yes=None, closed=True, active=False,
                            synced_at=seen, first_seen_at=seen - timedelta(days=5)) for t in (YES, NO, VOID, NEVER)]


@pytest.fixture
def fake_db(monkeypatch):
    """settle() over in-memory links: `pending` keeps the SQL's rule (closed, resolved_yes empty, no void noted)."""
    links = _links()
    monkeypatch.setattr(D.KS, "competition", lambda session, sport: (SimpleNamespace(id=1), None))
    monkeypatch.setattr(D, "pending", lambda session, code, cid: [
        lk for lk in links if lk.closed and lk.resolved_yes is None and not (lk.params or {}).get("settlement")])
    return SimpleNamespace(commit=lambda: None), {lk.token_id: lk for lk in links}


@pytest.mark.quick
def test_settle_writes_outcomes_notes_voids_and_is_idempotent(fake_db):
    session, links = fake_db
    log = []
    with client(log) as c:
        st = D.settle(session, None, "og", "f1", client=c)
        assert (st["links"], st["matched"], st["resolved"], st["yes"], st["no"], st["void"], st["pending"]) == (4, 3, 2, 1, 1, 1, 1)
        assert st["pages"] == 3                                    # NEVER is missing: the feed is read to its end
        assert int(log[0][1]["since"]) == D.epoch(T0 - timedelta(hours=3, days=1), "ns")   # a day before the last sync
        assert links[YES].resolved_yes is True and links[NO].resolved_yes is False
        assert links[YES].params == {"contract": "Race Winner", "settlement": "yes", "settlement_value": 1.0,
                                     "settled_at": T0.isoformat()}
        assert links[VOID].resolved_yes is None and links[VOID].params["settlement"] == "void"
        mark = pd.Timestamp(links[NEVER].params["settle_scanned_to"])
        assert links[NEVER].resolved_yes is None and abs(mark - pd.Timestamp.now("UTC")) < pd.Timedelta(minutes=1)
        before = {t: dict(lk.params) for t, lk in links.items() if t != NEVER}

        log.clear()
        st = D.settle(session, None, "og", "f1", client=c)          # again: only the missing one is looked for,
        assert (st["links"], st["matched"], st["pending"]) == (1, 0, 1)   # from an hour before the last pass
        assert int(log[0][1]["since"]) == D.epoch(mark - pd.Timedelta(hours=1), "ns")
    assert {t: lk.params for t, lk in links.items() if t != NEVER} == before
    assert links[YES].resolved_yes is True and links[VOID].resolved_yes is None


@pytest.mark.quick
def test_an_exchange_without_a_settlement_feed_does_nothing(monkeypatch, fake_db):
    session, links = fake_db
    schema = {k: v for k, v in EX.load("og").items()}
    schema["endpoints"] = {k: v for k, v in schema["endpoints"].items() if k != "settlements"}
    monkeypatch.setattr(D.EX, "load", lambda code: schema)
    boom = SimpleNamespace(pages=lambda *a, **k: pytest.fail("no feed: nothing is fetched"))
    assert D.settle(session, None, "og", "f1", client=boom) == {"supported": False}
    assert all(lk.resolved_yes is None and "settlement" not in lk.params for lk in links.values())


def test_settle_against_the_database(test_engine):
    """The real pending query and write-back: closed links of the sport only, voids not rescanned, sync-proof."""
    from sqlalchemy import text

    from racinglines.db import models as m
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    from racinglines.markets.kalshi.sync import competition
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()
        comp, cat = competition(s, "f1")
        s.execute(text("DELETE FROM market_links WHERE exchange = 'og'"))
        for tok, closed in ((YES, True), (NO, True), (VOID, True), (NEVER, False)):
            s.add(m.MarketLink(exchange="og", token_id=tok, market_slug=tok, question="Race Winner", outcome="X",
                               competition_id=comp.id, category_id=cat.id, prediction="unmodeled", closed=closed,
                               active=not closed, params={"contract": "Race Winner"}, synced_at=T0 - timedelta(hours=3)))
        s.commit()
        with client([]) as c, test_engine.connect() as conn:
            st = D.settle(s, conn, "og", "f1", client=c)
            assert (st["links"], st["matched"], st["resolved"], st["void"], st["pending"]) == (3, 3, 2, 1, 0)
            assert st["pages"] == 2                                  # all three found: no third page
            assert D.settle(s, conn, "og", "f1", client=c)["links"] == 0
    with test_engine.connect() as conn:
        got = dict(conn.execute(text("SELECT token_id, resolved_yes FROM market_links WHERE exchange = 'og'")).all())
        assert got == {YES: True, NO: False, VOID: None, NEVER: None}
        assert conn.execute(text("SELECT params->>'settled_at' FROM market_links WHERE token_id = :t"), dict(t=YES)).scalar() == T0.isoformat()
