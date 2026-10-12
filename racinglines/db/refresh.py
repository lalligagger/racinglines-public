"""
`vm.sh staging refresh`: production's race, market and model-run data copied into staging again, staging's own
state kept (docs/vm-deploy.md, "Staging: refresh").

Why: staging's database is a copy of production made once (deploy/vm/staging/setup.sh), and staging runs no
recorders, signals or pricing timers, so it falls behind from the minute it is copied. The only way to catch up
used to be `staging reset`, which drops the whole database, so staging's accounts, fantasy ledger, jobs and trading
tables went with it. A refresh replaces only the SHARED tables below and leaves everything else alone:

    SHARED (production's data)    race history, athletes, model runs and their predictions, market links, the
                                  market tape (prices, trades, books), live events, the data change log
    everything else (staging's)   users, activity, jobs, paper positions, signals, orders, the house book, the
                                  `accounts` schema (fantasy), alembic_version, and any table not listed in SHARED

Production is only read (a read-only session). Staging is written in one transaction, so the staging app sees the
old data until the new data is complete, and a failed refresh changes nothing.

Rows staging makes itself in a SHARED table (a Lab job's model run, a staging live run, a reference row a staging
deploy seeded before production had it) survive refreshes: the first refresh moves staging's id sequences for those
tables up to OFFSET, and a refresh keeps every row at or above it (and, in a table without an id, every row whose
parent is). A staging row that production now also has (the same unique key) becomes production's row, and staging's
references follow it. Rows staging made below OFFSET before its first refresh are replaced; `plan` counts them and
`vm.sh staging refresh` backs the database up first.

    python -m racinglines.db.refresh plan      # read-only: per table, production vs staging, what would be replaced
    python -m racinglines.db.refresh run       # the refresh

Run on the VM with staging's env file (DATABASE_URL = racinglines_staging, RACINGLINES_ENV=staging).
"""

import argparse
import os
import sys
import time

# Production's data, parents first. A table not listed here is staging's own and is never touched: the safe default
# for a new table. A new data table belongs here once production has it.
SHARED = (
    "sports", "leagues", "competitions", "categories", "seasons", "venues", "venue_aliases", "points_schemes",
    "events", "races", "rounds", "track_profiles", "athletes", "athlete_identifiers", "results", "splits", "laps",
    "source_files", "model_runs", "race_predictions", "standings_predictions", "market_links",
    "market_price_history", "market_trades", "market_book_snapshots", "market_disagreements", "live_events",
    "data_changes", "fastf1_session_snapshots", "fastf1_driver_positions",
)
OFFSET = 1_000_000_000      # staging's own rows in a SHARED table start here (int4 max is 2,147,483,647)
PROD_DB = "racinglines"
STAGING_DB = "racinglines_staging"
BEAT = 60                   # seconds between progress lines during a long copy


def log(msg):
    print(f"[refresh {time.strftime('%H:%M:%S', time.gmtime())}] {msg}", flush=True)


def urls(env=os.environ):
    """(production, staging) libpq URLs from staging's env file; refuses anything but staging's database."""
    url = env.get("DATABASE_URL", "")
    if env.get("RACINGLINES_ENV") != "staging" or not url.endswith("/" + STAGING_DB):
        raise SystemExit(f"refusing: run with staging's env file (DATABASE_URL .../{STAGING_DB}, RACINGLINES_ENV=staging)")
    staging = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return staging[: -len(STAGING_DB)] + PROD_DB, staging


def connect(url, read_only=False):
    import psycopg
    c = psycopg.connect(url, autocommit=True)
    if read_only:
        c.execute("SET default_transaction_read_only = on")
    return c


def q(c, query, args=None):
    return c.execute(query, args).fetchall()


def one(c, query, args=None):
    r = c.execute(query, args).fetchone()
    return r[0] if r else None


def ident(name):
    from psycopg import sql
    return sql.Identifier(name)


def tables(c):
    return {r[0] for r in q(c, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}


def columns(c, table):
    return [r[0] for r in q(c, "SELECT column_name FROM information_schema.columns "
                               "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position", (table,))]


def shared(prod, stg):
    """SHARED tables on both databases, and the ones left out with why."""
    p, s = tables(prod), tables(stg)
    ok = [t for t in SHARED if t in p and t in s]
    skipped = [(t, "not on production yet" if t not in p else "not on staging") for t in SHARED if t not in ok]
    return ok, skipped


def common(prod, stg, table):
    """Columns both sides have (staging may be a migration ahead: a new column takes its default)."""
    pc = set(columns(prod, table))
    return [c for c in columns(stg, table) if c in pc]


def parent_columns(stg, table):
    """Single-column foreign keys of a table that point at an `id` (the parent's id)."""
    return [r[0] for r in q(stg, "SELECT a.attname FROM pg_constraint c JOIN pg_class cl ON cl.oid = c.conrelid "
                                 "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
                                 "WHERE c.contype = 'f' AND cl.relname = %s AND array_length(c.conkey, 1) = 1", (table,))]


def own(stg, table):
    """SQL condition for staging's own rows in a SHARED table: id >= OFFSET, or (no id) a parent id >= OFFSET."""
    from psycopg import sql
    cols = ["id"] if "id" in columns(stg, table) else parent_columns(stg, table)
    if not cols:
        return sql.SQL("false")
    return sql.SQL(" OR ").join(sql.SQL("{} >= {}").format(ident(c), sql.Literal(OFFSET)) for c in cols)


def sequences(stg, table):
    """The sequences behind a table's serial or identity columns."""
    return [r[0] for r in q(stg, "SELECT pg_get_serial_sequence(quote_ident(%s), a.attname) FROM pg_attribute a "
                                 "JOIN pg_class t ON t.oid = a.attrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
                                 "WHERE n.nspname = 'public' AND t.relname = %s AND a.attnum > 0 AND NOT a.attisdropped",
                                 (table, table)) if r[0]]


def lift_sequences(stg, names):
    """Staging's own rows in a SHARED table take ids from OFFSET up (idempotent; never lowers a sequence)."""
    for t in names:
        for seq in sequences(stg, t):
            if one(stg, f"SELECT last_value FROM {seq}") < OFFSET:
                stg.execute("SELECT setval(%s, %s, false)", (seq, OFFSET))
                log(f"{seq}: staging's own ids start at {OFFSET:,} from now on")


def unique_keys(stg, table):
    """Column lists of a table's unique constraints and unique indexes, the primary key excepted."""
    rows = q(stg, "SELECT array_agg(a.attname ORDER BY k.ord) FROM pg_index i "
                  "JOIN pg_class t ON t.oid = i.indrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
                  "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord) "
                  "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum "
                  "WHERE n.nspname = 'public' AND t.relname = %s AND i.indisunique AND NOT i.indisprimary "
                  "AND i.indpred IS NULL GROUP BY i.indexrelid", (table,))
    return [list(r[0]) for r in rows]


def references(stg, table):
    """(table, column) pairs whose single-column foreign key points at table.id."""
    return q(stg, "SELECT cl.relname, a.attname FROM pg_constraint c JOIN pg_class cl ON cl.oid = c.conrelid "
                  "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
                  "JOIN pg_class rt ON rt.oid = c.confrelid "
                  "WHERE c.contype = 'f' AND rt.relname = %s AND array_length(c.conkey, 1) = 1", (table,))


def adopt(prod, stg, names):
    """Each staging-own row (id >= OFFSET) whose unique key production also has (say staging seeded a competition
    before production did) becomes production's row: staging's references move to production's id and staging's row
    goes. Call inside the refresh's transaction, with foreign-key triggers off. Returns the number of rows moved."""
    from psycopg import sql
    moved = 0
    for t in names:
        if "id" not in columns(stg, t):
            continue
        for key in unique_keys(stg, t):
            cols = sql.SQL(", ").join(ident(k) for k in key)
            where = sql.SQL(" AND ").join(sql.SQL("{} = %s").format(ident(k)) for k in key)
            for sid, *vals in q(stg, sql.SQL("SELECT id, {} FROM {} WHERE id >= %s").format(cols, ident(t)), (OFFSET,)):
                if any(v is None for v in vals):
                    continue
                pid = one(prod, sql.SQL("SELECT id FROM {} WHERE {}").format(ident(t), where), vals)
                if pid is None:
                    continue
                for rt, rc in references(stg, t):
                    stg.execute(sql.SQL("UPDATE {} SET {} = %s WHERE {} = %s").format(ident(rt), ident(rc), ident(rc)),
                                (pid, sid))
                stg.execute(sql.SQL("DELETE FROM {} WHERE id = %s").format(ident(t)), (sid,))
                log(f"{t}: staging's row {sid} {dict(zip(key, vals))} is production's {pid} now (references moved)")
                moved += 1
    return moved


def copy(prod, stg, table, cols):
    """Stream production's rows into staging (COPY out, COPY in). Returns the row count."""
    from psycopg import sql
    cl = sql.SQL(", ").join(ident(c) for c in cols)
    t0 = last = time.monotonic()
    size = 0
    with prod.cursor().copy(sql.SQL("COPY (SELECT {} FROM {}) TO STDOUT").format(cl, ident(table))) as src, \
            stg.cursor().copy(sql.SQL("COPY {} ({}) FROM STDIN").format(ident(table), cl)) as dst:
        for chunk in src:
            dst.write(chunk)
            size += len(chunk)
            if time.monotonic() - last >= BEAT:
                last = time.monotonic()
                log(f"{table}: {size / 2**20:,.0f} MB copied, {(last - t0) / 60:.1f} min elapsed")
    return one(stg, sql.SQL("SELECT count(*) FROM {} WHERE NOT ({})").format(ident(table), own(stg, table)))


def plan(prod, stg):
    """Read-only: per SHARED table, production's rows, staging's, and how many of staging's rows a refresh replaces
    that production doesn't have as-is (an id production lacks, or the same id with other content)."""
    ok, skipped = shared(prod, stg)
    print(f"{'table':26} {'production':>12} {'staging':>12} {'replaced*':>10} {'staging-own':>12}")
    for t in ok:
        np_, ns = one(prod, f"SELECT count(*) FROM {t}"), one(stg, f"SELECT count(*) FROM {t}")
        mine = one(stg, f"SELECT count(*) FROM {t} WHERE " + own(stg, t).as_string(stg))
        cols = common(prod, stg, t)
        diff = ""
        if "id" in cols and max(np_, ns) < 2_000_000:
            row = "md5(ROW(" + ", ".join(f'"{c}"' for c in cols) + ")::text)"
            pid = dict(q(prod, f"SELECT id, {row} FROM {t}"))
            diff = sum(1 for i, h in q(stg, f"SELECT id, {row} FROM {t} WHERE id < {OFFSET}") if pid.get(i) != h)
        print(f"{t:26} {np_:>12,} {ns:>12,} {diff!s:>10} {mine:>12,}")
    for t, why in skipped:
        print(f"{t:26} skipped: {why}")
    print("* staging rows below the staging-own range that production doesn't have as-is (kept in the backup);"
          " blank for tables over 2M rows")


def run(prod, stg):
    from psycopg import sql
    ok, skipped = shared(prod, stg)
    for t, why in skipped:
        log(f"{t}: skipped ({why})")
    t0 = time.monotonic()
    with stg.transaction():
        stg.execute("SET LOCAL session_replication_role = replica")   # staging's own rows keep their references
        lift_sequences(stg, ok)
        moved = adopt(prod, stg, ok)
        for t in reversed(ok):     # children first
            n = stg.execute(sql.SQL("DELETE FROM {} WHERE NOT ({})").format(ident(t), own(stg, t))).rowcount
            if n:
                log(f"{t}: {n:,} old rows out")
        with prod.transaction():   # one snapshot of production for every table
            prod.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            for t in ok:
                n = copy(prod, stg, t, common(prod, stg, t))
                log(f"{t}: {n:,} rows from production")
    for t in ok:   # the deleted rows' space is reused by the next refresh, so staging's size stays put
        stg.execute(sql.SQL("VACUUM ANALYZE {}").format(ident(t)))
    log(f"done in {(time.monotonic() - t0) / 60:.1f} min: {len(ok)} tables from production"
        + (f", {moved} staging rows matched to production's" if moved else "")
        + "; staging's accounts, jobs, positions and other tables untouched")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m racinglines.db.refresh", description=__doc__.strip().split("\n\n")[0])
    ap.add_argument("command", choices=("plan", "run"))
    a = ap.parse_args(argv)
    prod_url, stg_url = urls()
    prod, stg = connect(prod_url, read_only=True), connect(stg_url)
    (plan if a.command == "plan" else run)(prod, stg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
