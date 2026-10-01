"""
MotoGP riders' championship: the rest of the season, round by round, from the points standings as of a date, to
price the champion markets (Kalshi's KXMOTOGP, Polymarket's championship winner).

    state = standings_asof(points, cutoff)                     points and wins per rider from rounds run before it
    ss = simulate_season(state, race_sims, sprint_sims, rng)   an outcomes.SeasonSims (rank 1 = champion)
    markets.kinds.season_fair("champion", ss)                  per-rider fair values

Every remaining round is priced by the sport's own race model (sports/motogp.toml `pricing_model`, an OutcomeSims
per race); this module only turns those finishing orders into championship points. What each round scores (the
FIM's MotoGP points since 2023): the Grand Prix 25, 20, 16, 13, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1 to the top 15;
the Saturday sprint half of it, 12, 9, 7, 6, 5, 4, 3, 2, 1 to the top 9. The champion has the most points; a tie
goes to more Grand Prix wins (then a coin toss; the FIM's next tie-breaks, second places and so on, are not
simulated).

Simplifications, all of which understate the spread of outcomes: the race model reads Grand Prix results only, so
each sprint is simulated as an independent draw of the same race model; rounds are independent given the form as
of the cutoff (no form drift, no injuries or missed rounds, no track types). Nothing here reads or writes the
database: pipelines/season_replay.py does the reading, read-only.
"""

import numpy as np
import pandas as pd

from racinglines.models import outcomes as O

RACE_POINTS = (25, 20, 16, 13, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)
SPRINT_POINTS = (12, 9, 7, 6, 5, 4, 3, 2, 1)


def points_for(table, rank):
    """Points for finishing positions `rank` (any shape, 1 = the winner; beyond the table, or not finite, 0)."""
    t = np.zeros(len(table) + 2)
    t[1:len(table) + 1] = table
    r = np.asarray(rank, float)
    r = np.where(np.isfinite(r) & (r >= 1) & (r <= len(table)), r, 0).astype(int)
    return t[r]


def standings_asof(points, cutoff=None):
    """Where the championship stands: one row per rider with a scored round before `cutoff` (a date; None = all).
    points: one row per rider per scored round: date, athlete_id, kind ('race' | 'sprint'), position, points
    (as the source awarded them). Returns athlete_id, points, wins (Grand Prix wins), sorted by points."""
    p = points if cutoff is None else points[pd.to_datetime(points["date"]) < pd.Timestamp(cutoff)]
    if p.empty:
        return pd.DataFrame(columns=["athlete_id", "points", "wins"])
    out = pd.DataFrame(dict(
        points=p.groupby("athlete_id")["points"].sum(),
        wins=p[p["kind"] == "race"].groupby("athlete_id")["position"].apply(lambda s: int((s == 1).sum())),
    )).fillna(0.0).reset_index().rename(columns={"index": "athlete_id"})
    return out.sort_values(["points", "wins"], ascending=False).reset_index(drop=True)


def simulate_season(state, race_sims, sprint_sims, rng):
    """Monte Carlo of the remaining rounds. race_sims / sprint_sims: one OutcomeSims per remaining round (the same
    n_sims each; sprint_sims may hold None for a round without a sprint). A rider in the standings but not in a
    round's field scores nothing there; a rider in a field but not in the standings starts from 0."""
    if len(race_sims) != len(sprint_sims):
        raise ValueError(f"{len(race_sims)} races but {len(sprint_sims)} sprints")
    ids = [int(a) for a in state["athlete_id"]]
    for s in [*race_sims, *sprint_sims]:
        if s is not None:
            ids += [a for a in s.entrants if a not in set(ids)]
    col = {a: i for i, a in enumerate(ids)}
    sims = [s for s in [*race_sims, *sprint_sims] if s is not None]
    n_sims = sims[0].n_sims if sims else 1
    if any(s.n_sims != n_sims for s in sims):
        raise ValueError("every round needs the same number of simulations")
    st = state.set_index("athlete_id").reindex(ids)
    points = np.tile(st["points"].fillna(0).to_numpy(float), (n_sims, 1))
    wins = np.tile(st["wins"].fillna(0).to_numpy(float), (n_sims, 1))
    for table, round_sims in ((RACE_POINTS, race_sims), (SPRINT_POINTS, sprint_sims)):
        for s in round_sims:
            if s is None:
                continue
            idx = np.array([col[a] for a in s.entrants])
            rk = np.where(s.finished, s.rank, np.inf)
            points[:, idx] += points_for(table, rk)
            if table is RACE_POINTS:
                wins[:, idx] += rk == 1
    key = points + wins * 1e-3 + rng.random(points.shape) * 1e-6
    rank = np.argsort(np.argsort(-key, axis=1), axis=1) + 1
    return O.SeasonSims(entrants=ids, rank=rank, points=points, wins=wins)
