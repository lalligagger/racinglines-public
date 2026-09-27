"""
Default season-long strategy for the championship markets (drivers' and constructors'
champion), replayed through the season on Polymarket's recorded prices.

Decisions: pre-season (PRESEASON_DAYS before the first practice), then one hour
after every race ends. At each, an as-of season forecast (position_sim.pricing.forecast with the
cutoff; only data from sessions that had ended) gives our fair values; the strategy
(racinglines/markets/strategies/season.py) rebalances and holds. Execution is at Polymarket's hourly price one
hour after the decision plus a per-market cost (half the recorded spread, 0.5c if
none recorded, plus 0.5c slippage). Markets with under MIN_VOLUME traded are skipped.

Demo liberty (documented): the pre-season forecast simulates the published 2026 entry
list (identities only) instead of the 2025 field.
"""

from datetime import timedelta

import pandas as pd
from sqlalchemy import text

from racinglines.markets.strategies import season as SS
from racinglines.core.stats import last_at
from racinglines.markets.strategies.sizing import target_shares

KINDS = ("champion", "constructors_champion")
MIN_VOLUME = 100_000
PRESEASON_DAYS = 5
DECISION_LAG = timedelta(hours=1)          # after the race has ended
DEFAULT_HALF_SPREAD, SLIPPAGE = 0.005, 0.005
HISTORY_START = pd.Timestamp("2025-12-09", tz="UTC")


def season_links(conn, year):
    return pd.read_sql(text("""
        SELECT ml.*, a.display_name AS athlete FROM market_links ml LEFT JOIN athletes a ON a.id = ml.athlete_id
        WHERE ml.race_id IS NULL AND ml.prediction = ANY(:k) AND coalesce(ml.volume, 0) >= :v
          AND ml.competition_id = (SELECT id FROM competitions WHERE code = 'f1_wdc')
          AND extract(year FROM ml.end_date) IN (:y, :y + 1)
        ORDER BY ml.prediction, ml.volume DESC"""), conn, params=dict(k=list(KINDS), v=MIN_VOLUME, y=year))


def fetch_history(session, conn, tokens, start=HISTORY_START, end=None, echo=print):
    """Hourly price history in 7-day windows (the API's limit); weeks already stored are skipped."""
    from racinglines.markets import store as MS

    from racinglines.markets.polymarket.sync import fetch_history as fh
    end = end or pd.Timestamp.now(tz="UTC")
    n, a = 0, start
    while a < end:
        b = min(a + timedelta(days=7), end)
        have = MS.read(conn, "prices", tokens=tokens, start=a, end=b)
        if have["token_id"].nunique() < max(1, int(0.8 * len(tokens))) or b > end - timedelta(days=8):
            n += fh(session, conn, None, a.to_pydatetime(), b.to_pydatetime(), fidelity=60, tokens=tokens)
        a = b
    echo(f"progress season history: {n} new price points")
    return n


def decision_times(meas, year):
    """[(label, t)] UTC: pre-season, then after each race that has run."""
    res = meas.res[meas.res["year"] == year]
    first = res["session_ts"].min()
    out = [("pre-season", (first - timedelta(days=PRESEASON_DAYS)).tz_localize("UTC"))]
    races = res[res["round"] == "race"].groupby("series_round")[["session_ts", "venue"]].first().sort_index()
    for rnd, r in races.iterrows():
        t = (r["session_ts"] + timedelta(minutes=150) + DECISION_LAG).tz_localize("UTC")
        out.append((f"after R{int(rnd):02d} {r['venue']}", t))
    return out


def asof_forecasts(engine, engine_url, meas, hist, year, times, n_sims=5000, reforecast=False, echo=print):
    """Championship forecast as of each decision (kind='season_asof'); stored ones are reused."""
    from racinglines.db.queries import records

    from racinglines.models.position_sim import pricing as run
    with engine.connect() as c:
        have = pd.read_sql(text("""SELECT id, params->>'cutoff' AS cutoff FROM model_runs WHERE kind = 'season_asof'
                                   AND (params->>'year')::int = :y ORDER BY id"""), c, params=dict(y=year))
    have = {str(pd.Timestamp(cu)): int(i) for i, cu in zip(have["id"], have["cutoff"])}
    first_event = meas.res[meas.res["year"] == year].sort_values("session_ts")["event_id"].iloc[0]
    schedule = run.upcoming_schedule(year)
    out = []
    for i, (label, t) in enumerate(times):
        cutoff = t.tz_convert("UTC").tz_localize(None)
        if str(cutoff) in have and not reforecast:
            out.append((label, t, have[str(cutoff)]))
            continue
        field = run.entry_list(meas, first_event) if i == 0 else None      # demo liberty: published entry list
        _, standings, ex = run.forecast(meas, hist, year, cutoff=cutoff, n_sims=n_sims, schedule=schedule, field=field,
                                        race_prices=False)
        rid = run.save_forecast(engine_url, year, [], standings,
                                dict(cutoff=str(cutoff), year=year, label=label, sims=n_sims, drift=ex["drift"]),
                                dict(constructors=records(ex["constructors"]), latest_data=ex["latest_data"]),
                                kind="season_asof")
        out.append((label, t, rid))
        echo(f"progress {i + 1}/{len(times)} season forecast {label}: run #{rid}")
    return out


def market_costs(conn, tokens):
    """$ per share per trade: half the median recorded spread (0.5c default) + slippage."""
    from racinglines.markets import store as MS
    bk = MS.read(conn, "books", tokens=tokens)
    half = {}
    if len(bk):
        bk = bk.dropna(subset=["best_bid", "best_ask"])
        half = ((bk["best_ask"] - bk["best_bid"]) / 2).groupby(bk["token_id"]).median().to_dict()
    return {t: max(half.get(t, DEFAULT_HALF_SPREAD), 0.0005) + SLIPPAGE for t in tokens}


def build_markets(conn, links):
    from racinglines.markets import store as MS
    toks = links["token_id"].tolist()
    px = MS.read(conn, "prices", tokens=toks)
    costs = market_costs(conn, toks)
    by = dict(tuple(px.groupby("token_id")))
    out = {}
    for link in links.to_dict("records"):
        g = by.get(link["token_id"])
        if g is None or not len(g):
            continue
        closed = bool(link["closed"]) and link["resolved_yes"] is not None and not pd.isna(link["resolved_yes"])
        subject = link["athlete"] or (link["params"] or {}).get("team") or link["group_title"]
        out[link["token_id"]] = SS.SeasonMarket(
            key=link["token_id"], kind=link["prediction"], subject=subject,
            ts=g["ts"].to_numpy(), px=g["price"].to_numpy(float), cost=costs[link["token_id"]],
            outcome=bool(link["resolved_yes"]) if closed else None, closed_at=g["ts"].iloc[-1] if closed else None)
    return out


def fairs(conn, links, run_id):
    from racinglines.db import reads as D
    cache = {}
    return {lk["token_id"]: D.model_prob(conn, lk, cache, run_id=run_id)[0] for lk in links.to_dict("records")}


def run_season(engine, engine_url, year=2026, params=SS.SeasonParams(), fetch=True, reforecast=False, n_sims=5000,
               echo=print):
    from racinglines.db.config import get_session
    from racinglines.db import reads as D

    from racinglines.models.position_sim import pricing as run
    with engine.connect() as c:
        links = season_links(c, year)
    echo(f"progress {len(links)} championship markets with >= ${MIN_VOLUME:,} traded")
    if fetch:
        with engine.connect() as c, get_session(engine_url) as s:
            fetch_history(s, c, links["token_id"].tolist(), echo=echo)
    echo("progress 0/1 building history")
    meas = run.Measurements.load(engine)
    hist = run.history(meas)
    times = decision_times(meas, year)
    runs = asof_forecasts(engine, engine_url, meas, hist, year, times, n_sims=n_sims, reforecast=reforecast, echo=echo)
    with engine.connect() as c:
        markets = build_markets(c, links)
        decisions = [dict(t=t, label=label, run_id=rid, fairs=fairs(c, links, rid)) for label, t, rid in runs]
        live_run, _ = D.latest_forecast_run(c, int(links["competition_id"].iloc[0])) if len(links) else (None, None)
        live_fair = fairs(c, links, live_run) if live_run else {}
    now = pd.Timestamp.now(tz="UTC")
    marks = pd.date_range(times[0][1].normalize(), now, freq="D")
    res = SS.replay(markets, decisions, params, now=now, marks=marks)
    hold = SS.replay(markets, decisions, SS.SeasonParams(**{**params.__dict__, "mode": "hold"}), now=now, marks=marks)
    # what the strategy would do right now (live forecast vs the latest price)
    pos = res["positions"].set_index("key") if len(res["positions"]) else pd.DataFrame()
    now_rows = []
    for k, mk in markets.items():
        if mk.outcome is not None:
            continue
        price = last_at(mk.ts, mk.px, now, timedelta(days=3))
        fair = live_fair.get(k)
        if price is None or fair is None:
            continue
        held_side = pos.loc[k, "side"] if k in pos.index and pos.loc[k, "status"] == "open" else None
        held = float(pos.loc[k, "shares"]) if held_side else 0.0
        ty, tn = target_shares(fair, price, mk.cost, params.min_edge, params.stake_per_edge, params.max_stake)
        if not params.price_band[0] <= price <= params.price_band[1]:      # outside the band: only reduce
            ty = min(ty, held if held_side == "YES" else 0.0)
            tn = min(tn, held if held_side == "NO" else 0.0)
        tgt_side, tgt = ("YES", ty) if ty else (("NO", tn) if tn else (None, 0.0))
        if tgt_side == held_side and abs(tgt - held) * (price if tgt_side == "YES" else 1 - price) < params.min_trade:
            action = "hold" if held else "no position"
        elif tgt_side is None:
            action = f"sell {held_side}" if held else "no position"
        elif tgt_side == held_side:
            action = f"{'add' if tgt > held else 'trim'} {tgt_side}"
        else:
            action = f"buy {tgt_side}" + (f" (close {held_side})" if held else "")
        now_rows.append(dict(key=k, kind=mk.kind, subject=mk.subject, price=price, fair=fair, edge=fair - price,
                             holding=f"{held:.0f} {held_side}" if held_side else "", target=f"{tgt:.0f} {tgt_side}" if tgt_side else "",
                             action=action, cost=mk.cost))
    now_df = pd.DataFrame(now_rows)
    if len(now_df):
        now_df = now_df.assign(a=now_df["edge"].abs()).sort_values(["kind", "a"], ascending=[False, False]).drop(columns="a")
    return dict(result=res, hold=hold, now=now_df, decisions=[dict(label=d["label"], t=d["t"], run_id=d["run_id"])
                                                               for d in decisions],
                params=params, live_run=live_run, markets=len(markets))
