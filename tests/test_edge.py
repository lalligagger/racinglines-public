"""Edge Finder combo edits (racinglines/web/edge.py): pure list logic, no database."""

import pytest

from racinglines.web import edge as E

pytestmark = pytest.mark.quick


def test_default_is_baseline_with_every_strategy():
    assert E.apply([], "reset") == E.DEFAULT
    assert [s for _, s in E.DEFAULT] == E.STRATEGY_KEYS


def test_add_remove_toggle():
    cs = E.apply([], "add", "gridq+pretrain", "maker")
    assert cs == [("gridq+pretrain", "maker")]
    assert E.apply(cs, "add", "gridq+pretrain", "maker") == cs                   # no duplicates
    assert E.apply(cs, "toggle", "gridq+pretrain", "maker") == []
    assert E.apply([], "toggle", "reset", "hold") == [("reset", "hold")]
    assert E.apply(cs, "remove", "gridq+pretrain", "maker") == []


def test_add_model_and_strategy_follow_what_is_shown():
    cs = [("baseline", "maker"), ("baseline", "hold")]
    assert E.apply(cs, "add_model", "reset") == cs + [("reset", "maker"), ("reset", "hold")]
    assert E.apply([], "add_model", "reset") == [("reset", s) for s in E.STRATEGY_KEYS]
    assert E.apply(cs + [("reset", "maker")], "add_strategy", strategy="last") == \
        cs + [("reset", "maker"), ("baseline", "last"), ("reset", "last")]
    assert E.apply([], "add_strategy", strategy="last") == [("baseline", "last")]
    assert E.apply(cs + [("reset", "maker")], "remove_model", "baseline") == [("reset", "maker")]


@pytest.mark.parametrize("args", [("add", "nonsense", "maker"), ("add", "baseline", "nope"), ("add_model", "x+y"),
                                  ("add_strategy", "", "nope"), ("explode",)])
def test_rejects_unknown_models_strategies_and_actions(args):
    with pytest.raises(ValueError):
        E.apply([], *args)
