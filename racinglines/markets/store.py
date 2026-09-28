"""
Exchange market data store: Parquet for history, Postgres as a small buffer.

High-volume exchange data (minute prices, trades, order-book snapshots) is written
to Postgres by the sync/recorder (idempotent upserts), then `archive()` moves rows
older than a few hours into Parquet and deletes them from Postgres:

    data/archive/markets/<exchange>/<name>/month=YYYY-MM/part-<utc>-<id>.parquet     (zstd)

Each row goes to its market's exchange (market_links.exchange; a token without a link counts as Polymarket),
and readers without an explicit `root` read every exchange's tree. Token ids don't collide across exchanges.

    name      Postgres table            key
    prices    market_price_history     token_id, ts
    trades    market_trades            tx_hash, token_id, wallet, side, price, size
    books     market_book_snapshots    token_id, ts      (bids/asks as JSON text)

Every reader goes through `read()` / `last_before()`, which merge both and drop
duplicates, so callers never care where a row lives. Metadata (market_links),
results and model runs stay in Postgres.

Retention (`hot_tokens`, used by `archive(..., policy=True)`): Postgres keeps the
market data the app presents live, i.e. every upcoming / in-progress race, the
most recent completed race of each competition, and the last RECENT_DAYS of
still-open season-long markets. Everything else is stale and moves to Parquet.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from sqlalchemy import text

from racinglines import paths  # noqa: E402

ROOT = paths.archive_markets("polymarket")


def root_for(exchange):
    """One exchange's Parquet tree (data/archive/markets/<exchange>), for readers that want only that venue."""
    return ROOT if exchange in (None, "polymarket") else paths.archive_markets(exchange)
RECENT_DAYS = 7

STORES = {
    "prices": dict(table="market_price_history", key=["token_id", "ts"], cols=["token_id", "ts", "price"]),
    "trades": dict(table="market_trades", key=["tx_hash", "token_id", "wallet", "side", "price", "size"],
                   cols=["token_id", "condition_id", "outcome_index", "ts", "side", "price", "size", "tx_hash", "wallet"]),
    "books": dict(table="market_book_snapshots", key=["token_id", "ts"],
                  cols=["token_id", "ts", "best_bid", "best_ask", "bids", "asks"]),
}


def _utc(t):
    if t is None:
        return None
    t = pd.Timestamp(t)
    return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).to_pydatetime()


def _roots(root=None):
    """The Parquet trees to read: `root`, else every exchange's (archive/markets/<exchange>/)."""
    if root is not None:
        return [root]
    base = paths.archive_markets().parent
    return sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []


def _dataset(name, root):
    path = root / name
    if not path.exists() or not any(path.rglob("*.parquet")):
        return None
    return ds.dataset(path, format="parquet", partitioning="hive")


def _read_parquet(name, tokens, conditions, start, end, root=None):
    parts = [x for x in (_read_tree(name, tokens, conditions, start, end, r) for r in _roots(root)) if len(x)]
    if not parts:
        return pd.DataFrame(columns=STORES[name]["cols"])
    return parts[0] if len(parts) == 1 else pd.concat(parts, ignore_index=True)


def _read_tree(name, tokens, conditions, start, end, root):
    d = _dataset(name, root)
    if d is None:
        return pd.DataFrame(columns=STORES[name]["cols"])
    f = None
    if tokens is not None:
        f = ds.field("token_id").isin(list(tokens))
    if conditions is not None:
        g = ds.field("condition_id").isin(list(conditions))
        f = g if f is None else f & g
    if start is not None:
        g = ds.field("ts") >= pa.scalar(_utc(start), type=pa.timestamp("us", tz="UTC"))
        f = g if f is None else f & g
    if end is not None:
        g = ds.field("ts") <= pa.scalar(_utc(end), type=pa.timestamp("us", tz="UTC"))
        f = g if f is None else f & g
    t = d.to_table(filter=f, columns=STORES[name]["cols"])
    return t.to_pandas()


def _read_pg(conn, name, tokens, conditions, start, end):
    s = STORES[name]
    where, params = ["TRUE"], {}
    if tokens is not None:
        where.append("token_id = ANY(:tok)")
        params["tok"] = list(tokens)
    if conditions is not None:
        where.append("condition_id = ANY(:cond)")
        params["cond"] = list(conditions)
    if start is not None:
        where.append("ts >= :a")
        params["a"] = _utc(start)
    if end is not None:
        where.append("ts <= :b")
        params["b"] = _utc(end)
    df = pd.read_sql(text(f"SELECT {', '.join(s['cols'])} FROM {s['table']} WHERE {' AND '.join(where)}"), conn,
                     params=params)
    if name == "books":
        for c in ("bids", "asks"):
            df[c] = df[c].map(lambda v: v if v is None or isinstance(v, str) else json.dumps(v))
    return df


def merge(a, b, name):
    parts = [x for x in (a, b) if x is not None and len(x)]
    if not parts:
        return pd.DataFrame(columns=STORES[name]["cols"])
    df = pd.concat(parts, ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.drop_duplicates(STORES[name]["key"]).sort_values("ts").reset_index(drop=True)


def read(conn, name, *, tokens=None, conditions=None, start=None, end=None, root=None):
    """Rows of store `name` (prices / trades / books), from Parquet and Postgres, ts UTC-aware, sorted."""
    if (tokens is not None and not len(tokens)) or (conditions is not None and not len(conditions)):
        return pd.DataFrame(columns=STORES[name]["cols"])
    pg = _read_pg(conn, name, tokens, conditions, start, end) if conn is not None else None
    return merge(_read_parquet(name, tokens, conditions, start, end, root), pg, name)


def last_before(conn, tokens, t, lookback=timedelta(days=30), root=None):
    """{token: last price at or before t} (prices store). Postgres side uses the (token_id, ts)
    index; the Parquet side reads only the lookback window."""
    tokens = list(tokens)
    if not tokens:
        return {}
    t = _utc(t)
    parts = [_read_parquet("prices", tokens, None, t - lookback, t, root)]
    if conn is not None:
        parts.append(pd.read_sql(text("""
            SELECT DISTINCT ON (token_id) token_id, ts, price FROM market_price_history
            WHERE token_id = ANY(:tok) AND ts <= :t AND ts >= :a ORDER BY token_id, ts DESC"""), conn,
            params=dict(tok=tokens, t=t, a=t - lookback)))
    df = pd.concat([x for x in parts if len(x)], ignore_index=True) if any(len(x) for x in parts) else None
    if df is None:
        return {}
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").groupby("token_id")["price"].last().to_dict()


def _write(name, df, root=None):
    """Append rows to Parquet, one file per month."""
    if not len(df):
        return 0
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    n = 0
    for month, g in df.groupby(df["ts"].dt.strftime("%Y-%m")):
        d = (root or ROOT) / name / f"month={month}"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"part-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.parquet"
        tbl = pa.Table.from_pandas(g[STORES[name]["cols"]], preserve_index=False)
        tbl = tbl.cast(pa.schema([pa.field(c, pa.timestamp("us", tz="UTC")) if c == "ts" else tbl.schema.field(c)
                                  for c in tbl.column_names]))
        pq.write_table(tbl, f, compression="zstd")
        if pq.read_metadata(f).num_rows != len(g):
            raise IOError(f"verification failed for {f}")
        n += len(g)
    return n


def hot_tokens(conn):
    """(keep_all, keep_recent): tokens whose market data stays in Postgres entirely (upcoming /
    in-progress races and the latest completed race per competition), and open season-long
    tokens whose last RECENT_DAYS stay."""
    keep_all = conn.execute(text("""
        WITH latest AS (
            SELECT DISTINCT ON (s.competition_id) ra.id AS race_id
            FROM races ra JOIN events e ON e.id = ra.event_id JOIN seasons s ON s.id = e.season_id
            WHERE e.status = 'completed' ORDER BY s.competition_id, e.start_date DESC)
        SELECT ml.token_id FROM market_links ml JOIN races ra ON ra.id = ml.race_id JOIN events e ON e.id = ra.event_id
        WHERE e.status <> 'completed' OR ml.race_id IN (SELECT race_id FROM latest)""")).scalars().all()
    keep_recent = conn.execute(text("SELECT token_id FROM market_links WHERE race_id IS NULL AND NOT closed")).scalars().all()
    return list(keep_all), list(keep_recent)


def _exchanges(conn, tokens):
    """{token: exchange} from market_links."""
    return dict(conn.execute(text("SELECT token_id, exchange FROM market_links WHERE token_id = ANY(:t)"),
                             dict(t=list(tokens))).all())


def archive(engine, name, older_than=timedelta(hours=6), tokens=None, root=None, chunk_days=31, policy=False):
    """Move rows from Postgres to Parquet (delete ... returning, written and verified before the
    transaction commits). By default: rows older than `older_than`. With policy=True: every row
    that isn't hot (see hot_tokens), whatever its age. `tokens` limits it (tests). Rows go to their
    exchange's tree, or all to `root` when given. Returns rows moved."""
    s = STORES[name]
    now = datetime.now(timezone.utc)
    keep_all, keep_recent = [], []
    if policy:
        with engine.connect() as c:
            keep_all, keep_recent = hot_tokens(c)
        cutoff, recent_cut = now + timedelta(days=1), now - timedelta(days=RECENT_DAYS)
    else:
        cutoff, recent_cut = now - older_than, now
    cond = ("NOT (token_id = ANY(:ka)) AND NOT (token_id = ANY(:kr) AND ts >= :rc)"
            + (" AND token_id = ANY(:t)" if tokens else ""))
    params = dict(ka=keep_all, kr=keep_recent, rc=recent_cut, t=list(tokens or []))
    moved = 0
    with engine.connect() as c:
        lo = c.execute(text(f"SELECT min(ts) FROM {s['table']} WHERE ts < :c AND {cond}"), dict(params, c=cutoff)).scalar()
    if lo is None:
        return 0
    a = lo
    while a < cutoff:
        b = min(a + timedelta(days=chunk_days), cutoff)
        with engine.begin() as c:        # rolls back (keeps the rows) if writing fails
            rows = c.execute(text(f"""DELETE FROM {s['table']} WHERE ts >= :a AND ts < :b AND {cond}
                                      RETURNING {', '.join(s['cols'])}"""), dict(params, a=a, b=b)).mappings().all()
            df = pd.DataFrame(rows, columns=s["cols"])
            if name == "books":
                for col in ("bids", "asks"):
                    df[col] = df[col].map(lambda v: v if v is None or isinstance(v, str) else json.dumps(v))
            if root is not None or not len(df):
                moved += _write(name, df, root)
            else:
                ex = df["token_id"].map(_exchanges(c, df["token_id"].unique())).fillna("polymarket")
                for x, g in df.groupby(ex):
                    moved += _write(name, g, paths.archive_markets(x))
        a = b
    return moved


def stats(engine, root=None):
    out = {}
    with engine.connect() as c:
        for name, s in STORES.items():
            n_pg = c.execute(text(f"SELECT count(*) FROM {s['table']}")).scalar()
            size_pg = c.execute(text("SELECT pg_total_relation_size(:t)"), dict(t=s["table"])).scalar()
            files = [f for r in _roots(root) for f in (r / name).rglob("*.parquet")]
            n_pq = sum(pq.read_metadata(f).num_rows for f in files)
            out[name] = dict(postgres_rows=n_pg, postgres_mb=size_pg / 1e6, parquet_rows=n_pq,
                             parquet_mb=sum(f.stat().st_size for f in files) / 1e6, parquet_files=len(files))
    return out


def compact(name, root=None):
    """Rewrite each month as one deduplicated file (in `root`, else in every exchange's tree)."""
    for r in _roots(root):
        for d in sorted((r / name).glob("month=*")):
            files = sorted(d.glob("*.parquet"))
            if len(files) < 2:
                continue
            df = pd.concat([pq.read_table(f).to_pandas() for f in files], ignore_index=True)
            df = df.drop_duplicates(STORES[name]["key"]).sort_values("ts")
            _write(name, df, r)
            for f in files:
                f.unlink()
