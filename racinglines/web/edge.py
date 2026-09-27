"""
Edge Finder: the Lab's headline view. A user's chosen (model variant, strategy) combos, each read
from the latest saved season sweep of that variant (kind 'sweep', racinglines f1 sweep): total P&L,
weekends up, and P&L per weekend side by side.

The selection is stored per user in users.prefs["edge_finder"] as [[variant, strategy], ...];
with none stored, the default is the baseline model with every strategy.
"""

from sqlalchemy import text

from racinglines.models.position_sim import evaluate as EV
from racinglines.models.position_sim import variants as V
from racinglines.web import prefs as P

STRATEGY_LABEL = dict(EV.STRATEGIES)
STRATEGY_KEYS = [k for k, _ in EV.STRATEGIES]
DEFAULT = [("baseline", k) for k in STRATEGY_KEYS]
MAX_COMBOS = 30
IN_SAMPLE = {"early"}          # rules drawn from the sweep they're scored on
# The benchmark every combo is measured against, pinned so it can't be removed or replaced: the
# conservative maker replay (quote fair ± 2c, conservative fills) on the baseline model, from the
# latest baseline sweep at the default sweep settings (a sweep run with other knobs never replaces it).
BENCHMARK = ("baseline", "maker")
DEFAULT_SWEEP = dict(min_edge=0.05, stake_per_edge=250.0, max_stake=50.0, cost=0.01)


def label(strategy):
    return STRATEGY_LABEL[strategy].replace("Taker: ", "").replace("Maker: ", "Maker, ")


def valid(variant, strategy):
    if strategy not in STRATEGY_LABEL:
        return False
    try:
        V.switches(variant)
    except ValueError:
        return False
    return True


def combos(conn, user_id):
    """The user's combos, or the default."""
    got = P.get(conn, user_id).get("edge_finder")
    if got is None:
        return list(DEFAULT)
    return [(v, s) for v, s in got if valid(v, s)]


def save(conn, user_id, cs):
    out = list(dict.fromkeys((v, s) for v, s in cs if valid(v, s)))[:MAX_COMBOS]
    P.put(conn, user_id, "edge_finder", [list(c) for c in out])
    return out


def apply(cs, action, variant="", strategy=""):
    """New combo list after one edit. add_model: the model x every strategy already shown (all
    strategies if none); add_strategy: the strategy x every model already shown (baseline if none)."""
    cs = list(cs)
    if action == "reset":
        return list(DEFAULT)
    if action == "clear":
        return []
    if action in ("add", "remove", "toggle") and not valid(variant, strategy):
        raise ValueError("unknown model or strategy")
    if action == "add" or (action == "toggle" and (variant, strategy) not in cs):
        return cs + [(variant, strategy)] if (variant, strategy) not in cs else cs
    if action in ("remove", "toggle"):
        return [c for c in cs if c != (variant, strategy)]
    if action == "add_model":
        if not valid(variant, STRATEGY_KEYS[0]):
            raise ValueError("unknown model")
        strategies = list(dict.fromkeys(s for _, s in cs)) or STRATEGY_KEYS
        return cs + [(variant, s) for s in strategies if (variant, s) not in cs]
    if action == "remove_model":
        return [c for c in cs if c[0] != variant]
    if action == "add_strategy":
        if strategy not in STRATEGY_LABEL:
            raise ValueError("unknown strategy")
        models = list(dict.fromkeys(v for v, _ in cs)) or ["baseline"]
        return cs + [(v, strategy) for v in models if (v, strategy) not in cs]
    raise ValueError(f"unknown action {action!r}")


def swept_variants(conn, year=2026):
    return [r[0] for r in conn.execute(text("""SELECT coalesce(params->>'variant', 'baseline') v FROM model_runs
                                              WHERE kind = 'sweep' AND (params->>'year')::int = :y
                                              GROUP BY 1 ORDER BY min(id)"""), dict(y=year))]


def build(conn, cs, year=2026):
    """dict(cards, weekends, columns, detail, missing) for the template."""
    sweeps = {}
    for v in dict.fromkeys(v for v, _ in cs):
        r = EV._latest(conn, "sweep", v, f"AND (params->>'year')::int = {int(year)}")
        if r:
            sweeps[v] = dict(id=int(r[0]), params=r[1] or {}, metrics=r[2] or {})
    cards, columns, missing = [], [], []
    for v, s in cs:
        sw = sweeps.get(v)
        t = (sw["metrics"].get("totals") or {}).get(s) if sw else None
        if not t:
            missing.append(dict(variant=v, strategy=s, label=label(s)))
            continue
        maker = s.startswith("maker")
        cards.append(dict(variant=v, strategy=s, label=label(s), pnl=t["pnl"], volume=t["bought"],
                          volume_label="filled" if maker else "bought", up=t["weekends_up"], weekends=t["weekends"],
                          run_id=sw["id"], in_sample=s in IN_SAMPLE))
        columns.append((v, s))
    events = {}
    for v, s in columns:
        for w in sweeps[v]["metrics"].get("weekends") or []:
            e = events.setdefault(w["event_key"], dict(event=w["event"], event_key=w["event_key"], round=w.get("round"),
                                                       format=w.get("format"), last_run_id=w.get("last_run_id"), cells={}))
            e["cells"][v, s] = w.get(f"{s}_pnl")
    weekends = sorted(events.values(), key=lambda e: (e["round"] is None, e["round"] or 0, e["event_key"]))
    for e in weekends:
        e["cells"] = [e["cells"].get(c) for c in columns]
    bench = benchmark(conn, year)
    if bench:          # the pinned card already shows this combo (its weekend column stays)
        cards = [c for c in cards if not ((c["variant"], c["strategy"]) == BENCHMARK and c["run_id"] == bench["run_id"])]
    for c in cards:
        c["vs_bench"] = c["pnl"] - bench["pnl"] if bench and (c["variant"], c["strategy"]) != BENCHMARK else None
    best = max((c["pnl"] for c in cards), default=None)
    for c in cards:
        c["best"] = len(cards) > 1 and c["pnl"] == best
    first = next((sweeps[v] for v, _ in cs if v in sweeps), None)
    return dict(benchmark=bench, cards=cards, weekends=weekends, columns=[dict(variant=v, strategy=s, label=label(s)) for v, s in columns],
                missing=missing, detail=first, detail_variant=next((v for v, _ in cs if v in sweeps), None))


def benchmark(conn, year=2026):
    """The pinned benchmark card (see BENCHMARK), or None if no default-settings baseline sweep exists."""
    same = " ".join(f"AND (params->>'{k}')::float = {v}" for k, v in DEFAULT_SWEEP.items())
    r = EV._latest(conn, "sweep", BENCHMARK[0], f"AND (params->>'year')::int = {int(year)} {same}")
    t = ((r[2] or {}).get("totals") or {}).get(BENCHMARK[1]) if r else None
    if not t:
        return None
    return dict(variant=BENCHMARK[0], strategy=BENCHMARK[1], label=label(BENCHMARK[1]), pnl=t["pnl"], volume=t["bought"],
                up=t["weekends_up"], weekends=t["weekends"], run_id=int(r[0]))
