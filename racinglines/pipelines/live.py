"""
The live core, shared by every sport: the run folder, snapshots, replay, live / replay state, the event
registry, and launch specs. Each sport's data stream and pricing is an adapter (pipelines/live_dh.py,
pipelines/live_f1.py) implementing

    markets(event)          the markets and their fair values now
    step(spec, now)         new stream data, if any; the engine's update if something changed
    outcomes(...)           settled results per market, when known
    view(...)               what the sport's body partial (templates/live_<sport>.html) needs

The book, the crowd and the quotes are markets/crowd.py and markets/quoting.py. A sport's live settings are
data: the [live] section of sports/<code>.toml, overridden per event by a launch spec (live/<sport>/<event>.toml).

Run folder: data/runs/live/<run>/ (downhill: <slug>_<key>, one per final; F1: the event key, e.g. 2026-16)
    latest.json        the newest snapshot (the Live tab reads it)
    snaps/<ts>.json.gz every snapshot, for the replay
    history.jsonl      one line per update: every market's fair value and quote
    book.json          the maker's private book (markets/crowd.py)
    crowd.jsonl        every crowd fill, per update / poll
    picks.json         the demo taker's picks
    meta.json          the settings and model inputs; every version kept as meta_<ts>.json
"""

import bisect
import gzip
import json
import time
import tomllib
from importlib import import_module

from racinglines import paths, sports
from racinglines.markets import crowd as C

SPECS = paths.ROOT / "live"             # committed launch specs: live/<sport>/<event>.toml
STALE_H = 6                             # a run not updated for this long is a replay (sport default: [live.poll] stale_h)


def base():
    return paths.DATA / "runs" / "live"


def folder(run, mkdir=True):
    d = base() / run
    if mkdir:
        d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Settings: a sport's [live] section, and a launch spec per event
# ---------------------------------------------------------------------------

def merge(a, b):
    """b over a, recursively (dicts); b's other values replace a's."""
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def settings(sport, overrides=None):
    """A sport's live settings: sports/<sport>.toml [live], with overrides."""
    return merge(sports.load(sport).get("live", {}), overrides or {})


def spec_path(sport, event):
    return SPECS / sport / f"{event}.toml"


def load_spec(path):
    """A launch spec (path, or 'sport/event'): dict(sport, event, run, title, feed, window, market_set, live=
    the sport's [live] settings with the spec's [live] overrides, path)."""
    from pathlib import Path
    p = Path(path)
    if not p.exists() and not p.suffix:
        p = SPECS / f"{path}.toml"
    spec = tomllib.loads(p.read_text())
    spec.setdefault("run", spec["event"])
    spec["live"] = settings(spec["sport"], spec.get("live"))
    spec["path"] = str(p)
    return spec


def adapter(sport):
    """The sport's adapter module ([live] adapter in sports/<sport>.toml)."""
    return import_module(sports.load(sport)["live"]["adapter"])


# ---------------------------------------------------------------------------
# Files: meta, snapshots, history, the crowd log
# ---------------------------------------------------------------------------

def write_meta(out, meta, stamp):
    """meta.json when it changed, and every version as meta_<stamp>.json. True if it changed."""
    blob = json.dumps(meta, sort_keys=True, default=str)
    if (out / "meta.json").exists() and (out / "meta.json").read_text() == blob:
        return False
    (out / "meta.json").write_text(blob)
    (out / f"meta_{stamp}.json").write_text(blob)
    return True


def write_snapshot(out, snap, stamp):
    (out / "snaps").mkdir(exist_ok=True)
    with gzip.open(out / "snaps" / f"{stamp}.json.gz", "wt") as f:
        json.dump(snap, f, default=str)
    tmp = out / "latest.json.tmp"
    tmp.write_text(json.dumps(snap, default=str))
    tmp.replace(out / "latest.json")


def append(out, name, row):
    with (out / name).open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def read_jsonl(p):
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []


# ---------------------------------------------------------------------------
# Reading a run: latest, replay, the book rebuilt from its fills
# ---------------------------------------------------------------------------

def load(run):
    """(latest snapshot or None, picks, history)."""
    out = folder(run)
    snap = json.loads((out / "latest.json").read_text()) if (out / "latest.json").exists() else None
    picks = json.loads((out / "picks.json").read_text()) if (out / "picks.json").exists() else []
    return snap, picks, read_jsonl(out / "history.jsonl")


def snap_times(run):
    """The saved snapshots' times (their file names, e.g. 20260927T223221), oldest first."""
    return sorted(f.name.split(".")[0] for f in (folder(run) / "snaps").glob("*.json.gz"))


def load_at(run, t):
    """load() as of one snapshot (the last one at or before t, a snap_times name): the snapshot, the picks,
    the history up to it."""
    times = snap_times(run)
    if not times:
        return load(run)
    name = times[max(0, bisect.bisect_right(times, t) - 1)]
    with gzip.open(folder(run) / "snaps" / f"{name}.json.gz", "rt") as f:
        snap = json.load(f)
    _, picks, hist = load(run)
    return snap, picks, [h for h in hist if h["ts"] <= snap["ts"]]


def book_opened(run):
    """When the private book that ran opened: its first crowd update's time (ISO), or None."""
    p = folder(run) / "crowd.jsonl"
    if not p.exists():
        return None
    with p.open() as f:
        first = f.readline()
    return json.loads(first)["ts"] if first.strip() else None


def book_at(run, ts=None):
    """The maker's private book rebuilt from the crowd's fills up to ts (ISO; None = all): {market: dict(inv,
    cash)} (the maker's side; the same as book.json at the end) and the crowd updates up to ts, newest last."""
    return C.rebuild(read_jsonl(folder(run) / "crowd.jsonl"), ts)


# ---------------------------------------------------------------------------
# The registry: which live events exist, and which adapter each uses
# ---------------------------------------------------------------------------

def _sport_of(meta, run):
    if meta.get("sport"):
        return meta["sport"]
    return "mtb_dh" if "slug" in meta or "_" in run else None


def events():
    """Every recorded live event, newest first: dict(run, sport, event_key, title, mtime)."""
    b = base()
    out = []
    for p in (b.glob("*/latest.json") if b.exists() else []):
        run = p.parent.name
        mp = p.parent / "meta.json"
        try:
            meta = json.loads(mp.read_text()) if mp.exists() else {}
        except ValueError:
            meta = {}
        sport = _sport_of(meta, run)
        key = meta.get("event_key") or (run.rsplit("_", 1)[0] if sport == "mtb_dh" else run)
        out.append(dict(run=run, sport=sport, event_key=key, title=meta.get("title") or event_name(key),
                        mtime=p.stat().st_mtime))
    return sorted(out, key=lambda e: -e["mtime"])


def find(run=None):
    """A registry entry: the given run (or event key), else the most recently updated one; None if none."""
    evs = events()
    if run:
        return next((e for e in evs if run in (e["run"], e["event_key"])), None)
    return evs[0] if evs else None


def latest():
    """The most recently updated run's name (however old: a replay), or None."""
    e = find()
    return e["run"] if e else None


def stale_h(sport):
    try:
        return float(settings(sport).get("poll", {}).get("stale_h", STALE_H))
    except (FileNotFoundError, KeyError):
        return STALE_H


def state(run=None, max_age_h=None):
    """'live' while an event runs (not over, and updated within its sport's stale_h, or its next update not
    more than that overdue), 'replay' once it is over (or stale), None when nothing was ever recorded. Cached
    on latest.json's mtime (read per page)."""
    e = find(run)
    if e is None:
        return None
    p = folder(e["run"]) / "latest.json"
    m = p.stat().st_mtime
    cache = state.__dict__.setdefault("cache", {})
    if cache.get(p) is None or cache[p][0] != m:
        s = json.loads(p.read_text())
        nxt = s.get("next_at")
        cache[p] = (m, bool(s.get("done")), _epoch(nxt) if nxt else None)
    _, done, nxt = cache[p]
    age = (max_age_h if max_age_h is not None else stale_h(e["sport"])) * 3600
    now = time.time()
    fresh = now - m <= age or (nxt is not None and now <= nxt + age)
    return "live" if not done and fresh else "replay"


def _epoch(iso):
    from datetime import datetime, timezone
    t = datetime.fromisoformat(str(iso))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


def event_name(event_key):
    """A private-book event's display name: its registry title, a downhill final's name, else the key."""
    from racinglines.pipelines import live_dh
    if event_key in live_dh.EVENT_NAMES:
        return live_dh.EVENT_NAMES[event_key]
    b = base()
    mp = b / event_key / "meta.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text()).get("title") or event_key
        except ValueError:
            pass
    return event_key


def _runs_of(event_key):
    b = base()
    if not b.exists():
        return []
    exact = b / event_key
    return [exact] if (exact / "meta.json").exists() or (exact / "snaps").exists() else sorted(b.glob(f"{event_key}_*"))


def book_curve(event_key, maker=True):
    """The private book's P&L through the event, from every saved snapshot since the book opened (all of the
    event's runs, e.g. a downhill event's finals): [(time, P&L)], the maker's total (maker) or the demo taker's
    (the negative of the maker's P&L vs the taker). Cached per snapshot count: the files are only ever added to."""
    import pandas as pd
    dirs = _runs_of(event_key)
    files = sorted(str(f) for d in dirs for f in (d / "snaps").glob("*.json.gz"))
    opened = min((o for d in dirs if (d / "crowd.jsonl").exists() and (o := book_opened(d.name))), default=None)
    cache = book_curve.__dict__.setdefault("cache", {})
    if cache.get(event_key, (None,))[0] != len(files):
        pts = []
        for f in files:
            with gzip.open(f, "rt") as fh:
                s = json.load(fh)
            if s.get("maker_pnl") and (opened is None or s["ts"] >= opened):   # a replaced book's snapshots: not this one
                pts.append((pd.Timestamp(s["ts"]), s["maker_pnl"]["total"], -s["maker_pnl"]["taker"]))
        cache[event_key] = (len(files), pts)
    return [(t, m if maker else k) for t, m, k in cache[event_key][1]]
