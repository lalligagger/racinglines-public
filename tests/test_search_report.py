"""Search report (racinglines/pipelines/search_report.py): the held-out labels, the noise floor from seed
replicates, same-fidelity baselines, confirmation, concentration and stable candidate ids. Synthetic
saved-run metrics, no database."""

import json

import numpy as np
import pytest

from racinglines.pipelines import search_report as R
from racinglines.pipelines import sweep_settings as SS

pytestmark = pytest.mark.quick

STRATS = [("update", "Taker: update"), ("maker", "Maker")]


def _job(i, year, pnls, **settings):
    """A finished sweep job whose saved run has these weekend P&Ls for (update, maker)."""
    st = SS.Settings.from_dict(settings).to_json()
    wk = [dict(round=r + 1, event=f"GP {r + 1}", update_pnl=u, maker_pnl=m) for r, (u, m) in enumerate(pnls)]
    return dict(id=f"j{i}", year=year, settings=st, run_id=i, note=""), {i: dict(weekends=wk)}


def _build(specs, **cfg):
    jobs, metrics = [], {}
    for i, (year, pnls, st) in enumerate(specs, 1):
        j, m = _job(i, year, pnls, **st)
        jobs.append(j)
        metrics.update(m)
    rows, curves = R.stats(jobs, metrics, STRATS, cfg)
    return rows, curves, R.rank(rows, curves, cfg)[0]


FLAT = [(10.0, 10.0)] * 4
A = dict(min_edge=0.10)


def test_curve_stats():
    s, cum = R.curve_stats([100.0, -50.0, 30.0, -80.0], 24)
    assert cum == [100.0, 50.0, 80.0, 0.0]
    assert s["pnl"] == 0.0 and s["weekends_up"] == 2 and s["max_drawdown"] == 100.0
    assert s["pnl_without_best"] == -100.0 and s["best_index"] == 0


def test_labels_follow_the_held_out_rule():
    good = [(200.0, 10.0)] * 4                     # +760 on update against the baseline
    _, _, rank = _build([(2026, FLAT, {}), (2025, FLAT, {}),
                         (2026, good, A), (2025, good, A),                                    # robust
                         (2026, good, dict(min_edge=0.12)), (2025, FLAT, dict(min_edge=0.12)),   # target only
                         (2026, good, dict(min_edge=0.08))])                                  # no held-out run
    v = {(r["strategy"], r["settings_key"]): r["verdict"] for r in rank}
    key = lambda d: SS.Settings.from_dict(d).key                                  # noqa: E731
    assert v[("update", key({}))] == "baseline"
    assert v[("update", key(A))] == "robust"
    assert v[("update", key(dict(min_edge=0.12)))] == "target only"
    assert v[("update", key(dict(min_edge=0.08)))] == "no held-out run"
    assert v[("maker", key(A))] == "not better"                                  # maker P&L equal to the baseline


def test_a_difference_inside_the_noise_floor_is_not_better():
    small = [(40.0, 10.0)] * 4                     # +120 over four weekends: inside the ±150 taker floor
    _, _, rank = _build([(2026, FLAT, {}), (2025, FLAT, {}), (2026, small, A), (2025, small, A)])
    assert next(r for r in rank if r["strategy"] == "update" and r["settings_key"] == SS.Settings.from_dict(A).key
                )["verdict"] == "not better"


def test_seed_replicates_set_the_noise_floor_and_group_into_one_combo():
    specs = [(2026, FLAT, {}), (2025, FLAT, {})]
    for seed, x in ((1, 150.0), (2, 250.0), (3, 350.0)):                  # A's totals: 600, 1000, 1400 ...
        specs += [(2026, [(x, 10.0)] * 4, dict(A, seed=seed)), (2026, FLAT, dict(seed=seed))]
    specs += [(2026, [(250.0, 10.0)] * 4, A), (2025, [(200.0, 10.0)] * 4, A)]      # ... and 1000 at the default seed
    rows, curves, rank = _build(specs)
    floor, measured = R.noise_floor(rows)
    sd = float(np.std([600.0, 1000.0, 1400.0, 1000.0], ddof=1))
    assert measured["taker"] == pytest.approx(sd) and floor["taker"] == pytest.approx(sd)
    assert floor["maker"] == 0.0                   # the maker P&L never moved across seeds
    a = next(r for r in rank if r["strategy"] == "update" and r["settings_key"] == SS.Settings.from_dict(A).key)
    assert a["replicates"] == 4 and a["pnl_target"] == 1000.0      # the seeds are one combo, averaged
    assert a["noise_floor"] == pytest.approx(sd) and a["verdict"] == "robust"


def test_baselines_are_matched_at_the_same_fidelity():
    rows, _, _ = _build([(2026, FLAT, {}), (2026, [(0.0, 0.0)] * 4, dict(sims=16000)),
                         (2026, [(50.0, 10.0)] * 4, dict(A, sims=16000))])
    r = next(x for x in rows if x["settings_key"] == SS.Settings.from_dict(dict(A, sims=16000)).key
             and x["strategy"] == "update")
    assert r["vs_baseline"] == 200.0              # against the 16k baseline (0), not the 4k one (40)


def test_confirmation_and_twin_seasons():
    good = [(200.0, 10.0)] * 4
    twin = lambda st, y: SS.Settings.from_dict(dict(st, variant="gridq"))      # noqa: E731
    spec = [(2026, FLAT, {}), (2025, FLAT, {}), (2026, FLAT, dict(sims=16000)), (2025, FLAT, dict(sims=16000)),
            (2026, good, dict(A, variant="gridq+reset")), (2025, good, dict(A, variant="gridq")),
            (2026, good, dict(A, variant="gridq+reset", sims=16000)), (2025, FLAT, dict(A, variant="gridq", sims=16000))]
    jobs, metrics = [], {}
    for i, (y, p, st) in enumerate(spec, 1):
        j, m = _job(i, y, p, **st)
        jobs.append(j)
        metrics.update(m)
    rows, curves = R.stats(jobs, metrics, STRATS)
    rank, _, _ = R.rank(rows, curves, twin=twin)
    a = next(r for r in rank if r["strategy"] == "update" and "reset" in r["label_settings"])
    assert a["verdict"] == "robust" and a["pnl_2025"] == 800.0
    assert a["confirmed"] == "no"                  # the 2025 16k run gives nothing over the 16k baseline


def test_outputs_and_stable_candidate_ids(tmp_path):
    good = [(300.0, 10.0), (100.0, 10.0), (-20.0, 10.0), (200.0, 10.0)]
    jobs, metrics = [], {}
    for i, (y, p, st) in enumerate([(2026, FLAT, {}), (2025, FLAT, {}), (2026, good, A), (2025, good, A)], 1):
        j, m = _job(i, y, p, **st)
        jobs.append(j)
        metrics.update(m)
    R.write(tmp_path, jobs, metrics, STRATS, rerun=lambda j: ["racinglines", "f1", "sweep", "--year", str(j["year"])],
            echo=lambda m: None)
    cid = f"update-{SS.Settings.from_dict(A).key}"
    doc = json.loads((tmp_path / "candidates" / f"{cid}.json").read_text())
    assert doc["rank"] == 1 and doc["verdict"] == "robust" and doc["without_best_target"] == 280.0
    assert doc["best_event_target"] == "GP 1" and doc["rerun"]["2025"].endswith("2025")
    assert f'name = "{cid}:' in (tmp_path / "candidates.toml").read_text()
    for f in ("stats.csv", "ranking.csv", "pnl_curves.json", "report.md"):
        assert (tmp_path / f).exists()


def test_seasonal_switches_are_dropped_outside_their_season():
    from racinglines.models.position_sim import variants as V
    assert V.for_season("gridq+pretrain+reset", 2025) == "gridq+pretrain"
    assert V.for_season("gridq+pretrain+reset", 2026) == "gridq+pretrain+reset"
    assert V.for_season("reset", 2024) == "baseline"


def test_beating_a_losing_baseline_is_flagged_when_it_still_loses():
    losing = [(-100.0, 10.0)] * 4                  # the held-out baseline loses 400
    better = [(-10.0, 10.0)] * 4                   # beats it by 360 and still loses 40
    _, _, rank = _build([(2026, FLAT, {}), (2025, losing, {}), (2026, [(200.0, 10.0)] * 4, A), (2025, better, A)])
    a = next(r for r in rank if r["strategy"] == "update" and r["settings_key"] == SS.Settings.from_dict(A).key)
    assert a["verdict"] == "robust" and a["loses_money_in"] == "2025"
