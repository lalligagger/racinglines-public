"""Kalshi connector (markets/kalshi/): the client, title classifier, link / trade / history / book rows, the
database writes and the order gate, all against mocked responses shaped like Kalshi's Trade API v2 docs
(no network: the cloud policy blocks Kalshi, and no credentials exist)."""

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import text

from racinglines.markets.kalshi import client as K
from racinglines.markets.kalshi import sync as KS
from racinglines.markets.kalshi import trade as KT

SERIES = {"series": [{"ticker": "KXF1RACE", "title": "Formula 1 race winner", "category": "Sports"},
                     {"ticker": "KXF1PODIUM", "title": "F1 podium finish", "category": "Sports"},
                     {"ticker": "KXNFLGAME", "title": "Pro football game", "category": "Sports"}]}


def _mk(ticker, event, title, sub, **kw):
    base = dict(ticker=ticker, event_ticker=event, title=title, yes_sub_title=sub, status="active",
                close_time="2026-10-11T14:00:00Z", yes_bid=30, yes_ask=33, last_price=31, volume=1200,
                tick_size=1, rules_primary=f"If {sub} is the official winner, the market resolves to Yes.", result="")
    return dict(base, **kw)


EVENTS = {
    "KXF1RACE": [dict(event_ticker="KXF1RACE-26SIN", series_ticker="KXF1RACE", title="Who will win the Singapore Grand Prix?",
                      mutually_exclusive=True, markets=[
                          _mk("KXF1RACE-26SIN-VER", "KXF1RACE-26SIN", "Singapore GP winner", "Max Verstappen"),
                          _mk("KXF1RACE-26SIN-NOR", "KXF1RACE-26SIN", "Singapore GP winner", "Lando Norris",
                              yes_bid=None, yes_ask=None, yes_bid_dollars="0.2500", yes_ask_dollars="0.2800"),
                          _mk("KXF1RACE-26SIN-XXX", "KXF1RACE-26SIN", "Singapore GP winner", "Someone New", yes_bid=0, yes_ask=100)])],
    "KXF1PODIUM": [dict(event_ticker="KXF1SC-26SIN", series_ticker="KXF1PODIUM", title="Safety car at the Singapore Grand Prix?",
                        markets=[_mk("KXF1SC-26SIN", "KXF1SC-26SIN", "Will there be a safety car?", "Safety car",
                                     status="settled", result="yes", yes_bid=99, yes_ask=100)])],
}
TRADES = {"trades": [dict(trade_id="t1", ticker="KXF1RACE-26SIN-VER", count=10, yes_price=31, no_price=69, taker_side="yes",
                          created_time="2026-10-10T12:00:00Z"),
                     dict(trade_id="t2", ticker="KXF1RACE-26SIN-VER", count=4, yes_price_dollars="0.3000", taker_side="no",
                          created_time="2026-10-10T12:05:00Z")]}
BOOK = {"orderbook": {"yes": [[28, 100], [30, 50]], "no": [[65, 20], [67, 40]]}}
CANDLES = {"candlesticks": [dict(end_period_ts=1791806400, price=dict(close=31), yes_bid=dict(close=30), yes_ask=dict(close=33)),
                            dict(end_period_ts=1791810000, price=dict(close=None), yes_bid=dict(close=32), yes_ask=dict(close=34))]}


def _transport(log):
    def handler(req):
        log.append((req.method, req.url.path, dict(req.url.params)))
        p = req.url.path.removeprefix(K.PREFIX)
        if p == "/series":
            return httpx.Response(200, json=SERIES)
        if p == "/events":
            s, cur = req.url.params.get("series_ticker"), req.url.params.get("cursor")
            evs = EVENTS.get(s, []) if req.url.params.get("status") == "open" or s == "KXF1PODIUM" else []
            if s == "KXF1RACE" and cur is None:          # two pages: the cursor is followed
                return httpx.Response(200, json=dict(events=[], cursor="p2"))
            return httpx.Response(200, json=dict(events=evs, cursor=""))
        if p == "/markets/trades":
            return httpx.Response(200, json=dict(TRADES, cursor=""))
        if p.endswith("/orderbook"):
            return httpx.Response(200, json=BOOK)
        if p.endswith("/candlesticks"):
            return httpx.Response(200, json=CANDLES)
        if p == "/portfolio/orders":
            return httpx.Response(201, json=dict(order=dict(order_id="o1", status="resting")))
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


class FakeResolver:
    def driver(self, name):
        return {"max verstappen": 1, "lando norris": 4}.get((name or "").lower())

    def team(self, name):
        return None

    def race(self, gp, end=None):
        return (77, "2026-17") if gp and "Singapore" in gp else (None, None)


@pytest.mark.quick
def test_classifier_and_gp_names():
    assert KS.gp_name("Who will win the Singapore Grand Prix?") == "Singapore Grand Prix"
    assert KS.gp_name("Formula 1 Mexico City Grand Prix winner") == "Mexico City Grand Prix"
    assert KS.gp_name("Who Will Win The Bahrain Grand Prix") == "Bahrain Grand Prix"
    c = KS.classify
    assert c("Who will win the Singapore Grand Prix?") == ("race_win", "Singapore Grand Prix")
    assert c("Singapore Grand Prix podium finish") == ("race_podium", "Singapore Grand Prix")
    assert c("Singapore Grand Prix pole position") == ("race_pole", "Singapore Grand Prix")
    assert c("Singapore Grand Prix", "Will Norris finish ahead of Piastri?")[0] == "race_h2h"
    assert c("Top constructor at the Singapore Grand Prix")[0] == "race_constructor_top"
    assert c("Fastest lap at the Singapore Grand Prix")[0] == "race_fastest_lap"
    assert c("Red flag at the Singapore Grand Prix?")[0] == "race_red_flag"
    assert c("Will it rain during the Bahrain Grand Prix?")[0] == "race_rain"
    assert c("Bahrain Grand Prix winner")[0] == "race_win"                  # "Bahrain" isn't rain
    assert c("2026 F1 Drivers' Champion") == ("champion", None)
    assert c("F1 Constructors' Championship") == ("constructors_champion", None)
    assert c("Pro football game") == ("unmodeled", None)


@pytest.mark.quick
def test_client_pages_and_prices():
    log = []
    with K.Client(transport=_transport(log)) as kc:
        assert KS.f1_series(kc) == ["KXF1RACE", "KXF1PODIUM"]
        evs = kc.events(series_ticker="KXF1RACE", status="open")
    assert [e["event_ticker"] for e in evs] == ["KXF1RACE-26SIN"]
    assert [p.get("cursor") for m, path, p in log if path.endswith("/events")] == [None, "p2"]
    assert all(path.startswith("/trade-api/v2/") for _, path, _ in log)
    assert K.price(dict(yes_bid=56), "yes_bid") == 0.56 and K.price(dict(yes_bid_dollars="0.5600", yes_bid=1), "yes_bid") == 0.56
    assert K.price({}, "yes_bid") is None


@pytest.mark.quick
def test_link_rows():
    rows = {r["token_id"]: r for r in KS.link_rows(EVENTS["KXF1RACE"] + EVENTS["KXF1PODIUM"], FakeResolver())}
    v = rows["KXF1RACE-26SIN-VER"]
    assert (v["exchange"], v["prediction"], v["athlete_id"], v["race_id"], v["condition_id"]) == ("kalshi", "race_win", 1, 77, "KXF1RACE-26SIN")
    assert (v["last_bid"], v["last_ask"], v["last_price"]) == (0.30, 0.33, pytest.approx(0.315))
    assert v["params"]["event_key"] == "2026-17" and v["params"]["series"] == "KXF1RACE" and "Max Verstappen" in v["params"]["rules"]
    assert v["neg_risk"] and v["tick_size"] == 0.01 and not v["closed"] and v["resolved_yes"] is None
    assert (rows["KXF1RACE-26SIN-NOR"]["last_bid"], rows["KXF1RACE-26SIN-NOR"]["last_ask"]) == (0.25, 0.28)
    x = rows["KXF1RACE-26SIN-XXX"]
    assert x["prediction"] == "unmodeled" and (x["last_bid"], x["last_ask"]) == (None, None)    # unknown driver; empty book
    sc = rows["KXF1SC-26SIN"]
    assert sc["prediction"] == "race_safety_car" and sc["closed"] and sc["resolved_yes"] is True and not sc["active"]


@pytest.mark.quick
def test_trade_history_and_book_rows():
    t = KS.trade_rows("KXF1RACE-26SIN-VER", "KXF1RACE-26SIN", TRADES["trades"])
    assert [(r["side"], r["price"], r["size"], r["tx_hash"]) for r in t] == [("BUY", 0.31, 10.0, "t1"), ("SELL", 0.30, 4.0, "t2")]
    assert t[0]["ts"] == datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    h = KS.history_rows("X", CANDLES["candlesticks"])
    assert [r["price"] for r in h] == [0.31, pytest.approx(0.33)]
    b = KS.book_row("X", BOOK["orderbook"], None)
    assert (b["best_bid"], b["best_ask"]) == (0.30, 0.33)
    assert b["bids"] == [[0.30, 50.0], [0.28, 100.0]] and b["asks"] == [[0.33, 40.0], [0.35, 20.0]]
    assert KS.book_row("X", {"yes_dollars": [["0.30", 5]], "no_dollars": [["0.60", 7]]}, None)["best_ask"] == 0.40


def _key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return k, k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


@pytest.mark.quick
def test_signature_verifies():
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    k, pem = _key()
    h = KT.headers("key-1", pem, "POST", "/trade-api/v2/portfolio/orders?x=1", ts_ms=1700000000000)
    assert h["KALSHI-ACCESS-KEY"] == "key-1" and h["KALSHI-ACCESS-TIMESTAMP"] == "1700000000000"
    k.public_key().verify(base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"]), b"1700000000000POST/trade-api/v2/portfolio/orders",
                          padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())


@pytest.mark.quick
def test_orders_are_dry_runs_unless_enabled(monkeypatch):
    monkeypatch.delenv("KALSHI_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("KALSHI_MAX_ORDER_USD", raising=False)
    log = []
    kc = K.Client(transport=_transport(log))
    _, pem = _key()
    out = KT.place(KT.Order("KXF1RACE-26SIN-VER", "buy", 0.29, 10), kc, "key-1", pem)
    assert not out["sent"] and out["response"] is None and not any(p == "POST" for p, _, _ in log)
    body = out["request"]["json"]
    assert (body["yes_price"], body["count"], body["post_only"], body["side"], body["action"]) == (29, 10, True, "yes", "buy")
    assert "KALSHI-ACCESS-SIGNATURE" in out["request"]["headers"]
    for bad in (KT.Order("T", "buy", 0.33, 1), KT.Order("T", "sell", 0.30, 1), KT.Order("T", "buy", 0.295, 1),
                KT.Order("T", "buy", 0.29, 100), KT.Order("T", "hold", 0.29, 1)):
        with pytest.raises(ValueError):                  # crosses, off-grid, over the $25 cap, bad action
            KT.place(bad, kc, "key-1", pem)
    monkeypatch.setenv("KALSHI_TRADING_ENABLED", "true")
    with pytest.raises(RuntimeError):                    # enabled without credentials: refused, nothing sent
        KT.place(KT.Order("KXF1RACE-26SIN-VER", "buy", 0.29, 10), kc)
    out = KT.place(KT.Order("KXF1RACE-26SIN-VER", "buy", 0.29, 10), kc, "key-1", pem)
    assert out["sent"] and out["response"]["order"]["status"] == "resting"
    post = [x for x in log if x[0] == "POST"]
    assert len(post) == 1 and post[0][1] == "/trade-api/v2/portfolio/orders"


def test_sync_and_tape_write_the_shared_tables(test_engine, monkeypatch):
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    from racinglines.markets.polymarket import sync as PS
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE exchange = 'kalshi'"))
        c.execute(text("DELETE FROM market_trades WHERE token_id LIKE 'KXF1%'"))
    class NoIds(FakeResolver):                           # this database has no F1 races or drivers
        def driver(self, name):
            return None

        def race(self, gp, end=None):
            return None, None
    monkeypatch.setattr(PS, "Resolver", lambda conn, year: NoIds())
    log = []
    kc = K.Client(transport=_transport(log))
    with test_engine.connect() as c, get_session(url) as s:
        st = KS.sync(s, c, 2026, include_closed=True, kc=kc)
        assert st["links"] == 4 and st["new"] == 4 and st["unmatched"] == 4
        assert KS.sync(s, c, 2026, kc=kc)["new"] == 0                  # idempotent
        assert KS.fetch_trades(s, c, ["KXF1RACE-26SIN"], kc=kc) == 6   # 2 trades x 3 markets
        KS.fetch_trades(s, c, ["KXF1RACE-26SIN"], kc=kc)
        assert KS.snapshot_books(s, c, ["KXF1RACE-26SIN"], kc=kc) == 3
    with test_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM market_links WHERE exchange = 'kalshi'")).scalar() == 4
        assert c.execute(text("SELECT count(*) FROM market_trades WHERE token_id LIKE 'KXF1RACE%'")).scalar() == 6
        p = c.execute(text("SELECT params FROM market_links WHERE token_id = 'KXF1RACE-26SIN-VER'")).scalar()
    assert json.loads(json.dumps(p))["series"] == "KXF1RACE"


@pytest.mark.quick
def test_kalshi_backtest_venue_reads_the_shared_tables(monkeypatch):
    import pandas as pd

    from racinglines.markets import store as MS
    from racinglines.markets import venue_replay as VR
    t0 = pd.Timestamp("2026-10-10 12:00", tz="UTC")
    links = pd.DataFrame(dict(token_id=["KXF1RACE-26SIN-VER"], condition_id=["KXF1RACE-26SIN"], prediction=["race_win"],
                              athlete_id=[1], params=[{"event_key": "2026-17"}], exchange=["kalshi"]))
    rows = KS.trade_rows("KXF1RACE-26SIN-VER", "KXF1RACE-26SIN", TRADES["trades"])
    frames = {"prices": pd.DataFrame(dict(token_id=["KXF1RACE-26SIN-VER"] * 2, ts=[t0, t0 + pd.Timedelta(hours=1)],
                                          price=[0.31, 0.33])),
              "trades": pd.DataFrame(rows)}
    monkeypatch.setattr(MS, "read", lambda conn, store, **kw: frames[store])
    v = VR.Kalshi(None, links, "2026-10-10 00:00", "2026-10-11 14:00")
    m = v.markets()[0]
    p, vol, ok = v.view(m, pd.Timestamp("2026-10-10 12:30"), 1.0)
    assert (p, ok) == (0.31, True) and vol == pytest.approx(10 * 0.31 + 4 * 0.30)     # both trades in the last 24 h
    assert v.code == "kalshi" and VR.Kalshi.taker_fee(0.50, 100) == 1.75 and VR.Kalshi.taker_fee(0.01, 1) == 0.01
