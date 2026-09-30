"""
racinglines nascar <command>: NASCAR (Cup, from the free content feeds at cf.nascar.com).

    fetch        Download the feeds to data/raw/nascar/cf/<year>/<series>/ (1 request/s, safe to re-run;
                 --dry-run counts the requests first).
    ingest       Load the stored feeds into the database (events, results, laps, driver identity).
    link         Say which driver and race each stored NASCAR market link is about (any exchange); dry run by default,
                 --apply needs a fresh database dump (--backup FILE) and can be undone (--undo FILE).
    replay       Taker replay of Cup races against Kalshi's or Polymarket's recorded prices (read-only unless
                 --save; racinglines/pipelines/position_replay.py).
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
    p = sub.add_parser("link", help="Identify the driver, race and contract of stored market links.")
    p.add_argument("--exchange", default=None, help="Only this exchange's links (kalshi, polymarket, og).")
    p.add_argument("--apply", action="store_true", help="Write the changes (default: a dry run that only reports).")
    p.add_argument("--backup", default=None, help="With --apply: the database dump taken for this step (under 24 hours old).")
    p.add_argument("--undo", default=None, help="Put back the values a previous --apply replaced (the undo file it wrote).")
    from racinglines.cli import replay_cmd
    replay_cmd.add_parser(sub, "nascar")
    args = ap.parse_args(argv)

    if args.cmd == "replay":
        return replay_cmd.run(args, "nascar", _years(args.years))
    if args.cmd == "link":
        return _link(args)
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


def _link(args):
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    from racinglines import paths
    from racinglines.db import changes
    from racinglines.db.config import get_session
    from racinglines.sources.nascar import links

    if args.undo:
        with get_session(args.db) as s:
            n = links.undo(s, args.undo)
            changes.record(s, "link-undo", f"NASCAR market links: {n} restored from {args.undo}", sport="nascar")
            s.commit()
        print(f"Restored {n} links from {args.undo}")
        return 0
    backup = Path(args.backup) if args.backup else None
    if args.apply and not (backup and backup.is_file() and backup.stat().st_size and time.time() - backup.stat().st_mtime < 86400):
        sys.exit("--apply writes market_links: give --backup FILE, the database dump taken for this step within the last 24 hours "
                 "(data/backups/db/racinglines-before-nascar-links-<UTC>.sql.gz; docs/data-changes.md)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with get_session(args.db) as s:
        report = links.relink(s, s.connection(), exchange=args.exchange, apply=args.apply,
                              undo_path=paths.DATA / "backups" / "db" / f"nascar-links-undo-{stamp}.json")
        print(links.format_report(report))
        if not args.apply:
            print("\nDry run: nothing written. Add --apply --backup FILE to write these changes.")
        elif report["changed"]:
            changes.record(s, "link", f"NASCAR market links identified: {report['changed']:,} of {report['links']:,} changed "
                           f"(athlete, race, params.kind / nascar_series / season); backup {backup.name}; undo {report['undo']}",
                           sport="nascar", detail=dict(backup=backup.name, undo=report["undo"], links=report["links"],
                                                       changed=report["changed"], shapes=report["shapes"]))
            s.commit()
            print(f"\nWrote {report['changed']:,} links. Undo: racinglines nascar link --undo {report['undo']}")
        else:
            print("\nNothing to change.")
    return 0
