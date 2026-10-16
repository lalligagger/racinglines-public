"""
Rebuild sports/f1/calibration.toml (C48, racinglines/models/calibration.py) from the as-of stage prices stored in the
database: for every Grand Prix with a result, the latest diagnostic run per stage priced with the given variant and
without a calibration power, joined to the race winner. Read-only on the database; writes the TOML (or --out).

    python scripts/models/fit_calibration.py --variant gridq+pretrain+reset [--sims 16000] [--out FILE] [--check]
    python scripts/models/fit_calibration.py --csv rows.csv [--check]      # the same rows exported from another database

--check: also rerun the fit with every result from each race onwards scrambled and fail if any earlier row changes
(the leakage check, run on the real data; tests/test_calibration.py runs it on synthetic data).
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from racinglines.db.config import get_engine  # noqa: E402
from racinglines.models import calibration as CAL  # noqa: E402

GRID_STAGES = ("after Quali",)            # the race's starting grid is known; every other stage is "nogrid"
STAGES = ("pre-weekend", "after FP1", "after FP2", "after FP3", "after SQ", "after Sprint", "after Quali")

SQL = """
with runs as (
    select distinct on (params->>'event_key', params->>'sweep_stage') id, params->>'event_key' event_key,
           params->>'sweep_stage' stage
    from model_runs
    where kind = 'diagnostic' and params->>'variant' = :variant and params->>'sweep_stage' = any(:stages)
      and coalesce(params->'model_settings'->>'calib_power', '') = ''
      and (cast(:sims as int) is null or (params->'model_settings'->>'sims')::int = cast(:sims as int))
    order by params->>'event_key', params->>'sweep_stage', created_at desc)
select r.event_key, e.start_date race_date, r.stage, r.id run, p.athlete_id, p.win_prob p,
       coalesce((f.position = 1)::int, 0) won
from runs r
join race_predictions p on p.model_run_id = r.id
join races ra on ra.id = p.race_id
join events e on e.id = ra.event_id
left join (select ro.race_id, re.athlete_id, re.position from results re join rounds ro on ro.id = re.round_id
           where ro.kind = 'race') f on f.race_id = p.race_id and f.athlete_id = p.athlete_id
"""


def load(variant, sims=None, db=None):
    with get_engine(db).connect() as c:
        df = pd.read_sql(text(SQL), c, params=dict(variant=variant, stages=list(STAGES), sims=sims))
    df["group"] = df["stage"].map(lambda s: "grid" if s in GRID_STAGES else "nogrid")
    return df


def leak_check(df):
    """Scramble every result from race k on (winner moved to another driver) and refit: rows 0..k must not change."""
    base = CAL.fit_walk_forward(df)
    order = df.drop_duplicates("event_key").sort_values(["race_date", "event_key"])["event_key"].tolist()
    for k in range(CAL.MIN_RACES, len(order)):
        later = set(order[k:])
        d = df.copy()
        m = d["event_key"].isin(later)
        d.loc[m, "won"] = d.loc[m].groupby("run")["won"].transform(lambda w: w.shift(1, fill_value=w.iloc[-1]))
        refit = CAL.fit_walk_forward(d)
        n = k - CAL.MIN_RACES + 1            # rows fitted only on races before order[k]
        if [(f["from"], f["grid"], f["nogrid"]) for f in refit[:n]] != [(f["from"], f["grid"], f["nogrid"]) for f in base[:n]]:
            raise SystemExit(f"LEAK: scrambling races from {order[k]} on changed an earlier fit")
    print(f"leak check: {len(order) - CAL.MIN_RACES} cut points, no earlier fit changed")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", default="gridq+pretrain+reset")
    ap.add_argument("--sims", type=int, default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--csv", default=None, help="read the rows (columns of SQL above) from this file, not the database")
    ap.add_argument("--out", default=str(ROOT / "sports" / "f1" / "calibration.toml"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.csv:
        df = pd.read_csv(a.csv, parse_dates=["race_date"])
        df["group"] = df["stage"].map(lambda s: "grid" if s in GRID_STAGES else "nogrid")
    else:
        df = load(a.variant, a.sims, a.db)
    print(f"{df['event_key'].nunique()} races, {df['run'].nunique()} priced stages "
          f"({df['event_key'].min()} to {df['event_key'].max()})")
    if a.check:
        leak_check(df)
    fits = CAL.fit_walk_forward(df)
    old = "\n" + Path(a.out).read_text() if Path(a.out).exists() else ""
    header = old.split("\n[[fit]]\n")[0].lstrip("\n")       # the comment block above the first fit
    Path(a.out).write_text(CAL.to_toml(fits, header))
    print(f"wrote {len(fits)} fits -> {a.out}; latest: grid {fits[-1]['grid']}, nogrid {fits[-1]['nogrid']}")


if __name__ == "__main__":
    main()
