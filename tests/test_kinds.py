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
