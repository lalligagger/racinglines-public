"""`vm.sh staging refresh` (racinglines/db/refresh.py): production's data tables copied into staging again, staging's
own state kept. Two throwaway databases built from the migrations stand in for production and staging."""
import os
import re
from pathlib import Path

import pytest
from conftest import TEST_DB
from sqlalchemy import create_engine, text

from racinglines.db import refresh as R

ROOT = Path(__file__).resolve().parent.parent
VM_SH = (ROOT / "scripts/deploy/vm.sh").read_text()


def _db(name):
    base = TEST_DB.rsplit("/", 1)[0]
    admin = create_engine(base + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
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
        prod_url, stg_url = _db("racinglines_refresh_prod"), _db("racinglines_refresh_staging")
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"no Postgres for the test databases: {ex}")
    prod, stg = R.connect(prod_url), R.connect(stg_url)
    yield prod, stg
    prod.close()
    stg.close()


def sql(c, *stmts):
    for s in stmts:
        c.execute(s)


def test_refresh_brings_production_data_and_keeps_staging_state(dbs):
    prod, stg = dbs
    seed = ("INSERT INTO sports (code, name) VALUES ('f1', 'Formula 1')",
            "INSERT INTO leagues (code, name) VALUES ('fia', 'FIA')",
            "INSERT INTO competitions (code, name, league_id, sport_id) VALUES ('f1_wdc', 'F1', 1, 1)",
            "INSERT INTO model_runs (competition_id, model, kind) SELECT 1, 'm', 'forecast' FROM generate_series(1, 5)")
    sql(prod, *seed)
    sql(stg, *seed)                                  # staging: production as it was when copied
    # production moves on; staging makes its own run (an id production also uses) and its own accounts
    sql(prod, "INSERT INTO model_runs (competition_id, model, kind) SELECT 1, 'm', 'live' FROM generate_series(1, 3)",
        "INSERT INTO market_price_history (token_id, ts, price) VALUES ('tok', now(), 0.4)")
    sql(stg, "INSERT INTO model_runs (competition_id, model, kind) VALUES (1, 'c8', 'backtest')",
        "INSERT INTO users (username, role, password_hash) VALUES ('alpha1', 'user', 'x')",
        "INSERT INTO paper_positions (user_id, event_key, market_key, kind, yes_shares, no_shares, cash) "
        "VALUES (1, 'e', 'm', 'win', 1, 0, 0)")

    R.run(R.connect(prod.info.dsn, read_only=True), stg)
    assert R.one(stg, "SELECT count(*) FROM model_runs") == 8
    assert R.one(stg, "SELECT count(*) FROM market_price_history") == 1
    assert R.one(stg, "SELECT count(*) FROM users WHERE username = 'alpha1'") == 1   # staging's accounts and positions stay
    assert R.one(stg, "SELECT count(*) FROM paper_positions") == 1
    assert R.one(prod, "SELECT count(*) FROM users WHERE username = 'alpha1'") == 0  # production only read

    # after the first refresh staging's own rows take ids from OFFSET up and survive the next refresh; a reference
    # row staging seeded first becomes production's once production has it
    run_id = R.one(stg, "INSERT INTO model_runs (competition_id, model, kind) VALUES (1, 'lab', 'backtest') RETURNING id")
    assert run_id >= R.OFFSET
    sql(stg, "INSERT INTO sports (code, name) VALUES ('motogp', 'MotoGP')",
        "INSERT INTO competitions (code, name, league_id, sport_id) "
        "SELECT 'motogp', 'MotoGP', 1, id FROM sports WHERE code = 'motogp'")
    sql(prod, "INSERT INTO sports (code, name) VALUES ('nascar', 'NASCAR'), ('motogp', 'MotoGP')",
        "INSERT INTO model_runs (competition_id, model, kind) VALUES (1, 'm', 'new')")

    R.run(R.connect(prod.info.dsn, read_only=True), stg)
    assert R.one(stg, "SELECT model FROM model_runs WHERE id = %s", (run_id,)) == "lab"
    assert R.one(stg, "SELECT count(*) FROM model_runs WHERE id < %s", (R.OFFSET,)) == 9
    motogp = R.one(prod, "SELECT id FROM sports WHERE code = 'motogp'")
    assert R.one(stg, "SELECT id FROM sports WHERE code = 'motogp'") == motogp
    assert R.one(stg, "SELECT sport_id FROM competitions WHERE code = 'motogp'") == motogp


def test_refresh_refuses_anything_but_staging():
    with pytest.raises(SystemExit):
        R.urls({"DATABASE_URL": "postgresql+psycopg://u:p@h:5433/racinglines", "RACINGLINES_ENV": "staging"})
    with pytest.raises(SystemExit):
        R.urls({"DATABASE_URL": "postgresql+psycopg://u:p@h:5433/racinglines_staging"})
    prod, stg = R.urls({"DATABASE_URL": "postgresql+psycopg://u:p@h:5433/racinglines_staging", "RACINGLINES_ENV": "staging"})
    assert prod.endswith("/racinglines") and stg.endswith("/racinglines_staging")


def test_shared_tables_never_include_accounts_or_app_state():
    for t in ("users", "activity_log", "user_email_prefs", "jobs", "strategy_signals", "paper_positions", "orders",
              "house_markets", "house_bets", "alembic_version"):
        assert t not in R.SHARED, t


def test_vm_sh_refresh_backs_up_staging_and_only_reads_production():
    block = VM_SH.split("\n      refresh)\n", 1)[1].split("\n        ;;\n", 1)[0]
    code = "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))
    assert "/etc/racinglines-staging.env" in code and "/etc/racinglines.env" not in code
    assert re.search(r"pg_dump .* racinglines_staging \|", code)          # staging backed up before the refresh
    assert code.index("pg_dump") < code.index("$m run")
    assert "pg_dump --no-owner --no-privileges -U racinglines racinglines |" not in code
    assert "systemctl" not in code                                        # no production timer or service touched


def test_staging_never_archives(monkeypatch):
    from racinglines.markets import store as MS
    monkeypatch.setattr(os, "environ", {**os.environ, "RACINGLINES_ENV": "staging"})
    with pytest.raises(SystemExit):
        MS.archive(None, "prices")
