"""
Weekend sweep: every race of a season, traded through the weekend.

For each race:
  1. Stages from the real session schedule (FastF1): before any running, then
     DATA_LAG after each session ends (practice, sprint qualifying, sprint,
     qualifying). The race itself is never traded.
  2. At each stage, price the race as of that moment (position_sim.pricing.price_race: only data
     from sessions that started before the cutoff) and store it as a
     kind='diagnostic' run tagged with the stage.
  3. Read Polymarket at that moment (5-minute prices, trades for liquidity) and
     run the taker strategies in racinglines/markets/strategies/taker_weekend.py (update / hold / last) plus the
     maker replay (racinglines/markets/strategies/maker_replay.py) through the same stages.
  4. Only then read the result: settle, score, summarise.

The model uses qualifying, sprint and race results; practice pace isn't in the
model yet, so our fair value only moves after sprint qualifying / sprint /
qualifying, while the market moves after every session.
"""

import logging
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from racinglines import sports
from racinglines.markets.strategies import taker_weekend as RB
from racinglines.core.stats import last_at

_SCHEDULE = sports.load("f1")["sessions"]["schedule"]       # FastF1 session name -> [minutes, short label]
SESSION_MINUTES = {name: m for name, (m, _) in _SCHEDULE.items()}
SHORT = {name: short for name, (_, short) in _SCHEDULE.items()}
DATA_LAG = timedelta(minutes=30)     # a session's data is used 30 min after it ends
PRE = timedelta(hours=1)             # "before any running": 1 h before the first session
KINDS = tuple(sports.load("f1")["markets"]["weekend_kinds"])
GROUP_TARGET = {"race_win": 1, "race_pole": 1, "race_constructor_top": 1, "race_podium": 3}
COHERENCE_TOL = 0.25
STALE = timedelta(hours=6)
MIN_VOLUME_24H = 50.0                # $ traded in the market over the previous 24 h
TAKER_MODES = ("update", "hold", "last", "early")
# maker settings replayed side by side (docs/f1-roadmap.md, F1-4); all chosen a priori, not tuned
MAKERS = {"maker": {},
          "maker_flat": dict(flatten_before_qual=True),        # go flat at the market before qualifying
          "maker_skew": dict(info_skew=2.0),                    # skew harder as each session approaches
          "maker_widen": dict(widen=True),                      # wider where earlier weekends' markouts were bad
          "maker_all": dict(flatten_before_qual=True, info_skew=2.0, widen=True)}
WIDEN = 1.5                          # half-spread multiplier for widened market kinds


def schedule(year, rounds=None):
    """{round: dict(event_key, name, format, race_start, sessions, stages=[(label, cutoff)])} (naive UTC)."""
    import fastf1
    from racinglines.sources.fastf1.fetch import CACHE
    logging.getLogger("fastf1").setLevel(logging.ERROR)
    CACHE.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE))
    sch = fastf1.get_event_schedule(year, include_testing=False)
    out = {}
    for ev in sch.itertuples():
        rnd = int(ev.RoundNumber)
        if rounds and rnd not in rounds:
            continue
        sessions = []
        for i in range(1, 6):
            name, start = getattr(ev, f"Session{i}"), getattr(ev, f"Session{i}DateUtc")
            if name and not pd.isna(start):
                sessions.append((name, pd.Timestamp(start).tz_localize(None)))
        race = next((t for n, t in sessions if n == "Race"), None)
        if race is None:
            continue
        stages = [("pre-weekend", sessions[0][1] - PRE)]
        for name, start in sessions:
            if name in SESSION_MINUTES:
                cut = start + timedelta(minutes=SESSION_MINUTES[name]) + DATA_LAG
                if cut < race:
                    stages.append((f"after {SHORT[name]}", cut))
        out[rnd] = dict(event_key=f"{year}-{rnd:02d}", name=ev.EventName, format=ev.EventFormat, race_start=race,
                        qual_start=next((t for n, t in sessions if n == "Qualifying"), None),
                        sessions=[(SHORT.get(n, n), t) for n, t in sessions], stages=stages)
    return out


def price_stages(meas, hist, sched, engine, engine_url=None, n_sims=4000, reprice=False, echo=print,
                 variant="baseline"):
    """Diagnostic run per (race, stage); reuses stored ones with the same cutoff and model
    variant unless reprice (runs stored without a variant are the baseline).
    Returns {event_key: [(label, cutoff, run_id), ...]}."""
    from racinglines.models.position_sim import pricing as run
    with engine.connect() as c:
        have = pd.read_sql(text("""SELECT id, params->>'event_key' AS k, params->>'cutoff' AS cutoff
                                   FROM model_runs WHERE kind = 'diagnostic' AND params ? 'sweep_stage'
                                     AND coalesce(params->>'variant', 'baseline') = :v
                                   ORDER BY id"""), c, params=dict(v=variant))
    have = {(k, str(pd.Timestamp(cu))): int(i) for i, k, cu in zip(have["id"], have["k"], have["cutoff"])}
    out = {}
    for rnd, w in sched.items():
        ev = meas.res[(meas.res["year"] == int(w["event_key"][:4])) & (meas.res["series_round"] == rnd)]
        if ev.empty or not (ev["round"] == "race").any():
            continue                                     # not raced yet
        runs = []
        for label, cutoff in w["stages"]:
            k = (w["event_key"], str(pd.Timestamp(cutoff)))
            if k in have and not reprice:
                runs.append((label, cutoff, have[k]))
                continue
            _, summ, ex, _ = run.diagnostic(meas, hist, w["event_key"], cutoff, n_sims=n_sims)
            extra = {} if variant == "baseline" else dict(variant=variant)
            rid = run.save_diagnostic(engine_url, w["event_key"], cutoff, summ, ex, n_sims, sweep_stage=label, **extra)
            runs.append((label, cutoff, rid))
        out[w["event_key"]] = runs
        echo(f"progress {len(out)}/{len(sched)} priced {w['event_key']} {w['name']}: "
             + ", ".join(f"{lab} #{rid}" for lab, _, rid in runs))
    return out


def _token0_links(conn, race_id):
    links = pd.read_sql(text("""SELECT ml.*, a.display_name AS athlete FROM market_links ml
                                LEFT JOIN athletes a ON a.id = ml.athlete_id
                                WHERE ml.race_id = :r AND ml.prediction = ANY(:k) ORDER BY ml.id"""), conn,
                        params=dict(r=race_id, k=list(KINDS)))
    return links.drop_duplicates("condition_id", keep="first")


def _race_id(conn, event_key):
    return conn.execute(text("SELECT ra.id FROM races ra JOIN events e ON e.id = ra.event_id WHERE e.source_key = :k"),
                        dict(k=event_key)).scalar()


def fetch_market_data(session, conn, sched, fidelity=5, force=False, echo=print):
    """Polymarket price history (one token per question) over each weekend, and the trade tape."""
    from racinglines.markets.polymarket.sync import fetch_history, fetch_trades
    for rnd, w in sched.items():
        rid = _race_id(conn, w["event_key"])
        if rid is None:
            continue
        links = _token0_links(conn, rid)
        if not len(links):
            continue
        start = (w["stages"][0][1] - timedelta(hours=36)).tz_localize("UTC").to_pydatetime()
        end = (w["race_start"] + timedelta(hours=3)).tz_localize("UTC").to_pydatetime()
        from racinglines.markets import store as MS
        n_have = len(MS.read(conn, "prices", tokens=links["token_id"].tolist(), start=start, end=end))
        if n_have and not force:
            echo(f"progress {w['event_key']} market data already stored ({n_have} points)")
            continue
        n = fetch_history(session, conn, None, start, end, fidelity=fidelity, tokens=links["token_id"].tolist())
        k = fetch_trades(session, conn, links["event_slug"].dropna().unique().tolist(), modeled_only=True)
        echo(f"progress {w['event_key']} {w['name']}: {n} price points, {k} trades")


def _series(conn, tokens, conds, start, end):
    from racinglines.markets import store as MS
    a, b = pd.Timestamp(start).tz_localize("UTC"), pd.Timestamp(end).tz_localize("UTC")
    ph = MS.read(conn, "prices", tokens=tokens, start=a, end=b)[["token_id", "ts", "price"]]
    tr = MS.read(conn, "trades", conditions=conds, start=a - timedelta(hours=24), end=b)
    tr = tr.assign(usd=tr["price"] * tr["size"])[["condition_id", "ts", "usd"]]
    for df in (ph, tr):
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
    return {t: g for t, g in ph.groupby("token_id")}, {c: g for c, g in tr.groupby("condition_id")}


def _price_at_g(g, t):
    return None if g is None else last_at(pd.DatetimeIndex(g["ts"]), g["price"].to_numpy(), t, STALE)


def _vol24(g, t):
    if g is None:
        return 0.0
    a, b = g["ts"].searchsorted(t - timedelta(hours=24)), g["ts"].searchsorted(t, side="right")
    return float(g["usd"].iloc[a:b].sum())


def weekend_markets(conn, w, stage_runs):
    """The weekend's tradeable markets for racinglines/markets/strategies/taker_weekend.py: per market, each stage's fair,
    exchange price and tradeable flag (what was knowable then) and the outcome (settlement)."""
    from racinglines.db import reads as D
    from racinglines.markets import private_book as house
    rid = _race_id(conn, w["event_key"])
    links = _token0_links(conn, rid)
    if not len(links):
        return None
    start, end = stage_runs[0][1] - timedelta(hours=1), w["race_start"]
    prices, trades = _series(conn, links["token_id"].tolist(), links["condition_id"].tolist(), start, end)
    res = house.race_outcomes(conn, rid)
    cache, markets = {}, []
    fair = {}   # (token, stage) -> fair
    for lab, cutoff, run_id in stage_runs:
        for link in links.to_dict("records"):
            fair[(link["token_id"], lab)] = D.model_prob(conn, link, cache, run_id=run_id)[0]
    # coherence of each multi-outcome group at each stage (stale/empty books are skipped)
    coherent = {}
    for lab, cutoff, _ in stage_runs:
        for kind, target in GROUP_TARGET.items():
            g = links[links["prediction"] == kind]
            ps = [_price_at_g(prices.get(t), cutoff) for t in g["token_id"]]
            ps = [p for p in ps if p is not None]
            coherent[(kind, lab)] = bool(ps) and abs(sum(ps) - target) <= COHERENCE_TOL * target
    for link in links.to_dict("records"):
        kind = link["prediction"]
        ath = None if pd.isna(link["athlete_id"]) else int(link["athlete_id"])
        stages = []
        for lab, cutoff, _ in stage_runs:
            price = _price_at_g(prices.get(link["token_id"]), cutoff)
            f = fair[(link["token_id"], lab)]
            open_ = not (kind == "race_pole" and w["qual_start"] is not None and cutoff >= w["qual_start"])
            ok = (price is not None and f is not None and open_ and coherent.get((kind, lab), True)
                  and 0 < price < 1 and _vol24(trades.get(link["condition_id"]), cutoff) >= MIN_VOLUME_24H)
            stages.append(dict(label=lab, t=cutoff, fair=f, price=price, tradeable=ok))
        subject = link["athlete"] or (link["params"] or {}).get("team") or link["group_title"]
        if kind == "race_h2h":
            subject = f"{link['outcome']} ({link['question'].split(': ')[-1]})"
        markets.append(dict(key=link["token_id"], kind=kind, subject=subject, stages=stages,
                            outcome=house.outcome_for(kind, ath, link["params"], res)))
    return markets


def weekend(conn, w, stage_runs, params_list, echo=print, widen_kinds=()):
    """Trade one weekend. Returns dict(summary rows per mode, trades, stage scores, makers).
    widen_kinds: market kinds whose maker fills lost on 60-min markouts in EARLIER weekends."""
    markets = weekend_markets(conn, w, stage_runs)
    if markets is None:
        return None
    out = dict(modes={}, trades={})
    for p in params_list:
        tr, per = RB.run_weekend(markets, p)
        out["modes"][p.mode] = RB.summarize(tr, per)
        out["trades"][p.mode] = tr
    # model vs market at each stage, scored on the result (every kind; pole before qualifying)
    scores = []
    for lab, cutoff, _ in stage_runs:
        for kind in KINDS:
            rows = [(s["fair"], s["price"], float(m["outcome"])) for m in markets if m["kind"] == kind
                    for s in m["stages"] if s["label"] == lab and s["fair"] is not None and s["price"] is not None
                    and m["outcome"] is not None and s["tradeable"]]
            if len(rows) >= 5:
                f, pm, y = np.array(rows).T
                scores.append(dict(stage=lab, kind=kind, n=len(rows), brier_model=float(np.mean((f - y) ** 2)),
                                   brier_market=float(np.mean((pm - y) ** 2))))
    out["scores"] = scores
    out["markets"] = len(markets)
    out["tradeable_first"] = sum(m["stages"][0]["tradeable"] for m in markets)
    out["tradeable_last"] = sum(m["stages"][-1]["tradeable"] for m in markets)
    # maker replays through the same stages (conservative fills), one per setting
    out["makers"], out["markout_by_kind"] = {}, {}
    try:
        from dataclasses import replace

        from racinglines.markets.strategies import maker_replay as R
        ev = R.load_event(conn, [r for _, _, r in stage_runs])
    except Exception as ex:  # noqa: BLE001  (no tape for this weekend)
        echo(f"  maker replay skipped: {ex}")
        ev = None
    for name, opts in MAKERS.items() if ev is not None else []:
        opts = dict(opts)
        p = R.Params()
        if opts.pop("widen", False):
            opts["half_spread_by_kind"] = {k: p.half_spread * WIDEN for k in widen_kinds}
        rep = R.replay(ev, replace(p, **opts))
        sk = R.summary(rep)
        s = sk.loc["total"]
        out["makers"][name] = dict(fills=int(s["fills"]), notional=float(s["notional"]), pnl=float(s["pnl"]),
                                   markout_60m=float(s["markout_60m"]), spread_pnl=float(s["spread_pnl"]))
        if name == "maker":
            out["markout_by_kind"] = sk.drop(index="total")["markout_60m"].to_dict()
    out["maker"] = out["makers"].get("maker")
    return out


def run_sweep(engine, engine_url, year, rounds=None, n_sims=4000, fetch=True, reprice=False, taker=None, echo=print,
              variant="baseline"):
    """The whole season. Returns dict(weekends DataFrame, by_stage, by_kind, totals, trades, scores, params)."""
    from racinglines.db.config import get_session

    from racinglines.models.position_sim import pricing as run
    sched = schedule(year, rounds)
    if fetch:
        with engine.connect() as c, get_session(engine_url) as s:
            fetch_market_data(s, c, sched, echo=echo)
    echo("progress 0/1 building history")
    meas = run.Measurements.load(engine)
    hist = run.history(meas)
    stage_runs = price_stages(meas, hist, sched, engine, engine_url, n_sims=n_sims, reprice=reprice, echo=echo,
                              variant=variant)
    base = taker or RB.TakerParams()
    params_list = [RB.TakerParams(**{**base.__dict__, "mode": m}) for m in TAKER_MODES]
    rows, all_trades, all_scores = [], [], []
    markouts = {}                      # market kind -> maker's 60-min markout so far (as of each weekend)
    for rnd, w in sched.items():
        runs = stage_runs.get(w["event_key"])
        if not runs:
            continue
        with engine.connect() as c:
            r = weekend(c, w, runs, params_list, echo=echo, widen_kinds=[k for k, v in markouts.items() if v < 0])
        if r is None:
            continue
        for k, v in r["markout_by_kind"].items():
            markouts[k] = markouts.get(k, 0.0) + v
        row = dict(round=rnd, event_key=w["event_key"], event=w["name"], format=w["format"], stages=len(runs),
                   markets=r["markets"], tradeable_pre=r["tradeable_first"], tradeable_quali=r["tradeable_last"],
                   last_run_id=runs[-1][2])
        for mode, s in r["modes"].items():
            row.update({f"{mode}_{k}": v for k, v in s.items()})
        for name, m in r["makers"].items():
            row.update({f"{name}_{k}": v for k, v in m.items()})
        rows.append(row)
        t = r["trades"]["update"]
        if len(t):
            all_trades.append(t.assign(event_key=w["event_key"], event=w["name"]))
        all_scores += [dict(s, event_key=w["event_key"]) for s in r["scores"]]
        echo(f"progress {len(rows)}/{len(sched)} traded {w['event_key']} {w['name']}: "
             f"update {row.get('update_pnl', 0):+.2f} · hold {row.get('hold_pnl', 0):+.2f} · "
             f"after-quali {row.get('last_pnl', 0):+.2f} · maker {row.get('maker_pnl', float('nan')):+.2f}")
    weekends = pd.DataFrame(rows)
    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    stage_order = ["pre-weekend", "after FP1", "after SQ", "after Sprint", "after FP2", "after FP3", "after Quali"]
    by_stage = RB.by(trades, "stage")
    if len(by_stage):
        by_stage["o"] = by_stage["stage"].map({s: i for i, s in enumerate(stage_order)}).fillna(99)
        by_stage = by_stage.sort_values("o").drop(columns="o")
    scores = pd.DataFrame(all_scores)
    score_stage = (scores.groupby(["kind", "stage"])[["n", "brier_model", "brier_market"]]
                   .agg({"n": "sum", "brier_model": "mean", "brier_market": "mean"}).reset_index()
                   if len(scores) else scores)
    totals = {}
    for mode in (*TAKER_MODES, *MAKERS):
        col = f"{mode}_pnl"
        if col in weekends:
            spent = f"{mode}_notional" if mode.startswith("maker") else f"{mode}_bought"
            totals[mode] = dict(pnl=float(weekends[col].fillna(0).sum()),
                                weekends_up=int((weekends[col] > 0).sum()), weekends=int(weekends[col].notna().sum()),
                                bought=float(weekends.get(spent, pd.Series(dtype=float)).fillna(0).sum()))
    return dict(weekends=weekends, by_stage=by_stage, by_kind=RB.by(trades, "kind"), totals=totals, trades=trades,
                scores=score_stage, params=dict(base.__dict__, n_sims=n_sims, data_lag_min=DATA_LAG.seconds // 60,
                                                min_volume_24h=MIN_VOLUME_24H, coherence_tol=COHERENCE_TOL))
