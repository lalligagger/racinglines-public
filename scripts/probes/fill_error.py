"""Fill-price error of the live fantasy fill logic: our recorded books against Probalytics' (owner, 2026-10-14: "a quick
test to show % error in fill prices using our existing fill logic, and our tapes vs. prob"). Read-only; run on the VM,
where our books are (since 2026-09-30, the database plus data/archive/markets), with Probalytics' day books in
data/probalytics/ or fetched from PROBALYTICS_BUCKET.

The baseline for the "old vs new" comparison: the logic is the same on both sides, only the tape differs.

    old    what a live fantasy order gets: our latest snapshot at or before t (refused when older than
           fantasy.exchange.MAX_AGE_MIN, 15 min), walked by fantasy.exchange.walk (DEPTH levels, whole shares,
           NO from the flipped YES book)
    truth  the same order walked against Probalytics' book at t (on-change snapshots: the book stands until the next)

Orders: buy YES and buy NO for F$10, F$50 and F$100 on every linked market of every weekend both tapes cover, at each
stage cutoff and at RANDOM_PER_WEEKEND random times between the first stage and the race (seeded). The order is set
from our book, as a player sees it: limit = best ask + 5 cents (capped at 0.99), shares = floor(stake / limit). When
our book is refused, the order is set from theirs, so the refusal is counted.

    # VM (a transient unit, read-only)
    sudo systemd-run --unit=rl-fill-error --uid=racinglines --working-directory=/opt/racinglines-staging \\
      --property=EnvironmentFile=/etc/racinglines-staging.env --setenv=PYTHONUNBUFFERED=1 \\
      --setenv=PROBALYTICS_BUCKET=gs://racinglines-data-384052502248/vendor/probalytics \\
      /opt/racinglines-staging/.venv/bin/python scripts/probes/fill_error.py --since 2026-09-20

Writes data/runs/fill-error/<UTC>/ (orders.parquet, summary.json, SUMMARY.md).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

STAKES = (10.0, 50.0, 100.0)
OFFSET = 0.05                  # the limit above the best ask
RANDOM_PER_WEEKEND = 150
VENUES = ("polymarket", "kalshi")


def say(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def vwap(fills):
    n = sum(s for _, s in fills)
    return (sum(p * s for p, s in fills) / n, n) if n else (None, 0)


def our_books(conn, venue, tokens, a, b):
    """{token: (ts index naive UTC, [bids], [asks])} from our recorded snapshots (the database and our archive)."""
    from racinglines.fantasy import exchange as EX
    from racinglines.markets import store as MS
    root = None if venue == "polymarket" else MS.root_for(venue)
    aa = pd.Timestamp(a).tz_localize("UTC") - timedelta(minutes=EX.MAX_AGE_MIN)
    bk = MS.read(conn, "books", tokens=list(tokens), start=aa, end=pd.Timestamp(b).tz_localize("UTC"), root=root)
    out = {}
    for tok, g in bk.groupby("token_id"):
        g = g.sort_values("ts")
        ts = pd.DatetimeIndex(pd.to_datetime(g["ts"], utc=True)).tz_localize(None)
        out[str(tok)] = (ts, [EX.levels(x) for x in g["bids"]], [EX.levels(x) for x in g["asks"]])
    return out


def our_book_at(books, tok, t):
    from racinglines.fantasy import exchange as EX
    b = books.get(tok)
    if b is None:
        return None, None
    ts, bids, asks = b
    i = ts.searchsorted(pd.Timestamp(t), side="right") - 1
    if i < 0:
        return None, None
    age = (pd.Timestamp(t) - ts[i]).total_seconds()
    if age > EX.MAX_AGE_MIN * 60:
        return None, age
    return (bids[i], asks[i]), age


def orders_for(conn, w, venue, rng):
    from racinglines.fantasy import exchange as EX
    from racinglines.markets import probalytics as PB
    from racinglines.pipelines import weekend_sweep as W
    rid = W._race_id(conn, w["event_key"])
    links = W._links(conn, rid, venue) if rid is not None else []
    if not len(links):
        return []
    start, end = w["stages"][0][1] - timedelta(hours=1), w["race_start"]
    toks = links["token_id"].astype(str).tolist()
    ours = our_books(conn, venue, toks, start, end)
    if not ours:
        return []
    theirs = PB.EXCHANGES[venue](conn, links, start, end, W.GROUP_TARGET, W.COHERENCE_TOL, event_key=w["event_key"],
                                 levels=True)
    span = (end - start).total_seconds()
    times = [(lab, t) for lab, t in w["stages"]] + \
        [("random", start + timedelta(seconds=float(x))) for x in rng.uniform(0, span, RANDOM_PER_WEEKEND)]
    rows = []
    for tok in toks:
        for kind, t in times:
            ob, age = our_book_at(ours, tok, t)
            tb = theirs.book_at(tok, t)
            for side in ("yes", "no"):
                o_asks = None if ob is None else (ob[1] if side == "yes" else EX.yes_to_no(*ob)[1])
                t_asks = None if tb is None else (tb["asks"] if side == "yes" else EX.yes_to_no(tb["bids"], tb["asks"])[1])
                ref = o_asks or t_asks                      # the order is set from our book; from theirs if ours is refused
                if not ref:
                    continue
                limit = min(0.99, round(ref[0][0] + OFFSET, 2))
                for stake in STAKES:
                    n = math.floor(stake / limit + 1e-9)
                    if n < 1:
                        continue
                    op, on = vwap(EX.walk(o_asks, n, limit)) if o_asks else (None, 0)
                    tp, tn = vwap(EX.walk(t_asks, n, limit)) if t_asks else (None, 0)
                    rows.append(dict(event=w["event_key"], venue=venue, token=tok, kind=kind, t=t, side=side,
                                     stake=stake, shares=n, limit=limit, our_age_s=age, ours_ok=o_asks is not None,
                                     theirs_ok=t_asks is not None, our_px=op, our_n=on, true_px=tp, true_n=tn))
    return rows


def summarize(df):
    out = {}
    for v, g in df.groupby("venue"):
        both = g[g["our_px"].notna() & g["true_px"].notna()]
        err = both["our_px"] - both["true_px"]
        pct = err / both["true_px"]
        s = dict(orders=len(g), both_filled=len(both),
                 ours_refused=int((~g["ours_ok"]).sum()), theirs_missing=int((~g["theirs_ok"]).sum()),
                 abs_err_cents_median=float(err.abs().median() * 100) if len(err) else None,
                 abs_err_cents_p90=float(err.abs().quantile(0.9) * 100) if len(err) else None,
                 abs_err_pct_median=float(pct.abs().median() * 100) if len(pct) else None,
                 abs_err_pct_p90=float(pct.abs().quantile(0.9) * 100) if len(pct) else None,
                 bias_cents_mean=float(err.mean() * 100) if len(err) else None,
                 share_within_1c=float((err.abs() <= 0.01 + 1e-9).mean()) if len(err) else None,
                 size_mismatch=float((both["our_n"] != both["true_n"]).mean()) if len(both) else None)
        if len(both):
            b = both.assign(err=err.abs() * 100, age_bucket=pd.cut(both["our_age_s"].fillna(0), [-1, 60, 300, 900],
                                                                   labels=["<1 min", "1-5 min", "5-15 min"]))
            s["abs_err_cents_median_by_our_age"] = b.groupby("age_bucket", observed=True)["err"].median().round(2).to_dict()
            s["abs_err_cents_median_by_stage"] = b.groupby("kind")["err"].median().round(2).to_dict()
            s["abs_err_cents_median_by_stake"] = b.groupby("stake")["err"].median().round(2).to_dict()
            s["share_within_1c_by_event"] = b.groupby("event")["err"].apply(lambda x: float((x <= 1.0001).mean())).round(3).to_dict()
        out[v] = s
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--since", default="2026-09-20", help="weekends from this date (our books start 2026-09-30)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    from racinglines.db.config import get_engine
    from racinglines.paths import DATA
    from racinglines.pipelines import weekend_sweep as W
    out = Path(a.out or DATA / "runs" / "fill-error" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    out.mkdir(parents=True, exist_ok=True)
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    weekends = [w for w in W.schedule(a.year).values() if pd.Timestamp(a.since) <= w["race_start"] < now]
    rng = np.random.default_rng(a.seed)
    rows = []
    with get_engine().connect() as conn:
        for i, w in enumerate(weekends, 1):
            for v in VENUES:
                rows += orders_for(conn, w, v, rng)
            say(f"progress fill_error: weekend {i} of {len(weekends)} ({w['event_key']} {w['name']}), {len(rows)} orders")
    df = pd.DataFrame(rows)
    df.to_parquet(out / "orders.parquet")
    summ = summarize(df) if len(df) else {}
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    lines = [f"# Fill-price error: our books vs Probalytics', live fantasy logic ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)",
             "", f"Weekends since {a.since}: {', '.join(w['event_key'] for w in weekends)}. Orders: buy YES / NO, "
             f"F$ {', '.join(str(int(x)) for x in STAKES)}, limit best ask + {OFFSET:.2f}, at the stage cutoffs and "
             f"{RANDOM_PER_WEEKEND} random times per weekend (seed {a.seed}).", ""]
    for v, s in summ.items():
        lines += [f"## {v}", ""] + [f"- {k}: {x}" for k, x in s.items()] + [""]
    (out / "SUMMARY.md").write_text("\n".join(lines))
    print("\n".join(lines), flush=True)
    say(f"done -> {out}")


if __name__ == "__main__":
    main()
