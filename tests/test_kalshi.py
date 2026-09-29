"""Kalshi connector (markets/kalshi/): the client, title classifier, link / trade / history / book rows, the
database writes and the order gate, against mocked responses: first shaped like Kalshi's Trade API v2 docs,
then (LIVE_*) copied from the live read-only API on 2026-09-28. No network, no credentials."""

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
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
        if p == "/historical/trades":
            return httpx.Response(200, json=dict(trades=[], cursor=""))
        if p == "/historical/markets":
            return httpx.Response(200, json=dict(markets=[], cursor=""))
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


@pytest.mark.quick
def test_kalshi_venue_counts_each_markets_own_volume(monkeypatch):
    """A Kalshi condition_id is the event ticker: two drivers' markets of one event don't share liquidity."""
    import pandas as pd

    from racinglines.markets import store as MS
    from racinglines.markets import venue_replay as VR
    t0 = pd.Timestamp("2026-10-10 12:00", tz="UTC")
    toks = ["KXF1RACE-26SIN-VER", "KXF1RACE-26SIN-NOR"]
    links = pd.DataFrame(dict(token_id=toks, condition_id=["KXF1RACE-26SIN"] * 2, prediction=["race_win"] * 2,
                              athlete_id=[1, 2], params=[{}, {}], exchange=["kalshi"] * 2))
    trades = pd.DataFrame(KS.trade_rows(toks[0], "KXF1RACE-26SIN", TRADES["trades"]))
    frames = {"prices": pd.DataFrame(dict(token_id=toks, ts=[t0, t0], price=[0.31, 0.20])), "trades": trades}
    seen = []
    monkeypatch.setattr(MS, "read", lambda conn, store, **kw: seen.append(kw.get("root")) or frames[store])
    v = VR.Kalshi(None, links, "2026-10-10 00:00", "2026-10-11 14:00")
    at = pd.Timestamp("2026-10-10 12:30")
    assert v.view(v.markets()[0], at, 1.0)[1] == pytest.approx(10 * 0.31 + 4 * 0.30)
    assert v.view(v.markets()[1], at, 1.0) == (0.20, 0.0, False)
    assert seen and all(str(r).endswith("kalshi") for r in seen)


@pytest.mark.quick
def test_maker_fee_is_off_by_default_and_charged_per_fill():
    from racinglines.markets.strategies import maker_replay as R
    HOUR = int(3600e9)

    def mk():
        return R.Market(cond="T1", kind="race_win", subject="T1", question="T1", fairs={1: 0.5}, outcome=True,
                        mid_ts=np.array([0], dtype="int64"), mid_px=np.array([0.5]),
                        tr_ts=np.array([10, 20], dtype="int64"), tr_px=np.array([0.40, 0.60]),
                        tr_sz=np.array([100.0, 100.0]), tr_buy=np.array([False, True]))
    data = dict(markets=[mk()], stages=[dict(run_id=1, start=0, end=HOUR, session_end=False)])
    p = R.Params(pull_min=0, min_volume_24h=0, size=10, half_spread=0.02)
    free = R.replay(data, p)["positions"]["cash"].sum()
    paid = R.replay(dict(data, markets=[mk()]), R.Params(**{**p.__dict__, "maker_fee": R.KALSHI_MAKER_FEE}))
    n = len(paid["fills"])
    assert n == 2 and free == pytest.approx(10 * (0.52 - 0.48))
    fee = R.venue_fee(R.KALSHI_MAKER_FEE, 0.48, 10) + R.venue_fee(R.KALSHI_MAKER_FEE, 0.52, 10)
    assert paid["positions"]["cash"].sum() == pytest.approx(free - fee) and fee == pytest.approx(0.10)     # 5c a fill: rounded up
    assert R.venue_fee(0.07, 0.50, 100) == 1.75


# Shapes from the live API (2026-09-28), trimmed: dollar strings, `_fp` sizes, `orderbook_fp`, and the
# /historical endpoints for markets settled before Kalshi's cutoff.
LIVE_SERIES = {"series": [{"ticker": "KXF1RACE", "title": "F1 Race", "category": "Sports"},
                          {"ticker": "KXF1POLEPOSITION", "title": "Qualify in Pole Position", "category": "Sports"},
                          {"ticker": "KXNCAAF1H", "title": "College Football 1st Half Winner", "category": "Sports"}]}
LIVE_MARKET = {"ticker": "KXF1RACE-BELGP26-VER", "event_ticker": "KXF1RACE-BELGP26", "status": "finalized", "result": "no",
               "title": "Will Max Verstappen finish in first in the main race at the 2026 Belgian Grand Prix?",
               "yes_sub_title": "Max Verstappen", "close_time": "2026-07-19T22:52:10Z", "yes_bid_dollars": "0.0000",
               "yes_ask_dollars": "1.0000", "last_price_dollars": "0.0100", "volume_fp": "362818.18",
               "price_level_structure": "linear_cent"}
LIVE_BOOK = {"orderbook_fp": {"no_dollars": [["0.9600", "27.64"], ["0.9700", "11715.50"]], "yes_dollars": [["0.0100", "9128.21"]]}}
LIVE_CANDLE = {"end_period_ts": 1790002800, "price": {"close_dollars": "0.1100"}, "yes_bid": {"close_dollars": "0.1000"},
               "yes_ask": {"close_dollars": "0.1100"}}
HIST_CANDLE = {"end_period_ts": 1784001600, "price": {"close": "0.0700"}, "yes_bid": {"close": "0.0600"},
               "yes_ask": {"close": "0.0700"}}
LIVE_TRADE = {"count_fp": "93.51", "created_time": "2026-07-19T22:38:54.335565Z", "taker_side": "yes",
              "ticker": "KXF1RACE-BELGP26-VER", "trade_id": "d847db05-11b5-6773-48c5-2bb7ba997268", "yes_price_dollars": "0.0100"}


def _live_transport(log):
    def handler(req):
        log.append(req.url.path)
        p = req.url.path.removeprefix(K.PREFIX)
        if p == "/series":
            return httpx.Response(200, json=LIVE_SERIES)
        if p.endswith("/orderbook"):
            return httpx.Response(200, json=LIVE_BOOK)
        if p.startswith("/series/"):                     # settled before the cutoff: only /historical has it
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "not found"}})
        if p.startswith("/historical/markets/") and p.endswith("/candlesticks"):
            return httpx.Response(200, json={"candlesticks": [HIST_CANDLE]})
        if p == "/historical/markets":
            return httpx.Response(200, json={"markets": [LIVE_MARKET], "cursor": ""})
        if p == "/markets/trades":
            return httpx.Response(200, json={"trades": [], "cursor": ""})
        if p == "/historical/trades":
            return httpx.Response(200, json={"trades": [LIVE_TRADE], "cursor": ""})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


@pytest.mark.quick
def test_live_titles_classify():
    c = KS.classify
    assert c("Azerbaijan Grand Prix Winner", "Oscar Piastri to finish in first") == ("race_win", "Azerbaijan Grand Prix")
    assert c("Azerbaijan Grand Prix Main Race: Podium Finishers", "Oscar Piastri to finish")[0] == "race_podium"
    assert c("Azerbaijan Grand Prix Main Race: Top 10 Finishers", "Oscar Piastri to finish top 10")[0] == "race_top10"
    assert c("Azerbaijan Grand Prix Main Race: Top 5 Finishers", "Oscar Piastri to finish top 5")[0] == "unmodeled"
    assert c("Spanish Grand Prix Qualifying Session (Q3): Pole Position", "Oscar Piastri is awarded Pole Position")[0] == "race_pole"
    assert c("Azerbaijan Grand Prix Main Race: Top Constructor", "McLaren to finish in first")[0] == "race_constructor_top"
    assert c("Azerbaijan Grand Prix Main Race: Fastest Lap", "Fastest Lap: Oscar Piastri")[0] == "race_fastest_lap"
    for sprint in ("Dutch Grand Prix: Sprint Race Winner", "Dutch Grand Prix Sprint Qualifying: Pole Position",
                   "Dutch Grand Prix Sprint Race: Fastest Lap", "Dutch Grand Prix Sprint Race: Top Constructor"):
        assert c(sprint)[0] == "unmodeled"               # sprints aren't the model's race
    assert c("F1 Drivers Champion", "Will Lando Norris win the F1 Drivers Championship?") == ("champion", None)
    assert c("F1 Constructors Champion")[0] == "constructors_champion"
    assert c("F1 Matchup: Verstappen vs Hamilton", "Will Max Verstappen beat Lewis Hamilton in the racing matchup?") \
        == ("unmodeled", None)                           # no Grand Prix named ...
    assert c("F1 Matchup: Verstappen vs Hamilton", "", gp="British Grand Prix") == ("race_h2h", "British Grand Prix")



@pytest.mark.quick
def test_2025_titles_and_each_event_matched_in_its_own_season():
    assert KS.gp_name("F1 Australian Grand Prix Winner?") == "Australian Grand Prix"
    assert KS.gp_name("Las Vegas GP: Qualify in Pole Position") == "Las Vegas Grand Prix"
    assert KS.gp_name("Gran Premio de Mexico Winner?") == "Mexico Grand Prix"
    assert KS.classify("Abu Dhabi Grand Prix 2025 Podium Finishers?") == ("race_podium", "Abu Dhabi Grand Prix")
    assert [KS.season(dict(event_ticker=t), 2026) for t in ("KXF1RACE-ABUDGP25", "KXF1-25", "KXF1H2H-BRIGP26VERHAM")] \
        == [2025, 2025, 2026]
    assert KS.season(dict(event_ticker="KXAFRICAF1", markets=[dict(close_time="2027-01-01T00:00:00Z")])) == 2027

@pytest.mark.quick
def test_live_head_to_head_takes_the_weekends_grand_prix():
    class R(FakeResolver):
        def driver(self, name):
            return {"max verstappen": 1, "lewis hamilton": 44}.get((name or "").lower())

        def race(self, gp, end=None):
            return (9, "2026-09") if gp == "British Grand Prix" else (None, None)
    win = dict(event_ticker="KXF1RACE-BRIGP26", series_ticker="KXF1RACE", title="British Grand Prix Winner", markets=[])
    h2h = dict(event_ticker="KXF1H2H-BRIGP26VERHAM", series_ticker="KXF1H2H", title="F1 Matchup: Verstappen vs Hamilton",
               markets=[dict(ticker="KXF1H2H-BRIGP26VERHAM-VER", event_ticker="KXF1H2H-BRIGP26VERHAM", status="finalized",
                             result="no", yes_sub_title="Max Verstappen beats Lewis Hamilton",
                             title="Will Max Verstappen beat Lewis Hamilton in the racing matchup?")])
    assert KS.gp_codes([win, h2h]) == {"BRIGP26": "British Grand Prix"}
    (r,) = KS.link_rows([win, h2h], R())
    assert (r["prediction"], r["athlete_id"], r["params"]["opponent_id"], r["race_id"]) == ("race_h2h", 1, 44, 9)
    assert r["resolved_yes"] is False and r["closed"]


@pytest.mark.quick
def test_live_shapes_and_historical_endpoints():
    log = []
    with K.Client(transport=_live_transport(log)) as kc:
        assert KS.f1_series(kc) == ["KXF1RACE", "KXF1POLEPOSITION"]        # by ticker; not college football
        book = KS.book_row("KXF1-26-LN", kc.orderbook("KXF1-26-LN"), None)
        assert (book["best_bid"], book["best_ask"]) == (0.01, 0.03) and book["asks"][0][1] == 11715.5   # NO bid 0.97 = YES ask 0.03
        (mk,) = kc.historical_markets("KXF1RACE-BELGP26")
        h = KS.history_rows(mk["ticker"], kc.candlesticks("KXF1RACE", mk["ticker"], 1784000000, 1784600000))
        assert [r["price"] for r in h] == [0.07]         # "close": "0.0700" is dollars, not cents
        (t,) = KS.trade_rows(mk["ticker"], mk["event_ticker"], kc.trades(mk["ticker"]))
    assert "/trade-api/v2/historical/markets/KXF1RACE-BELGP26-VER/candlesticks" in log
    assert (t["side"], t["price"], t["size"]) == ("BUY", 0.01, 93.51)
    assert [r["price"] for r in KS.history_rows("X", [LIVE_CANDLE])] == [0.11]
    (row,) = KS.link_rows([dict(event_ticker="KXF1RACE-BELGP26", series_ticker="KXF1RACE", title="Belgian Grand Prix Winner",
                                markets=[LIVE_MARKET])], FakeResolver())
    assert row["volume"] == 362818.18 and row["last_price"] == 0.01 and row["closed"] and row["resolved_yes"] is False


# --- Sprint markets (docs/todo.md U5), on the archived 2026 Dutch GP (round 12, a sprint weekend) links --------

ARCHIVE = "data/archive/markets/kalshi/links/market_links.parquet"
SPRINT_KIND = {"KXF1RACESPRINT": "race_sprint_win", "KXF1SPRINTPOLE": "race_sprint_pole"}


class DutchResolver(FakeResolver):
    """Every driver and team resolves (ids from the names); the Dutch GP is race 12 of 2026."""
    def driver(self, name):
        return abs(hash((name or "").lower())) % 1000 + 1 if name else None

    def team(self, name):
        return (name or "").lower().replace(" ", "_") or None

    def race(self, gp, end=None):
        return (12, "2026-12") if gp == "Dutch Grand Prix" else (None, None)


def _dutch_events():
    """Kalshi /events (with nested markets) rebuilt from the archived Dutch GP 2026 rows: real tickers, titles
    and rules; prices as archived. [] when the archive isn't on disk."""
    import pandas as pd
    from racinglines.paths import ROOT
    path = ROOT / ARCHIVE
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    df = df[df["event_slug"].str.endswith("-DUTGP26", na=False)]
    evs = []
    for ev, g in df.groupby("event_slug", sort=True):
        markets = [dict(ticker=r.token_id, event_ticker=ev, title=r.question, yes_sub_title=r.outcome, status="settled",
                        close_time=r.end_date.strftime("%Y-%m-%dT%H:%M:%SZ"), tick_size=1,
                        yes_bid=int(round(r.last_price * 100)) if pd.notna(r.last_price) else 0,
                        yes_ask=int(round(r.last_price * 100)) + 1 if pd.notna(r.last_price) else 100,
                        rules_primary=json.loads(r.params)["rules"] if isinstance(r.params, str) else r.params["rules"],
                        result="yes" if str(r.resolved_yes) == "True" else "no")
                   for r in g.itertuples()]
        evs.append(dict(event_ticker=ev, series_ticker=ev.split("-")[0], title=g["event_title"].iloc[0],
                        mutually_exclusive=True, markets=markets))
    return evs


@pytest.mark.quick
def test_sprint_markets_stay_unmodeled_without_the_flag(monkeypatch):
    """Without RACINGLINES_KALSHI_SPRINTS the classifier gives exactly today's kinds: the archived link rows."""
    monkeypatch.delenv(KS.SPRINT_FLAG, raising=False)
    assert not KS.sprints_enabled()
    c = KS.classify
    assert c("Dutch Grand Prix: Sprint Race Winner", "Will Oscar Piastri finish in first in the Sprint Race at the 2026 Dutch Grand Prix?") \
        == ("unmodeled", "Dutch Grand Prix")
    assert c("Dutch Grand Prix Sprint Qualifying: Pole Position")[0] == "unmodeled"
    evs = _dutch_events()
    if not evs:
        pytest.skip("no archived Kalshi links")
    import pandas as pd
    from racinglines.paths import ROOT
    archived = pd.read_parquet(ROOT / ARCHIVE).set_index("token_id")["prediction"]
    rows = KS.link_rows(evs, DutchResolver())
    assert len(rows) == 22 * 12 + 11 * 2                                    # 12 driver events, 2 constructor events
    assert {r["token_id"]: r["prediction"] for r in rows} == archived[[r["token_id"] for r in rows]].to_dict()
    for flag in ("0", "no", ""):
        monkeypatch.setenv(KS.SPRINT_FLAG, flag)
        assert not KS.sprints_enabled() and c("Dutch Grand Prix: Sprint Race Winner")[0] == "unmodeled"


@pytest.mark.quick
def test_sprint_markets_classify_with_the_flag(monkeypatch):
    monkeypatch.setenv(KS.SPRINT_FLAG, "1")
    assert KS.sprints_enabled()
    c = KS.classify
    # the live titles (2026-09-28 listing, archived): event title / market title
    assert c("Dutch Grand Prix: Sprint Race Winner",
             "Will Oscar Piastri finish in first in the Sprint Race at the 2026 Dutch Grand Prix?") == ("race_sprint_win", "Dutch Grand Prix")
    assert c("Dutch Grand Prix Sprint Qualifying: Pole Position", "Will Oscar Piastri set the fastest valid qualifying lap time "
             "in the Sprint Qualifying session (SQ3) for the 2026 Dutch Grand Prix?") == ("race_sprint_pole", "Dutch Grand Prix")
    assert c("Qatar Grand Prix Sprint Race Winner?") == ("race_sprint_win", "Qatar Grand Prix")        # 2025's title
    # the other sprint series stay unmodeled: no sprint fastest lap / top 5 / top 10 / top constructor model
    assert c("Dutch Grand Prix Sprint Race: Fastest Lap", "Will Oscar Piastri record the fastest lap in the Sprint Race at the 2026 Dutch Grand Prix?")[0] == "unmodeled"
    assert c("Dutch Grand Prix Sprint Race: Top 5 Finishers", "Will Oscar Piastri finish top 5 in the Sprint Race at the 2026 Dutch Grand Prix?")[0] == "unmodeled"
    assert c("Dutch Grand Prix Sprint Race: Top 10 Finishers")[0] == "unmodeled"
    assert c("Dutch Grand Prix Sprint Race: Top Constructor", "Will McLaren finish in first in the Sprint Race at the 2026 Dutch Grand Prix?")[0] == "unmodeled"
    # the main race is untouched by the flag
    assert c("Dutch Grand Prix Winner", "Will Oscar Piastri finish in first in the main race at the 2026 Dutch Grand Prix?")[0] == "race_win"
    assert c("Dutch Grand Prix Qualifying Session (Q3): Pole Position")[0] == "race_pole"
    assert c("Dutch Grand Prix: Sprint Race Winner", sprints=False)[0] == "unmodeled"       # the explicit argument wins
    evs = _dutch_events()
    if not evs:
        pytest.skip("no archived Kalshi links")

    class Piastri(DutchResolver):
        def driver(self, name):
            return 81 if (name or "").lower() == "oscar piastri" else None
    rows = {r["token_id"]: r for r in KS.link_rows(evs, Piastri())}
    for series, kind in SPRINT_KIND.items():
        r = rows[f"{series}-DUTGP26-PIA"]
        assert (r["prediction"], r["athlete_id"], r["race_id"], r["params"]["event_key"], r["params"]["series"]) == (kind, 81, 12, "2026-12", series)
        assert rows[f"{series}-DUTGP26-NOR"]["prediction"] == "unmodeled"                   # driver not resolved: no model price
        assert "Sprint" in rows[f"{series}-DUTGP26-PIA"]["params"]["rules"]
    assert rows["KXF1RACESPRINT-DUTGP26-PIA"]["end_date"] < rows["KXF1RACE-DUTGP26-PIA"]["end_date"]  # sprint Saturday, race Sunday
    assert rows["KXF1SPRINTPOLE-DUTGP26-PIA"]["end_date"] < rows["KXF1RACESPRINT-DUTGP26-PIA"]["end_date"]
    kinds = {t.split("-")[0]: r["prediction"] for t, r in rows.items() if t.endswith("-PIA")}
    assert kinds == {"KXF1RACE": "race_win", "KXF1RACEPODIUM": "race_podium", "KXF1TOP10": "race_top10", "KXF1POLE": "race_pole",
                     "KXF1FASTLAP": "race_fastest_lap", "KXF1RACESPRINT": "race_sprint_win", "KXF1SPRINTPOLE": "race_sprint_pole",
                     "KXF1TOP5": "unmodeled", "KXF1BIGGESTMOVER": "unmodeled", "KXF1SPRINTFASTLAP": "unmodeled",
                     "KXF1SPRINTTOP5": "unmodeled", "KXF1SPRINTTOP10": "unmodeled"}


def test_sprint_markets_sync_with_a_model_price(test_engine, monkeypatch):
    """The roadmap's "done when": a sprint weekend's Kalshi sprint markets sync with a model price (Singapore's
    can't be reached from here; the archived Dutch GP tickers stand in). Without the flag they sync unmodeled
    and unpriced, as today."""
    from racinglines.db import models as m
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    from racinglines.db.reads import model_prob
    from racinglines.markets.polymarket import sync as PS
    evs = [e for e in _dutch_events() if e["series_ticker"] in ("KXF1RACE", "KXF1RACESPRINT", "KXF1SPRINTPOLE", "KXF1SPRINTTOP5")]
    if not evs:
        pytest.skip("no archived Kalshi links")
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        comp = s.scalars(text("SELECT id FROM competitions WHERE code = 'f1_wdc'")).one()
        cat = s.scalars(text("SELECT id FROM categories WHERE competition_id = :c AND code = 'DRV'").bindparams(c=comp)).one()
        pia = m.Athlete(display_name="Oscar Piastri", nation="AUS")
        season = m.Season(competition_id=comp, year=2026)
        s.add_all([pia, season]); s.flush()
        ev = m.Event(season_id=season.id, source="fastf1", source_key="2026-12", name="Dutch Grand Prix",
                     start_date=datetime(2026, 8, 21).date(), series_round=12)
        s.add(ev); s.flush()
        race = m.Race(event_id=ev.id, category_id=cat, format=dict(kind="f1", sprint=True))
        run = m.ModelRun(competition_id=comp, season_id=season.id, category_id=cat, model="position_sim", kind="forecast")
        s.add_all([race, run]); s.flush()
        s.add(m.RacePrediction(model_run_id=run.id, race_id=race.id, target="2026-12", athlete_id=pia.id,
                               win_prob=0.31, podium_prob=0.6, top10_prob=0.95, extra=dict(pole_prob=0.27)))
        s.execute(text("DELETE FROM market_links WHERE exchange = 'kalshi'"))
        s.commit()
        ids = dict(pia=pia.id, race=race.id)

    class Dutch(FakeResolver):
        def driver(self, name):
            return ids["pia"] if (name or "").lower() == "oscar piastri" else None

        def race(self, gp, end=None):
            return (ids["race"], "2026-12") if gp == "Dutch Grand Prix" else (None, None)

    class Kc:                                                           # KS.sync's client: the archived events
        def series(self, category=None):
            return [dict(ticker=e["series_ticker"], title=e["title"], category="Sports") for e in evs]

        def events(self, series_ticker=None, status=None):
            return [e for e in evs if e["series_ticker"] == series_ticker] if status == "open" else []
    monkeypatch.setattr(PS, "Resolver", lambda conn, year: Dutch())

    def links(c):
        return {r["token_id"]: r for r in c.execute(text("""SELECT token_id, prediction, athlete_id, race_id, competition_id, category_id, params, invert
                                                  FROM market_links WHERE exchange = 'kalshi'""")).mappings().all()}
    monkeypatch.delenv(KS.SPRINT_FLAG, raising=False)
    with test_engine.connect() as c, get_session(url) as s:
        st = KS.sync(s, c, 2026, kc=Kc())
        assert st["links"] == 88 and st["modeled"] == 1                 # Piastri's race win only: the sprints are unmodeled
        before = links(c)
        assert before["KXF1RACESPRINT-DUTGP26-PIA"]["prediction"] == "unmodeled"
        assert model_prob(c, dict(before["KXF1RACESPRINT-DUTGP26-PIA"])) == (None, None)
        assert model_prob(c, dict(before["KXF1RACE-DUTGP26-PIA"]))[0] == pytest.approx(0.31)
    monkeypatch.setenv(KS.SPRINT_FLAG, "1")
    with test_engine.connect() as c, get_session(url) as s:
        st = KS.sync(s, c, 2026, kc=Kc())
        assert (st["links"], st["modeled"], st["new"]) == (88, 3, 0)    # the same rows, re-classified in place
        after = links(c)
        assert after["KXF1RACESPRINT-DUTGP26-PIA"]["prediction"] == "race_sprint_win"
        assert after["KXF1SPRINTPOLE-DUTGP26-PIA"]["prediction"] == "race_sprint_pole"
        assert after["KXF1SPRINTTOP5-DUTGP26-PIA"]["prediction"] == "unmodeled"
        assert model_prob(c, dict(after["KXF1RACESPRINT-DUTGP26-PIA"]))[0] == pytest.approx(0.31)    # the race win, until a sprint sim
        assert model_prob(c, dict(after["KXF1SPRINTPOLE-DUTGP26-PIA"]))[0] == pytest.approx(0.27)    # the pole probability
        assert model_prob(c, dict(after["KXF1SPRINTTOP5-DUTGP26-PIA"])) == (None, None)
        # a run that simulates the sprint prices them from its own sprint probabilities
        s.execute(text("""UPDATE race_predictions SET extra = extra || '{"sprint_win_prob": 0.4, "sprint_pole_prob": 0.35}'::jsonb"""))
        s.commit()
        assert model_prob(c, dict(after["KXF1RACESPRINT-DUTGP26-PIA"]))[0] == pytest.approx(0.4)
        assert model_prob(c, dict(after["KXF1SPRINTPOLE-DUTGP26-PIA"]))[0] == pytest.approx(0.35)
    monkeypatch.delenv(KS.SPRINT_FLAG, raising=False)
    with test_engine.connect() as c, get_session(url) as s:             # flag off again: back to today's rows
        KS.sync(s, c, 2026, kc=Kc())
        assert {k: v["prediction"] for k, v in links(c).items()} == {k: v["prediction"] for k, v in before.items()}


# Tape-only sports (docs/todo.md, U9): NASCAR Cup, MotoGP and IndyCar, synced only when named, every link
# unmodeled under the sport's own competition. Fixture in the client's shape: tests/fixtures/market/.
OTHER = json.loads((Path(__file__).parent / "fixtures" / "market" / "kalshi_other_series.json").read_text())


def _other_transport(log):
    def handler(req):
        p = req.url.path.removeprefix(K.PREFIX)
        q = dict(req.url.params)
        log.append((req.method, p, q))
        if p == "/series":
            return httpx.Response(200, json={"series": OTHER["series"]})
        if p == "/events":
            evs = OTHER["events"].get(q.get("series_ticker"), {}).get(q.get("status"), [])
            return httpx.Response(200, json=dict(events=evs, cursor=""))
        if p == "/markets/trades":
            trades = [t for t in OTHER["trades"] if t["ticker"] == q.get("ticker")]
            return httpx.Response(200, json=dict(trades=trades, cursor=""))
        if p in ("/historical/trades", "/historical/markets"):
            return httpx.Response(200, json={"trades": [], "markets": [], "cursor": ""})
        if p.endswith("/orderbook"):
            return httpx.Response(200, json=OTHER["orderbook"])
        if p.endswith("/candlesticks"):
            return httpx.Response(200, json={"candlesticks": OTHER["candlesticks"]})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


@pytest.mark.quick
def test_tape_only_sports_have_schemas_and_series():
    from racinglines import sports
    from racinglines.cli import markets as CM
    for code, comp, prefix in (("nascar", "nascar_cup", "KXNASCAR"), ("motogp", "motogp_wc", "KXMOTOGP"),
                               ("indycar", "indycar_series", "KXINDYCAR")):
        s = sports.load(code)
        assert not sports.modeled(code) and "pricing_model" not in s["sport"] and "live" not in s
        assert s["competition"]["code"] == comp and sports.kalshi_series(code) == (prefix,)
        assert s["markets"]["venues"] == ["polymarket", "kalshi"]
    for code, comp, series, venues in (
            ("road_cycling", "uci_road_wt", ("KXCYCLING", "KXCYCLINGSTAGE", "KXCYCLINGTEAM", "KXCYCLINGJERSEY"), ["kalshi"]),
            ("le_mans", "le_mans_24h", ("KXLEMANS24H",), ["kalshi"]),
            ("sailgp", "sailgp_champ", ("KXSAILGP", "KXSAILGPRACE"), ["kalshi", "og"])):
        s = sports.load(code)
        assert not sports.modeled(code) and "pricing_model" not in s["sport"] and "live" not in s
        assert s["competition"]["code"] == comp and sports.kalshi_series(code) == series
        assert s["markets"]["venues"] == venues
    assert sports.modeled("f1") and sports.modeled("mtb_dh") and sports.kalshi_series("f1") == ()
    assert CM.kalshi_sports() == ["f1", "nascar", "motogp", "indycar", "road_cycling", "le_mans", "sailgp"]
    with pytest.raises(ValueError):
        KS.series_for(None, "mtb_dh")                    # no [markets.kalshi]: nothing to discover


@pytest.mark.quick
def test_series_discovery_is_per_sport_and_f1_is_unchanged():
    log = []
    with K.Client(transport=_other_transport(log)) as kc:
        assert KS.series_for(kc) == ["KXF1RACE"]                         # the default: F1 only, as before
        assert KS.series_for(kc, "nascar") == ["KXNASCARRACE", "KXNASCAR"]
        assert KS.series_for(kc, "motogp") == ["KXMOTOGPRACE", "KXMOTOGP"]
        assert KS.series_for(kc, "indycar") == ["KXINDYCARRACE"]
        assert KS.series_for(kc, "nascar", series=["KXNASCARCHAMP"]) == ["KXNASCARCHAMP"]   # explicit tickers win
    assert all(q.get("category") == "Sports" for _, p, q in log if p == "/series")


@pytest.mark.quick
def test_tape_only_link_rows_are_unmodeled_and_never_resolve():
    class Boom:
        def __getattr__(self, name):
            raise AssertionError("a tape-only sport must not look up drivers or races")
    evs = OTHER["events"]["KXNASCARRACE"]["open"] + OTHER["events"]["KXNASCARRACE"]["settled"] + OTHER["events"]["KXNASCAR"]["open"]
    rows = {r["token_id"]: r for r in KS.link_rows(evs, Boom(), modeled=False)}
    assert len(rows) == 4 and all(r["prediction"] == "unmodeled" for r in rows.values())
    assert all(r["athlete_id"] is None and r["race_id"] is None and r["exchange"] == "kalshi" for r in rows.values())
    r = rows["KXNASCARRACE-26NOV08-KLAR"]
    assert (r["condition_id"], r["outcome"], r["last_bid"], r["last_ask"], r["volume"]) == ("KXNASCARRACE-26NOV08", "Kyle Larson", 0.20, 0.23, 15230.5)
    assert r["params"]["series"] == "KXNASCARRACE" and "Kyle Larson" in r["params"]["rules"] and "event_key" not in r["params"]
    assert r["end_date"] == datetime(2026, 11, 8, 23, tzinfo=timezone.utc) and not r["closed"] and r["active"]
    settled = rows["KXNASCARRACE-26NOV01-KLAR"]
    assert settled["closed"] and settled["resolved_yes"] is True and not settled["active"]
    assert (rows["KXNASCARRACE-26NOV08-WBYR"]["last_bid"], rows["KXNASCARRACE-26NOV08-WBYR"]["last_ask"]) == (None, None)
    # the F1 classifier would have called the champion market "champion": the tape-only path never asks it
    assert KS.classify("NASCAR Cup Series Champion", "Will Kyle Larson win the 2026 NASCAR Cup Series Championship?")[0] == "champion"


def test_tape_only_sync_records_under_its_own_competition(test_engine, monkeypatch):
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    from racinglines.markets import store as MS
    from racinglines.markets.polymarket import sync as PS
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE exchange = 'kalshi'"))
        c.execute(text("DELETE FROM market_trades WHERE token_id LIKE 'KX%'"))
        c.execute(text("DELETE FROM market_book_snapshots WHERE token_id LIKE 'KX%'"))
        c.execute(text("DELETE FROM market_price_history WHERE token_id LIKE 'KX%'"))
    monkeypatch.setattr(PS, "Resolver", lambda conn, year: (_ for _ in ()).throw(AssertionError("no resolver for a tape-only sport")))
    log = []
    kc = K.Client(transport=_other_transport(log))
    with test_engine.connect() as c, get_session(url) as s:
        st = KS.sync(s, c, 2026, include_closed=True, kc=kc, sport="nascar")
        assert (st["events"], st["links"], st["new"], st["modeled"], st["unmatched"]) == (3, 4, 4, 0, 4)
        assert KS.sync(s, c, 2026, include_closed=True, kc=kc, sport="nascar")["new"] == 0       # idempotent
        assert KS.sync(s, c, 2026, kc=kc, sport="motogp")["links"] == 2
        assert KS.sync(s, c, 2026, kc=kc, sport="indycar")["links"] == 0                         # nothing listed yet
        # the sport's whole tape without naming events: trades on every market, books on the open ones
        assert KS.fetch_trades(s, c, kc=kc, sport="nascar") == 2
        assert KS.fetch_trades(s, c, kc=kc, sport="nascar") == 2                                 # deduplicated
        assert KS.snapshot_books(s, c, kc=kc, sport="nascar") == 3                               # not the settled one
        t0, t1 = datetime(2026, 11, 5, tzinfo=timezone.utc), datetime(2026, 11, 6, tzinfo=timezone.utc)
        assert KS.fetch_history(s, c, ["KXMOTOGPRACE-26QAT"], t0, t1, 60, kc=kc) == 2
        with pytest.raises(ValueError):
            KS.fetch_trades(s, c, kc=kc)                                                          # no events, no sport
    with test_engine.connect() as c:
        by_comp = dict(c.execute(text("""SELECT co.code, count(*) FROM market_links l JOIN competitions co ON co.id = l.competition_id
                                         WHERE l.exchange = 'kalshi' GROUP BY co.code""")).all())
        assert by_comp == {"nascar_cup": 4, "motogp_wc": 2}
        assert c.execute(text("SELECT count(*) FROM market_links WHERE exchange = 'kalshi' AND prediction <> 'unmodeled'")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM market_trades WHERE token_id = 'KXNASCARRACE-26NOV08-KLAR'")).scalar() == 2
        assert c.execute(text("SELECT count(DISTINCT token_id) FROM market_book_snapshots WHERE token_id LIKE 'KXNASCAR%'")).scalar() == 3
        assert c.execute(text("SELECT count(*) FROM market_price_history WHERE token_id = 'KXMOTOGPRACE-26QAT-MMAR'")).scalar() == 2
        # the archive pass files these rows by market_links.exchange: Kalshi's tree, like F1's
        assert MS._exchanges(c, ["KXNASCARRACE-26NOV08-KLAR", "KXMOTOGP-26-MMAR"]) == \
            {"KXNASCARRACE-26NOV08-KLAR": "kalshi", "KXMOTOGP-26-MMAR": "kalshi"}
    assert str(MS.root_for("kalshi")).endswith("archive/markets/kalshi")
    # no NASCAR / MotoGP series was asked of Kalshi while F1 was the sport: the default run is unchanged
    f1_log = []
    with K.Client(transport=_other_transport(f1_log)) as kc, test_engine.connect() as c, get_session(url) as s:
        monkeypatch.setattr(PS, "Resolver", lambda conn, year: FakeResolver())
        KS.sync(s, c, 2026, kc=kc)
    assert {q.get("series_ticker") for _, p, q in f1_log if p == "/events"} == {"KXF1RACE"}


@pytest.mark.quick
def test_markets_cli_routes_tape_only_sports_to_kalshi(monkeypatch, capsys):
    from racinglines.cli import markets as CM
    calls = []
    monkeypatch.setattr(CM, "kalshi", lambda db, argv, sport="f1": calls.append((sport, argv)) or 0)
    assert CM.main(["--exchange", "kalshi", "--sport", "nascar", "sync", "--closed"]) == 0
    assert CM.main(["--exchange", "kalshi", "books"]) == 0
    assert calls == [("nascar", ["sync", "--closed"]), ("f1", ["books"])]
    monkeypatch.setattr(CM, "polymarket_sports", lambda: ["f1"])
    assert CM.main(["--sport", "motogp", "sync"]) == 2                    # (were Polymarket not to list it)
    assert "only Kalshi" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        CM.main(["--exchange", "kalshi", "--sport", "wec", "sync"])       # not a known sport
