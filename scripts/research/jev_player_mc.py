"""Monte Carlo over Jev's own per-round distributions (reports/2026-10-15-jev-player/PREREG.md, Amendment 2).

    .venv/bin/python scripts/research/jev_player_mc.py [--skip-reasks] [--force-reasks]

Step 1 re-asks rounds 1 and 9 three times each (6 requests, cache bypassed, cache not overwritten) and writes
montecarlo_reasks.json; if that file exists it is reused unless --force-reasks. Steps 2-4 use no network. Seed 1.
Writes montecarlo.json and montecarlo.md. Descriptive, in-sample; nothing here is a test of skill.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_player as S                                     # noqa: E402  (scripts/research/jev_player.py)
from racinglines.research import jev_player as J           # noqa: E402

OUT = J.OUT_DIR
ROUNDS = list(range(1, 18))
JEV_USER = 22
SEED = 1
PREREG_CAVEAT = J.CAVEAT
REASK_ROUNDS = (1, 9)
N_REASK = 3


def f2(x):
    return f"{x:,.2f}"


def load_inputs():
    styles, _ = J.load_styles(OUT / "styles.json")
    players = J.load_players(OUT / "players.csv")
    cal = J.calendar_from_styles(styles)
    return styles, players, cal


def state_of(styles, players, cal, r):
    return J.state_for(styles, players, cal, r, (JEV_USER,))


def cached_records(styles, players, cal):
    recs = {}
    for r in ROUNDS:
        hit = J.cached_answer(state_of(styles, players, cal, r), J.DEFAULT_MODEL)
        if hit is None:
            sys.exit(f"round {r}: state does not reproduce a cached answer (cache miss); stopping")
        recs[r] = hit
    return recs


def raw_ask(state, client):
    """One live request, same shape as J.ask's record, but nothing is written to the cache."""
    resp = client.system_one(state=state, questions=J.questions(), model=J.DEFAULT_MODEL)
    rec = {"model": J.DEFAULT_MODEL, "answered_by": getattr(resp, "model", None)}
    for k in ("style", "sizing"):
        a = resp.choices[k]
        rec[k] = {"choice": a.choice, "confidence": getattr(a, "confidence", None), "probabilities": dict(a.probabilities)}
    rec["basis"] = {k: float(resp.nouls[k].noul) for k in J.BASIS_TEXT}
    return rec


def do_reasks(styles, players, cal, recs, force):
    path = OUT / "montecarlo_reasks.json"
    if path.exists() and not force:
        print(f"reusing {path} (no requests sent)", flush=True)
        return json.loads(path.read_text()), 0
    S.ensure_key()
    client = J.make_client()
    out, n = {}, 0
    for r in REASK_ROUNDS:
        state = state_of(styles, players, cal, r)
        J.guard(state, J.canaries(styles, players, r))
        out[str(r)] = []
        for i in range(N_REASK):
            try:
                rec = raw_ask(state, client)
            except Exception as ex:                        # noqa: BLE001
                path.write_text(json.dumps(out, indent=1, default=str))
                sys.exit(f"re-ask failed at round {r} #{i + 1} after {n} requests: {ex!r}")
            n += 1
            out[str(r)].append(rec)
            print(f"re-ask round {r} #{i + 1} done ({n}/6)", flush=True)
    path.write_text(json.dumps(out, indent=1, default=str))
    return out, n


def determinism(reasks, recs):
    res = {}
    for r in REASK_ROUNDS:
        answers = reasks[str(r)]
        cached = recs[r]
        d = {}
        for q in ("style", "sizing"):
            keys = list(cached[q]["probabilities"])
            P = np.array([[a[q]["probabilities"][k] for k in keys] for a in answers])
            c = np.array([cached[q]["probabilities"][k] for k in keys])
            d[q] = dict(max_abs_diff_among_reasks=float((P.max(0) - P.min(0)).max()),
                        max_abs_diff_vs_cached=float(np.abs(P - c).max()),
                        choices=[a[q]["choice"] for a in answers], cached_choice=cached[q]["choice"])
        d["answered_by"] = [a.get("answered_by") for a in answers]
        d["cached_answered_by"] = cached.get("answered_by")
        res[r] = d
    res["max_abs_diff_overall"] = max(v[q][m] for r, v in res.items() if isinstance(r, int)
                                      for q in ("style", "sizing") for m in ("max_abs_diff_among_reasks", "max_abs_diff_vs_cached"))
    return res


def stats(x, extra=None):
    x = np.asarray(x)
    d = dict(n=int(len(x)), mean=float(x.mean()), median=float(np.median(x)), p5=float(np.percentile(x, 5)),
             p95=float(np.percentile(x, 95)), min=float(x.min()), max=float(x.max()), sd=float(x.std(ddof=1)))
    return d


def shares(x, bases):
    x = np.asarray(x)
    return {k: float((x > v).mean()) for k, v in bases.items()}


def percentile_of(x, v):
    x = np.asarray(x)
    return float(100.0 * ((x < v).mean() + 0.5 * (x == v).mean()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-reasks", action="store_true")
    args = ap.parse_args()
    styles, players, cal = load_inputs()
    recs = cached_records(styles, players, cal)
    codes = list(J.CODES)
    # P&L matrix: rounds x styles
    M = np.array([[J.pnl_of(styles, c, r) or 0.0 for c in codes] for r in ROUNDS])
    # baselines, recomputed with the module's own rules, asserted against results.txt
    bp = J.baseline_picks(styles, ROUNDS)
    base = {"B1": sum(J.weekly(styles, bp["B1"], ROUNDS)), "B2": sum(J.weekly(styles, bp["B2"], ROUNDS)),
            "B3": sum(J.equal_weight(styles, ROUNDS))}
    expect = {"B1": 1099.67, "B2": 2532.09, "B3": 1176.68}
    for k, v in expect.items():
        assert round(base[k], 2) == v, (k, base[k], v)
    picks, _ = J.run(styles, players, cal, ROUNDS, J.cache_only_ask(), exclude_users=(JEV_USER,))
    argmax_path = float(sum(J.weekly(styles, {r: picks[r]["code"] for r in ROUNDS}, ROUNDS)))
    assert round(argmax_path, 2) == 2046.51, argmax_path
    bases = {"B1": base["B1"], "B2": base["B2"], "B3": base["B3"], "argmax": argmax_path}
    h1 = float(sum(J.weekly(styles, bp["H1"], ROUNDS)))

    reasks, n_req = do_reasks(styles, players, cal, recs, args.force_reasks)
    det = determinism(reasks, recs)

    # Jev style probabilities per round (cached answers), ordered by codes, renormalised
    P = np.array([[recs[r]["style"]["probabilities"].get(c, 0.0) for c in codes] for r in ROUNDS])
    P = P / P.sum(1, keepdims=True)
    rng = np.random.default_rng(SEED)

    def season(Pm, n):
        cum = Pm.cumsum(1)
        u = rng.random((n, len(ROUNDS), 1))
        idx = (u > cum[None]).sum(2).clip(max=len(codes) - 1)
        return M[np.arange(len(ROUNDS))[None, :], idx].sum(1)

    out = {"seed": SEED, "codes": codes, "baselines": bases, "hindsight_best_each_round": h1, "determinism": det,
           "requests_sent": n_req, "expected_policy_total": float((P * M).sum())}
    policy = {}
    for n in (100, 10000):
        s = season(P, n)
        policy[str(n)] = dict(stats=stats(s), share_above=shares(s, bases))
    out["policy"] = policy
    # answers vary: sensitivity with rounds 1 and 9 using the mean of the cached answer and the three re-asks
    P2 = P.copy()
    for r in REASK_ROUNDS:
        allp = [recs[r]] + reasks[str(r)]
        v = np.array([[a["style"]["probabilities"].get(c, 0.0) for c in codes] for a in allp]).mean(0)
        P2[ROUNDS.index(r)] = v / v.sum()
    rng_s = np.random.default_rng(SEED)
    rng, rng_main = rng_s, rng
    s2 = season(P2, 10000)
    rng = rng_main
    out["policy_reask_mean_10000"] = dict(stats=stats(s2), share_above=shares(s2, bases), expected=float((P2 * M).sum()))
    U = np.full_like(P, 1 / len(codes))
    null = season(U, 10000)
    out["null"] = dict(stats=stats(null), share_above=shares(null, bases),
                       argmax_percentile=percentile_of(null, argmax_path),
                       policy_mean_percentile=percentile_of(null, out["expected_policy_total"]),
                       policy_mean=out["expected_policy_total"], exact_expected_total=float(M.mean(1).sum()))
    out["hold_one_style"] = {c: float(M[:, i].sum()) for i, c in enumerate(codes)}
    out["per_round"] = [dict(round=r, jev_expected=float((P[i] * M[i]).sum()), uniform=float(M[i].mean()),
                             hindsight=float(M[i].max()), argmax_pick=picks[r]["code"], argmax_pnl=float(M[i, codes.index(picks[r]["code"])]))
                        for i, r in enumerate(ROUNDS)]
    out["sizing_scale"] = ("not computed: standard scales stakes by bankroll (bank.scale, linear), Kelly stakes are kelly x f* x "
                           "bankroll with f* from each position's own edge and price (sizing.target_shares), so no closed-form "
                           "factor relates a Kelly fraction to standard sizing; the stored P&L cannot be rescaled by position "
                           "from the per-round totals")
    (OUT / "montecarlo.json").write_text(json.dumps(out, indent=1))
    (OUT / "montecarlo.md").write_text(render(out, codes))
    print("wrote montecarlo.json, montecarlo.md; requests sent:", n_req)


def stat_row(label, s):
    return f"| {label} | {f2(s['mean'])} | {f2(s['median'])} | {f2(s['p5'])} | {f2(s['p95'])} | {f2(s['min'])} | {f2(s['max'])} |"


def pct(x):
    return f"{100 * x:.1f}%"


def render(o, codes):
    b = o["baselines"]
    L = ["# Jev as a fantasy player: Monte Carlo over Jev's own distributions (PREREG Amendment 2)", "",
         f"Seed {o['seed']}; rounds 1-17; season P&L = sum of the drawn style's stored P&L at default sizing. Descriptive only.", "",
         f"Reference totals: B1 {f2(b['B1'])}, B2 {f2(b['B2'])}, B3 {f2(b['B3'])}, argmax path {f2(b['argmax'])}, "
         f"hindsight best each round {f2(o['hindsight_best_each_round'])}. Expected total under Jev's distributions (exact): "
         f"{f2(o['expected_policy_total'])}.", "",
         "## 1. Determinism (cache bypassed, 3 re-asks each, 6 requests)", "",
         "| Round | max abs diff, style probs (among re-asks) | vs cached | max abs diff, sizing probs (among re-asks) | vs cached | choices (re-asks / cached) | answered_by |",
         "|---|---|---|---|---|---|---|"]
    for r in REASK_ROUNDS:
        d = o["determinism"][r] if r in o["determinism"] else o["determinism"][str(r)]
        L.append(f"| {r} | {d['style']['max_abs_diff_among_reasks']:.6f} | {d['style']['max_abs_diff_vs_cached']:.6f} | "
                 f"{d['sizing']['max_abs_diff_among_reasks']:.6f} | {d['sizing']['max_abs_diff_vs_cached']:.6f} | "
                 f"{d['style']['choices']} / {d['style']['cached_choice']}; sizing {d['sizing']['choices']} / {d['sizing']['cached_choice']} | "
                 f"{set(d['answered_by'])} (cached: {d['cached_answered_by']}) |")
    L += ["", f"Largest absolute probability difference overall: {o['determinism']['max_abs_diff_overall']:.6f}.", "",
          "## 2. Policy Monte Carlo (style drawn from Jev's per-round probabilities)", "",
          "| Seasons | mean | median | p5 | p95 | min | max |", "|---|---|---|---|---|---|---|"]
    for n in ("100", "10000"):
        L.append(stat_row(f"{int(n):,}", o["policy"][n]["stats"]))
    L += ["", "Share of seasons above each reference:", "", "| Seasons | B1 | B2 | B3 | argmax path |", "|---|---|---|---|---|"]
    for n in ("100", "10000"):
        s = o["policy"][n]["share_above"]
        L.append(f"| {int(n):,} | {pct(s['B1'])} | {pct(s['B2'])} | {pct(s['B3'])} | {pct(s['argmax'])} |")
    nl = o["null"]
    q = o["policy_reask_mean_10000"]
    L += ["", "Sensitivity (answers vary, so rounds 1 and 9 use the mean of the cached answer and the 3 re-asks), 10,000 seasons:", "",
          "| mean | median | p5 | p95 | above B1 | above B2 | above B3 | above argmax | exact expectation |", "|---|---|---|---|---|---|---|---|---|",
          f"| {f2(q['stats']['mean'])} | {f2(q['stats']['median'])} | {f2(q['stats']['p5'])} | {f2(q['stats']['p95'])} | "
          f"{pct(q['share_above']['B1'])} | {pct(q['share_above']['B2'])} | {pct(q['share_above']['B3'])} | {pct(q['share_above']['argmax'])} | {f2(q['expected'])} |"]
    L += ["", "## 3. Null Monte Carlo (uniform over the five styles every round, 10,000 seasons)", "",
          "| mean | median | p5 | p95 | min | max |", "|---|---|---|---|---|---|",
          f"| {f2(nl['stats']['mean'])} | {f2(nl['stats']['median'])} | {f2(nl['stats']['p5'])} | {f2(nl['stats']['p95'])} | {f2(nl['stats']['min'])} | {f2(nl['stats']['max'])} |", "",
          "| Share of null seasons above | B1 | B2 | B3 | argmax path |", "|---|---|---|---|---|",
          f"| | {pct(nl['share_above']['B1'])} | {pct(nl['share_above']['B2'])} | {pct(nl['share_above']['B3'])} | {pct(nl['share_above']['argmax'])} |", "",
          f"Percentile in the null distribution: argmax path {nl['argmax_percentile']:.1f}, policy mean ({f2(nl['policy_mean'])}) "
          f"{nl['policy_mean_percentile']:.1f}. Exact null expectation: {f2(nl['exact_expected_total'])}.", "",
          "Hold one style all season:", "", "| Style | season total |", "|---|---|"]
    for c in codes:
        L.append(f"| {c} | {f2(o['hold_one_style'][c])} |")
    L += ["", "## Expected P&L per round: Jev's distribution vs uniform vs hindsight best", "",
          "| Round | Jev expected | uniform | hindsight best | argmax pick | argmax P&L |", "|---|---|---|---|---|---|"]
    for p in o["per_round"]:
        L.append(f"| {p['round']} | {f2(p['jev_expected'])} | {f2(p['uniform'])} | {f2(p['hindsight'])} | {p['argmax_pick']} | {f2(p['argmax_pnl'])} |")
    tj = sum(p["jev_expected"] for p in o["per_round"]); tu = sum(p["uniform"] for p in o["per_round"]); th = sum(p["hindsight"] for p in o["per_round"])
    L.append(f"| **total** | **{f2(tj)}** | **{f2(tu)}** | **{f2(th)}** | | |")
    L += ["", "## 4. Sizing scale", "", o["sizing_scale"] + ".", "", "## Plain reading", "",
          f"Jev's own distributions put the expected season at {f2(o['expected_policy_total'])}, against {f2(nl['exact_expected_total'])} "
          f"for a uniform draw and {f2(b['B2'])} / {f2(b['B1'])} / {f2(b['B3'])} for B2 / B1 / B3. In 10,000 policy seasons "
          f"{pct(o['policy']['10000']['share_above']['B2'])} beat B2, {pct(o['policy']['10000']['share_above']['B1'])} beat B1 and "
          f"{pct(o['policy']['10000']['share_above']['B3'])} beat B3; the argmax path ({f2(b['argmax'])}) sits at the "
          f"{nl['argmax_percentile']:.0f}th percentile of the null. Re-asks differed by at most {o['determinism']['max_abs_diff_overall']:.4f} in any probability. "
          f"The spread shows how much one round (round 9, a single large week) drives any style's total, not skill. "
          f"Caveat, verbatim from the PREREG: {PREREG_CAVEAT}", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
