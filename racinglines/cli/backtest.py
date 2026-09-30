"""
racinglines backtest <command>: the backtest core for any sport with a pricing model (docs/backtest-core.md).

    walk-forward SPORT   price every event from data before it (racinglines/core/walk_forward.py), model-only:
                         calibration per market kind; --save stores it as a walk_forward model run (what a
                         search job runs). The sport's pricing model is named in sports/<code>.toml
                         ([sport] pricing_model), and its settings are its flags.

    racinglines backtest walk-forward mtb_dh --seasons 2025 --half-life-days 120 [--save]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


def run_walk_forward(model, data, st, seasons=None, kinds=None, out_dir=None, save=False, engine_url=None,
                     echo=print):
    """The engine, its CSVs and (save) the model run. Returns the engine's output."""
    from racinglines.core import walk_forward as WF
    seasons = seasons or model.seasons(data, st)
    echo(f"Walk-forward {model.sport} {', '.join(map(str, seasons))} · {st.label()} (settings {st.key})")
    from racinglines.db import records as REC
    keep = bool(save and REC.enabled())
    out = WF.run(model, data, st, seasons=seasons, kinds=kinds, echo=echo, keep_sims=keep)
    kept = out.pop("sims", None) if keep else None            # the returned output is the same with records on or off
    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("events", "calibration", "reliability"):
            out[name].to_csv(out_dir / f"walk_forward_{name}.csv", index=False)
    pd.set_option("display.width", 250)
    cal = out["calibration"]
    echo("\n=== Calibration of the model's fair values (all seasons) ===")
    echo(cal[cal["season"] == "all"].drop(columns=["season", "source"]).to_string(index=False, float_format="{:.4f}".format))
    if out_dir:
        echo(f"\nCSVs -> {out_dir}/")
    if save:
        from racinglines import sports
        from racinglines.db.config import get_session
        from racinglines.db.queries import save_model_run
        params = dict(settings=st.to_json(), settings_key=st.key, model_key=st.model_key, label=st.label(),
                      seasons=list(map(int, seasons)), year=int(seasons[-1]) if len(seasons) == 1 else None,
                      sims=st["sims"], seed=st.rng_seed, sport=model.sport)
        with get_session(engine_url) as session:
            run_id = save_model_run(session, competition=sports.load(model.sport)["competition"]["code"],
                                    season=seasons[-1] if len(seasons) == 1 else None, category=st.get("category"),
                                    model=model.name, kind="walk_forward", data_through=model.data_through(data),
                                    params=params, metrics=WF.saved_metrics(out))
        echo(f"Saved walk-forward run {run_id}.")
        if keep and kept:
            frames = [sims.to_records(run_id, model.sport, model.name, ev.season, ev.id, ev.name, "pre_race",
                                      ev.cutoff, kinds=kinds) for ev, sims in kept]
            REC.write(run_id, REC.concat(frames), sims={ev.id: sims for ev, sims in kept})
            echo(f"Prediction records -> {REC.records_dir() / str(run_id)}/")
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    from racinglines import paths
    from racinglines.models import race_model as RM
    from racinglines.pipelines import sweep_settings as SS
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("cmd", nargs="?")
    pre.add_argument("sport", nargs="?")
    known, _ = pre.parse_known_args(argv)
    ap = argparse.ArgumentParser(prog="racinglines backtest", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    wf = sub.add_parser("walk-forward", help="Price every event through the shared engine (model-only).")
    wf.add_argument("sport", help="A sport code with a pricing model (sports/<code>.toml).")
    wf.add_argument("--db", default=None, metavar="URL", help="Database URL (default: $DATABASE_URL).")
    wf.add_argument("--seasons", nargs="+", type=int, help="Seasons (default: every season the model can score).")
    wf.add_argument("--kinds", help="Market kinds, comma-separated (default: every per-entrant kind the model prices).")
    wf.add_argument("--out-dir", help="Write the CSVs here (default: data/runs/<sport>/walk_forward).")
    wf.add_argument("--save", action="store_true", help="Store the run in the database (model_runs, kind walk_forward).")
    if known.cmd == "walk-forward" and known.sport:
        model = RM.get(known.sport)
        SS.add_arguments(wf, model.Settings)
    args = ap.parse_args(argv)
    model = RM.get(args.sport)
    st = SS.from_args(args, model.Settings)
    data = model.load(args.db)
    run_walk_forward(model, data, st, seasons=args.seasons, kinds=args.kinds.split(",") if args.kinds else None,
                     out_dir=args.out_dir or paths.runs(args.sport, "walk_forward", mkdir=False), save=args.save,
                     engine_url=args.db)
    return 0
