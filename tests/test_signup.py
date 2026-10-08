"""Beta sign-up (RACINGLINES_SIGNUP=1, web/accounts.py): off by default, the 1,000 fantasy-bucks grant, admin
reset and remove, the `users` CLI. The first tests need no database; the rest run on the test database."""

import re

import pytest
from fastapi.testclient import TestClient

GOOD = dict(username="Ada_Lovelace", email="Ada@Example.com", password="correct horse battery",
            confirm="correct horse battery", adult="1")


# --- no database -------------------------------------------------------------------------------------------------

@pytest.mark.quick
def test_rules():
    from racinglines.web import accounts as ACC

    class NoRows:
        def execute(self, *a, **k):
            return self

        def first(self):
            return None
    c = NoRows()
    assert ACC.check_username(c, "ada_lovelace") == ""
    for bad in ("ab", "-ada", "ada lovelace", "ada@example.com", "x" * 31):
        assert "3 to 30" in ACC.check_username(c, bad)
    for name in ("admin", "maker", "taker", "polymarket-takers"):
        assert "reserved" in ACC.check_username(c, name)
    assert ACC.check_password("short", "short", "ada") .startswith("Passwords need")
    assert "username" in ACC.check_password("ada-is-my-password", "ada-is-my-password", "ada")
    assert "match" in ACC.check_password("correct horse battery", "correct horse batterY", "ada")
    assert ACC.check_password("correct horse battery", "correct horse battery", "ada") == ""
    assert ACC.temp_password() != ACC.temp_password() and len(ACC.temp_password()) >= 16


@pytest.mark.quick
def test_off_by_default(monkeypatch):
    from racinglines.web import app as A
    monkeypatch.delenv("RACINGLINES_SIGNUP", raising=False)
    client = TestClient(A.app)
    assert client.get("/signup").status_code == 404 and client.get("/forgot").status_code == 404
    assert client.post("/signup", data=GOOD).status_code == 404
    page = client.get("/login").text
    assert "/signup" not in page and "signups</a> are live" not in page


@pytest.mark.quick
def test_closed_until_setup_has_run(monkeypatch):
    """Switch on but no ledger (or no database): the page says sign-up isn't open, and nothing is written."""
    from racinglines.web import app as A
    monkeypatch.setenv("RACINGLINES_SIGNUP", "1")
    monkeypatch.setattr(A, "_signup_ready", lambda: False)
    monkeypatch.setattr(A, "_signup_hits", {})
    client = TestClient(A.app)
    assert "isn't open yet" in client.get("/signup").text
    assert client.post("/signup", data=GOOD).status_code == 503
    page = client.get("/login").text                      # the landing page links to sign-up once; no popup (2026-10-08)
    assert 'id="site-notice"' not in page and page.count('href="/signup"') == 1
    assert 'href="/forgot"' in page
    forgot = client.get("/forgot").text                    # no email on file: a reset request to us, prefilled
    assert "mailto:hello@racinglines.bet?subject=Password%20reset%20request" in forgot and "Username:" in forgot


# --- the test database ---------------------------------------------------------------------------------------------

@pytest.fixture
def app_db(test_engine, monkeypatch):
    """The web app on the test database, with the accounts ledger set up and sign-up on."""
    from racinglines.db import config
    from racinglines.web import accounts as ACC
    from racinglines.web import app as A
    with test_engine.begin() as c:
        c.execute(__import__("sqlalchemy").text("DROP SCHEMA IF EXISTS accounts CASCADE"))
        c.execute(__import__("sqlalchemy").text("DELETE FROM users"))
    monkeypatch.setenv("DATABASE_URL", test_engine.url.render_as_string(hide_password=False))
    config.get_engine.cache_clear()
    monkeypatch.setenv("RACINGLINES_SIGNUP", "1")
    monkeypatch.setattr(A, "_signup_hits", {})
    with config.get_session() as s:
        from racinglines.web import users as U
        U.create_user(s, "boss", "boss-password-1", "admin")
        U.create_user(s, "taker", "password", "basic")
    assert ACC.setup(config.get_engine()) == 2                    # backfill: both existing accounts get 1,000
    assert ACC.setup(config.get_engine()) == 0                    # idempotent
    yield A
    config.get_engine.cache_clear()


def _balance(name):
    from sqlalchemy import text
    from racinglines.db.config import get_engine
    with get_engine().connect() as c:
        return c.execute(text("""SELECT sum(l.amount) FROM accounts.fantasy_ledger l JOIN users u ON u.id = l.user_id
                                 WHERE u.username = :n"""), dict(n=name)).scalar()


def _admin(A):
    client = TestClient(A.app)
    assert client.post("/login", data=dict(username="boss", password="boss-password-1"),
                       follow_redirects=False).status_code == 303
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/admin/users").text)
    return client, (csrf.group(1) if csrf else "")


def test_signup_creates_a_hashed_account_with_1000_bucks(app_db):
    from sqlalchemy import text
    from racinglines.db.config import get_engine
    client = TestClient(app_db.app)
    r = client.post("/signup", data=GOOD, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/markets" and "rl_session" in r.cookies
    with get_engine().connect() as c:
        role, h = c.execute(text("SELECT role, password_hash FROM users WHERE username = 'ada_lovelace'")).one()
        logs = c.execute(text("SELECT detail::text FROM activity_log")).scalars().all()
    assert role == "pro" and h.startswith("scrypt$") and GOOD["password"] not in h
    assert not any(GOOD["password"] in (d or "") for d in logs)          # never logged
    assert float(_balance("ada_lovelace")) == 1000
    assert client.get("/markets").status_code == 200                       # signed in
    fresh = TestClient(app_db.app)                                         # and can sign in again
    assert fresh.post("/login", data=dict(username="ada_lovelace", password=GOOD["password"]),
                      follow_redirects=False).headers["location"] == "/markets"


def test_signups_get_different_taker_strategies(app_db):
    """Each new account gets one strategy from TAKER_TOP, round-robin by user id (owner, 2026-10-06)."""
    from sqlalchemy import text
    from racinglines.db.config import get_engine
    from racinglines.pipelines import profiles as PF
    with get_engine().begin() as c:                     # candidates need the F1 championship (search.add_candidate)
        c.execute(text("INSERT INTO sports (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
        c.execute(text("INSERT INTO leagues (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
        c.execute(text("""INSERT INTO competitions (code, name, league_id, sport_id)
                          SELECT 'f1_wdc', 'F1', l.id, s.id FROM leagues l, sports s WHERE l.code = 'f1' AND s.code = 'f1'
                          ON CONFLICT DO NOTHING"""))
    for name in ("ada_one", "ada_two"):
        app_db._signup_hits.clear()
        assert TestClient(app_db.app).post("/signup", data=dict(GOOD, username=name, email=f"{name}@example.com"),
                                           follow_redirects=False).status_code == 303
    with get_engine().connect() as c:
        ids = [c.execute(text("SELECT id FROM users WHERE username = :u"), dict(u=n)).scalar() for n in ("ada_one", "ada_two")]
        names = [PF.of_user(c, i)["name"] for i in ids]
    assert ids[1] == ids[0] + 1
    taker = {PF.PROFILES[code]["name"] for code in PF.TAKER_TOP}
    assert names[0] != names[1] and set(names) <= taker
    assert names == [PF.PROFILES[PF.TAKER_TOP[i % len(PF.TAKER_TOP)]]["name"] for i in ids]


@pytest.mark.parametrize("change, msg", [(dict(username="ADA_LOVELACE"), "taken"), (dict(username="admin"), "reserved"),
                                         (dict(password="short", confirm="short"), "at least"),
                                         (dict(confirm="something else"), "match"),
                                         (dict(adult=""), "18"), (dict(email=""), "valid email"),
                                         (dict(email="ada at example"), "valid email"),
                                         (dict(username="ada_two", email="ADA@example.com "), "already on an account")])
def test_signup_refusals(app_db, change, msg):
    client = TestClient(app_db.app)
    if msg in ("taken", "already on an account"):
        assert client.post("/signup", data=GOOD, follow_redirects=False).status_code == 303
        client = TestClient(app_db.app)
    r = client.post("/signup", data=dict(GOOD, **change), follow_redirects=False)
    assert r.status_code == 400 and msg in r.text
    assert GOOD["password"] not in r.text                                  # the password is never echoed back


def test_signup_is_rate_limited_and_honeypotted(app_db):
    client = TestClient(app_db.app)
    assert client.post("/signup", data=dict(GOOD, website="x")).status_code == 400
    for _ in range(10):                                   # the honeypot hit above doesn't count
        assert client.post("/signup", data=dict(GOOD, adult="")).status_code == 400
    assert client.post("/signup", data=GOOD).status_code == 429


def test_admin_reset_shows_a_one_time_password_and_remove(app_db):
    client, csrf = _admin(app_db)
    page = client.get("/admin/users").text
    assert "Fantasy bucks" in page and "scrypt$" not in page
    from sqlalchemy import text
    from racinglines.db.config import get_engine
    with get_engine().connect() as c:
        uid = c.execute(text("SELECT id FROM users WHERE username = 'taker'")).scalar()
    r = client.post(f"/admin/users/{uid}/reset-password", data=dict(csrf_token=csrf))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    temp = re.search(r'<p class="onetime">([^<]+)</p>', r.text).group(1)
    assert f"Username: taker\nTemporary password: {temp}" in r.text and 'id="onetime-copy"' in r.text  # the form email
    assert temp not in client.get("/admin/users").text                    # shown once
    fresh = TestClient(app_db.app)
    assert fresh.post("/login", data=dict(username="taker", password="password"),
                      follow_redirects=False).headers["location"].startswith("/login")   # old one is gone
    assert fresh.post("/login", data=dict(username="taker", password=temp),
                      follow_redirects=False).headers["location"] == "/markets"
    assert "can&#39;t be removed" in client.post(f"/admin/users/{uid}/delete", data=dict(csrf_token=csrf)).text  # demo login
    TestClient(app_db.app).post("/signup", data=GOOD)
    with get_engine().connect() as c:
        ada = c.execute(text("SELECT id FROM users WHERE username = 'ada_lovelace'")).scalar()
    assert "Removed ada_lovelace" in client.post(f"/admin/users/{ada}/delete", data=dict(csrf_token=csrf)).text
    assert _balance("ada_lovelace") is None                                # its ledger rows went with it


def test_cli(app_db, capsys):
    from racinglines.cli import users as CLI
    assert CLI.main(["add", "carol", "--role", "pro"]) == 0
    temp = capsys.readouterr().out.rsplit(": ", 1)[1].strip()
    from racinglines.db.config import get_session
    from racinglines.web import users as U
    with get_session() as s:
        assert U.authenticate(s, "carol", temp)
    assert CLI.main(["list"]) == 0 and "carol" in capsys.readouterr().out
    assert CLI.main(["reset-password", "carol"]) == 0
    with get_session() as s:
        assert not U.authenticate(s, "carol", temp)
    assert CLI.main(["remove", "carol"]) == 0 and float(_balance("carol") or 0) == 0


def test_signup_stores_the_email_and_older_accounts_sign_in_without_one(app_db):
    """New sign-ups need an email (owner, 2026-10-08), kept lower-cased in users.prefs.email; accounts made before
    have none and still sign in."""
    from sqlalchemy import text
    from racinglines.db.config import get_engine
    assert TestClient(app_db.app).post("/signup", data=GOOD, follow_redirects=False).status_code == 303
    with get_engine().connect() as c:
        assert c.execute(text("SELECT prefs->>'email' FROM users WHERE username = 'ada_lovelace'")).scalar() == "ada@example.com"
        assert c.execute(text("SELECT prefs->>'email' FROM users WHERE username = 'taker'")).scalar() is None
    r = TestClient(app_db.app).post("/login", data=dict(username="taker", password="password"), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/markets"


def test_admin_creates_a_user_from_the_one_password_field(app_db):
    """The admin form has one password field: it used to be checked against an empty confirmation and always failed
    with "The two passwords don't match" (owner report, 2026-10-08)."""
    client, csrf = _admin(app_db)
    page = client.get("/admin/users").text
    assert 'autocomplete="new-password"' in page and "Password (10+ chars)" in page
    r = client.post("/admin/users", data=dict(csrf_token=csrf, username="New_Pro", display_name="", role="pro",
                                              password="a long enough password"), follow_redirects=True)
    assert "Created pro new_pro" in r.text
    r = client.post("/admin/users", data=dict(csrf_token=csrf, username="newer", display_name="", role="basic",
                                              password="short"), follow_redirects=True)
    assert "at least 10" in r.text
