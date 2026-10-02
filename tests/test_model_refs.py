"""Every modeled sport's `[sport] pricing_model` resolves to a class with the pricing-model contract
(racinglines/models/race_model.py). `racinglines check` and the other tests never import it, so a typo or a
reference to a module that was never merged only failed at the first backtest."""

import pytest

from racinglines import sports
from racinglines.models import race_model as RM

pytestmark = pytest.mark.quick

CONTRACT = ("Settings", "name", "load", "data_through", "seasons", "events", "history", "price", "results")


@pytest.mark.parametrize("code", [c for c in sports.SPORT_CODES if sports.modeled(c)])
def test_the_pricing_model_reference_resolves(code):
    model = RM.model_class(code)
    assert [a for a in CONTRACT if not hasattr(model, a)] == []
    assert RM.get(code).sport == code
