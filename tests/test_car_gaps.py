"""Per-car pace gaps saved with every F1 run (metrics.car_gaps): the car term only, as a % gap to the fastest car,
so the MCP get_model_run tool can answer "how far apart are the cars" without re-pricing."""

import inspect

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.quick


def _snap(**kw):
    from racinglines.models.inputs import laps as M
    base = dict(team_q={"a": (0.010, 0.0), "b": (0.012, 0.004)}, q0=0.02,
                team_r={"a": (0.008, 0.002), "b": (0.007, 0.0)}, r0=0.02,
                drv_q={1: -0.5}, drv_r={1: -0.5}, dnf_team={}, dnf0=0.1)
    return M.Snapshot(**dict(base, **kw))


def test_gaps_are_the_car_term_relative_to_the_fastest():
    from racinglines.models.inputs import laps as M
    g = M.car_gaps(_snap(), ["a", "b"], dict(x_track=1.0))
    # race: a = 0.008 + 0.002 = 1.0%, b = 0.7% -> b fastest; qualifying: a = 1.0%, b = 1.6%
    assert g == {"b": {"race_pct": 0.0, "qual_pct": 0.6}, "a": {"race_pct": 0.3, "qual_pct": 0.0}}
    assert list(g) == ["b", "a"]                         # ordered by race-pace gap
    # driver offsets (huge here) never enter: the same gaps with none
    assert M.car_gaps(_snap(drv_q={}, drv_r={}), ["a", "b"], dict(x_track=1.0)) == g


def test_track_term_is_off_without_track_features_and_unknown_teams_get_the_slow_default():
    from racinglines.models.inputs import laps as M
    g = M.car_gaps(_snap(use_track=False), ["a", "b", "new"], dict(x_track=5.0))
    assert g["b"]["race_pct"] == 0.0 and g["a"]["race_pct"] == pytest.approx(0.1)
    # the slowest known car's base pace on each table: a on race pace, b in qualifying
    assert g["new"] == {"race_pct": g["a"]["race_pct"], "qual_pct": g["b"]["qual_pct"]}


def test_price_race_and_save_diagnostic_carry_the_gaps(monkeypatch):
    from racinglines.models.inputs import laps_pricing as run
    from racinglines.testing import synthetic as SY
    m = run.Measurements.from_frames(*SY.f1_frames())
    hist = run.history(m)
    eid = int(m.drivers["event_id"].max())
    cutoff = m.sessions(eid)["qual"] + pd.Timedelta(hours=2)
    summ, ex = run.price_race(m, hist, cutoff, eid, n_sims=500, rng=np.random.default_rng(1))
    gaps = ex["car_gaps"]
    assert set(gaps) == set(summ["team_key"])
    assert min(v["race_pct"] for v in gaps.values()) == 0.0
    assert min(v["qual_pct"] for v in gaps.values()) == 0.0
    seen = {}
    monkeypatch.setattr(run, "records_enabled", lambda: False)
    monkeypatch.setattr(run, "save_forecast", lambda *a, **k: seen.update(metrics=a[5]) or 1)
    run.save_diagnostic("unused", "2025-01", cutoff, summ, ex, 500)
    assert seen["metrics"]["car_gaps"] == {"2025-01": gaps}


def test_forecast_runs_save_the_gaps_per_event():
    from racinglines.cli import f1 as CLI
    from racinglines.models.inputs import laps_pricing as run
    assert 'car_gaps[f"{year}-{ev.round:02d}"] = ex["car_gaps"]' in inspect.getsource(run)
    assert 'car_gaps=extras["car_gaps"]' in inspect.getsource(CLI)
