"""Downhill calibration tools (racinglines/models/timed_runs): the walk-forward's per-rider rows,
the reliability table, and the model switches (--prior-n, --eps-df). Synthetic data, no database."""

import argparse
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from racinglines.models import timed_runs as P
from racinglines.models.timed_runs import model as TM
from racinglines.models.timed_runs import season as SE

pytestmark = pytest.mark.quick


@pytest.fixture(scope="module")
def raw():
    from racinglines.sources.chronorace.parse import parse_markdown_tables_file
    from racinglines.testing import synthetic as SY
    d = Path(tempfile.mkdtemp(prefix="racinglines-test-"))
    for name, text in SY.mtb_results_md().items():
        (d / name).write_text(text)
    r = pd.concat([pd.DataFrame(parse_markdown_tables_file(f)) for f in sorted(d.glob("*.md"))], ignore_index=True)
    return r[r["round"].isin(P.RUN_WEIGHTS)]


def _walk(raw, **kw):
    tgt = P.select_target(raw, 2026, "ME")
    done = tgt[tgt["event_id"].isin(P.completed_events(tgt))]
    rows = []
    wf = SE.walk_forward_season(raw, done, n_sims=300, rng=np.random.default_rng(5), rider_rows=rows, **kw)
    return wf, rows


def test_rider_rows_match_the_event_metrics(raw):
    wf, rows = _walk(raw)
    assert len(rows) == len(wf) > 0
    for (_, m), r in zip(wf.iterrows(), rows):
        assert len(r) == m["n_riders"] and r["won"].sum() <= 1 and r["podium"].sum() <= 3
        assert np.isclose(((r["win_prob"] - r["won"]) ** 2).mean(), m["brier_win"])
        assert np.isclose(((r["make_final_prob"] - r["made_final"]) ** 2).mean(), m["brier_final"])
    plain = SE.walk_forward_season(raw, P.select_target(raw, 2026, "ME").pipe(
        lambda t: t[t["event_id"].isin(P.completed_events(t))]), n_sims=300, rng=np.random.default_rng(5))
    assert plain.equals(wf)                                     # collecting rows changes nothing


def test_reliability_table():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 20000)
    df = pd.DataFrame({c: p for c, _ in SE.CAL_MARKETS.values()})
    for c, y in SE.CAL_MARKETS.values():
        df[y] = rng.random(len(p)) < p                          # perfectly calibrated
    rel = SE.calibration(df)
    bins = rel[rel["bin"] != "total"]
    assert set(rel["market"]) == set(SE.CAL_MARKETS) and bins["n"].sum() == 4 * len(p)
    assert bins["z"].abs().max() < 4.5
    tot = rel[rel["bin"] == "total"].set_index("market")
    assert np.allclose(tot["brier"], ((p - df["won"]) ** 2).mean(), atol=0.01)
    flat = SE.calibration(df.assign(**{c: 0.5 for c, _ in SE.CAL_MARKETS.values()}))
    assert (flat.loc[flat["bin"] == "total", "brier"].to_numpy() > tot["brier"].to_numpy()).all()


def test_less_shrinkage_spreads_the_paces(raw):
    tight, loose = P.fit_season_model(raw, prior_n=1.5), P.fit_season_model(raw, prior_n=0.5)
    assert loose["mu"].std() > tight["mu"].std()


def test_student_t_noise(raw, monkeypatch):
    m = P.fit_season_model(raw)
    riders = list(m["mu"].index[:20])
    sim = lambda: P.simulate_weekend(m, riders, n_sims=400, rng=np.random.default_rng(9))["points"]
    base = sim()
    monkeypatch.setattr(TM, "EPS_DF", None)
    assert (sim() == base).all()                                # unset: the same draws as before
    monkeypatch.setattr(TM, "EPS_DF", 5.0)
    t = sim()
    assert t.shape == base.shape and not (t == base).all()
    # the scaling in simulate_weekend keeps the run noise's sd at sigma
    eps = 0.02 * np.sqrt((5 - 2) / 5) * np.random.default_rng(2).standard_t(5, 400000)
    assert abs(eps.std() - 0.02) < 0.0005


def test_cli_switches(monkeypatch):
    from racinglines.cli import mtb_dh as C
    monkeypatch.setattr(TM, "EPS_DF", None)
    assert C._model_switches(argparse.Namespace(prior_n=None, eps_df=None)) == {} and TM.EPS_DF is None
    assert C._model_switches(argparse.Namespace(prior_n=0.5, eps_df=6.0)) == dict(prior_n=0.5) and TM.EPS_DF == 6.0
    with pytest.raises(SystemExit):
        C._model_switches(argparse.Namespace(prior_n=None, eps_df=2.0))
