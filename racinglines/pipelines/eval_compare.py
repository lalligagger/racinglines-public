"""
`racinglines eval compare RUN_A RUN_B`: two saved runs scored against the same outcomes, paired by event
(docs/engine-roadmap.md phase E5; docs/novig-and-model-bakeoff.md Part 2, "paired by event with ±2 standard errors").

It reads the prediction records of each run (racinglines/db/records.py, written with RACINGLINES_PREDICTION_RECORDS=1),
and works in four steps, each a function of plain frames so it runs on any two runs of any sport:

    pair(a, b)               inner join on (event_id, stage, kind, subject, params); the rows only one run has are
                             counted and reported, never dropped silently
    settle_rows(paired, ...) y per paired row from the official result, through the walk-forward's own settlement
                             (markets.kinds.settle on the sport's pricing model's `results`); a row that can't settle
                             (no result, an entrant the result doesn't list, an undecidable kind) is counted by
                             reason, reported as "paired but not settled" and left out of the scores
    compare(paired_y)        log loss and Brier per row (the clip of core/calibration.py), the mean per event for A and
                             for B, and B - A per event
    summarize(per_event)     per kind, per kind x season and pooled over seasons: the mean of the per-event
                             differences, its standard error over events (std, ddof 1, over sqrt(n)), and whether
                             0 lies outside ±2 SE

The score is "lower is better", so a negative difference (B - A) means B is the better forecast.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from racinglines.core import calibration as CAL

KEY = ["event_id", "stage", "kind", "subject", "params"]
SCORES = (("logloss", "log loss"), ("brier", "Brier"))
SUMMARY_COLUMNS = ["kind", "stage", "season", "n_events", "n_rows",
                   "logloss_a", "logloss_b", "logloss_diff", "logloss_se", "logloss_outside",
                   "brier_a", "brier_b", "brier_diff", "brier_se", "brier_outside"]


# --- pairing -------------------------------------------------------------------------------------

def _canon(p):
    """params as one canonical JSON string (sorted keys), whether the record holds a string, a dict or nothing."""
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "{}"
    return json.dumps(json.loads(p) if isinstance(p, str) else p, sort_keys=True)


def _keyed(df, label):
    df = df.copy()
    df["params"] = df["params"].map(_canon)
    df["event_id"] = df["event_id"].astype(str)
    df["subject"] = df["subject"].astype(str)
    df["stage"] = df["stage"].astype(str)
    dup = df.duplicated(KEY, keep=False)
    if dup.any():
        raise ValueError(f"run {label}: {int(dup.sum())} records share an (event, stage, kind, subject, params) key; "
                         f"the first is {df.loc[dup, KEY].iloc[0].to_dict()}")
    return df


def pair(records_a, records_b):
    """(paired, counts): the records both runs have, side by side, and the counts of what was left unpaired.
    paired: sport, season, event_id, event, stage, kind, subject, params, fair_a, fair_b, se_a, se_b.
    counts: n_a, n_b, paired, only_a, only_b (rows), and the same split by kind in `only_a_kinds` / `only_b_kinds`."""
    a, b = _keyed(records_a, "A"), _keyed(records_b, "B")
    cols = ["fair", "se"]
    m = a.merge(b[KEY + cols], on=KEY, how="outer", suffixes=("_a", "_b"), indicator=True)
    both = m[m["_merge"] == "both"]
    paired = both[["sport", "season", "event_id", "event", "stage", "kind", "subject", "params",
                   "fair_a", "fair_b", "se_a", "se_b"]].reset_index(drop=True)
    paired = paired.assign(season=pd.to_numeric(paired["season"]).astype("Int64"))     # the outer join made it a float
    only_b = b.merge(a[KEY], on=KEY, how="left", indicator=True)
    only_b = only_b[only_b["_merge"] == "left_only"]
    only_a = m[m["_merge"] == "left_only"]
    counts = dict(n_a=len(a), n_b=len(b), paired=len(paired), only_a=len(only_a), only_b=len(only_b),
                  only_a_kinds=only_a["kind"].value_counts().to_dict(), only_b_kinds=only_b["kind"].value_counts().to_dict())
    return paired, counts


# --- outcomes ------------------------------------------------------------------------------------

NO_RESULT, NOT_IN_RESULT, UNDECIDED = "no result", "entrant not in the result", "undecidable"
UNSETTLED = (NO_RESULT, NOT_IN_RESULT, UNDECIDED)


def settle_rows(paired, results_for):
    """The paired frame with a `y` column (1.0 / 0.0, NaN where the result can't settle the row) and `unsettled`, why
    not: no result for the event, an entrant (subject or opponent) the result doesn't list, or a kind the result
    can't decide (markets.kinds.settle's None). results_for(sport, event_id) -> the official result in
    markets.kinds.settle's shape (columns athlete_id, position, status, ...) or None. The settlement is
    markets.kinds.settle, the call core/walk_forward.event_rows makes: nothing is re-implemented. The record's subject
    is the one key of db/records.athlete_key; the result's athlete ids are looked up through it, whatever shape the
    sport's results carry."""
    from racinglines.db import records as REC
    from racinglines.markets import kinds as K
    y = pd.Series(np.nan, index=paired.index, dtype=float)
    why = pd.Series(None, index=paired.index, dtype=object)
    for (sport, event_id), g in paired.groupby(["sport", "event_id"], sort=False, dropna=False):
        res = results_for(sport, event_id)
        if res is None or res.empty:
            why[g.index] = NO_RESULT
            continue
        ids = {}
        for x in res["athlete_id"]:
            ids.setdefault(REC.subject_key(x), x)
        for i, kind, subject, params in zip(g.index, g["kind"], g["subject"], g["params"]):
            p = json.loads(params)
            if "team" in p:                           # a top team: the group key is the subject, the athlete none
                ok = K.settle(kind, None, p, res)
            else:
                a = ids.get(subject)
                b = ids.get(REC.subject_key(p["opponent_id"])) if "opponent_id" in p else None
                if a is None or ("opponent_id" in p and b is None):
                    why[i] = NOT_IN_RESULT
                    continue
                if b is not None:
                    p = dict(p, opponent_id=b)
                ok = K.settle(kind, a, p or None, res)
            if ok is None:
                why[i] = UNDECIDED
            else:
                y[i] = float(bool(ok))
    return paired.assign(y=y, unsettled=why)


def unsettled_counts(paired_y):
    """{reason: rows} over the paired rows with no y, in UNSETTLED's order, zero counts left out."""
    if "unsettled" not in paired_y:
        return {}
    c = paired_y["unsettled"].value_counts()
    return {r: int(c[r]) for r in UNSETTLED if r in c and c[r]}


def db_results(engine_url=None):
    """results_for(sport, event_id) reading the official result as the walk-forward does: the sport's pricing model
    loads its data once (model.load), `events` names the event, `results` is the official classification, marked with
    the sport's classified rule (markets.payoffs.mark_sport)."""
    from racinglines.markets import payoffs as P
    from racinglines.models import race_model as RM
    cache = {}

    def loaded(sport):
        if sport not in cache:
            model = RM.get(sport)
            data = model.load(engine_url)
            cache[sport] = (model, data, {str(ev.id): ev for ev in model.events(data, model.Settings.from_dict({}), None)})
        return cache[sport]

    def results_for(sport, event_id):
        model, data, events = loaded(sport)
        if event_id not in events:
            return None
        return P.mark_sport(model.results(data, events[event_id]), getattr(model, "sport", None))

    return results_for


# --- scores --------------------------------------------------------------------------------------

def compare(paired_y):
    """Per (kind, stage, season, event): n rows, the mean log loss and Brier of A and of B, and B - A. Rows with no y
    are left out here (settle_rows marks them; run() reports their number)."""
    d = paired_y.dropna(subset=["y"])
    cols = ["kind", "stage", "season", "event_id", "event", "n", "logloss_a", "logloss_b", "logloss_diff",
            "brier_a", "brier_b", "brier_diff"]
    if d.empty:
        return pd.DataFrame(columns=cols)
    y = d["y"].to_numpy(float)
    out = d[["kind", "stage", "season", "event_id", "event"]].copy()
    for s in "ab":
        p = d[f"fair_{s}"].to_numpy(float)
        q = np.clip(p, CAL.EPS, 1 - CAL.EPS)
        out[f"logloss_{s}"] = -(y * np.log(q) + (1 - y) * np.log(1 - q))
        out[f"brier_{s}"] = (p - y) ** 2
    out["n"] = 1
    g = out.groupby(["kind", "stage", "season", "event_id", "event"], sort=True, dropna=False)
    ev = g.agg(n=("n", "sum"), **{f"{m}_{s}": (f"{m}_{s}", "mean") for m in ("logloss", "brier") for s in "ab"}).reset_index()
    for m, _ in SCORES:
        ev[f"{m}_diff"] = ev[f"{m}_b"] - ev[f"{m}_a"]
    return ev[cols]


def _summ(g):
    row = dict(n_events=len(g), n_rows=int(g["n"].sum()))
    for m, _ in SCORES:
        d = g[f"{m}_diff"].to_numpy(float)
        se = float(np.std(d, ddof=1) / np.sqrt(len(d))) if len(d) > 1 else float("nan")
        mean = float(d.mean())
        row.update({f"{m}_a": float(g[f"{m}_a"].mean()), f"{m}_b": float(g[f"{m}_b"].mean()), f"{m}_diff": mean,
                    f"{m}_se": se, f"{m}_outside": bool(np.isfinite(se) and abs(mean) > 2 * se)})
    return row


def summarize(per_event):
    """Per (kind, stage, season) and pooled over seasons (season = "all"): the mean of the per-event differences, its
    standard error over events (paired by event) and whether 0 is outside ±2 SE. Events weigh equally."""
    if per_event.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    rows = []
    for (kind, stage), g in per_event.groupby(["kind", "stage"], sort=True):
        for season, h in g.groupby("season", sort=True, dropna=False):
            rows.append(dict(kind=kind, stage=stage, season=str(season), **_summ(h)))
        rows.append(dict(kind=kind, stage=stage, season="all", **_summ(g)))
    return pd.DataFrame(rows)[SUMMARY_COLUMNS]


# --- the report ----------------------------------------------------------------------------------

def format_markdown(summary, run_a, run_b, counts=None, unsettled=0, unsettled_why=None):
    stages = summary["stage"].nunique() if len(summary) else 0
    head = ["kind"] + (["stage"] if stages > 1 else []) + ["season", "n events", "logloss A", "logloss B", "diff ± 2 SE",
                                                           "Brier A", "Brier B", "diff ± 2 SE"]
    lines = [f"Run A = {run_a}, run B = {run_b}. diff = B - A; lower is better, so a negative diff favours B. "
             f"`*` marks a diff whose ±2 SE (over events, paired) excludes 0.", "",
             "| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]

    def dd(r, m):
        se = r[f"{m}_se"]
        star = "*" if r[f"{m}_outside"] else ""
        return f"{r[f'{m}_diff']:+.4f} ± {2 * se:.4f}{star}" if np.isfinite(se) else f"{r[f'{m}_diff']:+.4f} (1 event)"

    for r in summary.to_dict("records"):
        cells = [r["kind"]] + ([r["stage"]] if stages > 1 else []) + [
            r["season"], str(r["n_events"]), f"{r['logloss_a']:.4f}", f"{r['logloss_b']:.4f}", dd(r, "logloss"),
            f"{r['brier_a']:.4f}", f"{r['brier_b']:.4f}", dd(r, "brier")]
        lines.append("| " + " | ".join(cells) + " |")
    if counts:
        lines += ["", f"Paired {counts['paired']} rows (A has {counts['n_a']}, B has {counts['n_b']}); "
                      f"only in A: {counts['only_a']}{_kinds(counts['only_a_kinds'])}; "
                      f"only in B: {counts['only_b']}{_kinds(counts['only_b_kinds'])}; "
                      f"paired but not settled (left out of the scores): {unsettled}{_kinds(unsettled_why)}."]
    return "\n".join(lines)


def _kinds(d):
    return " (" + ", ".join(f"{k} {v}" for k, v in d.items()) + ")" if d else ""


def run(run_a, run_b, kinds=None, stage=None, out_dir=None, echo=print, results_for=None, engine_url=None, write=True):
    """Compare two saved runs on their prediction records. Returns dict(paired, per_event, summary, counts, unsettled,
    unsettled_why: {reason: rows} of the paired rows left out of the scores).
    results_for: how a result is read (default: the sport's pricing model on engine_url, db_results). write=False
    (the MCP tool) writes nothing; otherwise compare.csv (per event) and compare.md (summary) go to out_dir, by default
    data/runs/eval/<run_a>-vs-<run_b>/."""
    from racinglines import paths
    from racinglines.db import records as REC
    frames = []
    for label, rid in (("A", run_a), ("B", run_b)):
        try:
            df = REC.read(rid)
        except FileNotFoundError:
            raise ValueError(f"run {rid} ({label}) has no prediction records in {REC.records_dir()}; run it with "
                             f"--save and {REC.SWITCH}=1") from None
        if kinds:
            df = df[df["kind"].isin(kinds)]
        if stage:
            df = df[df["stage"] == stage]
        frames.append(df)
    paired, counts = pair(*frames)
    if not len(paired):
        echo(f"No records pair: run {run_a} has {counts['n_a']} rows and run {run_b} {counts['n_b']} after the filters, "
             f"and none share an (event, stage, kind, subject, params) key.")
    paired_y = settle_rows(paired, results_for or db_results(engine_url)) if len(paired) else \
        paired.assign(y=np.nan, unsettled=None)
    unsettled, why = int(paired_y["y"].isna().sum()), unsettled_counts(paired_y)
    per_event = compare(paired_y)
    summary = summarize(per_event)
    md = format_markdown(summary, run_a, run_b, counts, unsettled, why)
    echo(md)
    if write:
        d = Path(out_dir) if out_dir else paths.runs("eval", f"{run_a}-vs-{run_b}", mkdir=False)
        d.mkdir(parents=True, exist_ok=True)
        per_event.to_csv(d / "compare.csv", index=False)
        (d / "compare.md").write_text(md + "\n")
        echo(f"\nFiles -> {d}/")
    return dict(paired=paired_y, per_event=per_event, summary=summary, counts=counts, unsettled=unsettled,
                unsettled_why=why)
