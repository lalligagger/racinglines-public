"""
racinglines markets <command>: exchange data (Polymarket; F1 is the only sport listed today).

    sync       Sync the exchange's events into market links (live prices, resolutions)
    history    Store price history for events (--fidelity 1 = minute-level)
    trades     Store every taker trade for events (the tape a maker replay fills against)
    record     Record order-book snapshots every --interval seconds (archives to Parquet hourly)
    archive    Move stale prices / trades / books from Postgres to Parquet (--stats: sizes)

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
    if not rest or rest[0] in ("-h", "--help") or rest[0] not in COMMANDS:
        print(__doc__)
        return 0 if rest and rest[0] in ("-h", "--help") else 2
    from . import f1
    return f1.main((["--db", known.db] if known.db else []) + [COMMANDS[rest[0]]] + rest[1:])


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
