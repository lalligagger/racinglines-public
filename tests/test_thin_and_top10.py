"""Opt-in settings: thin-market book depth, per-kind coherence tolerance, Kalshi top-10 as a selectable kind.
Synthetic; no database."""

from datetime import timedelta

import pandas as pd
import pytest

from racinglines.markets import venue_replay as VR
from racinglines.pipelines import sweep_settings as SS
from racinglines.pipelines import weekend_sweep as WS

pytestmark = pytest.mark.quick

T0 = pd.Timestamp("2026-06-06 12:00")


def _venue(prices, target, tol=0.25):
    v = VR.Polymarket.__new__(VR.Polymarket)
    v.links = pd.DataFrame(dict(token_id=list(prices), prediction="race_podium"))
    v.prices = {t: pd.DataFrame(dict(ts=[T0 - timedelta(minutes=5)], price=[p])) for t, p in prices.items()}
    v.stale, v.group_target, v.coherence_tol = timedelta(hours=6), {"race_podium": target}, tol
    return v


def test_coherence_tolerance_per_kind():
    v = _venue({"a": 0.9, "b": 0.9, "c": 0.9, "d": 0.5}, target=3)          # sums to 3.2, off by 6.7%
    assert v.coherent("race_podium", T0)
    v = _venue({"a": 0.9, "b": 0.9, "c": 0.9, "d": 0.8}, target=3)          # 3.5: 16.7% over
    assert v.coherent("race_podium", T0)
    v = _venue({"a": 0.9, "b": 0.9, "c": 0.9, "d": 1.2}, target=3)          # 3.9: 30% over
    assert not v.coherent("race_podium", T0)
    v.tol_by_kind = {"race_podium": 0.35}
    assert v.coherent("race_podium", T0)
    v.tol_by_kind = {"race_win": 0.5}                                        # another kind's tolerance: not this one
    assert not v.coherent("race_podium", T0)


def test_touch_depth_reads_the_latest_recent_book():
    v = _venue({"a": 0.05}, target=3)
    ts = pd.DatetimeIndex([T0 - timedelta(minutes=30), T0 - timedelta(minutes=4)])
    v.books = {"a": (ts, [{0.04: 10.0}, {0.04: 20.0, 0.03: 99.0}], [{0.06: 5.0}, {0.06: 70.0, 0.07: 9.0}])}
    assert v.touch_depth("a", T0) == (70.0, 20.0)                            # best ask's and best bid's size
    assert v.touch_depth("a", T0 + timedelta(minutes=30)) is None            # snapshot too old
    assert v.touch_depth("a", T0 - timedelta(hours=1)) is None               # none yet
    assert v.touch_depth("nope", T0) is None
    v.books = None
    assert v.touch_depth("a", T0) is None                                    # no books recorded: no exception


def test_new_settings_are_off_by_default_and_leave_the_keys_alone():
    d = SS.Settings.from_dict()
    assert d["thin_edge_mult"] is None and d["coherence_tol_by_kind"] is None
    assert d["market_kinds"] == WS.KINDS and "race_top10" not in d["market_kinds"]
    assert d.changed() == {} and d.argv() == []
    on = SS.Settings.from_dict(dict(thin_edge_mult=2, market_kinds="race_podium,race_top10",
                                    coherence_tol_by_kind="race_podium=0.35"))
    assert on["thin_edge_mult"] == 2.0 and on["market_kinds"] == ("race_podium", "race_top10")
    assert SS.parse_map(on["coherence_tol_by_kind"]) == {"race_podium": 0.35}
    assert on.key != d.key and on.model_key == d.model_key
    with pytest.raises(ValueError):
        SS.Settings.from_dict(dict(thin_edge_mult=0.5))                       # below 1 x the minimum edge
    with pytest.raises(ValueError):
        SS.Settings.from_dict(dict(market_kinds="race_top5"))


def test_top10_is_a_group_of_ten():
    assert WS.OPT_KINDS == SS.OPT_KINDS == ("race_top10",) and WS.OPT_GROUP_TARGET["race_top10"] == 10
    assert "race_top10" not in WS.KINDS and "race_top10" not in WS.GROUP_TARGET
