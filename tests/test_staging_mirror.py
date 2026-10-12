"""Staging as a live copy of production (racinglines/db/mirror.py): two throwaway databases built from the
migrations stand in for production and staging, in one Postgres cluster as on the VM. Needs wal_level=logical on the
test server (skipped otherwise), plus static checks of vm.sh's mirror commands."""
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
from conftest import TEST_DB
from sqlalchemy import create_engine, text

from racinglines.db import mirror as M

ROOT = Path(__file__).resolve().parent.parent
VM_SH = (ROOT / "scripts/deploy/vm.sh").read_text()


def _db(name):
    base = TEST_DB.rsplit("/", 1)[0]
    admin = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        for row in c.execute(text("SELECT subname FROM pg_subscription s JOIN pg_database d ON d.oid = s.subdbid "
                                  "WHERE d.datname = :n"), {"n": name}):
            raise RuntimeError(f"{name} still has subscription {row[0]}")
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"{base}/{name}")
    command.upgrade(cfg, "head")
    return f"{base}/{name}".replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def dbs():
    try:
        prod_url = _db("racinglines_mirror_prod")
        prod = M.connect(prod_url)
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"no Postgres for the test databases: {ex}")
    if M.one(prod, "SHOW wal_level") != "logical":
        pytest.skip("the test Postgres needs wal_level=logical")
    stg = M.connect(_db("racinglines_mirror_staging"))
    u = urlparse(prod_url)
    old = M.PUBLISHER
    M.PUBLISHER = f"host={u.hostname} port={u.port or 5432} dbname={u.path.lstrip('/')}"
    yield prod, stg
    M.turn_off(prod, stg)
    M.PUBLISHER = old
    prod.close()
    stg.close()


def sql(c, *stmts):
    for s in stmts:
        c.execute(s)


def until(check, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.5)
    return False


def test_mirror_follows_production_and_keeps_staging_rows(dbs):
    prod, stg = dbs
    seed = ("INSERT INTO sports (code, name) VALUES ('f1', 'Formula 1')",
            "INSERT INTO leagues (code, name) VALUES ('fia', 'FIA')",
            "INSERT INTO competitions (code, name, league_id, sport_id) VALUES ('f1_wdc', 'F1', 1, 1)",
            "INSERT INTO model_runs (competition_id, model, kind) SELECT 1, 'm', 'forecast' FROM generate_series(1, 5)")
    sql(prod, *seed)
    sql(stg, *seed)                                  # staging: production as it was when copied
    sql(prod, "INSERT INTO model_runs (competition_id, model, kind) SELECT 1, 'm', 'live' FROM generate_series(1, 3)")
    sql(stg, "INSERT INTO model_runs (competition_id, model, kind) VALUES (1, 'c8', 'backtest')",   # collides on id 6
        "INSERT INTO users (username, role, password_hash) VALUES ('alpha1', 'user', 'x')")

    M.turn_on(M.connect(prod.info.dsn), stg, "data")
    assert until(lambda: M.one(stg, "SELECT count(*) FROM model_runs") == 8)
    assert M.one(stg, "SELECT count(*) FROM users WHERE username = 'alpha1'") == 1   # data scope: accounts stay
    assert M.status(prod, stg)

    # production keeps going: it arrives without a refresh; staging's own rows take ids from OFFSET up
    sql(prod, "INSERT INTO market_price_history (token_id, ts, price) VALUES ('tok', now(), 0.4)",
        "UPDATE model_runs SET kind = 'final' WHERE id = 8")
    run_id = M.one(stg, "INSERT INTO model_runs (competition_id, model, kind) VALUES (1, 'lab', 'backtest') RETURNING id")
    assert run_id >= M.OFFSET
    assert until(lambda: M.one(stg, "SELECT kind FROM model_runs WHERE id = 8") == "final")
    assert M.one(stg, "SELECT count(*) FROM market_price_history") == 1

    # staging seeds a reference row first; production's later copy would stop replication until repair adopts it
    sql(stg, "INSERT INTO sports (code, name) VALUES ('motogp', 'MotoGP')",
        "INSERT INTO competitions (code, name, league_id, sport_id) SELECT 'motogp', 'MotoGP', 1, id FROM sports "
        "WHERE code = 'motogp'")
    sql(prod, "INSERT INTO sports (code, name) VALUES ('nascar', 'NASCAR'), ('motogp', 'MotoGP')",
        "INSERT INTO model_runs (competition_id, model, kind) VALUES (1, 'm', 'after')")
    assert not until(lambda: M.one(stg, "SELECT count(*) FROM model_runs WHERE kind = 'after'") == 1, 4)
    assert M.repair(prod, stg) == 1
    motogp = M.one(prod, "SELECT id FROM sports WHERE code = 'motogp'")
    assert until(lambda: M.one(stg, "SELECT count(*) FROM model_runs WHERE kind = 'after'") == 1)
    assert M.one(stg, "SELECT id FROM sports WHERE code = 'motogp'") == motogp
    assert M.one(stg, "SELECT sport_id FROM competitions WHERE code = 'motogp'") == motogp
    assert M.one(stg, "SELECT model FROM model_runs WHERE id = %s", (run_id,)) == "lab"
    assert M.one(prod, "SELECT count(*) FROM users WHERE username = 'alpha1'") == 0  # production only read

    # widening the scope adds accounts; staging's own account ids stay clear of production's
    sql(prod, "INSERT INTO users (username, role, password_hash) VALUES ('prod_user', 'user', 'x')")
    M.turn_on(M.connect(prod.info.dsn), stg, "accounts")
    assert until(lambda: M.one(stg, "SELECT count(*) FROM users WHERE username = 'prod_user'") == 1)
    assert M.one(stg, "INSERT INTO users (username, role, password_hash) VALUES ('stg_test', 'user', 'x') "
                      "RETURNING id") >= M.OFFSET
    assert "public.jobs" not in M.subscribed(stg) and "public.alembic_version" not in M.subscribed(stg)


def test_mirror_refuses_anything_but_staging():
    with pytest.raises(SystemExit):
        M.urls({"DATABASE_URL": "postgresql+psycopg://u:p@h:5433/racinglines", "RACINGLINES_ENV": "staging"})
    with pytest.raises(SystemExit):
        M.urls({"DATABASE_URL": "postgresql+psycopg://u:p@h:5433/racinglines_staging"})
    prod, stg = M.urls({"DATABASE_URL": "postgresql+psycopg://u:p@h:5433/racinglines_staging", "RACINGLINES_ENV": "staging"})
    assert prod.endswith("/racinglines") and stg.endswith("/racinglines_staging")


def test_scopes():
    assert not set(M.STAGING_OWN) & set(M.DATA + M.ACCOUNTS)
    for t in ("public.users", "accounts.fantasy_ledger", "public.paper_positions", "public.jobs"):
        assert t not in M.DATA
    assert "public.jobs" in M.STAGING_OWN     # staging's worker must never run production's queued jobs


def block(name):
    return VM_SH.split(f"\n  {name})\n", 1)[1].split("\n    ;;\n", 1)[0]


def test_vm_sh_mirror_backs_up_staging_first_and_never_touches_production_rows():
    code = "\n".join(line for line in block("mirror").splitlines() if not line.lstrip().startswith("#"))
    assert "/etc/racinglines-staging.env" in code and "/etc/racinglines.env" not in code
    assert code.index("pg_dump --no-owner --no-privileges -U racinglines racinglines_staging") < code.index('m "on')
    assert "systemctl stop" not in code and "$PAUSED" not in code


def test_vm_sh_postgres_logical_pauses_and_resumes_timers():
    code = block("postgres")
    assert "wal_level = logical" in code and "max_slot_wal_keep_size" in code
    assert code.index("systemctl stop") < code.index("docker compose restart db")
    assert "trap resume EXIT" in code


def test_staging_never_archives(monkeypatch):
    from racinglines.markets import store as MS
    monkeypatch.setattr(os, "environ", {**os.environ, "RACINGLINES_ENV": "staging"})
    with pytest.raises(SystemExit):
        MS.archive(None, "prices")
