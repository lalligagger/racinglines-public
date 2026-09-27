"""Shared fixtures: pinned inputs (tests/fixtures, built by scripts/fetch_test_fixtures.py) and a throwaway test database."""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

def pytest_configure(config):
    """Fail fast, with the fix, when run under the wrong interpreter or without the dependencies."""
    fix = ("Use the project environment:  source .venv/bin/activate  "
           "(or create it: python3.14 -m venv .venv && pip install -r requirements.txt && pip install -e .)")
    if sys.version_info < (3, 11):
        pytest.exit(f"Python {sys.version.split()[0]} at {sys.executable} is too old (need 3.11+). {fix}", returncode=4)
    missing = []
    for mod in ("sqlalchemy", "pyarrow", "pandas", "fastf1", "fastapi", "httpx"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        pytest.exit(f"Missing packages: {', '.join(missing)} ({sys.executable}). {fix}", returncode=4)


def need(*parts):
    """Skip (not fail) when the test fixtures haven't been downloaded yet."""
    path = FIX.joinpath(*parts)
    if not path.exists():
        pytest.skip(f"test fixtures missing ({path.relative_to(ROOT)}): run python scripts/fetch_test_fixtures.py")
    return path


TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines_test")


@pytest.fixture(scope="session")
def f1_frames():
    need("f1", "res.parquet")
    res = pd.read_parquet(FIX / "f1" / "res.parquet")
    res["extra"] = res["extra"].map(json.loads)
    laps = pd.read_parquet(FIX / "f1" / "laps.parquet")
    prof = pd.read_parquet(FIX / "f1" / "prof.parquet")
    prof["features"] = prof["features"].map(json.loads)
    return res, laps, prof


@pytest.fixture(scope="session")
def f1_meas(f1_frames):
    from racinglines.models.position_sim import pricing as run
    return run.Measurements.from_frames(*f1_frames)


@pytest.fixture(scope="session")
def f1_hist(f1_meas):
    from racinglines.models.position_sim import pricing as run
    return run.history(f1_meas)


@pytest.fixture(scope="session")
def f1_schedule():
    need("f1", "schedule_2026.json")
    s = pd.read_json(FIX / "f1" / "schedule_2026.json", orient="records")
    s["date"] = pd.to_datetime(s["date"]).dt.tz_localize(None)
    return s


@pytest.fixture(scope="session")
def test_engine():
    """A fresh database built from the migrations (dropped and re-created each session)."""
    url = TEST_DB
    name = url.rsplit("/", 1)[1]
    admin = url.rsplit("/", 1)[0] + "/postgres"
    try:
        eng = create_engine(admin, isolation_level="AUTOCOMMIT")
        with eng.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            c.execute(text(f'CREATE DATABASE "{name}"'))
        eng.dispose()
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"no Postgres for the test database: {ex}")
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    e = create_engine(url, future=True)
    yield e
    e.dispose()


def replay_fixture():
    from racinglines.markets.strategies import maker_replay as R
    meta = json.loads(need("market", "replay.json").read_text())
    arr = np.load(FIX / "market" / "replay.npz")
    markets = []
    for i, m in enumerate(meta["markets"]):
        markets.append(R.Market(cond=m["cond"], kind=m["kind"], subject=m["subject"], question=m["question"],
                                fairs={int(k): v for k, v in m["fairs"].items()}, outcome=m["outcome"],
                                mid_ts=arr[f"{i}_mid_ts"], mid_px=arr[f"{i}_mid_px"], tr_ts=arr[f"{i}_tr_ts"],
                                tr_px=arr[f"{i}_tr_px"], tr_sz=arr[f"{i}_tr_sz"], tr_buy=arr[f"{i}_tr_buy"]))
    stages = [dict(run_id=int(s["run_id"]), start=int(s["start"]), end=int(s["end"]),
                   session_end=s["session_end"] in (True, "True"))
              for s in meta["stages"]]
    return dict(markets=markets, stages=stages)


def season_fixture():
    from racinglines.markets.strategies import season as SS
    meta = json.loads(need("market", "season.json").read_text())
    arr = np.load(FIX / "market" / "season.npz")
    markets = {}
    for i, m in enumerate(meta["markets"]):
        markets[m["key"]] = SS.SeasonMarket(
            key=m["key"], kind=m["kind"], subject=m["subject"], cost=m["cost"], outcome=m["outcome"],
            closed_at=pd.Timestamp(m["closed_at"]) if m["closed_at"] else None,
            ts=pd.DatetimeIndex(pd.to_datetime(arr[f"{i}_ts"], utc=True)).to_numpy(dtype=object), px=arr[f"{i}_px"])
    decisions = [dict(label=d["label"], t=pd.Timestamp(d["t"]), fairs=d["fairs"]) for d in meta["decisions"]]
    return markets, decisions


def weekend_fixture():
    raw = json.loads(need("market", "weekends.json").read_text())
    for markets in raw.values():
        for m in markets:
            for s in m["stages"]:
                s["t"] = pd.Timestamp(s["t"])
    return raw
