"""
Prediction records on disk (docs/backtest-core.md, "Prediction records"; docs/engine-roadmap.md phase E4a):
the long-format rows of a saved model run, beside `race_predictions`, and the archive of its simulations.

    data/runs/records/<model_run_id>/predictions.parquet    one row per event x stage x kind x subject
    data/runs/records/<model_run_id>/sims.npz               the OutcomeSims (backtests and forecasts only)

Written only when RACINGLINES_PREDICTION_RECORDS is set (default off: nothing is written and every existing
output is unchanged). RACINGLINES_RECORDS_DIR moves the root (tests use a temporary folder). A run that
simulated several events keeps one archive per event, `sims-<key>.npz`, keyed as given to `write`.

One subject key for every writer (2026-10-14, docs/todo.md "Prediction records, cross-engine pairing"): `subject` is
the athlete id as the text of a plain integer ("12") and a head-to-head's `params["opponent_id"]` the integer itself,
whatever shape the model's entrants carry (the results core and rank_logit: 12; the run-times core: "ath:12", the
rider_id of db/queries.py). `athlete_key` is that convention; `to_records` (models/outcomes.py) writes with it and
`read` applies it to records written before it, so `eval compare` pairs runs of different engines.
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

SWITCH = "RACINGLINES_PREDICTION_RECORDS"
ROOT_ENV = "RACINGLINES_RECORDS_DIR"
ATHLETE_PREFIX = "ath:"          # the run-times core's rider_id (db/queries.py): "ath:<athlete id>"


def athlete_key(x):
    """The one key of an athlete in prediction records: "ath:12", "12", 12, np.int64(12) and 12.0 are all 12. A key
    that is not an athlete id (a team's group key, a name) is returned as it is, less the prefix."""
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, str):
        if x.startswith(ATHLETE_PREFIX):
            x = x[len(ATHLETE_PREFIX):]
        return int(x) if x.strip().lstrip("-").isdigit() else x
    if isinstance(x, float) and np.isfinite(x) and x == int(x):
        return int(x)
    return x


def subject_key(x):
    """`subject` as written: athlete_key as text."""
    return str(athlete_key(x))


def _normalized_params(p):
    if not isinstance(p, str) or ATHLETE_PREFIX not in p:
        return p
    d = json.loads(p)
    if "opponent_id" in d:
        d["opponent_id"] = athlete_key(d["opponent_id"])
    return json.dumps(d, sort_keys=True)


def normalize(df):
    """Records in the one subject key: rows written under the run-times core's old key ("ath:12" as subject or
    opponent) are rewritten; a frame already in the convention comes back unchanged, the same object."""
    if df is None or not len(df) or "subject" not in df:
        return df
    subj = df["subject"].astype(str)
    old = subj.str.startswith(ATHLETE_PREFIX)
    if "params" in df:
        old = old | df["params"].astype(str).str.contains('"' + ATHLETE_PREFIX, regex=False)
    if not old.any():
        return df
    df = df.copy()
    df.loc[old, "subject"] = subj[old].map(subject_key)
    if "params" in df:
        df.loc[old, "params"] = df.loc[old, "params"].map(_normalized_params)
    return df


def enabled():
    return os.environ.get(SWITCH, "").strip().lower() in ("1", "true", "yes", "on")


def records_dir():
    if os.environ.get(ROOT_ENV):
        return Path(os.environ[ROOT_ENV])
    from racinglines import paths
    return paths.runs("records", mkdir=False)


def _sims_name(key=None):
    return "sims.npz" if key is None else f"sims-{key}.npz"


def write(run_id, df, sims=None):
    """Write a run's records; `sims` is an OutcomeSims (sims.npz), or {key: OutcomeSims} (sims-<key>.npz each).
    Returns the run's folder."""
    from racinglines.models import outcomes as O
    d = records_dir() / str(int(run_id))
    d.mkdir(parents=True, exist_ok=True)
    df.to_parquet(d / "predictions.parquet", index=False)
    if sims is not None:
        for key, s in ({None: sims} if isinstance(sims, O.OutcomeSims) else dict(sims)).items():
            O.save_sims(s, d / _sims_name(key))
    return d


def read(run_id):
    """A run's records, in the one subject key (records written before it are normalized on the way in)."""
    return normalize(pd.read_parquet(records_dir() / str(int(run_id)) / "predictions.parquet"))


def load_sims(run_id, key=None):
    from racinglines.models import outcomes as O
    return O.load_sims(records_dir() / str(int(run_id)) / _sims_name(key))


def concat(frames):
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else None
