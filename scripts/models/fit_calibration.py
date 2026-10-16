"""
Rebuild sports/f1/calibration.toml (C48, racinglines/models/calibration.py) from the as-of stage prices stored in the
database: for every Grand Prix with a result, the latest diagnostic run per stage priced with the given variant and
without a calibration power, joined to the race winner. Read-only on the database; writes the TOML (or --out).

    python scripts/models/fit_calibration.py --variant gridq+pretrain+reset [--sims 16000] [--out FILE] [--check]
    python scripts/models/fit_calibration.py --csv rows.csv [--check]      # the same rows exported from another database
    python scripts/models/fit_calibration.py --sport nascar --seasons 2023 2024 2025 2026 [--sims 4000] [--check]

--report DIR (with --sport): also score the race-win prices before and after the fitted table, per race and season,
and beside each venue's price at the same cutoff (Polymarket, Kalshi: model_vs_market's exact links), written as
DIR/report.md, DIR/races.csv and DIR/vs_<venue>.csv. The calibrated price is p^a renormalised with the row in force
at the race's cutoff (what the resample converges to). Read-only.

--sport (any sport whose pricing model is the results level, e.g. nascar, motogp): the as-of win prices come from the
walk-forward (racinglines/core/walk_forward.py) run here with calib_power unset, one price per race at its cutoff,
and the table goes to sports/<sport>/calibration.toml. Such a model never knows the grid, so `grid` and `nogrid` are
fitted on the same prices and are equal.

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


def _every_tenth(m):
    """The walk-forward's progress, one line per 10 races (and the last)."""
    i, _, n = m.split()[1].partition("/") if m.startswith("progress") else ("", "", "")
    if i.isdigit() and n.isdigit() and (int(i) % 10 == 0 or i == n):
        print(m, flush=True)


def load_walk_forward(sport, seasons=None, sims=None, db=None, keep=None, data=None):
    """The fit's rows from the sport's walk-forward, priced in memory with calib_power unset: one run per race and
    group (both groups hold the same prices: the results level has no grid stage). keep: a dict that gets the
    walk-forward's output ("out") for the report."""
    from racinglines.core import walk_forward as WF
    from racinglines.models import race_model as RM
    model = RM.get(sport)
    st = model.Settings.from_dict({"sims": sims} if sims else {})
    if st.get("calib_power"):
        raise SystemExit(f"{sport}: the fit needs calib_power unset (sports/{sport}.toml [model.defaults] sets it)")
    out = WF.run(model, model.load(db) if data is None else model.load(data=data), st, seasons=seasons, kinds=["race_win"],
                 echo=_every_tenth)
    if keep is not None:
        keep["out"] = out
    r = out["rows"].dropna(subset=["y"])
    day = {e: pd.Timestamp(t).normalize().tz_localize(None) if pd.Timestamp(t).tzinfo else pd.Timestamp(t).normalize()
           for e, t in out["cutoffs"].items()}
    base = pd.DataFrame(dict(event_key=r["event_id"].astype(str), race_date=r["event_id"].map(day),
                             athlete_id=r["athlete_id"], p=r["fair"].astype(float), won=r["y"].astype(int)))
    return pd.concat([base.assign(group=g, run=base["event_key"] + "|" + g, stage=g) for g in ("grid", "nogrid")],
                     ignore_index=True)


def _binary_ll(p, y, eps=1e-4):
    import numpy as np
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def report(sport, df, fits, out, folder, db=None, venues=("polymarket", "kalshi")):
    """Race-win log loss before and after the walk-forward table, and beside each venue's price (module docstring)."""
    import numpy as np
    from racinglines.pipelines import model_vs_market as MVM
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    base = df[df["group"] == "nogrid"].copy()
    rows = sorted(fits, key=lambda f: f["from"])

    def power_at(day):
        a = 1.0
        for f in rows:
            if pd.Timestamp(f["from"]) <= pd.Timestamp(day):
                a = float(f["nogrid"])
        return a

    parts = []
    for ev, g in base.groupby("event_key", sort=False):
        a = power_at(g["race_date"].iloc[0])
        parts.append(g.assign(a=a, q=CAL.win_power(g["p"].to_numpy(), a)))
    cal = pd.concat(parts, ignore_index=True)
    cal["season"] = pd.to_datetime(cal["race_date"]).dt.year
    races = (cal.groupby(["event_key", "race_date", "season", "a"])
             .apply(lambda g: pd.Series(dict(nll_raw=-np.log(max(g.loc[g["won"] == 1, "p"].sum(), 1e-4)),
                                             nll_cal=-np.log(max(g.loc[g["won"] == 1, "q"].sum(), 1e-4)),
                                             fav_raw=g["p"].max(), fav_cal=g["q"].max())), include_groups=False)
             .reset_index().sort_values("race_date"))
    races.to_csv(folder / "races.csv", index=False)
    scored = races[races["a"] > 1.0]
    lines = [f"# {sport} race-win calibration (walk-forward, C48)", "",
             f"{races['event_key'].nunique()} races priced; {len(scored)} with a fitted power (from race "
             f"{CAL.MIN_RACES + 1} on). Latest power {rows[-1]['nogrid'] if rows else 1.0}.", "",
             "## Winner log loss (mean over races, lower is better)", "",
             "| season | races | raw | calibrated | change | top price raw | top price calibrated |", "|---|---|---|---|---|---|---|"]
    for season, g in [*scored.groupby("season"), ("all", scored)]:
        if len(g):
            lines.append(f"| {season} | {len(g)} | {g['nll_raw'].mean():.4f} | {g['nll_cal'].mean():.4f} | "
                         f"{g['nll_cal'].mean() - g['nll_raw'].mean():+.4f} | {g['fav_raw'].mean():.3f} | "
                         f"{g['fav_cal'].mean():.3f} |")
    wf = out["rows"][out["rows"]["kind"] == "race_win"].dropna(subset=["y"])
    qmap = {(str(e), int(a)): q for e, a, q in zip(cal["event_key"], cal["athlete_id"], cal["q"])}
    amap = dict(zip(cal["event_key"], cal["a"]))
    for venue in venues:
        try:
            with __import__("racinglines.db.config", fromlist=["get_engine"]).get_engine(db).connect() as c:
                mids = MVM.read_mids(c, out["cutoffs"], venue, kinds=("race_win",))
        except Exception as ex:  # noqa: BLE001  (a venue's prices are an addition: the fit stands without them)
            lines += ["", f"## Against {venue}", "", f"not scored: {type(ex).__name__}: {ex}"]
            continue
        paired = MVM.pair(wf, mids, kinds=("race_win",)) if len(mids) else pd.DataFrame()
        paired = paired.dropna(subset=["mid"]) if len(paired) else paired
        lines += ["", f"## Against {venue} (its price at each race's cutoff, 00:00 UTC race day; binary log loss per market)", ""]
        if not len(paired):
            lines.append(f"no {venue} race-win price at any cutoff: nothing to pair (the tape was never pulled, or "
                         "every group was incoherent or stale)")
            continue
        paired["q"] = [qmap.get((str(e), int(a)), p) for e, a, p in zip(paired["event_id"], paired["athlete_id"], paired["fair"])]
        paired["a"] = [amap.get(str(e), 1.0) for e in paired["event_id"]]
        paired.to_csv(folder / f"vs_{venue}.csv", index=False)
        lines += ["| season | races | markets | model raw | model calibrated | market |", "|---|---|---|---|---|---|"]
        for season, g in [*paired.groupby("season"), ("all", paired)]:
            lines.append(f"| {season} | {g['event_id'].nunique()} | {len(g)} | {_binary_ll(g['fair'], g['y']):.4f} | "
                         f"{_binary_ll(g['q'], g['y']):.4f} | {_binary_ll(g['mid'], g['y']):.4f} |")
    lines += ["", "Raw = the walk-forward's price with calib_power unset; calibrated = p^a renormalised with the table "
              "row in force at the race's cutoff (fitted on earlier races only). Races before the first fitted row "
              "are left out of the tables above (a = 1, nothing to compare)."]
    (folder / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


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
    ap.add_argument("--sport", default="f1", help="f1 (stored sweep stages) or a results-level sport (walk-forward)")
    ap.add_argument("--seasons", nargs="+", type=int, default=None, help="--sport other than f1: the races fitted")
    ap.add_argument("--out", default=None, help="default sports/<sport>/calibration.toml")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", default=None, metavar="DIR", help="--sport other than f1: log loss before/after, vs venues")
    a = ap.parse_args(argv)
    a.out = a.out or str(ROOT / "sports" / a.sport / "calibration.toml")
    keep = {}
    if a.sport != "f1":
        df = load_walk_forward(a.sport, a.seasons, a.sims, a.db, keep=keep)
    elif a.csv:
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
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(CAL.to_toml(fits, header))
    print(f"wrote {len(fits)} fits -> {a.out}; latest: grid {fits[-1]['grid']}, nogrid {fits[-1]['nogrid']}")
    if a.report and keep:
        report(a.sport, df, fits, keep["out"], a.report, a.db)


if __name__ == "__main__":
    main()
