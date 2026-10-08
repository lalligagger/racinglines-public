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

Two kinds of kind. The declarative kinds (the sportsbook classification and retirement markets) are specs in
markets/kinds.toml: subject / predicate / aggregate / compare, priced and settled by the two generic functions of
racinglines/markets/payoffs.py, so a new one is a table in that file, not a branch here (owner, 2026-10-06: "as few
conditional code switches in the model, and more generalized support functions who's inputs are set by the
schemas"). The legacy kinds below (payoffs top_n, stage_top_n, reached, h2h, group_top, standings, indicator,
mover) keep their code in this change: their fair values feed the golden tests and the live book, and moving them
onto specs is a later change under the promotion rule (docs/f1-roadmap.md).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from racinglines.markets import payoffs as P

first_retired = P.first_retired          # re-exported (tests/test_kinds.py)


@dataclass(frozen=True)
class Kind:
    code: str
    payoff: str               # top_n | stage_top_n | h2h | reached | group_top | indicator | mover | standings (not from
                              # sims) | spec (a declarative kind: markets/kinds.toml, priced and settled by payoffs.py)
                              # | prop (a history-rate race prop, PROPS below: not in KINDS)
    n: int | None = None      # top_n / stage_top_n
    stage: str | None = None  # stage_top_n / mover: which earlier round (sims.stage_rank key); reached: which round
    label: str = ""
    default: bool = True      # False: priced only when named (fair(), a model's own summary); left out of summary(),
                              # to_records and the walk-forward default set, so adding one changes no existing output
    spec: dict | None = field(default=None, compare=False)   # payoff "spec": {"payoff": {...}, "settle": {...}}
    wx: str | None = None     # how a probability of rain moves its price (models/position_sim/props.py): None, not at
                              # all; "rate" a yes/no rate priced with props.rate_wx; "dnf" its drivers' dnf_prob scaled by
                              # props.wx_scale before pricing. Declarative kinds: `wx = "..."` in markets/kinds.toml
    session: str | None = None   # a market on an earlier round raced as its own classification (F1: "sprint"):
                                 # priced on sims.at(session), settled on the result's <session>_ columns


# Declared in the order the readers list prediction kinds (db/reads.PREDICTION_KINDS is derived from it).
# payoff "standings": season-long markets read from a model run's standings, not priced from an OutcomeSims.
LEGACY = (
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
    # payoff "indicator": a yes/no the model draws itself in each simulation (sims.indicators[code]). F1's
    # fastest lap is drawn by position_sim behind its `fastlap` variant (model.FASTEST_LAP, off by default) and
    # stored as race_predictions.extra.fl_prob; the classification doesn't record it, so settle() can't decide it
    Kind("race_fastest_lap", "indicator", label="Fastest lap"),
    # Kalshi's KXF1TOP5 and KXF1BIGGESTMOVER: F1 position_sim stores them as extra.top5_prob / extra.mover_prob.
    # Biggest mover: the classified driver with the largest gain from the starting grid to the finish, if anyone
    # gained; every driver tied on that gain counts as YES (docs/f1-roadmap.md decision log, 2026-10-04)
    Kind("race_top5", "top_n", n=5, label="Top 5", default=False),
    Kind("race_biggest_mover", "mover", stage="qual", label="Biggest mover", default=False),
    # The sprint as a race of its own (models/position_sim/pricing.price_stages, docs/todo.md U13): the race payoffs
    # on the sprint's classification and points. Kept out of every default set and live book (owner, DEC-12) until
    # their settlement is proven
    Kind("race_sprint_podium", "top_n", n=3, label="Sprint podium", default=False, session="sprint"),
    Kind("race_sprint_top8", "top_n", n=8, label="Sprint top 8", default=False, session="sprint"),
    Kind("race_sprint_h2h", "h2h", label="Sprint head-to-head", default=False, session="sprint"),
    Kind("race_sprint_constructor_top", "group_top", label="Sprint top constructor", default=False, session="sprint"),
    # Qualifying as a classification of its own (owner, 2026-10-07: every session's markets, combo legs included): priced
    # from sims.stage_rank["qual"], the simulated qualifying order before qualifying, the real one after; settled from
    # the results' qual_position (the head-to-head needs qual_status too, which the result frame doesn't carry yet:
    # undecidable until then). Kept out of every default set and live book
    Kind("race_qual_top3", "stage_top_n", n=3, stage="qual", label="Qualifying top 3", default=False),
    Kind("race_qual_top10", "stage_top_n", n=10, stage="qual", label="Qualifying top 10 (reaches Q3)", default=False),
    Kind("race_qual_h2h", "h2h", label="Qualifying head-to-head", default=False, session="qual"),
)

# The declarative kinds (markets/kinds.toml), after the legacy ones in the file's order: the sportsbook classification
# markets (docs/sportsbook/) and the retirements (decision log 2026-10-06, provisional), all default=False.
KINDS = {k.code: k for k in LEGACY + tuple(
    Kind(e["code"], "spec", label=e["label"], default=e["default"], spec=e, wx=e["wx"]) for e in P.load().values())}

# The race props priced from the race history (models/position_sim/props.py), not from simulations: kinds for their
# `wx` only, kept out of KINDS so the prediction kinds (db/reads.PREDICTION_KINDS) and every summary stay as they are.
# The red flag is priced given a probability of rain; the safety car is not (conditioning it was worse in the
# walk-forward, decision log 2026-10-06) and rain is the forecast itself.
PROPS = (
    Kind("race_safety_car", "prop", label="Safety car", default=False),
    Kind("race_red_flag", "prop", label="Red flag", default=False, wx="rate"),
    Kind("race_rain", "prop", label="Rain", default=False),
)


def wx_kinds(how):
    """The codes whose `wx` is `how` ("rate" or "dnf"), props first, then KINDS in registry order."""
    return tuple(k.code for k in PROPS + tuple(KINDS.values()) if k.wx == how)


# --- fair values ---------------------------------------------------------------------------------------

def fair(kind, sims, a=None, b=None, line=None):
    """Fair probability of YES. Per-entrant kinds return an array over sims.entrants (or one value with
    `a` = an athlete id); race_h2h needs a and b; race_constructor_top and the team kinds of markets/kinds.toml
    return {group: probability}; its field kinds with compare over (race_n_classified, race_n_retirements) need
    `line` and return P(over)."""
    k = KINDS[kind]
    if k.session is not None:                  # an earlier round's own classification (the sprint)
        sims = sims.at(k.session)
    if k.spec is not None:
        try:
            return P.fair(k.spec["payoff"], sims, a=a, line=line)
        except ValueError as e:
            raise ValueError(f"{kind}: {e}") from None
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
    elif k.payoff == "indicator":
        if kind not in sims.indicators:
            raise ValueError(f"{kind}: these simulations don't draw it")
        p = sims.indicators[kind].mean(0)
    elif k.payoff == "mover":
        if k.stage not in sims.stage_rank:
            raise ValueError(f"{kind}: these simulations have no {k.stage} order")
        p = biggest_mover(sims.stage_rank[k.stage], sims.rank, sims.finished).mean(0)
    elif k.payoff == "standings":
        raise ValueError(f"{kind} is a standings market: not priced from an OutcomeSims")
    else:
        raise ValueError(f"unknown payoff {k.payoff}")
    return p if a is None else float(p[sims.index(a)])


def biggest_mover(grid, rank, finished):
    """(n_sims, n) bool: who has the largest gain from `grid` to `rank` among the cars that finished, in each
    simulation; nobody when no one gained, everyone tied on the largest gain."""
    gain = np.where(finished, np.asarray(grid, float) - rank, -np.inf)
    best = gain.max(axis=1, keepdims=True)
    return (gain == best) & (best > 0)


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
    for payoff in ("top_n", "stage_top_n", "reached", "indicator"):     # columns grouped by payoff, in registry order
        for code, k in KINDS.items():
            if k.payoff != payoff or not k.default:
                continue
            if payoff == "indicator":
                has = code in sims.indicators
            else:
                has = payoff == "top_n" or k.stage in (sims.stage_rank if payoff == "stage_top_n" else sims.reached)
            if has:
                out[code] = fair(code, sims)
    return pd.DataFrame(out)


# --- season-long markets, from a season simulation ------------------------------------------------------------

def season_fair(kind, ss, a=None, b=None, n=None):
    """Fair probability of YES for a "standings" kind from an outcomes.SeasonSims (a season simulation; `fair`
    above stays for race markets). champion / standings_top3: per entrant (or one value with `a`); standings_h2h:
    the matrix, or P(a finishes the season ahead of b); season_wins_ge: P(at least n wins)."""
    k = KINDS[kind]
    if k.payoff != "standings":
        raise ValueError(f"{kind} is a race market: priced by fair() from an OutcomeSims")
    if kind == "champion":
        p = standings_position(ss, 1)
    elif kind == "standings_top3":
        p = standings_position(ss, 3)
    elif kind == "standings_h2h":
        if a is None:
            r = ss.rank
            return (r[:, :, None] < r[:, None, :]).mean(0)
        return float((ss.rank[:, ss.index(a)] < ss.rank[:, ss.index(b)]).mean())
    elif kind == "season_wins_ge":
        if ss.wins is None or n is None:
            raise ValueError("season_wins_ge needs simulated wins and n")
        p = (ss.wins >= n).mean(0)
    else:
        raise ValueError(f"{kind} is not priced from a driver season simulation")
    return p if a is None else float(p[ss.index(a)])


def standings_position(ss, n):
    """P(finishing the season in the top `n` of the standings), per entrant: the points-position payoff
    (n = 1 is the champion)."""
    return (ss.rank <= n).mean(0)


# --- settlement ----------------------------------------------------------------------------------------

def session_result(res, session):
    """An earlier round's classification out of the race's result frame (private_book.race_outcomes adds
    <session>_position / _status / _points), as a result frame of its own: the drivers who took part in it.
    None when the frame doesn't carry it (that round's results aren't in yet)."""
    cols = {f"{session}_{c}": c for c in ("position", "status", "points")}
    if not set(cols) <= set(res.columns):
        return None
    out = res.drop(columns=[c for c in cols.values() if c in res]).rename(columns=cols)
    out = out[out["status"].notna()]
    return out if len(out) else None


def settle(kind, athlete_id, params, res, group_key=None):
    """YES/NO for a race market from the official classification (None if undecidable).
    group_key: maps a result's team_id to the group key the market names (F1: position_sim team_key).
    The n-th retirement kinds read a `laps_completed` column when the frame has one (the caller adds it; nothing here
    queries the database): the DNF with the fewest laps is first, every tied driver YES."""
    if res.empty:
        return None
    k = KINDS.get(kind)
    if k is not None and k.session is not None:
        res = session_result(res, k.session)
        if res is None:
            return None
    if k is not None and k.spec is not None:
        return P.settle(k.spec["settle"], athlete_id, params, res, group_key=group_key)
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
    if k.payoff == "mover":
        return None          # needs the starting grid, which the results don't store (qual_position misses penalties)
    if k.payoff == "group_top":
        keys =res["team_id"].map(group_key) if group_key else res["team_id"]
        pts = res.assign(tk=keys).groupby("tk")["points"].sum()
        return bool(pts.idxmax() == (params or {}).get("team")) if len(pts) else None
    return None
