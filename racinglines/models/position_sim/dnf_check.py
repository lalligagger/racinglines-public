"""
DNF calibration of the position simulation (decision log 2026-10-06, provisional): how well a stage run's per-driver
dnf_prob (race_predictions.extra.dnf_prob) prices retirements, the input to race_retire, race_n_retirements and
race_first_retirement (markets/kinds.py). Pure pandas on an as-of export, no database:

    race_id, event_key, start, run_id, cutoff, grid, athlete_id, team_id (or team), dnf_prob, status, position

one row per driver per run. A retirement is status DNF or DSQ (the model's own rule), a finish is OK; rows with an
empty status (no result row) are dropped, and DNS or any other status is counted in `totals["other"]` but scored as
neither. With several runs of one race, the latest cutoff is scored.

Scored against two baselines on the same rows: `field` (one rate for every driver: the realised share over the rows,
in-sample, so it flatters the baseline) and `race_mean` (every driver in a race gets the run's mean dnf_prob: what
the model says about the race, without its split between drivers).

    racinglines f1 props --dnf-check dnf_asof.csv
"""

import numpy as np
import pandas as pd

RETIRED = ("DNF", "DSQ")
BUCKETS = (0.0, 0.05, 0.10, 0.15, 0.20, 1.0)
BUCKET_LABELS = ("0-5%", "5-10%", "10-15%", "15-20%", "20%+")


def _scores(p, y):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    se2 = (p - y) ** 2
    return dict(brier=float(se2.mean()), log_loss=float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()),
                se=float(se2.std(ddof=1) / np.sqrt(len(y))) if len(y) > 1 else float("nan"), mean_p=float(p.mean()))


def _latest(df, latest_only=True):
    """The rows with a status and a dnf_prob, of the latest run per race; a `team` column renamed team_id."""
    d = df.rename(columns={"team": "team_id"}) if "team" in df and "team_id" not in df else df
    d = d[d["status"].notna() & (d["status"].astype(str).str.strip() != "")].dropna(subset=["dnf_prob"]).copy()
    if latest_only and "cutoff" in d and "run_id" in d:
        d["_c"] = pd.to_datetime(d["cutoff"], utc=True, errors="coerce")
        last = d.sort_values(["_c", "run_id"]).groupby("race_id")["run_id"].last()
        d = d[d["run_id"] == d["race_id"].map(last)].drop(columns="_c")
    return d


def prepare(df, latest_only=True):
    """The scored rows: finished (OK) or retired (DNF, DSQ) drivers with a dnf_prob, the latest run per race;
    adds `y` (retired)."""
    d = _latest(df, latest_only)
    d = d[d["status"].isin(("OK",) + RETIRED)].copy()
    d["y"] = d["status"].isin(RETIRED).astype(float)
    d["dnf_prob"] = d["dnf_prob"].astype(float)
    return d.reset_index(drop=True)


def check(df, latest_only=True):
    """-> dict(summary: Brier / log loss / se / mean price per method; calibration: per predicted-probability bucket
    n, mean p, realised rate; totals: rows, races, mean predicted and realised DNF rate, retirements per race, and
    `other`: {status: rows} for the statuses scored as neither, e.g. DNS)."""
    d = prepare(df, latest_only)
    rest = _latest(df, latest_only)
    other = {str(k): int(v) for k, v in rest.loc[~rest["status"].isin(("OK",) + RETIRED), "status"].value_counts().items()}
    if d.empty:
        raise ValueError("no scored rows (need status and dnf_prob)")
    y = d["y"].to_numpy()
    meths = dict(model=d["dnf_prob"], field=np.full(len(d), y.mean()),
                 race_mean=d.groupby("race_id")["dnf_prob"].transform("mean"))
    summary = pd.DataFrame([dict(method=m, rows=len(d), yes_rate=float(y.mean()), **_scores(p, y))
                            for m, p in meths.items()])
    b = pd.cut(d["dnf_prob"], BUCKETS, labels=BUCKET_LABELS, right=False, include_lowest=True)
    cal = (d.assign(bucket=b).groupby("bucket", observed=False)
           .agg(n=("y", "size"), mean_p=("dnf_prob", "mean"), realised=("y", "mean")).reset_index())
    per_race = d.groupby("race_id").agg(pred=("dnf_prob", "sum"), real=("y", "sum"))
    totals = dict(rows=len(d), races=int(d["race_id"].nunique()), mean_p=float(d["dnf_prob"].mean()),
                  realised=float(y.mean()), pred_per_race=float(per_race["pred"].mean()),
                  real_per_race=float(per_race["real"].mean()), other=other)
    return dict(summary=summary, calibration=cal, totals=totals)


def render(out):
    """The check as text (the CLI's output)."""
    t = out["totals"]
    lines = [f"{t['rows']} driver rows, {t['races']} races: mean predicted DNF {t['mean_p']:.1%}, realised "
             f"{t['realised']:.1%}; per race {t['pred_per_race']:.2f} predicted, {t['real_per_race']:.2f} realised"
             + (f"; not scored: {', '.join(f'{k} {v}' for k, v in t['other'].items())}" if t["other"] else ""),
             "", out["summary"].to_string(index=False, float_format="{:.4f}".format), "",
             out["calibration"].to_string(index=False, float_format="{:.4f}".format)]
    return "\n".join(lines)
