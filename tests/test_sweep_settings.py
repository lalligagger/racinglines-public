"""Sweep settings schema (racinglines/pipelines/sweep_settings.py): defaults, validation, identity keys,
command-line round trip, and model settings applied and restored."""

import argparse

import pytest

from racinglines.pipelines import sweep_settings as SS

pytestmark = pytest.mark.quick


def test_defaults_match_the_code_they_configure():
    from racinglines.markets.strategies import maker_replay as R
    from racinglines.markets.strategies.taker_weekend import TakerParams
    from racinglines.models.position_sim import model as M
    from racinglines.models.position_sim import practice as PR
    from racinglines.pipelines import weekend_sweep as W
    d = SS.Settings.from_dict()
    t, m = TakerParams(), R.Params()
    assert (d["min_edge"], d["stake_per_edge"], d["max_stake"], d["cost"]) == (t.min_edge, t.stake_per_edge,
                                                                               t.max_stake, t.cost)
    assert d["late_stages"] == t.late_stages
    assert (d["half_spread"], d["size"], d["max_pos"], d["skew"], d["max_disagree"], d["fill"]) == (
        m.half_spread, m.size, m.max_pos, m.skew, m.max_disagree, m.fill)
    assert d["info_skew"] == W.MAKERS["maker_skew"]["info_skew"] and d["widen"] == W.WIDEN
    assert d["min_volume_24h"] == W.MIN_VOLUME_24H and d["market_kinds"] == W.KINDS
    assert (d["half_life_days"], d["ridge_team"], d["ridge_slope"], d["driver_prior_n"]) == (
        M.HALF_LIFE_DAYS, M.RIDGE_A, M.RIDGE_B, M.DRIVER_PRIOR_N)
    assert d["practice_prior"] == PR.USE_PRACTICE and d["reset_weight"] == M.REG_RESET_WEIGHT
    assert d.changed() == {} and d.argv() == [] and d.label() == "baseline"


def test_keys():
    d = SS.Settings.from_dict()
    trading = SS.Settings.from_dict(dict(min_edge=0.08))
    model = SS.Settings.from_dict(dict(half_life_days=90))
    assert trading.model_key == d.model_key and trading.key != d.key      # same prices, different combo
    assert model.model_key != d.model_key
    assert SS.Settings.from_dict(dict(taker_stages="after FP2,pre-weekend")).key == \
        SS.Settings.from_dict(dict(taker_stages=["pre-weekend", "after FP2"])).key   # order doesn't matter


def test_validation():
    for bad in (dict(half_life_days=5), dict(variant="nope"), dict(market_kinds="race_lunch"), dict(fill="maybe"),
                dict(bogus=1)):
        with pytest.raises(ValueError):
            SS.Settings.from_dict(bad)


def test_argv_round_trips_through_the_parser():
    s = SS.Settings.from_dict(dict(variant="gridq", half_life_days=90, practice_prior=False,
                                   taker_stages="pre-weekend,after FP1", half_spread=0.03))
    p = argparse.ArgumentParser()
    p.add_argument("--variant", default="baseline")
    SS.add_arguments(p)
    args = p.parse_args(["--variant", s["variant"], *s.argv()])
    assert SS.from_args(args) == s


def test_old_saved_params_are_read():
    s = SS.Settings.from_run_params({"n_sims": 4000, "variant": "reset", "min_edge": 0.05, "mode": "update",
                                     "price_band": [0.02, 0.98]})
    assert s["variant"] == "reset" and s.changed() == {"variant": "reset"}


def test_applied_sets_and_restores_model_globals():
    from racinglines.models.position_sim import model as M
    from racinglines.models.position_sim import practice as PR
    before = (M.HALF_LIFE_DAYS, PR.USE_PRACTICE, M.GRID_TERMS)
    with SS.Settings.from_dict(dict(variant="gridq", half_life_days=90, practice_prior=False)).applied():
        assert (M.HALF_LIFE_DAYS, PR.USE_PRACTICE, M.GRID_TERMS) == (90.0, False, "known")
    assert (M.HALF_LIFE_DAYS, PR.USE_PRACTICE, M.GRID_TERMS) == before


# --- min_edge_h2h (the head-to-head threshold): new setting, unchanged keys --------------------------

PROFILE_A = {"variant": "gridq+pretrain+reset", "min_edge": 0.10,
             "taker_stages": ["after FP1", "after FP2", "after FP3", "after SQ", "after Sprint", "after Quali"]}


def test_unset_optional_setting_leaves_every_key_unchanged():
    """Keys saved before min_edge_h2h existed (these values were computed before it was added)."""
    assert SS.Settings.from_dict().key == "c107835cbced"
    assert SS.Settings.from_dict(PROFILE_A).key == "8a383d4d0c68"
    a = SS.Settings.from_dict(PROFILE_A)
    b = SS.Settings.from_dict(dict(PROFILE_A, min_edge_h2h=0.05))
    assert a["min_edge_h2h"] is None and b.key != a.key and b.model_key == a.model_key
    assert "min_edge_h2h" not in a.changed() and b.changed()["min_edge_h2h"] == 0.05
    assert "--min-edge-h2h" in b.argv() and "--min-edge-h2h" not in a.argv()


def test_optional_setting_parses_blank_and_checks_range():
    assert SS.Settings.from_dict({"min_edge_h2h": ""})["min_edge_h2h"] is None
    assert SS.Settings.from_dict({"min_edge_h2h": "0.05"})["min_edge_h2h"] == 0.05
    with pytest.raises(ValueError):
        SS.Settings.from_dict({"min_edge_h2h": 0.9})


def _market(kind, fair, price, outcome=True):
    return dict(key=f"{kind}-{fair}", kind=kind, subject=kind, outcome=outcome,
                stages=[dict(label="after FP1", t=1, fair=fair, price=price, tradeable=True),
                        dict(label="after FP2", t=2, fair=fair + 0.01, price=price, tradeable=True)])


def test_h2h_threshold():
    from racinglines.markets.strategies.taker_weekend import TakerParams, run_weekend
    wk = [_market("race_h2h", 0.57, 0.50), _market("race_win", 0.37, 0.30), _market("race_podium", 0.50, 0.30, False)]
    # default (None): byte-identical to the taker before the setting existed
    t0, p0 = run_weekend(wk, TakerParams())
    t1, p1 = run_weekend(wk, TakerParams(min_edge_h2h=None))
    assert t0.equals(t1) and p0.equals(p1)
    # min_edge 0.10 with h2h at 0.05: the 7-point h2h edge trades, the 7-point win edge doesn't
    tr, _ = run_weekend(wk, TakerParams(min_edge=0.10, min_edge_h2h=0.05))
    assert set(tr["kind"]) == {"race_h2h", "race_podium"}
    tr, _ = run_weekend(wk, TakerParams(min_edge=0.10))
    assert set(tr["kind"]) == {"race_podium"}
