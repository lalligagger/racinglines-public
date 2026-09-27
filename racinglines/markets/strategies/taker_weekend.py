"""
Taker strategy through a race weekend: at each pricing stage (before any running,
then after each session), compare our fresh fair value with the exchange price at
that moment and rebalance each market to a target position; hold to resolution.

Per market and stage the inputs are only what was known then: our as-of fair value,
the exchange price, and whether the market was tradeable (liquid, not extreme, a
coherent book). The outcome is used only to settle.

Modes (to see whether updating adds value):
    update   rebalance at every stage (enter before any running, re-price after each session)
    hold     trade once, at the first stage the market is tradeable, then hold
    last     trade once, at the last stage (after qualifying)
    early    rebalance at every stage except the late ones (after FP3, after qualifying),
             then hold: the stage-aware taker (docs/f1-roadmap.md, F1-4)

Execution: buy at price + cost, sell at price - cost (cost per share covers spread
and slippage; the Baku books were a cent or two wide). NO is bought at 1 - price.
"""

from dataclasses import dataclass, replace

import pandas as pd
from racinglines.markets.strategies.sizing import target_shares


@dataclass(frozen=True)
class TakerParams:
    min_edge: float = 0.05         # act only when |fair - price| >= 5 pts
    stake_per_edge: float = 250.0  # target cost = 250 x edge (10 pts -> $25) ...
    max_stake: float = 50.0        # ... capped per market
    cost: float = 0.01             # $ per share on every trade
    min_trade: float = 2.0         # skip rebalances smaller than $2
    price_band: tuple = (0.02, 0.98)
    mode: str = "update"
    late_stages: tuple = ("after FP3", "after Quali")    # mode "early" doesn't trade these
    stages: tuple | None = None                          # entry timing: stages any mode may trade (None = all)
    min_edge_h2h: float | None = None                    # head-to-head markets' threshold (None = min_edge)


def run_market(stages, outcome, p: TakerParams):
    """stages: list of dict(label, t, fair, price, tradeable). outcome: True/False/None.
    Returns dict(trades, marks, pnl, yes, no, cash)."""
    yes = no = cash = 0.0
    trades, marks = [], []
    idx = [i for i, s in enumerate(stages) if s["tradeable"] and s["fair"] is not None and s["price"] is not None]
    if p.stages is not None:
        idx = [i for i in idx if stages[i]["label"] in p.stages]
    if p.mode == "hold":
        idx = idx[:1]
    elif p.mode == "last":
        idx = [len(stages) - 1] if (len(stages) - 1) in idx else []
    elif p.mode == "early":
        idx = [i for i in idx if stages[i]["label"] not in p.late_stages]
    for i, s in enumerate(stages):
        price = s["price"]
        if i in idx:
            ty, tn = target_shares(s["fair"], price, p.cost, p.min_edge, p.stake_per_edge, p.max_stake)
            for side, cur, tgt, px in (("YES", yes, ty, price), ("NO", no, tn, 1 - price)):
                d = tgt - cur
                if abs(d) * px < p.min_trade and tgt != 0:
                    continue
                if abs(d) < 1e-9:
                    continue
                exec_px = px + p.cost if d > 0 else max(px - p.cost, 0.0)
                cash -= d * exec_px
                if side == "YES":
                    yes = tgt
                else:
                    no = tgt
                trades.append(dict(stage=s["label"], t=s["t"], side=side, shares=d, price=exec_px, fair=s["fair"],
                                   mid=price))
        if price is not None:
            marks.append(dict(stage=s["label"], value=cash + yes * price + no * (1 - price)))
    pnl = None
    if outcome is not None:
        y = float(outcome)
        pnl = cash + yes * y + no * (1 - y)
        for tr in trades:      # each decision's P&L to resolution (attribution by stage)
            v = y if tr["side"] == "YES" else 1 - y
            tr["pnl"] = tr["shares"] * (v - tr["price"])
    return dict(trades=trades, marks=marks, pnl=pnl, yes=yes, no=no, cash=cash)


def params_for(kind, p: TakerParams):
    """The parameters one market is traded with: head-to-head markets may have their own threshold."""
    return replace(p, min_edge=p.min_edge_h2h) if kind == "race_h2h" and p.min_edge_h2h is not None else p


def run_weekend(markets, p: TakerParams):
    """markets: list of dict(key, kind, subject, outcome, stages). -> (trades df, per-market df)."""
    all_trades, per = [], []
    for mk in markets:
        r = run_market(mk["stages"], mk["outcome"], params_for(mk["kind"], p))
        for tr in r["trades"]:
            all_trades.append(dict(tr, key=mk["key"], kind=mk["kind"], subject=mk["subject"]))
        cost_basis = sum(tr["shares"] * tr["price"] for tr in r["trades"] if tr["shares"] > 0)
        per.append(dict(key=mk["key"], kind=mk["kind"], subject=mk["subject"], trades=len(r["trades"]),
                        bought=cost_basis, pnl=r["pnl"], outcome=mk["outcome"]))
    return pd.DataFrame(all_trades), pd.DataFrame(per)


def summarize(trades, per):
    if not len(per):
        return dict(markets=0, traded=0, trades=0, turnover=0.0, bought=0.0, pnl=0.0)
    t = per[per["trades"] > 0]
    turnover = float((trades["shares"].abs() * trades["price"]).sum()) if len(trades) else 0.0
    return dict(markets=len(per), traded=len(t), trades=int(per["trades"].sum()), turnover=turnover,
                bought=float(per["bought"].sum()), pnl=float(per["pnl"].fillna(0).sum()),
                roi=float(per["pnl"].fillna(0).sum() / per["bought"].sum()) if per["bought"].sum() > 0 else None)


def by(trades, col):
    """P&L to resolution of the trades made, grouped (e.g. by stage or kind)."""
    if not len(trades) or "pnl" not in trades:
        return pd.DataFrame(columns=[col, "trades", "pnl"])
    g = trades.groupby(col, sort=False).agg(trades=("pnl", "size"), pnl=("pnl", "sum"))
    return g.reset_index()
