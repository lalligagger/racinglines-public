"""Tests for racinglines.research.jev_gate_stats (no DB, no network)."""

from __future__ import annotations

import math

import numpy as np

from racinglines.research.jev_gate_stats import (
    analyse,
    auc_loser_gt_winner,
    cluster_boot_ci,
    format_report,
    perm_p,
)


def test_auc_hand_cases():
    # losers score 3, 4; winners 1, 2 -> every loser above every winner
    assert auc_loser_gt_winner([3, 4, 1, 2], [False, False, True, True]) == 1.0
    assert auc_loser_gt_winner([1, 2, 3, 4], [False, False, True, True]) == 0.0
    # loser 2 vs winners 1,3 -> 0.5
    assert auc_loser_gt_winner([2, 1, 3], [False, True, True]) == 0.5
    # ties count half: losers [1,2], winner [1] -> (0.5 + 1) / 2
    assert auc_loser_gt_winner([1, 2, 1], [False, False, True]) == 0.75
    # all tied
    assert auc_loser_gt_winner([5, 5, 5, 5], [False, True, False, True]) == 0.5


def test_auc_empty_class_is_nan():
    assert math.isnan(auc_loser_gt_winner([1, 2], [True, True]))
    assert math.isnan(auc_loser_gt_winner([1, 2], [False, False]))


def _planted(n_each=30, shift=2.0, seed=0):
    rng = np.random.default_rng(seed)
    lose = rng.normal(shift, 1, n_each)
    win = rng.normal(0, 1, n_each)
    return np.r_[lose, win], np.r_[np.zeros(n_each, bool), np.ones(n_each, bool)]


def test_perm_p_tails():
    s, w = _planted()
    assert perm_p(s, w, "high", n=2000) < 0.01
    assert perm_p(s, w, "low", n=2000) > 0.9


def test_perm_p_noise():
    rng = np.random.default_rng(5)
    s = rng.normal(size=60)
    w = rng.random(60) < 0.5
    assert perm_p(s, w, "high", n=2000) > 0.1


def test_cluster_boot():
    s, w = _planted()
    races = np.arange(len(s)) % 12
    lo, hi = cluster_boot_ci(s, w, races, n=300)
    auc = auc_loser_gt_winner(s, w)
    assert lo <= auc <= hi
    assert cluster_boot_ci(s, w, races, n=300) == (lo, hi)
    assert all(math.isnan(x) for x in cluster_boot_ci(s, w, np.zeros(len(s)), n=50))


def _rows(planted: str | None, seed=0, n_races=40):
    """Three NO buys per race plus one YES buy; ids 0..; exploration = first 12 races' signals."""
    rng = np.random.default_rng(seed)
    rows, i = [], 0
    for race in range(n_races):
        for k in range(4):
            side = "YES" if k == 3 else "NO"
            won = bool(rng.random() < (0.05 if side == "YES" else 0.4))
            se = float(rng.normal())
            gcc = float(rng.normal())
            if planted == "H1" and side == "NO":
                se += 3.0 if won else 0.0  # winners score higher on se
            rows.append(dict(id=i, race_id=race, side=side, won=won,
                             pnl=float(rng.normal()), stage="fp1",
                             event_key=f"ev{race // 2}", mm=float(rng.normal()), se=se, gcc=gcc))
            i += 1
    return rows


def _explore_ids(rows, races=12):
    return {r["id"] for r in rows if r["race_id"] < races}


def test_analyse_planted_h1():
    rows = _rows("H1")
    ex = _explore_ids(rows)
    # exploration carries no signal: scrub it
    rng = np.random.default_rng(9)
    for r in rows:
        if r["id"] in ex:
            r["se"] = float(rng.normal())
    res = analyse(rows, ex, n_perm=2000, n_boot=300)
    h1, h2 = res["decision"]["H1"], res["decision"]["H2"]
    assert h1["confirmed"] and h1["auc"] <= 0.35
    assert not h2["confirmed"]
    n_conf_no = sum(1 for r in rows if r["id"] not in ex and r["side"] == "NO")
    assert h1["n"] == n_conf_no
    assert res["sets"]["confirm"]["NO"]["se"]["n"] == n_conf_no
    assert res["sets"]["explore"]["all"]["se"]["n"] == len(ex)
    assert res["sets"]["pooled"]["all"]["se"]["n"] == len(rows)
    ov = res["overlap"]
    assert ov["confirm_races"] == 28 and ov["in_exploration"] == 0
    assert res["decision_subset"] is not None
    assert sum(t["n"] for t in res["terciles"]["confirm"]) == n_conf_no
    txt = format_report(res)
    assert "CONFIRMED" in txt and "size" in txt.splitlines()[-1]


def test_analyse_noise():
    rows = _rows(None, seed=3)
    res = analyse(rows, _explore_ids(rows), n_perm=2000, n_boot=300)
    assert not res["decision"]["H1"]["confirmed"]
    assert not res["decision"]["H2"]["confirmed"]


def test_exploration_does_not_leak():
    rows = _rows(None, seed=4)
    ex = _explore_ids(rows)
    res = analyse(rows, ex, n_perm=200, n_boot=50)
    conf = [r for r in rows if r["id"] not in ex]
    assert res["sets"]["confirm"]["all"]["mm"]["n"] == len(conf)
    assert res["sets"]["confirm"]["all"]["mm"]["winners"] == sum(r["won"] for r in conf)


def test_yes_only_insufficient_no_crash():
    rows = _rows(None, seed=6)
    ex = _explore_ids(rows)
    for r in rows:
        if r["side"] == "YES" and r["id"] not in ex:
            r["won"] = False
    res = analyse(rows, ex, n_perm=200, n_boot=50)
    yes = res["sets"]["confirm"]["YES"]["se"]
    assert yes["winners"] == 0 and math.isnan(yes["auc"])
    # decision uses NO buys only; make those insufficient too
    for r in rows:
        if r["id"] not in ex:
            r["won"] = False
    res = analyse(rows, ex, n_perm=200, n_boot=50)
    for h in ("H1", "H2"):
        assert res["decision"][h]["status"] == "insufficient"
        assert res["decision"][h]["confirmed"] is False
    assert "INSUFFICIENT" in format_report(res)
