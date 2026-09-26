#!/usr/bin/env python3
"""
predictor.py — Build per-rider models from tidy DH split data (as produced
by parser.py) and predict an upcoming event.

WHAT IT BUILDS
--------------
1. Relative performance metrics per event/round (pct_back, robust z-score)
   computed off FINISH cum_time_s, since raw seconds aren't comparable
   across different tracks.

2. A rider skill rating (Elo-style, updated race-by-race from pairwise
   finishing-order comparisons within each round). This handles DNFs/DNS
   gracefully and doesn't require every rider to have raced every course —
   the two things that break plain time-regression on sparse DH fields.

3. A recency-weighted rider "form" feature (EWMA of pct_back) plus a
   rider x venue historical prior, for the time-regression model.

4. A gradient-boosted regressor (sklearn) predicting pct_back-at-finish
   from: elo rating, form EWMA, venue prior, start order, round, and
   track condition. This is your "how far back from the leader" estimate.

5. Walk-forward validation (train on everything before event N, test on N)
   so you get an honest error estimate instead of a leaked one.

6. A predict mode: given an elo-rated field + start list for an upcoming
   event, outputs (a) simulated finish-order win/podium probabilities via
   Plackett-Luce sampling on the elo ratings, and (b) expected pct_back /
   gap-to-leader from the regression model.

USAGE
-----
    # Fit ratings + model, run walk-forward validation, save artifacts
    python predictor.py fit --data splits.csv --out-dir model/

    # Predict an upcoming event from a start list
    python predictor.py predict --model-dir model/ --start-list startlist.csv \\
        --out predictions.csv

startlist.csv needs at minimum: rider_id (or rider_name), start_order,
track_condition (dry/wet/mixed/unknown). rider_id must match the IDs
parser.py generated (uci:<id> or name:<normalized name>).
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

RNG = np.random.default_rng(42)

# ---------------------------------------------------------------------------
# 1. Relative performance metrics
# ---------------------------------------------------------------------------

def add_relative_metrics(df):
    """df: long-format finish rows only (sector_id == 'FINISH', status == OK).
    Adds pct_back and robust z-score of cum_time_s within each event+round."""
    df = df.copy()
    grp = df.groupby(["event_id", "round"])["cum_time_s"]
    fastest = grp.transform("min")
    median = grp.transform("median")
    mad = grp.transform(lambda s: (s - s.median()).abs().median() * 1.4826 or 1.0)
    df["pct_back"] = df["cum_time_s"] / fastest - 1.0
    df["z_score"] = (df["cum_time_s"] - median) / mad
    return df


# ---------------------------------------------------------------------------
# 2. Elo-style rider ratings from pairwise finishing order
# ---------------------------------------------------------------------------

def fit_elo_ratings(finish_df, k=24, base_rating=1500.0):
    """Chronological pairwise Elo update. Within each (event_id, round),
    every finisher is treated as having beaten every rider who finished
    behind them (or DNF'd/DSQ'd). Returns a dict rider_id -> rating and a
    rating history list for inspection/decay-weighting later."""
    ratings = {}
    history = []

    finish_df = finish_df.sort_values(["event_date", "event_id", "round"])
    for (event_id, round_), g in finish_df.groupby(["event_id", "round"], sort=False):
        g = g.sort_values("cum_time_s", na_position="last")  # NaN = DNF/DSQ, sorts last
        riders = g["rider_id"].tolist()
        for r in riders:
            ratings.setdefault(r, base_rating)

        n = len(riders)
        deltas = {r: 0.0 for r in riders}
        # Compare every pair once (n is small per round, typically <120)
        for i in range(n):
            for j in range(i + 1, n):
                ri, rj = riders[i], riders[j]
                exp_i = 1.0 / (1.0 + 10 ** ((ratings[rj] - ratings[ri]) / 400.0))
                # i finished ahead of j -> actual score for i = 1
                deltas[ri] += k * (1 - exp_i) / (n - 1)
                deltas[rj] += k * (0 - (1 - exp_i)) / (n - 1)
        for r in riders:
            ratings[r] += deltas[r]
            history.append(dict(event_id=event_id, round=round_, rider_id=r, rating=ratings[r]))

    return ratings, pd.DataFrame(history)


# ---------------------------------------------------------------------------
# 3. Recency-weighted form + venue prior
# ---------------------------------------------------------------------------

def add_form_features(finish_df, half_life_days=270):
    """EWMA of pct_back per rider over time (lower pct_back = better form),
    plus a rider x venue historical mean pct_back (shrunk toward the
    rider's overall mean when venue history is thin)."""
    df = finish_df.sort_values(["rider_id", "event_date"]).copy()
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    df["form_ewma"] = np.nan
    lam = np.log(2) / half_life_days

    # Loop per rider explicitly (robust across pandas versions — groupby+apply
    # has version-dependent quirks around dropping/renaming the group key).
    for rider_id, idx in df.groupby("rider_id").groups.items():
        g = df.loc[idx].sort_values("event_date")
        t = g["event_date"].astype("int64").to_numpy() / 1e9 / 86400  # days
        vals = g["pct_back"].to_numpy()
        form = np.full(len(g), np.nan)
        for i in range(1, len(g)):
            weights = np.exp(-lam * (t[i] - t[:i]))
            form[i] = np.average(vals[:i], weights=weights)
        df.loc[g.index, "form_ewma"] = form

    # venue prior: rider's historical mean pct_back at this event_id's venue
    # (venue proxied by event_id prefix before the round-specific suffix;
    # adjust this if your event_ids encode venue differently)
    df["venue_key"] = df["event_id"].str.replace(r"_(qual|semi|final|practice|seeding).*$", "", regex=True)
    overall_mean = df.groupby("rider_id")["pct_back"].transform("mean")
    venue_mean = df.groupby(["rider_id", "venue_key"])["pct_back"].transform("mean")
    venue_n = df.groupby(["rider_id", "venue_key"])["pct_back"].transform("count")
    shrink = venue_n / (venue_n + 3)  # shrink toward overall mean when n is small
    df["venue_prior"] = shrink * venue_mean + (1 - shrink) * overall_mean

    df["form_ewma"] = df["form_ewma"].fillna(overall_mean)
    return df


# ---------------------------------------------------------------------------
# 4. Time-regression model
# ---------------------------------------------------------------------------

FEATURE_COLS = ["elo_rating", "form_ewma", "venue_prior", "start_order_norm"]
CATEGORICAL_COLS = ["round", "track_condition"]


def build_feature_matrix(df, elo_ratings):
    df = df.copy()
    df["elo_rating"] = df["rider_id"].map(elo_ratings).fillna(1500.0)
    df["start_order_norm"] = df.groupby(["event_id", "round"])["start_order"].transform(
        lambda s: (s - s.min()) / (s.max() - s.min()) if s.max() != s.min() else 0.5
    )
    df["start_order_norm"] = df["start_order_norm"].fillna(0.5)
    for c in CATEGORICAL_COLS:
        df[c] = df[c].fillna("unknown").astype(str)
    dummies = pd.get_dummies(df[CATEGORICAL_COLS], prefix=CATEGORICAL_COLS)
    X = pd.concat([df[FEATURE_COLS].fillna(0), dummies], axis=1)
    return X, df


def fit_time_model(df, elo_ratings):
    X, df2 = build_feature_matrix(df, elo_ratings)
    y = df2["pct_back"].fillna(df2["pct_back"].median())
    model = GradientBoostingRegressor(
        n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=0
    )
    model.fit(X, y)
    return model, list(X.columns)


# ---------------------------------------------------------------------------
# 5. Walk-forward validation
# ---------------------------------------------------------------------------

def walk_forward_validate(finish_df, min_train_events=15):
    events_ordered = (
        finish_df[["event_date", "event_id", "round"]]
        .drop_duplicates()
        .sort_values("event_date")
        .reset_index(drop=True)
    )
    errors = []
    for i in range(min_train_events, len(events_ordered)):
        cutoff_key = events_ordered.loc[i, ["event_id", "round"]]
        train_keys = events_ordered.iloc[:i][["event_id", "round"]]
        train_mask = finish_df.set_index(["event_id", "round"]).index.isin(
            train_keys.set_index(["event_id", "round"]).index
        )
        test_mask = (finish_df["event_id"] == cutoff_key["event_id"]) & (
            finish_df["round"] == cutoff_key["round"]
        )
        train_df, test_df = finish_df[train_mask], finish_df[test_mask]
        if len(train_df) < 30 or len(test_df) < 3:
            continue
        elo, _ = fit_elo_ratings(train_df)
        train_feat = add_form_features(train_df)
        model, cols = fit_time_model(train_feat, elo)

        test_feat = add_form_features(pd.concat([train_df, test_df]))
        test_feat = test_feat[test_feat["event_id"] == cutoff_key["event_id"]]
        Xtest, _ = build_feature_matrix(test_feat, elo)
        Xtest = Xtest.reindex(columns=cols, fill_value=0)
        preds = model.predict(Xtest)
        mae = mean_absolute_error(test_feat["pct_back"].fillna(0), preds)
        errors.append(dict(event_id=cutoff_key["event_id"], round=cutoff_key["round"],
                            n_riders=len(test_df), mae_pct_back=mae))
    return pd.DataFrame(errors)


# ---------------------------------------------------------------------------
# 6. Prediction for an upcoming event
# ---------------------------------------------------------------------------

def plackett_luce_simulate(rider_ids, ratings, n_sims=20000, scale=400.0):
    """Monte Carlo full-order simulation: strength = 10^(rating/scale),
    sample without replacement proportional to remaining strength each
    'position'. Returns win / podium / top10 probabilities per rider."""
    strengths = np.array([10 ** (ratings.get(r, 1500.0) / scale) for r in rider_ids])
    n = len(rider_ids)
    wins = np.zeros(n)
    podium = np.zeros(n)
    top10 = np.zeros(n)
    idx_all = np.arange(n)
    for _ in range(n_sims):
        remaining = idx_all.copy()
        remaining_strength = strengths.copy()
        order = []
        for _pos in range(min(n, 10)):
            p = remaining_strength / remaining_strength.sum()
            choice = RNG.choice(len(remaining), p=p)
            order.append(remaining[choice])
            remaining = np.delete(remaining, choice)
            remaining_strength = np.delete(remaining_strength, choice)
        wins[order[0]] += 1
        for k in order[:3]:
            podium[k] += 1
        for k in order[:10]:
            top10[k] += 1
    return pd.DataFrame(dict(
        rider_id=rider_ids,
        win_prob=wins / n_sims,
        podium_prob=podium / n_sims,
        top10_prob=top10 / n_sims,
    ))


def predict_event(start_list, elo_ratings, form_lookup, venue_lookup, model, model_cols):
    df = start_list.copy()
    df["elo_rating"] = df["rider_id"].map(elo_ratings).fillna(1500.0)
    df["form_ewma"] = df["rider_id"].map(form_lookup).fillna(df["form_ewma"] if "form_ewma" in df else 0.0)
    df["venue_prior"] = df["rider_id"].map(venue_lookup).fillna(0.0)
    df["round"] = df.get("round", pd.Series(["final"] * len(df)))
    df["start_order_norm"] = (
        (df["start_order"] - df["start_order"].min())
        / max(df["start_order"].max() - df["start_order"].min(), 1)
        if "start_order" in df else 0.5
    )
    for c in CATEGORICAL_COLS:
        if c not in df:
            df[c] = "unknown"
        df[c] = df[c].fillna("unknown").astype(str)
    dummies = pd.get_dummies(df[CATEGORICAL_COLS], prefix=CATEGORICAL_COLS)
    X = pd.concat([df[["elo_rating", "form_ewma", "venue_prior", "start_order_norm"]], dummies], axis=1)
    X = X.reindex(columns=model_cols, fill_value=0)
    df["pred_pct_back"] = model.predict(X)

    lp = plackett_luce_simulate(df["rider_id"].tolist(), elo_ratings)
    out = df.merge(lp, on="rider_id")
    return out.sort_values("pred_pct_back")


# ---------------------------------------------------------------------------
# 7. Season simulation: full race weekend (Q1 -> Q2 -> Final) Monte Carlo
#    + championship points / standings
# ---------------------------------------------------------------------------
#
# Per-run model, on log finish time y of rider i in run r (one run = one
# event+round):   y = run_effect[r] + mu[i] + u[i, event] + eps
#   mu      rider pace (recency-weighted, shrunk toward the field median)
#   u       rider x track effect, shared by all of a rider's runs that weekend
#   eps     run-to-run noise
# plus a per-rider "incident" rate (DNF/DSQ, or a finished run more than
# INCIDENT_THRESHOLD slower than expected); incident runs are simulated as a
# DNF or as a time loss resampled from the observed incident losses.
# Weekend format observed in every 2026 round: Q1 top 20 go to the final,
# everyone else rides Q2, Q2 top 10 fill the final (30 riders).

# PLACEHOLDER POINTS: approximate UCI DHI World Cup scales, NOT the official
# tables. Replace with the real values; everything downstream reads these.
FINAL_POINTS = [250, 210, 180, 160, 140, 125, 110, 95, 80, 75,
                70, 65, 60, 55, 50, 45, 40, 35, 30, 25,
                20, 19, 18, 17, 16, 15, 14, 13, 12, 11]
QUAL_POINTS = [60, 50, 40, 35, 30, 25, 20, 18, 16, 14,
               12, 10, 9, 8, 7, 6, 5, 4, 3, 2]
QUAL_POINTS_ROUND = "qual1"   # the qualifying round QUAL_POINTS are paid on

Q1_TO_FINAL = 20
Q2_TO_FINAL = 10
RACE_ROUNDS = ("qual1", "qual2", "final")
RUN_WEIGHTS = {"practice": 0.5, "qual1": 1.0, "qual2": 1.0, "final": 1.0}
INCIDENT_THRESHOLD = 0.04     # finished >4% slower than expected = incident


def points_for(pos, table):
    """Vectorized f(rank) -> points; NaN/inf/out-of-table ranks score 0."""
    pos = np.asarray(pos, dtype=float)
    out = np.zeros(pos.shape)
    ok = np.isfinite(pos) & (pos >= 1) & (pos <= len(table))
    out[ok] = np.asarray(table, dtype=float)[pos[ok].astype(int) - 1]
    return out


def event_order(raw):
    return raw.groupby("event_id")["event_date"].min().sort_values().index.tolist()


def actual_event_points(raw):
    """Championship points actually scored, one row per rider per event."""
    fin = raw[(raw["sector_id"] == "FINISH") & (raw["status"] == "OK")]
    q = fin[fin["round"] == QUAL_POINTS_ROUND].set_index(["event_id", "rider_id"])["rank_at_split"]
    f = fin[fin["round"] == "final"].set_index(["event_id", "rider_id"])["rank_at_split"]
    idx = q.index.union(f.index)
    out = pd.DataFrame(index=idx)
    out["qual_rank"] = q.reindex(idx)
    out["final_rank"] = f.reindex(idx)
    out["qual_pts"] = points_for(out["qual_rank"], QUAL_POINTS)
    out["final_pts"] = points_for(out["final_rank"], FINAL_POINTS)
    out["points"] = out["qual_pts"] + out["final_pts"]
    return out.reset_index()


def event_starters(raw, event_id):
    """Riders who actually took the start of Q1 at an event (not DNS)."""
    q1 = raw[(raw["event_id"] == event_id) & (raw["round"] == "qual1") & (raw["sector_id"] == "FINISH")]
    return q1.loc[q1["status"] != "DNS", "rider_id"].unique().tolist()


def fit_season_model(raw, half_life_events=4.0, prior_n=1.5, incident_prior_n=8.0, n_iter=30):
    fin = raw[(raw["sector_id"] == "FINISH") & raw["round"].isin(RUN_WEIGHTS)].copy()
    ev_idx = {e: i for i, e in enumerate(event_order(fin))}
    fin["ev_i"] = fin["event_id"].map(ev_idx)
    fin["run"] = fin["event_id"] + "|" + fin["round"]
    fin["w"] = fin["round"].map(RUN_WEIGHTS) * 0.5 ** ((fin["ev_i"].max() - fin["ev_i"]) / half_life_events)

    ok = fin[(fin["status"] == "OK") & (fin["cum_time_s"] > 0)].copy()
    ok["y"] = np.log(ok["cum_time_s"])
    riders = ok["rider_id"].unique()
    mu = pd.Series(0.0, index=riders)
    clean = pd.Series(True, index=ok.index)
    for _ in range(n_iter):
        c = ok[clean]
        run_eff = (c["y"] - c["rider_id"].map(mu)).groupby(c["run"]).median()
        ok["resid"] = ok["y"] - ok["run"].map(run_eff)
        c = ok[clean]
        num = (c["resid"] * c["w"]).groupby(c["rider_id"]).sum()
        den = c["w"].groupby(c["rider_id"]).sum()
        mu = (num / (den + prior_n)).reindex(riders).fillna(0.0)  # shrink toward 0 = field median
        mu -= mu.median()
        clean = (ok["resid"] - ok["rider_id"].map(mu)) < INCIDENT_THRESHOLD
    ok["e"] = ok["resid"] - ok["rider_id"].map(mu)

    # noise: split clean race-run residuals into within-weekend (sigma) and
    # rider x weekend (tau) components
    race = ok[clean & ok["round"].isin(RACE_ROUNDS)]
    g = race.groupby(["rider_id", "event_id"])["e"]
    n_ie, mean_ie = g.transform("count"), g.transform("mean")
    dof = len(race) - g.ngroups
    sigma2 = ((race["e"] - mean_ie) ** 2).sum() / max(dof, 1)
    grp = race.groupby(["rider_id", "event_id"])["e"].agg(["mean", "count"])
    tau2 = max(grp["mean"].var() - (sigma2 / grp["count"]).mean(), 1e-6)

    # incidents over started race runs
    started = fin[fin["round"].isin(RACE_ROUNDS) & fin["status"].isin(["OK", "DNF", "DSQ"])].copy()
    started["e"] = ok["e"].reindex(started.index)
    started["incident"] = started["status"].isin(["DNF", "DSQ"]) | (started["e"] >= INCIDENT_THRESHOLD)
    p0 = started["incident"].mean()
    inc = started.groupby("rider_id")["incident"].agg(["sum", "count"])
    p_inc = (inc["sum"] + incident_prior_n * p0) / (inc["count"] + incident_prior_n)
    incidents = started[started["incident"]]
    dnf_share = incidents["status"].isin(["DNF", "DSQ"]).mean()
    excess = incidents.loc[incidents["status"] == "OK", "e"].to_numpy()

    names = raw.drop_duplicates("rider_id", keep="last").set_index("rider_id")["rider_name"]
    return dict(mu=mu, mu_new=float(mu.quantile(0.75)), sigma=float(np.sqrt(sigma2)),
                tau=float(np.sqrt(tau2)), p_inc=p_inc, p0=float(p0),
                dnf_share=float(dnf_share), excess=excess if len(excess) else np.array([0.05]),
                names=names)


def _ranks(t):
    """Per-sim 1-based ranks along axis 1; non-finite times -> inf (no rank)."""
    n_sims, n = t.shape
    order = np.argsort(t, axis=1)
    r = np.empty((n_sims, n))
    np.put_along_axis(r, order, np.broadcast_to(np.arange(1, n + 1, dtype=float), (n_sims, n)), axis=1)
    return np.where(np.isfinite(t), r, np.inf)


def simulate_weekend(model, riders, n_sims=10000, attend_prob=None, rng=RNG):
    """Simulate Q1 -> Q2 -> Final for `riders`. Returns dict of (n_sims, n)
    arrays: q1_rank, q2_rank, final_rank (inf = didn't run/finish), points."""
    n = len(riders)
    mu = model["mu"].reindex(riders).fillna(model["mu_new"]).to_numpy()
    p_inc = model["p_inc"].reindex(riders).fillna(model["p0"]).to_numpy()
    if attend_prob is None:
        starts = np.ones((n_sims, n), bool)
    else:
        starts = rng.random((n_sims, n)) < np.asarray(attend_prob)
    u = rng.normal(0.0, model["tau"], (n_sims, n))

    def run(mask):
        t = mu + u + rng.normal(0.0, model["sigma"], (n_sims, n))
        inc = rng.random((n_sims, n)) < p_inc
        dnf = inc & (rng.random((n_sims, n)) < model["dnf_share"])
        t = t + np.where(inc & ~dnf, rng.choice(model["excess"], (n_sims, n)), 0.0)
        t[dnf | ~mask] = np.inf
        return t

    q1 = _ranks(run(starts))
    to_final = q1 <= Q1_TO_FINAL
    q2 = _ranks(run(starts & ~to_final))
    to_final |= q2 <= Q2_TO_FINAL
    final = _ranks(run(to_final))
    qual = q1 if QUAL_POINTS_ROUND == "qual1" else q2
    points = points_for(qual, QUAL_POINTS) + points_for(final, FINAL_POINTS)
    return dict(q1_rank=q1, q2_rank=q2, final_rank=final, made_final=to_final, points=points)


def summarize_weekend(model, riders, sim):
    fr = sim["final_rank"]
    return pd.DataFrame(dict(
        rider_id=riders,
        rider_name=[model["names"].get(r, r) for r in riders],
        win_prob=(fr == 1).mean(0),
        podium_prob=(fr <= 3).mean(0),
        top10_prob=(fr <= 10).mean(0),
        make_final_prob=sim["made_final"].mean(0),
        exp_points=sim["points"].mean(0),
    )).sort_values("exp_points", ascending=False).reset_index(drop=True)


def simulate_standings(model, current_points, weekends, n_sims=10000, rng=RNG):
    """current_points: Series rider_id -> points so far. weekends: list of
    (riders, attend_prob_or_None). Returns (standings_df, per-weekend sims)."""
    all_riders = list(dict.fromkeys(list(current_points.index) + [r for w, _ in weekends for r in w]))
    col = {r: j for j, r in enumerate(all_riders)}
    total = np.tile(current_points.reindex(all_riders).fillna(0.0).to_numpy(), (n_sims, 1))
    sims = []
    for riders, attend in weekends:
        sim = simulate_weekend(model, riders, n_sims=n_sims, attend_prob=attend, rng=rng)
        total[:, [col[r] for r in riders]] += sim["points"]
        sims.append(sim)
    jitter = rng.random(total.shape) * 1e-3   # random tie-break
    rank = _ranks(-(total + jitter))
    df = pd.DataFrame(dict(
        rider_id=all_riders,
        rider_name=[model["names"].get(r, r) for r in all_riders],
        current_points=current_points.reindex(all_riders).fillna(0.0).to_numpy(),
        exp_points=total.mean(0),
        points_p10=np.percentile(total, 10, axis=0),
        points_p90=np.percentile(total, 90, axis=0),
        champion_prob=(rank == 1).mean(0),
        top3_prob=(rank <= 3).mean(0),
        top10_prob=(rank <= 10).mean(0),
        exp_rank=rank.mean(0),
    )).sort_values("exp_points", ascending=False).reset_index(drop=True)
    return df, sims


def _spearman(a, b):
    return pd.Series(a).rank().corr(pd.Series(b).rank())


def _brier(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def backtest_season(raw, n_holdout=2, n_sims=10000, rng=RNG):
    """Fit on all but the last n_holdout events, simulate those events with
    their actual start lists, and score against what actually happened."""
    events = event_order(raw)
    train_ev, test_ev = events[:-n_holdout], events[-n_holdout:]
    model = fit_season_model(raw[raw["event_id"].isin(train_ev)])
    pts = actual_event_points(raw)
    before = pts[pts["event_id"].isin(train_ev)].groupby("rider_id")["points"].sum()
    fields = [event_starters(raw, e) for e in test_ev]
    standings, sims = simulate_standings(model, before, [(f, None) for f in fields], n_sims=n_sims, rng=rng)

    event_reports = []
    for e, field, sim in zip(test_ev, fields, sims):
        summ = summarize_weekend(model, field, sim)
        act = pts[pts["event_id"] == e].set_index("rider_id")
        summ["actual_final_rank"] = summ["rider_id"].map(act["final_rank"])
        summ["actual_points"] = summ["rider_id"].map(act["points"]).fillna(0.0)
        fr = summ["actual_final_rank"]
        made = summ["rider_id"].isin(raw.loc[(raw["event_id"] == e) & (raw["round"] == "final"), "rider_id"])
        metrics = dict(
            event_id=e,
            venue=raw.loc[raw["event_id"] == e, "venue"].iloc[0] if "venue" in raw else e,
            spearman_points=_spearman(summ["exp_points"], summ["actual_points"]),
            brier_win=_brier(summ["win_prob"], fr == 1),
            brier_win_base=_brier(np.full(len(summ), 1 / len(summ)), fr == 1),
            brier_podium=_brier(summ["podium_prob"], fr <= 3),
            brier_podium_base=_brier(np.full(len(summ), 3 / len(summ)), fr <= 3),
            brier_final=_brier(summ["make_final_prob"], made),
            brier_final_base=_brier(np.full(len(summ), 30 / len(summ)), made),
            top10_hits=len(set(summ.nlargest(10, "top10_prob")["rider_id"])
                           & set(summ.loc[fr <= 10, "rider_id"])),
            winner=summ.loc[fr == 1, "rider_name"].squeeze() if (fr == 1).any() else None,
            winner_pred_win_prob=float(summ.loc[fr == 1, "win_prob"].sum()),
        )
        event_reports.append((metrics, summ))

    actual_total = pts[pts["event_id"].isin(events)].groupby("rider_id")["points"].sum()
    standings["actual_points"] = standings["rider_id"].map(actual_total).fillna(0.0)
    standings["actual_rank"] = standings["actual_points"].rank(ascending=False, method="min")
    return model, event_reports, standings, (train_ev, test_ev)


def forecast_season(raw, n_remaining=2, n_sims=10000, attend_window=3, rng=RNG):
    """Fit on every event, then simulate the n_remaining unraced rounds.
    Field = riders who started Q1 in any of the last attend_window events,
    each attending with probability (starts in that window / window)."""
    events = event_order(raw)
    model = fit_season_model(raw)
    pts = actual_event_points(raw)
    current = pts.groupby("rider_id")["points"].sum()
    recent = events[-attend_window:]
    starts = pd.Series([r for e in recent for r in event_starters(raw, e)]).value_counts()
    field = starts.index.tolist()
    attend = (starts / len(recent)).to_numpy()
    standings, sims = simulate_standings(model, current, [(field, attend)] * n_remaining,
                                         n_sims=n_sims, rng=rng)
    per_round = summarize_weekend(model, field, sims[0])
    per_round["attend_prob"] = per_round["rider_id"].map(starts / len(recent))
    standings["current_rank"] = standings["current_points"].rank(ascending=False, method="min")
    return model, per_round, standings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_fit(args):
    raw = pd.read_csv(args.data)
    finish = raw[(raw["sector_id"] == "FINISH") & (raw["status"] == "OK")].copy()
    if finish.empty:
        raise SystemExit("No FINISH/OK rows found — check parser output / status values.")
    finish = add_relative_metrics(finish)
    elo_ratings, elo_history = fit_elo_ratings(finish)
    feat = add_form_features(finish)
    model, model_cols = fit_time_model(feat, elo_ratings)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump(model, out_dir / "time_model.joblib")
    (out_dir / "model_cols.json").write_text(json.dumps(model_cols))
    pd.Series(elo_ratings).rename("rating").to_csv(out_dir / "elo_ratings.csv")
    elo_history.to_csv(out_dir / "elo_history.csv", index=False)
    latest_form = feat.sort_values("event_date").groupby("rider_id").tail(1)
    latest_form[["rider_id", "form_ewma"]].to_csv(out_dir / "latest_form.csv", index=False)
    venue_prior = feat.groupby("rider_id")["venue_prior"].last()
    venue_prior.to_csv(out_dir / "venue_prior.csv")

    print(f"Fitted on {finish['event_id'].nunique()} event/round groups, "
          f"{finish['rider_id'].nunique()} riders. Artifacts -> {out_dir}/")

    if args.validate:
        print("Running walk-forward validation (this re-fits repeatedly, may take a while)...")
        val = walk_forward_validate(finish)
        val.to_csv(out_dir / "walk_forward_validation.csv", index=False)
        if not val.empty:
            print(f"Walk-forward MAE (pct_back): {val['mae_pct_back'].mean():.4f} "
                  f"over {len(val)} held-out rounds.")
        else:
            print("Not enough history yet for walk-forward validation "
                  "(need more events than --min-train-events).")


def cmd_predict(args):
    import joblib
    model_dir = Path(args.model_dir)
    model = joblib.load(model_dir / "time_model.joblib")
    model_cols = json.loads((model_dir / "model_cols.json").read_text())
    elo_ratings = pd.read_csv(model_dir / "elo_ratings.csv", index_col=0)["rating"].to_dict()
    form_lookup = pd.read_csv(model_dir / "latest_form.csv").set_index("rider_id")["form_ewma"].to_dict()
    venue_lookup = pd.read_csv(model_dir / "venue_prior.csv", index_col=0)["venue_prior"].to_dict()

    start_list = pd.read_csv(args.start_list)
    if "rider_id" not in start_list.columns and "rider_name" in start_list.columns:
        from parser import normalize_rider_id
        start_list["rider_id"] = start_list["rider_name"].apply(lambda n: normalize_rider_id(n))

    preds = predict_event(start_list, elo_ratings, form_lookup, venue_lookup, model, model_cols)
    preds.to_csv(args.out, index=False)
    print(preds[["rider_id", "pred_pct_back", "win_prob", "podium_prob", "top10_prob"]]
          .to_string(index=False))
    print(f"\nFull output -> {args.out}")


def cmd_season(args):
    raw = pd.read_csv(args.data)
    raw = raw[raw["discipline"].eq("DHI") & raw["round"].isin(RUN_WEIGHTS)] if "discipline" in raw else raw
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    top = args.top
    pd.set_option("display.width", 200)
    fmt = {c: "{:.1%}".format for c in ("win_prob", "podium_prob", "top10_prob", "make_final_prob",
                                         "champion_prob", "top3_prob", "attend_prob")}
    print("NOTE: FINAL_POINTS / QUAL_POINTS are placeholders, not the official UCI tables.\n")

    if args.backtest:
        model, reports, standings, (train_ev, test_ev) = backtest_season(
            raw, n_holdout=args.backtest, n_sims=args.sims, rng=rng)
        print(f"=== BACKTEST: fit on {len(train_ev)} events, predict {', '.join(test_ev)} ===")
        print(f"model: sigma={model['sigma']:.4f} tau={model['tau']:.4f} (log-time), "
              f"incident rate={model['p0']:.1%}, incidents that are DNF/DSQ={model['dnf_share']:.0%}\n")
        for metrics, summ in reports:
            print(f"--- {metrics['venue']} ({metrics['event_id']}) ---")
            print(f"  Spearman(exp points, actual points) = {metrics['spearman_points']:.3f}")
            for k in ("win", "podium", "final"):
                print(f"  Brier {k:<7} model {metrics[f'brier_{k}']:.4f}  vs uniform {metrics[f'brier_{k}_base']:.4f}")
            print(f"  top-10 hits: {metrics['top10_hits']}/10   winner {metrics['winner']} "
                  f"had win prob {metrics['winner_pred_win_prob']:.1%}")
            cols = ["rider_name", "win_prob", "podium_prob", "top10_prob", "make_final_prob",
                    "exp_points", "actual_final_rank", "actual_points"]
            print(summ[cols].head(top).to_string(index=False, formatters=fmt, float_format="{:.1f}".format))
            summ.to_csv(out_dir / f"backtest_{metrics['venue']}.csv", index=False)
            print()
        standings.to_csv(out_dir / "backtest_standings.csv", index=False)
        print(f"--- Standings after {test_ev[-1]}: predicted vs actual ---")
        s = standings[standings["actual_points"] > 0]
        print(f"  Spearman(exp points, actual points) = {_spearman(s['exp_points'], s['actual_points']):.3f}")
        cols = ["rider_name", "current_points", "exp_points", "champion_prob", "top3_prob",
                "actual_points", "actual_rank"]
        print(standings[cols].head(top).to_string(index=False, formatters=fmt, float_format="{:.0f}".format))
        print()

    if args.remaining:
        model, per_round, standings = forecast_season(
            raw, n_remaining=args.remaining, n_sims=args.sims, rng=rng)
        print(f"=== FORECAST: {args.remaining} remaining round(s), fit on all {len(event_order(raw))} events ===")
        print("--- Per remaining round (venue unknown -> same distribution for each) ---")
        cols = ["rider_name", "attend_prob", "win_prob", "podium_prob", "top10_prob",
                "make_final_prob", "exp_points"]
        print(per_round[cols].head(top).to_string(index=False, formatters=fmt, float_format="{:.1f}".format))
        per_round.to_csv(out_dir / "forecast_per_round.csv", index=False)
        print("\n--- Projected final championship standings ---")
        cols = ["rider_name", "current_rank", "current_points", "exp_points", "points_p10",
                "points_p90", "champion_prob", "top3_prob", "exp_rank"]
        print(standings[cols].head(top).to_string(index=False, formatters=fmt, float_format="{:.0f}".format))
        standings.to_csv(out_dir / "forecast_standings.csv", index=False)
    print(f"\nCSVs -> {out_dir}/")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    fit_p = sub.add_parser("fit", help="Fit ratings + time model from tidy splits CSV.")
    fit_p.add_argument("--data", required=True, help="Tidy CSV from parser.py")
    fit_p.add_argument("--out-dir", required=True)
    fit_p.add_argument("--validate", action="store_true", help="Also run walk-forward validation.")
    fit_p.set_defaults(func=cmd_fit)

    pred_p = sub.add_parser("predict", help="Predict an upcoming event from a start list.")
    pred_p.add_argument("--model-dir", required=True)
    pred_p.add_argument("--start-list", required=True,
                         help="CSV with rider_id or rider_name, start_order, track_condition, round")
    pred_p.add_argument("--out", default="predictions.csv")
    pred_p.set_defaults(func=cmd_predict)

    season_p = sub.add_parser("season", help="Backtest held-out rounds and forecast remaining "
                                             "rounds + championship standings.")
    season_p.add_argument("--data", required=True, help="Tidy CSV from parser.py (data/*.md)")
    season_p.add_argument("--out-dir", default="season_out")
    season_p.add_argument("--backtest", type=int, default=2,
                          help="Hold out and predict the last N raced events (0 = skip).")
    season_p.add_argument("--remaining", type=int, default=2,
                          help="Number of unraced rounds left in the season (0 = skip).")
    season_p.add_argument("--sims", type=int, default=10000)
    season_p.add_argument("--seed", type=int, default=42)
    season_p.add_argument("--top", type=int, default=15, help="Rows to print per table.")
    season_p.set_defaults(func=cmd_season)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
