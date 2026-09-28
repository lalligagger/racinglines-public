"""Stages from the sport's schema (racinglines/core/stages.py) and per-kind entry thresholds
(sweep_settings min_edge_by_kind, taker_weekend.params_for): the F1 weekend's stages are what the sweep
always used, and a kind's own threshold overrides the others. No data."""

from datetime import datetime, timedelta

import pytest

from racinglines.core import stages as ST
from racinglines.markets.strategies import taker_weekend as RB
from racinglines.pipelines import sweep_settings as SS

pytestmark = pytest.mark.quick

T0 = datetime(2026, 7, 3, 11, 30)
SPRINT = [("Practice 1", T0), ("Sprint Qualifying", T0 + timedelta(hours=4)), ("Sprint", T0 + timedelta(days=1)),
          ("Qualifying", T0 + timedelta(days=1, hours=4)), ("Race", T0 + timedelta(days=2, hours=3))]


def test_f1_stages_from_the_schema():
    b = ST.build(SPRINT, "f1")
    assert [lab for lab, _ in b["stages"]] == ["pre-weekend", "after FP1", "after SQ", "after Sprint", "after Quali"]
    assert b["stages"][0][1] == T0 - timedelta(hours=1)
    assert b["stages"][1][1] == T0 + timedelta(minutes=60 + 30)                  # FP1 ends, + 30 min data lag
    assert b["closes"] == {"race_pole": T0 + timedelta(days=1, hours=4)} and b["until"] == SPRINT[-1][1]
    assert ST.is_open("race_pole", b["closes"]["race_pole"] - timedelta(seconds=1), b["closes"])
    assert not ST.is_open("race_pole", b["closes"]["race_pole"], b["closes"]) and ST.is_open("race_win", T0, b["closes"])
    assert ST.build(SPRINT[:-1], "f1") is None                                  # no race: nothing to trade


def test_a_stage_ending_after_the_race_starts_is_dropped():
    late = [("Practice 1", T0), ("Qualifying", T0 + timedelta(hours=2)), ("Race", T0 + timedelta(hours=3, minutes=10))]
    assert [lab for lab, _ in ST.build(late, "f1")["stages"]] == ["pre-weekend", "after FP1"]


def test_per_kind_thresholds_are_canonical_and_unset_by_default():
    a = SS.Settings.from_dict(dict(min_edge_by_kind="race_podium=0.08, race_h2h=0.050"))
    assert a["min_edge_by_kind"] == "race_h2h=0.05,race_podium=0.08"
    assert a.key == SS.Settings.from_dict(dict(min_edge_by_kind={"race_podium": 0.08, "race_h2h": 0.05})).key
    assert SS.Settings.from_dict()["min_edge_by_kind"] is None
    assert SS.Settings.from_dict().key == "c107835cbced"                       # unset: saved keys don't move
    assert a.argv()[-2:] == ["--min-edge-by-kind", "race_h2h=0.05,race_podium=0.08"]
    assert SS.parse_map(a["min_edge_by_kind"]) == {"race_h2h": 0.05, "race_podium": 0.08}
    for bad in ("race_lunch=0.1", "race_h2h=0.9"):
        with pytest.raises(ValueError):
            SS.Settings.from_dict(dict(min_edge_by_kind=bad))


def test_a_kinds_own_threshold_wins():
    p = RB.TakerParams(min_edge=0.05, min_edge_h2h=0.03, min_edge_by_kind=(("race_podium", 0.08), ("race_h2h", 0.10)))
    assert RB.params_for("race_podium", p).min_edge == 0.08
    assert RB.params_for("race_h2h", p).min_edge == 0.10                        # over min_edge_h2h
    assert RB.params_for("race_win", p).min_edge == 0.05
    assert RB.params_for("race_h2h", RB.TakerParams(min_edge_h2h=0.03)).min_edge == 0.03
