"""Price sportsbook-style specials for any F1 event, or backtest them (models/position_sim/specials.py).

    .venv/bin/python scripts/price_specials.py price 2026-17                    # Singapore, data up to now
    .venv/bin/python scripts/price_specials.py price 2026-17 --cutoff "2026-10-10 05:00" --out reports/specials
    .venv/bin/python scripts/price_specials.py price 2026-17 --book book.csv --bankroll 400
    .venv/bin/python scripts/price_specials.py backtest --start-year 2024 --last-n 12

price writes <out>/<event>-specials.csv (every family: classified, team classified, team points, number
classified, last classified, all H2H pairs, with fair odds). --book is a CSV with `label,odds` (odds in
decimal, fractional or American); it adds edge and half-Kelly stakes on --bankroll for those lines.
Read-only: nothing is written to the database. Fair values only know what happened before --cutoff.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from racinglines.db.config import get_engine
from racinglines.models.position_sim import pricing as PRC, specials as S

echo = lambda m: print(m, file=sys.stderr, flush=True)


def _load():
    meas = PRC.Measurements.load(get_engine())
    return meas, PRC.history(meas)


def cmd_price(a):
    meas, hist = _load()
    from sqlalchemy import text
    with get_engine().connect() as c:
        row = c.execute(text("SELECT e.id, e.name, v.slug FROM events e JOIN seasons s ON s.id = e.season_id "
                             "JOIN competitions co ON co.id = s.competition_id LEFT JOIN venues v ON v.id = e.venue_id "
                             "WHERE co.code = 'f1_wdc' AND e.source_key = :k"), dict(k=a.event_key)).first()
    if not row:
        raise SystemExit(f"no F1 event {a.event_key}")
    event_id, name, venue = row
    cutoff = pd.Timestamp(a.cutoff) if a.cutoff else pd.Timestamp.utcnow().tz_localize(None)
    kw = {}
    if not (meas.res["event_id"] == event_id).any():     # not run yet: the field of the latest race, venue from the schedule
        last = meas.drivers[meas.drivers["year"] == int(a.event_key.split("-")[0])].sort_values("r_ts")
        last = last[last["event_id"] == last["event_id"].iloc[-1]]
        kw = dict(entrants=last[["athlete_id", "driver", "team_key"]].reset_index(drop=True), venue=venue)
        echo(f"{name} has no results yet: entrants from the latest race in the database ({last['venue'].iloc[0]}), "
             f"data through {last['r_ts'].max():%Y-%m-%d}")
    summ, ex = PRC.price_race(meas, hist, cutoff, event_id, n_sims=a.sims, rng=np.random.default_rng(a.seed), **kw)
    ent = ex["entrants"]
    priced = S.price(S.board(ent, h2h_pairs=a.pairs), ex["sim"], ent).drop(columns="spec")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    f = out / f"{a.event_key}-specials.csv"
    priced.to_csv(f, index=False)
    print(f"{name}: {len(priced)} specials, cutoff {cutoff}, grid: {ex['audit']['grid']} -> {f}")
    if a.coin:
        from sqlalchemy import text as _t
        extra = {}
        try:
            from racinglines.models.position_sim import props as PP
            with get_engine().connect() as c:
                vid, start = PP.event_info(c, a.event_key)
                h = PP.history(c, start)
            sc = PP.rate(h, vid, "sc")
            vh = h[h["venue_id"] == vid]
            extra["safety_car"] = {"yes": sc, "no": 1 - sc}
            echo(f"safety car (circuit history shrunk to the field): {sc:.3f}; raw at this venue {int(vh['sc'].sum())} of {len(vh)} races")
        except Exception as e:      # noqa: BLE001
            echo(f"safety car not priced: {e}")
        book = pd.read_csv(a.coin)
        spr = None
        if book["market"].isin(["sprint_win", "sprint_team_win"]).any():
            spr, _, glab = S.sprint_sim(meas, hist, cutoff, event_id, n_sims=a.sims, rng=np.random.default_rng(a.seed),
                                        entrants=kw.get("entrants"), venue=kw.get("venue"), year=int(a.event_key.split("-")[0]))
            echo(f"sprint simulated, grid: {glab}")
        sess_sims = {}
        for sess in S.SESSIONS:
            if sess not in ("race", "sprint") and book["market"].str.startswith(sess + "_").any():
                sess_sims[sess], _ = S.session_sim(meas, hist, cutoff, event_id, sess, n_sims=a.sims,
                                                   rng=np.random.default_rng(a.seed), entrants=kw.get("entrants"),
                                                   venue=kw.get("venue"), year=int(a.event_key.split("-")[0]))
        t = S.price_book(book, ex["sim"], ent, extra=extra, bankroll=a.bankroll, sprint=spr, session_sims=sess_sims,
                         thin=tuple(extra) + ("first_retirement", "first_team_retirement", "sprint_win", "sprint_team_win", "fp1_win", "fp2_win", "fp3_win", "sprint_qual_win", "qual_win"))
        if a.picks:
            rec = S.recommend(t, a.picks)
            print(f"\nPICKS on ${a.picks:.0f} (shrunk toward the book by market confidence, half-Kelly, capped):")
            print(rec.round(3).to_string(index=False)); print(f"total staked ${rec['stake'].sum():.2f}")
        f2 = out / f"{a.event_key}-book-edges.csv"
        t.to_csv(f2, index=False)
        echo(f"book edges -> {f2}")
        pd.set_option("display.width", 200)
        ok = t.dropna(subset=["prob"])
        print(ok[~ok["suspect"]].sort_values("edge", ascending=False).head(25).round(3).to_string(index=False))
        echo(f"{int(ok['suspect'].sum())} priced lines gated as suspect (edge > 100% or price >= 100); "
             f"unpriced: {sorted(set(t[t['prob'].isna()]['market']))}")
    if a.book:
        book = pd.read_csv(a.book)
        full = S.price(S.board(ent, h2h_pairs="all"), ex["sim"], ent)
        e = S.edge_table(full, dict(zip(book["label"], book["odds"])), a.bankroll)
        missing = set(book["label"]) - set(e["label"])
        print(e[["label", "odds", "prob", "edge", "half_kelly_stake"]].to_string(index=False))
        if missing:
            print("not matched:", sorted(missing))


def cmd_backtest(a):
    meas, hist = _load()
    bt = S.backtest(meas, hist, start_year=a.start_year, n_sims=a.sims, mode=a.mode, last_n=a.last_n,
                    h2h_pairs=a.pairs, echo=echo)
    s, rel = S.score(bt)
    print(s.round(4).to_string(index=False))
    print(rel.round(3).to_string(index=False))
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        bt.to_csv(Path(a.out) / "specials-backtest.csv", index=False)


p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = p.add_subparsers(dest="cmd", required=True)
a = sub.add_parser("price"); a.add_argument("event_key"); a.add_argument("--cutoff"); a.add_argument("--sims", type=int, default=10000)
a.add_argument("--seed", type=int, default=42); a.add_argument("--pairs", default="all"); a.add_argument("--out", default="reports/specials")
a.add_argument("--book"); a.add_argument("--picks", type=float, help="bankroll to stake across the book (the F1 share)"); a.add_argument("--coin", help="CSV market,subject,odds: price a typed-in book across categories"); a.add_argument("--bankroll", type=float, default=400.0); a.set_defaults(fn=cmd_price)
b = sub.add_parser("backtest"); b.add_argument("--start-year", type=int, default=2024); b.add_argument("--last-n", type=int)
b.add_argument("--sims", type=int, default=2000); b.add_argument("--mode", default="pre_quali", choices=["pre_quali", "pre_race"])
b.add_argument("--pairs", default="teammates"); b.add_argument("--out"); b.set_defaults(fn=cmd_backtest)
args = p.parse_args()
args.fn(args)
