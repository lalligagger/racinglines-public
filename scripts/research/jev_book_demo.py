#!/usr/bin/env python3
"""LOCAL (Mac): layered Jev decision chain on sportsbook lines (paper, in-sample demo).

Inputs, either:
  --priced PRICED.json [--settled SETTLED.json]   outputs of `racinglines book price|settle FILE --json`
  --book FILE --asof UTC [--db URL]               prices as of `asof` and settles, read-only, from the local database
Exchange price: --pm-trades TRADES.csv (token_id,ts,price,...) fills each line's Polymarket price from the last trade
at or before `asof`; --no-pm drops the exchange price entirely (Jev sees fair and the line only). Both need --book.

Examples:
  .venv/bin/python scripts/research/jev_book_demo.py --priced p.json --settled s.json --dry-run
  TYPESAFE_API_KEY=... .venv/bin/python scripts/research/jev_book_demo.py --priced p.json --settled s.json --out data/runs/jev_book_demo/run1

--dry-run prints the plan and writes nothing. A real run makes Jev calls (cached on disk, so interrupting and
rerunning resumes) up to --budget calls (default 200); the budget is counted before each call.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from racinglines.research import jev_book_demo as D


def _load(args):
    if args.priced:
        priced = json.loads(Path(args.priced).read_text())
        settled = json.loads(Path(args.settled).read_text()) if args.settled else None
        return priced, settled
    import csv
    from racinglines.books import slips as B
    from racinglines.db.config import get_engine
    from racinglines.research.jev_book_demo import fill_pm
    trades = list(csv.DictReader(open(args.pm_trades))) if args.pm_trades else None
    priced, settled = {"lines": []}, {"lines": []}
    with get_engine(args.db).connect() as conn:
        B.readonly(conn)
        for i, path in enumerate(args.book):
            book = B.load_file(path)
            p = B.price_book(conn, book, asof=args.asof)
            if trades is not None:
                p, n = fill_pm(p, B.price_book(conn, book), trades, args.asof)
                print(f"{path}: exchange price filled for {n} lines", file=sys.stderr)
            s = B.settle_book(conn, book)
            for r in p["lines"] + s["lines"]:
                r["id"] = f"{i + 1}-{r.get('id') or r.get('line')}" if len(args.book) > 1 else r.get("id") or r.get("line")
            priced["lines"] += p["lines"]
            settled["lines"] += s["lines"]
        conn.rollback()
    return priced, settled


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--priced")
    src.add_argument("--book", nargs="+")
    ap.add_argument("--settled")
    ap.add_argument("--asof")
    ap.add_argument("--db")
    ap.add_argument("--pm-trades", help="CSV of Polymarket trades; the last one by --asof is the exchange price")
    ap.add_argument("--no-pm", action="store_true", help="Jev sees our fair price and the line only")
    ap.add_argument("--out", help="directory for report.md and result.json (omit to print only)")
    ap.add_argument("--model", default=D.DEFAULT_MODEL)
    ap.add_argument("--budget", type=int, default=D.DEFAULT_BUDGET, help="max Jev API calls")
    ap.add_argument("--min-noul", type=float, default=D.MIN_NOUL)
    ap.add_argument("--min-conf", type=float, default=D.MIN_CONF)
    ap.add_argument("--cache-dir", default=str(D.CACHE_DIR))
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit; no calls, no writes")
    args = ap.parse_args(argv)
    if (args.pm_trades or args.no_pm) and not args.book:
        ap.error("--pm-trades and --no-pm need --book (and --asof)")
    if args.pm_trades and args.no_pm:
        ap.error("--pm-trades and --no-pm are exclusive")
    if args.book and not args.asof:
        ap.error("--book needs --asof (leakage-safe pricing)")
    if args.budget < 0:
        ap.error("--budget must be >= 0")
    priced, settled = _load(args)
    if args.no_pm:
        for r in priced["lines"]:
            r["market_prob"] = None
    if args.dry_run:
        print(json.dumps(D.plan(priced, args.model, args.cache_dir, args.budget, need_pm=not args.no_pm), indent=2))
        return 0
    client = None
    if args.budget > 0:
        from racinglines.research.jev_gate import make_client
        try:
            client = make_client()
        except RuntimeError as e:
            ap.error(f"{e}; set it, or use --budget 0 for cache-only")
    ask = D.Asker(client, args.model, args.cache_dir, args.budget)
    res = D.run(priced, settled, ask, args.min_noul, args.min_conf, need_pm=not args.no_pm)
    res["calls"], res["cache_hits"] = ask.calls, ask.hits
    report = D.format_report(res)
    print(report)
    print(f"calls {ask.calls}, cache hits {ask.hits}", file=sys.stderr)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.md").write_text(report)
        (out / "result.json").write_text(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
