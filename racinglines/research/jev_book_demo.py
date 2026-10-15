"""Jev book demo: a layered decision chain on sportsbook lines, priced as of a past moment and settled afterwards.

Research demo, paper only, in-sample: no trading flag is touched and nothing here is a claim about edge.

Jev sees only our fair price, the Polymarket (exchange) price and the sportsbook line, with the arithmetic done in
Python. Names and titles are withheld so a past event can't be recalled from memory. Four layers, each asked only if the
one before it passed its gate:

  L1 Noul    `plus_ev`   : is backing this line +EV?                       gate: probability >= min_noul
  L2 Choice  `trust`     : trust our fair price, the exchange price, or neither   gate: not `neither`, confidence >= min_conf
  L3 Choice  `sizing`    : one of a fixed set of sizing routines (Python computes the stake)
  L4 Choice  `final`     : place or pass the sized ticket                  gate: place, confidence >= min_conf

Answers are cached on disk (state, question and model make the key), so a rerun or an interrupted run resumes with no
repeat calls. Calls are counted against a budget before they are made.
"""
import hashlib
import json
from pathlib import Path

CACHE_DIR = Path("data/runs/jev_book_demo/cache")
DEFAULT_MODEL = "jev-latest"
BANKROLL = 100.0            # units; sizing routines are fractions of it
STAKE_CAP = 3.0             # units, applies to every routine
MIN_NOUL = 0.70
MIN_CONF = 0.60
DEFAULT_BUDGET = 200
SIZING = {                  # name -> (kind, parameter)
    "flat_1u": ("flat", 1.0),
    "kelly_eighth": ("kelly", 0.125),
    "kelly_quarter": ("kelly", 0.25),
    "kelly_half": ("kelly", 0.5),
}
LAYERS = ("plus_ev", "trust", "sizing", "final")

QUESTIONS = {
    "plus_ev": {
        "type": "noul",
        "instructions": (
            "A sportsbook offers a line at `decimal_odds` (implied probability `book_prob`). `fair` is our model's "
            "probability and `pm_price` the Polymarket price for the same outcome. `edge_fair` and `edge_pm` are each "
            "minus `book_prob`; `ev_fair` and `ev_pm` are the expected profit per unit staked. Is backing this line "
            "+EV, judged on both prices rather than one?"),
        "criteria": {"true": "Both prices clearly beat the book, or one does by a wide margin and the other does not "
                             "contradict it.",
                     "false": "The edge is thin, or the two prices disagree about it, or it is negative."},
    },
    "trust": {
        "type": "choice",
        "instructions": "Whose probability should size this bet: our fair price, the exchange price, or neither?",
        "criteria": {"trust_fair": "Our model's probability is the better estimate here.",
                     "trust_pm": "The exchange price is the better estimate here.",
                     "neither": "The two disagree too much to rely on either."},
    },
    "sizing": {
        "type": "choice",
        "instructions": "Pick one sizing routine for this bet from its edge and how well the two prices agree.",
        "criteria": {"flat_1u": "One flat unit.",
                     "kelly_eighth": "An eighth of the Kelly fraction: a small, cautious stake.",
                     "kelly_quarter": "A quarter of the Kelly fraction.",
                     "kelly_half": "Half the Kelly fraction: only for a large, well-agreed edge."},
    },
    "final": {
        "type": "choice",
        "instructions": "Given the sized ticket in `ticket`, place it or pass.",
        "criteria": {"place": "Place the ticket as sized.", "pass": "Do not place it."},
    },
}


# ---------------------------------------------------------------- lines

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf")


def eligible(row, need_pm=True):
    """(ok, reason) for a priced line: mapped, with odds and our fair price (and the exchange price if need_pm)."""
    if row.get("status") != "mapped":
        return False, f"status {row.get('status')}"
    for f in ("decimal_odds", "book_prob", "model_prob") + (("market_prob",) if need_pm else ()):
        if not _num(row.get(f)):
            return False, f"no {f}"
    if row["decimal_odds"] <= 1.0:
        return False, "decimal odds <= 1"
    return True, None


def line_state(row):
    """What Jev sees: prices and the line only. No name, title, event or outcome."""
    d, p_f = float(row["decimal_odds"]), float(row["model_prob"])
    b = float(row["book_prob"])
    st = {"kind": row.get("kind"), "n_legs": row.get("n_legs"), "decimal_odds": round(d, 3),
          "book_prob": round(b, 4), "fair": round(p_f, 4), "edge_fair": round(p_f - b, 4),
          "ev_fair": round(p_f * d - 1, 4)}
    if _num(row.get("market_prob")):
        p_m = float(row["market_prob"])
        st.update(pm_price=round(p_m, 4), edge_pm=round(p_m - b, 4), ev_pm=round(p_m * d - 1, 4))
    return st


def join(priced, settled=None, need_pm=True):
    """Priced lines in input order with the settled profit per unit (None if unsettled) joined by line id."""
    out = {r.get("id") or r.get("line"): r for r in (settled or {}).get("lines", [])}
    rows = []
    for r in priced["lines"]:
        key = r.get("id") or r.get("line")
        s = out.get(key, {})
        ok, why = eligible(r, need_pm)
        rows.append({"id": key, "row": r, "ok": ok, "why": why, "result": s.get("result"),
                     "profit": s.get("profit") if s.get("result") in ("won", "lost", "void") else None})
    return rows


# ---------------------------------------------------------------- exchange price from a trade export

def fill_pm(priced, now_priced, trades, asof):
    """Fill the exchange price of single-leg lines from `trades` (rows with token_id, ts, price): the last trade at or
    before `asof`. Tokens come from `now_priced` (the same book priced without asof, only for the leg-to-token link).
    Lines that already have an exchange price are left alone. Returns (priced, number filled)."""
    import pandas as pd
    cut = pd.Timestamp(asof)
    cut = cut.tz_localize("UTC") if cut.tzinfo is None else cut.tz_convert("UTC")
    last = {}
    for t in sorted(trades, key=lambda r: pd.Timestamp(r["ts"])):
        if pd.Timestamp(t["ts"]) <= cut:
            last[str(t["token_id"])] = float(t["price"])
    tok = {}
    for r in now_priced["lines"]:
        if len(r.get("legs", [])) == 1 and r["legs"][0].get("quotes"):
            tok[r.get("id")] = r["legs"][0]["quotes"][0]["token_id"]
    n = 0
    for r in priced["lines"]:
        px = last.get(tok.get(r.get("id")))
        if r.get("market_prob") is not None or px is None or r.get("status") != "mapped" or len(r["legs"]) != 1:
            continue
        p = 1.0 - px if r["legs"][0].get("side") in ("no", "under") else px
        r["market_prob"] = round(p, 6)
        r["ev_market"] = None if not _num(r.get("decimal_odds")) else round(p * r["decimal_odds"] - 1, 6)
        r["market_method"] = f"last polymarket trade by {cut:%Y-%m-%dT%H:%MZ}"
        n += 1
    return priced, n


# ---------------------------------------------------------------- sizing (Python owns the arithmetic)

def stake(routine, p, decimal_odds):
    """Units staked by a routine for win probability p; 0 when the bet is not +EV at p."""
    kind, par = SIZING[routine]
    if p * decimal_odds - 1 <= 0:
        return 0.0
    if kind == "flat":
        s = par
    else:
        s = BANKROLL * par * (p * decimal_odds - 1) / (decimal_odds - 1)
    return round(min(s, STAKE_CAP), 4)


# ---------------------------------------------------------------- the cached Jev call

class MissingCache(Exception):
    pass


class BudgetExhausted(Exception):
    pass


def question(layer, state):
    """The layer's question; without an exchange price in the state, `trust` offers only our fair price or neither."""
    q = QUESTIONS[layer]
    if layer == "trust" and "pm_price" not in state:
        q = dict(q, instructions="Should our fair price size this bet, or neither?",
                 criteria={k: v for k, v in q["criteria"].items() if k != "trust_pm"})
    return q


def _key(layer, state, model):
    blob = json.dumps({"layer": layer, "state": state, "question": question(layer, state), "model": model},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def cached(layer, state, model, cache_dir):
    p = Path(cache_dir) / f"{_key(layer, state, model)}.json"
    return json.loads(p.read_text()) if p.exists() else None


class Asker:
    """Answers from cache; otherwise one API call, counted against the budget before it is made."""

    def __init__(self, client=None, model=DEFAULT_MODEL, cache_dir=CACHE_DIR, budget=DEFAULT_BUDGET):
        self.client, self.model, self.cache_dir, self.budget = client, model, Path(cache_dir), budget
        self.calls = 0
        self.hits = 0

    def __call__(self, layer, state):
        hit = cached(layer, state, self.model, self.cache_dir)
        if hit is not None:
            self.hits += 1
            return hit
        if self.client is None:
            raise MissingCache(layer)
        if self.calls >= self.budget:
            raise BudgetExhausted(f"call budget {self.budget} used")
        self.calls += 1
        resp = self.client.system_one(state=state, questions={layer: question(layer, state)}, model=self.model)
        if layer == "plus_ev":
            rec = {"layer": layer, "noul": float(resp.nouls[layer].noul)}
        else:
            a = resp.choices[layer]
            rec = {"layer": layer, "choice": a.choice, "confidence": float(a.confidence),
                   "probabilities": dict(a.probabilities)}
        rec["answered_by"] = getattr(resp, "model", None)
        path = self.cache_dir / f"{_key(layer, state, self.model)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, sort_keys=True, indent=1, default=str))
        tmp.replace(path)
        return rec


# ---------------------------------------------------------------- the chain

def decide(state, ask, min_noul=MIN_NOUL, min_conf=MIN_CONF):
    """Run the four layers on one line. Returns a ticket dict; `stopped_at` names the layer that ended the chain."""
    t = {"layers": {}, "stopped_at": None, "stake": 0.0, "routine": None, "trust": None}

    a = ask("plus_ev", state)
    t["layers"]["plus_ev"] = a["noul"]
    if a["noul"] < min_noul:
        t["stopped_at"] = "plus_ev"
        return t

    a = ask("trust", dict(state, plus_ev=round(t["layers"]["plus_ev"], 3)))
    t["layers"]["trust"] = {"choice": a["choice"], "confidence": a["confidence"]}
    if a["choice"] == "neither" or a["confidence"] < min_conf:
        t["stopped_at"] = "trust"
        return t
    t["trust"] = a["choice"]
    p = state["fair"] if a["choice"] == "trust_fair" else state["pm_price"]

    s2 = dict(state, trusted="fair" if a["choice"] == "trust_fair" else "pm_price", p_used=p,
              kelly_full=round(max(0.0, (p * state["decimal_odds"] - 1) / (state["decimal_odds"] - 1)), 4))
    a = ask("sizing", s2)
    t["layers"]["sizing"] = {"choice": a["choice"], "confidence": a["confidence"]}
    t["routine"] = a["choice"]
    t["stake"] = stake(a["choice"], p, state["decimal_odds"])
    if t["stake"] <= 0:
        t["stopped_at"] = "sizing"
        return t

    a = ask("final", dict(state, ticket={"routine": t["routine"], "stake_units": t["stake"], "p_used": p}))
    t["layers"]["final"] = {"choice": a["choice"], "confidence": a["confidence"]}
    if a["choice"] != "place" or a["confidence"] < min_conf:
        t["stopped_at"] = "final"
        t["stake"] = 0.0
    return t


# ---------------------------------------------------------------- baselines and report

def _pnl(rows, stakes):
    """Totals over the settled lines that were staked: units staked, profit, ROI, bets, wins."""
    n = w = 0
    staked = profit = 0.0
    for r, s in zip(rows, stakes):
        if s <= 0 or r["profit"] is None:
            continue
        n += 1
        staked += s
        profit += s * r["profit"]
        w += r["result"] == "won"
    return {"bets": n, "wins": w, "staked": round(staked, 4), "profit": round(profit, 4),
            "roi": None if staked == 0 else round(profit / staked, 4)}


def baselines(rows):
    """Rules Jev must beat: take every eligible line flat; +EV on every price it has, flat; the same at quarter Kelly on fair."""
    def go(f):
        return [f(r["row"]) if r["ok"] else 0.0 for r in rows]
    both = lambda x: x["model_prob"] * x["decimal_odds"] > 1 and (x.get("market_prob") is None or x["market_prob"] * x["decimal_odds"] > 1)
    return {
        "take_all_flat_1u": _pnl(rows, go(lambda x: 1.0)),
        "plus_ev_flat_1u": _pnl(rows, go(lambda x: 1.0 if both(x) else 0.0)),
        "plus_ev_kelly_quarter_fair": _pnl(rows, go(lambda x: stake("kelly_quarter", x["model_prob"], x["decimal_odds"]) if both(x) else 0.0)),
    }


def calibration(rows, tickets):
    """L1 only: mean Jev probability against how often +EV-by-fair lines made money, in thirds, plus Brier vs the
    line's win outcome (Jev's number is a +EV probability, so this is a rough check, not a score of the layer)."""
    pts = [(t["layers"]["plus_ev"], 1.0 if r["profit"] > 0 else 0.0)
           for r, t in zip(rows, tickets) if t and "plus_ev" in t["layers"] and r["profit"] is not None]
    if not pts:
        return {"n": 0}
    pts.sort()
    k = max(1, len(pts) // 3)
    groups = [pts[i:i + k] for i in range(0, len(pts), k)]
    return {"n": len(pts), "bins": [{"n": len(g), "mean_noul": round(sum(p for p, _ in g) / len(g), 3),
                                     "made_money": round(sum(y for _, y in g) / len(g), 3)} for g in groups]}


def run(priced, settled=None, ask=None, min_noul=MIN_NOUL, min_conf=MIN_CONF, need_pm=True):
    """Chain over every eligible line, stopping cleanly if the budget or the cache runs out (warm start on rerun)."""
    rows = join(priced, settled, need_pm)
    tickets, halted = [], None
    for r in rows:
        if not r["ok"]:
            tickets.append(None)
            continue
        if halted:
            tickets.append(None)
            continue
        try:
            tickets.append(decide(line_state(r["row"]), ask, min_noul, min_conf))
        except (BudgetExhausted, MissingCache) as e:
            halted = f"{type(e).__name__}: {e}"
            tickets.append(None)
    stakes = [t["stake"] if t else 0.0 for t in tickets]
    funnel = {"lines": len(rows), "eligible": sum(r["ok"] for r in rows),
              "scored": sum(t is not None for t in tickets)}
    for layer in LAYERS:
        funnel["asked_" + layer] = sum(1 for t in tickets if t and layer in t["layers"])
    funnel["placed"] = sum(1 for t in tickets if t and t["stake"] > 0)
    stops = {}
    for t in tickets:
        if t and t["stopped_at"]:
            stops[t["stopped_at"]] = stops.get(t["stopped_at"], 0) + 1
    return {"funnel": funnel, "stopped_at": stops, "halted": halted, "jev": _pnl(rows, stakes),
            "baselines": baselines(rows), "calibration": calibration(rows, tickets),
            "unsettled": sum(1 for r in rows if r["ok"] and r["profit"] is None),
            "skipped": {r["id"]: r["why"] for r in rows if not r["ok"]},
            "tickets": [{"id": r["id"], "result": r["result"], "profit_per_unit": r["profit"], **(t or {"scored": False})}
                        for r, t in zip(rows, tickets)]}


def plan(priced, model=DEFAULT_MODEL, cache_dir=CACHE_DIR, budget=DEFAULT_BUDGET, need_pm=True):
    """No network: eligible lines, how many layer-1 answers are cached, and the worst case calls (4 per line)."""
    states = [line_state(r["row"]) for r in join(priced, None, need_pm) if r["ok"]]
    l1 = sum(cached("plus_ev", s, model, cache_dir) is not None for s in states)
    worst = 4 * len(states) - l1
    return {"eligible_lines": len(states), "layer1_cached": l1, "layer1_calls": len(states) - l1,
            "max_calls": worst, "budget": budget, "budget_covers_layer1": budget >= len(states) - l1,
            "note": "later layers run only for lines that pass the gate before; their cache hits are counted at run time"}


def format_report(res, name="jev book demo"):
    f, j = res["funnel"], res["jev"]
    L = [f"# {name}", "",
         "Paper only, in-sample. Jev saw fair, exchange price and the line, with names withheld. Samples this small "
         "show the chain working, not edge.", "",
         f"Lines {f['lines']}, eligible {f['eligible']}, scored {f['scored']}, placed {f['placed']}. "
         f"Unsettled (excluded from P&L): {res['unsettled']}."]
    if res["halted"]:
        L += ["", f"**Halted early** ({res['halted']}). Rerun to continue from the cache."]
    L += ["", "## Funnel", "", "| layer | asked | stopped here |", "|---|---|---|"]
    for ly in LAYERS:
        L.append(f"| {ly} | {f['asked_' + ly]} | {res['stopped_at'].get(ly, 0)} |")
    L += ["", "## Paper P&L (units; settled lines only)", "", "| strategy | bets | wins | staked | profit | ROI |", "|---|---|---|---|---|---|"]
    for k, v in [("jev chain", j), *res["baselines"].items()]:
        roi = "n/a" if v["roi"] is None else f"{v['roi']:+.1%}"
        L.append(f"| {k} | {v['bets']} | {v['wins']} | {v['staked']} | {v['profit']:+.2f} | {roi} |")
    c = res["calibration"]
    L += ["", "## Layer 1 against outcomes", ""]
    if c["n"] == 0:
        L.append("No settled scored lines.")
    else:
        L += ["| bin | n | mean Jev P(+EV) | share that made money |", "|---|---|---|---|"]
        for i, b in enumerate(c["bins"], 1):
            L.append(f"| {i} | {b['n']} | {b['mean_noul']} | {b['made_money']} |")
    if res["skipped"]:
        L += ["", "## Skipped lines", ""] + [f"- {k}: {v}" for k, v in res["skipped"].items()]
    L += ["", "## What this does not show", "",
          "One event window, hand-supplied lines, no significance test, no promotion. A decision-log entry would be "
          "needed before any gate value here is treated as tuned."]
    return "\n".join(L) + "\n"
