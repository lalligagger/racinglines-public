"""Parity check: the signal engine's replay of a profile on a past weekend must equal the sweep's trades.

    .venv/bin/python scripts/signals_parity.py                       # profile A, 2026 round 15 (Azerbaijan)
    .venv/bin/python scripts/signals_parity.py --profile A --year 2026 --round 12 --reprice

Replays `racinglines f1 signals` at the race start (every stage known, markets read at each cutoff) and runs
`racinglines f1 sweep --rounds N --no-fetch` with the profile's settings; compares market, stage, side,
shares and price of every taker trade. --reprice makes the sweep price every stage itself. Exit 1 on a diff.
"""

import argparse
import sys
import warnings

warnings.filterwarnings("ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="A")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--round", type=int, default=15)
    ap.add_argument("--reprice", action="store_true")
    a = ap.parse_args()
    from racinglines.db.config import get_engine
    from racinglines.pipelines import profiles as PF
    from racinglines.pipelines import signals as SG
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.pipelines.weekend_sweep import run_sweep, schedule
    eng = get_engine()
    with eng.connect() as c:
        prof = PF.load(c, a.profile)
    if prof["strategy"] not in SG.WS.TAKER_MODES:
        sys.exit(f"{prof['name']} is a {prof['strategy']} profile: parity is checked on taker profiles")
    st = SS.Settings.from_dict(prof["settings"], strict=False)
    w = schedule(a.year, [a.round])[a.round]
    out = SG.compute(eng, None, prof, now=w["race_start"], event=f"{a.year}-{a.round}", live=False, fetch=False,
                     echo=lambda m: None)
    sw = run_sweep(eng, None, a.year, rounds=[a.round], fetch=False, reprice=a.reprice, settings=st, echo=lambda m: None)
    mode = prof["strategy"]
    tr = sw["trades"] if mode == "update" else None
    if tr is None:
        sys.exit("the sweep keeps only the update taker's trades; use an update profile")
    want = sorted((r["key"], r["stage"], r["side"], round(r["shares"], 6), round(r["price"], 6))
                  for r in tr.to_dict("records"))
    got = sorted((s["market_key"], s["stage"], s["side"], round(s["shares"] if s["action"] == "buy" else -s["shares"], 6),
                  round(s["limit_price"], 6)) for s in out["signals"])
    print(f"{prof['name']} · {w['name']}: sweep {len(want)} trades, signals {len(got)} "
          f"(sweep update P&L {sw['totals'].get('update', {}).get('pnl', 0):+.2f})")
    if got == want:
        print("PARITY: identical")
        return 0
    print("PARITY: DIFFERENT")
    print("  only in the sweep:  ", sorted(set(want) - set(got))[:10])
    print("  only in the signals:", sorted(set(got) - set(want))[:10])
    return 1


if __name__ == "__main__":
    sys.exit(main())
