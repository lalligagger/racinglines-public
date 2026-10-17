"""
The VM's load over time (owner, 2026-10-14): CPU, memory, load average and disk, sampled every SAMPLE_SECONDS by a
thread in the web app (no systemd unit) into data/status/vm_history.jsonl, KEEP_DAYS kept, and drawn on the admin
Database page (/admin/db) next to the storage status.

    one line per sample: {"t": epoch s, "cpu": [busy jiffies, total jiffies], "mem_total", "mem_avail" (bytes),
                          "load": [1, 5, 15 min], "disk_total", "disk_free" (bytes, the filesystem holding data/)}

CPU % is the busy share between two consecutive samples (/proc/stat is cumulative). Linux only: elsewhere the sampler
does not start and the charts say there is no history. RACINGLINES_VM_HISTORY=0 turns the sampler off.
"""

import json
import os
import shutil
import threading
import time
from pathlib import Path

from racinglines import paths

SAMPLE_SECONDS = 300
KEEP_DAYS = 14
_STARTED = False


def history_path():
    return Path(paths.DATA) / "status" / "vm_history.jsonl"


def _cpu():
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:]]
    idle = v[3] + (v[4] if len(v) > 4 else 0)                  # idle + iowait
    return [sum(v) - idle, sum(v)]


def _mem():
    m = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            m[k] = int(v.split()[0]) * 1024
    return m["MemTotal"], m.get("MemAvailable", m.get("MemFree", 0))


def sample():
    """One sample of this machine, or None where /proc is missing (not Linux)."""
    if not Path("/proc/stat").exists():
        return None
    total, avail = _mem()
    du = shutil.disk_usage(paths.DATA if Path(paths.DATA).exists() else "/")
    return dict(t=int(time.time()), cpu=_cpu(), mem_total=total, mem_avail=avail, load=list(os.getloadavg()),
                disk_total=du.total, disk_free=du.free)


def append(s, path=None):
    """Add a sample; past KEEP_DAYS the oldest lines are dropped (checked once the file has a day's slack)."""
    p = path or history_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(s) + "\n")
    keep = KEEP_DAYS * 86400 // SAMPLE_SECONDS
    lines = p.read_text().splitlines()
    if len(lines) > keep + 86400 // SAMPLE_SECONDS:
        tmp = p.with_suffix(".tmp")
        tmp.write_text("\n".join(lines[-keep:]) + "\n")
        tmp.replace(p)


def read(days=KEEP_DAYS, path=None, now=None):
    p = path or history_path()
    try:
        raw = p.read_text().splitlines()
    except OSError:
        return []
    since = (now or time.time()) - days * 86400
    out = []
    for line in raw:
        try:
            s = json.loads(line)
        except ValueError:
            continue
        if s.get("t", 0) >= since:
            out.append(s)
    return out


def series(samples):
    """{metric: [(t, value)]}: cpu % (between consecutive samples), mem % used, load (1 min), disk % used."""
    out = dict(cpu=[], mem=[], load=[], disk=[])
    prev = None
    for s in samples:
        t = s["t"]
        if prev and s["cpu"][1] > prev["cpu"][1] and s["cpu"][0] >= prev["cpu"][0]:
            out["cpu"].append((t, 100 * (s["cpu"][0] - prev["cpu"][0]) / (s["cpu"][1] - prev["cpu"][1])))
        if s["mem_total"]:
            out["mem"].append((t, 100 * (1 - s["mem_avail"] / s["mem_total"])))
        out["load"].append((t, s["load"][0]))
        if s["disk_total"]:
            out["disk"].append((t, 100 * (1 - s["disk_free"] / s["disk_total"])))
        prev = s
    return out


def chart(points, w=600, h=110, ymax=None, pad=4):
    """An SVG polyline for one series on its own 0..ymax scale: dict(points="x,y ...", last, max, ymax, start, end, dots)
    with dots = [(x, y, t, v)] for hover titles. ymax: fixed (100 for %), else the series' max rounded up."""
    if len(points) < 2:
        return None
    t0, t1 = points[0][0], points[-1][0]
    top = ymax or max(1.0, float(int(max(v for _, v in points)) + 1))
    span = (t1 - t0) or 1
    xy = [(pad + (w - 2 * pad) * (t - t0) / span, h - pad - (h - 2 * pad) * min(v, top) / top, t, v) for t, v in points]
    return dict(points=" ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in xy), last=points[-1][1],
                max=max(v for _, v in points), ymax=top, start=t0, end=t1, dots=xy, w=w, h=h)


def charts(days=KEEP_DAYS):
    """The four charts the admin page draws, from the history file: [dict(key, label, unit, chart)]."""
    s = series(read(days))
    spec = (("cpu", "CPU", "%", 100), ("mem", "Memory used", "%", 100), ("load", "Load (1 min)", "", None),
            ("disk", "Disk used", "%", 100))
    return [dict(key=k, label=label, unit=unit, chart=chart(s[k], ymax=ymax)) for k, label, unit, ymax in spec]


def start_sampler():
    """The sampling thread, once per process, on Linux, unless RACINGLINES_VM_HISTORY=0 or under pytest."""
    global _STARTED
    if (_STARTED or os.environ.get("RACINGLINES_VM_HISTORY", "1") == "0" or "PYTEST_CURRENT_TEST" in os.environ
            or not Path("/proc/stat").exists()):
        return False
    _STARTED = True

    def run():
        while True:
            try:
                s = sample()
                if s:
                    append(s)
            except Exception as ex:  # noqa: BLE001  (a missed sample is a gap in the chart, never a crash)
                print(f"vm history: sample skipped: {ex}")
            time.sleep(SAMPLE_SECONDS)

    threading.Thread(target=run, name="vm-history", daemon=True).start()
    return True
