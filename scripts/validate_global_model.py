"""Validate the global results model (racinglines/models/model_global.py) against a sport's own pricing model.

Runs the same seasons, seed, simulation count and market kinds through the shared walk-forward engine
(racinglines/core/walk_forward.py) three ways and prints one calibration table (log loss and Brier, lower is
better; the model never sees the prices):

    own      the sport's [sport] pricing_model
    global   the sport-agnostic model pointed at the sport's schema (`--set k=v` changes its settings)
    control  the same model told to learn nothing (prior_weight 100, the setting's cap: results move a price by a few percent of a place at most): every entrant priced alike, the floor

Read-only: reads the database, writes nothing but the CSV (default data/runs/validation/<sport>.csv).

    python scripts/validate_global_model.py motogp --seasons 2016 2026 --own-field
    python scripts/validate_global_model.py f1 --seasons 2024 2025 2026 --set half_life_days=120

`--own-field` hands the sport's own model the event's start list (the result-only MotoGP and NASCAR models price
every entrant they have ever seen unless the replay gives them one, which dilutes every walk-forward price); the
control for a fair comparison. F1's own model reads its own field and needs no flag.
"""

import argparse
import dataclasses
from pathlib import Path

import pandas as pd

from racinglines import paths
from racinglines.cli.backtest import pricing_model
from racinglines.core import walk_forward as WF

KINDS = "race_win,race_podium,race_top10,race_h2h"


def with_field(model):
    """The model with each event's start list in ev.info["field"], read from the event's own classification."""
    class FieldAware(type(model)):
        def events(self, data, settings, seasons=None):
            return [dataclasses.replace(e, info={"field": sorted(int(a) for a in self.results(data, e)["athlete_id"])})
                    for e in super().events(data, settings, seasons)]
    return FieldAware()


def with_filled_positions(model):
    """The model reading a frame whose unclassified positions (retirements stored without one) are filled in
    behind the race's last classified finisher: the own MotoGP/NASCAR models average positions, so a rider whose
    every position is empty has a NaN form and sorts last in every simulation."""
    class Filled(type(model)):
        def load(self, engine_url=None, data=None):
            d = super().load(engine_url, data)
            d["position"] = d["position"].fillna(d.groupby("race")["position"].transform("max") + 1)
            return d
    return Filled()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sport")
    ap.add_argument("--seasons", nargs="+", type=int, required=True)
    ap.add_argument("--kinds", default=KINDS)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--set", action="append", default=[], metavar="K=V", help="a global-model setting")
    ap.add_argument("--own-set", action="append", default=[], metavar="K=V", help="a setting of the sport's own model")
    ap.add_argument("--own-field", action="store_true", help="give the sport's own model each event's start list")
    ap.add_argument("--own-fill", action="store_true", help="fill the own model's empty positions behind the finishers")
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    kinds = args.kinds.split(",")
    extra = dict(kv.split("=", 1) for kv in args.set)
    base = {"sims": args.sims, "seed": args.seed}
    own = pricing_model(args.sport)
    glob = pricing_model(args.sport, "global")
    own_extra = dict(kv.split("=", 1) for kv in args.own_set)
    if args.own_fill:
        own = with_filled_positions(own)
    if args.own_field:
        own = with_field(own)
    runs = [("own", own, {**base, **own_extra}),
            ("global", glob, {**base, **extra}),
            ("control", glob, {**base, **extra, "prior_weight": 100, "uncertainty": 0, "dnf": False})]
    rows = []
    for label, model, settings in runs:
        st = model.Settings.from_dict(settings)
        data = model.load(args.db)
        out = WF.run(model, data, st, seasons=args.seasons, kinds=kinds, echo=lambda s: None)
        cal = out["calibration"]
        rows.append(cal.assign(model=label, events=cal["season"].map(
            {**{str(k): v for k, v in out["events"].groupby("season").size().items()}, "all": len(out["events"])})))
        print(f"{label}: {model.name} priced {len(out['events'])} events ({st.label()})", flush=True)
    table = pd.concat(rows, ignore_index=True)
    table["season"] = table["season"].astype(str)
    path = Path(args.out or paths.runs("validation", mkdir=True) / f"{args.sport}.csv")
    table.to_csv(path, index=False)
    pd.set_option("display.width", 200)
    for col in ("logloss", "brier"):
        print(f"\n{args.sport}: {col} (lower is better)")
        print(table.pivot_table(index=["season", "kind"], columns="model", values=col)[["own", "global", "control"]]
              .round(4).to_string())
    print("\nn (outcomes scored) per kind, all seasons:")
    print(table[table["season"] == "all"].pivot_table(index="kind", columns="model", values="n").to_string())
    print(f"\nCSV -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
