"""
UCI downhill regression suite: every pipeline stage on pinned inputs (tests/fixtures/mtb),
checked against golden outputs. Small sims, fixed seeds.

Stages: parser (results tables) -> ingest (fresh database) -> tidy
frame -> season model -> weekend simulation -> season forecast -> backtest -> walk-forward.
"""

import numpy as np
import pandas as pd
import pytest
from conftest import FIX, need
from golden import check

MD = FIX / "mtb" / "20260821_mtb_dhi_elite-men.md"
MD_JUNIOR = FIX / "mtb" / "20260821_mtb_dhi_junior-men.md"


def _fp(df, cols):
    """Small fingerprint of a parsed / tidy frame."""
    out = dict(rows=len(df), columns=sorted(df.columns))
    for c in cols:
        if c in df:
            s = df[c]
            out[c] = s.value_counts().sort_index().to_dict() if s.dtype == object else float(pd.to_numeric(s, errors="coerce").sum())
    return out


# --- 1. parser -------------------------------------------------------------------

def test_parse_results_tables():
    from racinglines.sources.chronorace.parse import parse_markdown_tables_file
    out = {}
    for f in (MD, MD_JUNIOR):
        need("mtb", f.name)
        df = pd.DataFrame(parse_markdown_tables_file(f))
        fin = df[(df["round"] == "final") & (df["sector_id"] == "FINISH")].sort_values("rank_at_split")
        out[f.name] = dict(_fp(df, ["round", "sector_id", "status", "cum_time_s"]),
                           podium=fin[["rider_name", "cum_time_s", "rank_at_split"]].head(3))
    check("mtb_parse_tables", out)


# --- 2. ingest + tidy frame from the database -------------------------------------

def test_ingest_and_tidy(test_engine):
    from sqlalchemy.orm import sessionmaker

    from racinglines.sources.chronorace.ingest import ingest_file, seed
    from racinglines.db.queries import load_tidy
    with sessionmaker(test_engine)() as s:
        seed(s)
        s.commit()
        status = [ingest_file(s, need("mtb", f.name)) for f in (MD, MD_JUNIOR)]
        s.commit()
    raw = load_tidy(test_engine, with_splits=True)
    check("mtb_ingest_tidy", dict(ingest=status, **_fp(raw, ["category", "round", "sector_id", "status", "cum_time_s"])))


# --- 3. model and simulations on the pinned training slice ------------------------

@pytest.fixture(scope="module")
def dh():
    from racinglines.models import timed_runs as P
    raw = pd.read_parquet(need("mtb", "tidy_2025_2026.parquet"))
    raw = raw[raw["round"].isin(P.RUN_WEIGHTS)]
    target = P.select_target(raw, 2026, "ME")
    done = target[target["event_id"].isin(P.completed_events(target))]
    return P, raw, target, done


def test_season_model(dh):
    P, raw, target, _ = dh
    m = P.fit_season_model(raw, category="ME")
    top = m["mu"].sort_values().head(8)
    check("mtb_season_model", dict(
        scalars={k: v for k, v in m.items() if isinstance(v, (int, float))},
        riders=len(m["mu"]), mu_top=top.round(10).to_dict(), mu_mean=float(m["mu"].mean())))


def test_weekend_simulation(dh):
    P, raw, target, done = dh
    model = P.fit_season_model(raw, category="ME")
    last = P.event_order(done)[-1]
    riders = P.event_starters(done, last)
    sim = P.simulate_weekend(model, riders, n_sims=1000, rng=np.random.default_rng(5), fmt=P.event_format(done, last))
    summ = P.summarize_weekend(model, riders, sim).sort_values("rider_id")
    check("mtb_weekend_sim", dict(event=last, riders=len(riders), summary=summ))


def test_season_forecast(dh):
    P, raw, target, _ = dh
    model, upcoming, per_round, standings = P.forecast_season(raw, target, n_remaining=2, n_sims=1000,
                                                              rng=np.random.default_rng(11))
    check("mtb_season_forecast", dict(
        upcoming=[(e, s.sort_values("rider_id").head(15)) for e, s in upcoming],
        per_round=per_round.sort_values("rider_id").head(15) if per_round is not None else None,
        standings=standings.sort_values("rider_id").head(20)))


def test_backtest(dh):
    P, raw, _, done = dh
    model, reports, standings, (train_ev, test_ev) = P.backtest_season(raw, done, n_holdout=2, n_sims=1000,
                                                                       rng=np.random.default_rng(13))
    # each weekend's table sorted by rider: summarize_weekend orders by exp_points, and riders tied at 0 swap places
    reports = [(metrics, summ.sort_values("rider_id", kind="stable").reset_index(drop=True)) for metrics, summ in reports]
    check("mtb_backtest", dict(train=train_ev, test=test_ev, reports=reports,
                               standings=standings.sort_values("rider_id").head(20)))


def test_walk_forward(dh):
    P, raw, _, done = dh
    wf = P.walk_forward_season(raw, done, n_sims=300, rng=np.random.default_rng(17))
    check("mtb_walk_forward", wf)
