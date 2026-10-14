"""Statistics for the Jev gate pre-registration (reports/2026-10-14-jev-gate/PREREG.md).

Pure functions on lists of dicts: no database, no network. numpy only.

AUC here is P(a losing trade's score > a winning trade's score), ties 0.5.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

KEYS = ("mm", "se", "gcc")
SIDES = ("NO", "YES", "all")
MIN_PER_CLASS = 5
ALPHA = 0.025
H1_MAX_AUC = 0.35
H2_MIN_AUC = 0.65
MIN_SUBSET_RACES = 15
_EPS = 1e-9


def _midranks(x: np.ndarray) -> np.ndarray:
    """1-based midranks (ties share the mean rank)."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    n = len(x)
    ranks = np.empty(n, dtype=float)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def auc_loser_gt_winner(scores, won) -> float:
    """P(random losing trade's score > random winning trade's), ties 0.5; nan if a class is empty."""
    s = np.asarray(scores, dtype=float)
    w = np.asarray(won, dtype=bool)
    n_w = int(w.sum())
    n_l = int((~w).sum())
    if n_w == 0 or n_l == 0:
        return float("nan")
    ranks = _midranks(s)
    u = ranks[~w].sum() - n_l * (n_l + 1) / 2.0
    return float(u / (n_l * n_w))


def perm_p(scores, won, tail: str, n: int = 20000, seed: int = 1) -> float:
    """One-sided permutation p for the AUC. tail 'low': P(perm <= obs); 'high': P(perm >= obs)."""
    if tail not in ("low", "high"):
        raise ValueError("tail must be 'low' or 'high'")
    s = np.asarray(scores, dtype=float)
    w = np.asarray(won, dtype=bool)
    n_w = int(w.sum())
    n_l = int((~w).sum())
    if n_w == 0 or n_l == 0:
        return float("nan")
    N = len(s)
    ranks = _midranks(s)
    base = n_l * (n_l + 1) / 2.0
    denom = n_l * n_w
    obs_u = ranks[~w].sum() - base
    rng = np.random.default_rng(seed)
    count = 0
    chunk = max(1, min(n, 2_000_000 // max(N, 1)))
    done = 0
    while done < n:
        m = min(chunk, n - done)
        idx = np.argsort(rng.random((m, N)), axis=1)[:, :n_l]
        u = ranks[idx].sum(axis=1) - base
        if tail == "low":
            count += int((u <= obs_u + _EPS).sum())
        else:
            count += int((u >= obs_u - _EPS).sum())
        done += m
    _ = denom
    return float((count + 1) / (n + 1))


def cluster_boot_ci(scores, won, race_ids, n: int = 2000, seed: int = 1) -> tuple[float, float]:
    """95% percentile CI of the AUC, resampling whole races with replacement."""
    s = np.asarray(scores, dtype=float)
    w = np.asarray(won, dtype=bool)
    r = np.asarray(race_ids)
    uniq = np.unique(r)
    if len(uniq) < 2:
        return (float("nan"), float("nan"))
    groups = [np.flatnonzero(r == u) for u in uniq]
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), size=len(groups))
        idx = np.concatenate([groups[k] for k in pick])
        a = auc_loser_gt_winner(s[idx], w[idx])
        if not math.isnan(a):
            vals.append(a)
    if len(vals) < max(10, n // 2):
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return (float(lo), float(hi))


def _arrays(rows, key):
    s = np.array([float(r[key]) for r in rows], dtype=float)
    w = np.array([bool(r["won"]) for r in rows], dtype=bool)
    race = np.array([r["race_id"] for r in rows])
    return s, w, race


def _basic(rows, key) -> dict:
    s, w, _ = _arrays(rows, key)
    return {
        "n": len(rows),
        "losers": int((~w).sum()),
        "winners": int(w.sum()),
        "auc": auc_loser_gt_winner(s, w) if len(rows) else float("nan"),
    }


def _by_side(rows, side):
    return rows if side == "all" else [r for r in rows if r["side"] == side]


def _full_test(rows, key, tail, n_perm, n_boot) -> dict:
    s, w, race = _arrays(rows, key)
    out: dict[str, Any] = {
        "n": len(rows),
        "losers": int((~w).sum()),
        "winners": int(w.sum()),
    }
    if out["losers"] < MIN_PER_CLASS or out["winners"] < MIN_PER_CLASS:
        out.update(auc=float("nan"), p=float("nan"), ci=(float("nan"), float("nan")),
                   status="insufficient")
        return out
    out["auc"] = auc_loser_gt_winner(s, w)
    out["p"] = perm_p(s, w, tail, n=n_perm)
    out["ci"] = cluster_boot_ci(s, w, race, n=n_boot)
    out["status"] = "ok"
    return out


def _decide(rows, n_perm, n_boot) -> dict:
    """H1/H2 + mm_report on the given NO buys."""
    no = [r for r in rows if r["side"] == "NO"]
    res = {}
    for name, key, tail in (("H1", "se", "low"), ("H2", "gcc", "high")):
        t = _full_test(no, key, tail, n_perm, n_boot)
        t["key"] = key
        t["tail"] = tail
        if t["status"] == "insufficient":
            t.update(p_ok=False, ci_ok=False, effect_ok=False, confirmed=False)
        else:
            lo, hi = t["ci"]
            t["p_ok"] = bool(t["p"] < ALPHA)
            t["ci_ok"] = bool(not math.isnan(lo) and (hi < 0.5 or lo > 0.5))
            t["effect_ok"] = bool(t["auc"] <= H1_MAX_AUC if name == "H1" else t["auc"] >= H2_MIN_AUC)
            t["confirmed"] = t["p_ok"] and t["ci_ok"] and t["effect_ok"]
        res[name] = t
    return res


def _tercile_stats(group) -> dict:
    n = len(group)
    pnl = sum(float(r["pnl"]) for r in group)
    wins = sum(1 for r in group if r["won"])
    by_event: dict[str, float] = {}
    for r in group:
        by_event[r["event_key"]] = by_event.get(r["event_key"], 0.0) + float(r["pnl"])
    best = sorted(by_event, key=lambda k: by_event[k], reverse=True)[:2]
    ex = sum(v for k, v in by_event.items() if k not in best)
    ses = [float(r["se"]) for r in group]
    return {
        "n": n,
        "win_rate": wins / n if n else float("nan"),
        "pnl": pnl,
        "pnl_ex_best2": ex,
        "se_min": min(ses) if ses else float("nan"),
        "se_max": max(ses) if ses else float("nan"),
        "dropped_events": best,
    }


def _terciles(rows) -> list[dict]:
    no = sorted((r for r in rows if r["side"] == "NO"), key=lambda r: float(r["se"]))  # stable
    n = len(no)
    cuts = [0, n // 3, (2 * n) // 3, n]
    return [_tercile_stats(no[cuts[i] : cuts[i + 1]]) for i in range(3)]


def analyse(rows, exploration_ids, n_perm: int = 20000, n_boot: int = 2000) -> dict:
    rows = list(rows)
    ex_ids = set(exploration_ids)
    explore = [r for r in rows if r["id"] in ex_ids]
    confirm = [r for r in rows if r["id"] not in ex_ids]
    groups = {"explore": explore, "confirm": confirm, "pooled": rows}

    sets = {g: {side: {k: _basic(_by_side(gr, side), k) for k in KEYS} for side in SIDES}
            for g, gr in groups.items()}

    decision = _decide(confirm, n_perm, n_boot)
    mm_report = _full_test([r for r in confirm if r["side"] == "NO"], "mm", "high", n_perm, n_boot)
    mm_report["key"] = "mm"
    mm_report["tail"] = "high"

    terciles = {"confirm": _terciles(confirm), "pooled": _terciles(rows)}

    stages = {}
    for st in sorted({r["stage"] for r in rows}):
        sr = [r for r in rows if r["stage"] == st]
        stages[st] = {side: {k: _basic(_by_side(sr, side), k) for k in KEYS} for side in SIDES}

    ex_races = {r["race_id"] for r in explore}
    conf_races = {r["race_id"] for r in confirm}
    shared = conf_races & ex_races
    absent = conf_races - ex_races
    overlap = {
        "confirm_races": len(conf_races),
        "in_exploration": len(shared),
        "share": len(shared) / len(conf_races) if conf_races else float("nan"),
        "absent_races": len(absent),
    }
    if len(absent) >= MIN_SUBSET_RACES:
        sub = [r for r in confirm if r["race_id"] in absent]
        decision_subset = _decide(sub, n_perm, n_boot)
    else:
        decision_subset = None

    return {
        "sets": sets,
        "decision": decision,
        "mm_report": mm_report,
        "terciles": terciles,
        "stages": stages,
        "overlap": overlap,
        "decision_subset": decision_subset,
    }


def _f(x, nd=3) -> str:
    return "nan" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def _verdict(t) -> str:
    if t["status"] == "insufficient":
        return "INSUFFICIENT"
    return "CONFIRMED" if t["confirmed"] else "NOT CONFIRMED"


def _fmt_decision(title, dec, lines) -> None:
    lines.append(title)
    for name, crit in (("H1", "stale_edge: AUC<=0.35, p<0.025, CI excludes 0.5"),
                       ("H2", "gap_cause conf: AUC>=0.65, p<0.025, CI excludes 0.5")):
        t = dec[name]
        lines.append(f"  {name} ({crit}) -> {_verdict(t)}")
        lo, hi = t["ci"]
        lines.append(f"    NO buys n={t['n']} losers={t['losers']} winners={t['winners']} "
                     f"AUC={_f(t['auc'])} p={_f(t['p'], 4)} CI=({_f(lo)}, {_f(hi)})")
        if t["status"] == "insufficient":
            lines.append(f"    fewer than {MIN_PER_CLASS} signals in a class: not computed")
        else:
            lines.append(f"    p<0.025: {t['p_ok']}  CI excludes 0.5: {t['ci_ok']}  effect size: {t['effect_ok']}")


def format_report(result: dict) -> str:
    L: list[str] = []
    L.append("JEV GATE: pre-registered confirmation run")
    L.append("=" * 60)
    _fmt_decision("DECISION (confirmation set, NO buys)", result["decision"], L)
    m = result["mm_report"]
    lo, hi = m["ci"]
    L.append("")
    L.append("model_missing on confirmation NO buys (reported, not a hypothesis)")
    L.append(f"  n={m['n']} losers={m['losers']} winners={m['winners']} AUC={_f(m['auc'])} "
             f"p(high)={_f(m['p'], 4)} CI=({_f(lo)}, {_f(hi)}) [{m['status']}]")

    ov = result["overlap"]
    L.append("")
    L.append(f"OVERLAP: {ov['in_exploration']} of {ov['confirm_races']} confirmation races also in exploration "
             f"(share {_f(ov['share'], 2)}); {ov['absent_races']} absent")
    if result["decision_subset"] is not None:
        _fmt_decision("DECISION on races absent from exploration", result["decision_subset"], L)
    else:
        L.append(f"  fewer than {MIN_SUBSET_RACES} absent races: subset decision not computed")

    L.append("")
    L.append("AUC (loser > winner) BY SET, SIDE, ANSWER")
    L.append(f"  {'set':8}{'side':5}{'key':4}{'n':>5}{'lose':>6}{'win':>5}{'auc':>8}")
    for g, d in result["sets"].items():
        for side in SIDES:
            for k in KEYS:
                b = d[side][k]
                L.append(f"  {g:8}{side:5}{k:4}{b['n']:>5}{b['losers']:>6}{b['winners']:>5}{_f(b['auc']):>8}")

    L.append("")
    L.append("AUC BY STAGE (pooled)")
    L.append(f"  {'stage':16}{'side':5}{'key':4}{'n':>5}{'lose':>6}{'win':>5}{'auc':>8}")
    for st, d in result["stages"].items():
        for side in SIDES:
            for k in KEYS:
                b = d[side][k]
                L.append(f"  {str(st)[:15]:16}{side:5}{k:4}{b['n']:>5}{b['losers']:>6}{b['winners']:>5}{_f(b['auc']):>8}")

    for g in ("confirm", "pooled"):
        L.append("")
        L.append(f"NO BUYS BY stale_edge TERCILE ({g}); hold-to-settle P&L")
        L.append(f"  {'tercile':8}{'n':>5}{'win%':>8}{'se range':>20}{'pnl':>10}{'ex best 2 wknds':>17}")
        for i, t in enumerate(result["terciles"][g], 1):
            rng = f"{_f(t['se_min'])}..{_f(t['se_max'])}"
            L.append(f"  {i:<8}{t['n']:>5}{_f(100 * t['win_rate'], 1):>8}{rng:>20}"
                     f"{_f(t['pnl'], 2):>10}{_f(t['pnl_ex_best2'], 2):>17}")

    L.append("")
    L.append("Reminder: hold-to-settle AUC says nothing about size; it does not show a gate would make money.")
    return "\n".join(L)
