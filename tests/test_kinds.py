"""Market kinds as payoffs (racinglines/markets/kinds.py) on the shared simulation shape
(racinglines/models/outcomes.py): each model's own summary equals the catalogue's fair values exactly,
and settlement is what private_book.outcome_for returned before it moved there. Synthetic data."""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from racinglines.markets import kinds as K
from racinglines.markets import private_book as house
from racinglines.models import outcomes as O

pytestmark = pytest.mark.quick


@pytest.fixture(scope="module")
def f1_priced():
    from racinglines.models.position_sim import pricing as run
    from racinglines.testing import synthetic as SY
    m = run.Measurements.from_frames(*SY.f1_frames())
    hist = run.history(m)
    eid = int(m.drivers["event_id"].max())
    cutoff = m.sessions(eid)["qual"] + pd.Timedelta(hours=2)
    return run.price_race(m, hist, cutoff, eid, n_sims=600, rng=np.random.default_rng(3))


def test_f1_summary_equals_the_catalogue(f1_priced):
    summ, ex = f1_priced
    sims = O.from_position_sim(ex["entrants"], ex["sim"])
    got = K.summary(sims).set_index("athlete_id")
    want = summ.set_index("athlete_id").loc[got.index]
    for kind, col in (("race_win", "win_prob"), ("race_podium", "podium_prob"), ("race_top10", "top10_prob"),
                      ("race_pole", "pole_prob")):
        np.testing.assert_array_equal(got[kind].to_numpy(), want[col].to_numpy(), err_msg=kind)


def test_f1_head_to_heads_equal_price_race(f1_priced):
    summ, ex = f1_priced
    sims = O.from_position_sim(ex["entrants"], ex["sim"])
    for _, r in summ.head(4).iterrows():
        for b, p in list(r["h2h"].items())[:5]:
            assert round(K.fair("race_h2h", sims, r["athlete_id"], int(b)), 4) == p


def test_constructor_top_is_a_distribution_close_to_price_race(f1_priced):
    _, ex = f1_priced
    got = K.fair("race_constructor_top", O.from_position_sim(ex["entrants"], ex["sim"]))
    assert abs(sum(got.values()) - 1) < 1e-9
    # price_race breaks ties with random noise, the catalogue splits them: equal up to tie weight
    for team, p in ex["constructor_top"].items():
        assert abs(got[team] - p) < 0.02


@pytest.fixture(scope="module")
def dh_sim():
    from racinglines.models import timed_runs as P
    from racinglines.models.timed_runs import model as TM
    from racinglines.sources.chronorace.parse import parse_markdown_tables_file
    from racinglines.testing import synthetic as SY
    d = Path(tempfile.mkdtemp(prefix="racinglines-test-"))
    for name, text in SY.mtb_results_md().items():
        (d / name).write_text(text)
    raw = pd.concat([pd.DataFrame(parse_markdown_tables_file(f)) for f in sorted(d.glob("*.md"))], ignore_index=True)
    raw = raw[raw["round"].isin(P.RUN_WEIGHTS)]
    model = TM.fit_season_model(P.select_target(raw, None, "ME"), category="ME")
    riders = list(model["mu"].index[:25])
    sim = TM.simulate_weekend(model, riders, n_sims=500, rng=np.random.default_rng(4))
    return model, riders, sim


def test_downhill_summary_equals_the_catalogue(dh_sim):
    from racinglines.models.timed_runs import model as TM
    model, riders, sim = dh_sim
    got = K.summary(O.from_timed_runs(riders, sim)).set_index("athlete_id")
    want = TM.summarize_weekend(model, riders, sim).set_index("rider_id").loc[got.index]
    for kind, col in (("race_win", "win_prob"), ("race_podium", "podium_prob"), ("race_top10", "top10_prob"),
                      ("race_make_final", "make_final_prob")):
        np.testing.assert_array_equal(got[kind].to_numpy(), want[col].to_numpy(), err_msg=kind)


def test_one_winner_and_complementary_head_to_heads(dh_sim):
    _, riders, sim = dh_sim
    sims = O.from_timed_runs(riders, sim)
    assert abs(K.fair("race_win", sims).sum() - 1) < 1e-9
    h = K.h2h_matrix(sims)
    both = np.isfinite(sims.rank[:, :, None]) & np.isfinite(sims.rank[:, None, :])
    off = both.all(0) & ~np.eye(len(riders), dtype=bool)          # always both classified, not oneself
    assert off.any() and np.allclose((h + h.T)[off], 1.0)


RES = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4, 5], position=[1, 2, 3, 4, 20], status=["OK"] * 4 + ["DNF"],
                        qual_position=[2, 1, 3, None, 5], team_id=["a", "b", "a", "c", "b"],
                        points=[25.0, 18, 15, 12, 0]))


@pytest.mark.parametrize("kind,ath,params,want", [
    ("race_win", 1, None, True), ("race_win", 2, None, False), ("race_win", 9, None, False),
    ("race_podium", 3, None, True), ("race_podium", 4, None, False), ("race_top10", 5, None, False),
    ("race_pole", 2, None, True), ("race_pole", 1, None, False), ("race_pole", 4, None, None),
    ("race_pole", 9, None, False),
    ("race_h2h", 2, {"opponent_id": 1}, False), ("race_h2h", 4, {"opponent_id": 5}, True),
    ("race_h2h", 4, {"opponent_id": 9}, None),
    ("race_constructor_top", None, {"team": "a"}, True), ("race_constructor_top", None, {"team": "b"}, False),
    ("race_make_final", 1, None, None), ("rank_up", 1, None, None),
])
def test_settlement(kind, ath, params, want):
    assert K.settle(kind, ath, params, RES) == want
    assert house.outcome_for(kind, ath, params, RES) == want


def test_settlement_without_results_is_undecided():
    assert K.settle("race_win", 1, None, RES.iloc[:0]) is None


# --- sportsbook classification kinds (docs/sportsbook/) -------------------------------------------------------

def test_classification_kinds_from_the_simulations(f1_priced):
    _, ex = f1_priced
    sims = O.from_position_sim(ex["entrants"], ex["sim"])
    classified = K.fair("race_classified", sims)
    assert classified.shape == (len(sims.entrants),) and ((0 <= classified) & (classified <= 1)).all()
    last = K.fair("race_last_classified", sims)
    assert abs(last.sum() - 1) < 1e-9                       # exactly one last finisher per simulation (ties split none here)
    both = K.fair("race_team_both_classified", sims)
    win = K.fair("race_constructor_win", sims)
    assert abs(sum(win.values()) - 1) < 1e-9
    groups = np.array(sims.groups)
    for team, p in both.items():
        members = np.where(groups == team)[0]
        assert p <= classified[members].min() + 1e-9      # both classified is never likelier than either one
    n = sims.finished.sum(axis=1)
    over = K.fair("race_n_classified", sims, line=float(np.median(n)) - 0.5)
    assert 0 <= over <= 1 and over >= K.fair("race_n_classified", sims, line=float(n.max()) + 0.5) == 0.0
    with pytest.raises(ValueError):
        K.fair("race_n_classified", sims)


@pytest.mark.parametrize("kind,ath,params,want", [
    ("race_classified", 1, None, True), ("race_classified", 5, None, False), ("race_classified", 9, None, False),
    ("race_last_classified", 4, None, True), ("race_last_classified", 3, None, False),
    ("race_last_classified", 5, None, False),
    ("race_team_both_classified", None, {"team": "a"}, True), ("race_team_both_classified", None, {"team": "b"}, False),
    ("race_team_both_classified", None, {"team": "z"}, None),
    ("race_n_classified", None, {"line": 3.5}, True), ("race_n_classified", None, {"line": 4.5}, False),
    ("race_n_classified", None, None, None),
    ("race_constructor_win", None, {"team": "a"}, True), ("race_constructor_win", None, {"team": "b"}, False),
])
def test_classification_settlement(kind, ath, params, want):
    assert K.settle(kind, ath, params, RES) == want


# --- retirements (decision log 2026-10-06) --------------------------------------------------------------------

def _retire_sims():
    # 4 cars on teams a, a, b, b; 4 simulations: nobody retires / car 1 / cars 1 and 3 / cars 2, 3 and 4
    fin = np.array([[1, 1, 1, 1], [0, 1, 1, 1], [0, 1, 0, 1], [1, 0, 0, 0]], bool)
    rank = np.where(fin, np.tile(np.arange(1.0, 5), (4, 1)), np.inf)
    return O.OutcomeSims(entrants=[1, 2, 3, 4], rank=rank, finished=fin, groups=["a", "a", "b", "b"])


def test_retirement_kinds_from_the_simulations():
    sims = _retire_sims()
    np.testing.assert_allclose(K.fair("race_retire", sims), [0.5, 0.25, 0.5, 0.25])
    np.testing.assert_allclose(K.fair("race_retire", sims), 1 - K.fair("race_classified", sims))
    assert K.fair("race_retire", sims, a=3) == 0.5
    # uniform timing: each retiring car is equally likely to be first out; a sim with no retirement gives nobody
    first = K.fair("race_first_retirement", sims)
    np.testing.assert_allclose(first, [(1 + 0.5) / 4, (1 / 3) / 4, (0.5 + 1 / 3) / 4, (1 / 3) / 4])
    assert first.sum() == pytest.approx(0.75)                      # P(anyone retires)
    assert K.fair("race_first_retirement_team", sims) == pytest.approx({"a": (1.5 + 1 / 3) / 4, "b": (0.5 + 2 / 3) / 4})
    assert K.fair("race_n_retirements", sims, line=0.5) == 0.75
    assert K.fair("race_n_retirements", sims, line=1.5) == 0.5 and K.fair("race_n_retirements", sims, line=3.5) == 0
    with pytest.raises(ValueError):
        K.fair("race_n_retirements", sims)
    none = O.OutcomeSims(entrants=[1, 2], rank=np.array([[1.0, 2.0]]), finished=np.ones((1, 2), bool))
    np.testing.assert_array_equal(K.fair("race_first_retirement", none), [0.0, 0.0])
    # n-th retirement: first_retired's share, only in simulations with at least n retirements
    n_dnf = (~sims.finished).sum(axis=1)
    second = K.fair("race_second_retirement", sims)
    np.testing.assert_allclose(second, (K.first_retired(sims.finished) * (n_dnf >= 2)[:, None]).mean(0))
    assert second.sum() == pytest.approx((n_dnf >= 2).mean()) and K.fair("race_third_retirement", sims).sum() == pytest.approx((n_dnf >= 3).mean())
    assert (second <= first + 1e-12).all()
    # team versions of the classification kinds
    anyc = K.fair("race_team_any_classified", sims)
    both = K.fair("race_team_both_classified", sims)
    assert all(anyc[t] >= both[t] for t in anyc) and anyc == pytest.approx({t: float(sims.finished[:, np.array(sims.groups) == t].any(axis=1).mean()) for t in anyc})
    pts = K.fair("race_team_both_points", sims)
    assert all(pts[t] <= both[t] for t in pts)


def test_retirement_kinds_on_the_simulation_from_position_sim(f1_priced):
    _, ex = f1_priced
    sims = O.from_position_sim(ex["entrants"], ex["sim"])
    n_dnf = (~sims.finished).sum(axis=1)
    assert K.fair("race_first_retirement", sims).sum() == pytest.approx((n_dnf > 0).mean())
    assert sum(K.fair("race_first_retirement_team", sims).values()) == pytest.approx((n_dnf > 0).mean())
    assert K.fair("race_retire", sims).sum() == pytest.approx(n_dnf.mean())
    assert "race_retire" not in K.summary(sims)


RET = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4, 5, 6], position=[1, 2, 3, 4, 5, 6],
                        status=["OK", "OK", "DNF", "DNF", "DSQ", "DNS"], team_id=["a", "a", "b", "c", "c", "d"],
                        points=[25.0, 18, 0, 0, 0, 0], qual_position=[1, 2, 3, 4, 5, 6],
                        laps_completed=[57, 57, 12, 12, 57, 0]))


@pytest.mark.parametrize("kind,ath,params,want", [
    ("race_retire", 3, None, True), ("race_retire", 5, None, True), ("race_retire", 1, None, False),
    ("race_retire", 6, None, None), ("race_retire", 9, None, None),
    ("race_n_retirements", None, {"line": 2.5}, True), ("race_n_retirements", None, {"line": 3.5}, False),
    ("race_n_retirements", None, None, None),
    # cars 3 and 4 both stopped after 12 laps: a tie, both YES; the DSQ and the DNS are never first
    ("race_first_retirement", 3, None, True), ("race_first_retirement", 4, None, True),
    ("race_first_retirement", 5, None, False), ("race_first_retirement", 6, None, False),
    ("race_first_retirement", 1, None, False), ("race_first_retirement", 9, None, None),
    ("race_first_retirement_team", None, {"team": "b"}, True), ("race_first_retirement_team", None, {"team": "c"}, True),
    ("race_first_retirement_team", None, {"team": "a"}, False), ("race_first_retirement_team", None, {"team": "z"}, None),
    # competition ranking on laps: cars 3 and 4 share first place, so nobody is the second retirement; a third needs 3 DNFs
    ("race_second_retirement", 3, None, False), ("race_second_retirement", 4, None, False), ("race_second_retirement", 5, None, False),
    ("race_third_retirement", 3, None, False), ("race_second_retirement", 9, None, None),
    ("race_team_any_classified", None, {"team": "a"}, True), ("race_team_any_classified", None, {"team": "c"}, False),
    ("race_team_any_classified", None, {"team": "z"}, None),
    ("race_team_both_points", None, {"team": "a"}, True), ("race_team_both_points", None, {"team": "b"}, False),
])
def test_retirement_settlement(kind, ath, params, want):
    assert K.settle(kind, ath, params, RET) == want


def test_first_retirement_needs_laps_completed():
    one = RET.assign(laps_completed=[57, 57, 12, 30, 57, 0])
    assert K.settle("race_first_retirement", 3, None, one) is True
    assert K.settle("race_first_retirement", 4, None, one) is False
    assert K.settle("race_second_retirement", 4, None, one) is True and K.settle("race_second_retirement", 3, None, one) is False
    assert K.settle("race_second_retirement", 3, None, RET.drop(columns="laps_completed")) is None
    pts = RES.assign(position=[1, 11, 3, 4, 5], status="OK")
    assert K.settle("race_team_both_points", None, {"team": "a"}, pts) is True and K.settle("race_team_both_points", None, {"team": "b"}, pts) is False
    no_laps = RET.drop(columns="laps_completed")
    assert K.settle("race_first_retirement", 3, None, no_laps) is None
    assert K.settle("race_first_retirement_team", None, {"team": "b"}, no_laps) is None
    assert K.settle("race_first_retirement", 3, None, RET.assign(laps_completed=[57, 57, None, 12, 57, 0])) is None
    clean = RES.assign(status="OK")                                 # nobody retired: every driver and team is NO
    assert K.settle("race_first_retirement", 1, None, clean) is False
    assert K.settle("race_first_retirement_team", None, {"team": "a"}, clean) is False
    assert house.outcome_for("race_retire", 3, None, RET) is True
