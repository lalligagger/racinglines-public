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
    page = client.get("/").text
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
    page = client.get("/").text                           # the landing page links to sign-up once; no popup (2026-10-08)
    assert 'id="site-notice"' not in page and page.count('href="/signup"') == 1
    assert 'href="/forgot"' in client.get("/signin").text           # the sign-in form has its own page (2026-10-12)
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


def test_signups_start_with_no_strategy(app_db):
    """No default strategy until the user picks one (owner, 2026-10-11 22:04Z; replaces the TAKER_TOP round-robin)."""
    from sqlalchemy import text
    from racinglines.db.config import get_engine
    from racinglines.pipelines import profiles as PF
    assert TestClient(app_db.app).post("/signup", data=GOOD, follow_redirects=False).status_code == 303
    with get_engine().connect() as c:
        uid = c.execute(text("SELECT id FROM users WHERE username = 'ada_lovelace'")).scalar()
        assert PF.of_user(c, uid) is None
        assert c.execute(text("SELECT count(*) FROM paper_positions WHERE user_id = :u"), dict(u=uid)).scalar() == 0


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
                      follow_redirects=False).headers["location"].startswith("/signin")   # old one is gone
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


@pytest.mark.quick
def test_demo_accounts_see_the_signup_notice_and_link(monkeypatch):
    """The demo accounts (maker / taker) get the sign-up popup and a Sign up link in the top bar (owner, 2026-10-11);
    registered accounts and the signed-out landing page get neither, and nobody gets it while sign-up is off."""
    from types import SimpleNamespace

    from racinglines.web import app as A
    notice = A.templates.env.get_template("_site_notice.html")

    def page(user, path="/markets"):
        return notice.render(user=user, request=SimpleNamespace(url=SimpleNamespace(path=path, query="")))

    maker, pro = dict(username="maker", role="pro"), dict(username="someone", role="pro")
    monkeypatch.setenv("RACINGLINES_SIGNUP", "1")
    assert 'data-signup="1"' in page(maker) and '<a href="/signup">signups</a>' in page(maker)
    assert 'id="site-notice"' not in page(maker, "/signup")            # not on the sign-up page itself
    assert 'id="site-notice"' not in page(pro) and 'id="site-notice"' not in page(None, "/login")
    top = A.templates.env.get_template("base.html")
    req = SimpleNamespace(url=SimpleNamespace(path="/markets", query=""))
    demo_bar = top.render(user=maker, request=req, trading=None)
    assert 'class="signup-link" href="/signup"' in demo_bar and 'href="/settings"' not in demo_bar
    own_bar = top.render(user=pro, request=req, trading=None)
    assert 'href="/settings"' in own_bar and "signup-link" not in own_bar
    monkeypatch.setenv("RACINGLINES_SIGNUP", "0")
    assert 'id="site-notice"' not in page(maker) and "signup-link" not in top.render(user=maker, request=req, trading=None)


def test_reset_fantasy_keeps_the_demo_accounts(app_db, capsys):
    """Owner, 2026-10-11: every account but maker/taker back to one 1,000 grant and no trading history."""
    from sqlalchemy import text
    from racinglines.cli import users as CLI
    from racinglines.db.config import get_engine
    with get_engine().begin() as c:
        ids = dict(c.execute(text("SELECT username, id FROM users")).all())
        for name in ("boss", "taker"):
            c.execute(text("""INSERT INTO paper_positions (user_id, event_key, market_key, kind, yes_shares, no_shares, cash,
                                                           venue) VALUES (:u, '2026-17', 'm1', 'race_win', 1, 0, -0.5,
                                                           'polymarket')"""), dict(u=ids[name]))
        c.execute(text("INSERT INTO accounts.fantasy_ledger (user_id, amount, reason) VALUES (:u, -40, 'stake')"),
                  dict(u=ids["boss"]))
        for name in ("boss", "taker"):                                # a profile on two venues, and an unrelated pref
            c.execute(text("""UPDATE users SET prefs = coalesce(prefs, '{}'::jsonb) || '{"strategy_profile": {"name": "A"},
                              "strategy_profile_kalshi": {"name": "K"}, "email": "x@example.com"}'::jsonb WHERE id = :u"""),
                      dict(u=ids[name]))
    assert CLI.main(["reset-fantasy"]) == 0                           # dry run: counts, writes nothing
    out = capsys.readouterr().out
    assert "would" in out and "dry run: would reset 1 accounts" in out
    assert float(_balance("boss")) == 960
    assert CLI.main(["reset-fantasy", "--apply", "--note", "reset test"]) == 0
    with get_engine().connect() as c:
        pos = dict(c.execute(text("SELECT user_id, count(*) FROM paper_positions GROUP BY user_id")).all())
        rows = c.execute(text("SELECT amount, reason, note FROM accounts.fantasy_ledger WHERE user_id = :u"),
                         dict(u=ids["boss"])).all()
    assert pos == {ids["taker"]: 1}                                   # the demo taker's history is untouched
    assert [(float(a), r, n) for a, r, n in rows] == [(1000.0, "signup_grant", "reset test")]
    assert float(_balance("taker")) == 1000
    with get_engine().connect() as c:
        prefs = dict(c.execute(text("SELECT username, prefs FROM users")).all())
    assert prefs["boss"] == {"email": "x@example.com"}                 # no strategy left, other prefs kept
    assert set(prefs["taker"]) >= {"strategy_profile", "strategy_profile_kalshi"}


def test_accounts_without_an_email_get_the_add_email_popup(app_db):
    """A registered account with no email gets the add-email popup on app pages (not Settings) until it saves one
    (owner, 2026-10-11). The save runs the sign-up checks: a valid address, on no other account."""
    from sqlalchemy import text
    from racinglines.db.config import get_engine
    client, csrf = _admin(app_db)
    page = client.get("/admin/users").text
    assert 'action="/settings/email"' in page and 'data-key="email"' in page
    assert "confirm a reset request" in page and "fantasy update" in page and "Skip for now" in page   # why we ask, and it's skippable
    assert 'action="/settings/email"' not in client.get("/settings").text
    with get_engine().begin() as c:
        c.execute(text("""UPDATE users SET prefs = coalesce(prefs, '{}'::jsonb) || '{"email": "taken@example.com"}'::jsonb
                          WHERE username = 'taker'"""))
    for bad, msg in (("not-an-email", "valid email"), ("Taken@Example.com", "already on an account")):
        r = client.post("/settings/email", data=dict(csrf_token=csrf, email=bad, next="/admin/users"))
        assert r.status_code == 400 and msg in r.text
    r = client.post("/settings/email", data=dict(csrf_token=csrf, email=" Boss@Example.com ", next="//evil.example"),
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/markets"     # off-site targets fall back
    with get_engine().connect() as c:
        assert c.execute(text("SELECT prefs->>'email' FROM users WHERE username = 'boss'")).scalar() == "boss@example.com"
    assert 'action="/settings/email"' not in client.get("/admin/users").text



def test_the_taker_demo_account_still_signs_in_by_name(app_db):
    """The basic demo has no button any more, but the taker login is kept (owner, 2026-10-12)."""
    from racinglines.web import app as A
    r = TestClient(A.app).post("/login", data=dict(username="taker", password="password"), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/markets"
