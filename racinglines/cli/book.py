"""
racinglines book <command> FILE [options]: generic sportsbook lines and slips against our model and the prediction
markets (racinglines/books/slips.py, docs/sportsbook/slips.md). CLI only, outside the web app; read-only on the
database.

    map      resolve every line's legs to a race, athletes and a kind by exact keys; list what stays unmapped
    price    + the model's fair, the linked exchange price, the book's implied probability, EV against each
    settle   + each leg's and line's result from the stored classification, and the payout per unit staked

Options (every command):
    --json                 the whole result as JSON (stable keys: docs/sportsbook/slips.md#json-output)
    --db URL               the database (default DATABASE_URL)
price only:
    --run ID               price legs of that run's competition from it (repeatable; default: the app's own choice
                           per race, markets/venues.pricing_run)
    --sims RACE_ID=FILE    an OutcomeSims archive (.npz, models/outcomes.save_sims) for a race: legs on that race are
                           priced jointly from it (repeatable)
"""

import argparse
import json
import sys

import pandas as pd


def _parser():
    p = argparse.ArgumentParser(prog="racinglines book", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, hlp in (("map", "Resolve each line's legs by exact keys."),
                      ("price", "Model fair, market price, book implied probability and EV per leg and per slip."),
                      ("settle", "Results and payouts from the stored classification.")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("file", help="a book file (books/<venue>/<date>-<event>.toml, docs/sportsbook/index.md)")
        s.add_argument("--json", action="store_true", help="print the result as JSON")
        s.add_argument("--db", default=None, help="database URL (default DATABASE_URL)")
        if name == "price":
            s.add_argument("--run", type=int, action="append", default=[], help="a model run id (repeatable)")
            s.add_argument("--sims", action="append", default=[], metavar="RACE_ID=FILE",
                           help="simulations for one race, for joint same-race pricing (repeatable)")
    return p


def _sims(specs):
    from racinglines.models.outcomes import load_sims
    out = {}
    for spec in specs:
        rid, _, path = spec.partition("=")
        if not rid.isdigit() or not path:
            raise SystemExit(f"--sims {spec!r}: expected RACE_ID=FILE")
        out[int(rid)] = load_sims(path)
    return out


def _runs(conn, ids):
    from racinglines.db.reads import model_run
    out = {}
    for rid in ids:
        r = model_run(conn, rid)
        if r is None:
            raise SystemExit(f"--run {rid}: no such model run")
        out[rid] = r["competition"]
    return out


def run(cmd, book, conn, runs=(), sims=()):
    """The command's result dict (what --json prints)."""
    from racinglines.books import slips as B
    B.readonly(conn)
    if cmd == "map":
        return B.map_book(conn, book)
    if cmd == "price":
        return B.price_book(conn, book, runs=_runs(conn, runs), sims=_sims(sims))
    return B.settle_book(conn, book)


TEXT_COLUMNS = {
    "map": (["leg", "status", "sport", "event_key", "race_id", "kind", "side", "athlete", "opponent", "team",
             "threshold", "reason"], ["id", "title", "selection", "kind", "status", "n_legs", "odds", "reason"]),
    "price": (["leg", "sport", "event_key", "kind", "side", "athlete", "opponent", "team", "odds", "book_prob",
               "model_prob", "run_id", "market_prob", "market_exchange", "ev_model", "ev_market", "model_note"],
              ["id", "selection", "n_legs", "decimal_odds", "book_prob", "model_prob", "model_method", "market_prob",
               "ev_model", "ev_market", "flags"]),
    "settle": (["leg", "sport", "event_key", "kind", "side", "athlete", "opponent", "team", "result"],
               ["id", "selection", "n_legs", "decimal_odds", "result", "payout", "profit"]),
}


def _print(cmd, out):
    from racinglines.books import slips as B
    b = out["book"]
    print(f"{b['venue']} · event {b['event']} · captured {b['captured_utc']} · odds {b['odds']}")
    legs, lines = B.leg_table(out), B.line_table(out)
    lc, rc = TEXT_COLUMNS[cmd]
    with pd.option_context("display.width", 250, "display.max_columns", None, "display.max_colwidth", 80):
        if len(legs):
            print("\nLegs\n" + legs[[c for c in lc if c in legs]].to_string(index=False))
        print("\nLines\n" + lines[[c for c in rc if c in lines]].to_string(index=False))
    if out["unmapped"]:
        print(f"\nUnmapped lines: {', '.join(out['unmapped'])} (exact keys only: fix the book file or its [aliases])")
    if cmd == "price":
        print("\nAssumptions:\n" + "\n".join(f"  - {a}" for a in out["assumptions"]))


def main(argv=None):
    args = _parser().parse_args(argv)
    from racinglines.books import schema as S
    from racinglines.books import slips as B
    from racinglines.db.config import get_engine
    try:
        book = B.load_file(args.file)
    except (S.BookError, OSError) as e:
        print(f"book: {e}", file=sys.stderr)
        return 2
    with get_engine(args.db).connect() as conn:
        out = run(args.cmd, book, conn, getattr(args, "run", ()), getattr(args, "sims", ()))
        conn.rollback()
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        _print(args.cmd, out)
    return 0
