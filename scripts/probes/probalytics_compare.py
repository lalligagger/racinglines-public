"""Our recorded tape against Probalytics', market by market, for the 2026 F1 weekends. Read-only; run on the VM, where
our tape is (the database plus data/archive/markets), with Probalytics' files under $RACINGLINES_DATA/probalytics/
(scripts/probes/probalytics_pull.py writes them on the Mac; copy stages/, fills/ and any books/ days across).

Three checks, each against the owner's thresholds (2026-10-13, proposed and taken as the default on "go"):

  stages  at every stage cutoff the sweep reads, per market: our price (Polymarket's 5-minute price history; Kalshi's
          quote) against their book's mid, both as the backtest venue gives them (markets/probalytics.py).
          Pass: |our price - their mid| <= 1 cent on at least 95% of the markets both price.
  trades  per weekend and venue: our tape's trade count against their fill count over the weekend window.
          Pass: within 5% (reported per weekend; a weekend outside is listed).
  books   where we recorded books (since 2026-09-30) and their day files were pulled: at each of our snapshots, our
          best bid / ask against their last book at or before it. Pass: mid within 1 cent on at least 95%.

The sweep's own check (each weekend's P&L within 10% or $5) is the golden re-run: the same queue twice, the second
with RACINGLINES_TAPE_SOURCE=probalytics, compared by scripts/probes/probalytics_compare.py --results A B.

    # VM (a transient unit)
    sudo systemd-run --unit=rl-pb-compare --uid=racinglines --setenv=PYTHONUNBUFFERED=1 \\
      --working-directory=/opt/racinglines-staging --property=EnvironmentFile=/etc/racinglines-staging.env \\
      /opt/racinglines-staging/.venv/bin/python scripts/probes/probalytics_compare.py --year 2026
    # the two golden runs' per-weekend P&L
    .venv/bin/python scripts/probes/probalytics_compare.py --results data/runs/search/golden-ours-2026 \\
      data/runs/search/golden-probalytics-2026

Writes data/runs/probalytics-compare/<UTC>/ (rows.parquet, summary.json, SUMMARY.md).
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

PRICE_TOL = 0.01
SHARE_MIN = 0.95
TRADES_TOL = 0.05
PNL_TOL, PNL_FLOOR = 0.10, 5.0
VENUES = ("polymarket", "kalshi")


def say(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def stage_rows(conn, w, venue):
    from racinglines.markets import probalytics as PB
    from racinglines.pipelines import weekend_sweep as W
    stage_rows.venue = None
    rid = W._race_id(conn, w["event_key"])
    links = W._links(conn, rid, venue) if rid is not None else []
    if not len(links):
        return [], {}
    start = w["stages"][0][1] - timedelta(hours=1)
    end = w["race_start"]
    ours = W._exchange(venue)(conn, links, start, end, W.GROUP_TARGET, W.COHERENCE_TOL, W.STALE)
    theirs = PB.EXCHANGES[venue](conn, links, start, end, W.GROUP_TARGET, W.COHERENCE_TOL, event_key=w["event_key"])
    vk = ours.MARKET_KEY if venue == "kalshi" else "condition_id"
    rows = []
    stage_rows.venue = theirs                             # book_rows reuses it: one load of their books per weekend
    for lab, t in w["stages"]:
        for m in links.to_dict("records"):
            tok = m["token_id"]
            oq, tq = ours.quote(tok, t), theirs.quote(tok, t)
            rows.append(dict(event=w["event_key"], venue=venue, stage=lab, t=t, token=tok, kind=m["prediction"],
                             ours=ours.price(tok, t), theirs=theirs.price(tok, t),
                             ours_bid=oq[0] if oq else None, ours_ask=oq[1] if oq else None,
                             theirs_bid=tq[0] if tq else None, theirs_ask=tq[1] if tq else None,
                             ours_vol=ours.volume_24h(m[vk], t), theirs_vol=theirs.volume_24h(m[vk], t)))
    # trades over the weekend window: our tape's rows against their fills
    n_ours = sum(len(g[(g["ts"] >= start) & (g["ts"] <= end)]) for g in ours.trades.values())
    n_theirs = sum(len(g[(g["ts"] >= start) & (g["ts"] <= end)]) for g in theirs.pb_fills.values())
    return rows, dict(event=w["event_key"], venue=venue, ours_trades=n_ours, theirs_trades=n_theirs,
                      markets=len(links))


def book_rows(conn, w, venue):
    """Our book snapshots (best bid / ask) against their last book at or before each, where both exist."""
    from racinglines.markets import probalytics as PB
    from racinglines.markets import store as MS
    from racinglines.pipelines import weekend_sweep as W
    rid = W._race_id(conn, w["event_key"])
    links = W._links(conn, rid, venue) if rid is not None else []
    if not len(links):
        return []
    start, end = w["stages"][0][1] - timedelta(hours=1), w["race_start"]
    days = pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize())
    if not any((PB.root() / "books" / f"{d:%Y-%m-%d}_F1_{venue.upper()}.parquet").exists() for d in days):
        return []
    root = None if venue == "polymarket" else MS.root_for(venue)
    a, b = pd.Timestamp(start).tz_localize("UTC"), pd.Timestamp(end).tz_localize("UTC")
    bk = MS.read(conn, "books", tokens=links["token_id"].tolist(), start=a, end=b, root=root)
    if not len(bk):
        return []
    theirs = getattr(stage_rows, "venue", None) or PB.EXCHANGES[venue](
        conn, links, start, end, W.GROUP_TARGET, W.COHERENCE_TOL, event_key=w["event_key"])
    rows = []
    for r in bk.itertuples():
        t = pd.Timestamp(r.ts).tz_convert("UTC").tz_localize(None) if pd.Timestamp(r.ts).tzinfo else pd.Timestamp(r.ts)
        q = theirs._touch(str(r.token_id), t)
        rows.append(dict(event=w["event_key"], venue=venue, token=r.token_id, t=t, ours_bid=r.best_bid,
                         ours_ask=r.best_ask, theirs_bid=q[0] if q else None, theirs_ask=q[1] if q else None))
    return rows


def share_within(a, b, tol=PRICE_TOL):
    d = (pd.to_numeric(a) - pd.to_numeric(b)).abs().dropna()
    return (float((d <= tol + 1e-9).mean()) if len(d) else None), int(len(d)), (float(d.median()) if len(d) else None)


def summarize(st, tr, bk):
    out = {}
    for v in VENUES:
        s = st[st["venue"] == v] if len(st) else st
        if not len(s):
            continue
        share, n, med = share_within(s["ours"], s["theirs"])
        both = s["ours"].notna() & s["theirs"].notna()
        out[v] = dict(stage_points=len(s), both_priced=int(both.sum()),
                      ours_only=int((s["ours"].notna() & s["theirs"].isna()).sum()),
                      theirs_only=int((s["ours"].isna() & s["theirs"].notna()).sum()),
                      price_share_within_1c=share, price_median_abs_diff=med,
                      price_pass=share is not None and share >= SHARE_MIN)
        t = tr[tr["venue"] == v] if len(tr) else tr
        if len(t):
            t = t.assign(rel=(t["theirs_trades"] - t["ours_trades"]).abs() / t["ours_trades"].clip(lower=1))
            out[v].update(trades_ours=int(t["ours_trades"].sum()), trades_theirs=int(t["theirs_trades"].sum()),
                          trades_weekends_outside=t.loc[t["rel"] > TRADES_TOL, "event"].tolist(),
                          trades_pass=bool((t["rel"] <= TRADES_TOL).all()))
        b = bk[bk["venue"] == v] if len(bk) else bk
        if len(b):
            om, tm = (b["ours_bid"] + b["ours_ask"]) / 2, (b["theirs_bid"] + b["theirs_ask"]) / 2
            share, n, med = share_within(om, tm)
            out[v].update(book_points=len(b), book_matched=n, book_share_within_1c=share, book_median_abs_diff=med,
                          book_pass=share is not None and share >= SHARE_MIN)
    return out


def compare_results(a, b):
    """Per weekend P&L of every strategy in two search folders' results.json (ours, then Probalytics'), matched by
    job id (the same queue gives the same ids: the tape source is not part of a job's key), round and metric."""
    def load(d):
        r = json.loads((Path(d) / "results.json").read_text())
        runs = {x["id"]: x for x in r["runs"]}
        out = {}
        for job, v in r["state"].items():
            m = (runs.get(v.get("run_id")) or {}).get("metrics") or {}
            for wk in m.get("weekends") or []:
                for k, x in wk.items():
                    if k.endswith("_pnl") and x is not None:
                        out[(job, v.get("year"), (v.get("settings") or {}).get("seed"), wk["round"], wk.get("event"),
                             k)] = float(x)
        return out
    A, B = load(a), load(b)
    rows = [dict(job=k[0], year=k[1], seed=k[2], round=k[3], event=k[4], metric=k[5], ours=A[k], theirs=B.get(k))
            for k in sorted(A, key=str)]
    df = pd.DataFrame(rows)
    if len(df):
        df["diff"] = df["theirs"] - df["ours"]
        df["ok"] = df["diff"].abs() <= np.maximum(PNL_TOL * df["ours"].abs(), PNL_FLOOR)
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--results", nargs=2, metavar=("OURS", "THEIRS"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    from racinglines.paths import DATA
    out = Path(a.out or DATA / "runs" / "probalytics-compare" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    out.mkdir(parents=True, exist_ok=True)
    if a.results:
        df = compare_results(*a.results)
        df.to_csv(out / "pnl.csv", index=False)
        bad = df[~df["ok"]] if len(df) else df
        say(f"P&L per weekend: {len(df)} rows, {len(bad)} outside max({PNL_TOL:.0%}, ${PNL_FLOOR:.0f}) -> {out}")
        print(bad.to_string(index=False) if len(bad) else "all within", flush=True)
        return
    from racinglines.db.config import get_engine
    from racinglines.pipelines import weekend_sweep as W
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    weekends = [w for w in W.schedule(a.year).values() if w["race_start"] < now]
    st, tr, bk = [], [], []
    with get_engine().connect() as conn:
        for i, w in enumerate(weekends, 1):
            for v in VENUES:
                rows, t = stage_rows(conn, w, v)
                st += rows
                if t:
                    tr.append(t)
                bk += book_rows(conn, w, v)
            say(f"progress probalytics_compare: weekend {i} of {len(weekends)} ({w['event_key']} {w['name']}), "
                f"{len(st)} stage points, {len(bk)} book points")
    st, tr, bk = pd.DataFrame(st), pd.DataFrame(tr), pd.DataFrame(bk)
    st.to_parquet(out / "stages.parquet")
    tr.to_csv(out / "trades.csv", index=False)
    if len(bk):
        bk.to_parquet(out / "books.parquet")
    summ = summarize(st, tr, bk)
    (out / "summary.json").write_text(json.dumps(summ, indent=1, default=str))
    lines = [f"# Probalytics vs our tape, F1 {a.year} ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)", "",
             f"Thresholds: price and book mid within {PRICE_TOL * 100:.0f}c on >= {SHARE_MIN:.0%}; trades within "
             f"{TRADES_TOL:.0%} per weekend.", ""]
    for v, s in summ.items():
        lines += [f"## {v}", ""] + [f"- {k}: {x}" for k, x in s.items()] + [""]
    (out / "SUMMARY.md").write_text("\n".join(lines))
    print("\n".join(lines), flush=True)
    say(f"done -> {out}")


if __name__ == "__main__":
    main()
