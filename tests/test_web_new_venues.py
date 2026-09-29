"""The web app on tonight's new market data, without a database: the schema venues' list page (/markets/og, behind
RACINGLINES_OG_VENUE) with the fair-price indicator net of the fee, the same indicator beside a schema venue's quote
on the race and season pages, and the tape-only sports' page (/markets/tapes, behind RACINGLINES_TAPES). With both
switches off every route is a 404 and the board, race and season pages render as before."""

import pandas as pd
import pytest
from starlette.requests import Request

from racinglines import exchanges
from racinglines.markets import venues as V

pytestmark = pytest.mark.quick


# --- the fair-price indicator (one arithmetic, shared by the CLI report and the app) ---------------------------

def test_net_edge_is_per_side_and_net_of_the_fee():
    e = V.net_edge(0.02, 0.30, 0.20, 0.25)
    assert e["edge_yes"] == pytest.approx(0.30 - 0.25 - 0.02) and e["edge_no"] == pytest.approx(0.20 - 0.30 - 0.02)
    assert e["call"] == "YES" and e["best"] == pytest.approx(0.03)
    assert V.net_edge(0.02, 0.10, 0.20, 0.25)["call"] == "NO"                         # bid above fair: sell it
    assert V.net_edge(0.02, 0.26, 0.20, 0.25)["call"] == ""                           # inside the fee: no call
    one_sided = V.net_edge(0.02, 0.50, None, 0.01)                                      # a thin book: no bid, a 1c ask
    assert one_sided["edge_no"] is None and one_sided["call"] == "YES"                  # the quoted side only
    assert V.net_edge(0.02, 0.50, None, None) == dict(edge_yes=None, edge_no=None, best=None, call="")
    assert V.net_edge(0.02, None, 0.2, 0.3)["call"] == ""                               # nothing priced: nothing said


def test_the_cli_report_uses_the_same_arithmetic():
    from racinglines.markets import exchange_driver as D
    import inspect
    assert "venues.net_edge(" in inspect.getsource(D.fair_report)


def _links(*rows):
    base = dict(id=1, exchange="og", token_id="t", condition_id="e", prediction="champion", athlete_id=7, params={},
                last_bid=0.20, last_ask=0.25, last_price=0.225, volume=10.0, event_slug="F1-2026", closed=False,
                question="Champion", outcome="Max")
    return pd.DataFrame([dict(base, **r) for r in rows])


def test_schema_venue_quotes_carry_the_indicator_and_others_do_not(monkeypatch):
    from racinglines.db import reads as data
    monkeypatch.setattr(data, "model_prob", lambda conn, link, cache, run_id=None: (0.30, 1))
    rows = V._exchange_rows(None, _links(dict(exchange="og", token_id="a"), dict(exchange="polymarket", token_id="b", id=2),
                                         dict(exchange="kalshi", token_id="c", id=3)), {}, None)
    (k,) = rows
    og, pm, ks = rows[k]["og"], rows[k]["polymarket"], rows[k]["kalshi"]
    assert og["call"] == "YES" and og["best"] == pytest.approx(0.30 - 0.25 - V.schema_fee("og"))
    assert "call" not in pm and "call" not in ks                       # Polymarket and Kalshi rows are unchanged


def test_no_indicator_without_a_fair_price(monkeypatch):
    from racinglines.db import reads as data
    monkeypatch.setattr(data, "model_prob", lambda conn, link, cache, run_id=None: (None, None))
    (q,) = V._exchange_rows(None, _links({}), {}, None).values()
    assert "call" not in q["og"] and q["og"]["fair"] is None


# --- the routes and their switches --------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from racinglines.web import app as A

    def as_maker(request: Request):
        request.state.user = dict(id=1, username="tester", role="maker", sid=None)      # not a demo user: no view log
        return request.state.user
    monkeypatch.setitem(A.app.dependency_overrides, A.authenticate, as_maker)
    monkeypatch.setitem(A.app.dependency_overrides, A.conn, lambda: None)                 # no database
    monkeypatch.setattr(A, "_signals_nav", lambda user: None)
    return TestClient(A.app)


def test_every_schema_exchange_has_a_list_route():
    from racinglines.web.app import app
    paths = {r.path for r in app.routes}
    for code in exchanges.CODES:
        assert {f"/markets/{code}", f"/markets/{code}/mirror", f"/markets/{code}/sync"} <= paths
    # no untyped wildcard under /markets: the legacy /markets/{id:int} redirect keeps matching numbers only
    assert "/markets/tapes" in paths and {p for p in paths if p.startswith("/markets/{")} == {"/markets/{link_id:int}"}


def test_switched_off_pages_are_404s(client, monkeypatch):
    monkeypatch.delenv("RACINGLINES_OG_VENUE", raising=False)
    monkeypatch.setattr(V, "TAPES", False)
    assert client.get("/markets/og").status_code == 404
    assert client.get("/markets/tapes").status_code == 404


BLOCKS = [dict(sport="nascar", sport_name="NASCAR", exchange="kalshi", exchange_name="Kalshi", markets=3, open=2, trades=120,
               prices=4000, books=12, synced=pd.Timestamp("2026-09-29 07:00"),
               events=[dict(slug="KXNASCAR-26", title="NASCAR Cup Champion", end_date=pd.Timestamp("2026-11-08"), markets=3,
                            open=2, synced=pd.Timestamp("2026-09-29 07:00"), volume=1234.0, last_price=0.41, favourite="Larson",
                            trades=120, trades_last=pd.Timestamp("2026-09-28 22:10"), prices=4000, prices_last=pd.Timestamp("2026-09-28 22:00"),
                            books=12, books_last=None)]),
          dict(sport="motogp", sport_name="MotoGP", exchange="kalshi", exchange_name="Kalshi", markets=1, open=1, trades=0,
               prices=0, books=0, synced=None,
               events=[dict(slug="KXMOTOGP-26", title="MotoGP Champion", end_date=None, markets=1, open=1, synced=None, volume=0.0,
                            last_price=None, favourite=None, trades=0, trades_last=None, prices=0, prices_last=None, books=0,
                            books_last=None)])]


def test_tapes_page_lists_market_data_only(client, monkeypatch):
    monkeypatch.setattr(V, "TAPES", True)
    monkeypatch.setattr(V, "tape_summary", lambda conn: BLOCKS)
    r = client.get("/markets/tapes")
    assert r.status_code == 200
    html = r.text
    assert "NASCAR · Kalshi" in html and "MotoGP · Kalshi" in html and "NASCAR Cup Champion" in html
    assert "Larson" in html and "2026-09-28 22:10" in html and "1,234" in html and "4,000" in html
    assert "P&amp;L" in html or "P&L" in html                     # the page says what it is not
    assert "nan" not in html.lower().replace("financ", "")


def test_tapes_page_with_nothing_linked(client, monkeypatch):
    monkeypatch.setattr(V, "TAPES", True)
    monkeypatch.setattr(V, "tape_summary", lambda conn: [])
    r = client.get("/markets/tapes")
    assert r.status_code == 200 and "No tape-only markets linked yet" in r.text


# --- the templates: the schema venue's list and the indicator on a race page --------------------------------------

def _render(name, **ctx):
    from racinglines.web.app import templates
    req = Request({"type": "http", "method": "GET", "path": "/x", "headers": [], "query_string": b"", "url": "http://t/x"})
    ctx.setdefault("request", req)
    for k in ("user", "signals_nav", "live_nav", "storage_ns", "trading", "kalshi"):
        ctx.setdefault(k, None)
    ctx.setdefault("schema_exchanges", [])
    ctx.setdefault("tapes", False)
    return templates.env.get_template(name).render(**ctx)


def test_exchange_list_shows_edges_per_side_and_the_call():
    venue = V.Venue("og", "OG.com", "live", "exchange", "https://og.com/")
    ev = dict(slug="F1-2026", title="F1 2026 Drivers' Champion", end_date=pd.Timestamp("2026-12-07"), volume=42.0, modeled=1, new=0,
              rows=[dict(subject="Max Verstappen", new=False, prediction="champion", last_bid=0.20, last_ask=0.25, last_price=0.225,
                         fair=0.30, edge=0.075, edge_yes=0.03, edge_no=-0.12, call="YES", q_bid=0.28, q_ask=0.32, mirrored=False),
                    dict(subject="Cup Champion", new=False, prediction="unmodeled", last_bid=None, last_ask=0.01, last_price=None,
                         fair=None, edge=None, edge_yes=None, edge_no=None, call="", q_bid=None, q_ask=None, mirrored=False)])
    html = _render("exchange.html", events=[ev], show="all", closed=0, spread_pct=4.0, msg="", synced=None, event="", venue=venue,
                   fee=0.02, sports=["F1", "NASCAR"])
    assert "OG.com markets" in html and "$0.02 per contract" in html and 'action="/markets/og/sync"' in html
    assert "+3.0 pts" in html and "-12.0 pts" in html and ">YES<" in html
    assert "nan" not in html.lower().replace("financ", "")


def test_race_page_marks_the_call_beside_a_schema_venue_quote():
    og = V.Venue("og", "OG.com", "live", "exchange", "https://og.com/")
    exch = [V.Venue("polymarket", "Polymarket", "live", "exchange"), og]
    row = dict(kind="champion", kind_label="Champion", athlete_id=1, team=None, opponent_id=None, subject="Max", detail="", fair=0.30,
               venues={"polymarket": dict(bid=0.2, ask=0.3, mid=0.25),
                       "og": dict(bid=0.20, ask=0.25, mid=0.225, call="YES", best=0.03, edge_yes=0.03, edge_no=-0.12)},
               private=None, result=None, pm_mid=0.25, gap=-0.05)
    info = dict(race_id=0, competition="f1_wdc", title="F1", sport="F1", name="F1", status="scheduled", start_date=None,
                event_id=None, season=2026, category="DRV")
    ctx = dict(info=info, pricing=dict(run_id=1, source="live forecast", as_of=None), groups=[("champion", "Champion", [row])],
               exchanges=exch, has_pm=True, results=None, completed=False, season=True, strategy=None,
               venue_sum=[dict(venue=og, listed=1, volume=42.0, slug="F1-2026")], mine=dict(open=0, worst=0, staked=0),
               charts=[], winner=None, schema_exchanges=[og], user=dict(role="maker", id=1))
    html = _render("race.html", **ctx)
    assert "YES +3.0" in html and "net of the taker fee" in html and 'href="/markets/og"' in html       # season page
    html = _render("race.html", **dict(ctx, season=False))
    assert "YES +3.0" in html and "/markets/og/mirror" in html                                       # race page
    # without the schema venue on, the same row renders with no indicator at all
    row["venues"]["og"] = dict(bid=0.20, ask=0.25, mid=0.225)
    html = _render("race.html", **dict(ctx, exchanges=exch[:1], schema_exchanges=[], venue_sum=[]))
    assert "YES +" not in html and "taker fee" not in html


# --- the Markets calendar mixes a race's plain date with an exchange event's timezone-aware timestamp -------
# (2026-09-29: /markets as maker returned 500 on the VM once NASCAR links were synced, because the sort
# compared the two and pandas refuses to.)

def test_calendar_sort_key_orders_dates_timestamps_and_missing_together():
    import datetime as dt
    rows = [dict(date=dt.date(2026, 9, 20)), dict(date=pd.Timestamp("2026-10-04T23:00:00Z")), dict(date=None),
            dict(date=pd.NaT), dict(date=pd.Timestamp("2026-09-20T01:00:00Z")), dict(date=dt.datetime(2026, 11, 1))]
    rows.sort(key=V._calendar_key, reverse=True)
    dated = [r["date"] for r in rows if r["date"] is not None and not pd.isna(r["date"])]
    assert [V._calendar_key(dict(date=d))[1] for d in dated] == sorted(
        (V._calendar_key(dict(date=d))[1] for d in dated), reverse=True)
    assert all(r["date"] is None or pd.isna(r["date"]) for r in rows[:2])              # undated rows lead, as they did before


def test_calendar_rows_with_a_race_and_a_tape_only_event(monkeypatch):
    import datetime as dt

    class Conn:                                                   # data.q is patched below; no database needed
        pass

    def fake_q(conn, sql, **kw):
        if "FROM races" in sql:
            return pd.DataFrame([dict(race_id=1, start_date=dt.date(2026, 9, 20), status="done", event_name="Bristol",
                                      competition="f1_wdc")])
        return pd.DataFrame(columns=["race_id", "exchange"])
    monkeypatch.setattr(V.data, "q", fake_q)
    monkeypatch.setattr(V, "exchange_breakdown", lambda conn, comps=None: [dict(
        sport="nascar", sport_name="NASCAR", competition="nascar_cup", exchange="kalshi",
        events=[dict(end_date=pd.Timestamp("2026-10-04T23:00:00Z"), title="South Point 400 Winner", open=3)])])
    rows = V.calendar_rows(Conn())
    assert [r["title"] for r in rows] == ["South Point 400 Winner", "Bristol"]
