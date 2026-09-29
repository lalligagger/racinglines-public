"""An exchange defined as a schema (exchanges/og.toml, racinglines/exchanges.py) and the generic driver that reads it
(markets/exchange_driver.py), against the real OG.com responses captured 2026-09-29 (tests/fixtures/market/og_*.json,
described in og_README.txt). No network, no credentials: httpx.MockTransport serves the fixtures by endpoint."""

import json
from datetime import timezone
from pathlib import Path

import httpx
import pandas as pd
import pytest
from sqlalchemy import text

from racinglines import exchanges as EX
from racinglines import sports
from racinglines.markets import exchange_driver as D

FIX = Path(__file__).parent / "fixtures" / "market"


def fx(name):
    return json.loads((FIX / f"og_{name}.json").read_text())


def envelope(data, **result):
    return {"id": -1, "method": "public/x", "code": 0, "result": {"data": data, **result}}


F1_EVENTS = fx("events_f1_futures")["result"]["data"]                  # F1-00001-2026 (drivers), F1-00002-2026 (constructors)
GP_EVENT = fx("events_f1")["result"]["data"][0]                        # a per-GP event: listed, no live instruments
NASCAR_EVENT = fx("events_nascar")["result"]["data"][0]
SAILGP_EVENT = fx("events_sailgp")["result"]["data"][0]                # SAIL-00011-26
INSTRUMENTS = fx("instruments_f1")["result"]["data"]
TICKERS = fx("tickers")["result"]["data"]


def transport(log=None, error=False):
    """The OG.com public API over the fixtures: events on two pages, instruments and tickers filtered by the ids asked."""
    events = [F1_EVENTS[0], F1_EVENTS[1], GP_EVENT, NASCAR_EVENT, fx("events_page1")["result"]["data"][0],
              SAILGP_EVENT]

    def handler(req):
        p, q = req.url.path, dict(req.url.params)
        if log is not None:
            log.append((req.method, p, q))
        assert req.method == "GET"                                    # read-only: nothing but GETs
        if error:
            return httpx.Response(200, json={"id": -1, "code": 40004, "message": "MISSING_OR_INVALID_ARGUMENT"})
        if p.endswith("/get-events"):
            page = int(q.get("cursor", "0"))
            chunk = events[page * 3:(page + 1) * 3]
            return httpx.Response(200, json=envelope(chunk, **({"next_cursor": str(page + 1)} if page == 0 else {})))
        if p.endswith("/get-instruments"):
            want = set(q["event_symbols"].split(","))
            if len(want) > 10:                                        # the live cap (2026-09-29): 11 symbols -> 400
                return httpx.Response(400, json={"code": 40004, "message": "Invalid event_symbol"})
            return httpx.Response(200, json=envelope([i for i in INSTRUMENTS if i["underlying_symbol"] in want]))
        if p.endswith("/get-tickers"):
            want = set(q["instrument_name"].split(","))
            return httpx.Response(200, json=envelope([t for t in TICKERS if t["i"] in want]))
        if p.endswith("/get-book"):
            return httpx.Response(200, json=fx("book"))
        if p.endswith("/get-trades"):
            return httpx.Response(200, json=fx("trades"))
        if p.endswith("/get-ticker-histories"):
            return httpx.Response(200, json=fx("ticker_histories"))
        return httpx.Response(404)
    return httpx.MockTransport(handler)


class FakeResolver:
    NAMES = {9001: "Lando Norris", 9002: "Max Verstappen", 9003: "Lewis Hamilton"}
    IDS = {n.lower(): i for i, n in NAMES.items()}
    TEAMS = {"ferrari": "ferrari", "mercedes": "mercedes"}

    def driver(self, name):
        return self.IDS.get(name.lower())

    def team(self, name):
        return self.TEAMS.get(name.lower())


# ----- the schema -----

@pytest.mark.quick
def test_every_exchange_schema_is_complete_and_names_real_sports():
    assert "og" in EX.CODES
    for code in EX.CODES:
        s = EX.load(code)
        assert {"exchange", "api", "endpoints", "fields", "prices", "sports"} <= set(s)
        assert s["exchange"]["code"] == code and s["exchange"]["switch"]
        for name in ("events", "instruments", "tickers", "book", "trades", "history"):
            assert s["endpoints"][name]["path"].startswith("/")
        for sport in EX.sports(code):
            assert sport in sports.SPORT_CODES                          # a sport schema (sports/<code>.toml) exists
        for sport, cfg in s["sports"].items():
            assert cfg["event_prefixes"] and (not cfg.get("modeled") or cfg["rules"])
    assert "sailgp" in EX.sports("og")
    assert D.classify(EX.load("og"), "sailgp", "SailGP Championship Winner") == ("unmodeled", None)


@pytest.mark.quick
def test_dig_when_epoch_and_quotes():
    assert EX.dig({"a": {"b": [{"c": 5}]}}, "a.b.0.c") == 5
    assert EX.dig({"a": {}}, "a.b.c") is None and EX.dig({"a": [1]}, "a.3") is None and EX.dig({"a": None}, "a.b") is None
    t = D.when(1801436400000, "ms")
    assert t.tzinfo is not None and t.isoformat() == "2027-01-31T23:00:00+00:00" and D.epoch(t, "ms") == 1801436400000
    assert D.when(1790420400000000000, "ns").year == 2026 and D.when(None, "ms") is None
    assert D.quote(0.83, 0.92, 0.84) == (0.83, 0.92, pytest.approx(0.875))
    assert D.quote(None, 0.01, 0.01) == (None, 0.01, 0.01)               # asks only: the last price, not a fake mid
    assert D.quote(0.0, 1.0, None) == (None, None, None)                 # an empty book
    assert D.price("0.03") == 0.03 and D.price(None) is None and D.price("") is None


@pytest.mark.quick
def test_classify_uses_the_sports_rules_and_tape_only_sports_stay_unmodeled():
    s = EX.load("og")
    assert D.classify(s, "f1", "F1 Drivers' Champion 2026") == ("champion", "driver")
    assert D.classify(s, "f1", "F1 Constructors' Champion 2026") == ("constructors_champion", "team")
    assert D.classify(s, "f1", "Azerbaijan Grand Prix winner") == ("unmodeled", None)
    assert D.classify(s, "nascar", "NASCAR Cup Series Champion") == ("unmodeled", None)
    with pytest.raises(ValueError):
        D.classify(s, "motogp", "x")                                     # not listed by this exchange


@pytest.mark.quick
def test_link_rows_map_fields_and_quotes_from_the_schema():
    s = EX.load("og")
    tick = {t["i"]: t for t in TICKERS}
    rows = {r["token_id"]: r for r in D.link_rows(s, "f1", INSTRUMENTS, tick, FakeResolver())}
    nor = rows["NX.F.OPT.F1-00001-2026.O.1.13"]
    assert (nor["exchange"], nor["prediction"], nor["athlete_id"], nor["outcome"]) == ("og", "champion", 9001, "Lando Norris")
    assert nor["condition_id"] == nor["event_slug"] == "F1-00001-2026" and nor["question"] == "F1 Drivers' Champion 2026"
    assert nor["end_date"].isoformat() == "2027-01-31T23:00:00+00:00" and nor["tick_size"] == 0.01 and not nor["closed"]
    ferrari = rows["NX.F.OPT.F1-00002-2026.O.1.5"]
    assert ferrari["prediction"] == "constructors_champion" and ferrari["params"]["team"] == "ferrari"
    # a driver we can't match stays listed, unmodeled
    leclerc = rows["NX.F.OPT.F1-00001-2026.O.1.4"]
    assert leclerc["prediction"] == "unmodeled" and leclerc["athlete_id"] is None
    # quotes: Hamilton-ish rows with both sides show a mid; asks-only rows show the last price and no bid
    two_sided = [r for r in rows.values() if r["last_bid"] is not None and r["last_ask"] is not None]
    assert two_sided and all(r["last_price"] == pytest.approx((r["last_bid"] + r["last_ask"]) / 2) for r in two_sided)
    asks_only = [r for r in rows.values() if r["last_bid"] is None]
    assert asks_only and all(r["last_price"] is None or 0 <= r["last_price"] <= 1 for r in asks_only)


# ----- the client -----

@pytest.mark.quick
def test_client_pages_and_batches_and_only_reads():
    log = []
    with D.Client("og", transport=transport(log)) as c:
        events, instruments = D.discover(c, "f1")
        ids = [e["symbol"] for e in events]
        assert ids == ["F1-00001-2026", "F1-00002-2026", "F1-00034-2026"]      # both pages, F1 events only, the GP event too
        assert {i["underlying_symbol"] for i in instruments} == {"F1-00001-2026", "F1-00002-2026"}   # the GP has none live
        assert len(instruments) == 12
        nascar_events, _ = D.discover(c, "nascar")
        assert [e["symbol"] for e in nascar_events] == ["NSCAR-00002-2026"]
        sailgp_events, _ = D.discover(c, "sailgp")
        assert [e["symbol"] for e in sailgp_events] == ["SAIL-00011-26"]
    cursors = [q.get("cursor") for m, p, q in log if p.endswith("/get-events")]
    assert None in cursors and "1" in cursors and all(m == "GET" for m, _, _ in log)


def test_instrument_batches_stay_under_the_exchange_cap():
    """The 2026 F1 listing has 23 events; get-instruments refuses more than 10 event symbols per call (a 400 the first
    live sync hit with batch_size 25), so discovery must ask in batches of at most 10."""
    log = []
    with D.Client("og", transport=transport(log)) as c:
        c.batched("instruments", [f"F1-{n:05d}-2026" for n in range(1, 24)])
    sizes = [len(q["event_symbols"].split(",")) for m, p, q in log if p.endswith("/get-instruments")]
    assert sizes == [10, 10, 3]


@pytest.mark.quick
def test_client_raises_the_exchanges_own_error():
    with D.Client("og", transport=transport(error=True)) as c, pytest.raises(RuntimeError, match="MISSING_OR_INVALID_ARGUMENT"):
        c.rows("events")


@pytest.mark.quick
def test_windows_are_clipped_to_what_the_exchange_keeps_and_naive_times_are_utc():
    log = []
    with D.Client("og", transport=transport(log)) as c:
        c.window("trades", "NX.F.OPT.F1-00001-2026.O.1.13", "2001-01-01")
        c.window("history", "NX.F.OPT.F1-00001-2026.O.1.13", "2001-01-01", "2026-09-29T00:00")
        c.window("history", "NX.F.OPT.F1-00001-2026.O.1.13", "2001-01-01")            # end defaults to now
    (_, _, trades), (_, _, hist), (_, _, open_end) = [x for x in log if "trades" in x[1] or "histories" in x[1]]
    now_ns = pd.Timestamp.now("UTC").timestamp() * 1e9
    assert now_ns - int(trades["start_ts"]) < 31 * 86400e9 and int(trades["start_ts"]) > now_ns - 31 * 86400e9
    assert int(hist["end_ts"]) == int(pd.Timestamp("2026-09-29", tz="UTC").timestamp() * 1000)
    assert int(hist["end_ts"]) - int(hist["start_ts"]) <= 31 * 86400 * 1000            # the 31-day cap
    assert 0 < 31 * 86400 * 1000 - (int(open_end["end_ts"]) - int(open_end["start_ts"])) <= 1000    # never over it by a tick
    assert trades["count"] == "150"                                                        # OG.com's maximum


@pytest.mark.quick
def test_tape_history_and_book_rows_from_the_fixtures():
    s = EX.load("og")
    trades = D.trade_rows(s, "T", "E", fx("trades")["result"]["data"])
    assert len(trades) == 20 and {r["side"] for r in trades} <= {"BUY", "SELL"} and all(0 <= r["price"] <= 1 for r in trades)
    assert trades[0]["size"] == 462 and trades[0]["price"] == 0.01 and trades[0]["wallet"] == "" and trades[0]["ts"].tzinfo
    pts = D.history_rows(s, "T", fx("ticker_histories")["result"]["data"])
    assert pts and all(0 <= r["price"] <= 1 for r in pts) and pts[0]["ts"] > pts[1]["ts"]
    b = D.book_row(s, "T", fx("book")["result"])
    assert b["best_bid"] is None and b["best_ask"] == 0.01 and b["asks"][0] == [0.01, 3890.0] and len(b["asks"]) == 4


# ----- the database -----

def _seed(test_engine):
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()
    with test_engine.begin() as c:                  # the drivers FakeResolver hands out (links reference athletes)
        for i, name in FakeResolver.NAMES.items():
            c.execute(text("INSERT INTO athletes (id, display_name) VALUES (:i, :n) ON CONFLICT (id) DO NOTHING"), dict(i=i, n=name))
    return url


def test_sync_tape_history_and_books_write_the_shared_tables(test_engine):
    from racinglines.db.config import get_session
    url = _seed(test_engine)
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE exchange = 'og'"))
        c.execute(text("DELETE FROM market_trades WHERE token_id LIKE 'NX.F.OPT.%'"))
    with D.Client("og", transport=transport()) as kc, test_engine.connect() as c, get_session(url) as s:
        st = D.sync(s, c, "og", "f1", client=kc, resolver=FakeResolver())
        assert st["links"] == 12 and st["new"] == 12 and st["modeled"] == 5 and st["events"] == 3
        st2 = D.sync(s, c, "og", "f1", client=kc, resolver=FakeResolver())
        assert st2["new"] == 0 and st2["links"] == 12                     # idempotent
        assert D.sync(s, c, "og", "nascar", client=kc)["links"] == 0      # its instruments aren't in the fixtures: nothing
        n = D.fetch_trades(s, c, "og", sport="f1", client=kc)
        assert n == 12 * 20
        D.fetch_trades(s, c, "og", sport="f1", client=kc)
        assert D.fetch_history(s, c, "og", "2026-09-28", client=kc, sport="f1") > 0
        assert D.snapshot_books(s, c, "og", sport="f1", client=kc) == 12
    with test_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM market_links WHERE exchange = 'og'")).scalar() == 12
        assert c.execute(text("SELECT count(DISTINCT token_id) FROM market_trades WHERE token_id LIKE 'NX.F.OPT.%'")).scalar() == 12
        row = c.execute(text("""SELECT co.code, l.prediction, l.athlete_id FROM market_links l JOIN competitions co ON co.id = l.competition_id
                                WHERE l.token_id = 'NX.F.OPT.F1-00001-2026.O.1.13'""")).one()
    assert tuple(row) == ("f1_wdc", "champion", 9001)


def test_instruments_that_leave_the_listing_are_closed(test_engine):
    from racinglines.db.config import get_session
    url = _seed(test_engine)
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE exchange = 'og'"))
    with D.Client("og", transport=transport()) as kc, test_engine.connect() as c, get_session(url) as s:
        D.sync(s, c, "og", "f1", client=kc, resolver=FakeResolver())
        gone = INSTRUMENTS[0]["symbol"]
        INSTRUMENTS.remove(INSTRUMENTS[0])
        try:
            st = D.sync(s, c, "og", "f1", client=kc, resolver=FakeResolver())
        finally:
            INSTRUMENTS.insert(0, json.loads(json.dumps(fx("instruments_f1")["result"]["data"][0])))
        assert st["closed"] == 1
    with test_engine.connect() as c:
        assert c.execute(text("SELECT closed FROM market_links WHERE token_id = :t"), dict(t=gone)).scalar() is True


# ----- the fair-price indicator -----

def test_fair_report_shows_the_model_price_beside_the_quote_net_of_the_fee(test_engine, monkeypatch):
    from racinglines.db import reads as data
    from racinglines.db.config import get_session
    url = _seed(test_engine)
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE exchange = 'og'"))
    fair = {9001: 0.60, 9002: 0.10, 9003: 0.50}          # Norris, Verstappen, Hamilton (FakeResolver ids)
    monkeypatch.setattr(data, "model_prob", lambda conn, link, cache=None, run_id=None: (fair.get(link["athlete_id"]), 7))
    with D.Client("og", transport=transport()) as kc, test_engine.connect() as c, get_session(url) as s:
        D.sync(s, c, "og", "f1", client=kc, resolver=FakeResolver())
    with test_engine.connect() as c:
        df = D.fair_report(c, "og", "f1")
        txt = D.fair_text(df, "og", 0.02)
    assert len(df) and (df["kind"] == "champion").all() and set(df["token"]) >= {"NX.F.OPT.F1-00001-2026.O.1.13"}
    r = df.set_index("token")
    for tok, row in r.iterrows():
        if row["ask"] is not None and not pd.isna(row["ask"]):
            assert row["edge_yes"] == pytest.approx(row["fair"] - row["ask"] - 0.02)
        if row["bid"] is not None and not pd.isna(row["bid"]):
            assert row["edge_no"] == pytest.approx(row["bid"] - row["fair"] - 0.02)
        assert row["call"] in ("", "YES", "NO")
        assert (row["call"] == "") == (max([e for e in (row["edge_yes"], row["edge_no"]) if e is not None and not pd.isna(e)] or [0]) <= 0)
    assert "fair" in txt and "taker fee" in txt
    assert D.fair_text(pd.DataFrame(), "og", 0.02).startswith("og: no open market")


# ----- the switch and the CLI -----

@pytest.mark.quick
def test_the_venue_appears_only_with_its_switch(monkeypatch):
    from racinglines.markets import venues as V
    monkeypatch.delenv("RACINGLINES_OG_VENUE", raising=False)
    assert V.schema_venues() == [] and [v.code for v in V.VENUES] == ["polymarket", "kalshi", "private"]
    monkeypatch.setenv("RACINGLINES_OG_VENUE", "1")
    (v,) = V.schema_venues()
    assert (v.code, v.name, v.kind, v.status) == ("og", "OG.com", "exchange", "live")


@pytest.mark.quick
def test_cli_refuses_a_sport_the_exchange_does_not_list(capsys):
    from racinglines.cli import markets
    assert markets.main(["--exchange", "og", "--sport", "motogp", "sync"]) == 2
    assert "lists f1, nascar" in capsys.readouterr().err
