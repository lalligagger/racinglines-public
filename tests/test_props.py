"""F1 race props (models/position_sim/props.py): per-circuit rates shrunk to the field, fastest-lap prices from
finishing odds, and their place in the live book (opt-in kinds only), on synthetic data."""

import numpy as np
import pandas as pd
import pytest

from racinglines.models.position_sim import props as P
from racinglines.pipelines import live as LV
from racinglines.pipelines import live_f1 as F


def _hist():
    # 20 races: venue 1 always has a safety car, venue 2 never; the fastest lap mostly goes to the winner
    rows = []
    for i in range(20):
        v = 1 if i % 2 == 0 else 2
        rows.append(dict(race_id=i, event_key=f"2025-{i + 1:02d}", venue_id=v, start=pd.Timestamp("2025-03-01") + pd.Timedelta(days=14 * i),
                         sc=v == 1, red=i % 5 == 0, rain=i % 4 == 0, rain_share=0.3 if i % 4 == 0 else 0.0,
                         fl_athlete=100, fl_bucket="p1" if i < 12 else "p4_10", n_ok=18, n_dnf=2))
    return pd.DataFrame(rows)


@pytest.mark.quick
def test_circuit_rates_shrink_to_the_field():
    h = _hist()
    field = h["sc"].mean()
    assert P.rate(h, 1, "sc", prior_n=16) == pytest.approx((10 + 16 * field) / 26)
    assert P.rate(h, 2, "sc", prior_n=16) == pytest.approx((0 + 16 * field) / 26)
    assert P.rate(h, 99, "sc") == pytest.approx(field)                    # a new venue: the field rate
    assert P.rate(h, 1, "sc", prior_n=1e9) == pytest.approx(field)
    assert P.rate(h.iloc[:0], 1, "sc") is None


@pytest.mark.quick
def test_fastest_lap_prices_sum_to_one_and_follow_the_winner():
    h = _hist()
    r = P.fl_rates(h)
    assert r["p1"] > r["p2_3"] and r["p4_10"] > r["p11"]
    preds = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4], driver=list("ABCD"), win_prob=[0.6, 0.3, 0.1, 0.0],
                              podium_prob=[0.9, 0.8, 0.6, 0.1], top10_prob=[1.0, 1.0, 0.9, 0.5],
                              dnf_prob=[0.0, 0.0, 0.05, 0.2]))
    p = P.fl_probs(preds, r)
    assert p.sum() == pytest.approx(1) and list(np.argsort(-p)) == [0, 1, 2, 3]
    m = P.market_set(preds, 1, h)
    assert [x["kind"] for x in m][:3] == ["race_safety_car", "race_red_flag", "race_rain"]
    fl = [x for x in m if x["kind"] == "race_fastest_lap"]
    assert len(fl) == 4 and sum(x["fair"] for x in fl) == pytest.approx(1) and fl[0]["key"] == "race_fastest_lap:1"
    assert P.market_set(preds, 1, h, kinds=("race_rain",)) == [dict(key="race_rain", kind="race_rain", athlete_id=None,
                                                                    params=None, subject="Rain", fair=P.rate(h, 1, "rain"))]


@pytest.mark.quick
def test_props_are_opt_in():
    live = LV.settings("f1")
    assert set(live["markets"]["kinds"]) == set(F.KINDS) and not set(F.PROP_KINDS) & set(F.KINDS)
    assert F.prop_markets(None, "2026-16", None, F.KINDS) == []           # nothing read, nothing listed


@pytest.mark.quick
def test_the_live_tab_groups_the_props():
    mk = [dict(key="race_safety_car", kind="race_safety_car", subject="Safety car", fair=0.6, prev_fair=None),
          dict(key="race_rain", kind="race_rain", subject="Rain", fair=0.2, prev_fair=None),
          dict(key="race_fastest_lap:1", kind="race_fastest_lap", subject="A", fair=0.7, prev_fair=0.6),
          dict(key="race_fastest_lap:2", kind="race_fastest_lap", subject="B", fair=0.3, prev_fair=None)]
    snap = dict(markets=mk, outcomes=[], ts="2026-10-02T03:30:00+00:00")
    import racinglines.pipelines.live as live_core
    orig = live_core.book_at
    live_core.book_at = lambda run, ts: ({}, [])
    try:
        v = F.view("x", snap, [], [], "live", maker=False)
    finally:
        live_core.book_at = orig
    g = {x["kind"]: x for x in v["groups"]}
    assert list(g) == ["race_props", "race_fastest_lap"]
    assert [m["subject"] for m in g["race_props"]["markets"]] == ["Safety car", "Rain"] and g["race_props"]["target"] is None
    assert g["race_fastest_lap"]["target"] == 1.0 and g["race_fastest_lap"]["total"] == pytest.approx(1)


@pytest.mark.quick
def test_race_outcomes_add_the_props(monkeypatch):
    from racinglines.markets import private_book as PB
    res = pd.DataFrame(dict(athlete_id=list(range(1, 7)), position=list(range(1, 7)), status=["OK"] * 6,
                            team_id=["t"] * 6, points=[0.0] * 6, qual_position=list(range(1, 7))))
    monkeypatch.setattr(PB, "race_outcomes", lambda conn, rid: res)
    seen = []
    monkeypatch.setattr(P, "outcomes", lambda conn, rid, mkts: seen.append([m["key"] for m in mkts]) or {"race_rain": True})
    mk = [dict(key="race_win:1", kind="race_win", athlete_id=1, params=None),
          dict(key="race_rain", kind="race_rain", athlete_id=None, params=None)]
    assert F.outcomes(None, 7, mk) == {"race_win:1": True, "race_rain": True} and seen == [["race_rain"]]
    seen.clear()
    assert F.outcomes(None, 7, mk[:1]) == {"race_win:1": True} and seen == []   # no props listed: not read
