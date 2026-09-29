"""Parity check: the signal engine's replay of a profile on a past weekend must equal the sweep's trades.

    .venv/bin/python scripts/signals_parity.py                       # profile A, 2026 round 15 (Azerbaijan)
    .venv/bin/python scripts/signals_parity.py --profile A --year 2026 --round 12 --reprice
    .venv/bin/python scripts/signals_parity.py --venue kalshi        # the same on Kalshi's links and tape
    .venv/bin/python scripts/signals_parity.py --profile C --venue kalshi   # a maker: fills and settled P&L

Replays `racinglines f1 signals` at the race start (every stage known, markets read at each cutoff) and runs
`racinglines f1 sweep --rounds N --no-fetch` with the profile's settings; compares market, stage, side,
shares and price of every taker trade. --reprice makes the sweep price every stage itself. Exit 1 on a diff.

--venue kalshi gives the profile the `venue = kalshi` setting for both sides (the switch the signal engine and
the sweep read), so nothing about the profile's Polymarket record is touched. A maker profile is replayed as
`f1 demo-history` replays it (a day after the race, settled) and compared with the sweep's maker on fills and
settled P&L, and with the demo maker's stored record for that weekend and venue when there is one.
"""

import argparse
import sys
import warnings

warnings.filterwarnings("ignore")


def _taker(prof, w, out, sw):
    tr = sw["trades"] if prof["strategy"] == "update" else None
    if tr is None:
        sys.exit("the sweep keeps only the update taker's trades; use an update profile")
    want = sorted((r["key"], r["stage"], r["side"], round(r["shares"], 6), round(r["price"], 6))
                  for r in tr.to_dict("records"))
    got = sorted((s["market_key"], s["stage"], s["side"], round(s["shares"] if s["action"] == "buy" else -s["shares"], 6),
                  round(s["limit_price"], 6)) for s in out["signals"])
    print(f"{prof['name']} · {w['name']} · {out['venue']}: sweep {len(want)} trades, signals {len(got)} "
          f"(sweep update P&L {sw['totals'].get('update', {}).get('pnl', 0):+.2f})")
    if got == want:
        print("PARITY: identical")
        return 0
    print("PARITY: DIFFERENT")
    print("  only in the sweep:  ", sorted(set(want) - set(got))[:10])
    print("  only in the signals:", sorted(set(got) - set(want))[:10])
    return 1


def _maker(eng, prof, w, out, sw, venue):
    from sqlalchemy import text
    fills = [s for s in out["signals"] if s["action"] == "fill"]
    pnl = sum(p["cash"] + p["yes_shares"] * float(p["outcome"]) for p in out["positions"] if p["outcome"] is not None)
    wk = sw["weekends"].iloc[0] if len(sw["weekends"]) else {}
    want = (int(wk.get("maker_fills", 0)), round(float(wk.get("maker_pnl", 0.0)), 2))
    got = (len(fills), round(pnl, 2))
    print(f"{prof['name']} · {w['name']} · {venue}: signals {got[0]} fills, settled P&L {got[1]:+.2f}; "
          f"sweep maker {want[0]} fills, P&L {want[1]:+.2f}")
    with eng.connect() as c:
        stored = c.execute(text("""SELECT sum(cash + yes_shares * outcome::int + no_shares * (1 - outcome::int))
                                   FROM paper_positions pp JOIN users u ON u.id = pp.user_id
                                   WHERE u.username = 'maker' AND pp.event_key = :e AND pp.venue = :v
                                     AND pp.outcome IS NOT NULL"""), dict(e=w["event_key"], v=venue)).scalar()
    if stored is not None:
        print(f"  demo maker's stored record ({venue}, f1 demo-history): {float(stored):+.2f}")
    ok = got == want and (stored is None or round(float(stored), 2) == got[1])
    print("PARITY: identical" if ok else "PARITY: DIFFERENT")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="A")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--round", type=int, default=15)
    ap.add_argument("--reprice", action="store_true")
    ap.add_argument("--venue", default=None, choices=["polymarket", "kalshi"],
                    help="Give the profile this `venue` setting on both sides (default: the profile's own).")
    a = ap.parse_args()
    from racinglines.db.config import get_engine
    from racinglines.pipelines import demo_history as DH
    from racinglines.pipelines import profiles as PF
    from racinglines.pipelines import signals as SG
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.pipelines.weekend_sweep import run_sweep, schedule
    eng = get_engine()
    with eng.connect() as c:
        prof = PF.load(c, a.profile)
    if a.venue:
        prof = dict(prof, settings=dict(prof["settings"], venue=a.venue))
    st = SS.Settings.from_dict(prof["settings"], strict=False)
    venue = SS.venue_of(st)
    maker = prof["strategy"] in SG.WS.MAKERS
    if not maker and prof["strategy"] not in SG.WS.TAKER_MODES:
        sys.exit(f"{prof['name']} is a {prof['strategy']} profile: parity is checked on taker and maker profiles")
    w = schedule(a.year, [a.round])[a.round]
    now = w["race_start"] + DH.SETTLED if maker else w["race_start"]
    out = SG.compute(eng, None, prof, now=now, event=f"{a.year}-{a.round}", live=False, fetch=False, echo=lambda m: None)
    sw = run_sweep(eng, None, a.year, rounds=[a.round], fetch=False, reprice=a.reprice, settings=st, echo=lambda m: None)
    return _maker(eng, prof, w, out, sw, venue) if maker else _taker(prof, w, out, sw)


if __name__ == "__main__":
    sys.exit(main())
