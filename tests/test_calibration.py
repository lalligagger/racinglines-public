"""Calibration scores (racinglines/core/calibration.py): reliability bins, Brier, log loss and ECE, for any
source of probabilities side by side."""

import numpy as np
import pandas as pd
import pytest

from racinglines.core import calibration as C

pytestmark = pytest.mark.quick


def test_a_calibrated_forecast_scores_near_zero_ece():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 20000)
    y = (rng.uniform(0, 1, len(p)) < p).astype(float)
    s = C.scores(p, y)
    assert s["n"] == 20000 and s["ece"] < 0.02
    assert all(abs(r["z"]) < 4 for r in C.reliability(p, y))


def test_scores_by_hand():
    s = C.scores([0.1, 0.9], [0.0, 1.0])
    assert s["brier"] == pytest.approx(0.01)
    assert s["logloss"] == pytest.approx(-np.log(0.9))
    assert s["ece"] == pytest.approx(0.1)       # two bins, each off by 0.1
    assert C.scores([], [])["brier"] is None


def test_table_scores_each_source_on_its_own_rows():
    rows = pd.DataFrame(dict(kind=["a", "a", "b"], model=[0.2, 0.8, 0.5], market=[0.3, None, 0.5], y=[0, 1, 1]))
    summ, rel = C.table(rows, ("model", "market"), by=("kind",))
    got = summ.set_index(["kind", "source"])["n"].to_dict()
    assert got == {("a", "model"): 2, ("a", "market"): 1, ("b", "model"): 1, ("b", "market"): 1}
    assert set(rel.columns) >= {"kind", "source", "lo", "hi", "n", "predicted", "observed", "z"}
