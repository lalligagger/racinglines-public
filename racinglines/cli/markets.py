"""
racinglines markets <command>: exchange data (Polymarket; F1 is the only sport listed today).

    sync       Sync the exchange's events into market links (live prices, resolutions)
    history    Store price history for events (--fidelity 1 = minute-level)
    trades     Store every taker trade for events (the tape a maker replay fills against)
    record     Record order-book snapshots every --interval seconds (archives to Parquet hourly)
    archive    Move stale prices / trades / books from Postgres to Parquet (--stats: sizes)
    disagree   Cross-venue disagreement log: Polymarket vs Kalshi on every outcome listed on both, per tick
               (--event 2026-15, a round number, or season [--year]; --start/--end UTC, --step minutes, --no-save)

Options: --exchange polymarket (default) --sport f1 (default), then the command's own options.

Kalshi (--exchange kalshi; markets/kalshi/, built on mocked responses, unverified against the live API):
    sync       [--year 2026] [--closed]                  Kalshi's F1 markets into market links
    trades     --events TICKER …                         the tape of those events' markets
    history    --events TICKER … --start --end [--period 60]   candlesticks (minutes: 1, 60, 1440)
    books      --events TICKER …                         one order-book snapshot per open market
"""

import argparse
import sys

COMMANDS = {"sync": "pm-sync", "history": "pm-history", "trades": "pm-trades", "record": "pm-record",
            "archive": "pm-archive"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="racinglines markets", description=__doc__, add_help=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exchange", default="polymarket", choices=["polymarket", "kalshi"])
    ap.add_argument("--sport", default="f1", choices=["f1"])
    ap.add_argument("--db", default=None)
    known, rest = ap.parse_known_args(argv)
    if known.exchange == "kalshi":
        return kalshi(known.db, rest)
    if rest and rest[0] == "disagree":
        return disagree(known.db, rest[1:])
    if not rest or rest[0] in ("-h", "--help") or rest[0] not in COMMANDS:
        print(__doc__)
        return 0 if rest and rest[0] in ("-h", "--help") else 2
    from . import f1
    return f1.main((["--db", known.db] if known.db else []) + [COMMANDS[rest[0]]] + rest[1:])


def disagree(db, argv):
    """racinglines markets disagree (markets/disagree.py): backfill the cross-venue log from stored prices and print
    the report. --event YEAR-ROUND / ROUND (a race weekend, up to the race start) or season (the drivers' and
    constructors' champion markets of --year). The window defaults to where both venues have prices, on a --step
    minute grid."""
    ap = argparse.ArgumentParser(prog="racinglines markets disagree")
    ap.add_argument("--event", required=True, help="YEAR-ROUND (e.g. 2026-15), a round number of --year, or 'season'")
    ap.add_argument("--year", type=int, default=None, help="Season (default: this year)")
    ap.add_argument("--competition", default="f1_wdc", help="Competition code (default f1_wdc)")
    ap.add_argument("--start", default=None, help="UTC start, e.g. 2026-09-22T00:00 (default: first tick both venues quote)")
    ap.add_argument("--end", default=None, help="UTC end (default: the last, or the race start)")
    ap.add_argument("--step", type=int, default=60, help="Minutes between ticks (default 60)")
    ap.add_argument("--no-save", action="store_true", help="Print the report without writing market_disagreements")
    args = ap.parse_args(argv)
    from datetime import datetime, timedelta, timezone

    import pandas as pd
    from sqlalchemy import text

    from racinglines.db.config import get_engine
    from racinglines.markets import disagree as D
    year = args.year or datetime.now(timezone.utc).year
    engine = get_engine(db)
    with engine.begin() as c:
        comp = c.execute(text("SELECT id, name FROM competitions WHERE code = :c"), dict(c=args.competition)).fetchone()
        if comp is None:
            print(f"unknown competition {args.competition}", file=sys.stderr)
            return 2
        if args.event == "season":
            prs, title = D.pairs(c, competition_id=int(comp[0]), year=year), f"{comp[1]} {year} championship"
        else:
            key = args.event if "-" in args.event else f"{year}-{args.event}"
            race = c.execute(text("""SELECT ra.id, e.name, (SELECT min((ro.extra->>'session_date')::timestamp) FROM rounds ro
                                                          WHERE ro.race_id = ra.id AND ro.kind = 'race') AS race_start
                                     FROM races ra JOIN events e ON e.id = ra.event_id
                                     JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
                                     WHERE e.source_key = :k AND co.code = :c ORDER BY ra.id LIMIT 1"""),
                             dict(k=key, c=args.competition)).fetchone()
            if race is None:
                print(f"no race for event {key}", file=sys.stderr)
                return 2
            prs, title = D.pairs(c, race_id=int(race[0])), f"{race[1]} ({key})"
        if not len(prs):
            print(f"{title}: no outcome linked on both venues")
            return 0
        start, end = D.coverage(c, prs)
        if args.event != "season" and race[2] is not None and end is not None:
            end = min(end, pd.Timestamp(race[2]).tz_localize(timezone.utc))     # up to the start: after it, settlement
        if args.start:
            start = pd.Timestamp(args.start).tz_localize(timezone.utc)
        if args.end:
            end = pd.Timestamp(args.end).tz_localize(timezone.utc)
        if start is None or end is None:
            print(f"{title}: {len(prs)} outcomes on both venues, but no stored prices for both")
            return 0
        df = D.build(c, prs, start, end, step=timedelta(minutes=args.step))
        n = 0 if args.no_save else D.save(c, df)
    print(D.report(df, title))
    print(f"\n{len(prs)} outcomes on both venues · {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC every {args.step} min · "
          f"{n} rows {'would be ' if args.no_save else ''}written to market_disagreements")
    return 0


def kalshi(db, argv):
    """racinglines markets --exchange kalshi <command> (markets/kalshi/sync.py)."""
    ap = argparse.ArgumentParser(prog="racinglines markets --exchange kalshi")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--closed", action="store_true", help="Also settled events")
    for name in ("trades", "history", "books"):
        p = sub.add_parser(name)
        p.add_argument("--events", nargs="+", required=True, help="Kalshi event tickers (market_links.condition_id)")
        if name == "history":
            p.add_argument("--start", required=True, help="UTC start, e.g. 2026-10-01T00:00")
            p.add_argument("--end", required=True, help="UTC end")
            p.add_argument("--period", type=int, default=60, choices=[1, 60, 1440], help="Minutes per candle")
    args = ap.parse_args(argv)
    from datetime import timezone

    import pandas as pd

    from racinglines.db.config import get_engine, get_session
    from racinglines.markets.kalshi import sync as KS
    with get_engine(db).connect() as c, get_session(db) as s:
        if args.cmd == "sync":
            print(KS.sync(s, c, args.year, include_closed=args.closed))
        elif args.cmd == "trades":
            print(f"{KS.fetch_trades(s, c, args.events)} trades stored")
        elif args.cmd == "history":
            t = [pd.Timestamp(x).tz_localize(timezone.utc).to_pydatetime() for x in (args.start, args.end)]
            print(f"{KS.fetch_history(s, c, args.events, t[0], t[1], args.period)} price points stored")
        else:
            print(f"{KS.snapshot_books(s, c, args.events)} book snapshots stored")
    return 0
