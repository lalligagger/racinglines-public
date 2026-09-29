"""
racinglines motogp <command>: MotoGP race results (from the free public results API at
api.motogp.pulselive.com).

    fetch        Download season events, categories, sessions and race classifications to
                 data/raw/motogp/pulselive/<year>/ (paced, safe to re-run; --dry-run counts the requests first).
    ingest       Load the stored classifications into the database (events, results, rider identity).
    (exchange data: racinglines markets sync | history | trades | record | archive --sport motogp)

Nothing here runs by default. Terms of use: sports/motogp.toml [results].terms — the owner has reviewed
them for the intended non-commercial fantasy use (2026-09-29); revisit before any wider use.
"""

import argparse


def _years(spec):
    if "," in spec:
        return [int(y) for y in spec.split(",")]
    a, _, b = spec.partition("-")
    return list(range(int(a), int(b or a) + 1))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines motogp", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="Database URL (default: $DATABASE_URL / docker-compose).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch", help="Download season events, sessions and race classifications.")
    p.add_argument("--years", default="2016-2026", help="e.g. 2026, 2016-2026 (default) or 2024,2026. "
                                                        "2016 is when Michelin became the sole tyre supplier; "
                                                        "earlier (Bridgestone-era) seasons are a follow-up.")
    p.add_argument("--force", action="store_true", help="Ask again for files already stored.")
    p.add_argument("--dry-run", action="store_true", help="Count the requests a run would make; ask for nothing.")
    p = sub.add_parser("ingest", help="Load the stored classifications into the database.")
    p.add_argument("--years", default="2016-2026")
    p.add_argument("--force", action="store_true", help="Rebuild events whose files have not changed.")
    args = ap.parse_args(argv)

    if args.cmd == "fetch":
        from racinglines.sources.motogp import fetch
        counts = fetch.fetch(_years(args.years), force=args.force, dry_run=args.dry_run)
        print("Would ask for" if args.dry_run else "Done:", counts)
        return 1 if counts["errors"] else 0
    from racinglines.db.config import get_session
    from racinglines.sources.motogp import ingest
    with get_session(args.db) as s:
        report = ingest.ingest(s, _years(args.years), force=args.force)
    done = sum(1 for v in report.values() if v.endswith("results"))
    print(f"Done: {done} events ingested of {len(report)} seen.")
    return 0
