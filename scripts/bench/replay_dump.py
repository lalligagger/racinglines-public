"""Benchmark helper (read-only on the database): the maker replays that `racinglines strategy replay f1 --runs ... --sweep`
runs, as input for the Rust/WebAssembly replay in wasm/, and the check that its quotes and fills equal the Python
replay's exactly and its summaries agree.

    python scripts/bench/replay_dump.py --runs 1298,1299,1300,1301,1302 --out /tmp/replay_input.json
    python scripts/bench/replay_dump.py --runs 1298,1299,1300,1301,1302 --check /tmp/replay_output.json
"""

import argparse
import json
import math
import sys
import time
from dataclasses import replace

from racinglines.db.config import get_engine
from racinglines.markets.strategies import maker_replay as R
from racinglines.markets.strategies.replay_json import event_json, params_json

REASONS = {None: 0, "no fair": 1, "no market price": 2, "outside price band": 3, "thin": 4, "disagree": 5, "limit": 6}
COLUMNS = ("markets", "quoted_share", "fills", "shares", "notional", "spread_pnl", "markout_60m", "model_edge", "pnl",
           "worst_case")


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
    with open(path, "w") as f:
        json.dump(dict(event=event_json(data), calls=[params_json(p) for p in params]), f)


def compare(data, p, k):
    """The differences between the Python replay with `p` and one call's output of the wasm/ runner: [] when every
    quote and fill is equal and the per-kind summary agrees to 1e-9 (sums may add in a different order)."""
    conds = {m.cond: i for i, m in enumerate(data["markets"])}
    res = R.replay(data, p)
    q = res["quotes"]
    py_q = [[int(t), conds[c], int(r), _f(b), _f(a), REASONS[w]]
            for t, c, r, b, a, w in zip(q.ts, q.cond, q.run_id, q.bid, q.ask, q.skip)]
    f = res["fills"]
    py_f = [[int(t), conds[c], int(r), s == "buy", float(px), float(n)]
            for t, c, r, s, px, n in zip(f.ts, f.cond, f.run_id, f.side, f.price, f.qty)]
    bad = []
    if py_q != k["quotes"]:
        bad.append("quotes")
    if sorted(py_f) != sorted(k["fills"]):
        bad.append("fills")
    py_s = R.summary(res)
    for row in k["summary"]["summary"]:
        for col in COLUMNS:
            a, b = float(py_s.loc[row["kind"], col]), float(row[col])
            if not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9):
                bad.append(f"summary {row['kind']} {col}: python {a} wasm {b}")
    if len(k["summary"]["summary"]) != len(py_s):
        bad.append("summary rows")
    return bad


def check(data, params, path):
    """0 when every call agrees (compare())."""
    out = json.load(open(path))
    t0, bad = time.perf_counter(), 0
    for p, k in zip(params, out):
        diff = compare(data, p, k)
        bad += bool(diff)
        for d in diff[:5]:
            print(f"  {p.fill} h={p.half_spread} d={p.max_disagree}: {d}")
    print(f"python replays: {len(params)} in {time.perf_counter() - t0:.2f} s; "
          f"{'identical' if not bad else f'{bad} calls differ'} (quotes and fills exact, summaries to 1e-9)")
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
