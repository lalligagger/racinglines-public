"""A walk-forward scored beside a venue (racinglines/pipelines/model_vs_market.py): the pairing on exact keys, the
price-at-cutoff and coherence rules, and the scores, from synthetic rows and a stub venue (no database)."""

import pandas as pd
import pytest

from racinglines.pipelines import model_vs_market as MVM

pytestmark = pytest.mark.quick

CUT = pd.Timestamp("2026-05-01")


class StubVenue:
    """The three venue_replay calls market_mids uses; prices after the cutoff would be a leak, so it raises."""

    def __init__(self, links, prices, coherent=True):
        self.links, self.prices, self._coherent = pd.DataFrame(links), prices, coherent

    def markets(self):
        return self.links.to_dict("records")

    def price(self, token, t):
        assert t == CUT
        return self.prices.get(token)

    def coherent(self, kind, t):
        assert t == CUT
        return self._coherent if isinstance(self._coherent, bool) else self._coherent[kind]


def _links():
    return [dict(prediction="race_win", athlete_id=1, token_id="w1"), dict(prediction="race_win", athlete_id=2, token_id="w2"),
            dict(prediction="race_win", athlete_id=9, token_id="w9"),            # not in the model's field
            dict(prediction="race_podium", athlete_id=1, token_id="p1"),
            dict(prediction="race_pole", athlete_id=1, token_id="x1"),           # a kind the walk-forward doesn't price
            dict(prediction="race_win", athlete_id=None, token_id="wn")]         # a market with no athlete


def _rows():
    r = [dict(event_id=7, season=2026, event="Test GP", kind="race_win", athlete_id=a, fair=f, y=y)
         for a, f, y in ((1, 0.6, 1.0), (2, 0.3, 0.0), (3, 0.1, 0.0))]
    r += [dict(event_id=7, season=2026, event="Test GP", kind="race_podium", athlete_id=1, fair=0.9, y=1.0),
          dict(event_id=7, season=2026, event="Test GP", kind="race_h2h", athlete_id=1, fair=0.5, y=1.0)]
    return pd.DataFrame(r)


def test_market_mids_reads_the_cutoff_and_drops_what_it_should():
    ven = StubVenue(_links(), {"w1": 0.5, "w2": 1.0, "p1": 0.8, "w9": 0.2})
    m = MVM.market_mids(pd.DataFrame(_links()), CUT, ven).set_index(["kind", "athlete_id"])
    assert set(m.index) == {("race_win", 1), ("race_win", 2), ("race_win", 9), ("race_podium", 1)}
    assert m.loc[("race_win", 1), "mid"] == 0.5
    assert pd.isna(m.loc[("race_win", 2), "mid"])                  # 1.0 is no price: a settled or empty book
    assert m.loc[("race_podium", 1), "coherent"]
    assert MVM.market_mids(pd.DataFrame(_links()), CUT.tz_localize("UTC"), ven).shape == m.reset_index().shape


def test_pair_joins_on_exact_keys_only():
    mids = MVM.market_mids(pd.DataFrame(_links()), CUT, StubVenue(_links(), {"w1": 0.5, "w2": 0.25, "p1": 0.8, "w9": 0.2}))
    p = MVM.pair(_rows(), mids.assign(event_id=7))
    assert sorted(zip(p["kind"], p["athlete_id"])) == [("race_podium", 1), ("race_win", 1), ("race_win", 2)]
    assert p["event_id"].eq(7).all()                               # athlete 3 has no market; 9 and the pole are not scored
    assert len(MVM.pair(_rows(), mids.assign(event_id=8))) == 0    # another event's links pair with nothing


def test_scores_are_model_on_all_and_model_vs_venue_on_paired():
    mids = pd.DataFrame([dict(event_id=7, kind="race_win", athlete_id=1, token_id="w1", mid=0.5, coherent=True),
                         dict(event_id=7, kind="race_win", athlete_id=2, token_id="w2", mid=None, coherent=True),
                         dict(event_id=7, kind="race_podium", athlete_id=1, token_id="p1", mid=0.8, coherent=False)])
    by_kind, by_season = MVM.scores(MVM.pair(_rows(), mids))
    w = by_kind.set_index("kind").loc["race_win"]
    assert w["n"] == 2 and w["paired"] == 1
    assert w["brier_model"] == pytest.approx((0.6 - 1) ** 2) and w["brier_venue"] == pytest.approx(0.25)
    assert w["gap"] == pytest.approx(0.1)
    pod = by_kind.set_index("kind").loc["race_podium"]
    assert pod["n"] == 1 and pod["paired"] == 0                     # an incoherent group gives no price
    assert set(by_season["season"]) == {2026}


def test_nothing_linked_is_empty_not_an_error():
    assert len(MVM.pair(_rows(), pd.DataFrame(columns=MVM.MID_COLS))) == 0


def test_stage_time_is_the_first_stage_unless_one_is_named():
    stages = [("pre-weekend", pd.Timestamp("2026-05-01 10:30")), ("after FP1", pd.Timestamp("2026-05-01 13:30")),
              ("after Quali", pd.Timestamp("2026-05-02 17:30"))]
    assert MVM.stage_time(stages) == pd.Timestamp("2026-05-01 10:30")
    assert MVM.stage_time(stages, "after Quali") == pd.Timestamp("2026-05-02 17:30")
    assert MVM.stage_time(stages, "after Sprint") is None and MVM.stage_time([]) is None


def test_stage_times_is_empty_for_a_sport_without_a_session_schedule():
    assert MVM.stage_times("motogp", [1, 2]) == {} and MVM.stage_times("f1", []) == {}
