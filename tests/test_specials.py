"""Sportsbook-style specials (models/position_sim/specials.py): sim pricing, settlement and odds helpers, on
synthetic simulations."""

import numpy as np
import pandas as pd
import pytest

from racinglines.models.position_sim import specials as S

IDS, TEAMS = [1, 2, 3, 4], ["a", "a", "b", "b"]


def _sim():
    # 4 sims x 4 drivers. pos: finishing order (DNFs last); dnf flags
    pos = np.array([[1, 2, 3, 4], [2, 1, 4, 3], [1, 4, 3, 2], [3, 4, 1, 2]], float)
    dnf = np.array([[0, 0, 0, 0], [0, 0, 0, 1], [0, 1, 0, 0], [1, 1, 0, 0]], bool)
    return dict(pos=pos, dnf=dnf)


@pytest.mark.quick
def test_sim_probabilities_by_counting():
    sim = _sim()
    assert S.sim_prob(dict(kind="classified", athlete=4), sim, IDS, TEAMS)[0] == 0.75
    assert S.sim_prob(dict(kind="team_classified", team="a"), sim, IDS, TEAMS)[0] == 0.5     # sims 1, 2 only
    assert S.sim_prob(dict(kind="n_classified", line=2.5), sim, IDS, TEAMS)[0] == 0.75      # 4, 3, 3, 2 finish
    p, void = S.sim_prob(dict(kind="h2h", a=1, b=2), sim, IDS, TEAMS)
    assert void == 0.25 and p == pytest.approx(2 / 3)       # sim 4 void (both out); 1 wins sims 1, 3 (2 retires), loses sim 2
    p, void = S.sim_prob(dict(kind="h2h", a=1, b=2, both_dnf="behind"), sim, IDS, TEAMS)
    assert void == 0 and p == 0.5                           # sims 1 and 3 (2 is out)
    assert S.sim_prob(dict(kind="last_classified", athlete=4), sim, IDS, TEAMS)[0] == 0.5    # sims 1 and 4


@pytest.mark.quick
def test_settle_matches_the_sim_rules():
    actual = pd.DataFrame(dict(athlete_id=IDS, team_key=TEAMS, status=["OK", "DNF", "OK", "OK"],
                               position=[1, 20, 2, 3]))
    assert S.settle(dict(kind="classified", athlete=2), actual) == 0
    assert S.settle(dict(kind="team_classified", team="b"), actual) == 1
    assert S.settle(dict(kind="team_points", team="a"), actual) == 0
    assert S.settle(dict(kind="n_classified", line=2.5), actual) == 1
    assert S.settle(dict(kind="last_classified", athlete=4), actual) == 1
    assert S.settle(dict(kind="h2h", a=1, b=2), actual) == 1
    out = actual.assign(status=["DNF", "DNF", "OK", "OK"])
    assert S.settle(dict(kind="h2h", a=1, b=2), out) is None
    assert S.settle(dict(kind="h2h", a=1, b=2, both_dnf="behind"), out) == 0


@pytest.mark.quick
def test_board_lists_every_family_and_prices_it():
    ent = pd.DataFrame(dict(athlete_id=IDS, driver=list("ABCD"), team_key=TEAMS))
    specs = S.board(ent, h2h_pairs="teammates")
    kinds = {s["kind"] for s in specs}
    assert kinds == set(S.KINDS)
    assert sum(s["kind"] == "h2h" for s in specs) == 4         # two teammate pairs, both directions
    t = S.price(specs, _sim(), ent)
    assert len(t) == len(specs) and t["prob"].between(0, 1).all()


@pytest.mark.quick
def test_odds_formats_devig_and_half_kelly():
    assert S.decimal("+230") == pytest.approx(3.3) and S.decimal(-150) == pytest.approx(1 + 2 / 3)
    assert S.decimal("7/2") == 4.5 and S.decimal(2.5) == 2.5
    assert S.devig(["-110", "-110"]).tolist() == pytest.approx([0.5, 0.5])
    assert S.devig(["1/16", "13/2"]).sum() == pytest.approx(1.0)
    priced = pd.DataFrame(dict(kind=["classified"], label=["X classified"], prob=[0.6], void=[0.0]))
    e = S.edge_table(priced, {"X classified": 2.0}, bankroll=400)
    assert e["edge"].iloc[0] == pytest.approx(0.2) and e["half_kelly_stake"].iloc[0] == pytest.approx(400 * 0.5 * 0.2)


@pytest.mark.quick
def test_decimal_board_is_not_misread_as_american():
    assert S.decimal(501.0, "decimal") == 501.0 and S.decimal(501.0) == pytest.approx(6.01)   # auto reads it as +501
    ent = pd.DataFrame(dict(athlete_id=IDS, driver=["A A", "B B", "C C", "D D"], team_key=TEAMS))
    book = pd.DataFrame(dict(market=["race_win"] * 2, subject=["A", "D"], odds=[2.0, 501.0]))
    t = S.price_book(book, _sim(), ent)
    assert t["odds"].tolist() == [2.0, 501.0]
    assert t["book_prob"].sum() == pytest.approx(1.0)
    t = S.price_book(book, _sim(), ent, extra={"race_win": {"A": 0.9}}, thin=("race_win",))
    assert (t["half_kelly_stake"] == 0).all()


@pytest.mark.quick
def test_sprint_markets_price_from_the_sprint_sim_not_the_race_sim():
    ent = pd.DataFrame(dict(athlete_id=IDS, driver=["A A", "B B", "C C", "D D"], team_key=TEAMS))
    race = dict(pos=np.array([[1, 2, 3, 4.0]] * 4), dnf=np.zeros((4, 4), bool))
    sprint = dict(pos=np.array([[2, 1, 3, 4.0]] * 4), dnf=np.zeros((4, 4), bool))
    book = pd.DataFrame(dict(market=["sprint_win", "sprint_team_win", "race_win"], subject=["B", "a", "A"], odds=[2.0, 1.5, 2.0]))
    t = S.price_book(book, race, ent, sprint=sprint, thin=("sprint_win",)).set_index("market")
    assert t.loc["sprint_win", "prob"] == 1.0 and t.loc["sprint_team_win", "prob"] == 1.0
    assert t.loc["race_win", "prob"] == 1.0 and t.loc["sprint_win", "half_kelly_stake"] == 0.0


@pytest.mark.quick
def test_any_session_rank_odds_and_book_markets():
    ent = pd.DataFrame(dict(athlete_id=IDS, driver=["A A", "B B", "C C", "D D"], team_key=TEAMS))
    fp = dict(pos=np.array([[2, 1, 3, 4.0], [1, 2, 3, 4.0], [1, 3, 2, 4.0], [2, 1, 4, 3.0]]), dnf=np.zeros((4, 4), bool))
    t = S.rank_table(fp, ent, tops=(1, 2))
    assert t.set_index("driver").loc["A A", "top1"] == 0.5 and t.set_index("driver").loc["A A", "top2"] == 1.0
    assert t["r1"].sum() == pytest.approx(1.0)
    book = pd.DataFrame(dict(market=["fp1_win", "fp1_top2"], subject=["B", "B"], odds=[3.0, 1.5]))
    out = S.price_book(book, _sim(), ent, session_sims={"fp1": fp}, thin=("fp1_win",)).set_index("market")
    assert out.loc["fp1_win", "prob"] == 0.5 and out.loc["fp1_top2", "prob"] == 0.75
