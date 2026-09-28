"""
racinglines db <command>

    init      Create or upgrade the schema to the latest migration (Alembic), then seed reference data.
    seed      Upsert sports / leagues / competitions / categories / venues from registry.py.
    stats     Row counts and coverage per season and category.
    export    Write the tidy frame (same columns as `racinglines mtb_dh parse`'s CSV) for a competition to CSV.
    snapshot-export  The tables the models read, with ids, to data/archive/db/ (Parquet).
    snapshot-import  Load that snapshot into a fresh database: an exact replica (same ids, same prices).
    merge-athletes   Merge two athletes that are the same person (e.g. a name change found by UCI ID).

Connection: $DATABASE_URL, or --db URL (default: docker-compose.yml's database).
"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # the repository

from sqlalchemy import text  # noqa: E402

from racinglines.db.config import database_url, get_engine, get_session  # noqa: E402


def cmd_init(args):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url(args.db))
    command.upgrade(cfg, "head")
    cmd_seed(args)


def cmd_seed(args):
    from racinglines.db.ingest import seed

    with get_session(args.db) as s:
        seed(s)
        s.commit()
    print("Reference data seeded.")


STATS_SQL = """
SELECT co.code AS competition, s.year, c.code AS category, count(DISTINCT e.id) AS events,
       count(DISTINCT ro.id) AS rounds, count(r.id) AS results
FROM results r JOIN rounds ro ON ro.id = r.round_id JOIN races ra ON ra.id = ro.race_id
JOIN events e ON e.id = ra.event_id JOIN seasons s ON s.id = e.season_id
JOIN competitions co ON co.id = s.competition_id JOIN categories c ON c.id = ra.category_id
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
"""


def cmd_stats(args):
    import pandas as pd

    eng = get_engine(args.db)
    with eng.connect() as conn:
        for t in ["sports", "leagues", "competitions", "categories", "venues", "events", "races", "rounds",
                  "athletes", "athlete_identifiers", "results", "splits", "source_files", "model_runs",
                  "race_predictions", "standings_predictions"]:
            print(f"{t:<22} {conn.execute(text(f'SELECT count(*) FROM {t}')).scalar():>8}")
        print()
        print(pd.read_sql(text(STATS_SQL), conn).to_string(index=False))


def cmd_export(args):
    from racinglines.db.queries import load_tidy

    df = load_tidy(get_engine(args.db), competition=args.competition)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df)} rows -> {args.out}")


def cmd_snapshot_export(args):
    from racinglines import paths
    from racinglines.db import snapshot as S
    counts = S.export(get_engine(args.db))
    print(f"exported {sum(counts.values()):,} rows in {len(counts)} tables -> {paths.rel(S.DIR)}")


def cmd_snapshot_import(args):
    from racinglines.db import snapshot as S
    counts = S.import_(get_engine(args.db), force=args.force)
    print(f"imported {sum(counts.values()):,} rows in {len(counts)} tables")


def cmd_merge_athletes(args):
    from racinglines.db.ingest import merge_athletes
    with get_session(args.db) as s:
        moved = merge_athletes(s, args.keep, args.drop, dry_run=args.dry_run)
        if not args.dry_run:
            s.commit()
    rows = ", ".join(f"{t} {n}" for t, n in moved.items()) or "nothing"
    print(f"{'Would move' if args.dry_run else 'Moved'} athlete {args.drop} into {args.keep}: {rows}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines db", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="Database URL (default: $DATABASE_URL or the docker-compose database).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="Migrate schema to latest and seed reference data.").set_defaults(func=cmd_init)
    sub.add_parser("seed", help="Upsert reference data from registry.py.").set_defaults(func=cmd_seed)
    sub.add_parser("stats", help="Row counts and coverage.").set_defaults(func=cmd_stats)
    p = sub.add_parser("export", help="Write the tidy frame for a competition to CSV.")
    p.add_argument("--competition", default="uci_dhi_wc")
    p.add_argument("--out", default="splits.csv")
    p.set_defaults(func=cmd_export)
    sub.add_parser("snapshot-export", help="Model tables with ids -> data/archive/db/.").set_defaults(func=cmd_snapshot_export)
    p = sub.add_parser("snapshot-import", help="Load data/archive/db/ into a fresh database.")
    p.add_argument("--force", action="store_true", help="Even if the database already holds model runs.")
    p.set_defaults(func=cmd_snapshot_import)
    p = sub.add_parser("merge-athletes", help="Merge athlete DROP into KEEP (same person), then delete DROP.")
    p.add_argument("keep", type=int)
    p.add_argument("drop", type=int)
    p.add_argument("--dry-run", action="store_true", help="Only report what would move.")
    p.set_defaults(func=cmd_merge_athletes)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
