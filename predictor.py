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

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
