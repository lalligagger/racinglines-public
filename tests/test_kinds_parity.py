"""Every supportable kind as a row of markets/kinds.toml (C11): the file is the whole registry (legacy payoffs and
declarative specs), and each kind added for parity with the exchanges' listings prices from what the simulations
already draw and settles from the stored results, or says it can't (None). Synthetic data, hand-checked numbers."""

import numpy as np
import pandas as pd
import pytest

from racinglines.markets import kinds as K
from racinglines.markets import payoffs as P
from racinglines.models import outcomes as O

pytestmark = pytest.mark.quick


# --- the file is the registry ----------------------------------------------------------------------------------------

def test_every_kind_is_a_row_of_the_file_in_file_order():
    rows = P.entries()
    assert [e["code"] for e in rows] == list(K.KINDS)
    legacy = [e["code"] for e in rows if isinstance(e["payoff"], str)]
    assert legacy == [k.code for k in K.LEGACY] and list(K.KINDS)[:len(legacy)] == legacy     # legacy rows first
    assert K.KINDS["race_win"] == K.Kind("race_win", "top_n", n=1, label="Win")
    assert K.KINDS["race_sprint_h2h"].subject == "pair" and K.KINDS["race_constructor_top"].subject == "team"
    assert K.KINDS["constructors_p3"].subject == "team" and K.KINDS["standings_p3"].exact
    assert K.KINDS["race_sprint_top5"].session == "sprint" and K.KINDS["race_constructor_h2h"].subject == "team"
    assert all(len(c) <= 30 for c in K.KINDS)                 # market_links.prediction is a String(30)
    assert not any(K.KINDS[c].default for c in list(K.KINDS)[list(K.KINDS).index("race_qual_top3"):])


@pytest.mark.parametrize("row,match", [
    ('payoff = "top_n"', r"\.n: payoff top_n needs it"),
    ('payoff = "stage_top_n"\nn = 1', r"\.stage: payoff stage_top_n needs it"),
    ('payoff = "fastest"', r"\.payoff: 'fastest'"),
    ('payoff = "top_n"\nn = 3\ncolour = "red"', r"unknown fields \['colour'\]"),
])
def test_a_bad_legacy_row_names_its_field(tmp_path, row, match):
    f = tmp_path / "kinds.toml"
    f.write_text(f'[[kinds]]\ncode = "race_x"\nlabel = "X"\n{row}\n')
    with pytest.raises(ValueError, match=match):
        K.load(f)


def test_the_file_refuses_order_length_and_bad_specs(tmp_path):
    f = tmp_path / "kinds.toml"
    spec = '[[kinds]]\ncode = "race_s"\ndefault = false\npayoff = { subject = "driver", predicate = "retired" }\n'
    f.write_text(spec + '[[kinds]]\ncode = "race_l"\npayoff = "top_n"\nn = 2\n')
    with pytest.raises(ValueError, match="legacy payoff after a declarative kind"):
        K.load(f)
    f.write_text(f'[[kinds]]\ncode = "{"x" * 31}"\npayoff = "h2h"\n')
    with pytest.raises(ValueError, match="30 characters"):
        K.load(f)
    for payoff, field in [('{ subject = "team", predicate = "stage_top", n = 1, aggregate = "any" }', "stage"),
                          ('{ subject = "team", predicate = "indicator", aggregate = "any" }', "of"),
                          ('{ subject = "team", predicate = "points", aggregate = "any", compare = "rank", place = 2 }',
                           "aggregate"),
                          ('{ subject = "team", predicate = "points", aggregate = "total", compare = "rank" }', "place"),
                          ('{ subject = "team", predicate = "points", aggregate = "total" }', "compare"),
                          ('{ subject = "driver", predicate = "top", n = 3, compare = "ahead" }', "compare"),
                          ('{ subject = "driver", predicate = "points" }', "predicate")]:
        f.write_text(f'[[kinds]]\ncode = "race_y"\ndefault = false\npayoff = {payoff}\n')
        with pytest.raises(ValueError, match=rf"race_y\)\.payoff\.{field}:"):
            P.load(f)


# --- simulations: 6 cars on teams a, a, b, b, c, c; 4 simulations ------------------------------------------------------

def _sims(indicator=True):
    rank = np.array([[1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1], [1, 6, 2, 5, 3, 4], [2, 3, 1, 4, 5, 6]], float)
    pts = np.array([[25, 18, 15, 12, 10, 8], [8, 10, 12, 15, 18, 25], [25, 8, 18, 10, 15, 12], [10, 10, 15, 5, 0, 0]],
                   float)
    fin = np.ones_like(rank, bool)
    fin[1, 1] = False                                    # car 2 retires in simulation 2 (ranked 5th, not classified)
    qual = np.array([[2, 1, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6], [3, 4, 1, 2, 5, 6], [6, 5, 4, 3, 2, 1]], float)
    sprint = np.array([[1, 2, 3, 4, 5, 6]] * 2 + [[6, 5, 4, 3, 2, 1]] * 2, float)
    fl = np.zeros_like(fin)
    fl[[0, 1, 2, 3], [0, 5, 2, 0]] = True                # fastest lap: car 1, 6, 3, 1
    return O.OutcomeSims(entrants=[1, 2, 3, 4, 5, 6], rank=rank, finished=fin, points=pts,
                         groups=["a", "a", "b", "b", "c", "c"], stage_rank={"qual": qual, "sprint": sprint},
                         stage_finished={"sprint": np.ones_like(fin)}, stage_points={"sprint": np.zeros_like(pts)},
                         indicators={"race_fastest_lap": fl} if indicator else {})


def test_exact_place_and_top20():
    s = _sims()
    places = [K.fair(f"race_p{n}", s) for n in (2, 3, 4, 5)]
    np.testing.assert_allclose(places[0], [0.25, 0.25, 0.25, 0, 0.25, 0])   # 2nd: car 2, 5, 3, 1
    np.testing.assert_allclose(places[3], [0, 0, 0, 0.25, 0.5, 0])          # 5th: car 5, (2 retired), 4, 5
    np.testing.assert_allclose(K.fair("race_p2", s, a=1), 0.25)
    np.testing.assert_allclose(sum(places) + K.fair("race_win", s), K.fair("race_top5", s))      # 1st .. 5th = top 5
    assert K.fair("race_p5", s, a=2) == 0.0                                 # ranked 5th in sim 2, but retired
    np.testing.assert_allclose(K.fair("race_top20", s), s.finished.mean(0))


def test_sprint_top5_and_top10_are_the_sprints_own_classification():
    s = _sims()
    np.testing.assert_allclose(K.fair("race_sprint_top5", s), [0.5, 1, 1, 1, 1, 0.5])
    np.testing.assert_allclose(K.fair("race_sprint_top10", s), np.ones(6))
    np.testing.assert_allclose(K.fair("race_sprint_top5", s), K.fair("race_top5", s.at("sprint")))


def test_constructor_pole_and_fastest_lap_are_team_aggregates():
    s = _sims()
    assert K.fair("race_constructor_pole", s) == {"a": 0.5, "b": 0.25, "c": 0.25}     # pole: car 2, 1, 3, 6
    assert K.fair("race_constructor_fastest_lap", s) == {"a": 0.5, "b": 0.25, "c": 0.25}  # fastest: 1, 6, 3, 1
    with pytest.raises(ValueError, match="race_constructor_fastest_lap: these simulations don't draw"):
        K.fair("race_constructor_fastest_lap", _sims(indicator=False))


def test_constructor_points_rank_and_head_to_head():
    s = _sims()
    # team points: sim 1 a 43 b 27 c 18; sim 2 a 18 b 27 c 43; sim 3 a 33 b 28 c 27; sim 4 a 20 b 20 c 0, b ahead on
    # the countback (car 3 won)
    assert K.fair("race_constructor_p2", s) == {"a": 0.25, "b": 0.75, "c": 0.0}
    assert K.fair("race_constructor_p3", s) == {"a": 0.25, "b": 0.0, "c": 0.75}
    for n in (2, 3, 4, 5):
        assert sum(K.fair(f"race_constructor_p{n}", s).values()) == pytest.approx(1.0 if n <= 3 else 0.0)
    assert K.fair("race_constructor_h2h", s, a="a", b="b") == 0.5
    assert K.fair("race_constructor_h2h", s, a="a", b="c") == 0.75
    m = K.fair("race_constructor_h2h", s)
    assert m["c"]["a"] == 0.25 and all(m[x][y] + m[y][x] == pytest.approx(1) for x in m for y in m[x])


def test_a_tie_the_countback_cannot_break_splits_the_place():
    above, tied = P.team_order(np.array([[10.0, 10.0, 5.0]]), np.array([[np.inf, np.inf, 3.0]]))
    np.testing.assert_allclose(P.place_share(above, tied, 1), [[0.5, 0.5, 0]])
    np.testing.assert_allclose(P.place_share(above, tied, 3), [[0, 0, 1]])


def test_double_podium():
    assert K.fair("race_team_double_podium", _sims()) == {"a": 0.5, "b": 0.0, "c": 0.25}   # sims 1 and 4; sim 2


def test_standings_places_from_a_season_simulation():
    rank = np.array([[1, 2, 3], [2, 1, 3], [3, 2, 1], [2, 3, 1]])
    ss = O.SeasonSims(entrants=[7, 8, 9], rank=rank, points=-rank.astype(float))
    np.testing.assert_allclose(K.season_fair("standings_p2", ss), [0.5, 0.5, 0])
    assert K.season_fair("standings_p3", ss, a=9) == 0.5
    np.testing.assert_allclose(K.season_fair("champion", ss), (rank == 1).mean(0))     # n = 1, at most
    teams = O.SeasonSims(entrants=["a", "b", "c"], rank=rank, points=-rank.astype(float))
    assert K.season_fair("constructors_p2", teams, a="b") == 0.5
    assert K.season_fair("constructors_champion", teams, a="c") == 0.5
    for code in ("standings_p2", "constructors_p4"):
        with pytest.raises(ValueError):
            K.fair(code, _sims())                       # a season market: not from one race's simulations
        assert K.settle(code, 7, None, RES) is None     # settled by the venue


# --- settlement from the results frame ----------------------------------------------------------------------------

RES = pd.DataFrame(dict(
    athlete_id=[1, 2, 3, 4, 5, 6, 7], position=[1, 2, 3, 4, 5, 6, 7], status=["OK"] * 5 + ["DNF", "OK"],
    qual_position=[3, 1, 2, 4, 5, None, 6], team_id=["a", "a", "b", "b", "c", "c", "d"],
    points=[25.0, 18, 15, 12, 10, 0, 0],
    sprint_position=[2, 1, 3, 4, 5, 6, None], sprint_status=["OK"] * 6 + [None], sprint_points=[7.0, 8, 6, 5, 4, 3, None]))


@pytest.mark.parametrize("kind,ath,params,want", [
    ("race_p2", 2, None, True), ("race_p2", 1, None, False), ("race_p2", 9, None, False),
    ("race_p5", 5, None, True), ("race_p4", 6, None, False),
    ("race_top20", 6, None, False), ("race_top20", 7, None, True), ("race_top20", 9, None, False),
    ("race_sprint_top5", 5, None, True), ("race_sprint_top5", 6, None, False), ("race_sprint_top5", 7, None, False),
    ("race_sprint_top10", 6, None, True),
    ("race_constructor_pole", None, {"team": "a"}, True), ("race_constructor_pole", None, {"team": "c"}, False),
    ("race_constructor_pole", None, {"team": "z"}, None),
    ("race_constructor_fastest_lap", None, {"team": "a"}, None),        # not in the results: the venue settles it
    # team points: a 43, b 27, c 10, d 0
    ("race_constructor_p2", None, {"team": "b"}, True), ("race_constructor_p2", None, {"team": "a"}, False),
    ("race_constructor_p3", None, {"team": "c"}, True), ("race_constructor_p4", None, {"team": "d"}, True),
    ("race_constructor_p5", None, {"team": "d"}, False),
    ("race_constructor_h2h", None, {"team": "b", "opponent": "a"}, False),
    ("race_constructor_h2h", None, {"team": "c", "opponent": "d"}, True),
    ("race_constructor_h2h", None, {"team": "c", "opponent": None}, None),
    ("race_team_double_podium", None, {"team": "a"}, True), ("race_team_double_podium", None, {"team": "b"}, False),
])
def test_settlement(kind, ath, params, want):
    assert K.settle(kind, ath, params, RES) == want


def test_settlement_edge_cases():
    no_qual = RES.assign(qual_position=None)
    assert K.settle("race_constructor_pole", None, {"team": "a"}, no_qual) is None      # qualifying not stored yet
    assert K.settle("race_sprint_top5", 1, None, RES.drop(columns=["sprint_position"])) is None
    podium = RES.assign(position=[1, 4, 2, 3, 5, 6, 7])
    assert K.settle("race_team_double_podium", None, {"team": "a"}, podium) is False
    assert K.settle("race_team_double_podium", None, {"team": "b"}, podium) is True
    # equal points, the countback decides: c and d both on 4, c's best car 5th, d's 7th
    even = RES.assign(points=[25.0, 18, 15, 12, 4, 0, 4])
    assert K.settle("race_constructor_p3", None, {"team": "c"}, even) is True
    assert K.settle("race_constructor_h2h", None, {"team": "d", "opponent": "c"}, even) is False
    # neither has a car placed and both have 0 points: tied for 3rd, undecided
    unplaced = RES.assign(points=[25.0, 18, 15, 12, 0, 0, 0], position=[1, 2, 3, 4, None, None, None])
    assert K.settle("race_constructor_p3", None, {"team": "c"}, unplaced) is None
    assert K.settle("race_constructor_h2h", None, {"team": "c", "opponent": "d"}, unplaced) is None
    assert K.settle("race_constructor_p2", None, {"team": "b"}, unplaced) is True


def test_team_markets_settle_through_the_private_book_team_keys():
    from racinglines.markets import private_book as house
    from racinglines.models.position_sim.model import team_key
    names = ["McLaren", "McLaren", "Ferrari", "Ferrari", "Haas F1 Team", "Haas F1 Team", "Alpine"]
    res = RES.assign(team_id=names)
    haas, alpine = team_key("Haas F1 Team"), team_key("Alpine")
    assert house.outcome_for("race_constructor_p2", None, {"team": team_key("Ferrari")}, res) is True
    assert house.outcome_for("race_constructor_pole", None, {"team": team_key("McLaren")}, res) is True
    assert house.outcome_for("race_constructor_h2h", None, {"team": haas, "opponent": alpine}, res) is True


def test_every_race_kind_added_prices_on_position_sim():
    """The F1 position_sim's own simulations price every race kind added here (the fastest-lap team kind only from a
    run that draws the fastest lap, as race_fastest_lap)."""
    from racinglines.models.position_sim import pricing as run
    from racinglines.testing import synthetic as SY
    m = run.Measurements.from_frames(*SY.f1_frames())
    hist = run.history(m)
    eid = int(m.drivers["event_id"].max())
    cutoff = m.sessions(eid)["qual"] + pd.Timedelta(hours=2)
    _, ex = run.price_race(m, hist, cutoff, eid, n_sims=400, rng=np.random.default_rng(5))
    s = O.from_position_sim(ex["entrants"], ex["sim"])
    exact = sum(K.fair(f"race_p{n}", s) for n in (2, 3, 4, 5)) + K.fair("race_win", s)
    np.testing.assert_allclose(exact, K.fair("race_top5", s))
    assert np.all(K.fair("race_top20", s) >= K.fair("race_top10", s))
    assert sum(K.fair("race_constructor_pole", s).values()) == pytest.approx(1.0)
    for n in (2, 3, 4, 5):
        assert sum(K.fair(f"race_constructor_p{n}", s).values()) == pytest.approx(1.0)
    h = K.fair("race_constructor_h2h", s)
    assert all(h[x][y] + h[y][x] == pytest.approx(1.0) for x in h for y in h[x])
    assert all(0 <= p <= 1 for p in K.fair("race_team_double_podium", s).values())
