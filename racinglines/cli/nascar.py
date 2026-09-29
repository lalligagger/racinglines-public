"""
racinglines nascar <command>: NASCAR (Cup, from the free content feeds at cf.nascar.com).

    fetch        Download the feeds to data/raw/nascar/cf/<year>/<series>/ (1 request/s, safe to re-run;
                 --dry-run counts the requests first).
    ingest       Load the stored feeds into the database (events, results, laps, driver identity).
    (exchange data: racinglines markets sync | history | trades | record | archive --sport nascar)

Nothing here runs by default. A full pull and ingest is a VM job: back up the database first
(docs/data-changes.md), and probe from the owner's machine before the first full run.
"""

import argparse
import sys


def _years(spec):
    if "," in spec:
        return [int(y) for y in spec.split(",")]
    a, _, b = spec.partition("-")
    return list(range(int(a), int(b or a) + 1))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines nascar", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="Database URL (default: $DATABASE_URL / docker-compose).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch", help="Download the content feeds.")
    p.add_argument("--years", default="2026", help="e.g. 2026, 2020-2026 or 2024,2026 (feeds start 2015-2020 by kind).")
    p.add_argument("--series", type=int, default=1, help="1 Cup (default), 2 Xfinity, 3 Trucks.")
    p.add_argument("--feeds", default=None, help="Comma list of: race_list_basic, points-feed, weekend-feed, pit-data, "
                                                 "loopstats, lap-times, lap-notes (default: all).")
    p.add_argument("--races", default=None, help="Only these race ids, e.g. 5624,5628.")
    p.add_argument("--force", action="store_true", help="Ask again for files already stored or marked missing.")
    p.add_argument("--dry-run", action="store_true", help="Count the requests a run would make; ask for nothing.")
    p = sub.add_parser("ingest", help="Load the stored feeds into the database.")
    p.add_argument("--years", default="2026")
    p.add_argument("--series", type=int, default=1)
    p.add_argument("--force", action="store_true", help="Rebuild races whose files have not changed.")
    p.add_argument("--no-laps", action="store_true", help="Skip the lap table (8,000 to 18,000 rows per race).")
    args = ap.parse_args(argv)

    if args.cmd == "fetch":
        from racinglines.sources.nascar import fetch
        feeds = [f.strip() for f in args.feeds.split(",")] if args.feeds else None
        known = set(fetch.SEASON_FEEDS) | set(fetch.RACE_FEEDS)
        if feeds and set(feeds) - known:
            sys.exit(f"unknown feed(s) {sorted(set(feeds) - known)}; choose from {sorted(known)}")
        races = {int(r) for r in args.races.split(",")} if args.races else None
        counts = fetch.fetch(_years(args.years), series=args.series, feeds=feeds, races=races, force=args.force,
                             dry_run=args.dry_run)
        print("Would ask for" if args.dry_run else "Done:", counts)
        return 1 if counts["errors"] else 0
    from racinglines.db.config import get_session
    from racinglines.sources.nascar import ingest
    with get_session(args.db) as s:
        print("Done:", ingest.ingest(s, _years(args.years), series=args.series, force=args.force, laps=not args.no_laps))
    return 0
