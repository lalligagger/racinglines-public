"""Research: can Jev rank stored sweep strategies for the coming race weekend? Spec: reports/2026-10-14-jev-desk/PREREG.md.

Paper research off the live path: no order, no setting, no database write. The only database touch is `load_runs`
(a read-only SELECT). Everything else is pure and testable. Answers are cached on disk keyed by sha256 of
state + question + model, so a rerun costs nothing; `plan` counts the API calls a run would make without any network.
`typesafe_sdk` is a research-only dependency, imported lazily inside `jev_gate.make_client`.

Interpretations of the PREREG (each also listed in the CLI's SOURCES.md):
  * A config is `params` without `year`, `label`, `rounds`, `mode`, `n_sims`, `data_key` and `weekends`. `n_sims` is left out so that "the run
    with the most `n_sims` per (config, year)" is meaningful and 2025 and 2026 runs at different `n_sims` pair up.
  * Flat or Kelly with `k` picks: each pick gets weight 1/k of the bankroll (flat: 1/k of the stored dollar P&L).
  * Blends (TB etc.) are not built: the docs name them by T-numbers that the stored params do not carry.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from racinglines.research.jev_gate import DEFAULT_MODEL, make_client
from racinglines.research.jev_gate_stats import _midranks, auc_loser_gt_winner

CACHE_DIR = Path("data/runs/jev_desk/cache")
TAKER_MODES = ("update", "hold", "early", "last")
NON_CONFIG = {"year", "label", "rounds", "mode", "n_sims", "data_key", "weekends"}   # the last two describe the season, not the strategy
N_BOOT = 5000
SEED = 1
_ = _midranks  # re-exported for callers that want the same tie handling

QUESTION = {
    "profit": {
        "type": "noul",
        "instructions": (
            "A taker strategy trades Formula 1 prediction markets once per race weekend. Will the strategy "
            "described in `strategy` finish the weekend named in `upcoming_event` with a profit (more than zero "
            "dollars after fees)? The evidence is `strategy.settings`, `season_previous` (its weekly returns in "
            "percent of its balance, by round, with `summary`), `season_current_so_far` (the same for the rounds "
            "already raced this season, earlier than `upcoming_event`) and `same_event_previous_season_return_pct` "
            "(its return at the same event last season, null if that event was not raced)."
        ),
        "criteria": {
            "true": "The strategy finishes the upcoming weekend with a profit after fees.",
            "false": "The strategy finishes the upcoming weekend flat or with a loss after fees.",
        },
    },
}


# ---------------------------------------------------------------- loading

def load_runs(engine):
    """Read-only: F1 sweep runs with mode 'update' as dicts {id, year, params, weekends}."""
    from sqlalchemy import text
    q = text("select id, params, metrics from model_runs where kind = 'sweep' and params->>'mode' = 'update' "
             "order by id")
    out = []
    with engine.connect() as c:
        for r in c.execute(q):
            params = r.params or {}
            weekends = ((r.metrics or {}).get("weekends")) or []
            if params.get("year") is None or not weekends:
                continue
            out.append({"id": r.id, "year": int(params["year"]), "params": params, "weekends": weekends})
    return out


# ---------------------------------------------------------------- menu

def cfg_hash(params):
    cfg = {k: v for k, v in params.items() if k not in NON_CONFIG}
    return hashlib.md5(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()


def _num(x):
    return None if x is None else float(x)


def _mode_series(weekends, mode, bankroll, kelly):
    """{round: {pnl, bought, event, ret}} for one mode; ret = pnl / balance at start of that week (Kelly) or / B0 (flat)."""
    rows = []
    for w in weekends:
        pnl = _num(w.get(f"{mode}_pnl"))
        if pnl is None or w.get("round") is None:
            continue
        rows.append((int(w["round"]), pnl, _num(w.get(f"{mode}_bought")), w.get("event")))
    rows.sort(key=lambda r: r[0])
    out, cum = {}, 0.0
    for rnd, pnl, bought, event in rows:
        base = bankroll + cum if kelly else bankroll
        out[rnd] = {"pnl": pnl, "bought": bought, "event": event, "ret": pnl / base if base else 0.0}
        cum += pnl
    return out


def settings_words(params, mode):
    k = params.get("kelly")
    return {
        "variant": params.get("variant"),
        "taker_mode": mode,
        "sizing": "flat stake" if k is None else f"Kelly fraction {k}",
        "min_edge": params.get("min_edge"),
        "n_sims": params.get("n_sims"),
    }


def build_menu(runs, bankroll, year=2026):
    """Candidates per the PREREG menu rule, plus a menu_report dict."""
    prev = year - 1
    best = {}  # (cfg, year) -> run with most n_sims (ties: highest id)
    for r in runs:
        if r["year"] not in (prev, year):
            continue
        k = (cfg_hash(r["params"]), r["year"])
        rank = (r["params"].get("n_sims") or 0, r["id"])
        if k not in best or rank > (best[k]["params"].get("n_sims") or 0, best[k]["id"]):
            best[k] = r
    report = {"runs_seen": len(runs), "configs_with_both_years": 0, "candidates": 0, "kelly_candidates": 0,
              "n_sims": {}, "run_ids": [], "skipped": []}
    menu = []
    for h in sorted({k[0] for k in best}):
        a, b = best.get((h, prev)), best.get((h, year))
        if a is None or b is None:
            report["skipped"].append(f"config {h[:8]}: only {'current' if a is None else 'previous'} year")
            continue
        report["configs_with_both_years"] += 1
        kelly = b["params"].get("kelly")
        used = False
        for mode in TAKER_MODES:
            sa = _mode_series(a["weekends"], mode, bankroll, kelly is not None)
            sb = _mode_series(b["weekends"], mode, bankroll, kelly is not None)
            if not sa or not sb:
                report["skipped"].append(f"config {h[:8]} {mode}: no P&L in both years")
                continue
            used = True
            menu.append({"key": f"{h[:10]}:{mode}", "mode": mode, "cfg_hash": h, "kelly": kelly,
                         "n_sims": b["params"].get("n_sims"), "n_sims_prev": a["params"].get("n_sims"),
                         "params": b["params"], "settings_words": settings_words(b["params"], mode),
                         "series": {prev: sa, year: sb}})
        if used:
            report["run_ids"] += [a["id"], b["id"]]
    menu.sort(key=lambda c: c["key"])
    report["candidates"] = len(menu)
    report["kelly_candidates"] = sum(c["kelly"] is not None for c in menu)
    report["n_sims"] = dict(sorted(Counter(str(c["n_sims"]) for c in menu).items()))
    report["run_ids"] = sorted(set(report["run_ids"]))
    report["blends"] = "skipped: components (T-numbers) are not identifiable from stored params"
    return menu, report


# ---------------------------------------------------------------- series statistics

def _equity(rets, kelly):
    """Multiplicative (Kelly) or additive (flat) equity path in units of B0, starting at 1."""
    path, v = [1.0], 1.0
    for r in rets:
        v = v * (1 + r) if kelly else v + r
        path.append(v)
    return path


def _total(rets, kelly):
    return _equity(rets, kelly)[-1] - 1.0


def summary(rets, kelly):
    if not rets:
        return {"weeks": 0, "weeks_up": 0, "total_return_pct": 0.0, "total_ex_best_two_pct": 0.0,
                "worst_drawdown_pct": 0.0}
    drop = sorted(range(len(rets)), key=lambda i: (-rets[i], i))[:2]
    rest = [r for i, r in enumerate(rets) if i not in drop]
    path = _equity(rets, kelly)
    peak, dd = path[0], 0.0
    for v in path:
        peak = max(peak, v)
        dd = max(dd, (peak - v) / peak if peak else 0.0)
    return {"weeks": len(rets), "weeks_up": sum(r > 0 for r in rets),
            "total_return_pct": round(100 * _total(rets, kelly), 3),
            "total_ex_best_two_pct": round(100 * _total(rest, kelly), 3),
            "worst_drawdown_pct": round(-100 * dd, 3)}


def _rets(cand, yr, below=None):
    s = cand["series"].get(yr, {})
    return [s[r]["ret"] for r in sorted(s) if below is None or r < below]


def week_state(cand, round_no, event_name, year=2026):
    """The state for one (week, candidate). Nothing from `year` rounds >= round_no."""
    kelly = cand["kelly"] is not None
    prev, cur = year - 1, year
    p_rounds = sorted(cand["series"].get(prev, {}))
    c_rounds = sorted(r for r in cand["series"].get(cur, {}) if r < round_no)
    same = None
    for r in p_rounds:
        if event_name and cand["series"][prev][r]["event"] == event_name:
            same = round(100 * cand["series"][prev][r]["ret"], 3)
    pr = [cand["series"][prev][r]["ret"] for r in p_rounds]
    cr = [cand["series"][cur][r]["ret"] for r in c_rounds]
    return {
        "strategy": {"settings": cand["settings_words"]},
        "upcoming_event": event_name,
        "season_previous": {"rounds": p_rounds, "weekly_returns_pct": [round(100 * x, 3) for x in pr],
                            "summary": summary(pr, kelly)},
        "season_current_so_far": {"rounds": c_rounds, "weekly_returns_pct": [round(100 * x, 3) for x in cr],
                                  "summary": summary(cr, kelly)},
        "same_event_previous_season_return_pct": same,
    }


def weeks_of(menu, year=2026, limit=None):
    """[(round, event name)] for the target year, in order."""
    ev = {}
    for c in menu:
        for r, d in c["series"].get(year, {}).items():
            if r not in ev or (ev[r] is None and d["event"]):
                ev[r] = d["event"]
    out = [(r, ev[r]) for r in sorted(ev)]
    return out[:limit] if limit else out


# ---------------------------------------------------------------- cache / asking

def _key(state, model):
    blob = json.dumps({"state": state, "question": QUESTION, "model": model}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _path(state, model, cache_dir):
    return Path(cache_dir) / f"{_key(state, model)}.json"


def requests_for(menu, weeks, year=2026):
    """[(round, cand_key, state)] one per (week, eligible candidate)."""
    out = []
    for rnd, ev in weeks:
        for c in menu:
            if rnd in c["series"].get(year, {}):
                out.append((rnd, c["key"], week_state(c, rnd, ev, year)))
    return out


def plan(menu, weeks, cache_dir=CACHE_DIR, model=DEFAULT_MODEL, year=2026):
    """Dry run, no network: requests, unique states, cached, calls to make."""
    reqs = requests_for(menu, weeks, year)
    keys = {_key(s, model) for _, _, s in reqs}
    cached = sum((Path(cache_dir) / f"{k}.json").exists() for k in keys)
    return {"requests": len(reqs), "unique_states": len(keys), "cached": cached, "to_make": len(keys) - cached}


def ask_desk(state, client=None, model=DEFAULT_MODEL, cache_dir=CACHE_DIR):
    """P(profit) for a state, from cache when the key is unchanged. Record: p, usage (input/output tokens)."""
    path = _path(state, model, cache_dir)
    if path.exists():
        return json.loads(path.read_text())
    client = client or make_client()
    resp = client.system_one(state=state, questions=QUESTION, model=model)
    p = float(resp.nouls["profit"].noul)
    u = getattr(resp, "usage", None)
    usage = {"input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None)} \
        if u is not None else None
    rec = {"key": _key(state, model), "model": model, "answered_by": getattr(resp, "model", None),
           "state": state, "p": p, "usage": usage}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, sort_keys=True, indent=1, default=str))
    return rec


# ---------------------------------------------------------------- walk-forward

def _contrib(cand, rnd, bankroll_now, year):
    """Dollar P&L of the candidate for the round at full weight, given the running bankroll."""
    d = cand["series"][year][rnd]
    return d["ret"] * bankroll_now if cand["kelly"] is not None else d["pnl"]


def _score_total_prev(c, year):
    return _total(_rets(c, year - 1), c["kelly"] is not None)


def _score_trailing(c, rnd, year):
    rets = _rets(c, year, below=rnd)
    return _total(rets, c["kelly"] is not None) if rets else _score_total_prev(c, year)


def _pick_top(scores, k):
    """scores {key: float}; highest first, ties by key."""
    return [key for key, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def _find_b4(menu):
    m = [c for c in menu if c["mode"] == "update" and c["kelly"] is None
         and c["params"].get("variant") == "gridq+pretrain+reset" and c["params"].get("min_edge") == 0.1
         and c["n_sims"] == 16000]
    hashes = {c["cfg_hash"] for c in m}
    return m[0]["key"] if len(hashes) == 1 else None


def _run_rule(menu, weeks, bankroll, k, year, chooser):
    """chooser(rnd, eligible, W) -> list of keys (or weighted list [(key, weight)]). Returns picks and path."""
    by_key = {c["key"]: c for c in menu}
    W, path, picks, pnls = bankroll, [bankroll], [], []
    for rnd, _ in weeks:
        elig = [c for c in menu if rnd in c["series"].get(year, {})]
        ch = chooser(rnd, elig, W)
        ch = [(x, 1.0 / k) if isinstance(x, str) else x for x in ch]
        delta = sum(w * _contrib(by_key[key], rnd, W, year) for key, w in ch)
        W += delta
        path.append(W)
        picks.append([key for key, _ in ch])
        pnls.append(delta)
    return {"picks": picks, "path": path, "weekly_pnl": pnls}


def run_walk_forward(menu, answers, bankroll, k, weeks, year=2026):
    """answers: {(round, cand_key): P(profit)}. Returns {rule_name: {picks, path, weekly_pnl}} + notes."""
    notes = []
    by_key = {c["key"]: c for c in menu}
    b1 = _pick_top({c["key"]: _score_total_prev(c, year) for c in menu}, 1)[0] if menu else None

    def jev(rnd, elig, W):
        sc = {c["key"]: answers[(rnd, c["key"])] for c in elig if (rnd, c["key"]) in answers}
        return _pick_top(sc, k)

    def fixed(key):
        return lambda rnd, elig, W: [key] if key in {c["key"] for c in elig} else []

    def trailing(rnd, elig, W):
        return _pick_top({c["key"]: _score_trailing(c, rnd, year) for c in elig}, k)

    def equal(rnd, elig, W):
        return [(c["key"], 1.0 / len(elig)) for c in elig]

    def hindsight(rnd, elig, W):
        return _pick_top({c["key"]: _contrib(c, rnd, W, year) for c in elig}, k)

    res = {"Jev": _run_rule(menu, weeks, bankroll, k, year, jev),
           "B1 best 2025 total": _run_rule(menu, weeks, bankroll, 1, year, fixed(b1)),
           "B2 trailing best": _run_rule(menu, weeks, bankroll, k, year, trailing),
           "B3 equal weight": _run_rule(menu, weeks, bankroll, k, year, equal)}
    b4 = _find_b4(menu)
    if b4:
        res["B4 profile A config"] = _run_rule(menu, weeks, bankroll, 1, year, fixed(b4))
    else:
        notes.append("B4 skipped: profile A's configuration is not identifiable as exactly one config in the menu")
    res["B5 hindsight weekly"] = _run_rule(menu, weeks, bankroll, k, year, hindsight)
    solo = {c["key"]: _run_rule(menu, weeks, bankroll, 1, year, fixed(c["key"])) for c in menu}
    if solo:
        b6 = sorted(solo, key=lambda x: (-solo[x]["path"][-1], x))[0]
        res["B6 hindsight season"] = solo[b6]
        notes.append(f"B6 candidate: {b6}")
    notes.append(f"B1 candidate: {b1}")
    return res, notes


# ---------------------------------------------------------------- analysis

def week_auc(scores, profit):
    """P(a profitable candidate ranks above an unprofitable one), ties 0.5; nan if a class is empty."""
    a = auc_loser_gt_winner(scores, np.asarray(profit, dtype=bool))
    return float("nan") if math.isnan(a) else 1.0 - a


def boot_mean(values, n=N_BOOT, seed=SEED):
    """Mean of values (nan dropped) and 95% CI from resampling whole weeks."""
    v = np.asarray([x for x in values if not math.isnan(x)], dtype=float)
    if len(v) < 2:
        return float(v.mean()) if len(v) else float("nan"), (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(n, len(v)))
    means = v[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(v.mean()), (float(lo), float(hi))


def weekly_aucs(menu, answers, weeks, year=2026):
    """Per week AUC for Jev, 2025-total rank and trailing rank; list of dicts."""
    out = []
    for rnd, ev in weeks:
        elig = [c for c in menu if rnd in c["series"].get(year, {}) and (rnd, c["key"]) in answers]
        if not elig:
            out.append({"round": rnd, "event": ev, "n": 0, "jev": float("nan"), "prev_total": float("nan"),
                        "trailing": float("nan")})
            continue
        profit = [c["series"][year][rnd]["pnl"] > 0 for c in elig]
        out.append({
            "round": rnd, "event": ev, "n": len(elig), "n_profit": int(sum(profit)),
            "jev": week_auc([answers[(rnd, c["key"])] for c in elig], profit),
            "prev_total": week_auc([_score_total_prev(c, year) for c in elig], profit),
            "trailing": week_auc([_score_trailing(c, rnd, year) for c in elig], profit)})
    return out


def analyse(menu, answers, weeks, walk, bankroll, k, year=2026, n_boot=N_BOOT):
    wk = weekly_aucs(menu, answers, weeks, year)
    valid = [w for w in wk if not math.isnan(w["jev"])]
    res = {"weekly_auc": wk, "weeks_valid": len(valid), "bankroll": bankroll, "k": k}
    for name in ("jev", "prev_total", "trailing"):
        res[name] = boot_mean([w[name] for w in wk], n=n_boot)
    better = "prev_total" if res["prev_total"][0] >= res["trailing"][0] else "trailing"
    diffs = [w["jev"] - w[better] for w in valid]
    res["better_rule"] = better
    res["diff"] = boot_mean(diffs, n=n_boot)
    lo = res["jev"][1][0]
    res["chance"] = "YES" if not math.isnan(lo) and lo > 0.5 else "NOT SHOWN"
    dlo = res["diff"][1][0]
    res["adds_value"] = "YES" if not math.isnan(dlo) and dlo > 0 else "NOT SHOWN"
    # descriptive
    rules = {}
    for name, w in walk.items():
        pnl = w["weekly_pnl"]
        path = w["path"]
        peak, dd = path[0], 0.0
        for v in path:
            peak = max(peak, v)
            dd = max(dd, peak - v)
        best2 = sorted(pnl, reverse=True)[:2]
        rules[name] = {"total_pnl": sum(pnl), "final": path[-1], "weeks_up": sum(x > 0 for x in pnl),
                       "weeks": len(pnl), "ex_best_two": sum(pnl) - sum(best2), "worst_drawdown": dd}
    res["rules"] = rules
    jp = walk["Jev"]["picks"]
    flat = [c for p in jp for c in p]
    by_key = {c["key"]: c for c in menu}
    res["churn"] = sum(a != b for a, b in zip(jp, jp[1:])) / max(1, len(jp) - 1)
    cnt = Counter(flat)
    res["concentration"] = {"distinct": len(cnt), "top": cnt.most_common(3), "picks": len(flat)}
    res["by_mode"] = dict(Counter(by_key[x]["mode"] for x in flat))
    res["by_sizing"] = dict(Counter("kelly" if by_key[x]["kelly"] is not None else "flat" for x in flat))
    res["weeks"] = [(r, e) for r, e in weeks]
    res["walk"] = walk
    return res


def _f(x, nd=3):
    return "nan" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def format_report(result, menu_report=None, notes=()):
    L = ["JEV DESK: pre-registered walk-forward over stored sweep strategies", "=" * 60,
         f"bankroll {result['bankroll']:,.0f}  k={result['k']}  weeks with both classes: {result['weeks_valid']}"]
    if menu_report:
        L.append(f"menu: {menu_report['candidates']} candidates ({menu_report['kelly_candidates']} Kelly), "
                 f"n_sims {menu_report['n_sims']}; blends {menu_report.get('blends')}")
    L += list(notes)
    L += ["", "PRIMARY: within-week AUC (profitable ranked above unprofitable), mean over weeks, 95% CI by weeks"]
    for name, label in (("jev", "Jev P(profit)"), ("prev_total", "previous-season total rank"),
                        ("trailing", "trailing-return rank")):
        m, (lo, hi) = result[name]
        L.append(f"  {label:28}{_f(m)}  CI ({_f(lo)}, {_f(hi)})")
    m, (lo, hi) = result["diff"]
    L.append(f"  Jev minus better rule ({result['better_rule']}): {_f(m)}  CI ({_f(lo)}, {_f(hi)})")
    L += ["", f"ranks better than chance: {result['chance']}",
          f"adds value over simple rules: {result['adds_value']}", "",
          "BANKROLL OUTCOMES (descriptive, no decision attached)",
          f"  {'rule':24}{'final':>12}{'total P&L':>12}{'weeks up':>10}{'ex best 2':>12}{'worst DD':>11}"]
    for name, r in result["rules"].items():
        L.append(f"  {name:24}{r['final']:>12,.0f}{r['total_pnl']:>12,.0f}{r['weeks_up']:>6}/{r['weeks']:<3}"
                 f"{r['ex_best_two']:>12,.0f}{r['worst_drawdown']:>11,.0f}")
    c = result["concentration"]
    L += ["", f"Jev pick churn (share of weeks the pick set changed): {_f(result['churn'], 2)}",
          f"Jev concentration: {c['distinct']} distinct of {c['picks']} picks; top {c['top']}",
          f"Jev picks by mode: {result['by_mode']}", f"Jev picks by sizing: {result['by_sizing']}", "",
          "WEEK BY WEEK", f"  {'rnd':>3} {'event':28}{'n':>4}{'Jev':>7}{'2025':>7}{'trail':>7}{'Jev pick':>16}{'pnl':>9}"]
    for i, w in enumerate(result["weekly_auc"]):
        jp = result["walk"]["Jev"]["picks"][i]
        pnl = result["walk"]["Jev"]["weekly_pnl"][i]
        L.append(f"  {w['round']:>3} {str(w['event'])[:27]:28}{w['n']:>4}{_f(w['jev'], 2):>7}"
                 f"{_f(w['prev_total'], 2):>7}{_f(w['trailing'], 2):>7}{','.join(jp)[:15]:>16}{pnl:>9,.0f}")
    L += ["", "Not shown by this design:",
          "  Whether this would have made money live: stored P&L is at the touch after fees, hold-to-settle, not live fills.",
          "  The weeks are 15-16, and candidates are near-duplicates with correlated outcomes, so the effective sample "
          "is small.",
          "  Jev sees only P&L series and plain-word settings, no market data or news: this tests pattern-reading in "
          "strategy records, nothing more.",
          "  The menu and the T1-T10/TB shortlist were chosen with 2026 results in view (known in-sample bias)."]
    return "\n".join(L)
