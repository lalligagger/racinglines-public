"""
Declarative market kinds: a kind is a payoff spec read from markets/kinds.toml, and two generic functions turn any
spec into a fair value and a settlement. No per-kind branch: a spec names a predicate, an aggregate and a comparison,
each a small table of named functions below.

    load()                                    {code: entry} from markets/kinds.toml, every spec checked
    fair(spec, sims, a=None, line=None)       from a model's simulations (racinglines/models/outcomes.py)
    settle(spec, athlete_id, params, res)     YES / NO / None (undecidable) from the results frame
    check(spec)                               the spec, or ValueError naming the bad field

A spec (an entry's `payoff` table; `settle` holds the settlement view, the payoff table with its overrides):

    subject    driver | team | field        driver: per entrant; team: {group: p}; field: one value
    predicate  classified | retired | top | last_classified | nth_retired     (n_sims, n_cars), bool or float
    n          top / nth_retired
    aggregate  any | all | sum | count      how a team's or the field's cars combine (none for driver)
    compare    over                         P(aggregate > line)
    absent     no | void                    settlement only: a driver missing from the results (default void)

    fair({"subject": "team", "predicate": "top", "n": 5, "aggregate": "any"}, sims)    a team with a car in the top 5

Owner (2026-10-06): "as few conditional code switches in the model, and more generalized support functions who's
inputs are set by the schemas". The 13 classification and retirement kinds are declared this way. The legacy kinds
in racinglines/markets/kinds.py (top_n, stage_top_n, reached, h2h, group_top, standings, indicator, mover payoffs)
keep their code: their fair values feed the golden tests and the live book, and moving them here is a later change
under the promotion rule (docs/f1-roadmap.md).
"""

import tomllib
from functools import cache
from pathlib import Path

import numpy as np

from racinglines.paths import ROOT

PATH = ROOT / "markets" / "kinds.toml"
RETIRED = ("DNF", "DSQ")      # result statuses that count as a retirement
SUBJECTS = ("driver", "team", "field")
ABSENT = {"no": False, "void": None}


# --- predicates: one car, every simulation or every result row ---------------------------------------------------

def last_classified(rank, finished):
    """(n_sims, n) bool: the classified car with the worst rank in each simulation (everyone tied on it counts);
    nobody when no car is classified."""
    r = np.where(finished, np.asarray(rank, float), -np.inf)
    worst = r.max(axis=1, keepdims=True)
    return (r == worst) & np.isfinite(worst)


def first_retired(finished):
    """(n_sims, n) float: each car's chance of being the first retirement in each simulation, under the uniform
    timing assumption (the simulations draw who retires, not when): 1 / n_dnf for every retiring car, 0 for the
    rest and for every car when nobody retires. Rows sum to 1, or 0 with no retirement."""
    dnf = ~np.asarray(finished, bool)
    n = dnf.sum(axis=1, keepdims=True)
    return np.where(dnf, 1.0 / np.maximum(n, 1), 0.0)


def nth_retired(finished, n):
    """(n_sims, n_cars) float: each car's chance of being the n-th retirement under the uniform timing assumption:
    first_retired's 1 / n_dnf for every retiring car in a simulation with at least n retirements, else 0."""
    dnf = ~np.asarray(finished, bool)
    enough = dnf.sum(axis=1, keepdims=True) >= n
    return np.where(enough, first_retired(finished), 0.0)


def _ok(res):
    return res["status"] == "OK"


def _res_retired(res, s):
    v = res["status"].isin(RETIRED).astype(object)
    v[res["status"] == "DNS"] = None             # a non-starter: void, not a retirement
    return v


def _res_last_classified(res, s):
    ok = _ok(res)
    if not ok.any():
        return None
    return ok & (res["position"] == res.loc[ok, "position"].max())


def _res_nth_retired(res, s):
    dnf = res["status"] == "DNF"                 # a DSQ is decided after the flag, not a car stopping first
    if not dnf.any():
        return dnf                               # nobody retired: every driver (and team) is a NO
    if "laps_completed" not in res or res.loc[dnf, "laps_completed"].isna().any():
        return None
    place = res.loc[dnf, "laps_completed"].rank(method="min")              # competition ranking: ties share the place
    return dnf & (place.reindex(res.index) == s["n"])


# name -> (on the simulations: (sims, spec) -> (n_sims, n_cars) array,
#          on the results: (res, spec) -> a value per row (True / False / None) or None when the frame can't decide,
#          the fields it needs)
PREDICATES = {
    "classified": (lambda sims, s: sims.finished,
                   lambda res, s: _ok(res), ()),
    "retired": (lambda sims, s: ~sims.finished,
                _res_retired, ()),
    "top": (lambda sims, s: (sims.rank <= s["n"]) & sims.finished,
            lambda res, s: _ok(res) & (res["position"] <= s["n"]), ("n",)),
    "last_classified": (lambda sims, s: last_classified(sims.rank, sims.finished),
                        _res_last_classified, ()),
    "nth_retired": (lambda sims, s: nth_retired(sims.finished, s["n"]),
                    _res_nth_retired, ("n",)),
}


# --- aggregates: a team's or the field's cars -> one value per simulation, or one settlement ---------------------

def _vals(vals):
    """True / False / None (undecided) per car."""
    return [None if v is None or (isinstance(v, float) and np.isnan(v)) else bool(v) for v in vals]


def _any(vals):
    vals = _vals(vals)
    return True if True in vals else (None if None in vals else False)


def _all(vals):
    vals = _vals(vals)
    return False if False in vals else (None if None in vals else True)


def _count(vals):
    return sum(1 for v in _vals(vals) if v)


# name -> (on the simulations: (n_sims, k) -> (n_sims,), on the results: [True / False / None] -> value)
AGGREGATES = {
    "any": (lambda v: v.any(axis=1), _any),
    "all": (lambda v: v.all(axis=1), _all),
    "sum": (lambda v: v.sum(axis=1), _count),       # per-car shares of one outcome (first retiring constructor)
    "count": (lambda v: v.sum(axis=1), _count),
}
COUNTS = ("sum", "count")


# name -> (on the simulations: (x, line) -> bool array, on the results: (x, line) -> bool)
COMPARES = {
    "over": (lambda x, line: x > line, lambda x, line: bool(x > float(line))),
}


# --- the spec ------------------------------------------------------------------------------------------------------

def check(spec, where="spec"):
    """The spec unchanged, or ValueError naming the first bad field (`where`.field)."""
    def bad(field, msg):
        raise ValueError(f"{where}.{field}: {msg}")
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: must be a table")
    subject, pred, agg, comp = spec.get("subject"), spec.get("predicate"), spec.get("aggregate"), spec.get("compare")
    if subject not in SUBJECTS:
        bad("subject", f"{subject!r} not in {SUBJECTS}")
    if pred not in PREDICATES:
        bad("predicate", f"{pred!r} not in {tuple(PREDICATES)}")
    for f in PREDICATES[pred][2]:
        if isinstance(spec.get(f), bool) or not isinstance(spec.get(f), int) or spec[f] < 1:
            bad(f, f"predicate {pred} needs a positive integer {f}, got {spec.get(f)!r}")
    if subject == "driver":
        if agg is not None:
            bad("aggregate", "a driver kind has no aggregate")
    elif agg not in AGGREGATES:
        bad("aggregate", f"{agg!r} not in {tuple(AGGREGATES)}")
    if comp is not None and comp not in COMPARES:
        bad("compare", f"{comp!r} not in {tuple(COMPARES)}")
    if comp is not None and agg not in COUNTS:
        bad("compare", f"compares a count: aggregate must be one of {COUNTS}, got {agg!r}")
    if agg == "count" and comp is None:
        bad("compare", "a count needs a compare (e.g. over)")
    if "absent" in spec and spec["absent"] not in ABSENT:
        bad("absent", f"{spec['absent']!r} not in {tuple(ABSENT)}")
    return spec


def load(path=None):
    """{code: {"code", "label", "default", "payoff", "settle"}} in file order, every spec checked; `settle` is the
    payoff spec with the file's [kinds.settle] overrides. markets/kinds.toml is read once; another `path` each call."""
    return _default() if path is None else _parse(Path(path))


@cache
def _default():
    return _parse(PATH)


def _parse(p):
    with open(p, "rb") as f:
        entries = tomllib.load(f).get("kinds", [])
    out = {}
    for i, e in enumerate(entries):
        code = e.get("code")
        where = f"{p.name}: kinds[{i}]" + (f" ({code})" if code else "")
        if not isinstance(code, str) or not code:
            raise ValueError(f"{where}.code: missing")
        if code in out:
            raise ValueError(f"{where}.code: {code} declared twice")
        if e.get("default", False) is not False:
            raise ValueError(f"{where}.default: declarative kinds are default = false (summary() and the records "
                             "read only the legacy payoffs)")
        payoff = check(e.get("payoff"), f"{where}.payoff")
        settle = check({**payoff, **e.get("settle", {})}, f"{where}.settle")
        out[code] = dict(code=code, label=e.get("label", code), default=False, payoff=payoff, settle=settle)
    return out


# --- pricing -------------------------------------------------------------------------------------------------------

def _compare(s, x, line):
    if s.get("compare") is None:
        return x
    if line is None:
        raise ValueError("needs a line (e.g. 18.5)")
    return COMPARES[s["compare"]][0](x, line)


def fair(spec, sims, a=None, line=None):
    """Fair probability of YES from an OutcomeSims. driver: an array over sims.entrants (or one value with `a`);
    team: {group: probability} over sims.groups; field: one probability (P(count > line) for compare over)."""
    s = check(spec)
    v = PREDICATES[s["predicate"]][0](sims, s)
    if s["subject"] == "driver":
        p = v.mean(0)
        return p if a is None else float(p[sims.index(a)])
    agg = AGGREGATES[s["aggregate"]][0]
    if s["subject"] == "field":
        return float(_compare(s, agg(v), line).mean())
    if sims.groups is None:
        raise ValueError("group markets need groups")
    g = np.array(sims.groups)
    return {key: float(_compare(s, agg(v[:, g == key]), line).mean()) for key in sorted(set(sims.groups))}


# --- settlement ----------------------------------------------------------------------------------------------------

def settle(spec, athlete_id, params, res, group_key=None):
    """YES / NO / None (undecidable) from the results frame (athlete_id, position, status, team_id, and
    laps_completed when the frame has one). driver: `athlete_id`; team: params["team"], results' team_id mapped
    through `group_key`; compare over: params["line"]."""
    s = check(spec)
    if res.empty:
        return None
    v = PREDICATES[s["predicate"]][1](res, s)
    if v is None:
        return None
    params = params or {}
    if s["subject"] == "driver":
        rows = res["athlete_id"] == athlete_id
        if not rows.any():
            return ABSENT[s.get("absent", "void")]
        return _any(list(v[rows]))
    if s["subject"] == "team":
        keys = res["team_id"].map(group_key) if group_key else res["team_id"]
        rows = keys == params.get("team")
        if not rows.any():
            return None
        vals = list(v[rows])
    else:
        vals = list(v)
    x = AGGREGATES[s["aggregate"]][1](vals)
    if s.get("compare") is not None:
        line = params.get("line")
        return None if line is None else COMPARES[s["compare"]][1](x, line)
    return x if x is None or isinstance(x, bool) else bool(x > 0)
