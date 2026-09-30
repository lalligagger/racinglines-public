"""
Job counts for the overnight VM run's progress lines (scripts/vm/overnight.sh; docs/overnight-vm-run.md). Read-only,
no network, never fails the run: any error prints nothing.

    python scripts/vm/progress.py "<phase text>" <phase start, epoch seconds> [<run log> <step start, epoch seconds>]

Prints " · 42 of 106 jobs done, 1 failed, about 35 min left" for a phase that has countable jobs (the F1 searches
and the replay grids). Given the run's log, it also reads the race counters the replay prints (" · kalshi tape race
57 of 213, about 40 min left" while a tape pull runs, " · replay race 12 of 36" while a replay or its saves run),
timing the rest from the current step's start. Prints nothing when it has nothing to count.
"""

import json
import re
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


PULL = re.compile(r"^pull (\w+) (\d+)/(\d+) ")                      # position_replay.pull, one per race
REPLAY_HEAD = re.compile(r"^progress \S+ (\w+): (\d+) races")        # position_replay.run, once per venue
REPLAY_RACE = re.compile(r"^progress (\d+) ")                         # position_replay.run, one per race


def _tail(log, size=256_000):
    with open(log, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - size))
        return f.read().decode("utf-8", "replace").replace("\r", "\n").splitlines()


def _left(n, m, start, now):
    if 0 < n < m and start is not None and now > start:
        return f", about {(now - start) / n * (m - n) / 60:.0f} min left"
    return ""


def activity(log, step_start=None, now=None):
    """The race counter of the replay work the log shows last: a tape pull's race N of M, or a replay's."""
    now = now or time.time()
    for i, line in enumerate(reversed(lines := _tail(log))):
        if m := PULL.match(line):
            n, total = int(m[2]), int(m[3])
            return f" · {m[1]} tape race {n} of {total}" + _left(n, total, step_start, now)
        if m := REPLAY_RACE.match(line):
            n = int(m[1])
            for head in reversed(lines[:len(lines) - i]):
                if h := REPLAY_HEAD.match(head):
                    total = int(h[2])
                    return f" · {h[1]} replay race {n} of {total}" + _left(n, total, step_start, now)
            return f" · replay race {n}"
        if line.startswith(("== ", "Pulled ", "Wrote ", "Stored ", "search: ")):
            return ""                   # a newer phase or a finished pull/replay: nothing in flight to count
    return ""


if __name__ == "__main__":
    out = ""
    try:
        out = counts(sys.argv[1], float(sys.argv[2]))
    except Exception:
        pass
    try:
        if not out and len(sys.argv) > 3:
            out = activity(sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None)
    except Exception:
        pass
    print(out, end="")
