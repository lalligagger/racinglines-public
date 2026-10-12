"""First-cut manual trading on the test database (fantasy/exchange.place, fantasy/ledger.py, web/fantasy_routes.py):
the full order flow and its ledger rows, every refusal, the balance under the row lock, retries, the pages and the
leaderboard. The books are injected or written as market_book_snapshots rows; nothing calls a venue."""

import re
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
RACE = NOW + timedelta(days=5)                       # the deciding round's stored start
ASKS = [[0.41, 120], [0.42, 300], [0.44, 500]]       # docs/fantasy-trading.md worked example
BIDS = [[0.39, 150], [0.38, 400]]


def book(ts=None, bids=BIDS, asks=ASKS):
    from racinglines.fantasy import exchange as FX
    return lambda tok: dict(ts=ts or NOW - timedelta(minutes=2), bids=FX.levels(bids), asks=FX.levels(asks))


@pytest.fixture
def db(test_engine, monkeypatch):
    """F1 with one race five days out, Kalshi and Polymarket links, three players with the 1,000 grant."""
    from racinglines.db import config
    from racinglines.fantasy import exchange as FX
    from racinglines.web import accounts as ACC
    from racinglines.web import users as U
    with test_engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS accounts CASCADE"))
        for t in ("activity_log", "paper_positions", "market_book_snapshots", "market_links", "rounds", "races",
                  "events", "seasons", "categories"):
            c.execute(text(f"DELETE FROM {t}"))
        c.execute(text("DELETE FROM users"))
        c.execute(text("INSERT INTO sports (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
        c.execute(text("INSERT INTO leagues (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
        c.execute(text("""INSERT INTO competitions (code, name, league_id, sport_id)
                          SELECT 'f1_wdc', 'F1', l.id, s.id FROM leagues l, sports s WHERE l.code = 'f1' AND s.code = 'f1'
                          ON CONFLICT DO NOTHING"""))
        comp = c.execute(text("SELECT id FROM competitions WHERE code = 'f1_wdc'")).scalar()
        cat = c.execute(text("INSERT INTO categories (competition_id, code, name) VALUES (:c, 'DRV', 'Drivers') RETURNING id"),
                        dict(c=comp)).scalar()
        season = c.execute(text("INSERT INTO seasons (competition_id, year) VALUES (:c, 2026) RETURNING id"),
                           dict(c=comp)).scalar()
        ev = c.execute(text("""INSERT INTO events (season_id, source, source_key, name, start_date, status)
                               VALUES (:s, 'fastf1', '2026-18', 'United States GP', :d, 'scheduled') RETURNING id"""),
                       dict(s=season, d=RACE.date())).scalar()
        race = c.execute(text("INSERT INTO races (event_id, category_id) VALUES (:e, :c) RETURNING id"),
                         dict(e=ev, c=cat)).scalar()
        c.execute(text("""INSERT INTO rounds (race_id, kind, ordinal, extra)
                          VALUES (:r, 'race', 5, CAST(:x AS jsonb)), (:r, 'qual', 4, CAST(:q AS jsonb))"""),
                  dict(r=race, x='{"session_date": "%s"}' % RACE.isoformat(),
                       q='{"session_date": "%s"}' % (NOW - timedelta(hours=1)).isoformat()))
        ids = {}
        for key, x, kind, tok, rid in (("win", "kalshi", "race_win", "KX-WIN-VER", race),
                                        ("pole", "kalshi", "race_pole", "KX-POLE-VER", race),
                                        ("champ", "polymarket", "champion", "PM-CHAMP-VER", None),
                                        ("motogp", "kalshi", "race_top10", "KX-NORACE", None)):
            ids[key] = c.execute(text("""
                INSERT INTO market_links (exchange, question, token_id, outcome, competition_id, race_id, prediction,
                                          event_title, group_title, last_bid, last_ask)
                VALUES (:x, :q, :t, 'Yes', :c, :r, :k, 'United States GP', 'Verstappen', 0.39, 0.41) RETURNING id"""),
                dict(x=x, q=f"{kind} Verstappen", t=tok, c=comp, r=rid, k=kind)).scalar()
    monkeypatch.setenv("DATABASE_URL", test_engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("RACINGLINES_FANTASY", "1")
    monkeypatch.delenv("RACINGLINES_FANTASY_BOOKS_URL", raising=False)
    config.get_engine.cache_clear()
    FX._HITS.clear()
    with config.get_session() as s:
        for name in ("ada", "bea", "cal"):
            U.create_user(s, name, f"{name}-password-1", "pro")
    ACC.setup(config.get_engine())
    users = {}
    with test_engine.connect() as c:
        for i, name in c.execute(text("SELECT id, username FROM users WHERE username IN ('ada', 'bea', 'cal')")):
            users[name] = dict(id=i, username=name, role="pro")
    yield dict(engine=config.get_engine(), links=ids, users=users)
    config.get_engine.cache_clear()


def _rows(eng, sql, **kw):
    with eng.connect() as c:
        return c.execute(text(sql), kw).all()


def test_full_order_flow_fill_and_ledger(db):
    from racinglines.fantasy import exchange as FX
    from racinglines.fantasy import ledger as FL
    eng, ada = db["engine"], db["users"]["ada"]
    r = FX.place(eng, ada, db["links"]["win"], "yes", "buy", 200, 0.42, now=NOW, get_book=book())
    assert r["ok"] and r["status"] == "filled" and r["fills"] == [(0.41, 120), (0.42, 80)] and r["fee"] == 3.40
    fills = _rows(eng, "SELECT shares, price, fee FROM accounts.fantasy_fills ORDER BY id")
    assert [(float(a), float(b), float(c)) for a, b, c in fills] == [(120, 0.41, 3.40), (80, 0.42, 0)]
    led = _rows(eng, "SELECT reason, amount FROM accounts.fantasy_ledger WHERE user_id = :u AND ref_table IS NOT NULL ORDER BY id",
                u=ada["id"])
    assert [(r_, float(a)) for r_, a in led] == [("trade", -49.20), ("trade", -33.60), ("fee", -3.40)]
    with eng.connect() as c:
        assert FL.cash(c, ada["id"]) == pytest.approx(1000 - 82.80 - 3.40)
        (p,) = FL.positions(c, ada["id"], open_only=True)
        assert p["yes_shares"] == 200 and p["cost"] == 82.80 and p["fees"] == 3.40 and p["value"] == 78.00  # 200 x bid 0.39
    assert _rows(eng, "SELECT action FROM activity_log WHERE user_id = :u", u=ada["id"])[-1][0] == "fantasy_order"
    # a partial sell back at the bid closes part of the position at average cost
    r = FX.place(eng, ada, db["links"]["win"], "yes", "sell", 50, 0.39, now=NOW, get_book=book())
    assert r["ok"] and r["fills"] == [(0.39, 50)] and r["position"]["shares"] == 150
    assert r["position"]["cost"] == pytest.approx(82.80 * 150 / 200, abs=0.01)


def test_depth_and_partial_status(db):
    from racinglines.fantasy import exchange as FX
    r = FX.place(db["engine"], db["users"]["ada"], db["links"]["win"], "yes", "buy", 238, 0.42, now=NOW,
                 get_book=book(asks=[[0.41, 100], [0.45, 500]]))
    assert r["status"] == "partial" and r["fills"] == [(0.41, 100)]


def test_no_side_buys_through_the_yes_bids(db):
    from racinglines.fantasy import exchange as FX
    r = FX.place(db["engine"], db["users"]["ada"], db["links"]["win"], "no", "buy", 100, 0.61, now=NOW, get_book=book())
    assert r["ok"] and r["fills"] == [(0.61, 100)] and r["fee"] == 1.67


def _reason(db, user="ada", link="win", side="yes", action="buy", shares=10, limit=0.42, **kw):
    from racinglines.fantasy import exchange as FX
    kw.setdefault("get_book", book())
    r = FX.place(db["engine"], db["users"][user], db["links"].get(link, link), side, action, shares, limit, now=kw.pop("now", NOW), **kw)
    assert not r["ok"]
    row = _rows(db["engine"], "SELECT status, reject_reason FROM accounts.fantasy_orders WHERE id = :i", i=r["order_id"])[0]
    assert row == ("rejected", r["reason"])
    audit = _rows(db["engine"], "SELECT detail->>'reason' FROM activity_log WHERE action = 'fantasy_order_rejected' ORDER BY id DESC LIMIT 1")
    assert audit[0][0] == r["reason"]
    return r["reason"]


def test_every_rejection_writes_a_row_and_an_audit_entry(db):
    from racinglines.fantasy import exchange as FX
    eng = db["engine"]
    assert _reason(db, shares=2.5) == "bad_input"
    assert _reason(db, side="maybe") == "bad_input"
    assert _reason(db, limit=1.5) == "bad_input"
    assert _reason(db, link=999999) == "bad_input"
    assert _reason(db, demo=True) == "not_a_member"
    with eng.begin() as c:                                   # an account without a ledger grant
        c.execute(text("DELETE FROM accounts.fantasy_ledger WHERE user_id = :u"), dict(u=db["users"]["cal"]["id"]))
    assert _reason(db, user="cal") == "not_a_member"
    assert _reason(db, link="motogp") == "no_schedule"       # a race kind with no race: fails closed
    with eng.begin() as c:
        c.execute(text("UPDATE sports SET code = 'f1x' WHERE code = 'f1'"))
    assert _reason(db) == "kind_not_tradable"
    with eng.begin() as c:
        c.execute(text("UPDATE sports SET code = 'f1' WHERE code = 'f1x'"))
    assert _reason(db, link="pole") == "session_started"     # qualifying started an hour ago
    assert _reason(db, now=RACE + timedelta(minutes=1)) == "session_started"
    with eng.begin() as c:
        c.execute(text("UPDATE market_links SET resolved_yes = true WHERE id = :i"), dict(i=db["links"]["champ"]))
    assert _reason(db, link="champ") == "market_closed"
    assert _reason(db, get_book=lambda tok: None) == "book_unavailable"
    assert _reason(db, get_book=book(ts=NOW - timedelta(minutes=FX.MAX_AGE_MIN + 1))) == "stale_book"
    assert _reason(db, limit=0.40) == "no_liquidity"
    assert _reason(db, shares=300, limit=0.42) == "over_order_cap"       # 126 > 100
    with eng.begin() as c:
        c.execute(text("INSERT INTO accounts.fantasy_ledger (user_id, amount, reason) VALUES (:u, -990, 'adjust')"),
                  dict(u=db["users"]["bea"]["id"]))
    assert _reason(db, user="bea", shares=100, limit=0.42) == "insufficient_balance"
    assert FX.place(eng, db["users"]["ada"], db["links"]["win"], "no", "buy", 10, 0.61, now=NOW, get_book=book())["ok"]
    assert _reason(db) == "opposite_side_held"
    assert _reason(db, side="no", action="sell", shares=11, limit=0.5) == "sell_exceeds_position"
    reasons = {r for (r,) in _rows(eng, "SELECT DISTINCT reject_reason FROM accounts.fantasy_orders WHERE status = 'rejected'")}
    assert reasons == set(FX.REASONS)
    assert not _rows(eng, "SELECT 1 FROM accounts.fantasy_fills f JOIN accounts.fantasy_orders o ON o.id = f.order_id "
                          "WHERE o.status = 'rejected'")


def test_insufficient_balance_rejects(db):
    from racinglines.fantasy import exchange as FX
    eng, bea = db["engine"], db["users"]["bea"]
    with eng.begin() as c:
        c.execute(text("INSERT INTO accounts.fantasy_ledger (user_id, amount, reason) VALUES (:u, -960, 'adjust')"),
                  dict(u=bea["id"]))
    r = FX.place(eng, bea, db["links"]["win"], "yes", "buy", 100, 0.42, now=NOW, get_book=book())   # 42 + fee > 40
    assert r["reason"] == "insufficient_balance"
    assert not _rows(eng, "SELECT 1 FROM accounts.fantasy_fills WHERE user_id = :u", u=bea["id"])


def test_concurrent_spending(db):
    """Two buys at once, each affordable alone, together not: the row lock lets exactly one through."""
    from racinglines.fantasy import exchange as FX
    eng, bea = db["engine"], db["users"]["bea"]
    with eng.begin() as c:
        c.execute(text("INSERT INTO accounts.fantasy_ledger (user_id, amount, reason) VALUES (:u, -930, 'adjust')"),
                  dict(u=bea["id"]))                    # 70 left; each order needs 41 + fee
    barrier, out = threading.Barrier(2), []

    def go():
        barrier.wait()
        out.append(FX.place(eng, bea, db["links"]["win"], "yes", "buy", 100, 0.41, now=NOW, get_book=book()))
    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(r["ok"] for r in out) == [False, True]
    assert [r["reason"] for r in out if not r["ok"]] == ["insufficient_balance"]
    with eng.connect() as c:
        from racinglines.fantasy import ledger as FL
        assert FL.cash(c, bea["id"]) >= 0


def test_idempotent_retry(db):
    from racinglines.fantasy import exchange as FX
    eng, ada = db["engine"], db["users"]["ada"]
    a = FX.place(eng, ada, db["links"]["win"], "yes", "buy", 10, 0.42, client_key="k1", now=NOW, get_book=book())
    b = FX.place(eng, ada, db["links"]["win"], "yes", "buy", 10, 0.42, client_key="k1", now=NOW, get_book=book())
    assert a["ok"] and b["repeat"] and a["order_id"] == b["order_id"] and b["fills"] == a["fills"]
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_orders")[0][0] == 1
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_fills")[0][0] == 1
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_ledger WHERE ref_table IS NOT NULL")[0][0] == 2   # trade + fee


def test_paper_tables_untouched(db):
    from racinglines.fantasy import exchange as FX
    before = _rows(db["engine"], "SELECT (SELECT count(*) FROM paper_positions), (SELECT count(*) FROM strategy_signals)")
    FX.place(db["engine"], db["users"]["ada"], db["links"]["win"], "yes", "buy", 10, 0.42, now=NOW, get_book=book())
    assert _rows(db["engine"], "SELECT (SELECT count(*) FROM paper_positions), (SELECT count(*) FROM strategy_signals)") == before


def test_reset_clears_manual_trades(db):
    from racinglines.fantasy import exchange as FX
    from racinglines.web import accounts as ACC
    eng = db["engine"]
    FX.place(eng, db["users"]["ada"], db["links"]["win"], "yes", "buy", 10, 0.42, now=NOW, get_book=book())
    with eng.begin() as c:
        rows = ACC.reset(c, apply=True)
    assert next(r for r in rows if r["username"] == "ada")["manual_orders"] == 1
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_orders")[0][0] == 0
    assert _rows(eng, "SELECT sum(amount) FROM accounts.fantasy_ledger WHERE user_id = :u", u=db["users"]["ada"]["id"])[0][0] == 1000


def _login(name):
    from racinglines.web import app as A
    client = TestClient(A.app)
    assert client.post("/login", data=dict(username=name, password=f"{name}-password-1"),
                       follow_redirects=False).status_code == 303
    return client


def test_pages_trade_and_leaderboard(db, monkeypatch):
    from racinglines.fantasy import exchange as FX
    eng = db["engine"]
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    with eng.begin() as c:                                   # a recorded book for the route (no injection there)
        c.execute(text("""INSERT INTO market_book_snapshots (token_id, ts, best_bid, best_ask, bids, asks)
                          VALUES ('PM-CHAMP-VER', :ts, 0.39, 0.41, CAST(:b AS jsonb), CAST(:a AS jsonb))"""),
                  dict(ts=recent, b=str(BIDS), a=str(ASKS)))
    ada = _login("ada")
    home = ada.get("/fantasy").text
    assert "1,000.00" in home and "Trade by hand" in home and "Pick a strategy" in home
    page = ada.get("/fantasy/trade").text
    assert "Verstappen" in page and f'href="/fantasy/trade?link={db["links"]["champ"]}"' in page
    page = ada.get(f"/fantasy/trade?link={db['links']['champ']}").text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    key = re.search(r'name="client_key" value="([^"]+)"', page).group(1)
    form = dict(csrf_token=csrf, market_link_id=str(db["links"]["champ"]), side="yes", action="buy", shares="100",
                limit_price="0.41", client_key=key)
    r = ada.post("/fantasy/orders", data=form, follow_redirects=False)
    assert r.status_code == 303 and "Bought%20100%20YES" in r.headers["location"]
    r = ada.post("/fantasy/orders", data=form, follow_redirects=False)              # a double submit
    assert "already%20placed" in r.headers["location"]
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_orders WHERE status <> 'rejected'")[0][0] == 1
    board = _login("bea").get("/leaderboard").text
    assert board.index("bea") < board.index("ada")           # ada paid 41 for shares worth 39 at the bid
    assert "taker" not in board.split("<tbody>")[1]          # demo accounts aren't ranked
    monkeypatch.setenv("RACINGLINES_FANTASY", "0")
    assert ada.get("/fantasy").status_code == 404 and ada.get("/leaderboard").status_code == 404
    assert FX.TEXT["no_liquidity"]


def test_pages_say_not_set_up_before_setup(db, monkeypatch):
    with db["engine"].begin() as c:
        c.execute(text("DROP TABLE accounts.fantasy_fills, accounts.fantasy_positions, accounts.fantasy_orders"))
    ada = _login("ada")
    assert "Not open yet" in ada.get("/fantasy").text and "Not open yet" in ada.get("/leaderboard").text
