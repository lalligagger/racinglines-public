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
    sync       [--year 2026] [--closed] [--series TICKER …]   the sport's Kalshi markets into market links
    trades     [--events TICKER …]                       the tape of those events' markets
    history    [--events TICKER …] --start --end [--period 60]   candlesticks (minutes: 1, 60, 1440)
    books      [--events TICKER …]                       one order-book snapshot per open market

Exchanges defined as schemas (--exchange og; exchanges/<code>.toml, markets/exchange_driver.py), read-only:
    sync       [--year 2026]                             the sport's markets and quotes into market links
    trades     [--events SYMBOL …]                       the tape the exchange still serves (about a month)
    history    [--events SYMBOL …] --start [--end]       minute prices (clipped to what the exchange keeps)
    books      [--events SYMBOL …]                       one order-book snapshot per open market
    fair       the model's fair price beside the quote, net of the taker fee: a simple indicator, no trades

--sport names the sport (default f1): the tape-only sports (nascar, motogp, indycar; sports/<code>.toml
[markets.kalshi]) are synced only when named, every link unmodeled, under their own competition. Without
--events, trades / history / books take every Kalshi event of --sport's competition (books: open markets).
"""

import argparse
import sys

COMMANDS = {"sync": "pm-sync", "history": "pm-history", "trades": "pm-trades", "record": "pm-record",
            "archive": "pm-archive"}


def kalshi_sports():
    """The sports the Kalshi sync knows: F1 and every schema with a [markets.kalshi] series list."""
    from racinglines import sports
    return ["f1"] + [c for c in sports.SPORT_CODES if c != "f1" and sports.kalshi_series(c)]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="racinglines markets", description=__doc__, add_help=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    from racinglines import exchanges
    ap.add_argument("--exchange", default="polymarket", choices=["polymarket", "kalshi", *exchanges.CODES])
    ap.add_argument("--sport", default="f1", choices=sorted({*kalshi_sports(), *(s for c in exchanges.CODES for s in exchanges.sports(c))}))
    ap.add_argument("--db", default=None)
    known, rest = ap.parse_known_args(argv)
    if known.exchange in exchanges.CODES:
        return schema_exchange(known.exchange, known.db, rest, known.sport)
    if known.exchange == "kalshi":
        return kalshi(known.db, rest, known.sport)
    if known.sport != "f1":
        print(f"--sport {known.sport}: only Kalshi lists it (--exchange kalshi)", file=sys.stderr)
        return 2
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
def kalshi(db, argv, sport="f1"):
    """racinglines markets --exchange kalshi [--sport f1] <command> (markets/kalshi/sync.py)."""
    ap = argparse.ArgumentParser(prog=f"racinglines markets --exchange kalshi --sport {sport}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync")
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--closed", action="store_true", help="Also settled events")
    p.add_argument("--series", nargs="+", default=None, help="Series tickers to sync instead of discovering them")
    for name in ("trades", "history", "books"):
        p = sub.add_parser(name)
        p.add_argument("--events", nargs="+", default=None,
                       help=f"Kalshi event tickers (market_links.condition_id); default: every {sport} event")
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
            print(KS.sync(s, c, args.year, include_closed=args.closed, sport=sport, series=args.series))
        elif args.cmd == "trades":
            print(f"{KS.fetch_trades(s, c, args.events, sport=sport)} trades stored")
        elif args.cmd == "history":
            t = [pd.Timestamp(x).tz_localize(timezone.utc).to_pydatetime() for x in (args.start, args.end)]
            print(f"{KS.fetch_history(s, c, args.events, t[0], t[1], args.period, sport=sport)} price points stored")
        else:
            print(f"{KS.snapshot_books(s, c, args.events, sport=sport)} book snapshots stored")
    return 0


def schema_exchange(code, db, argv, sport="f1"):
    """racinglines markets --exchange <code> [--sport f1] <command>: an exchange defined by a schema (exchanges/<code>.toml)."""
    from racinglines import exchanges
    if sport not in exchanges.sports(code):
        print(f"--sport {sport}: {code} lists {', '.join(exchanges.sports(code))} (exchanges/{code}.toml)", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog=f"racinglines markets --exchange {code} --sport {sport}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sync")
    p.add_argument("--year", type=int, default=2026)
    for name in ("trades", "history", "books"):
        p = sub.add_parser(name)
        p.add_argument("--events", nargs="+", default=None, help="Event symbols (market_links.condition_id); default: every event")
        if name == "history":
            p.add_argument("--start", required=True, help="UTC start, e.g. 2026-09-01T00:00 (clipped to what the exchange keeps)")
            p.add_argument("--end", default=None, help="UTC end (default now)")
    sub.add_parser("fair")
    args = ap.parse_args(argv)
    from racinglines.db.config import get_engine, get_session
    from racinglines.markets import exchange_driver as D
    with get_engine(db).connect() as c, get_session(db) as s:
        if args.cmd == "sync":
            print(D.sync(s, c, code, sport, args.year))
        elif args.cmd == "trades":
            print(f"{D.fetch_trades(s, c, code, sport=sport, events=args.events)} trades stored")
        elif args.cmd == "history":
            print(f"{D.fetch_history(s, c, code, args.start, args.end, sport=sport, events=args.events)} price rows stored")
        elif args.cmd == "books":
            print(f"{D.snapshot_books(s, c, code, sport=sport, events=args.events)} book snapshots stored")
        else:
            print(D.fair_text(D.fair_report(c, code, sport), code, exchanges.load(code)["exchange"].get("taker_fee_per_contract", 0.0)))
    return 0
