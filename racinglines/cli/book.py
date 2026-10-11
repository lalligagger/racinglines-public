"""
racinglines book <command> FILE [options]: generic sportsbook lines and slips against our model and the prediction
markets (racinglines/books/slips.py, docs/sportsbook/slips.md). CLI only, outside the web app; read-only on the
database.

    map      resolve every line's legs to a race, athletes and a kind by exact keys; list what stays unmapped
    price    + the model's fair, the linked exchange price, the book's implied probability, EV against each
    settle   + each leg's and line's result from the stored classification, and the payout per unit staked
    view     render a saved --json result of map, price or settle with Rich (no database)
    logout   forget the browser sign-in that --remote keeps
    config   show or set the CLI's defaults (racinglines/cli/config.py): `config`, `config KEY VALUE`, `config KEY --unset`

Where the data comes from (map, price, settle), three modes; the default is the defaults file's `source`, else local:
    --local                a local database (--db, else DATABASE_URL, else the defaults file's `db`): you rebuild the
                           data or run the app and its MCP server yourself
    --demo                 no database, no network, no account: the bundled synthetic sample book
                           (racinglines/books/demo/) and its stored results; FILE is left out. Rich by default
    --remote               the VM's hosted MCP server (racinglines/cli/remote.py): live model runs and exchange prices.
                           Signs in through the browser the first time (kept in ~/.config/racinglines/mcp-login.json),
                           or uses RACINGLINES_MCP_TOKEN (an rl_ token) when set. --mcp-url URL, RACINGLINES_MCP_URL or
                           the defaults file's `mcp_url` point it at your own server (default
                           https://mcp.racinglines.bet/mcp)

Options (map, price, settle):
    --json                 the whole result as JSON (stable keys: docs/sportsbook/slips.md#json-output)
    --rich                 a coloured terminal table (Rich; racinglines/cli/rich_view.py) instead of plain text
    --db URL               the database (default DATABASE_URL)
price only:
    --run ID               price legs of that run's competition from it (repeatable; default: the app's own choice
                           per race, markets/venues.pricing_run)
    --sims RACE_ID=FILE    an OutcomeSims archive (.npz, models/outcomes.save_sims) for a race: legs on that race are
                           priced jointly from it (repeatable)
"""

import argparse
import importlib.util
import json
import os
import sys

import pandas as pd


def _parser():
    p = argparse.ArgumentParser(prog="racinglines book", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    top = p.add_mutually_exclusive_group()                 # also before the command: `book --demo price`
    for flag in ("demo", "remote", "local"):
        top.add_argument(f"--{flag}", dest=f"top_{flag}", action="store_true", help=f"as `--{flag}` after the command")
    p.add_argument("--mcp-url", dest="top_mcp_url", default=None, help="as `--mcp-url` after the command")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, hlp in (("map", "Resolve each line's legs by exact keys."),
                      ("price", "Model fair, market price, book implied probability and EV per leg and per slip."),
                      ("settle", "Results and payouts from the stored classification.")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("file", nargs="?", help="a book file (books/<venue>/<date>-<event>.toml, "
                                               "docs/sportsbook/index.md); left out with --demo")
        s.add_argument("--json", action="store_true", help="print the result as JSON")
        s.add_argument("--rich", action="store_true", help="print a coloured terminal table (Rich)")
        s.add_argument("--db", default=None, help="database URL (default DATABASE_URL)")
        mode = s.add_mutually_exclusive_group()
        mode.add_argument("--demo", action="store_true",
                          help="the bundled synthetic sample and its stored results: no database, network or account")
        mode.add_argument("--remote", action="store_true",
                          help="the VM's hosted MCP server: browser sign-in, or RACINGLINES_MCP_TOKEN")
        mode.add_argument("--local", action="store_true", help="a local database (the default unless the defaults "
                                                               "file says otherwise)")
        s.add_argument("--mcp-url", default=None, help="the hosted server for --remote (default RACINGLINES_MCP_URL, "
                                                       "else https://mcp.racinglines.bet/mcp)")
        if name == "price":
            s.add_argument("--run", type=int, action="append", default=[], help="a model run id (repeatable)")
            s.add_argument("--sims", action="append", default=[], metavar="RACE_ID=FILE",
                           help="simulations for one race, for joint same-race pricing (repeatable)")
    v = sub.add_parser("view", help="Render a saved --json result with Rich (no database).")
    v.add_argument("file", help="the JSON a map, price or settle --json printed ('-' for stdin)")
    lo = sub.add_parser("logout", help="Forget the browser sign-in --remote keeps.")
    lo.add_argument("--mcp-url", default=None, help="only this server's sign-in (default: every server's)")
    cf = sub.add_parser("config", help="Show or set the CLI's defaults (source, mcp_url, db).")
    cf.add_argument("key", nargs="?", help="source (local / remote / demo), mcp_url or db")
    cf.add_argument("value", nargs="?")
    cf.add_argument("--unset", action="store_true", help="remove KEY")
    return p


def _config(C, args):
    if args.key is None:
        data = C.load()
        print(f"# {C.path()}" + ("" if data else " (none: every default applies)"))
        for k in C.KEYS:
            if k in data:
                print(f"{k} = {'<set>' if k == 'db' else data[k]}")       # a db URL can carry a password
        return 0
    if not args.unset and args.value is None:
        print(f"book config {args.key}: give a VALUE, or --unset", file=sys.stderr)
        return 2
    C.set_key(args.key, None if args.unset else args.value)
    print(f"{'removed' if args.unset else 'set'} {args.key} in {C.path()}")
    return 0


def demo(cmd):
    """The bundled sample's stored result for `cmd` (racinglines/books/demo/<cmd>.json)."""
    from importlib.resources import files
    return json.loads((files("racinglines.books") / "demo" / f"{cmd}.json").read_text())


def _kind(out):
    """Which command made a result dict: price adds assumptions, settle adds a result to every leg."""
    if "assumptions" in out:
        return "price"
    return "settle" if any("result" in lg for r in out.get("lines", []) for lg in r.get("legs", [])) else "map"


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
    parser = _parser()
    args = parser.parse_args(argv)
    tops = [f for f in ("demo", "remote", "local") if getattr(args, f"top_{f}")]
    if tops and args.cmd not in ("map", "price", "settle"):
        parser.error(f"--{tops[0]} applies to map, price and settle")
    if tops:
        if any(getattr(args, f) for f in ("demo", "remote", "local") if f not in tops):
            parser.error("give one of --demo, --remote, --local")
        setattr(args, tops[0], True)
    if args.top_mcp_url and args.cmd in ("map", "price", "settle", "logout"):
        args.mcp_url = args.mcp_url or args.top_mcp_url
    if args.cmd == "view":
        from racinglines.cli import rich_view
        try:
            out = json.load(sys.stdin if args.file == "-" else open(args.file))
        except (OSError, ValueError) as e:
            print(f"book view: {e}", file=sys.stderr)
            return 2
        rich_view.render(_kind(out), out)
        return 0
    from racinglines.cli import config as C
    if args.cmd == "logout":
        from racinglines.cli import remote
        print("signed out" if remote.logout(args.mcp_url) else "no stored sign-in")
        return 0
    try:
        if args.cmd == "config":
            return _config(C, args)
        defaults = C.load()
    except ValueError as e:
        print(f"book: {e}", file=sys.stderr)
        return 2
    if not (args.demo or args.remote or args.local):
        source = defaults.get("source", "local")
        args.demo, args.remote = source == "demo", source == "remote"
    args.mcp_url = args.mcp_url or os.environ.get("RACINGLINES_MCP_URL") or defaults.get("mcp_url")
    if not args.db and not os.environ.get("DATABASE_URL"):
        args.db = defaults.get("db")
    local_only = getattr(args, "sims", None) or getattr(args, "run", None) or (args.db and args.db != defaults.get("db"))
    if args.demo:
        if args.file or local_only:
            print("book --demo: prices the bundled sample only; leave out FILE, --db, --run and --sims "
                  "(--remote prices your own book on the VM)", file=sys.stderr)
            return 2
        print("demo: the bundled synthetic sample (racinglines/books/demo/book.toml): made-up names and prices, "
              "no database or network", file=sys.stderr)
        out = demo(args.cmd)
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        elif importlib.util.find_spec("rich"):
            from racinglines.cli import rich_view
            rich_view.render(args.cmd, out)
        else:                                              # the demo still works before `pip install -r requirements.txt`
            print("(plain text: pip install rich for the coloured tables)", file=sys.stderr)
            _print(args.cmd, out)
        return 0
    if not args.file:
        print(f"book {args.cmd}: a book FILE is needed (or --demo for the bundled sample)", file=sys.stderr)
        return 2
    from racinglines.books import schema as S
    from racinglines.books import slips as B
    from racinglines.db.config import get_engine
    try:
        book = B.load_file(args.file)
    except (S.BookError, OSError) as e:
        print(f"book: {e}", file=sys.stderr)
        return 2
    if args.remote:
        from racinglines.cli import remote
        if (args.db and args.db != defaults.get("db")) or getattr(args, "sims", None):
            print("book --remote: runs on the hosted server; --db and --sims are local only", file=sys.stderr)
            return 2
        try:
            out = remote.run(args.cmd, open(args.file).read(), args.mcp_url, getattr(args, "run", ()))
        except remote.RemoteError as e:
            print(f"book --remote: {e}", file=sys.stderr)
            return 2
    else:
        with get_engine(args.db).connect() as conn:
            out = run(args.cmd, book, conn, getattr(args, "run", ()), getattr(args, "sims", ()))
            conn.rollback()
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    elif args.rich:
        from racinglines.cli import rich_view
        rich_view.render(args.cmd, out)
    else:
        _print(args.cmd, out)
    return 0
