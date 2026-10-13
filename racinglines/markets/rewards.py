"""
Venue liquidity rewards on our linked markets: what a maker is paid for resting quotes, recorded as it changes, so a
replay can add a rewards line to its P&L (docs/todo.md, "Liquidity rewards as a replay P&L line"). Read-only.

    Polymarket  GET clob.polymarket.com/rewards/markets/current   every market with a live reward: rewards_min_size
                (shares), rewards_max_spread (cents from the midpoint), rewards_config[].rate_per_day (USD a day)
    Kalshi      GET /trade-api/v2/incentive_programs?status=active|upcoming   one row per program and market:
                incentive_type (liquidity, volume, ...), period_reward and max_reward_per_account (centi-cents,
                Kalshi's OpenAPI), target_size_fp (contracts), discount_factor_bps, start_date / end_date

Gamma's rewardsMinSize / rewardsMaxSpread on a Polymarket market are only eligibility settings: a market can carry them
with no pool, so the CLOB list is what counts (checked 2026-10-13: 219 of 241 Austin markets set 50 / 4.5, one paid).

Only open links of the sport's competition are kept (exact keys: market_links.condition_id for Polymarket, the market
ticker market_links.token_id for Kalshi). A row is stored when a program appears, changes, or disappears (`active`
false), not every pass, so the files stay small:

    data/archive/markets/<exchange>/rewards/month=YYYY-MM/part-<utc>-<id>.parquet

The last state per program is kept in data/runs/rewards/<exchange>-<sport>.json to compare against. An empty response
from the venue (no program on any market) is never saved: it stores nothing and leaves that state as it was.
"""

import json
import uuid
from datetime import datetime, timezone

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text

from racinglines import paths, sports
from racinglines.sources import http

CLOB = "https://clob.polymarket.com"
KALSHI_STATUSES = ("active", "upcoming")
KALSHI_PAGE = 1000
# kind, min_size, max_spread, rate_per_day, period_reward, max_per_account, target_size, discount_bps, start, end:
# what decides "changed"; the raw program goes along as JSON
COLS = ["ts", "exchange", "market", "event", "program", "active", "kind", "min_size", "max_spread", "rate_per_day",
        "period_reward", "max_per_account", "target_size", "discount_bps", "start", "end", "raw"]
FIELDS = COLS[6:16]
FLOATS = ["min_size", "max_spread", "rate_per_day", "period_reward", "max_per_account", "target_size", "discount_bps"]


def _f(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def polymarket_programs(client=None):
    """Every Polymarket market with a live reward (CLOB /rewards/markets/current, paged): one row per reward config."""
    own = client is None
    client = client or httpx.Client(base_url=CLOB, timeout=30)
    rows, cursor = [], None
    try:
        while True:
            r = http.get(client, "/rewards/markets/current", params={"next_cursor": cursor} if cursor else None)
            r.raise_for_status()
            body = r.json()
            for m in body.get("data") or []:
                for i, cfg in enumerate(m.get("rewards_config") or [{}]):
                    rows.append(dict(market=m["condition_id"].lower(), program=f"{m['condition_id'].lower()}:{cfg.get('id', i)}",
                                     kind="liquidity", min_size=_f(m.get("rewards_min_size")),
                                     max_spread=_f(m.get("rewards_max_spread")), rate_per_day=_f(cfg.get("rate_per_day")),
                                     period_reward=_f(cfg.get("total_rewards")), max_per_account=None, target_size=None,
                                     discount_bps=None, start=cfg.get("start_date"), end=cfg.get("end_date"),
                                     raw=json.dumps(dict(m, rewards_config=[cfg]), sort_keys=True)))
            cursor = body.get("next_cursor")
            if not cursor or cursor == "LTE=" or not body.get("data"):
                return rows
    finally:
        if own:
            client.close()


def kalshi_programs(kc=None):
    """Kalshi's active and upcoming incentive programs (GET /incentive_programs): one row per program. Money in USD
    (Kalshi reports centi-cents)."""
    from racinglines.markets.kalshi.client import Client
    own = kc is None
    kc = kc or Client()
    rows = []
    try:
        for status in KALSHI_STATUSES:
            cursor = None
            while True:
                body = kc.get("/incentive_programs", status=status, limit=KALSHI_PAGE, cursor=cursor)
                for p in body.get("incentive_programs") or []:
                    cc = lambda k: None if p.get(k) is None else float(p[k]) / 10_000    # noqa: E731  centi-cents → USD
                    rows.append(dict(market=p["market_ticker"], program=p["id"], kind=p.get("incentive_type"),
                                     min_size=None, max_spread=None, rate_per_day=None, period_reward=cc("period_reward"),
                                     max_per_account=cc("max_reward_per_account"), target_size=_f(p.get("target_size_fp")),
                                     discount_bps=_f(p.get("discount_factor_bps")), start=p.get("start_date"),
                                     end=p.get("end_date"), raw=json.dumps(p, sort_keys=True)))
                cursor = body.get("next_cursor")
                if not cursor or not body.get("incentive_programs"):
                    break
    finally:
        if own:
            kc.close()
    return list({r["program"]: r for r in rows}.values())     # a program can be listed under both statuses


def linked_markets(conn, exchange, sport):
    """{market key: event key} for the open links of `sport`'s competition on `exchange`: Polymarket condition ids
    (lower case) to event slugs, Kalshi market tickers to event tickers."""
    key = "lower(ml.condition_id)" if exchange == "polymarket" else "ml.token_id"
    event = "ml.event_slug" if exchange == "polymarket" else "ml.condition_id"
    rows = conn.execute(text(f"""SELECT DISTINCT {key}, {event} FROM market_links ml
                                 JOIN competitions co ON co.id = ml.competition_id
                                 WHERE ml.exchange = :x AND NOT ml.closed AND co.code = :c AND {key} IS NOT NULL"""),
                        dict(x=exchange, c=sports.load(sport)["competition"]["code"])).all()
    return {k: e for k, e in rows}


def changes(programs, last, now):
    """Rows to store: programs new or changed since `last` ({program: {field: value}}), and an `active` false row for
    each program in `last` that is gone. Returns (rows, new last)."""
    rows, state = [], {}
    for p in programs:
        cur = {k: p[k] for k in FIELDS}
        state[p["program"]] = dict(cur, market=p["market"], event=p.get("event"))
        if last.get(p["program"], {}) != state[p["program"]]:
            rows.append(dict(p, ts=now, active=True))
    for prog, old in last.items():
        if prog not in state:
            rows.append(dict(old, ts=now, program=prog, active=False, raw=None))
    return rows, state


def _write(exchange, rows, root=None):
    if not rows:
        return 0
    df = pd.DataFrame(rows).reindex(columns=COLS)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    for c in FLOATS:
        df[c] = df[c].astype("float64")
    d = (root or paths.archive_markets(exchange)) / "rewards" / f"month={df['ts'].iloc[0]:%Y-%m}"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"part-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), f, compression="zstd")
    if pq.read_metadata(f).num_rows != len(df):
        raise IOError(f"verification failed for {f}")
    return len(df)


def record(conn, exchange, sport, root=None, state_dir=None, fetch=None, now=None):
    """One pass: the venue's reward programs on our open links of `sport`, stored where they changed. Returns a
    one-line summary for the recorder's log."""
    fetch = fetch or (polymarket_programs if exchange == "polymarket" else kalshi_programs)
    now = now or datetime.now(timezone.utc)
    everything = fetch()
    if not everything:      # an empty venue list is a bad response, not every program ending: store and forget nothing
        return "empty rewards response from the venue: nothing stored"
    links = linked_markets(conn, exchange, sport)
    progs = [dict(p, event=links[p["market"]]) for p in everything if p["market"] in links]
    sf = (state_dir or paths.runs("rewards")) / f"{exchange}-{sport}.json"
    last = json.loads(sf.read_text()) if sf.exists() else {}
    rows, state = changes(progs, last, now)
    n = _write(exchange, rows, root)
    sf.write_text(json.dumps(state, sort_keys=True, default=str))
    paid = sum(1 for p in progs if (p["rate_per_day"] or p["period_reward"] or 0) > 0)
    return (f"{len(progs)} reward programs on {len({p['market'] for p in progs})} of {len(links)} open markets "
            f"({paid} with a pool); {n} changes stored")


def read(exchange, root=None):
    """Every stored reward row of `exchange` (empty frame if none)."""
    d = (root or paths.archive_markets(exchange)) / "rewards"
    files = sorted(d.rglob("*.parquet")) if d.exists() else []
    if not files:
        return pd.DataFrame(columns=COLS)
    return pd.concat([pq.read_table(f).to_pandas() for f in files], ignore_index=True).sort_values("ts")
