"""
Beta sign-up and the fantasy-bucks ledger.

Self-serve accounts (RACINGLINES_SIGNUP=1, off by default): /signup takes a username, a password and a tier (pro or
basic) and creates a `users` row (the password as a scrypt hash, web/users.py) plus a SIGNUP_GRANT credit in the
ledger, in one transaction, then signs the person in.

The ledger lives in its own Postgres schema, `accounts`, apart from the market data in `public`: one row per credit
or debit (`amount`, `reason`), never updated, so a balance is a sum and every change has a history. No wallet or
bankroll logic reads it yet; it only has to be right from the first sign-up.

The schema is NOT an alembic migration, because a deploy runs `alembic upgrade head` and deploys never change the
VM's database (owner rule, 2026-10-01). `racinglines users setup` creates it (idempotent; on the VM through
`vm.sh accounts`, which backs up first). Until it exists, sign-up says it isn't open yet and nothing else changes.
"""

import re
import secrets

from sqlalchemy import text

SIGNUP_GRANT = 1000                       # fantasy bucks every new account starts with
GRANT_REASON = "signup_grant"

DDL = (
    "CREATE SCHEMA IF NOT EXISTS accounts",
    """CREATE TABLE IF NOT EXISTS accounts.fantasy_ledger (
        id         bigserial PRIMARY KEY,
        user_id    integer NOT NULL REFERENCES public.users (id) ON DELETE CASCADE,
        amount     numeric(14, 2) NOT NULL,
        reason     varchar(40) NOT NULL,
        note       text,
        created_at timestamptz NOT NULL DEFAULT now())""",
    "CREATE INDEX IF NOT EXISTS fantasy_ledger_user ON accounts.fantasy_ledger (user_id)",
    # one signup grant per account, however often setup or sign-up runs
    f"""CREATE UNIQUE INDEX IF NOT EXISTS fantasy_ledger_one_grant ON accounts.fantasy_ledger (user_id)
        WHERE reason = '{GRANT_REASON}'""",
)

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,29}$")
RESERVED = {"admin", "administrator", "root", "system", "staff", "support", "hello", "help", "racinglines",
            "maker", "taker", "pro", "basic", "demo", "polymarket-takers", "kalshi", "polymarket", "null", "none"}
PASSWORD_MIN, PASSWORD_MAX = 10, 128


def setup(engine, backfill=True):
    """Create the accounts schema and ledger (idempotent). backfill: every active account without a signup grant
    gets one now, so every user starts with SIGNUP_GRANT. Returns the number of grants added."""
    with engine.begin() as c:
        for stmt in DDL:
            c.execute(text(stmt))
        if not backfill:
            return 0
        return c.execute(text(f"""
            INSERT INTO accounts.fantasy_ledger (user_id, amount, reason, note)
            SELECT u.id, :g, '{GRANT_REASON}', 'backfill at setup' FROM users u
            WHERE u.active AND NOT EXISTS (SELECT 1 FROM accounts.fantasy_ledger l
                                           WHERE l.user_id = u.id AND l.reason = '{GRANT_REASON}')"""),
                         dict(g=SIGNUP_GRANT)).rowcount


def ready(conn):
    """True when the ledger exists (setup has run)."""
    return conn.execute(text("SELECT to_regclass('accounts.fantasy_ledger') IS NOT NULL")).scalar()


def grant(conn, user_id, amount=SIGNUP_GRANT, reason=GRANT_REASON, note=None):
    conn.execute(text("INSERT INTO accounts.fantasy_ledger (user_id, amount, reason, note) VALUES (:u, :a, :r, :n)"),
                 dict(u=user_id, a=amount, r=reason, n=note))


def balances(conn):
    """{user_id: balance} for every account with a ledger row; {} before setup."""
    if not ready(conn):
        return {}
    rows = conn.execute(text("SELECT user_id, sum(amount) FROM accounts.fantasy_ledger GROUP BY user_id")).all()
    return {u: float(b) for u, b in rows}


def check_username(conn, username):
    """'' if the (lower-cased) username is free and valid, else the message to show."""
    if not USERNAME_RE.match(username):
        return "Usernames are 3 to 30 characters: lower-case letters, digits, '.', '_' or '-', starting with a letter or digit."
    if username in RESERVED:
        return "That username is reserved. Please pick another."
    if conn.execute(text("SELECT 1 FROM users WHERE lower(username) = :u"), dict(u=username)).first():
        return "That username is taken. Please pick another."
    return ""


def check_password(password, confirm, username):
    if len(password) < PASSWORD_MIN:
        return f"Passwords need at least {PASSWORD_MIN} characters."
    if len(password) > PASSWORD_MAX:
        return f"Passwords can be at most {PASSWORD_MAX} characters."
    if username and username in password.lower():
        return "Your password can't contain your username."
    if password != confirm:
        return "The two passwords don't match."
    return ""


def temp_password():
    """A one-time password for an admin reset: shown to the admin once, never stored or logged in clear."""
    return secrets.token_urlsafe(12)
