"""Plackett-Luce challenger (racinglines/models/model_pl.py): the MM fit recovers known strengths, and the prior
keeps an entrant with no results at the field average."""

import numpy as np
import pytest

from racinglines.models.model_pl import fit_pl


@pytest.mark.quick
def test_fit_recovers_known_strengths():
    rng = np.random.default_rng(0)
    true = np.linspace(1.5, -1.5, 10)                       # log strengths, best first
    orders = [np.argsort(-(true + rng.gumbel(size=10))) for _ in range(400)]
    g = np.log(fit_pl(orders, [1.0] * 400, 10, prior=0.01))
    g -= g.mean()
    assert np.all(np.diff(g)[:-1] < 0.2)                   # close to the true order
    assert np.max(np.abs(g - true)) < 0.25


@pytest.mark.quick
def test_unseen_entrant_stays_average_and_weights_count():
    orders = [np.array([0, 1, 2])] * 5
    g = fit_pl(orders, [1.0] * 5, 4, prior=3.0)
    assert g[3] == pytest.approx(1.0)                       # never raced: exactly the prior
    assert g[0] > g[1] > g[2]
    light = fit_pl(orders, [0.1] * 5, 4, prior=3.0)         # the same races at a tenth of the weight
    assert abs(np.log(light[0])) < abs(np.log(g[0]))        # move the strengths less
