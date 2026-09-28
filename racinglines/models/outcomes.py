"""
What every race model simulates, in one shape (docs/backtest-core.md): the contract between a
sport's model and the shared market, backtest and search code.

A race model's Monte Carlo gives, per simulation, a classification of the entrants. Every market
we price (win, podium, top 10, pole, head-to-head, makes the Final, top team) is a function of it,
so market code reads an `OutcomeSims` and never a model's own arrays.

    sims = from_position_sim(entrants, sim)     # F1: pricing.price_race's extras["sim"], ["entrants"]
    sims = from_timed_runs(riders, sim)         # downhill: timed_runs.model.simulate_weekend
    markets.kinds.fair("race_podium", sims)     # per-entrant fair values

Adapters only re-label arrays (no copies of the random draws, no new randomness), so prices built on
an `OutcomeSims` equal the model's own summaries exactly.
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class OutcomeSims:
    entrants: list                   # athlete ids, the columns of every array
    rank: np.ndarray                 # (n_sims, n) classification rank; ties allowed; np.inf = not classified
    finished: np.ndarray             # (n_sims, n) bool: counts for top-n markets (F1: not a DNF; DH: ran the Final)
    stage_rank: dict = field(default_factory=dict)   # earlier deciding rounds' ranks, e.g. {"qual": grid}
    reached: dict = field(default_factory=dict)      # (n_sims, n) bool per round reached, e.g. {"final": made_final}
    points: np.ndarray | None = None                 # (n_sims, n) championship points scored
    groups: list | None = None                       # per entrant: team / nation key (group markets)

    @property
    def n_sims(self):
        return self.rank.shape[0]

    def index(self, athlete_id):
        return self.entrants.index(athlete_id)


def from_position_sim(entrants, sim):
    """F1 (position_sim): `pos` is the classification with retirements last, `grid` the qualifying order."""
    pos = sim["pos"]
    return OutcomeSims(entrants=entrants["athlete_id"].tolist(), rank=pos, finished=~sim["dnf"],
                       stage_rank={"qual": sim["grid"]}, points=sim["points"],
                       groups=entrants["team_key"].tolist() if "team_key" in entrants else None)


def from_timed_runs(riders, sim):
    """Downhill (timed_runs): `final_rank` is inf for riders who didn't run or finish the Final."""
    fr = sim["final_rank"]
    return OutcomeSims(entrants=list(riders), rank=fr, finished=np.isfinite(fr),
                       stage_rank={"qual": sim["qual_rank"]}, reached={"final": sim["made_final"]},
                       points=sim["points"])
