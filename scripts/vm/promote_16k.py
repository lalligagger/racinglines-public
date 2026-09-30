"""
Promote a search's top combos to 16,000 simulations: the second half of the overnight VM run
(docs/overnight-vm-run.md). Reads the candidates.toml that `racinglines f1 search-report` wrote, keeps the best
`--top` distinct settings that a taker could really have traded (no 24 h volume floor under $25, Polymarket only:
Kalshi's taker replay fills at last-trade prints, data/runs/search/taker-resweep/REPORT.md section 3), and appends
one [[job]] per season at `--sims` to the queue, plus profile A and the default baseline at the same fidelity.
Running `racinglines f1 search` on the same queue again then runs only the new jobs (finished ones are kept in
state.json), and `f1 search-report` fills the report's Confirmed column from them.

    python scripts/vm/promote_16k.py sweeps/overnight-vm.toml --top 10

Idempotent: the promoted block is replaced, not appended twice. Prints what it added.
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

MARK = "# --- promoted to 16k by scripts/vm/promote_16k.py (replaced on every run) ---"
META = {"id", "name", "year", "strategy", "why", "venue", "sport", "seed", "sims"}
PROFILE_A = {"variant": "gridq+pretrain+reset", "min_edge": 0.1, "min_edge_h2h": 0.05,
             "taker_stages": ["after FP1", "after FP2", "after FP3", "after SQ", "after Sprint", "after Quali"]}
MIN_TRADEABLE_VOLUME = 25.0


def pick(candidates, top):
    """The first `top` distinct tradeable settings, in the report's order."""
    out, seen = [], set()
    for c in candidates:
        if c.get("venue", "polymarket") != "polymarket" or c.get("sport", "f1") != "f1":
            continue
        st = {k: v for k, v in c.items() if k not in META}
        if float(st.get("min_volume_24h", 50.0)) < MIN_TRADEABLE_VOLUME:
            continue
        key = repr(sorted(st.items()))
        if key not in seen:
            seen.add(key)
            out.append((c.get("id", "?"), st))
        if len(out) >= top:
            break
    return out


def _val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return '"' + v.replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return '"' + ",".join(map(str, v)) + '"'
    return repr(v)


def block(picked, years, sims):
    lines = [MARK, ""]
    rows = [("profile A (golden)", PROFILE_A), ("default baseline", {})] + [(cid, st) for cid, st in picked]
    done = set()
    for why, st in rows:
        key = repr(sorted(st.items()))
        if key in done:
            continue
        done.add(key)
        for y in years:
            lines += ["[[job]]", f"year = {y}", f"sims = {sims}"]
            lines += [f"{k} = {_val(v)}" for k, v in st.items()]
            lines += [f'note = "16k: {why}"', ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("queue")
    ap.add_argument("--candidates", default=None, help="default: data/runs/search/<[search] name>/candidates.toml")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--sims", type=int, default=16000)
    ap.add_argument("--years", default="2026,2025")
    a = ap.parse_args(argv)
    q = Path(a.queue)
    text = q.read_text()
    name = tomllib.loads(text).get("search", {}).get("name", "search")
    cf = Path(a.candidates) if a.candidates else Path("data/runs/search") / name / "candidates.toml"
    if not cf.exists():
        sys.exit(f"{cf} not found: run `racinglines f1 search-report {q}` first")
    picked = pick(tomllib.loads(cf.read_text()).get("candidate", []), a.top)
    if not picked:
        sys.exit(f"no tradeable Polymarket candidate in {cf}: nothing promoted")
    years = [int(y) for y in a.years.split(",")]
    base = text.split(MARK)[0].rstrip() + "\n\n"
    q.write_text(base + block(picked, years, a.sims))
    tomllib.loads(q.read_text())                       # still valid TOML
    for cid, st in picked:
        print(f"promoted {cid}: {st}")
    print(f"{len(picked)} combos + profile A + baseline at {a.sims:,} sims for {years}: appended to {q}")


if __name__ == "__main__":
    main()
