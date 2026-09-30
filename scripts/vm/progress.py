"""
Job counts for the overnight VM run's progress lines (scripts/vm/overnight.sh; docs/overnight-vm-run.md). Read-only,
no network, never fails the run: any error prints nothing.

    python scripts/vm/progress.py "<phase text>" <phase start, epoch seconds>

Prints " · 42 of 106 jobs done, 1 failed, about 35 min left" for a phase that has countable jobs (the F1 searches
and the replay grids), else nothing.
"""

import json
import sys
import time
from pathlib import Path

SEARCHES = {"F1 broad": ("overnight-vm", "sweeps/overnight-vm.toml", False),
            "16k": ("overnight-vm", "sweeps/overnight-vm.toml", True),
            "evidence sweeps": ("demo-taker-story", "sweeps/demo-taker-story.toml", None)}
GRID_RUNS = 16                 # 2 seasons x 4 edges x 2 volume floors (overnight.sh), before the 16k re-runs


def _sims(settings):
    try:
        return int(json.loads(settings).get("sims") if isinstance(settings, str) else (settings or {}).get("sims") or 0)
    except Exception:
        return 0


def _search(name, queue, deep=None):
    """(done, failed, total) of a search; deep=True counts only its 16,000-simulation jobs, False only the others."""
    keep = (lambda j: True) if deep is None else (lambda j: (_sims(j.get("settings")) == 16000) == deep)
    state = {k: v for k, v in json.loads((Path("data/runs/search") / name / "state.json").read_text()).items() if keep(v)}
    try:
        from racinglines.pipelines import search as S
        total = len([j for j in S.load(queue)[1] if keep(j)])
    except Exception:
        total = len(state)
    done = sum(v.get("status") == "done" for v in state.values())
    failed = sum(v.get("status") in ("failed", "stopped") for v in state.values())
    return done, failed, max(total, done + failed)


def _grid(sport):
    g = Path("data/runs/replay-grid") / sport
    done = len([p for p in g.glob("*/kalshi/summary.json") if "-s16000" not in p.parent.parent.name])
    return done, 0, GRID_RUNS            # a failed grid run gets its own progress line from overnight.sh


def counts(phase, start, now=None):
    now = now or time.time()
    got = None
    for key, (name, queue, deep) in SEARCHES.items():
        if key in phase:
            got = _search(name, queue, deep)
            break
    if got is None and "settings grid" in phase:
        got = _grid(phase.split(":")[0].strip())
    if got is None:
        return ""
    done, failed, total = got
    out = f" · {done} of {total} jobs done" + (f", {failed} failed" if failed else "")
    if 0 < done < total and now > start:
        left = (now - start) / done * (total - done) / 60
        out += f", about {left:.0f} min left"
    return out


if __name__ == "__main__":
    try:
        print(counts(sys.argv[1], float(sys.argv[2])), end="")
    except Exception:
        pass
