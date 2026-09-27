"""
racinglines markets <command>: exchange data (Polymarket; F1 is the only sport listed today).

    sync       Sync the exchange's events into market links (live prices, resolutions)
    history    Store price history for events (--fidelity 1 = minute-level)
    trades     Store every taker trade for events (the tape a maker replay fills against)
    record     Record order-book snapshots every --interval seconds (archives to Parquet hourly)
    archive    Move stale prices / trades / books from Postgres to Parquet (--stats: sizes)

Options: --exchange polymarket (default) --sport f1 (default), then the command's own options.
"""

import argparse
import sys

COMMANDS = {"sync": "pm-sync", "history": "pm-history", "trades": "pm-trades", "record": "pm-record",
            "archive": "pm-archive"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="racinglines markets", description=__doc__, add_help=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exchange", default="polymarket", choices=["polymarket"])
    ap.add_argument("--sport", default="f1", choices=["f1"])
    ap.add_argument("--db", default=None)
    known, rest = ap.parse_known_args(argv)
    if not rest or rest[0] in ("-h", "--help") or rest[0] not in COMMANDS:
        print(__doc__)
        return 0 if rest and rest[0] in ("-h", "--help") else 2
    from . import f1
    return f1.main((["--db", known.db] if known.db else []) + [COMMANDS[rest[0]]] + rest[1:])
