#!/usr/bin/env python3
"""
Download the inputs the regression suite needs, from the original public sources,
and build tests/fixtures/ with this repo's own pipeline. Nothing is committed to git:
fixtures, raw downloads and golden baselines are all ignored.

    python scripts/fetch_test_fixtures.py            # both sports
    python scripts/fetch_test_fixtures.py --f1       # Formula 1 only
    python scripts/fetch_test_fixtures.py --mtb      # UCI downhill only

Needs Postgres (docker compose up -d); a throwaway database `racinglines_fixtures` is
(re)created from the migrations ($FIXTURE_DATABASE_URL to override). Raw downloads go
to tests/fixtures/_work/ (FastF1 is rate limited to 500 calls/hour; the F1 part takes
up to an hour on a cold cache).

    F1   FastF1: 2026 rounds F1_ROUNDS (qualifying, sprint, race, practice)
         Polymarket: Baku and Monza race markets (prices, trades), championship prices
         -> tests/fixtures/f1/{res,laps,prof}.parquet, schedule_2026.json, raw/2026/15_*
            tests/fixtures/market/{replay,weekends,season}.*
    MTB  ChronoRace: 2025-2026 World Cup DH, Elite and Junior men (MTB_EVENTS)
         -> tests/fixtures/mtb/*.md, tidy_2025_2026.parquet

Then: python -m pytest -m "not live"   (the first run writes your golden baseline)
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
WORK = FIX / "_work"
os.environ["RACINGLINES_DATA"] = str(WORK / "data")          # every racinglines path points into the scratch dir
sys.path.insert(0, str(ROOT))

FIXTURE_DB = os.environ.get("FIXTURE_DATABASE_URL",
                            "postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines_fixtures")
F1_YEAR, F1_ROUNDS = 2026, "6-15"
BAKU, MONZA = "2026-15", "2026-13"
BAKU_CUTOFFS = ("2026-09-24T00:00", "2026-09-25T13:30", "2026-09-25T23:59")    # pre-quali, post-quali, overnight
REPLAY_MARKETS, SEASON_MARKETS = 12, 10
SEASON_END = "2026-09-26T18:00"            # fixed end of the championship price history
SIMS = 4000
MTB_EVENTS = ["20250516_mtb", "20250530_mtb", "20250605_mtb", "20250620_mtb", "20250703_mtb", "20250709_mtb",
              "20250821_mtb", "20250918_mtb", "20251003_mtb", "20251009_mtb", "20260501_mtb", "20260528_mtb",
              "20260611_mtb", "20260619_mtb", "20260703_mtb", "20260708_mtb", "20260821_mtb", "20260925_mtb"]
MTB_SAMPLE = ("20260821_mtb_dhi_elite-men.md", "20260821_mtb_dhi_junior-men.md")


def say(msg):
    print(msg, flush=True)


def fresh_db(url):
    """Drop and re-create the fixture database, then migrate it."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    name = url.rsplit("/", 1)[1]
    admin = create_engine(url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url, future=True)
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    with get_session(url) as s:
        seed(s)
        s.commit()
    return engine


# --- Formula 1 --------------------------------------------------------------------

def build_f1(engine):
    import numpy as np
    import pandas as pd

    from racinglines import paths
    from racinglines.db.config import get_session
    from racinglines.markets.polymarket.sync import sync
    from racinglines.markets.strategies import maker_replay as R
    from racinglines.models.position_sim import model as M
    from racinglines.models.position_sim import pricing as run
    from racinglines.pipelines import weekend_sweep as SW
    from racinglines.sources.fastf1 import fetch
    from racinglines.sources.fastf1.ingest import ingest

    say(f"F1: FastF1 sessions {F1_YEAR} rounds {F1_ROUNDS} (rate limited; resumable) ...")
    sys.argv = ["fetch", "--years", str(F1_YEAR), "--rounds", F1_ROUNDS, "--sessions", "Q,S,R,FP1,FP2,FP3,SQ"]
    fetch.main()
    with get_session(FIXTURE_DB) as s:
        say(f"F1: ingest {ingest(s, [F1_YEAR])}")

    d = FIX / "f1"
    d.mkdir(parents=True, exist_ok=True)
    res, laps, prof = M.load_frames(engine)
    res.assign(extra=res["extra"].map(lambda v: json.dumps(v, default=str, sort_keys=True))).to_parquet(d / "res.parquet", index=False)
    laps.to_parquet(d / "laps.parquet", index=False)
    prof.assign(features=prof["features"].map(lambda v: json.dumps(v, default=str, sort_keys=True))).to_parquet(
        d / "prof.parquet", index=False)
    schedule = run.upcoming_schedule(F1_YEAR)
    schedule.to_json(d / "schedule_2026.json", orient="records", date_format="iso")
    raw = d / "raw" / str(F1_YEAR)
    raw.mkdir(parents=True, exist_ok=True)
    for f in (paths.F1_RAW / str(F1_YEAR)).glob("15_*"):
        shutil.copy(f, raw / f.name)
    say(f"F1: model tables {len(res)} results, {len(laps)} laps, {len(prof)} profiles")

    say("F1: Polymarket markets (closed 2026 events) ...")
    with engine.connect() as c, get_session(FIXTURE_DB) as s:
        say(f"     {sync(s, c, F1_YEAR, include_closed=True)}")
    sched = SW.schedule(F1_YEAR, [int(k.split("-")[1]) for k in (MONZA, BAKU)])
    with engine.connect() as c, get_session(FIXTURE_DB) as s:
        SW.fetch_market_data(s, c, sched, fidelity=5, echo=say)

    meas = run.Measurements.load(engine)
    hist = run.history(meas)
    say("F1: Baku as-of diagnostics ...")
    diag_runs = []
    for cutoff in BAKU_CUTOFFS:
        _, summ, ex, _ = run.diagnostic(meas, hist, BAKU, pd.Timestamp(cutoff), n_sims=SIMS)
        diag_runs.append(run.save_diagnostic(FIXTURE_DB, BAKU, pd.Timestamp(cutoff), summ, ex, SIMS))
    with engine.connect() as c:
        ev = R.load_event(c, diag_runs)
    mks = sorted(ev["markets"], key=lambda m: (-len(m.tr_ts), m.cond))[:REPLAY_MARKETS]
    arrays, meta = {}, []
    for i, m in enumerate(mks):
        for f in ("mid_ts", "mid_px", "tr_ts", "tr_px", "tr_sz", "tr_buy"):
            arrays[f"{i}_{f}"] = getattr(m, f)
        meta.append(dict(cond=m.cond, kind=m.kind, subject=m.subject, question=m.question,
                         fairs={str(k): v for k, v in m.fairs.items()}, outcome=m.outcome))
    mdir = FIX / "market"
    mdir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(mdir / "replay.npz", **arrays)
    (mdir / "replay.json").write_text(json.dumps(dict(markets=meta, stages=ev["stages"], runs=ev["runs"]), default=str))
    say(f"F1: replay fixture {len(mks)} markets, {sum(len(m.tr_ts) for m in mks)} trades")

    say("F1: weekend sweep stages (Monza, Baku) ...")
    stage_runs = SW.price_stages(meas, hist, sched, engine, FIXTURE_DB, n_sims=SIMS, echo=say)
    out = {}
    with engine.connect() as c:
        for rnd, w in sched.items():
            out[w["event_key"]] = SW.weekend_markets(c, w, stage_runs[w["event_key"]])
    (mdir / "weekends.json").write_text(json.dumps(out, default=str))
    say(f"F1: weekend fixture {', '.join(f'{k} {len(v)} markets' for k, v in out.items())}")

    build_f1_season(engine, meas, hist)


def build_f1_season(engine, meas=None, hist=None):
    """Championship markets: hourly price history (to SEASON_END) and as-of season forecasts
    after each race in the fixture (decisions with no earlier race in the fixture are skipped)."""
    import numpy as np
    import pandas as pd

    from racinglines.db.config import get_session
    from racinglines.models.position_sim import pricing as run
    from racinglines.pipelines import season_strategy as SE
    if meas is None:
        meas = run.Measurements.load(engine)
        hist = run.history(meas)
    mdir = FIX / "market"
    mdir.mkdir(parents=True, exist_ok=True)
    say("F1: championship markets (hourly prices) and as-of season forecasts ...")
    end = pd.Timestamp(SEASON_END, tz="UTC")
    with engine.connect() as c:
        links = SE.season_links(c, F1_YEAR)
    with engine.connect() as c, get_session(FIXTURE_DB) as s:
        SE.fetch_history(s, c, links["token_id"].tolist(), end=end, echo=say)
    first_race = meas.drivers["r_ts"].min()
    times = [(lab, t) for lab, t in SE.decision_times(meas, F1_YEAR) if t.tz_convert(None) > first_race]
    runs = SE.asof_forecasts(engine, FIXTURE_DB, meas, hist, F1_YEAR, times, n_sims=SIMS // 2, echo=say)
    with engine.connect() as c:
        mks = SE.build_markets(c, links)
        keep = sorted(mks.values(), key=lambda m: (-len(m.ts), m.key))[:SEASON_MARKETS]
        keep_links = links[links["token_id"].isin([m.key for m in keep])]
        decisions = [dict(label=lab, t=str(t), fairs=SE.fairs(c, keep_links, rid)) for lab, t, rid in runs]
    arrays, meta = {}, []
    for i, m in enumerate(keep):
        ts = pd.DatetimeIndex(m.ts)
        sel = ts <= end
        arrays[f"{i}_ts"], arrays[f"{i}_px"] = ts[sel].asi8, m.px[sel]
        meta.append(dict(key=m.key, kind=m.kind, subject=m.subject, cost=m.cost, outcome=m.outcome,
                         closed_at=str(m.closed_at) if m.closed_at is not None else None))
    np.savez_compressed(mdir / "season.npz", **arrays)
    (mdir / "season.json").write_text(json.dumps(dict(markets=meta, decisions=decisions), default=str))
    say(f"F1: season fixture {len(keep)} markets, {len(decisions)} decisions")


# --- UCI downhill ----------------------------------------------------------------

def build_mtb(engine):
    from racinglines import paths
    from racinglines.db.config import get_session
    from racinglines.db.queries import load_tidy
    from racinglines.sources.chronorace import download
    from racinglines.sources.chronorace.ingest import ingest_paths

    for cat in ("Elite Men", "Junior Men"):
        say(f"MTB: ChronoRace {len(MTB_EVENTS)} events, {cat} ...")
        sys.argv = ["download", "--events", *MTB_EVENTS, "--discipline", "DH", "--category", cat]
        download.main()
    with get_session(FIXTURE_DB) as s:
        say(f"MTB: ingest {ingest_paths(s, [paths.DH_RAW], echo=lambda m: None)}")
    d = FIX / "mtb"
    d.mkdir(parents=True, exist_ok=True)
    for f in MTB_SAMPLE:
        shutil.copy(paths.DH_RAW / f, d / f)
    raw = load_tidy(engine, with_splits=False)
    raw = raw[raw["event_date"] >= "2025-01-01"]
    raw.to_parquet(d / "tidy_2025_2026.parquet", index=False)
    say(f"MTB: tidy {len(raw)} rows, {raw['event_id'].nunique()} event-categories")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--f1", action="store_true", help="Formula 1 fixtures only")
    ap.add_argument("--mtb", action="store_true", help="UCI downhill fixtures only")
    ap.add_argument("--resume-season", action="store_true", help=argparse.SUPPRESS)   # re-run only the championship step
    args = ap.parse_args()
    if args.resume_season:
        from sqlalchemy import create_engine
        build_f1_season(create_engine(FIXTURE_DB, future=True))
        return
    both = not args.f1 and not args.mtb
    WORK.mkdir(parents=True, exist_ok=True)
    engine = fresh_db(FIXTURE_DB)
    if args.mtb or both:
        build_mtb(engine)
    if args.f1 or both:
        build_f1(engine)
    total = sum(f.stat().st_size for f in FIX.rglob("*") if f.is_file() and "_work" not in f.parts)
    say(f"fixtures: {total / 1e6:.1f} MB in {FIX} (git-ignored). Raw downloads kept in {WORK} for re-runs.")
    say('Next: python -m pytest -m "not live"   (first run writes your golden baseline in tests/golden/)')


if __name__ == "__main__":
    main()
