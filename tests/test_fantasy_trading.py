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
    assert _reason(db) == "sport_not_tradable"
    with eng.begin() as c:
        c.execute(text("UPDATE sports SET code = 'f1' WHERE code = 'f1x'"))
    with eng.begin() as c:                                   # an F1 market of a kind fantasy doesn't trade
        c.execute(text("UPDATE market_links SET exchange = 'nowhere' WHERE id = :i"), dict(i=db["links"]["win"]))
    assert _reason(db) == "kind_not_tradable"
    with eng.begin() as c:
        c.execute(text("UPDATE market_links SET exchange = 'kalshi' WHERE id = :i"), dict(i=db["links"]["win"]))
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


def _board(page):
    """The leaderboard section of /history."""
    return page.split('<section id="leaderboard"', 1)[1].split("</section>", 1)[0]


def _main_nav(page):
    return page.split('<nav aria-label="Main">', 1)[1].split("</nav>", 1)[0]


def test_pages_trade_and_history(db, monkeypatch):
    from racinglines.fantasy import exchange as FX
    eng = db["engine"]
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    with eng.begin() as c:                                   # a recorded book for the route (no injection there)
        c.execute(text("""INSERT INTO market_book_snapshots (token_id, ts, best_bid, best_ask, bids, asks)
                          VALUES ('PM-CHAMP-VER', :ts, 0.39, 0.41, CAST(:b AS jsonb), CAST(:a AS jsonb))"""),
                  dict(ts=recent, b=str(BIDS), a=str(ASKS)))
    ada = _login("ada")
    home = ada.get("/history")
    assert home.status_code == 200
    assert "1,000.00" in home.text and "Pick one" in home.text and 'id="leaderboard"' in home.text
    page = ada.get("/trade")
    assert page.status_code == 200
    assert "Verstappen" in page.text and f'href="/trade?link={db["links"]["champ"]}"' in page.text
    assert "/fantasy/trade" not in page.text and 'href="/history"' in page.text
    page = ada.get(f"/trade?link={db['links']['champ']}").text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    key = re.search(r'name="client_key" value="([^"]+)"', page).group(1)
    form = dict(csrf_token=csrf, market_link_id=str(db["links"]["champ"]), side="yes", action="buy", shares="100",
                limit_price="0.41", client_key=key)
    r = ada.post("/fantasy/orders", data=form, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/trade?link=")
    assert "Bought%20100%20YES" in r.headers["location"]
    r = ada.post("/fantasy/orders", data=form, follow_redirects=False)              # a double submit
    assert "already%20placed" in r.headers["location"]
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_orders WHERE status <> 'rejected'")[0][0] == 1
    hist = ada.get("/history").text                         # the open trade, its Sell link and the order by hand
    assert f'href="/trade?link={db["links"]["champ"]}&action=sell&side=yes"' in hist
    assert "Orders by hand" in hist and "filled" in hist
    board = _board(_login("bea").get("/history").text)
    assert board.index("bea") < board.index("ada")           # both unranked (1 trade); ada's shares are worth 39 at the bid
    assert "taker" not in board.split("<tbody>")[1]          # demo accounts aren't listed
    monkeypatch.setenv("RACINGLINES_FANTASY", "0")
    for path in ("/history", "/trade", "/fantasy", "/leaderboard"):
        assert ada.get(path, follow_redirects=False).status_code == 404
    assert FX.TEXT["no_liquidity"]


def test_history_lists_refused_orders_and_the_curve(db):
    from racinglines.fantasy import exchange as FX
    eng, ada = db["engine"], db["users"]["ada"]
    FX.place(eng, ada, db["links"]["win"], "yes", "buy", 10, 0.42, now=NOW, get_book=book())
    FX.place(eng, ada, db["links"]["win"], "yes", "buy", 10, 0.40, now=NOW, get_book=book())       # no liquidity
    FX.place(eng, ada, db["links"]["win"], "yes", "sell", 5, 0.39, now=NOW, get_book=book())
    page = _login("ada").get("/history").text
    assert "refused: " + FX.TEXT["no_liquidity"] in page
    assert '<svg class="chart"' in page and ">now</text>" in page    # F$ through the run, the last point marked


def test_old_addresses_redirect(db):
    ada = _login("ada")
    r = ada.get("/fantasy", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/history"
    r = ada.get("/fantasy/trade?link=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/trade?link=1"
    r = ada.get("/fantasy/trade", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/trade"
    r = ada.get("/leaderboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/history#leaderboard"


def test_ranked_scores_gates_and_orders(db, monkeypatch):
    """fantasy/ledger.ranked: score = ROI x sqrt(trades), ranked best first; below MIN_TRADES unranked, after the
    ranked ones, by P&L."""
    from racinglines.fantasy import exchange as FX
    from racinglines.fantasy import ledger as FL
    eng, u = db["engine"], db["users"]
    for _ in range(FL.MIN_TRADES):                           # ada: MIN_TRADES buys of 10 YES at 0.41 (Kalshi fee each)
        assert FX.place(eng, u["ada"], db["links"]["win"], "yes", "buy", 10, 0.41, now=NOW, get_book=book())["ok"]
    assert FX.place(eng, u["bea"], db["links"]["win"], "yes", "buy", 10, 0.41, now=NOW, get_book=book())["ok"]
    with eng.connect() as c:
        rows = {r["username"]: r for r in FL.ranked(c)}
        order = [r["username"] for r in FL.ranked(c)]
    a, b, cal = rows["ada"], rows["bea"], rows["cal"]
    assert a["trades"] == FL.MIN_TRADES and b["trades"] == 1 and cal["trades"] == 0
    assert a["staked"] == pytest.approx(FL.MIN_TRADES * (4.10 + 0.17))      # cost plus the Kalshi fee, per order
    assert a["roi"] == pytest.approx((a["manual_pnl"] + a["strategy_pnl"]) / a["staked"])
    assert a["score"] == pytest.approx(a["roi"] * FL.MIN_TRADES ** 0.5, abs=1e-4) and a["rank"] == 1
    assert b["score"] is None and b["rank"] is None and b["roi"] is not None   # one trade: unranked
    assert cal["roi"] is None and cal["score"] is None and cal["rank"] is None
    assert order == ["ada", "cal", "bea"]                    # ranked first; then cal (P&L 0) before bea (a fee down)
    assert a["pnl"] == pytest.approx(a["manual_pnl"] + a["strategy_pnl"])
    monkeypatch.setattr(FL, "MIN_TRADES", 1)                  # with the gate at one trade both rank, by score
    with eng.connect() as c:
        rows = FL.ranked(c)
    ranked = [r for r in rows if r["rank"]]
    assert [r["rank"] for r in ranked] == [1, 2] and ranked[0]["score"] >= ranked[1]["score"]
    assert {r["username"] for r in ranked} == {"ada", "bea"} and rows[-1]["username"] == "cal"
    # the page lists the unranked with "–" in rank and explains the score
    board = _board(_login("cal").get("/history").text)
    assert "ROI × √trades" in board
    assert "Total F$" not in board and "1,000" not in board                # P&L and ROI, never a balance


def test_history_page_marks_unranked_players(db):
    from racinglines.fantasy import exchange as FX
    from racinglines.fantasy import ledger as FL
    eng, u = db["engine"], db["users"]
    for _ in range(FL.MIN_TRADES):
        FX.place(eng, u["ada"], db["links"]["win"], "yes", "buy", 10, 0.41, now=NOW, get_book=book())
    board = _board(_login("bea").get("/history").text)
    body = board.split("<tbody>")[1]
    first, *rest = body.split("</tr>")[:3]
    assert "ada" in first and '<td class="num">1</td>' in first
    assert all('<td class="num">–</td>' in r for r in rest)
    assert f"needs {FL.MIN_TRADES} trades to be ranked" in board


def _make_admin():
    from racinglines.db import config
    from racinglines.web import users as U
    with config.get_session() as s:
        U.create_user(s, "ola", "ola-password-1", "admin")


def test_alpha_archives_live_and_book(db, monkeypatch):
    """Under the alpha layout (fantasy on), /live and /book are 404 to everyone but admins; classic keeps them."""
    _make_admin()
    ada, ola = _login("ada"), _login("ola")
    for path in ("/live", "/book"):
        assert ada.get(path).status_code == 404, path
        assert ola.get(path).status_code == 200, path
    monkeypatch.setenv("RACINGLINES_LAYOUT", "classic")
    for path in ("/live", "/book"):
        assert ada.get(path).status_code == 200, path
        assert ola.get(path).status_code == 200, path


def test_nav_four_tabs_under_alpha_old_bar_under_classic(db, monkeypatch):
    _make_admin()
    ada = _login("ada")
    nav = _main_nav(ada.get("/history").text)
    assert [h for h in re.findall(r'href="([^"]+)"', nav)] == ["/markets", "/trade", "/history", "/strategy/pick"]  # Lab opens on Follow a strategy (owner, 2026-10-13)
    page = ada.get("/history").text
    assert 'href="/pitch"' not in page and "racinglines-public" in page
    assert 'href="/docs/" aria-label="racinglines docs"' in page          # the docs book beside GitHub (owner, 2026-10-14)
    assert 'href="/logout"' in page and 'href="/settings"' in page
    nav = _main_nav(_login("ola").get("/history").text)
    assert re.findall(r'href="([^"]+)"', nav) == ["/markets", "/trade", "/history", "/strategy/pick", "/admin"]
    monkeypatch.setenv("RACINGLINES_LAYOUT", "classic")
    page = ada.get("/history").text
    hrefs = re.findall(r'href="([^"]+)"', _main_nav(page))
    assert {"/markets", "/strategy", "/positions", "/trade", "/history", "/book", "/lab"} <= set(hrefs)
    assert "/fantasy" not in hrefs and "/leaderboard" not in hrefs
    assert 'href="/pitch"' in page and 'href="/docs/"' in page


def test_positions_hides_the_private_book_under_alpha(db, monkeypatch):
    uid = db["users"]["ada"]["id"]
    with db["engine"].begin() as c:
        c.execute(text("""INSERT INTO paper_positions (user_id, venue, event_key, market_key, kind, subject, yes_shares,
                                                       no_shares, cash, mark)
                          VALUES (:u, 'private', '2026-09-27-whistler', 'priv-1', 'race_win', 'Privaterider', 10, 0,
                                  -4, 0.5)"""), dict(u=uid))
    ada = _login("ada")
    page = ada.get("/positions").text
    assert "Privaterider" not in page and 'value="private"' not in page and "Private book" not in page
    assert ada.get("/positions?venue=private").status_code == 200
    monkeypatch.setenv("RACINGLINES_LAYOUT", "classic")
    page = ada.get("/positions").text
    assert "Privaterider" in page and 'value="private"' in page


def test_pages_say_not_set_up_before_setup(db, monkeypatch):
    with db["engine"].begin() as c:
        c.execute(text("DROP TABLE accounts.fantasy_fills, accounts.fantasy_positions, accounts.fantasy_orders"))
    ada = _login("ada")
    assert "Not open yet" in ada.get("/history").text and "Not open yet" in ada.get("/trade").text


def test_settle_pays_resolved_hand_trades_once_and_closes_them(db):
    from racinglines.fantasy import exchange as FX
    from racinglines.fantasy import ledger as FL
    eng, ada, bea = db["engine"], db["users"]["ada"], db["users"]["bea"]
    assert FX.place(eng, ada, db["links"]["win"], "yes", "buy", 100, 0.42, now=NOW, get_book=book())["ok"]
    assert FX.place(eng, bea, db["links"]["win"], "no", "buy", 100, 0.61, now=NOW, get_book=book())["ok"]
    assert FX.place(eng, ada, db["links"]["champ"], "yes", "buy", 10, 0.42, now=NOW, get_book=book())["ok"]
    assert FX.settle(eng) == 0                                          # nothing resolved yet
    with eng.begin() as c:
        c.execute(text("UPDATE market_links SET resolved_yes = true WHERE id = :i"), dict(i=db["links"]["win"]))
    with eng.connect() as c:
        before = FL.cash(c, ada["id"]), FL.cash(c, bea["id"])
    assert FX.settle(eng) == 2 and FX.settle(eng) == 0                  # once only
    with eng.connect() as c:
        assert FL.cash(c, ada["id"]) == pytest.approx(before[0] + 100)  # 100 YES x F$1
        assert FL.cash(c, bea["id"]) == pytest.approx(before[1])        # the NO side gets nothing
        assert [p["market_link_id"] for p in FL.positions(c, ada["id"], open_only=True)] == [db["links"]["champ"]]
        s = FL.summary(c, ada["id"])
    assert s["manual_pnl"] == pytest.approx(100 - 41.0 - 1.70 + (10 * 0.39 - 4.10), abs=0.01)
    st = _rows(eng, "SELECT status, outcome, payout FROM accounts.fantasy_positions WHERE user_id = :u AND market_link_id = :l",
               u=ada["id"], l=db["links"]["win"])
    assert st == [("settled", True, 100)]
    # a settled position can't be traded again
    r = FX.place(eng, ada, db["links"]["win"], "yes", "sell", 10, 0.39, now=NOW, get_book=book())
    assert not r["ok"] and r["reason"] == "market_closed"


def test_books_engine_from_another_url_is_read_only(test_engine, monkeypatch):
    from sqlalchemy.exc import DBAPIError

    from racinglines.fantasy import exchange as FX
    monkeypatch.setenv("RACINGLINES_FANTASY_BOOKS_URL", test_engine.url.render_as_string(hide_password=False))
    FX._BOOKS.clear()
    b = FX.books_engine(test_engine)
    assert b is not test_engine
    with b.connect() as c:
        assert c.execute(text("SELECT 1")).scalar() == 1
        with pytest.raises(DBAPIError, match="read-only"):
            c.execute(text("CREATE TABLE fantasy_ro_probe (x int)"))
    FX._BOOKS.clear()


def test_close_falls_back_to_the_books_database_by_token(db, monkeypatch):
    """Staging's rounds have no session starts: the close comes from the books database's link with the same token."""
    import pandas as pd
    from sqlalchemy import create_engine

    from racinglines.fantasy import exchange as FX
    eng = db["engine"]
    other = create_engine(eng.url)                                       # stands in for production's database
    seen = []

    def close(conn, link):
        seen.append(conn.engine is other)
        return pd.Timestamp("2026-10-19 19:00") if conn.engine is other else None
    monkeypatch.setattr(FX, "_close", close)
    monkeypatch.setattr(FX, "books_engine", lambda default: other)
    with eng.connect() as c:
        link = FX._link(c, db["links"]["win"])
        assert FX.closes_at(c, link).isoformat() == "2026-10-19T19:00:00+00:00" and seen == [False, True]
        monkeypatch.setattr(FX, "books_engine", lambda default: default)  # no separate books database: refused
        with pytest.raises(FX.Rejected):
            FX.closes_at(c, link)
    other.dispose()


def _mcp_client(engine, monkeypatch, who):
    """mcp(name, **args) against a server on the test database, called as `who` (None = stdio, the owner)."""
    import asyncio
    import json

    from mcp import Client

    from racinglines.mcp import server as S
    monkeypatch.setattr(S, "caller", lambda: who)
    url = engine.url.render_as_string(hide_password=False)

    def call(name, **args):
        async def go():
            async with Client(S.build(engine_url=url)) as client:
                r = await client.call_tool(name, args)
                t = r.content[-1].text
                return ("error", t) if r.is_error else json.loads(t)
        try:
            return asyncio.run(go())
        finally:
            S._URL = None
    return call


def test_mcp_fantasy_tools_are_own_account_and_trade_like_the_page(db, monkeypatch):
    from racinglines.fantasy import exchange as FX
    eng, u = db["engine"], db["users"]
    champ = db["links"]["champ"]
    with eng.begin() as c:
        c.execute(text("""INSERT INTO market_book_snapshots (token_id, ts, best_bid, best_ask, bids, asks)
                          VALUES ('PM-CHAMP-VER', :ts, 0.39, 0.41, CAST(:b AS jsonb), CAST(:a AS jsonb))"""),
                  dict(ts=datetime.now(timezone.utc) - timedelta(minutes=1), b=str(BIDS), a=str(ASKS)))
    FX._BOOKS.clear()
    mcp = _mcp_client(eng, monkeypatch, dict(u["ada"], role="pro"))
    assert any(m["market_link_id"] == champ for m in mcp("fantasy_markets", q="Verstappen")["markets"]["rows"])
    book = mcp("fantasy_book", market_link_id=champ)
    assert book["yes_asks"][0] == [0.41, 120] and len(book["no_bids"]) <= FX.DEPTH
    r = mcp("fantasy_order", market_link_id=champ, side="yes", action="buy", shares=10, limit_price=0.41)
    assert r["ok"] and r["user"] == "ada" and r["fills"] == [[0.41, 10]] and r["cash"] == pytest.approx(1000 - 4.10)
    bal = mcp("fantasy_balance")
    assert bal["user"] == "ada" and bal["open"] == 1
    assert mcp("fantasy_positions")["positions"]["rows"][0]["shares"] == 10
    assert mcp("fantasy_orders")["orders"]["rows"][0]["status"] == "filled"
    # guardrails: another account is out of reach for reads and orders, and the leaderboard has no balances
    for name in ("fantasy_balance", "fantasy_positions", "fantasy_orders"):
        denied = mcp(name, user="bea")
        assert denied[0] == "error" and "own account" in denied[1], name
    denied = mcp("fantasy_order", market_link_id=champ, side="yes", action="buy", shares=1, limit_price=0.41, user="bea")
    assert denied[0] == "error" and "own account" in denied[1]
    rows = mcp("fantasy_leaderboard")["rows"]["rows"]
    assert {"total", "cash", "grant"}.isdisjoint(rows[0]) and "pnl" in rows[0]
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_orders WHERE user_id = :u", u=u["bea"]["id"]) == [(0,)]
    assert _rows(eng, "SELECT detail->>'via' FROM activity_log WHERE action = 'fantasy_order'") == [("mcp",)]
    # an admin over HTTP still trades only as itself; stdio must name the account
    admin = _mcp_client(eng, monkeypatch, dict(u["cal"], role="admin"))
    assert admin("fantasy_balance", user="bea")["user"] == "bea"            # an admin may read others
    assert "own account" in admin("fantasy_order", market_link_id=champ, side="yes", action="buy", shares=1,
                                  limit_price=0.41, user="bea")[1]
    owner = _mcp_client(eng, monkeypatch, None)
    assert "which account" in owner("fantasy_order", market_link_id=champ, side="yes", action="buy", shares=1,
                                    limit_price=0.41)[1]


def _record(eng, token, ts=None):
    """A recorded book for `token` the routes and the MCP tools read (no injection there)."""
    with eng.begin() as c:
        c.execute(text("""INSERT INTO market_book_snapshots (token_id, ts, best_bid, best_ask, bids, asks)
                          VALUES (:t, :ts, 0.39, 0.41, CAST(:b AS jsonb), CAST(:a AS jsonb))"""),
                  dict(t=token, ts=ts or datetime.now(timezone.utc) - timedelta(minutes=1), b=str(BIDS), a=str(ASKS)))


def test_every_surface_says_when_a_market_closes(db, monkeypatch):
    """closes_at on the market list, the MCP markets and book tools and the Trade page's header (exchange.closes_for,
    closes_at for many links): the deciding round's stored start for a race link, null for a season future."""
    from racinglines.fantasy import exchange as FX
    eng, win, champ = db["engine"], db["links"]["win"], db["links"]["champ"]
    _record(eng, "KX-WIN-VER")
    _record(eng, "PM-CHAMP-VER")
    FX._BOOKS.clear()
    with eng.connect() as c:
        close = {m["id"]: m["closes_at"] for m in FX.markets(c)}
    assert close[win] == RACE and close[champ] is None
    mcp = _mcp_client(eng, monkeypatch, dict(db["users"]["ada"], role="pro"))
    rows = {m["market_link_id"]: m["closes_at"] for m in mcp("fantasy_markets")["markets"]["rows"]}
    assert rows[win] == RACE.isoformat() and rows[champ] is None
    assert mcp("fantasy_book", market_link_id=win)["closes_at"] == RACE.isoformat()
    assert mcp("fantasy_book", market_link_id=champ)["closes_at"] is None
    ada = _login("ada")
    assert "closes 2026-10-25 12:00 UTC" in ada.get(f"/trade?link={win}").text
    assert "season future, no close" in ada.get(f"/trade?link={champ}").text


def test_quote_previews_an_order_on_every_surface_without_writing(db, monkeypatch):
    """exchange.quote walks the latest recorded book as place does (the same steps, the same fee) and writes nothing;
    fantasy_quote serves it over MCP and the Trade form shows it as the 'if filled now' line."""
    from racinglines.fantasy import exchange as FX
    eng, win, champ = db["engine"], db["links"]["win"], db["links"]["champ"]
    _record(eng, "KX-WIN-VER")
    _record(eng, "PM-CHAMP-VER")
    FX._BOOKS.clear()
    mcp = _mcp_client(eng, monkeypatch, dict(db["users"]["ada"], role="pro"))
    q = mcp("fantasy_quote", market_link_id=win, side="yes", action="buy", shares=100, limit_price=0.42)
    assert q["ok"] and q["user"] == "ada" and q["fills"] == [[0.41, 100]] and q["status"] == "filled"
    assert q["avg_price"] == 0.41 and q["notional"] == 41.0 and q["fee"] == 1.7 and q["total"] == 42.7   # the worked example
    assert q["cash"] == 1000 and q["book_ts"] and q["age_s"] < 120
    refused = mcp("fantasy_quote", market_link_id=win, side="yes", action="buy", shares=10, limit_price=0.40)
    assert not refused["ok"] and refused["reason"] == "no_liquidity" and refused["message"] == FX.TEXT["no_liquidity"]
    assert mcp("fantasy_quote", market_link_id=champ, side="no", action="sell", shares=1, limit_price=0.5)["reason"] == "sell_exceeds_position"
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_orders")[0][0] == 0           # nothing written
    assert _rows(eng, "SELECT count(*) FROM activity_log WHERE action LIKE 'fantasy_order%'")[0][0] == 0
    r = mcp("fantasy_order", market_link_id=win, side="yes", action="buy", shares=100, limit_price=0.42)
    assert r["ok"] and r["fills"] == q["fills"] and r["fee"] == q["fee"]                   # the order does what the quote said
    assert "own account" in mcp("fantasy_quote", market_link_id=win, side="yes", action="buy", shares=1, limit_price=0.42, user="bea")[1]
    # the Trade form: the page's defaults are quoted, ?shares=&limit_price= requote, Preview places nothing
    ada = _login("ada")
    page = ada.get(f"/trade?link={champ}").text
    assert "If filled now:</b> buys 10 YES at an average of 0.410, F$4.10: costs F$4.10." in page
    page = ada.get(f"/trade?link={champ}&shares=150&limit_price=0.41").text
    assert 'value="150"' in page and "buys 120 of 150 YES" in page and "the rest isn't on the book" in page
    assert "would be refused:</b> " + FX.TEXT["over_order_cap"] in ada.get(f"/trade?link={champ}&shares=500&limit_price=0.42").text
    page = ada.get(f"/trade?link={champ}&shares=5&limit_price=0.40").text
    assert "would be refused:</b> " + FX.TEXT["no_liquidity"] in page
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    r = ada.post("/fantasy/orders", data=dict(csrf_token=csrf, market_link_id=str(champ), side="yes", action="buy", shares="7",
                                              limit_price="0.42", client_key="k1", preview="1"), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/trade?link={champ}&action=buy&side=yes&shares=7&limit_price=0.42"
    assert "buys 7 YES at an average of 0.410" in ada.get(r.headers["location"]).text
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_orders WHERE market_link_id = :l", l=champ)[0][0] == 0


def test_mcp_order_refusals_share_one_shape_rate_limit_included(db, monkeypatch):
    """tools.fantasy_order: a rate-limited order is ok=false, reason rate_limited, message exchange.TEXT, like every
    other refusal (not a tool error), with an audit row and no order row, as the Trade page's refusal; the web
    flash is unchanged."""
    from racinglines.fantasy import exchange as FX
    eng, champ = db["engine"], db["links"]["champ"]
    _record(eng, "PM-CHAMP-VER")
    FX._BOOKS.clear()
    monkeypatch.setattr(FX, "RATE_MINUTE", 1)
    mcp = _mcp_client(eng, monkeypatch, dict(db["users"]["ada"], role="pro"))
    assert mcp("fantasy_order", market_link_id=champ, side="yes", action="buy", shares=1, limit_price=0.41)["ok"]
    r = mcp("fantasy_order", market_link_id=champ, side="yes", action="buy", shares=1, limit_price=0.41)
    assert r == dict(user="ada", ok=False, order_id=None, status="rejected", reason="rate_limited",
                     message=FX.TEXT["rate_limited"], fills=[], fee=0.0, position=None, cash=r["cash"])
    assert r["cash"] == pytest.approx(1000 - 0.41)
    assert _rows(eng, "SELECT count(*) FROM accounts.fantasy_orders WHERE user_id = :u", u=db["users"]["ada"]["id"]) == [(1,)]
    assert _rows(eng, "SELECT detail->>'reason', detail->>'via' FROM activity_log WHERE action = 'fantasy_order_rejected'") == [("rate_limited", "mcp")]
    FX._HITS.clear()
    monkeypatch.setattr(FX, "RATE_MINUTE", 1)
    ada = _login("ada")
    page = ada.get(f"/trade?link={champ}").text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    form = dict(csrf_token=csrf, market_link_id=str(champ), side="yes", action="buy", shares="1", limit_price="0.41")
    assert "Bought%201%20YES" in ada.post("/fantasy/orders", data=dict(form, client_key="w1"), follow_redirects=False).headers["location"]
    r = ada.post("/fantasy/orders", data=dict(form, client_key="w2"), follow_redirects=False)
    assert r.status_code == 303 and "Error%3A%20Too%20many%20orders" in r.headers["location"]


def test_history_lists_settled_trades(db, monkeypatch):
    """/history shows the hand trades exchange.settle paid out (outcome, payout, when) in a Settled trades card, from
    ledger.positions(open_only=False), the rows fantasy_positions(open_only=False) already serves over MCP."""
    from racinglines.fantasy import exchange as FX
    eng, ada, win = db["engine"], db["users"]["ada"], db["links"]["win"]
    assert FX.place(eng, ada, win, "yes", "buy", 100, 0.42, now=NOW, get_book=book())["ok"]
    assert FX.place(eng, ada, db["links"]["champ"], "yes", "buy", 10, 0.42, now=NOW, get_book=book())["ok"]
    page = _login("ada").get("/history").text
    assert "No settled trades yet" in page
    with eng.begin() as c:
        c.execute(text("UPDATE market_links SET resolved_yes = true WHERE id = :i"), dict(i=win))
    page = _login("ada").get("/history").text                            # the page settles, then lists it
    card = page.split("<h2>Settled trades", 1)[1].split("</div>\n\n", 1)[0]
    assert "United States GP · Kalshi" in card and ">YES</td>" in card and ">100.00</td>" in card and "+$59.00" in card
    assert "UTC" in card and card.count("<tr>") == 2                      # the champ trade stays open
    opened = page.split("<h2>Open trades", 1)[1].split("<h2>Settled trades", 1)[0]
    assert "Polymarket" in opened and "Kalshi" not in opened
    mcp = _mcp_client(eng, monkeypatch, dict(ada, role="pro"))
    rows = mcp("fantasy_positions", open_only=False)["positions"]["rows"]
    assert [(r["status"], r["payout"]) for r in rows if r["market_link_id"] == win] == [("settled", 100.0)]


def test_other_sports_are_view_only_with_a_notice(db):
    """Fantasy trading is F1 only for now (owner, 2026-10-12 23:07Z): a non-F1 market says so on Trade and is refused."""
    from racinglines.fantasy import exchange as FX
    eng = db["engine"]
    with eng.begin() as c:
        c.execute(text("INSERT INTO sports (code, name) VALUES ('nascar', 'NASCAR') ON CONFLICT DO NOTHING"))
        c.execute(text("INSERT INTO leagues (code, name) VALUES ('nascar', 'NASCAR') ON CONFLICT DO NOTHING"))
        comp = c.execute(text("""INSERT INTO competitions (code, name, league_id, sport_id)
                                 SELECT 'nascar_cup_t', 'Cup', l.id, s.id FROM leagues l, sports s
                                 WHERE l.code = 'nascar' AND s.code = 'nascar' RETURNING id""")).scalar()
        lid = c.execute(text("""INSERT INTO market_links (exchange, question, token_id, outcome, competition_id, prediction,
                                                          group_title, last_bid, last_ask)
                                VALUES ('kalshi', 'race_win Larson', 'KX-NASCAR-LAR', 'Yes', :c, 'race_win', 'Larson', 0.2, 0.22)
                                RETURNING id"""), dict(c=comp)).scalar()
    page = _login("ada").get(f"/trade?link={lid}").text
    assert "Fantasy trading is Formula 1 only for now" in page and 'action="/fantasy/orders"' not in page
    r = FX.place(eng, db["users"]["ada"], lid, "yes", "buy", 10, 0.22, now=NOW, get_book=book())
    assert not r["ok"] and r["reason"] == "sport_not_tradable" and "Formula 1 only" in r["message"]
