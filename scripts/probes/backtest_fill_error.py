"""How far the taker backtest's fill prices are from what Probalytics' book says the order would really have paid. Read-only;
run on the VM, where our tape is (the database plus data/archive/markets), with Probalytics' stage files under
$RACINGLINES_DATA/probalytics/stages/ (every level of each market's book at each stage cutoff).

For every F1 market at every stage cutoff of a 2026 weekend, on each venue:

  ours   the price the taker backtest fills at today (markets/strategies/taker_weekend.py, on our tape): the whole
         order at one price. Kalshi: buy YES at our ask, NO at 1 - our bid. Polymarket: buy YES at our 5-minute price,
         NO at 1 - it. Plus the cost per share (the `cost` setting, default 1 cent) and the venue's taker fee.
  truth  the same order walked level by level through Probalytics' full book at that second (YES at their asks, NO
         at 1 - their bids), plus the same taker fee and no cost per share: the walk is the spread and the slippage.

  error  (ours - truth) / truth, in %: positive = the backtest paid more than the book asked (pessimistic), negative =
         it paid less (optimistic). Reported for orders of each --stakes dollar size (default $10, $50 = the default
         max_stake, $200), per venue, stage and price band, with the orders the book could not fill in full.

Every (market, stage) where our tape prices a buy inside the price band counts, not only the trades a strategy picked:
the test is of the fill model, not of a strategy. It covers every 2026 weekend Probalytics has stage files for
(Polymarket all season, Kalshi from round 5). scripts/probes/fill_error.py (#201) is its partner for live fantasy
orders: that walk on our recorded books against theirs, since 2026-09-30.

    # VM (a transient unit, on the season demo database; see GOLDEN-RUN-STEPS.md for the wrapper)
    .venv/bin/python scripts/probes/backtest_fill_error.py --year 2026

Writes data/runs/backtest-fill-error/<UTC>/ (rows.parquet, summary.json, SUMMARY.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

VENUES = ("polymarket", "kalshi")
STAKES = (10.0, 50.0, 200.0)
BAND = (0.02, 0.98)
PRICE_BANDS = [(0.0, 0.10), (0.10, 0.30), (0.30, 0.70), (0.70, 1.0)]


def say(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def walk_vwap(levels, shares):
    """(average price, shares filled) of buying `shares` through best-first [(price, size)] levels, all of them."""
    left, paid = float(shares), 0.0
    for p, s in levels:
        take = min(left, float(s))
        if take <= 0:
            continue
        paid += take * float(p)
        left -= take
        if left <= 1e-9:
            break
    filled = float(shares) - max(left, 0.0)
    return (paid / filled if filled > 0 else None), filled


def no_levels(bids):
    """A YES book's bids as the NO side's asks: buying NO at 1 - each bid, best (highest bid) first."""
    return [(1.0 - p, s) for p, s in bids]


def fee_per_share(rate, px, shares):
    from racinglines.markets.strategies.taker_weekend import _fee
    return _fee(rate, px, shares)


def order_rows(ours_px, book, side, stake, cost, fee_rate):
    """One order of `stake` dollars on `side` (YES/NO) at our price ours_px against the book (dict(bids, asks)):
    ours (exec price as the backtest fills it), truth (the walk's average plus the fee), filled share, error %."""
    shares = stake / ours_px
    ours = ours_px + cost + fee_per_share(fee_rate, ours_px, shares)
    levels = book["asks"] if side == "YES" else no_levels(book["bids"])
    vwap, filled = walk_vwap(levels, shares)
    truth = None if vwap is None else vwap + fee_per_share(fee_rate, vwap, filled)
    err = None if truth is None or truth <= 0 else (ours - truth) / truth * 100
    return dict(side=side, stake=stake, shares=shares, ours=ours, truth=truth, touch=levels[0][0] if levels else None,
                filled=filled / shares if shares else None, full=bool(vwap is not None and filled >= shares - 1e-6),
                err_pct=err)


def weekend_rows(conn, w, venue, stakes, cost):
    from racinglines.markets import probalytics as PB
    from racinglines.pipelines import weekend_sweep as W
    rid = W._race_id(conn, w["event_key"])
    links = W._links(conn, rid, venue) if rid is not None else []
    if not len(links):
        return []
    start, end = w["stages"][0][1] - timedelta(hours=1), w["race_start"]
    ours = W._exchange(venue)(conn, links, start, end, W.GROUP_TARGET, W.COHERENCE_TOL, W.STALE)
    theirs = PB.EXCHANGES[venue](conn, links, start, end, W.GROUP_TARGET, W.COHERENCE_TOL, event_key=w["event_key"],
                                 levels=True)
    rate = W.taker_fee(venue)
    c = W.taker_cost(cost, venue)
    rows = []
    for lab, t in w["stages"]:
        for m in links.to_dict("records"):
            tok = m["token_id"]
            q = ours.quote(tok, t)
            p = ours.price(tok, t)
            if q is not None:
                buy = {"YES": q[1], "NO": 1 - q[0]}
            elif p is not None:
                buy = {"YES": p, "NO": 1 - p}
            else:
                continue
            book = theirs.book_at(tok, t)
            for side, px in buy.items():
                if not BAND[0] <= px <= BAND[1]:
                    continue
                base = dict(event=w["event_key"], venue=venue, stage=lab, t=t, token=tok, kind=m["prediction"],
                            ours_px=px, quoted=q is not None, book=book is not None)
                if book is None or not (book["asks"] if side == "YES" else book["bids"]):
                    rows += [dict(base, side=side, stake=s) for s in stakes]
                    continue
                rows += [dict(base, **order_rows(px, book, side, s, c, rate)) for s in stakes]
    return rows


def band_of(px):
    for lo, hi in PRICE_BANDS:
        if lo <= px < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return "other"


def stats(g):
    e = pd.to_numeric(g["err_pct"], errors="coerce").dropna()
    full = g["full"].fillna(False).astype(bool) if "full" in g else pd.Series(dtype=bool)
    return dict(orders=int(len(g)), with_book=int(g["book"].sum()), compared=int(len(e)),
                median_err_pct=float(e.median()) if len(e) else None,
                mean_err_pct=float(e.mean()) if len(e) else None,
                median_abs_err_pct=float(e.abs().median()) if len(e) else None,
                p90_abs_err_pct=float(e.abs().quantile(0.9)) if len(e) else None,
                within_1pct=float((e.abs() <= 1).mean()) if len(e) else None,
                optimistic=float((e < -1e-9).mean()) if len(e) else None,
                not_full=int((~full[g["book"].astype(bool)]).sum()) if len(full) else 0)


def summarize(df):
    out = {}
    for (v, s), g in df.groupby(["venue", "stake"]):
        key = f"{v} ${s:.0f}"
        out[key] = dict(all=stats(g),
                        by_stage={k: stats(x) for k, x in g.groupby("stage", sort=False)},
                        by_band={k: stats(x) for k, x in g.groupby(g["ours_px"].map(band_of))},
                        by_side={k: stats(x) for k, x in g.groupby("side")})
    return out


def fmt(x, pct=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"{x:.1%}" if pct else f"{x:+.2f}"


def markdown(summary, args):
    lines = [f"# Fill-price error: our tape and fill logic against Probalytics' book ({args.year})", "",
             "error = (our backtest's fill price - the order walked through Probalytics' book at that second) / that, "
             "in %. Positive = the backtest paid more than the book asked (pessimistic); negative = it paid less "
             "(optimistic). Every market and stage our tape prices, both sides, not only the trades a strategy took.",
             "", "| venue, order | orders | compared | median err % | mean err % | median abs % | p90 abs % | "
             "within 1% | optimistic | not filled in full |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, s in summary.items():
        a = s["all"]
        lines.append(f"| {k} | {a['orders']} | {a['compared']} | {fmt(a['median_err_pct'])} | {fmt(a['mean_err_pct'])} "
                     f"| {fmt(a['median_abs_err_pct'])} | {fmt(a['p90_abs_err_pct'])} | {fmt(a['within_1pct'], True)} "
                     f"| {fmt(a['optimistic'], True)} | {a['not_full']} |")
    for k, s in summary.items():
        for part in ("by_stage", "by_band", "by_side"):
            lines += ["", f"## {k}, {part.replace('_', ' ')}", "",
                      "| | compared | median err % | median abs % | p90 abs % | within 1% | not full |",
                      "|---|---|---|---|---|---|---|"]
            for name, a in s[part].items():
                lines.append(f"| {name} | {a['compared']} | {fmt(a['median_err_pct'])} | {fmt(a['median_abs_err_pct'])} "
                             f"| {fmt(a['p90_abs_err_pct'])} | {fmt(a['within_1pct'], True)} | {a['not_full']} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--rounds", default=None, help="e.g. 5-17 (default: every completed round)")
    ap.add_argument("--stakes", default=",".join(f"{s:g}" for s in STAKES), help="order sizes in $, comma separated")
    ap.add_argument("--cost", type=float, default=0.01, help="the backtest's cost per share (the `cost` setting)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--day-books", action="store_true",
                    help="read Probalytics' day files where present (default: the stage files only, which hold the "
                         "same book at each stage cutoff, so the VM never loads a race day's levels or pulls from the bucket)")
    a = ap.parse_args()
    from racinglines import progress as PG
    from racinglines.db.config import get_engine
    from racinglines.pipelines import weekend_sweep as W
    from racinglines.paths import DATA
    stakes = [float(x) for x in a.stakes.split(",") if x.strip()]
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    rounds = None
    if a.rounds:
        lo, _, hi = a.rounds.partition("-")
        rounds = set(range(int(lo), int(hi or lo) + 1))
    weekends = [w for w in W.schedule(a.year, rounds).values() if w["race_start"] < now]
    out = Path(a.out or DATA / "runs" / "backtest-fill-error" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    out.mkdir(parents=True, exist_ok=True)
    if not a.day_books:                                  # a data root holding only the stage files
        import os

        from racinglines.markets import probalytics as PB
        only = out / "probalytics-stages"
        only.mkdir(exist_ok=True)
        if not (only / "stages").exists():
            (only / "stages").symlink_to(PB.root().resolve() / "stages")
        os.environ["PROBALYTICS_DATA"] = str(only)
        os.environ.pop("PROBALYTICS_BUCKET", None)
    rows = []
    with get_engine().connect() as conn:
        for w in PG.track(weekends, "fill error", name=lambda x: x["event_key"]):
            for v in VENUES:
                r = weekend_rows(conn, w, v, stakes, a.cost)
                say(f"{w['event_key']} {v}: {len(r)} orders")
                rows += r
    df = pd.DataFrame(rows)
    if not len(df):
        say("no orders: nothing to compare")
        return 1
    df.to_parquet(out / "rows.parquet", index=False)
    summary = summarize(df)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    md = markdown(summary, a)
    (out / "SUMMARY.md").write_text(md)
    print(md)
    say(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
