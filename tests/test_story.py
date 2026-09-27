"""The demo maker's decision rules (pipelines/story.py) on synthetic evidence: defaults first, a mid-season
switch only past the margin, and the season rule's pick of the most consistent setup within the noise band."""

import pytest

from racinglines.pipelines import story as S
from racinglines.pipelines import sweep_settings as SS

pytestmark = pytest.mark.quick

BASE, GRID, GBM = ({"variant": "baseline"}, {"variant": "gridq+pretrain"}, {"variant": "gbm"})
C = {"variant": "gbm", "max_disagree": 0.05, "size": 25}


def _k(settings, strategy="maker"):
    return (SS.Settings.from_dict(settings).key, strategy)


def run(monkeypatch, weekly, decisions):
    monkeypatch.setattr(S, "POOL", [(BASE, ("maker",)), (GRID, ("maker",)), (GBM, ("maker",)), (C, ("maker",))])
    monkeypatch.setattr(S, "DECISIONS", decisions)
    monkeypatch.setattr(S, "_weekly", lambda conn, year: weekly)
    return S.decisions(None)


def test_defaults_first_then_switch_only_past_the_margin(monkeypatch):
    wk = {_k(BASE): [(1, 50), (2, 50)], _k(GRID): [(1, 100), (2, 80)], _k(GBM): [(1, 300), (2, 300)]}
    d = run(monkeypatch, wk, [("start", 2025, 0, "mid"), ("r1", 2025, 1, "mid"), ("r2", 2025, 2, "mid")])
    assert d[0]["chosen"].startswith("maker · baseline") and not d[0]["table"]
    assert d[1]["switched"] and "gbm" in d[1]["chosen"]                       # +300 vs +50: past the margin
    assert not d[2]["switched"]


def test_no_switch_on_a_small_lead(monkeypatch):
    wk = {_k(BASE): [(1, 100)], _k(GRID): [(1, 180)]}
    d = run(monkeypatch, wk, [("start", 2025, 0, "mid"), ("r1", 2025, 1, "mid")])
    assert not d[1]["switched"] and d[1]["chosen"].startswith("maker · baseline")


def test_season_rule_takes_the_most_consistent_within_the_noise_band(monkeypatch):
    steady = [(r, 40.0 + (r % 2) * 5) for r in range(1, 21)]                 # +850, very steady
    choppy = [(r, 250.0 if r % 2 else -150.0) for r in range(1, 21)]         # +1,000, swings
    wk = {_k(GBM): choppy, _k(C): steady, _k(BASE): [(r, 5.0) for r in range(1, 21)]}
    d = run(monkeypatch, wk, [("start", 2025, 0, "mid"), ("mid", 2025, 20, "mid"), ("season", 2025, 99, "season")])
    assert "max_disagree=0.05" not in d[1]["chosen"]                         # mid-season: the P&L leader
    assert "max_disagree=0.05" in d[2]["chosen"] and d[2]["switched"]        # season: steadier, within $350
    band = {r["setup"]: r["in_band"] for r in d[2]["table"]}
    assert band[S.label(BASE, "maker")] is False


def test_phases_group_consecutive_weekends():
    rec = [dict(profile=p, pnl=x) for p, x in (("M1", 10), ("M1", -5), ("M2", 3), ("C", 7), ("C", 1))]
    ph = S.phases(rec)
    assert [(p["profile"], p["weekends"], p["pnl"], p["up"]) for p in ph] == [("M1", 2, 5, 1), ("M2", 1, 3, 1), ("C", 2, 8, 2)]
