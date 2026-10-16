"""A fast strategy walk-forward from a search's saved results: before every weekend, pick one setup from the pool using only
the weekends raced so far, trade that weekend with it, and score the picks. No re-simulation: each setup's season sweep
already holds its P&L weekend by weekend (every weekend priced as of its own sessions), so a pick can only see the past.

The rule is pipelines/story.py's (the demo accounts' walk-forward): start on the default setup (DEFAULT_NOTE, else the
first job); before each weekend switch to the setup with the most P&L so far when it beats the current one by more than
SWITCH_MARGIN. Reported per venue against every static setup and the best one in hindsight (which a walk-forward can't
know), so the gap between them is what choosing as you go costs.

    python scripts/probes/walk_forward.py data/runs/search/wf-probalytics-2026 [--strategy update] [--margin 100]

Read-only; writes walk_forward.md and walk_forward.json next to the search's results.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SWITCH_MARGIN = 100.0                 # $: pipelines/story.SWITCH_MARGIN, don't churn on noise
DEFAULT_NOTE = "min_edge 0.1"         # the starting setup: profile A's own minimum edge, no spread limit


def load(folder):
    """{job id: dict(venue, note, weekends {round: pnl dict})} from a search folder's results.json."""
    r = json.loads((Path(folder) / "results.json").read_text())
    runs = {x["id"]: x for x in r["runs"]}
    out = {}
    for job, v in r["state"].items():
        m = (runs.get(v.get("run_id")) or {}).get("metrics") or {}
        wk = {w["round"]: w for w in m.get("weekends") or []}
        if wk:
            seed = (v.get("settings") or {}).get("seed")
            out[job] = dict(venue=v.get("venue") or (v.get("settings") or {}).get("venue") or "polymarket",
                            note=(v.get("note") or job) + (f" (seed {seed})" if seed is not None else ""), weekends=wk)
    return out


def walk(pool, strategy="update", margin=SWITCH_MARGIN):
    """-> dict(rounds, picks [(round, job)], wf_pnl, static {job: pnl}, hindsight (job, pnl))."""
    rounds = sorted({r for p in pool.values() for r in p["weekends"]})
    key = f"{strategy}_pnl"
    pnl = {j: {r: float(p["weekends"].get(r, {}).get(key) or 0.0) for r in rounds} for j, p in pool.items()}
    start = next((j for j, p in pool.items() if p["note"].split(" (seed")[0].endswith(DEFAULT_NOTE)), next(iter(pool)))
    current, picks, wf = start, [], 0.0
    for i, r in enumerate(rounds):
        if i:                                            # before weekend r: only rounds[:i] are known
            so_far = {j: sum(pnl[j][x] for x in rounds[:i]) for j in pool}
            best = max(so_far, key=so_far.get)
            if so_far[best] > so_far[current] + margin:
                current = best
        picks.append((r, current))
        wf += pnl[current][r]
    static = {j: sum(v.values()) for j, v in pnl.items()}
    best = max(static, key=static.get)
    return dict(rounds=rounds, picks=picks, wf_pnl=wf, static=static, hindsight=(best, static[best]), start=start)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--strategy", default="update")
    ap.add_argument("--margin", type=float, default=SWITCH_MARGIN)
    a = ap.parse_args()
    jobs = load(a.folder)
    lines, out = [f"# Walk-forward on {Path(a.folder).name} ({a.strategy}, switch margin ${a.margin:.0f})", ""], {}
    for venue in sorted({p["venue"] for p in jobs.values()}):
        pool = {j: p for j, p in jobs.items() if p["venue"] == venue and "baseline" not in p["note"]}
        if not pool:
            continue
        w = walk(pool, a.strategy, a.margin)
        out[venue] = dict(w, picks=[(r, jobs[j]["note"]) for r, j in w["picks"]],
                          static={jobs[j]["note"]: round(x, 2) for j, x in w["static"].items()},
                          hindsight=(jobs[w["hindsight"][0]]["note"], round(w["hindsight"][1], 2)),
                          start=jobs[w["start"]]["note"])
        lines += [f"## {venue}", "", f"- walk-forward P&L: **{w['wf_pnl']:+,.0f}** over rounds {w['rounds'][0]} to "
                  f"{w['rounds'][-1]}, starting on {jobs[w['start']]['note']}",
                  f"- best static setup in hindsight: {jobs[w['hindsight'][0]]['note']} ({w['hindsight'][1]:+,.0f})", "",
                  "| setup | season P&L |", "|---|---|"]
        lines += [f"| {jobs[j]['note']} | {x:+,.0f} |" for j, x in sorted(w["static"].items(), key=lambda kv: -kv[1])]
        lines += ["", "| round | setup used |", "|---|---|"] + [f"| {r} | {jobs[j]['note']} |" for r, j in w["picks"]] + [""]
    (Path(a.folder) / "walk_forward.md").write_text("\n".join(lines))
    (Path(a.folder) / "walk_forward.json").write_text(json.dumps(out, indent=1, default=str))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
