"""
Market kinds as payoffs (docs/backtest-core.md): one definition per kind gives both its fair value,
from a model's simulations (racinglines/models/outcomes.py), and its settlement, from the official
result. Any sport whose model returns an `OutcomeSims` gets every kind here without new code.

    KINDS["race_podium"]                 the definition: top_n(3)
    fair("race_podium", sims)            per-entrant fair values, aligned with sims.entrants
    fair("race_h2h", sims, a, b)         one pair: P(a classified ahead of b)
    settle("race_win", athlete_id, params, res)   YES / NO / None (undecidable) from the classification

Settlement reads the result frame of private_book.race_outcomes (athlete_id, position, status,
qual_position, team_id, points) and is what private_book.outcome_for returns.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Kind:
    code: str
    payoff: str               # top_n | stage_top_n | h2h | reached | group_top | standings (not from sims)
    n: int | None = None      # top_n / stage_top_n
    stage: str | None = None  # stage_top_n: which earlier round (sims.stage_rank key); reached: which round
    label: str = ""


# Declared in the order the readers list prediction kinds (db/reads.PREDICTION_KINDS is derived from it).
# payoff "standings": season-long markets read from a model run's standings, not priced from an OutcomeSims.
KINDS = {k.code: k for k in (
    Kind("race_win", "top_n", n=1, label="Win"),
    Kind("race_podium", "top_n", n=3, label="Podium"),
    Kind("race_top10", "top_n", n=10, label="Top 10"),
    Kind("race_make_final", "reached", stage="final", label="Makes the Final"),
    Kind("champion", "standings", label="Champion"),
    Kind("standings_top3", "standings", label="Top 3 in the standings"),
    Kind("race_h2h", "h2h", label="Head-to-head"),
    Kind("race_pole", "stage_top_n", n=1, stage="qual", label="Pole position"),
    Kind("race_constructor_top", "group_top", label="Top constructor"),
    Kind("constructors_champion", "standings", label="Constructors' champion"),
    Kind("season_wins_ge", "standings", label="Season wins at least"),
    Kind("standings_h2h", "standings", label="Standings head-to-head"),
    # F1 sprint weekends (Kalshi's KXF1SPRINTPOLE / KXF1RACESPRINT, docs/todo.md U5): the sprint qualifying
    # order and the sprint classification are earlier rounds of the weekend, priced like pole from
    # sims.stage_rank["sprint_qual"] / ["sprint"] when a model simulates them
    Kind("race_sprint_pole", "stage_top_n", n=1, stage="sprint_qual", label="Sprint pole"),
    Kind("race_sprint_win", "stage_top_n", n=1, stage="sprint", label="Sprint winner"),
)}


# --- fair values ---------------------------------------------------------------------------------------

def fair(kind, sims, a=None, b=None):
    """Fair probability of YES. Per-entrant kinds return an array over sims.entrants (or one value with
    `a` = an athlete id); race_h2h needs a and b; race_constructor_top returns {group: probability}."""
    k = KINDS[kind]
    if k.payoff == "h2h":
        if a is None:
            return h2h_matrix(sims)
        i, j = sims.index(a), sims.index(b)
        return float((sims.rank[:, i] < sims.rank[:, j]).mean())
    if k.payoff == "group_top":
        return group_top(sims)
    if k.payoff == "top_n":
        p = ((sims.rank <= k.n) & sims.finished).mean(0)
    elif k.payoff == "stage_top_n":
        p = (sims.stage_rank[k.stage] <= k.n).mean(0)
    elif k.payoff == "reached":
        p = sims.reached[k.stage].mean(0)
    elif k.payoff == "standings":
        raise ValueError(f"{kind} is a standings market: not priced from an OutcomeSims")
    else:
        raise ValueError(f"unknown payoff {k.payoff}")
    return p if a is None else float(p[sims.index(a)])


def h2h_matrix(sims):
    """P(row entrant classified ahead of column entrant): the ranks as simulated (F1: retirements are
    classified behind finishers)."""
    r = sims.rank
    return (r[:, :, None] < r[:, None, :]).mean(0)


def group_top(sims):
    """{group: P(its entrants score the most points)}; a tie counts as a split win."""
    if sims.points is None or sims.groups is None:
        raise ValueError("group markets need points and groups")
    keys = sorted(set(sims.groups))
    tot = np.zeros((sims.n_sims, len(keys)))
    np.add.at(tot.T, np.array([keys.index(g) for g in sims.groups]), sims.points.T)
    best = tot == tot.max(axis=1, keepdims=True)
    share = best / best.sum(axis=1, keepdims=True)
    return {g: float(share[:, i].mean()) for i, g in enumerate(keys)}


def summary(sims):
    """Per entrant: the fair value of every per-entrant kind the simulations support."""
    out = dict(athlete_id=sims.entrants)
    for payoff in ("top_n", "stage_top_n", "reached"):        # columns grouped by payoff, in registry order
        for code, k in KINDS.items():
            if k.payoff == payoff and (payoff == "top_n" or k.stage in (sims.stage_rank if payoff == "stage_top_n"
                                                                        else sims.reached)):
                out[code] = fair(code, sims)
    return pd.DataFrame(out)


# --- settlement ----------------------------------------------------------------------------------------

def settle(kind, athlete_id, params, res, group_key=None):
    """YES/NO for a race market from the official classification (None if undecidable).
    group_key: maps a result's team_id to the group key the market names (F1: position_sim team_key)."""
    if res.empty:
        return None
    k = KINDS.get(kind)
    if k is None or k.payoff == "standings":
        return None
    by = res.set_index("athlete_id")
    if k.payoff == "stage_top_n":
        col = "qual_position" if k.stage == "qual" else f"{k.stage}_position"   # sprint rounds: sprint_qual_position, ...
        if col not in res:
            return None
        if athlete_id not in by.index or pd.isna(by.loc[athlete_id, col]):
            return False if athlete_id not in by.index else None
        return bool(by.loc[athlete_id, col] <= k.n)
    if k.payoff == "top_n":
        if athlete_id not in by.index:
            return False
        r = by.loc[athlete_id]
        return bool(r["status"] == "OK" and r["position"] <= k.n)
    if k.payoff == "h2h":
        b = (params or {}).get("opponent_id")
        if athlete_id not in by.index or b not in by.index:
            return None
        # classification order (retirements are classified behind finishers by laps completed)
        return bool(by.loc[athlete_id, "position"] < by.loc[b, "position"])
    if k.payoff == "reached":
        col = f"reached_{k.stage}"          # results that record the round (e.g. timed_runs: reached_final)
        if col not in res:
            return None
        return bool(by.loc[athlete_id, col]) if athlete_id in by.index else False
    if k.payoff == "group_top":
        keys =res["team_id"].map(group_key) if group_key else res["team_id"]
        pts = res.assign(tk=keys).groupby("tk")["points"].sum()
        return bool(pts.idxmax() == (params or {}).get("team")) if len(pts) else None
    return None
