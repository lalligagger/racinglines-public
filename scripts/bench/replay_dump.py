"""Benchmark helper (read-only on the database): the maker replays that `racinglines f1 replay --runs ... --sweep`
runs, as input for the Rust/WebAssembly kernel in scripts/bench/replay_kernel, and the check that the kernel's
quotes and fills equal the Python replay's exactly.

    python scripts/bench/replay_dump.py --runs 1298,1299,1300,1301,1302 --out /tmp/replay_input.json
    python scripts/bench/replay_dump.py --runs 1298,1299,1300,1301,1302 --check /tmp/kernel_out.json
"""

import argparse
import json
import math
import sys
import time
from dataclasses import replace

from racinglines.db.config import get_engine
from racinglines.markets.strategies import maker_replay as R

REASONS = {None: 0, "no fair": 1, "no market price": 2, "outside price band": 3, "thin": 4, "disagree": 5, "limit": 6}


def param_sets():
    """The replays of `f1 replay --sweep`: touch and through at the defaults, then sweep()'s grid."""
    out = [R.Params(fill=m) for m in ("touch", "through")]
    for h in (0.01, 0.02, 0.03, 0.04):
        for fm in ("touch", "through"):
            for d in (0.15, None):
                out.append(replace(R.Params(), half_spread=h, fill=fm, max_disagree=d))
    return out


def _f(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def dump(data, params, path):
    ev = dict(stages=[dict(run_id=int(s["run_id"]), start=int(s["start"]), end=int(s["end"]),
                           session_end=bool(s.get("session_end", True))) for s in data["stages"]],
              qual_start=None if data.get("qual_start") is None else int(data["qual_start"]),
              markets=[dict(kind=m.kind, fairs={str(k): _f(v) for k, v in m.fairs.items()},
                            mid_ts=m.mid_ts.astype("int64").tolist(), mid_px=m.mid_px.astype(float).tolist(),
                            tr_ts=m.tr_ts.astype("int64").tolist(), tr_px=m.tr_px.astype(float).tolist(),
                            tr_sz=m.tr_sz.astype(float).tolist(), tr_buy=[bool(x) for x in m.tr_buy])
                       for m in data["markets"]])
    calls = [dict(event=0, p=dict(half_spread=p.half_spread, tick=p.tick, size=p.size, max_pos=p.max_pos,
                                  max_capital=p.max_capital, skew=p.skew, step_min=p.step_min, pull_min=p.pull_min,
                                  min_volume_24h=p.min_volume_24h, band_lo=p.price_band[0], band_hi=p.price_band[1],
                                  max_disagree=p.max_disagree, touch=p.fill == "touch",
                                  flatten_before_qual=p.flatten_before_qual, taker_cost=p.taker_cost,
                                  info_skew=p.info_skew, info_tau_h=p.info_tau_h, by_kind=p.half_spread_by_kind or {},
                                  maker_fee=p.maker_fee)) for p in params]
    with open(path, "w") as f:
        json.dump(dict(events=[ev], calls=calls), f)


def check(data, params, path):
    """0 when every quote and fill of the kernel equals the Python replay's."""
    kernel = json.load(open(path))
    conds = {m.cond: i for i, m in enumerate(data["markets"])}
    t0, bad = time.perf_counter(), 0
    for p, k in zip(params, kernel):
        res = R.replay(data, p)
        q = res["quotes"]
        py_q = [[int(t), conds[c], int(r), _f(b), _f(a), REASONS[w]]
                for t, c, r, b, a, w in zip(q.ts, q.cond, q.run_id, q.bid, q.ask, q.skip)]
        f = res["fills"]
        py_f = sorted([int(t), conds[c], int(r), s == "buy", float(px), float(n)]
                      for t, c, r, s, px, n in zip(f.ts, f.cond, f.run_id, f.side, f.price, f.qty))
        bad += (py_q != k["quotes"]) + (py_f != sorted(k["fills"]))
    print(f"python replays: {len(params)} in {time.perf_counter() - t0:.2f} s; "
          f"{'identical' if not bad else f'{bad} differences'} to the kernel's quotes and fills")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", required=True, help="diagnostic run ids in time order, as for `f1 replay --runs`")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--out", help="write the kernel's input JSON here")
    g.add_argument("--check", help="compare the kernel's output JSON with the Python replay")
    a = ap.parse_args(argv)
    with get_engine().connect() as c:
        data = R.load_event(c, [int(x) for x in a.runs.split(",")])
    params = param_sets()
    if a.out:
        dump(data, params, a.out)
        print(f"wrote {a.out}: {len(data['markets'])} markets, {len(params)} replays")
        return 0
    return check(data, params, a.check)


if __name__ == "__main__":
    sys.exit(main())
