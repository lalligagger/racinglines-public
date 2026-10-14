"""Research: the strategy universe and the week-locked packages for the Jev desk. Spec: reports/2026-10-14-jev-desk/PREREG.md (v2).

Paper research off the live path: no order, no setting, no database write. The only database touches are the
read-only SELECTs in `jev_desk.load_runs` and `load_events` below. Everything else is pure.

Two sides, kept apart on purpose:
  * `Universe` holds every series, including 2026 rounds that have not happened as of a given week. Its `ret`, `total`
    and `canaries` are for the HARNESS (scoring, leak guard) only.
  * `View` is what Jev may see. `Universe.view(r)` builds a snapshot by copying 2025 data plus 2026 data for rounds < r
    plus only the non-outcome fields of round r, builds the packages from that snapshot alone, and keeps no reference to
    the snapshot or the Universe.

Interpretations of the PREREG (also listed in the report that quotes this module):
  * Returns: `jev_desk.build_menu(..., bankroll=REFERENCE_BANKROLL)`: flat = pnl / 10,000; Kelly = pnl / (10,000 + the
    run's own cumulative earlier pnl). Checked in tests.
  * Totals, "total without best two weeks" and drawdown use the arithmetic sum of weekly returns (an additive path).
  * "Last four weeks": the last four weeks before round r in time order (2026 so far, topped up from 2025's final weeks
    when 2026 has fewer than four), which is 2025's final four in week 1.
  * Clusters are the connected components of the pairs with Pearson >= 0.95 over >= 8 common weeks (2025 plus 2026 so
    far).
  * "Same event last season" matches the event name exactly; the event key carries the year, so it cannot be used.
  * Package size: measured as `json.dumps(package)` with default separators (the more conservative form).
  * Canaries: values whose repr is shorter than 6 characters (0.0, 1.0, 0.05, ...) are skipped, because they appear in
    any JSON by chance; non-finite values are skipped.
"""

from __future__ import annotations

import json
import math
from collections import Counter

import numpy as np

from racinglines.research.jev_desk import NON_CONFIG, TAKER_MODES, build_menu, cfg_hash, settings_words  # noqa: F401

REFERENCE_BANKROLL = 10_000.0
PKG_CAP = 8_000
SHORTLIST_CAP = 40
TOP_N = 10
CLONE_CORR = 0.95
MIN_COMMON_WEEKS = 8
YEAR = 2026
PREV = YEAR - 1
MIN_CANARY_LEN = 6


# ---------------------------------------------------------------- loading

def load_events(engine) -> dict:
    """Read-only: {event_key: {"name": str, "date": "YYYY-MM-DD"}} for F1 timing events (all seasons)."""
    from sqlalchemy import text
    q = text("select e.source_key, e.name, e.start_date from events e join seasons s on s.id = e.season_id "
             "where e.source = 'f1timing' order by e.source_key")
    out = {}
    with engine.connect() as c:
        for r in c.execute(q):
            out[r.source_key] = {"name": r.name, "date": r.start_date.isoformat() if r.start_date else None}
    return out


# ---------------------------------------------------------------- small helpers

def _finite(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def _norm_runs(runs):
    """Shallow copies whose weekends carry `round` (some stored rows say `r`)."""
    out = []
    for run in runs:
        ws = []
        for w in run.get("weekends") or []:
            w = dict(w)
            if w.get("round") is None and w.get("r") is not None:
                w["round"] = w["r"]
            ws.append(w)
        out.append({**run, "weekends": ws})
    return out


def _round_meta(runs):
    """{year: {round: {"key","name","format"}}}: calendar facts, first non-null value over all runs; no outcomes."""
    meta = {}
    for run in runs:
        y = run["year"]
        for w in run["weekends"]:
            if w.get("round") is None:
                continue
            m = meta.setdefault(y, {}).setdefault(int(w["round"]), {"key": None, "name": None, "format": None})
            for dst, src in (("key", "event_key"), ("name", "event"), ("format", "format")):
                if m[dst] is None and w.get(src) is not None:
                    m[dst] = w[src]
    return meta


def _is_untuned(params) -> bool:
    p = params or {}
    return p.get("label") is not None and p.get("label") == p.get("variant")


def _pct(x, nd=1):
    return round(100.0 * x, nd)


def _stats(rets):
    """Summary of a list of weekly returns (fractions), as percent. Arithmetic sums, additive drawdown path."""
    if not rets:
        return None
    best2 = sorted(range(len(rets)), key=lambda i: (-rets[i], i))[:2]
    ex2 = sum(r for i, r in enumerate(rets) if i not in best2)
    peak = cum = dd = 0.0
    for r in rets:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {"tot": _pct(sum(rets), 2), "up": sum(r > 0 for r in rets), "n": len(rets), "ex2": _pct(ex2, 2),
            "dd": _pct(dd, 2)}


def _dump(x):
    return json.dumps(x)


# ---------------------------------------------------------------- clone clustering

def _clusters(ids, series):
    """Connected components of Pearson >= CLONE_CORR over >= MIN_COMMON_WEEKS common weeks.

    series: {id: {week_key: return}}. Returns {id: root_id} with the lowest id as root.
    """
    n = len(ids)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    weeks = sorted({w for s in series.values() for w in s})
    if n > 1 and len(weeks) >= MIN_COMMON_WEEKS:
        col = {w: j for j, w in enumerate(weeks)}
        X = np.zeros((n, len(weeks)))
        M = np.zeros((n, len(weeks)))
        for i, sid in enumerate(ids):
            for w, v in series[sid].items():
                if _finite(v):
                    X[i, col[w]] = v
                    M[i, col[w]] = 1.0
        X2 = X * X
        block = 256
        for a in range(0, n, block):
            b = min(n, a + block)
            Xi, Mi, X2i = X[a:b], M[a:b], X2[a:b]
            cnt = Mi @ M.T
            sx = Xi @ M.T
            sy = Mi @ X.T
            sxy = Xi @ X.T
            sxx = X2i @ M.T
            syy = Mi @ X2.T
            with np.errstate(divide="ignore", invalid="ignore"):
                cov = sxy - sx * sy / cnt
                vx = sxx - sx * sx / cnt
                vy = syy - sy * sy / cnt
                r = cov / np.sqrt(vx * vy)
            ok = (cnt >= MIN_COMMON_WEEKS) & (vx > 1e-14) & (vy > 1e-14) & (r >= CLONE_CORR - 1e-12)
            for ii, jj in zip(*np.nonzero(ok)):
                i = a + ii
                if jj > i:
                    ra, rb = find(i), find(int(jj))
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
    return {ids[i]: ids[find(i)] for i in range(n)}


# ---------------------------------------------------------------- packages (pure; works on a copied snapshot only)

def _build_packages(snap):
    """snap: copied data only. {"round", "event": {...round r non-outcome...}, "meta": {year: {round: meta}},
    "strats": {sid: {"mode","kelly","n_sims","words","r25","r26"}}} where r26 holds rounds < round only."""
    rnd = snap["round"]
    strats = snap["strats"]
    meta = snap["meta"]
    ev = snap["event"]
    ids = sorted(strats)
    notes = {}

    # -- event
    last_names = {m["name"] for m in meta.get(PREV, {}).values() if m.get("name")}
    event = {"name": ev["name"], "round": rnd, "date": ev["date"], "format": ev["format"],
             "raced_last_season": bool(ev["name"] and ev["name"] in last_names),
             "rounds_raced": sum(1 for r in meta.get(YEAR, {}) if r < rnd)}

    # -- family summary (as-of): group by (mode, sizing)
    groups = {}
    for sid in ids:
        s = strats[sid]
        sizing = "flat" if s["kelly"] is None else f"kelly {s['kelly']}"
        groups.setdefault((s["mode"], sizing), []).append(sid)

    def agg(vals):
        if not vals:
            return None
        return {"med": _pct(float(np.median(vals)), 2), "best": _pct(max(vals), 2), "worst": _pct(min(vals), 2),
                "pos": round(sum(v > 0 for v in vals) / len(vals), 2)}

    family = []
    for (mode, sizing) in sorted(groups):
        g = groups[(mode, sizing)]
        t25 = [sum(strats[i]["r25"].values()) for i in g]
        t26 = [sum(strats[i]["r26"].values()) for i in g if strats[i]["r26"]]
        family.append({"mode": mode, "sizing": sizing, "n": len(g), "y25": agg(t25), "y26": agg(t26)})
    fam_cut = 0
    while family and len(_dump(family)) > PKG_CAP:
        family.pop()
        fam_cut += 1

    # -- per-strategy time-ordered series (as-of)
    def ordered(s):
        return [(PREV, r, s["r25"][r]) for r in sorted(s["r25"])] + [(YEAR, r, s["r26"][r]) for r in sorted(s["r26"])]

    # -- clone clusters on as-of series
    series = {sid: {(y, r): v for y, r, v in ordered(strats[sid])} for sid in ids}
    root = _clusters(ids, series)
    members = {}
    for sid, rt in root.items():
        members.setdefault(rt, []).append(sid)
    reps = {}
    for rt, mem in members.items():
        rep = sorted(mem, key=lambda i: (-(strats[i]["n_sims"] or 0), i))[0]
        reps[rep] = len(mem)

    # -- criteria
    st25 = {i: _stats([strats[i]["r25"][r] for r in sorted(strats[i]["r25"])]) for i in reps}
    st26 = {i: _stats([strats[i]["r26"][r] for r in sorted(strats[i]["r26"])]) for i in reps}
    last4 = {}
    for i in reps:
        o = [v for _, _, v in ordered(strats[i])][-4:]
        last4[i] = o
    crit = {}
    skipped = []

    def top(name, items):  # items: [(sid, value)], bigger is better
        items = [(i, v) for i, v in items if _finite(v)]
        crit[name] = [i for i, _ in sorted(items, key=lambda t: (-t[1], t[0]))[:TOP_N]]

    top("t25", [(i, st25[i]["tot"]) for i in reps if st25[i]])
    if any(st26[i] for i in reps):
        top("t26", [(i, st26[i]["tot"]) for i in reps if st26[i]])
    else:
        crit["t26"] = []
        skipped.append("t26")
    top("x2", [(i, st25[i]["ex2"]) for i in reps if st25[i]])
    top("l4", [(i, sum(last4[i])) for i in reps if last4[i]])
    top("dd", [(i, -st25[i]["dd"]) for i in reps if st25[i] and st25[i]["tot"] > 0])

    hits = {}
    for name, lst in crit.items():
        for i in lst:
            hits.setdefault(i, []).append(name)
    pool = sorted(hits, key=lambda i: (-len(hits[i]), -st25[i]["tot"], i))
    notes["criteria_skipped"] = skipped

    # -- shortlist records
    fmt = {}
    for y in (PREV, YEAR):
        for r, m in meta.get(y, {}).items():
            fmt[(y, r)] = m.get("format")
    last_round_for_name = None
    if ev["name"]:
        for r, m in meta.get(PREV, {}).items():
            if m.get("name") == ev["name"]:
                last_round_for_name = r

    def mean_pct(vals):
        return _pct(sum(vals) / len(vals), 2) if vals else None

    def record(i):
        s = strats[i]
        spr = [v for y, r, v in ordered(s) if fmt.get((y, r)) == "sprint"]
        con = [v for y, r, v in ordered(s) if fmt.get((y, r)) == "conventional"]
        same = s["r25"].get(last_round_for_name) if last_round_for_name is not None else None
        return {"id": i, "set": s["words"], "cl": reps[i], "c": hits[i], "y25": st25[i], "y26": st26[i],
                "l4": [_pct(v) for v in last4[i]], "ly": None if same is None else _pct(same),
                "spr": mean_pct(spr), "con": mean_pct(con),
                "w25": [_pct(s["r25"][r]) for r in sorted(s["r25"])],
                "w26": [_pct(s["r26"][r]) for r in sorted(s["r26"])]}

    shortlist = [record(i) for i in pool[:SHORTLIST_CAP]]
    over_cap = max(0, len(pool) - SHORTLIST_CAP)
    cut = 0
    while shortlist and len(_dump(shortlist)) > PKG_CAP:
        shortlist.pop()
        cut += 1

    notes.update({
        "strategies": len(ids), "clusters": len(reps), "collapsed_as_clones": len(ids) - len(reps),
        "criteria_hit_pool": len(pool), "shortlist": len(shortlist),
        "shortlist_cut_by_cap_40": over_cap, "shortlist_cut_by_size_cap": cut,
        "family_summary_cut_by_size_cap": fam_cut,
        "size_cap_chars": PKG_CAP,
        "weekly_lists": "w25 = every 2025 round in order; w26 = 2026 rounds before this one, in order; percent",
        "criteria": {"t25": "top 10 by 2025 total", "t26": "top 10 by 2026-so-far total",
                     "x2": "top 10 by 2025 total without best two weeks", "l4": "top 10 by last four weeks",
                     "dd": "smallest 2025 worst drawdown among positive 2025 totals"},
    })
    return {"event": event, "family_summary": family, "shortlist": shortlist, "notes": notes}


# ---------------------------------------------------------------- the public classes

class View:
    """What Jev may see. Holds only its own copied outputs."""

    def __init__(self, round_no, packages, shortlist_ids):
        self.round_no = round_no
        self.packages = packages
        self.shortlist_ids = shortlist_ids


class Universe:
    def __init__(self):
        self._s = {}          # sid -> record
        self._meta = {}       # {year: {round: {key,name,format}}}
        self._events = {}
        self._report = {}
        self.ids = []
        self._subset, self._sizing = "all", "all"

    @classmethod
    def from_runs(cls, runs, events=None, sizing="all", subset="all") -> "Universe":
        """sizing "flat" drops the Kelly strategies (a robustness run); subset "untuned" keeps only the strategies
        whose stored run is a plain default-settings variant sweep (params label == variant). Ids are numbered after
        the filters."""
        runs = _norm_runs(runs)
        menu, rep = build_menu(runs, REFERENCE_BANKROLL, YEAR)
        if sizing == "flat":
            menu = [c for c in menu if c["kelly"] is None]
        elif sizing != "all":
            raise ValueError("sizing must be 'all' or 'flat'")
        if subset == "untuned":
            menu = [c for c in menu if _is_untuned(c.get("params"))]
        elif subset != "all":
            raise ValueError("subset must be 'all' or 'untuned'")
        u = cls()
        u._subset, u._sizing = subset, sizing
        u._meta = _round_meta(runs)
        u._events = dict(events or {})
        menu.sort(key=lambda c: (c["cfg_hash"], c["mode"]))
        for n, c in enumerate(menu, 1):
            sid = f"S{n:04d}"
            u._s[sid] = {
                "mode": c["mode"], "kelly": c["kelly"], "n_sims": c["n_sims"], "params": c["params"],
                "words": u._words(c),
                "ret": {y: {r: d["ret"] for r, d in c["series"][y].items()} for y in (PREV, YEAR)},
                "bought": {y: {r: d["bought"] for r, d in c["series"][y].items()} for y in (PREV, YEAR)},
                "pnl": {y: {r: d["pnl"] for r, d in c["series"][y].items()} for y in (PREV, YEAR)},
            }
        u.ids = list(u._s)
        u._report = rep
        return u

    @staticmethod
    def _words(c):
        w, p = c["settings_words"], c.get("params") or {}
        venue = (p.get("settings") or {}).get("venue") or "polymarket"
        parts = [f"variant {w['variant']}", f"{w['taker_mode']} mode", w["sizing"], f"venue {venue}",
                 f"min edge {w['min_edge']}"]
        if p.get("min_edge_h2h") is not None:
            parts.append(f"head-to-head min edge {p['min_edge_h2h']}")
        if p.get("min_volume_24h") is not None:
            parts.append(f"min 24h volume {p['min_volume_24h']:g}")
        if p.get("taker_fee"):
            parts.append(f"taker fee {p['taker_fee']}")
        parts.append(f"n_sims {w['n_sims']}")
        return ", ".join(parts)

    def untuned_ids(self) -> set:
        """Ids in this universe whose params have label == variant (a plain default-settings variant sweep)."""
        return {sid for sid, s in self._s.items() if _is_untuned(s.get("params"))}

    def describe(self, sid) -> str:
        return self._s[sid]["words"]

    def rounds(self, year=YEAR) -> list:
        return sorted({r for s in self._s.values() for r in s["ret"].get(year, {})})

    def ret(self, sid, year, rnd):
        return self._s[sid]["ret"].get(year, {}).get(rnd)

    def total(self, sid, year, upto=None) -> float:
        d = self._s[sid]["ret"].get(year, {})
        return float(sum(v for r, v in d.items() if upto is None or r < upto))

    def find_profile_a(self):
        hit = [sid for sid, s in self._s.items()
               if s["mode"] == "update" and s["kelly"] is None
               and s["params"].get("variant") == "gridq+pretrain+reset"
               and s["params"].get("min_edge") == 0.1 and s["n_sims"] == 16000
               and s["params"].get("min_edge_h2h") == 0.05 and s["params"].get("min_volume_24h") == 50
               and not (s["params"].get("settings") or {}).get("venue") and not s["params"].get("taker_fee")]
        return hit[0] if len(hit) == 1 else None

    def meta(self) -> dict:
        return {"strategies": len(self.ids), "subset": self._subset, "rounds": self.rounds(),
                "rounds_prev": self.rounds(PREV),
                "n_sims": dict(sorted(Counter(str(s["n_sims"]) for s in self._s.values()).items())),
                "kelly": sum(s["kelly"] is not None for s in self._s.values()),
                "by_mode": dict(sorted(Counter(s["mode"] for s in self._s.values()).items())),
                "skipped": list(self._report.get("skipped", [])),
                "run_ids": list(self._report.get("run_ids", [])),
                "note": "Blends and makers are out of this universe: blend components (T-numbers) are not "
                        "identifiable from stored params, and only taker modes are listed."}

    def canaries(self, round_no) -> set:
        out = set()
        for s in self._s.values():
            for key in ("ret", "bought", "pnl"):
                for r, v in s[key].get(YEAR, {}).items():
                    if r >= round_no and _finite(v):
                        t = repr(float(v))
                        if len(t) >= MIN_CANARY_LEN:
                            out.add(t)
        return out

    def view(self, round_no: int) -> View:
        m26 = self._meta.get(YEAR, {}).get(round_no) or {}
        ekey = m26.get("key")
        evt = self._events.get(ekey) or {}
        snap = {
            "round": round_no,
            # round r: non-outcome fields only (name, key, format, date)
            "event": {"name": m26.get("name") or evt.get("name"), "key": ekey, "format": m26.get("format"),
                      "date": evt.get("date")},
            "meta": {PREV: {r: dict(m) for r, m in self._meta.get(PREV, {}).items()},
                     YEAR: {r: dict(m) for r, m in self._meta.get(YEAR, {}).items() if r < round_no}},
            "strats": {sid: {"mode": s["mode"], "kelly": s["kelly"], "n_sims": s["n_sims"], "words": s["words"],
                             "r25": dict(s["ret"].get(PREV, {})),
                             "r26": {r: v for r, v in s["ret"].get(YEAR, {}).items() if r < round_no}}
                       for sid, s in self._s.items()},
        }
        pk = _build_packages(snap)
        return View(round_no, pk, [r["id"] for r in pk["shortlist"]])
