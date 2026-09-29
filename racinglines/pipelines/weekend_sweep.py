"""
Weekend sweep: every race of a season, traded through the weekend.

For each race:
  1. Stages from the real session schedule (FastF1): before any running, then
     DATA_LAG after each session ends (practice, sprint qualifying, sprint,
     qualifying). The race itself is never traded.
  2. At each stage, price the race as of that moment (position_sim.pricing.price_race: only data
     from sessions that started before the cutoff) and store it as a
     kind='diagnostic' run tagged with the stage.
  3. Read the venue at that moment (5-minute prices, trades for liquidity) and
     run the taker strategies in racinglines/markets/strategies/taker_weekend.py (update / hold / last) plus the
     maker replay (racinglines/markets/strategies/maker_replay.py) through the same stages.
  4. Only then read the result: settle, score, summarise.

The venue is Polymarket unless the settings say `venue = "kalshi"` (`--venue kalshi`): then the race's
Kalshi links are read (one market per ticker, never grouped by condition_id, which is the event ticker),
its tape per market from data/archive/markets/kalshi/, and the maker pays Kalshi's maker fee. Nothing
about the default changes.

The model uses qualifying, sprint and race results; practice pace isn't in the
model yet, so our fair value only moves after sprint qualifying / sprint /
qualifying, while the market moves after every session.
"""

import logging
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from racinglines import sports
from racinglines.markets.strategies import taker_weekend as RB
from racinglines.core import calibration as CAL
from racinglines.core import stages as STG

_SCHEDULE = sports.load("f1")["sessions"]["schedule"]       # FastF1 session name -> [minutes, short label]
SESSION_MINUTES = {name: m for name, (m, _) in _SCHEDULE.items()}
SHORT = {name: short for name, (_, short) in _SCHEDULE.items()}
_STAGES = STG.spec("f1")                                     # sports/f1.toml [stages] (core/stages.py)
DATA_LAG = timedelta(minutes=_STAGES["lag_minutes"])         # a session's data is used 30 min after it ends
PRE = timedelta(minutes=_STAGES["pre_minutes"])              # "before any running": 1 h before the first session
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


SCHEDULE_COLS = ["RoundNumber", "EventName", "EventFormat"] + [f"Session{i}{x}" for i in range(1, 6) for x in ("", "DateUtc")]


def _event_schedule(year):
    """FastF1's event schedule, saved next to the raw files (data/raw/f1/fastf1/<year>/schedule.parquet)
    so a machine without access to FastF1's servers (e.g. a cloud session) can still build the sweep."""
    import fastf1
    from racinglines.sources.fastf1.fetch import CACHE, OUT
    snap = OUT / str(year) / "schedule.parquet"
    try:
        logging.getLogger("fastf1").setLevel(logging.ERROR)
        CACHE.mkdir(parents=True, exist_ok=True)
        fastf1.Cache.enable_cache(str(CACHE))
        sch = pd.DataFrame(fastf1.get_event_schedule(year, include_testing=False))[SCHEDULE_COLS]
        if snap.parent.is_dir():
            sch.to_parquet(snap, index=False)
        return sch
    except Exception:  # noqa: BLE001  (offline: fall back to the saved copy)
        if snap.is_file():
            return pd.read_parquet(snap)
        raise


def schedule(year, rounds=None):
    """{round: dict(event_key, name, format, race_start, sessions, stages=[(label, cutoff)])} (naive UTC)."""
    sch = _event_schedule(year)
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
        b = STG.build(sessions, "f1")                        # the stages, from the schema
        if b is None:
            continue
        out[rnd] = dict(event_key=f"{year}-{rnd:02d}", name=ev.EventName, format=ev.EventFormat, race_start=b["until"],
                        qual_start=next((t for n, t in sessions if n == "Qualifying"), None), closes=b["closes"],
                        sessions=[(SHORT.get(n, n), t) for n, t in sessions], stages=b["stages"])
    return out


def price_stages(meas, hist, sched, engine, engine_url=None, n_sims=4000, reprice=False, echo=print,
                 variant="baseline", settings=None):
    """Diagnostic run per (race, stage); a stored one is reused only when it was priced with the same
    model settings (model_key) from the same data (data_key), unless reprice.
    Returns {event_key: [(label, cutoff, run_id), ...]}."""
    from racinglines.models.position_sim import pricing as run
    from racinglines.pipelines import sweep_settings as SS
    st = settings or SS.Settings.from_dict({"variant": variant, "sims": n_sims})
    mk = st.model_key
    with engine.connect() as c:
        have = pd.read_sql(text("""SELECT id, params->>'event_key' AS k, params->>'cutoff' AS cutoff,
                                          params->>'data_key' AS d
                                   FROM model_runs WHERE kind = 'diagnostic' AND params ? 'sweep_stage'
                                     AND params->>'model_key' = :m ORDER BY id"""), c, params=dict(m=mk))
    have = {(k, str(pd.Timestamp(cu)), d): int(i) for i, k, cu, d in zip(have["id"], have["k"], have["cutoff"], have["d"])}
    out, data_keys = {}, []
    for rnd, w in sched.items():
        ev = meas.res[(meas.res["year"] == int(w["event_key"][:4])) & (meas.res["series_round"] == rnd)]
        if ev.empty or not (ev["round"] == "race").any():
            continue                                     # not raced yet
        runs = []
        for label, cutoff in w["stages"]:
            dk = SS.data_key(meas.view(cutoff))
            data_keys.append(dk)
            k = (w["event_key"], str(pd.Timestamp(cutoff)), dk)
            if k in have and not reprice:
                runs.append((label, cutoff, have[k]))
                continue
            _, summ, ex, _ = run.diagnostic(meas, hist, w["event_key"], cutoff, n_sims=st["sims"],
                                            use_track=st["track_features"], seed=st.rng_seed)
            extra = dict(model_key=mk, data_key=dk, model_settings={n: st.to_json()[n] for n in SS.MODEL_NAMES})
            if st["variant"] != "baseline":
                extra["variant"] = st["variant"]
            rid = run.save_diagnostic(engine_url, w["event_key"], cutoff, summ, ex, st["sims"], sweep_stage=label,
                                      **extra)
            runs.append((label, cutoff, rid))
        out[w["event_key"]] = runs
        echo(f"progress {len(out)}/{len(sched)} priced {w['event_key']} {w['name']}: "
             + ", ".join(f"{lab} #{rid}" for lab, _, rid in runs))
    price_stages.data_key = __import__("hashlib").sha1("|".join(data_keys).encode()).hexdigest()[:12]
    return out

def _token0_links(conn, race_id):
    links = pd.read_sql(text("""SELECT ml.*, a.display_name AS athlete FROM market_links ml
                                LEFT JOIN athletes a ON a.id = ml.athlete_id
                                WHERE ml.race_id = :r AND ml.prediction = ANY(:k) AND ml.exchange = 'polymarket'
                                ORDER BY ml.id"""), conn,
                        params=dict(r=race_id, k=list(KINDS)))
    return links.drop_duplicates("condition_id", keep="first")


def _links(conn, race_id, venue="polymarket"):
    """The race's tradeable links on a venue, one row per market: Polymarket's outcome-0 token per condition,
    or every Kalshi ticker (a Kalshi condition_id is the event ticker, shared by all its markets)."""
    if venue == "polymarket":
        return _token0_links(conn, race_id)
    from racinglines.markets.venue_replay import Kalshi
    if venue != Kalshi.code:
        raise ValueError(f"unknown venue {venue!r}")
    return Kalshi.links(conn, race_id, KINDS).drop_duplicates("token_id", keep="first")


def _venue(conn, links, start, end, venue="polymarket"):
    from racinglines.markets.venue_replay import Kalshi, Polymarket
    cls = Polymarket if venue == "polymarket" else Kalshi
    return cls(conn, links, start, end, GROUP_TARGET, COHERENCE_TOL, STALE)


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


def weekend_markets(conn, w, stage_runs, min_volume_24h=None, price_times=None, venue="polymarket"):
    """The weekend's tradeable markets for racinglines/markets/strategies/taker_weekend.py: per market, each stage's fair,
    exchange price and tradeable flag (what was knowable then) and the outcome (settlement). The exchange is a
    backtest venue (markets/venue_replay.py: Polymarket's recorded prices and trade tape, or Kalshi's with
    `venue="kalshi"`: one market per ticker, its own 24 h volume).
    price_times: {stage label: time} to read the market at instead of the stage's cutoff (live signals:
    when the stage was priced, i.e. when its trades could first be made); None = the cutoffs (backtests)."""
    at = lambda lab, cutoff: (price_times or {}).get(lab, cutoff)          # noqa: E731
    from racinglines.db import reads as D
    from racinglines.markets import private_book as house
    rid = _race_id(conn, w["event_key"])
    links = _links(conn, rid, venue)
    if not len(links):
        return None
    start, end = stage_runs[0][1] - timedelta(hours=1), max([w["race_start"], *(price_times or {}).values()])
    venue = _venue(conn, links, start, end, venue)
    res = house.race_outcomes(conn, rid)
    cache, markets = {}, []
    fair = {}   # (token, stage) -> fair
    for lab, cutoff, run_id in stage_runs:
        for link in links.to_dict("records"):
            fair[(link["token_id"], lab)] = D.model_prob(conn, link, cache, run_id=run_id)[0]
    # coherence of each multi-outcome group at each stage (stale/empty books are skipped)
    coherent = {(kind, lab): venue.coherent(kind, at(lab, cutoff)) for lab, cutoff, _ in stage_runs for kind in GROUP_TARGET}
    vol_min = MIN_VOLUME_24H if min_volume_24h is None else min_volume_24h
    for link in venue.markets():
        kind = link["prediction"]
        stages = []
        for lab, cutoff, _ in stage_runs:
            t = at(lab, cutoff)
            price, _, liquid = venue.view(link, t, vol_min)
            f = fair[(link["token_id"], lab)]
            open_ = STG.is_open(kind, t, w.get("closes", {"race_pole": w["qual_start"]}))
            ok = liquid and f is not None and open_ and coherent.get((kind, lab), True)
            stages.append(dict(label=lab, t=t, fair=f, price=price, tradeable=ok))
        subject = link["athlete"] or (link["params"] or {}).get("team") or link["group_title"]
        if kind == "race_h2h":
            subject = f"{link['outcome']} ({link['question'].split(': ')[-1]})"
        markets.append(dict(key=link["token_id"], kind=kind, subject=subject, stages=stages, link=link,
                            outcome=venue.resolve(link, res)))
    return markets


def weekend(conn, w, stage_runs, params_list, echo=print, widen_kinds=(), settings=None):
    """Trade one weekend. Returns dict(summary rows per mode, trades, stage scores, makers).
    widen_kinds: market kinds whose maker fills lost on 60-min markouts in EARLIER weekends.
    settings: sweep_settings.Settings (market kinds, volume filter, maker parameters); None = defaults."""
    from racinglines.pipelines import sweep_settings as SS
    st = settings or SS.Settings.from_dict()
    venue = SS.venue_of(st)
    markets = weekend_markets(conn, w, stage_runs, min_volume_24h=st["min_volume_24h"], venue=venue)
    if markets is None:
        return None
    markets = [m for m in markets if m["kind"] in st["market_kinds"]]
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
    # every tradeable (fair, price, outcome), for calibration (run_sweep's calibration tables)
    out["calib"] = [dict(stage=s["label"], kind=m["kind"], fair=s["fair"], price=s["price"], y=float(m["outcome"]))
                    for m in markets if m["outcome"] is not None
                    for s in m["stages"] if s["fair"] is not None and s["price"] is not None and s["tradeable"]]
    out["markets"] = len(markets)
    out["tradeable_first"] = sum(m["stages"][0]["tradeable"] for m in markets)
    out["tradeable_last"] = sum(m["stages"][-1]["tradeable"] for m in markets)
    # maker replays through the same stages (conservative fills), one per setting
    out["makers"], out["markout_by_kind"] = {}, {}
    try:
        from dataclasses import replace

        from racinglines.markets.strategies import maker_replay as R
        ev = R.load_event(conn, [r for _, _, r in stage_runs], books=st["fill"] == "queue",
                          **({} if venue == "polymarket" else dict(exchange=venue)))
        ev = dict(ev, markets=[m for m in ev["markets"] if m.kind in st["market_kinds"]])
    except Exception as ex:  # noqa: BLE001  (no tape for this weekend)
        echo(f"  maker replay skipped: {ex}")
        ev = None
    base = R.Params(half_spread=st["half_spread"], size=st["size"], max_pos=st["max_pos"], skew=st["skew"],
                    max_disagree=st["max_disagree"], fill=st["fill"], **maker_venue_opts(venue))
    for name, opts in MAKERS.items() if ev is not None else []:
        opts = dict(opts)
        p = base
        if "info_skew" in opts:
            opts["info_skew"] = st["info_skew"]
        if opts.pop("widen", False):
            opts["half_spread_by_kind"] = {k: p.half_spread * st["widen"] for k in widen_kinds}
        rep = R.replay(ev, replace(p, **opts))
        sk = R.summary(rep)
        s = sk.loc["total"]
        out["makers"][name] = dict(fills=int(s["fills"]), notional=float(s["notional"]), pnl=float(s["pnl"]),
                                   markout_60m=float(s["markout_60m"]), spread_pnl=float(s["spread_pnl"]))
        if name == "maker":
            out["markout_by_kind"] = sk.drop(index="total")["markout_60m"].to_dict()
    out["maker"] = out["makers"].get("maker")
    return out


def maker_venue_opts(venue):
    """maker_replay.Params overrides for a venue: Kalshi charges makers KALSHI_MAKER_FEE per fill; Polymarket nothing."""
    from racinglines.markets.strategies import maker_replay as R
    return {} if venue == "polymarket" else dict(maker_fee=R.KALSHI_MAKER_FEE)


def bankroll_scale(start, balance):
    """Stake multiplier for bankroll-aware sizing: the balance over the starting bankroll (0 once it's gone)."""
    return max(balance, 0.0) / start


def run_sweep(engine, engine_url, year, rounds=None, n_sims=4000, fetch=True, reprice=False, taker=None, echo=print,
              variant="baseline", settings=None):
    """The whole season (every raced weekend unless `rounds`). settings: sweep_settings.Settings, the
    full description of the combo (model, entry timing, taker, maker, markets); without it, one is
    built from n_sims / taker / variant. Returns dict(weekends DataFrame, by_stage, by_kind, totals,
    trades, scores, calibration, reliability, params). calibration / reliability: our fair values and the
    exchange's prices at every tradeable stage, scored on the outcome (core/calibration.py): per market kind
    and stage, and pooled per kind (stage "all"; a market counts once per stage it was tradeable)."""
    from racinglines.db.config import get_session

    from racinglines.models.position_sim import pricing as run
    from racinglines.pipelines import sweep_settings as SS
    if settings is None:
        t = taker or RB.TakerParams()
        settings = SS.Settings.from_dict(dict(variant=variant, sims=n_sims, min_edge=t.min_edge,
                                              stake_per_edge=t.stake_per_edge, max_stake=t.max_stake, cost=t.cost))
    st = settings
    sched = schedule(year, rounds)
    if fetch and SS.venue_of(st) != "polymarket":
        echo(f"progress {SS.venue_of(st)}: its tape is what the recorder and archive hold (nothing downloaded)")
    elif fetch:
        with engine.connect() as c, get_session(engine_url) as s:
            fetch_market_data(s, c, sched, echo=echo)
    echo(f"progress 0/1 building history ({st.label()})")
    meas = run.Measurements.load(engine)
    with st.applied():
        hist = run.history(meas, st["track_features"])
        stage_runs = price_stages(meas, hist, sched, engine, engine_url, reprice=reprice, echo=echo, settings=st)
    data_key = price_stages.data_key
    base = RB.TakerParams(min_edge=st["min_edge"], stake_per_edge=st["stake_per_edge"], max_stake=st["max_stake"],
                          cost=st["cost"], late_stages=st["late_stages"], min_edge_h2h=st["min_edge_h2h"],
                          min_edge_by_kind=tuple(SS.parse_map(st["min_edge_by_kind"]).items()),
                          stages=None if st["taker_stages"] == SS.STAGES else st["taker_stages"],
                          max_deployed=st["max_deployed"])
    params_list = [RB.TakerParams(**{**base.__dict__, "mode": m}) for m in TAKER_MODES]
    balance = {m: st["bankroll"] for m in TAKER_MODES}     # bankroll-aware sizing: each mode's balance
    rows, all_trades, all_scores, all_calib = [], [], [], []
    markouts = {}                      # market kind -> maker's 60-min markout so far (as of each weekend)
    for rnd, w in sched.items():
        runs = stage_runs.get(w["event_key"])
        if not runs:
            continue
        with engine.connect() as c:
            plist = params_list if st["bankroll"] is None else \
                [replace(q, scale=bankroll_scale(st["bankroll"], balance[q.mode])) for q in params_list]
            r = weekend(c, w, runs, plist, echo=echo, widen_kinds=[k for k, v in markouts.items() if v < 0],
                        settings=st)
        if r is None:
            continue
        if st["bankroll"] is not None:
            for q in plist:
                balance[q.mode] += r["modes"][q.mode]["pnl"]
                r["modes"][q.mode].update(scale=q.scale, balance=balance[q.mode])
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
        all_calib += [dict(c, event_key=w["event_key"]) for c in r["calib"]]
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
    calib = pd.DataFrame(all_calib, columns=["event_key", "stage", "kind", "fair", "price", "y"]).rename(
        columns=dict(fair="model", price="market"))
    cal_stage, _ = CAL.table(calib, ("model", "market"), by=("kind", "stage"))
    cal_all, rel = CAL.table(calib, ("model", "market"), by=("kind",))
    totals = {}
    for mode in (*TAKER_MODES, *MAKERS):
        col = f"{mode}_pnl"
        if col in weekends:
            spent = f"{mode}_notional" if mode.startswith("maker") else f"{mode}_bought"
            totals[mode] = dict(pnl=float(weekends[col].fillna(0).sum()),
                                weekends_up=int((weekends[col] > 0).sum()), weekends=int(weekends[col].notna().sum()),
                                bought=float(weekends.get(spent, pd.Series(dtype=float)).fillna(0).sum()))
    return dict(weekends=weekends, by_stage=by_stage, by_kind=RB.by(trades, "kind"), totals=totals, trades=trades,
                scores=score_stage, calibration=pd.concat([cal_all.assign(stage="all"), cal_stage], ignore_index=True),
                reliability=rel,
                params=dict({k: v for k, v in base.__dict__.items() if k != "stages" and not
                             (k in ("scale", "max_deployed", "min_edge_by_kind") and v == RB.TakerParams.__dataclass_fields__[k].default)},
                            n_sims=st["sims"],
                            variant=st["variant"], data_lag_min=DATA_LAG.seconds // 60,
                            min_volume_24h=st["min_volume_24h"], coherence_tol=COHERENCE_TOL,
                            settings=st.to_json(), settings_key=st.key, model_key=st.model_key, data_key=data_key,
                            label=st.label(), weekends=len(weekends)))
