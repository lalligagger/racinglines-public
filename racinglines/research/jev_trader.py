"""Research: Jev as a desk trader. It builds a 20-lot allocation table per 2026 race weekend. Spec:
reports/2026-10-14-jev-desk/PREREG.md (v2).

Paper research off the live path: no order, no setting, no database write. This module is pure apart from the disk
cache in `ask_choice`; the universe (strategies, returns, week-locked views) comes from `jev_universe.Universe`.
`typesafe_sdk` is imported lazily inside `jev_gate.make_client`, never at import time.

Interpretations of the PREREG (each also listed in the CLI's SOURCES.md):
  * Weekly return = week P&L / the bankroll at the start of that week. The bankroll rolls separately for Jev and for
    each baseline; Jev minus baseline is the difference of those weekly returns.
  * `u.total(sid, year, upto=r)` is read as the sum of weekly returns for rounds strictly before r.
  * B3 is equal weight: every strategy gets 20/N lots (fractional lots), N = len(u.ids).
  * B7 is equal weight over each week's own shortlist (the options Jev sees): it isolates Jev's choice from the
    packaging, because the shortlist is already filtered toward strategies that did well.
  * A strategy with a None return in a week where it holds lots counts 0 and is added to the `missing` tally.
  * Ties in the lot choice go to the earlier option; options are the shortlist ids in view order, then CASH.
"""

from __future__ import annotations

import hashlib
import json
import re
import math
import time
from pathlib import Path

from racinglines.research.jev_desk import boot_mean
from racinglines.research.jev_gate import DEFAULT_MODEL, make_client

CACHE_DIR = Path("data/runs/jev_trader/cache")
CASH = "CASH"
LOTS = 20
LOT_PCT = 5
YEAR = 2026
PREV_YEAR = 2025
N_BOOT = 5000
BASELINES = ("B1", "B2", "B3", "B4", "B5", "B6", "B7")
DECISION_BASELINES = ("B1", "B2", "B3", "B7")      # Jev must beat all four to "add value over simple rules"
BASELINE_NAMES = {
    "B1": "B1 best 2025 total", "B2": "B2 trailing best", "B3": "B3 equal weight", "B4": "B4 profile A",
    "B5": "B5 hindsight weekly best", "B6": "B6 hindsight season best",
    "B7": "B7 equal-wt shortlist"}

INSTRUCTIONS = (
    "A bankroll is being allocated for the coming Formula 1 race weekend. It is cut into 20 lots of 5% each. This "
    "request places one lot: choose the option that receives it, either a strategy from `packages.shortlist` "
    "(identified by its `id`) or CASH, which keeps this lot uninvested. The state fields are: `bankroll`, the current "
    "bankroll in dollars; `lot_pct`, the size of one lot in percent of the bankroll; `lots_left`, the number of lots "
    "still to place including this one; `table_so_far`, the lots already placed this weekend, by strategy id or CASH; "
    "`packages.event`, the upcoming event; `packages.family_summary`, a summary of all stored strategies by taker "
    "mode and sizing for 2025 and for 2026 so far; `packages.shortlist`, the candidate strategies with their "
    "settings and past weekly returns in percent; `packages.notes`, the number of strategies and any package that "
    "was cut to its size cap."
)


def question(options):
    """The one Choice question for a request; `options` is the ordered list of option ids (shortlist ids, then CASH)."""
    if len(options) > 255:
        raise ValueError(f"{len(options)} options, the Choice limit is 255")
    crit = {o: ("keep this lot in cash" if o == CASH else f"strategy {o}") for o in options}
    return {"lot": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": crit}}


# ---------------------------------------------------------------- state and guard

def lot_state(view, bankroll, table_so_far):
    table = {k: table_so_far[k] for k in sorted(table_so_far)}
    return {"bankroll": round(float(bankroll), 2), "lot_pct": LOT_PCT,
            "lots_left": LOTS - int(sum(table.values())), "table_so_far": table, "packages": view.packages}


def guard(state, canaries):
    blob = json.dumps(state, default=str)
    for c in canaries:
        if c and c in blob:
            raise RuntimeError(f"leak guard: canary {c!r} found in the request state")


def state_hash(state, options=None):
    return hashlib.sha256(json.dumps({"s": state, "o": options}, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------- the lot loop

def options_for(view):
    return list(view.shortlist_ids) + [CASH]


def _probs_choice(ans, options):
    """(choice, probabilities) from an `ask` answer (a dict, or a tuple of choice and probabilities)."""
    if isinstance(ans, dict):
        choice, probs = ans.get("choice"), ans.get("probabilities") or {}
    else:
        choice, probs = ans[0], ans[1] or {}
    return choice, probs


def argmax_option(options, probs, choice=None):
    """Highest probability, ties to the earlier option; falls back to `choice` with no probabilities."""
    if not probs:
        if choice not in options:
            raise ValueError(f"answer {choice!r} is not one of the options")
        return choice
    best, bp = None, -1.0
    for o in options:
        p = float(probs.get(o, 0.0))
        if p > bp:
            best, bp = o, p
    return best


def allocate_week(view, canaries, bankroll, ask, lots=LOTS):
    """20 sequential calls of `ask(state, options)`; returns (table {id|CASH: lots}, transcript)."""
    options = options_for(view)
    table, transcript = {}, []
    for n in range(1, lots + 1):
        state = lot_state(view, bankroll, table)
        state["lots_left"] = lots - (n - 1)
        guard(state, canaries)
        ans = ask(state, options)
        choice, probs = _probs_choice(ans, options)
        pick = argmax_option(options, probs, choice)
        table[pick] = table.get(pick, 0) + 1
        extra = ans if isinstance(ans, dict) else {}
        transcript.append({"round": view.round_no, "lot": n, "state_hash": state_hash(state, options),
                           "choice": pick, "model_choice": choice, "probabilities": probs,
                           "usage": extra.get("usage"), "answered_by": extra.get("answered_by"),
                           "cached": extra.get("cached")})
    return table, transcript


# ---------------------------------------------------------------- the TypeSafe call (cached)

def _cache_path(state, options, model, cache_dir):
    blob = json.dumps({"state": state, "question": question(options), "options": options, "model": model},
                      sort_keys=True, default=str)
    return Path(cache_dir) / f"{hashlib.sha256(blob.encode()).hexdigest()}.json"


def cached_answer(state, options, model=DEFAULT_MODEL, cache_dir=CACHE_DIR):
    p = _cache_path(state, options, model, cache_dir)
    if p.exists():
        rec = json.loads(p.read_text())
        rec["cached"] = True
        return rec
    return None


def ask_choice(state, options, client=None, model=DEFAULT_MODEL, cache_dir=CACHE_DIR):
    """One Choice answer for a lot, from disk cache when state, question, options and model are unchanged."""
    hit = cached_answer(state, options, model, cache_dir)
    if hit is not None:
        return hit
    client = client or make_client()
    resp = client.system_one(state=state, questions=question(options), model=model)
    a = resp.choices["lot"]
    u = getattr(resp, "usage", None)
    usage = {"input_tokens": getattr(u, "input_tokens", 0), "output_tokens": getattr(u, "output_tokens", 0)} if u else None
    rec = {"model": model, "answered_by": getattr(resp, "model", None), "choice": a.choice,
           "confidence": getattr(a, "confidence", None), "probabilities": dict(a.probabilities), "usage": usage}
    p = _cache_path(state, options, model, cache_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, sort_keys=True, indent=1, default=str))
    rec["cached"] = False
    return rec


class MissingCache(Exception):
    pass


def cache_only_ask(model=DEFAULT_MODEL, cache_dir=CACHE_DIR):
    """An `ask` for dry runs: answers from disk only, raises MissingCache on the first request not yet cached."""
    def ask(state, options):
        hit = cached_answer(state, options, model, cache_dir)
        if hit is None:
            raise MissingCache
        return hit
    return ask


# ---------------------------------------------------------------- accounting

def account(u, tables, rounds, bankroll, year=YEAR):
    """Roll a bankroll through `rounds`; tables[round] = {sid|CASH: lots}. Returns weekly rows, path, missing tally."""
    b, weekly, path, missing = float(bankroll), [], [float(bankroll)], 0
    for r in rounds:
        pnl, rows, start = 0.0, [], b
        for sid, lots in tables.get(r, {}).items():
            dollars = lots * LOT_PCT / 100.0 * start
            if not lots:
                continue
            if sid == CASH:
                rows.append({"sid": sid, "lots": lots, "dollars": dollars, "ret": 0.0, "pnl": 0.0})
                continue
            ret = u.ret(sid, year, r)
            if ret is None:
                missing += 1
                p = 0.0
            else:
                p = dollars * ret
            pnl += p
            rows.append({"sid": sid, "lots": lots, "dollars": dollars, "ret": ret, "pnl": p})
        b = start + pnl
        weekly.append({"round": r, "start": start, "pnl": pnl, "ret": pnl / start if start else 0.0, "end": b,
                       "rows": rows})
        path.append(b)
    return {"weekly": weekly, "path": path, "missing": missing}


# ---------------------------------------------------------------- baselines

def _argmax(ids, key):
    best, bv = None, -math.inf
    for s in ids:
        v = key(s)
        if v > bv:
            best, bv = s, v
    return best


def baseline_tables(u, rounds, lots=LOTS, year=YEAR):
    """{name: {round: table}} for B1-B6 (B4 only with a unique profile A). Hindsight rules B5, B6 read the season."""
    ids = list(u.ids)
    out = {}
    b1 = _argmax(ids, lambda s: u.total(s, PREV_YEAR))
    out["B1"] = {r: {b1: lots} for r in rounds}
    first = u.rounds(year)[0] if u.rounds(year) else None
    t2 = {}
    for r in rounds:
        if r == first:
            s = b1
        else:
            s = _argmax(ids, lambda x: u.total(x, year, upto=r))
        t2[r] = {s: lots}
    out["B2"] = t2
    out["B3"] = {r: {s: lots / len(ids) for s in ids} for r in rounds}
    out["B7"] = {}
    for r in rounds:
        sl = list(u.view(r).shortlist_ids)
        out["B7"][r] = {x: lots / len(sl) for x in sl} if sl else {CASH: lots}
    a = u.find_profile_a()
    if a is not None:
        out["B4"] = {r: {a: lots} for r in rounds}
    out["B5"] = {}
    for r in rounds:
        s = _argmax(ids, lambda x: (lambda v: -math.inf if v is None else v)(u.ret(x, year, r)))
        out["B5"][r] = {s: lots}
    b6 = _argmax(ids, lambda s: u.total(s, year))
    out["B6"] = {r: {b6: lots} for r in rounds}
    return out


# ---------------------------------------------------------------- analysis

def _desc(acc):
    pnl = [w["pnl"] for w in acc["weekly"]]
    path = acc["path"]
    peak, dd = path[0], 0.0
    for v in path:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return {"path": path, "final": path[-1], "total_pnl": sum(pnl), "weeks_up": sum(x > 0 for x in pnl),
            "weeks": len(pnl), "ex_best_two": sum(pnl) - sum(sorted(pnl, reverse=True)[:2]), "worst_drawdown": dd,
            "missing": acc["missing"]}


def _table_stats(tables, rounds):
    total_lots = lambda t: sum(t.values()) or 1
    conc, held, cash, turn = [], [], [], []
    prev = None
    for r in rounds:
        t = tables[r]
        n = total_lots(t)
        sh = {k: v / n for k, v in t.items()}
        invested = [v for k, v in sh.items() if k != CASH]
        conc.append(max(invested) if invested else 0.0)
        held.append(len(invested))
        cash.append(sh.get(CASH, 0.0))
        if prev is not None:
            keys = set(sh) | set(prev)
            turn.append(0.5 * sum(abs(sh.get(k, 0.0) - prev.get(k, 0.0)) for k in keys))
        prev = sh
    mean = lambda v: sum(v) / len(v) if v else float("nan")
    return {"largest_share": mean(conc), "n_held": mean(held), "cash_share": mean(cash), "turnover": mean(turn)}


def _attrs(desc):
    """(taker mode, sizing) from a Universe.describe() string: 'variant V, update mode, Kelly fraction 0.5, venue ...'."""
    s = str(desc or "")
    m = re.search(r"(\w+) mode", s)
    return (m.group(1) if m else "?"), ("kelly" if "Kelly" in s else "flat")


def _breakdown(u, tables, rounds):
    mode, sizing = {}, {}
    for r in rounds:
        for sid, lots in tables[r].items():
            if sid == CASH:
                continue
            m, k = _attrs(u.describe(sid))
            mode[m] = mode.get(m, 0) + lots
            sizing[k] = sizing.get(k, 0) + lots
    return {"by_mode": mode, "by_sizing": sizing}


# ---------------------------------------------------------------- static ranking (hindsight, descriptive)

RANK_MEASURES = (("final", "final bankroll", True), ("ex_best_two", "P&L without best two weeks", True),
                 ("weeks_up", "weeks up", True), ("worst_drawdown", "worst drawdown", False))


def _rank_line(jev_d, statics):
    """{measure: rank} where rank = 1 + number of statics strictly better than Jev."""
    out = {}
    for key, _, higher in RANK_MEASURES:
        v = jev_d[key]
        out[key] = 1 + sum((d[key] > v) if higher else (d[key] < v) for d in statics)
    return out


def static_ranking(u, rounds, bankroll, jev_tables=None, base=None):
    """Jev against every single strategy held at 100% (20 lots) every week, same accounting. Hindsight; no decision.

    `jev_tables` is Jev's {round: {sid|CASH: lots}}, `base` the {name: account()} of the baselines (B-rule ranks).
    """
    rounds = list(rounds)
    jev_desc = _desc(account(u, jev_tables, rounds, bankroll)) if jev_tables is not None else None
    statics = {}
    for sid in u.ids:
        statics[sid] = _desc(account(u, {r: {sid: LOTS} for r in rounds}, rounds, bankroll))
    shortlisted = set()
    for r in rounds:
        shortlisted |= set(u.view(r).shortlist_ids)
    untuned = set(u.untuned_ids()) & set(u.ids)
    groups = {"all": list(u.ids),
              "flat": [s for s in u.ids if _attrs(u.describe(s))[1] == "flat"],
              "shortlisted": [s for s in u.ids if s in shortlisted],
              "untuned": [s for s in u.ids if s in untuned]}
    out = {"statics": statics, "groups": {}, "b_rank": {}, "top5": []}
    if jev_desc is not None:
        for g, ids in groups.items():
            ds = [statics[s] for s in ids]
            out["groups"][g] = {"n": len(ids), "ranks": _rank_line(jev_desc, ds) if ids else None}
        allds = [statics[s] for s in groups["all"]]
        for k in DECISION_BASELINES:
            if base and k in base:
                bd = _desc(base[k])
                out["b_rank"][k] = {"final": bd["final"],
                                    "rank": 1 + sum(d["final"] > bd["final"] for d in allds), "of": len(allds) + 1}
    top = sorted(groups["all"], key=lambda s: (-statics[s]["final"], s))[:5]
    out["top5"] = [{"sid": s, "desc": u.describe(s), "final": statics[s]["final"], "total_pnl": statics[s]["total_pnl"]}
                   for s in top]
    return out


def format_static(st):
    L = ["JEV VS EVERY STATIC STRATEGY (hindsight leaderboard; descriptive, no decision attached)",
         "  A static strategy is one universe strategy held at 100% (20 lots) every week, same accounting as Jev.",
         "  Rank = 1 + the number of statics strictly better than Jev; Jev counts in the field. Drawdown: lower is better.",
         "  (a) The static field is ranked with the whole season known, so only B1 and B2 were choosable in advance.",
         "  (b) Kelly strategies dominate raw final bankroll (stored Kelly results assume unlimited depth at the touch), "
         "so read the flat and untuned groups first."]
    for g in ("all", "flat", "shortlisted", "untuned"):
        info = st["groups"].get(g)
        if not info or not info["n"]:
            L.append(f"  group {g}: none in this universe")
            continue
        n, total = info["n"], info["n"] + 1
        parts = []
        for key, label, _ in RANK_MEASURES:
            k = info["ranks"][key]
            parts.append(f"{label} rank {k} of {total} (top {math.ceil(100.0 * k / total)}%)")
        L.append(f"  group {g} ({n} statics): " + "; ".join(parts))
    L.append("  B-rules on final bankroll in the all group:")
    for k, b in st["b_rank"].items():
        L.append(f"    {BASELINE_NAMES[k]:26}final {b['final']:>10,.0f}  rank {b['rank']} of {b['of']}")
    L.append("  Top 5 statics by final bankroll (all group):")
    for t in st["top5"]:
        L.append(f"    {t['sid']} final {t['final']:,.0f}  total P&L {t['total_pnl']:,.0f}  {t['desc']}")
    return L


def analyse(u, rounds, jev_tables, bankroll, transcript=(), elapsed=0.0, n_boot=N_BOOT):
    rounds = list(rounds)
    jev = account(u, jev_tables, rounds, bankroll)
    bt = baseline_tables(u, rounds)
    base = {k: account(u, t, rounds, bankroll) for k, t in bt.items()}
    res = {"bankroll": float(bankroll), "rounds": rounds, "tables": jev_tables, "jev": jev, "base": base,
           "baseline_tables": bt, "skipped": [k for k in BASELINES if k not in base]}
    jr = [w["ret"] for w in jev["weekly"]]
    res["diff"], res["beats"] = {}, {}
    for k in DECISION_BASELINES:
        d = [a - b["ret"] for a, b in zip(jr, base[k]["weekly"])]
        res["diff"][k] = boot_mean(d, n=n_boot)
        lo = res["diff"][k][1][0]
        res["beats"][k] = "YES" if not math.isnan(lo) and lo > 0 else "NOT SHOWN"
    res["adds_value"] = "YES" if all(res["beats"][k] == "YES" for k in DECISION_BASELINES) else "NOT SHOWN"
    res["desc"] = {"Jev": _desc(jev), **{k: _desc(a) for k, a in base.items()}}
    res["static"] = static_ranking(u, rounds, bankroll, jev_tables, base)
    res["table_stats"] = _table_stats(jev_tables, rounds)
    res["breakdown"] = _breakdown(u, jev_tables, rounds)
    tin = sum((t.get("usage") or {}).get("input_tokens", 0) for t in transcript)
    tout = sum((t.get("usage") or {}).get("output_tokens", 0) for t in transcript)
    res["totals"] = {"requests": len(transcript), "api_calls": sum(1 for t in transcript if t.get("cached") is False),
                     "cached": sum(1 for t in transcript if t.get("cached")), "input_tokens": tin,
                     "output_tokens": tout, "elapsed_sec": elapsed}
    return res


def weeks_rows(result):
    out = []
    for w in result["jev"]["weekly"]:
        for r in w["rows"]:
            out.append({"week": w["round"], "sid": r["sid"], "lots": r["lots"], "pct": r["lots"] * LOT_PCT,
                        "dollars": r["dollars"], "ret": r["ret"], "pnl": r["pnl"]})
    return out


# ---------------------------------------------------------------- report

def _f(x, nd=4):
    return "nan" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


NOT_SHOWN = [
    "Whether this would have made money live: stored P&L is at the touch after fees and hold-to-settle, not live fills.",
    "The stored runs and the T-shortlist behind them were chosen with 2026 in view, so the universe is partly in-sample.",
    "The effective sample is 15-16 weekends and strategies are near-duplicates with correlated outcomes.",
    "Jev sees return records and settings in words, no market data, no news.",
]


def format_report(result):
    L = ["JEV DESK TRADER: pre-registered walk-forward allocation (reports/2026-10-14-jev-desk/PREREG.md v2)", "=" * 70,
         f"bankroll {result['bankroll']:,.0f}  weeks {len(result['rounds'])}  lots/week {LOTS}  "
         f"missing returns counted as 0: Jev {result['jev']['missing']}", "",
         "PRIMARY: Jev weekly return minus baseline, mean over weeks, 95% CI from resampling whole weeks (5,000, seed 1)"]
    for k in DECISION_BASELINES:
        m, (lo, hi) = result["diff"][k]
        L.append(f"  Jev - {BASELINE_NAMES[k]:26}{_f(m)}  CI ({_f(lo)}, {_f(hi)})")
    L.append("")
    for k in DECISION_BASELINES:
        L.append(f"beats {k}: {result['beats'][k]}")
    L += [f"adds value over simple rules: {result['adds_value']}", "",
          "BANKROLL OUTCOMES (descriptive, no decision attached; B5 and B6 are hindsight upper bounds)",
          f"  {'rule':26}{'final':>12}{'total P&L':>12}{'weeks up':>10}{'ex best 2':>12}{'worst DD':>11}"]
    for name, d in result["desc"].items():
        label = name if name == "Jev" else BASELINE_NAMES[name]
        L.append(f"  {label:26}{d['final']:>12,.0f}{d['total_pnl']:>12,.0f}{d['weeks_up']:>6}/{d['weeks']:<3}"
                 f"{d['ex_best_two']:>12,.0f}{d['worst_drawdown']:>11,.0f}")
    if result["skipped"]:
        L.append(f"  skipped: {', '.join(result['skipped'])} (no single strategy matches profile A)")
    L += ["", "BANKROLL PATH (start, then after each week)"]
    for name, d in result["desc"].items():
        L.append(f"  {name:5}" + " ".join(f"{v:,.0f}" for v in d["path"]))
    L += [""] + format_static(result["static"])
    ts = result["table_stats"]
    L += ["", f"Jev largest share {_f(ts['largest_share'], 2)}  strategies held {_f(ts['n_held'], 1)}  "
              f"cash share {_f(ts['cash_share'], 2)}  week-to-week turnover {_f(ts['turnover'], 2)}",
          f"Jev lots by mode: {result['breakdown']['by_mode']}",
          f"Jev lots by sizing: {result['breakdown']['by_sizing']}", "", "WEEK BY WEEK (Jev's table)"]
    for w in result["jev"]["weekly"]:
        tbl = ", ".join(f"{r['sid']}x{r['lots']:g}" for r in w["rows"])
        L.append(f"  rnd {w['round']:>2}  start {w['start']:>10,.0f}  pnl {w['pnl']:>9,.0f}  ret {_f(w['ret'])}  {tbl}")
    t = result["totals"]
    L += ["", f"requests {t['requests']} (API {t['api_calls']}, cached {t['cached']}); tokens in {t['input_tokens']:,} "
              f"out {t['output_tokens']:,}; time {t['elapsed_sec']:.0f} s", "", "Not shown by this design:"]
    L += [f"  {x}" for x in NOT_SHOWN]
    return "\n".join(L)


def now():
    return time.time()
