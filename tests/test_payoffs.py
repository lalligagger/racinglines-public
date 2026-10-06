"""Declarative market kinds (racinglines/markets/payoffs.py, markets/kinds.toml): every kind in the file loads with a
valid spec and is in the registry after the legacy kinds, a bad spec fails naming its field, and the two generic
functions price and settle a spec that is not in the file. Synthetic data."""

import numpy as np
import pandas as pd
import pytest

from racinglines.markets import kinds as K
from racinglines.markets import payoffs as P
from racinglines.models import outcomes as O

pytestmark = pytest.mark.quick


def test_every_kind_in_the_file_loads_with_a_valid_spec():
    got = P.load()
    assert len(got) == 13
    for code, e in got.items():
        assert e["code"] == code and e["label"] and e["default"] is False
        assert P.check(e["payoff"]) is e["payoff"] and P.check(e["settle"]) is e["settle"]
        assert {f: v for f, v in e["settle"].items() if f != "absent"} == e["payoff"]   # settlement uses the same spec
        k = K.KINDS[code]
        assert k.payoff == "spec" and k.spec is e and not k.default and k.label == e["label"]
    # the registry: legacy kinds first, then the file's order
    assert list(K.KINDS)[-len(got):] == list(got)
    assert all(K.KINDS[c].spec is None for c in list(K.KINDS)[:-len(got)])


@pytest.mark.parametrize("spec,field", [
    ({"subject": "driver", "predicate": "podium"}, "predicate"),
    ({"subject": "pair", "predicate": "classified"}, "subject"),
    ({"subject": "team", "predicate": "classified", "aggregate": "most"}, "aggregate"),
    ({"subject": "team", "predicate": "classified"}, "aggregate"),
    ({"subject": "driver", "predicate": "classified", "aggregate": "any"}, "aggregate"),
    ({"subject": "driver", "predicate": "top"}, "n"),
    ({"subject": "driver", "predicate": "nth_retired", "n": 0}, "n"),
    ({"subject": "field", "predicate": "retired", "aggregate": "count"}, "compare"),
    ({"subject": "field", "predicate": "retired", "aggregate": "count", "compare": "under"}, "compare"),
    ({"subject": "team", "predicate": "classified", "aggregate": "all", "compare": "over"}, "compare"),
    ({"subject": "driver", "predicate": "classified", "absent": "maybe"}, "absent"),
])
def test_a_bad_spec_names_its_field(spec, field):
    with pytest.raises(ValueError, match=rf"spec\.{field}:"):
        P.check(spec)


def test_a_bad_file_names_the_kind_and_field(tmp_path):
    f = tmp_path / "kinds.toml"
    f.write_text('[[kinds]]\ncode = "race_x"\nlabel = "X"\ndefault = false\n'
                 'payoff = { subject = "team", predicate = "fastest", aggregate = "any" }\n')
    with pytest.raises(ValueError, match=r"race_x\)\.payoff\.predicate: 'fastest'"):
        P.load(f)
    f.write_text('[[kinds]]\ncode = "race_y"\nlabel = "Y"\ndefault = false\n'
                 'payoff = { subject = "team", predicate = "top", n = 3, aggregate = "sideways" }\n')
    with pytest.raises(ValueError, match=r"race_y\)\.payoff\.aggregate: 'sideways'"):
        P.load(f)
    f.write_text('[[kinds]]\ncode = "race_z"\nlabel = "Z"\ndefault = true\npayoff = { subject = "driver", predicate = "retired" }\n')
    with pytest.raises(ValueError, match=r"race_z\)\.default"):
        P.load(f)


# a market not in the file: a team with at least one car in the top 5
TEAM_TOP5 = {"subject": "team", "predicate": "top", "n": 5, "aggregate": "any"}


def test_a_spec_not_in_the_file_prices():
    rng = np.random.default_rng(1)
    rank = np.argsort(rng.random((400, 8)), axis=1) + 1.0
    fin = rng.random((400, 8)) < 0.9
    groups = ["a", "a", "b", "b", "c", "c", "d", "d"]
    sims = O.OutcomeSims(entrants=list(range(1, 9)), rank=rank, finished=fin, groups=groups)
    got = P.fair(TEAM_TOP5, sims)
    hit = (rank <= 5) & fin
    g = np.array(groups)
    assert got == {t: float(hit[:, g == t].any(axis=1).mean()) for t in "abcd"}
    # the same predicate per driver, and over the field with a line
    np.testing.assert_array_equal(P.fair({"subject": "driver", "predicate": "top", "n": 5}, sims), hit.mean(0))
    assert P.fair({"subject": "driver", "predicate": "top", "n": 5}, sims, a=3) == hit[:, 2].mean()
    over = {"subject": "field", "predicate": "top", "n": 5, "aggregate": "count", "compare": "over"}
    assert P.fair(over, sims, line=4.5) == float((hit.sum(axis=1) > 4.5).mean())
    with pytest.raises(ValueError, match="needs a line"):
        P.fair(over, sims)
    with pytest.raises(ValueError, match="need groups"):
        P.fair(TEAM_TOP5, O.OutcomeSims(entrants=[1], rank=np.ones((1, 1)), finished=np.ones((1, 1), bool)))


RES = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4, 5, 6], position=[1, 2, 3, 6, 4, 5],
                        status=["OK", "OK", "OK", "OK", "DNF", "DNS"], team_id=["a", "b", "c", "c", "a", "d"]))


@pytest.mark.parametrize("spec,ath,params,want", [
    (TEAM_TOP5, None, {"team": "a"}, True), (TEAM_TOP5, None, {"team": "c"}, True),
    (TEAM_TOP5, None, {"team": "d"}, False),                       # a DNS is not classified
    (TEAM_TOP5, None, {"team": "z"}, None),
    ({**TEAM_TOP5, "aggregate": "all"}, None, {"team": "c"}, False),
    ({"subject": "driver", "predicate": "top", "n": 5}, 4, None, False),
    ({"subject": "driver", "predicate": "top", "n": 5}, 9, None, None),                   # absent: void by default
    ({"subject": "driver", "predicate": "top", "n": 5, "absent": "no"}, 9, None, False),
    ({"subject": "driver", "predicate": "retired"}, 6, None, None),                       # DNS: void
    ({"subject": "team", "predicate": "retired", "aggregate": "any"}, None, {"team": "d"}, None),
    ({"subject": "team", "predicate": "retired", "aggregate": "any"}, None, {"team": "a"}, True),
    ({"subject": "field", "predicate": "classified", "aggregate": "count", "compare": "over"}, None, {"line": 3.5}, True),
    ({"subject": "field", "predicate": "classified", "aggregate": "count", "compare": "over"}, None, None, None),
])
def test_a_spec_not_in_the_file_settles(spec, ath, params, want):
    assert P.settle(spec, ath, params, RES) is want


def test_team_settlement_reads_the_group_key():
    key = {"a": "alpha", "b": "beta", "c": "gamma", "d": "delta"}.get
    assert P.settle(TEAM_TOP5, None, {"team": "alpha"}, RES, group_key=key) is True
    assert P.settle(TEAM_TOP5, None, {"team": "a"}, RES, group_key=key) is None
