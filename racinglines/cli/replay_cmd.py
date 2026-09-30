"""
`racinglines nascar replay` / `racinglines motogp replay`: the taker replay of a result-only sport against an
exchange's recorded prices (racinglines/pipelines/position_replay.py). Read-only unless --save.

    --venue all            the default: Kalshi then Polymarket (the sport's [markets] venues), one report each
    --save --backup FILE   also store one as-of model run per race (model_runs + race_predictions + prediction records
                           and sims; records are on for this command unless RACINGLINES_PREDICTION_RECORDS=0); FILE is
                           the database dump taken for this step within the last 24 hours. Logged in data_changes with
                           its batch id. The runs are stored once, with the first venue's pass.
    --undo BATCH           delete the runs a --save pass stored (the batch id it printed).
"""

import sys
import time
from pathlib import Path


def add_parser(sub, sport):
    p = sub.add_parser("replay", help=f"Taker replay of {sport} races against an exchange's recorded prices "
                                      "(read-only unless --save).")
    p.add_argument("--years", default="2025-2026", help="e.g. 2026, 2025-2026 or 2024,2026.")
    p.add_argument("--venue", default="all", choices=["all", "kalshi", "polymarket"],
                   help="all (the default): every exchange the sport lists on, one report each.")
    p.add_argument("--events", default=None, help="Only these event keys, comma list, or 'latest' (the last race of "
                                                  "--years): a spot check. The model still learns from earlier races.")
    p.add_argument("--kinds", default=None, help=f"Comma list, a subset of sports/{sport}.toml [replay] kinds.")
    p.add_argument("--min-edge", type=float, default=None, help="Taker threshold (default: TakerParams, 0.05).")
    p.add_argument("--stake-per-edge", type=float, default=None)
    p.add_argument("--max-stake", type=float, default=None)
    p.add_argument("--cost", type=float, default=None, help="$ per share on every trade (default 0.01).")
    p.add_argument("--min-volume", type=float, default=None, help="24 h volume floor in $ (default 50).")
    p.add_argument("--sims", type=int, default=None, help="Model simulations per race (default: the model's).")
    p.add_argument("--out", default=None, help="Write races.csv, trades.csv, calibration.csv, summary.json here "
                                               "(default data/runs/replay/<sport>-<venue>-<years>/).")
    p.add_argument("--save", action="store_true", help="Also store one as-of model run per race (needs --backup).")
    p.add_argument("--backup", default=None, help="With --save: the database dump taken for this step (under 24 hours old).")
    p.add_argument("--undo", default=None, help="Delete the runs of a previous --save pass (its batch id).")
    return p


def run(args, sport, years):
    from racinglines import paths
    from racinglines.db import changes
    from racinglines.db.config import get_engine, get_session
    from racinglines.markets.strategies import taker_weekend as RB
    from racinglines.pipelines import position_replay as P

    if args.undo:
        with get_session(args.db) as s:
            n = P.undo(s, args.undo)
            changes.record(s, "replay-undo", f"{sport} replay runs deleted: {n} of batch {args.undo}", sport=sport,
                           detail=dict(batch=args.undo, runs=n))
            s.commit()
        print(f"Deleted {n} runs of batch {args.undo}")
        return 0
    save = None
    if args.save:
        backup = Path(args.backup) if args.backup else None
        if not (backup and backup.is_file() and backup.stat().st_size and time.time() - backup.stat().st_mtime < 86400):
            sys.exit("--save writes model_runs and race_predictions: give --backup FILE, the database dump taken for this "
                     f"step within the last 24 hours (data/backups/db/racinglines-before-{sport}-replay-<UTC>.sql.gz)")
        save = dict(engine_url=args.db, batch=P.batch_id())
    over = {k: v for k, v in dict(min_edge=args.min_edge, stake_per_edge=args.stake_per_edge, max_stake=args.max_stake,
                                  cost=args.cost).items() if v is not None}
    taker = RB.TakerParams(**over)
    kinds = [k.strip() for k in args.kinds.split(",")] if args.kinds else None
    engine = get_engine(args.db)
    venues = [v for v in ("kalshi", "polymarket") if v in P.venues(sport)] if args.venue == "all" else [args.venue]
    data = None
    for i, venue in enumerate(venues):
        out = P.run(engine, sport, years, venue=venue, taker=taker, kinds=kinds, data=data,
                    events=args.events.split(",") if args.events else None,
                    min_volume_24h=P.MIN_VOLUME_24H if args.min_volume is None else args.min_volume,
                    model_settings={"sims": args.sims} if args.sims else None, save=save if i == 0 else None)
        data = out.pop("data")
        print(P.format_report(out))
        tag = f"{sport}-{venue}-{years[0]}-{years[-1]}" if years else f"{sport}-{venue}"
        folder = P.write(out, Path(args.out) / venue if args.out else paths.runs("replay") / tag)
        print(f"\nWrote {folder}\n")
    if save:
        with get_session(args.db) as s:
            n = s.execute(__import__("sqlalchemy").text(
                "SELECT count(*) FROM model_runs WHERE params->>'replay_batch' = :b"), dict(b=save["batch"])).scalar()
            changes.record(s, "replay-save", f"{sport} replay: {n} as-of model runs stored (batch {save['batch']}); "
                           f"backup {Path(args.backup).name}", sport=sport,
                           detail=dict(batch=save["batch"], runs=n, backup=Path(args.backup).name, venue=args.venue,
                                       years=years))
            s.commit()
        print(f"Stored {n} runs, batch {save['batch']}. Undo: racinglines {sport} replay --undo {save['batch']}")
    return 0
