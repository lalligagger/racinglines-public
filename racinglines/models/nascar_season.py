"""
NASCAR Cup season simulation: the rest of the season, race by race, from the current points standings, through the
championship format, to price season-long markets (Cup champion, a finishing position in the final standings,
standings head-to-head, season wins).

    fmt = FORMATS[2026]                                          the Chase: 16 drivers, one reset, no eliminations
    state = standings_now(fmt, results, schedule)                 points, wins, who is in the Chase, from race results
    ss = simulate_season(fmt, state, remaining, race_sims, rng)   an outcomes.SeasonSims
    markets.kinds.season_fair("champion", ss)                     per-driver fair values

Every remaining race is priced by the sport's own race model (sports/nascar.toml `pricing_model`, an OutcomeSims per
race); this module only turns those finishing orders into championship points and applies the format. Nothing here
reads or writes the database: `load_state` (below) and `racinglines nascar season` do the reading, read-only.

What each race scores (checked against the 2026 weekend feeds in tests/fixtures/market, see test_nascar_season.py):
finishing points 55 for the win, 35 for 2nd, 34 for 3rd, ... 1 point from 36th down; 10..1 to the top 10 of each
paid stage (two per race; the Coca-Cola 600 pays three); and one bonus point per race that the feeds give to one
driver (56 for the Darlington winner, 36 for Bristol's runner-up). The bonus's rule is INFERRED (a fastest-lap point,
as in 2025), not read from a rulebook: it is simulated as going to the best of a noisy re-draw of the finishing order.

Stage finishes are not in the race model's simulations: each stage is simulated as the race's finishing order
re-ranked with Gaussian noise (`stage_noise` places), so stage points go mostly, not only, to the fast cars.
Races are simulated independently given today's form: no form drift over the rest of the season and no track types
(Talladega is as predictable as Phoenix to this model). Both understate the spread of outcomes.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from racinglines.models import outcomes as O


@dataclass(frozen=True)
class ChaseFormat:
    """One season's championship format. chase_size drivers qualify on regular-season points (ties: more wins);
    seeds[i] is the (i+1)th qualifier's points at the reset. rounds: [(races, drivers kept after them)] for an
    elimination format; empty = no eliminations. With `final_by_finish`, the last round's drivers are ranked by
    their finish in the final race (the 2014-2025 championship race); otherwise by points."""
    season: int
    chase_size: int
    seeds: tuple
    win_points: int = 55
    second_points: int = 35                   # 2nd 35, 3rd 34, ... down one a place, never below 1
    stage_points: tuple = (10, 9, 8, 7, 6, 5, 4, 3, 2, 1)
    paid_stages: int = 2
    bonus_points: int = 1                     # one per race (fastest lap, inferred from the 2026 feeds)
    rounds: tuple = ()
    final_by_finish: bool = False
    source: str = ""


# 2026: "The Chase" (NASCAR, 2026-01-12): the top 16 in points after the regular season (no win-and-in), one reset
# (2100, 2075, 2065, 2060, 2055, then 5 fewer a place down to 2000 for 16th), 10 races, no eliminations, the most
# points after the tenth race is the champion. 55 points for a win. No playoff points.
FORMATS = {
    2026: ChaseFormat(
        season=2026, chase_size=16, seeds=(2100, 2075, 2065, 2060) + tuple(range(2055, 1999, -5)),
        source="NASCAR 2026 Chase announcement (2026-01-12); win 55 and finishing points checked on the 2026 feeds"),
}


def finish_points(fmt, rank):
    """Finishing points for classification ranks (any shape; rank 1 = the winner)."""
    r = np.asarray(rank, float)
    pts = np.maximum(fmt.second_points - (r - 2), 1.0)
    return np.where(r == 1, float(fmt.win_points), pts)


def stage_points(fmt, rank, rng, noise, stages=None):
    """(n_sims, n) stage points over `stages` paid stages: each stage's order is the race's order re-drawn with
    N(0, noise) places, and its top len(fmt.stage_points) score."""
    rank = np.asarray(rank, float)
    table = np.zeros(rank.shape[1] + 1)
    table[1:len(fmt.stage_points) + 1] = fmt.stage_points[:rank.shape[1]]
    out = np.zeros(rank.shape)
    for _ in range(fmt.paid_stages if stages is None else stages):
        order = _ranks(rank + rng.normal(0.0, noise, rank.shape))
        out += table[order]
    return out


def bonus_points(fmt, rank, rng, noise):
    """The one bonus point a race: to the best of the finishing order re-drawn with N(0, noise) places."""
    out = np.zeros(np.shape(rank))
    if fmt.bonus_points:
        best = np.argmin(np.asarray(rank, float) + rng.normal(0.0, noise, np.shape(rank)), axis=1)
        out[np.arange(len(best)), best] = fmt.bonus_points
    return out


def _ranks(x):
    """1-based ranks along axis 1, smallest first (ties broken by position, as the draws are continuous)."""
    return np.argsort(np.argsort(x, axis=1), axis=1) + 1


# --- the state today ------------------------------------------------------------------------------------------

def standings_now(fmt, results, schedule):
    """Where the season stands, from the races already run.

    results: one row per driver per completed points race: event_id, athlete_id, position, points (as the feed
    awarded them, stage and bonus points included). schedule: one row per points race of the season: event_id,
    date, chase (bool, a Chase race), done (bool); optional stages (paid stages; default the format's).

    Returns a DataFrame over every driver with a result: athlete_id, regular (regular-season points), points (the
    standings today: seed + Chase points for a Chase driver once the Chase has started, else the season total),
    wins, seed (1..chase_size or 0; set once the regular season is over), and the flag `chase_set`."""
    sched = schedule.sort_values("date")
    reg_ids = set(sched.loc[~sched["chase"], "event_id"])
    chase_ids = set(sched.loc[sched["chase"], "event_id"])
    reg_done = bool(sched.loc[~sched["chase"], "done"].all())
    r = results[results["event_id"].isin(reg_ids | chase_ids)]
    reg = r[r["event_id"].isin(reg_ids)]
    by, rby = r.groupby("athlete_id"), reg.groupby("athlete_id")["position"]
    out = pd.DataFrame(dict(
        regular=reg.groupby("athlete_id")["points"].sum(),
        chase_pts=r[r["event_id"].isin(chase_ids)].groupby("athlete_id")["points"].sum(),
        wins=by["position"].apply(lambda s: int((s == 1).sum())),
        reg_wins=rby.apply(lambda s: int((s == 1).sum())),
        reg_top5=rby.apply(lambda s: int((s <= 5).sum())),
        reg_top10=rby.apply(lambda s: int((s <= 10).sum())),
    )).fillna(0.0).reset_index().rename(columns={"index": "athlete_id"})
    out["seed"] = 0
    if reg_done:
        # NASCAR's tie-breakers: wins, then top 5s, then top 10s (penalties are not in the results: see apply_feed)
        order = out.sort_values(["regular", "reg_wins", "reg_top5", "reg_top10", "athlete_id"],
                                ascending=[False, False, False, False, True])
        top = order.head(fmt.chase_size).index
        out.loc[top, "seed"] = np.arange(1, len(top) + 1)
    seeded = out["seed"] > 0
    seed_pts = np.array([fmt.seeds[s - 1] if s else 0 for s in out["seed"]], float)
    out["points"] = np.where(seeded, seed_pts + out["chase_pts"], out["regular"] + out["chase_pts"])
    out["chase_set"] = reg_done
    out["source"] = "results"
    return out[["athlete_id", "regular", "points", "wins", "seed", "chase_set", "source"]].sort_values(
        "points", ascending=False).reset_index(drop=True)


def apply_feed(fmt, state, feed, ids):
    """The standings today as NASCAR publishes them (points-feed.json: penalties and official tie-breaks included)
    in place of the ones summed from race results. ids: {NASCAR driver_id: athlete_id}. For every matched driver the
    feed's points and wins replace ours and, once the Chase is set, its playoff_rank (the seed) replaces ours; drivers
    the feed does not list keep theirs. Returns (state, matched count)."""
    st = state.set_index("athlete_id").copy()
    matched = 0
    for row in feed or []:
        a = ids.get(row.get("driver_id"))
        if a is None or a not in st.index:
            continue
        matched += 1
        st.loc[a, "points"] = float(row["points"])
        st.loc[a, "wins"] = int(row.get("wins") or 0)
        if st["chase_set"].any():
            rank = int(row.get("playoff_rank") or 0)
            st.loc[a, "seed"] = rank if 0 < rank <= fmt.chase_size else 0
        st.loc[a, "source"] = "feed"
    if matched and st["chase_set"].any() and (st["seed"] > 0).sum() != fmt.chase_size:
        raise ValueError(f"the points feed gives {(st['seed'] > 0).sum()} Chase seeds, not {fmt.chase_size}")
    return st.reset_index().sort_values("points", ascending=False).reset_index(drop=True), matched


def estimate_noise(results, recent=6, min_prior=3):
    """Race-to-race spread of finishing positions, in places: the SD of each result around the driver's mean over
    their previous `recent` races (drivers with at least `min_prior` of them). The race model's `noise` default
    (2.0) is far below it, which makes one favourite win most simulated races; the season forecast uses this
    estimate instead. results: date, athlete_id, position (any seasons, in any order)."""
    r = results.dropna(subset=["position"]).sort_values("date")
    prior = r.groupby("athlete_id")["position"].transform(lambda s: s.shift(1).rolling(recent, min_periods=min_prior).mean())
    resid = (r["position"] - prior).dropna()
    return float(resid.std()) if len(resid) > 30 else None


# --- the rest of the season -------------------------------------------------------------------------------------

def simulate_season(fmt, state, remaining, race_sims, rng, stage_noise=5.0, bonus_noise=6.0):
    """Monte Carlo of the rest of the season.

    state: standings_now's frame. remaining: the races still to run, in order, each a dict with `chase` (bool) and
    optionally `stages` (paid stages). race_sims: one outcomes.OutcomeSims per remaining race (the same n_sims each),
    as the race model priced it; a driver in the standings but not in a race's field scores nothing there, and a
    driver in a field but not in the standings enters with 0 points.
    Returns an outcomes.SeasonSims whose `rank` is the final standings position (Chase drivers first, ranked by
    points; everyone else behind them by points), with `qualified` = made the Chase."""
    if len(remaining) != len(race_sims):
        raise ValueError(f"{len(remaining)} remaining races but {len(race_sims)} race simulations")
    ids = list(state["athlete_id"])
    for s in race_sims:
        ids += [a for a in s.entrants if a not in set(ids)]
    col = {a: i for i, a in enumerate(ids)}
    n_sims = race_sims[0].n_sims if race_sims else 1
    if any(s.n_sims != n_sims for s in race_sims):
        raise ValueError("every race needs the same number of simulations")
    st = state.set_index("athlete_id").reindex(ids)
    n = len(ids)

    regular = np.tile(st["regular"].fillna(0).to_numpy(float), (n_sims, 1))
    points = np.tile(st["points"].fillna(0).to_numpy(float), (n_sims, 1))
    wins = np.tile(st["wins"].fillna(0).to_numpy(float), (n_sims, 1))
    reg_wins = wins.copy()
    chase_set = bool(state["chase_set"].iloc[0]) if len(state) else False
    seed = np.tile(st["seed"].fillna(0).to_numpy(int), (n_sims, 1)) if chase_set else np.zeros((n_sims, n), int)
    alive = seed > 0                                   # still in the Chase (all of it, unless the format eliminates)
    chase_races_run = 0
    for race, sims in zip(remaining, race_sims):
        if race.get("chase") and not chase_set:        # the reset, before the first Chase race
            seed = _seed(fmt, regular, reg_wins, rng)
            points = np.where(seed > 0, np.asarray(fmt.seeds + (0,))[seed - 1], points)
            alive = seed > 0
            chase_set = True
        idx = np.array([col[a] for a in sims.entrants])
        rk = np.asarray(sims.rank, float)
        rk = np.where(np.isfinite(rk), rk, rk.shape[1])
        earned = (finish_points(fmt, rk) + stage_points(fmt, rk, rng, stage_noise, race.get("stages"))
                  + bonus_points(fmt, rk, rng, bonus_noise))
        pts = np.zeros((n_sims, n))
        pts[:, idx] = earned
        points += pts
        won = np.zeros((n_sims, n))
        won[:, idx] = (rk == 1)
        wins += won
        if not race.get("chase"):
            regular += pts
            reg_wins += won
        else:
            chase_races_run += 1
            alive = _eliminate(fmt, alive, points, chase_races_run, rng)
            if fmt.final_by_finish and race is remaining[-1]:
                fin = np.full((n_sims, n), np.inf)
                fin[:, idx] = rk
                points = np.where(alive, 1e6 - fin, points)     # the final round: best finish wins
    if not chase_set:                                  # the season ends before the Chase in this call: seed anyway
        seed = _seed(fmt, regular, reg_wins, rng)
        alive = seed > 0
    qualified = seed > 0
    key = points + np.where(alive, 2e6, 0.0) + np.where(qualified, 1e6, 0.0) + rng.random(points.shape) * 1e-3
    rank = _ranks(-key)
    return O.SeasonSims(entrants=ids, rank=rank, points=points, wins=wins, qualified=qualified)


def _seed(fmt, regular, reg_wins, rng):
    """(n_sims, n) seed 1..chase_size by regular-season points, then wins; 0 = not in the Chase."""
    r = _ranks(-(regular + reg_wins * 1e-3 + rng.random(regular.shape) * 1e-6))
    return np.where(r <= fmt.chase_size, r, 0)


def _eliminate(fmt, alive, points, chase_races_run, rng):
    """The elimination rounds (none in 2026): after a round's last race keep its best `keep` drivers by points."""
    done = 0
    for races, keep in fmt.rounds:
        done += races
        if done == chase_races_run:
            key = np.where(alive, points + rng.random(points.shape) * 1e-3, -np.inf)
            return alive & (_ranks(-key) <= keep)
    return alive


# --- the model's standings table (the shape pricing.forecast writes for F1) -----------------------------------------

def standings_frame(ss, state, names=None, wins_up_to=10):
    """One row per driver: the columns a forecast run's standings carry (champion_prob, top3_prob, top10_prob,
    exp_points, exp_rank, extra.wins_ge / ahead_of), plus chase_prob, so db.reads.model_prob could read it."""
    from racinglines.markets import kinds as K
    names = names or {}
    st = state.set_index("athlete_id")
    ahead = K.season_fair("standings_h2h", ss)
    df = pd.DataFrame(dict(
        athlete_id=ss.entrants, driver=[names.get(a, str(a)) for a in ss.entrants],
        current_points=[float(st["points"].get(a, 0.0)) for a in ss.entrants],
        seed=[int(st["seed"].get(a, 0)) for a in ss.entrants],
        exp_points=ss.points.mean(0), points_p10=np.percentile(ss.points, 10, 0), points_p90=np.percentile(ss.points, 90, 0),
        champion_prob=K.season_fair("champion", ss), top3_prob=K.season_fair("standings_top3", ss),
        top10_prob=K.standings_position(ss, 10), chase_prob=ss.qualified.mean(0), exp_rank=ss.rank.mean(0)))
    df["extra"] = [dict(
        wins_now=int(st["wins"].get(a, 0)), exp_wins=round(float(ss.wins[:, i].mean()), 3),
        wins_ge={str(k): round(float((ss.wins[:, i] >= k).mean()), 4) for k in range(1, wins_up_to + 1)},
        ahead_of={str(b): round(float(ahead[i, j]), 4) for j, b in enumerate(ss.entrants) if b != a})
        for i, a in enumerate(ss.entrants)]
    return df.sort_values(["champion_prob", "exp_points"], ascending=False).reset_index(drop=True)


# --- reading the database (read-only) -------------------------------------------------------------------------------

def load_state(conn, year, competition="nascar_cup", source="nascar_cf"):
    """(results, schedule) for `year` from the database: the season's Cup points races (race.format race_type
    'points'; a Chase race has playoff_round > 0) and the results of those already run."""
    from sqlalchemy import text
    schedule = pd.read_sql(text("""
        SELECT e.id AS event_id, e.name, e.start_date AS date, e.status, ra.format AS format
        FROM events e JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
        JOIN races ra ON ra.event_id = e.id
        WHERE co.code = :c AND e.source = :src AND s.year = :y
        ORDER BY e.start_date, e.id"""), conn, params=dict(c=competition, src=source, y=year))
    fmt = schedule["format"].apply(lambda f: f or {})
    schedule = schedule[fmt.apply(lambda f: f.get("race_type", "points") == "points")].copy()
    fmt = schedule["format"].apply(lambda f: f or {})
    schedule["chase"] = fmt.apply(lambda f: bool(f.get("playoff_round") or 0))
    schedule["stages"] = fmt.apply(lambda f: max(len(f.get("stage_laps") or []) - 1, 1) if f.get("stage_laps") else None)
    results = pd.read_sql(text("""
        SELECT e.id AS event_id, r.athlete_id, r.position, COALESCE((r.extra->>'points')::float, 0.0) AS points
        FROM events e JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
        JOIN races ra ON ra.event_id = e.id JOIN rounds ro ON ro.race_id = ra.id AND ro.kind = 'race'
        JOIN results r ON r.round_id = ro.id
        WHERE co.code = :c AND e.source = :src AND s.year = :y"""), conn, params=dict(c=competition, src=source, y=year))
    schedule["done"] = schedule["event_id"].isin(set(results["event_id"]))
    return results, schedule.drop(columns=["format"]).reset_index(drop=True)
