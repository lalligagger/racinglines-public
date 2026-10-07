"""Combos (racinglines/markets/combos.py): a combo's fair value is the share of simulations in which every leg holds, so
independent legs give the product of their marginals and correlated legs (the winner sets the fastest lap) price above
it; a leg the simulations can't decide fails naming it; settlement takes each leg's own rule. Synthetic data only."""

import numpy as np
import pandas as pd
import pytest

from racinglines.books import schema as S
from racinglines.markets import combos as C
from racinglines.markets import kinds as K
from racinglines.models.outcomes import OutcomeSims

pytestmark = pytest.mark.quick

A, B, CC, D = 11, 22, 33, 44


def _factorial():
    """Four simulations in which A's win and A's fastest lap vary independently: each holds in two of four, both in one."""
    rank = np.array([[1, 2, 3, 4], [1, 2, 3, 4], [2, 1, 3, 4], [2, 1, 3, 4]], float)
    fl = np.zeros((4, 4), bool)
    fl[[0, 2], 0] = True
    fl[[1, 3], 1] = True
    pts = np.where(rank == 1, 25.0, np.where(rank == 2, 18.0, 0.0))
    return OutcomeSims(entrants=[A, B, CC, D], rank=rank, finished=np.ones((4, 4), bool),
                       stage_rank={"qual": np.tile([1.0, 2, 3, 4], (4, 1))}, points=pts,
                       groups=["red", "red", "blue", "blue"], indicators={"race_fastest_lap": fl})


def _race(n_sims=20000, seed=3):
    """A synthetic 20-car race: rank from pace + noise; the fastest lap to the winner half the time, else to a car
    drawn uniformly, so the two move together."""
    rng = np.random.default_rng(seed)
    n = 20
    score = np.linspace(0.0, 0.03, n)[None, :] + rng.normal(0, 0.01, (n_sims, n))
    rank = score.argsort(1).argsort(1) + 1.0
    who = np.where(rng.random(n_sims) < 0.5, (rank == 1).argmax(1), rng.integers(0, n, n_sims))
    fl = np.zeros((n_sims, n), bool)
    fl[np.arange(n_sims), who] = True
    return OutcomeSims(entrants=list(range(100, 100 + n)), rank=rank, finished=np.ones((n_sims, n), bool),
                       indicators={"race_fastest_lap": fl})


def test_independent_legs_equal_the_product():
    s = _factorial()
    legs = [{"kind": "race_win", "athlete": A}, {"kind": "race_fastest_lap", "athlete": A}]
    out = C.price(legs, s)
    assert out["legs"] == [0.5, 0.5]
    assert out["fair"] == pytest.approx(0.25) == pytest.approx(out["independent"])
    assert C.combo_fair(legs, s) == pytest.approx(0.25)


def test_three_independent_legs_win_pole_fastest_lap():
    """Eight simulations in which A's win, pole and fastest lap vary independently (each holds in four): the
    three-leg combo, same driver, holds in exactly one, the product of the marginals."""
    bits = np.array([[(i >> j) & 1 for j in range(3)] for i in range(8)], bool)
    rank = np.where(bits[:, [0]], [[1.0, 2, 3, 4]], [[2.0, 1, 3, 4]])
    qual = np.where(bits[:, [1]], [[1.0, 2, 3, 4]], [[2.0, 1, 3, 4]])
    fl = np.zeros((8, 4), bool)
    fl[:, 0], fl[:, 1] = bits[:, 2], ~bits[:, 2]
    s = OutcomeSims(entrants=[A, B, CC, D], rank=rank, finished=np.ones((8, 4), bool), stage_rank={"qual": qual},
                    indicators={"race_fastest_lap": fl})
    legs = [{"kind": "race_win", "athlete": A}, {"kind": "race_pole", "athlete": A},
            {"kind": "race_fastest_lap", "athlete": A}]
    out = C.price(legs, s)
    assert out["legs"] == [0.5, 0.5, 0.5] and out["fair"] == pytest.approx(1 / 8) == pytest.approx(out["independent"])


def test_legs_match_the_single_markets():
    s = _factorial()
    for leg, single in [({"kind": "race_podium", "athlete": B}, K.fair("race_podium", s, a=B)),
                        ({"kind": "race_pole", "athlete": A}, K.fair("race_pole", s, a=A)),
                        ({"kind": "race_h2h", "pair": [A, B]}, K.fair("race_h2h", s, a=A, b=B)),
                        ({"kind": "race_constructor_top", "team": "red"}, K.fair("race_constructor_top", s)["red"]),
                        ({"kind": "race_classified", "athlete": CC}, K.fair("race_classified", s, a=CC)),
                        ({"kind": "race_team_both_classified", "team": "blue"},
                         K.fair("race_team_both_classified", s)["blue"]),
                        ({"kind": "race_n_classified", "line": 3.5}, K.fair("race_n_classified", s, line=3.5))]:
        assert C.leg_hits(s, leg).mean() == pytest.approx(single), leg


def test_side_no_takes_the_complement():
    s = _factorial()
    yes = C.leg_hits(s, {"kind": "race_win", "athlete": A})
    no = C.leg_hits(s, {"kind": "race_win", "athlete": A, "side": "no"})
    assert np.array_equal(yes + no, np.ones(4))
    under = C.leg_hits(s, {"kind": "race_n_classified", "line": 3.5, "side": "under"})
    assert under.mean() == 0.0


def test_win_and_fastest_lap_correlated_price_above_the_product():
    s = _race()
    a = s.entrants[0]
    out = C.price([{"kind": "race_win", "athlete": a}, {"kind": "race_fastest_lap", "athlete": a}], s)
    assert out["fair"] > 1.5 * out["independent"]
    assert out["lift"] > 1.5


def test_leg_errors_are_clear():
    s = _factorial()
    with pytest.raises(ValueError, match="race_teleport"):
        C.combo_fair([{"kind": "race_teleport", "athlete": A}, {"kind": "race_win", "athlete": A}], s)
    with pytest.raises(ValueError, match="champion.*not decided per simulation"):
        C.check_legs([{"kind": "champion", "athlete": A}, {"kind": "race_win", "athlete": A}])
    with pytest.raises(ValueError, match="race_safety_car"):
        C.check_legs([{"kind": "race_safety_car"}, {"kind": "race_win", "athlete": A}])
    with pytest.raises(ValueError, match=r"legs\[1\]: kind race_h2h needs pair"):
        C.check_legs([{"kind": "race_win", "athlete": A}, {"kind": "race_h2h", "athlete": A}])
    with pytest.raises(ValueError, match="at least two legs"):
        C.check_legs([{"kind": "race_win", "athlete": A}])
    with pytest.raises(ValueError, match="needs line"):
        C.check_legs([{"kind": "race_n_classified"}, {"kind": "race_win", "athlete": A}])
    with pytest.raises(ValueError, match="shared timing draw"):
        C.check_legs([{"kind": "race_first_retirement", "athlete": A}, {"kind": "race_second_retirement", "athlete": B}])
    with pytest.raises(ValueError, match="leg race_win: athlete 99 is not an entrant"):
        C.leg_hits(s, {"kind": "race_win", "athlete": 99})
    no_fl = OutcomeSims(entrants=s.entrants, rank=s.rank, finished=s.finished)
    with pytest.raises(ValueError, match="race_fastest_lap: these simulations don't draw it"):
        C.combo_fair([{"kind": "race_win", "athlete": A}, {"kind": "race_fastest_lap", "athlete": A}], no_fl)


def _res():
    return pd.DataFrame(dict(athlete_id=[A, B, CC, D], position=[1, 2, 3, 4], status=["OK", "OK", "OK", "DNF"],
                             qual_position=[1, 2, 3, 4], team_id=[1, 1, 2, 2], points=[25, 18, 15, 0]))


def test_settle_rules():
    res = _res()
    win_a, win_b = {"kind": "race_win", "athlete": A}, {"kind": "race_win", "athlete": B}
    h2h = {"kind": "race_h2h", "pair": [A, B]}
    assert C.settle([win_a, h2h], res) is True
    assert C.settle([win_b, h2h], res) is False
    missing = {"kind": "race_h2h", "pair": [A, 99]}                 # an absent opponent: the leg is void
    assert C.settle([win_a, missing], res) is None
    assert C.settle([win_a, missing], res, void_leg="drop_leg") is True
    assert C.settle([win_b, missing], res, void_leg="drop_leg") is False
    fl = {"kind": "race_fastest_lap", "athlete": A}
    assert C.settle([win_a, fl], res) is None                      # manual: the results record no fastest lap
    assert C.settle([win_b, fl], res) is False                     # a losing leg settles it anyway
    with pytest.raises(ValueError, match="void_leg"):
        C.settle([win_a, h2h], res, void_leg="refund")


def _book_with(market):
    return {"book": dict(venue="book_a", event="2026-17", captured_utc="2026-10-06T05:33Z", source="paste",
                         odds="decimal", currency="USDT"),
            "lines": [dict(title="Race Winner and Fastest Lap", selection="X and X", odds=6.5, market=market)]}


def test_book_schema_takes_a_combo_line():
    good = {"kind": "combo", "void_leg": "void_all",
            "legs": [{"kind": "race_win", "driver": "Max Verstappen"},
                     {"kind": "race_fastest_lap", "driver": "Max Verstappen"}]}
    assert S.validate_book(_book_with(good))
    for bad, msg in [({"kind": "combo", "legs": [good["legs"][0]]}, "at least two legs"),
                     (dict(good, void_leg="refund"), "void_leg"),
                     ({"kind": "combo", "legs": [good["legs"][0], {"kind": "race_teleport", "driver": "x"}]},
                      "legs[1].kind"),
                     ({"kind": "combo", "legs": [good["legs"][0], good]}, "can't hold a combo"),
                     ({"kind": "combo", "legs": [good["legs"][0], {"kind": "race_win"}]}, "names a driver")]:
        with pytest.raises(S.BookError) as ex:
            S.validate_book(_book_with(bad))
        assert any(msg in p for p in ex.value.problems), (msg, ex.value.problems)
