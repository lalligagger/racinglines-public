"""
racinglines book <command> FILE [options]: generic sportsbook lines and slips against our model and the prediction
markets (racinglines/books/slips.py, docs/sportsbook/slips.md). CLI only, outside the web app; read-only on the
database.

    map      resolve every line's legs to a race, athletes and a kind by exact keys; list what stays unmapped
    price    + the model's fair, the linked exchange price, the book's implied probability, EV against each
    settle   + each leg's and line's result from the stored classification, and the payout per unit staked
    render   one HTML page (and --png) of the priced board: hud (on the book's screenshot), card, or agnostic (model
             and exchanges only), with stakes from markets/books.toml (docs/sportsbook/render.md)
    new      a book file draft from loose text ("A over B 1.57", "A vs B 1.57 2.25", "Name 4.35"): --from-text

Options (every command):
    --json                 the whole result as JSON (stable keys: docs/sportsbook/slips.md#json-output)
    --db URL               the database (default DATABASE_URL)
price only:
    --run ID               price legs of that run's competition from it (repeatable; default: the app's own choice
                           per race, markets/venues.pricing_run)
    --sims RACE_ID=FILE    an OutcomeSims archive (.npz, models/outcomes.save_sims) for a race: legs on that race are
                           priced jointly from it (repeatable)
render (FILE = a book file, priced like `price`; or a cycling price output folder or CSV; or leave it out with
--json-in):
    --style hud|card|agnostic   --image PNG   --out PATH.html   --png   --chrome PATH   --json-in PRICED.json
    --bank --kelly --cap --min-ev --scale --drop-under    override markets/books.toml [stake]
new:
    --from-text TXT --venue CODE --event KEY --odds FORMAT --out FILE.toml [--sport CODE] [--currency USD]
"""

import argparse
import json
import sys

import pandas as pd


def _parser():
    p = argparse.ArgumentParser(prog="racinglines book", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="An HTML page (and PNG) of the priced board: hud, card or agnostic.")
    r.add_argument("file", nargs="?", help="a book file, or a cycling price output folder / futures.csv / matchups.csv")
    r.add_argument("--style", choices=("hud", "card", "agnostic"), default="card")
    r.add_argument("--image", help="the book's screenshot (hud; default: [book] image in the book file)")
    r.add_argument("--out", help="the HTML file (default: <file stem>-<style>.html next to the input)")
    r.add_argument("--png", action="store_true", help="also write a PNG beside the HTML (needs a Chromium)")
    r.add_argument("--chrome", help="the Chromium to use (default: $RACINGLINES_CHROME, then PATH, then Playwright's)")
    r.add_argument("--json-in", help="a saved `book price --json` result: render without a database")
    r.add_argument("--db", default=None, help="database URL (default DATABASE_URL)")
    r.add_argument("--run", type=int, action="append", default=[], help="a model run id (repeatable)")
    for opt, hlp in (("bank", "bank in $"), ("kelly", "Kelly fraction"), ("cap", "per venue per event cap in $"),
                     ("min-ev", "minimum EV against each required price"), ("scale", "multiply every stake"),
                     ("drop-under", "drop stakes under this, after --scale")):
        r.add_argument(f"--{opt}", type=float, default=None, help=hlp + " (default: markets/books.toml [stake])")
    n = sub.add_parser("new", help="A book file draft from loose text lines.")
    n.add_argument("--from-text", required=True, help="a text file, one bet per line ('-' for stdin)")
    n.add_argument("--venue", required=True, help="the venue code, e.g. book_a")
    n.add_argument("--event", required=True, help="the event key, e.g. 2026-17")
    n.add_argument("--odds", default="decimal", choices=("decimal", "american", "fractional", "cents", "dollars", "prob"))
    n.add_argument("--sport", help="[book] sport (sports/<code>.toml)")
    n.add_argument("--currency", default="USD")
    n.add_argument("--out", required=True, help="the book file to write (refuses to overwrite)")
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


def _render(args):
    from pathlib import Path

    from racinglines.books import render as R
    from racinglines.books import slips as B
    overrides = {k.replace("-", "_"): getattr(args, k.replace("-", "_"))
                 for k in ("bank", "kelly", "cap", "min-ev", "scale", "drop-under")}
    st = R.load_settings(overrides)
    src = Path(args.file) if args.file else None
    book = None
    if src is not None and (src.is_dir() or src.suffix == ".csv"):
        meta, rows = R.rows_from_cycling(src)
    else:
        if src is not None and src.suffix == ".json" and not args.json_in:
            args.json_in, src = str(src), None
        if src is not None:
            book = B.load_file(src)
        if args.json_in:
            priced = json.loads(Path(args.json_in).read_text())
        elif book is not None:
            from racinglines.db.config import get_engine
            with get_engine(args.db).connect() as conn:
                priced = run("price", book, conn, args.run)
                conn.rollback()
        else:
            raise R.RenderError("give a book file, a cycling price output, or --json-in PRICED.json")
        meta, rows = R.rows_from_priced(priced, st, book)
    image = args.image
    if image is None and meta.get("image") and src is not None:
        image = str((src.parent / meta["image"]))
    stem = (src or Path(args.json_in)).resolve()
    out = Path(args.out) if args.out else stem.parent / f"{stem.stem}-{args.style}.html"
    page, sized, summary = R.render(meta, rows, args.style, st, image)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"wrote {out}")
    if args.style != "agnostic":
        for r in sized:
            if r["verdict"] == "BET":
                print(f"  BET ${r['stake']:7.2f}  {r['selection']}" + (f" over {r['opponent']}" if r["opponent"] else "")
                      + f" @ {r['decimal_odds']:.2f}")
        print(f"  {summary['n_bets']} bets, ${summary['total']:.2f}" + (" (scaled to the cap)" if summary["capped"] else ""))
    if args.png:
        png = R.to_png(out, out.with_suffix(".png"), args.chrome, st["render"]["dpr"][args.style])
        print(f"wrote {png}")
    return 0


def _new(args):
    import sys as _sys
    from pathlib import Path

    from racinglines.books import render as R
    text = _sys.stdin.read() if args.from_text == "-" else Path(args.from_text).read_text()
    lines, bad = R.parse_text(text, args.odds)
    out = Path(args.out)
    if out.exists():
        raise R.RenderError(f"{out} exists: not overwritten")
    if not lines:
        raise R.RenderError("no line parsed: " + "; ".join(f"line {n}: {s!r} ({why})" for n, s, why in bad))
    out.write_text(R.book_toml(lines, bad, args.venue, args.event, args.odds, args.sport, args.currency,
                               source_ref=f"from {args.from_text}"))
    print(f"wrote {out}: {len(lines)} lines, every market \"unmapped\" (write the market tables, then `book map`)")
    for n, s, why in bad:
        print(f"  not parsed, line {n}: {s!r} ({why})")
    return 0


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.cmd in ("render", "new"):
        from racinglines.books import render as R
        from racinglines.books import schema as S
        try:
            return _render(args) if args.cmd == "render" else _new(args)
        except (R.RenderError, S.BookError, OSError) as e:
            print(f"book {args.cmd}: {e}", file=sys.stderr)
            return 2
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
