"""Joint quarter Kelly over the prologue (winner, h2h) and GC (winner, matchups) books, from ONE GC simulation:
the prologue bets are settled on the simulated prologue stage, the GC bets on the simulated GC, so the two are
correlated exactly as the model has them. Candidates: model EV >= min_ev and both riders matched."""
import sys, json, numpy as np, pandas as pd
from racinglines.models import cycling as C, cycling_gc as G
data, out_dir, min_ev, kelly, bank = sys.argv[1], sys.argv[2], 0.05, 0.25, 1000.0
z = np.load(f"{out_dir}/gc_sims.npz", allow_pickle=True)
field = list(z["field"]); total = z["total"]; pro = z["stage_0"]
col = {u: j for j, u in enumerate(field)}
stages = pd.read_csv(C.results_file("stages", data))
res = pd.concat([C.load_results("itt", data), C.load_results("road", data), stages], ignore_index=True)
start = pd.DataFrame(columns=["rider", "rider_url"])
gc_ev, pr_ev = C.load_event("2026-10-13-eneco-tour-gc"), C.load_event(sys.argv[3])
gc_ids, _ = C.book_ids(gc_ev, start, res)
pr_ev.setdefault("names", {}).update({k: v for k, v in gc_ev["names"].items() if k not in pr_ev["names"]})
pr_ids, pr_bad = C.book_ids(pr_ev, start, res)
pr_win = np.argmin(np.where(np.isfinite(pro), pro, np.inf), axis=1)
gc_rk = G.gc_ranks(total)
bets = []
def add(name, market, odds, pay, pbook):
    bets.append(dict(bet=name, market=market, odds=odds, pay=pay, p_book=pbook))
for book, ids, market, win in [(pr_ev, pr_ids, "prologue winner", lambda j: pr_win == j),
                               (gc_ev, gc_ids, "GC winner", lambda j: gc_rk[:, j] == 1)]:
    fut = book["book"].get("futures", {}); ov = sum(1 / o for o in fut.values())
    for k, o in fut.items():
        if k in ids and ids[k] in col:
            add(f"{k} to win", market, o, np.where(win(col[ids[k]]), o - 1, -1.0), (1 / o) / ov)
for book, ids, market, arr in [(pr_ev, pr_ids, "prologue h2h", pro), (gc_ev, gc_ids, "GC matchup", total)]:
    for mt in book["book"].get("matchups", []):
        x, y = mt["a"], mt["b"]
        if not (x in ids and y in ids and ids[x] in col and ids[y] in col):
            continue
        a, b = arr[:, col[ids[x]]], arr[:, col[ids[y]]]
        both = ~np.isfinite(a) & ~np.isfinite(b); ob = 1 / mt["a_odds"] + 1 / mt["b_odds"]
        for p, q, o, pa, pb in [(x, y, mt["a_odds"], a, b), (y, x, mt["b_odds"], b, a)]:
            add(f"{p} over {q}", market, o, np.where(both, 0.0, np.where(pa < pb, o - 1, -1.0)), (1 / o) / ob)
tab = pd.DataFrame([dict(bet=b["bet"], market=b["market"], odds=b["odds"], p_model=float((b["pay"] > 0).mean()),
                         p_book=b["p_book"], ev=float(b["pay"].mean())) for b in bets])
tab["solo_qk"] = [round(bank * kelly * max(e, 0) / (o - 1), 2) for e, o in zip(tab["ev"], tab["odds"])]
cand = [i for i in range(len(bets)) if tab.loc[i, "ev"] >= min_ev]
P = np.stack([bets[i]["pay"] for i in cand], 1)
f = np.full(len(cand), 1e-3)
for it in range(30000):                                     # projected gradient ascent on mean log wealth
    w = 1 + P @ f
    f = np.maximum(f + 0.002 * (P / w[:, None]).mean(0), 0)
    if f.sum() > 0.95:
        f *= 0.95 / f.sum()
grad = (P / (1 + P @ f)[:, None]).mean(0)
picks = tab.loc[cand].copy(); picks["full_kelly_f"] = f; picks["stake"] = (bank * kelly * f).round(2)
picks = picks[picks["stake"] >= 0.01].sort_values("stake", ascending=False)
pnl = bank * (P @ (kelly * f))
summary = dict(total_stake=float(picks["stake"].sum()), mean_pnl=float(pnl.mean()), p_loss=float((pnl < 0).mean()),
               p5=float(np.percentile(pnl, 5)), p95=float(np.percentile(pnl, 95)), worst=float(pnl.min()),
               best=float(pnl.max()), max_kkt_violation=float(np.max(grad[f <= 1e-9] - grad[f > 1e-9].mean()))
               if (f > 1e-9).any() and (f <= 1e-9).any() else None, unmatched_prologue=pr_bad, sims=int(len(pnl)))
tab.to_csv(f"{out_dir}/all_lines.csv", index=False); picks.to_csv(f"{out_dir}/picks.csv", index=False)
np.save(f"{out_dir}/pnl.npy", pnl); json.dump(summary, open(f"{out_dir}/summary.json", "w"), indent=1)
print(tab.sort_values("ev", ascending=False).head(25).to_string(index=False, float_format="%.3f"))
print(picks.to_string(index=False, float_format="%.3f")); print(json.dumps(summary, indent=1))
