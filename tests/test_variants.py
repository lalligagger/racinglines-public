"""Model variants (position_sim/variants.py) and the comparison tools (position_sim/evaluate.py).

The baseline is untouched by construction: every switch defaults off, and the golden files
of test_pipeline_f1 pin it. Here: switches set and restore, each variant prices a race
through the same leakage-guarded path, and paired comparisons do what they claim."""

import numpy as np
import pandas as pd
import pytest

from racinglines.models.position_sim import evaluate as EV
from racinglines.models.position_sim import model as M
from racinglines.models.position_sim import variants as V


def test_use_sets_and_restores_switches():
    with V.use("gridq+tail"):
        assert M.GRID_TERMS == "known" and M.CHAOS and M.TEAM_DNF_CORR
    assert M.GRID_TERMS is False and not M.CHAOS and not M.TEAM_DNF_CORR
    with pytest.raises(ValueError):
        V.switches("nope")


def test_grid_terms_only_when_known():
    with V.use("gridq"):
        assert "g_log" in M.features(grid_known=True)
        assert "g_log" not in M.features(grid_known=False)
    with V.use("grid"):
        assert "g_log" in M.features(grid_known=False)


@pytest.mark.parametrize("variant", ["grid", "gridq", "pretrain", "tail"])
def test_variant_prices_a_race_and_guards_leakage(f1_meas, variant):
    from racinglines.models.position_sim import pricing as run
    eid = int(f1_meas.drivers["event_id"].max())
    s = f1_meas.sessions(eid)
    with V.use(variant):
        hist = run.history(f1_meas)
        for cutoff in (s["fp1"] - pd.Timedelta(hours=1), s["qual"] + pd.Timedelta(hours=2)):
            summ, ex = run.price_race(f1_meas, hist, cutoff, eid, n_sims=800, rng=np.random.default_rng(1))
            assert summ["win_prob"].sum() == pytest.approx(1.0, abs=0.02)
            assert summ["podium_prob"].sum() == pytest.approx(3.0, abs=0.1)
        # a session that hasn't ended can't be seen, whatever the variant
        v = f1_meas.view(s["qual"] + pd.Timedelta(minutes=30))
        assert not ((v.res["event_id"] == eid) & (v.res["round"] == "qual")).any()
        assert v.races is None or (v.races["r_ts"] + M.RACE_DONE < v.cutoff).all()


def test_paired_differences():
    a = pd.DataFrame(dict(event_id=range(10), mode="pre_race", brier_win=0.03))
    b = a.assign(brier_win=0.03 - 0.002 + np.linspace(-1e-4, 1e-4, 10))
    t = EV.paired(a, b, metrics=["brier_win"], modes=["pre_race"])
    r = t.iloc[0]
    assert r["n"] == 10 and r["diff"] == pytest.approx(-0.002) and r["verdict"] == "better"
    assert EV.paired(a, a, metrics=["brier_win"], modes=["pre_race"]).iloc[0]["verdict"] == ""


def test_reliability_bins():
    rows = pd.DataFrame(dict(mode=["pre_race"] * 2, pred=[dict(win=[0.9, 0.1], y_win=[1, 0]),
                                                          dict(win=[0.9, 0.1], y_win=[0, 0])]))
    rel = EV.reliability(rows, "win")
    hi = rel[rel["lo"] == 0.7].iloc[0]
    assert hi["n"] == 2 and hi["predicted"] == pytest.approx(0.9) and hi["observed"] == pytest.approx(0.5)
    ece = EV.calibration_error(rel).iloc[0]["ece"]
    assert ece == pytest.approx((2 * 0.4 + 2 * 0.1) / 4)


def test_reg_reset_discounts_earlier_seasons_only_in_a_reset_year():
    import pandas as pd

    from racinglines.models.position_sim import model as M
    dates = pd.Series(pd.to_datetime(["2025-11-30", "2026-03-08"]))
    base = M._car_weights(dates, pd.Timestamp("2026-04-01"))
    assert list(base) == list(M._weights(dates, pd.Timestamp("2026-04-01")))      # off: unchanged
    with V.use("reset"):
        w26 = M._car_weights(dates, pd.Timestamp("2026-04-01"))
        w25 = M._car_weights(pd.Series(pd.to_datetime(["2024-11-30", "2025-03-08"])), pd.Timestamp("2025-04-01"))
    assert w26[0] == pytest.approx(base[0] * M.REG_RESET_WEIGHT) and w26[1] == pytest.approx(base[1])
    assert 2025 not in M.RESET_YEARS and list(w25) == list(M._weights(
        pd.Series(pd.to_datetime(["2024-11-30", "2025-03-08"])), pd.Timestamp("2025-04-01")))
