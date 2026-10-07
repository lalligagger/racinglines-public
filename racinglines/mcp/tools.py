"""
The MCP tools as plain functions: `(conn, ...) -> dict`, where `conn` is a SQLAlchemy connection (a read-only
transaction; see server.py). Every list goes through page.page (row and byte caps); everything reuses the
functions the web app reads from: db/reads.py, markets/venues.py, markets/store.py, web/edge.py, web/diag.py,
pipelines/story.py, web/jobs.py. Nothing here writes to the database except the job tools (queue, cancel), which
do what the Lab's Run form does.
"""

import json
import re
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import text

from racinglines.db import reads as data
from racinglines.mcp import page as P

SPORT_OF = {"f1_wdc": "f1", "uci_dhi_wc": "mtb_dh"}
COMPETITION_OF = {v: k for k, v in SPORT_OF.items()}
RUN_KINDS = ("forecast", "scenario", "diagnostic", "backtest", "sweep", "season_strategy", "season_checkpoints",
             "season_asof", "walk_forward", "candidate")
# tables the sql tool never reads (login secrets; exchange credentials and responses)
SQL_HIDDEN = ("users", "orders")
SQL_TIMEOUT = "10s"

# one line per table, for describe_schema (docs/database.md has the long version)
TABLES = {
    "sports": "reference: what is raced (f1, mtb_dh)", "leagues": "reference: who organizes it",
    "competitions": "a league's championship in one sport (f1_wdc, uci_dhi_wc)", "categories": "per competition (DRV, ME, MJ, ...)",
    "seasons": "competition x year", "events": "a race weekend / round: source_key, start_date, venue, status",
    "venues": "circuits and resorts", "venue_aliases": "spellings of a venue in source data",
    "races": "event x category, with the weekend format (JSONB)", "rounds": "practice / qual / final / race ... of a race",
    "results": "one row per athlete per round: position, status, time_ms", "splits": "intermediate times of a result",
    "laps": "F1 laps: lap and sector ms, tyre, stint, position", "track_profiles": "per-event track features the F1 model uses",
    "athletes": "drivers and riders (shared across sports)", "athlete_identifiers": "(scheme, value) ids of an athlete",
    "source_files": "every ingested file with its hash", "points_schemes": "championship points tables",
    "model_runs": "one row per model run: kind (forecast, scenario, diagnostic, backtest, sweep, ...), params, metrics (JSONB)",
    "race_predictions": "per-athlete probabilities of a run for a race (win, podium, top10, make_final, exp_points)",
    "standings_predictions": "per-athlete projected standings of a run",
    "market_links": "an exchange token (Polymarket) or market (Kalshi) linked to a prediction kind, athlete, race; last price, volume, resolution",
    "market_price_history": "recent exchange prices (older rows are in the Parquet archive; use get_market_history)",
    "market_trades": "recent exchange trades (same)", "market_book_snapshots": "recent order books (same)",
    "house_markets": "YES/NO markets quoted in the app (the private book)", "house_bets": "bets against house markets",
    "users": "web-app accounts (hidden from sql)", "activity_log": "web-app audit trail", "jobs": "Lab jobs (CLI subprocesses)",
    "strategy_signals": "paper signals of a user's strategy profile", "paper_positions": "paper positions per user, market, venue",
    "live_events": "settled live private-book events", "data_changes": "the data change log", "orders": "exchange orders (hidden from sql)",
}


def _sport_filter(sport=None, competition=None):
    if competition:
        return competition
    if sport:
        return COMPETITION_OF.get(sport, sport)
    return None


def _usernames(conn):
    return {r[0]: int(r[1]) for r in conn.execute(text("SELECT username, id FROM users")).fetchall()}


def _user_id(conn, user):
    ids = _usernames(conn)
    if user is None:
        raise ValueError(f"which user? one of: {', '.join(sorted(ids))}")
    if user not in ids:
        raise ValueError(f"no user {user!r}; users: {', '.join(sorted(ids))}")
    return ids[user]


# ---------------------------------------------------------------------------------------------------
# orientation
# ---------------------------------------------------------------------------------------------------

def overview(conn):
    """What the database holds, so a client knows what to ask for."""
    from racinglines.markets import venues as V
    seasons = data.q(conn, """
        SELECT co.code AS competition, s.year AS season, count(e.id) AS events,
               count(e.id) FILTER (WHERE e.status = 'completed') AS completed, min(e.start_date) AS first, max(e.start_date) AS last
        FROM seasons s JOIN competitions co ON co.id = s.competition_id LEFT JOIN events e ON e.season_id = s.id
        GROUP BY 1, 2 HAVING count(e.id) > 0 ORDER BY 1, 2""")
    runs = data.q(conn, "SELECT kind, count(*) AS runs, max(created_at) AS latest FROM model_runs GROUP BY kind ORDER BY kind")
    links = data.q(conn, """SELECT exchange, count(*) AS links, count(*) FILTER (WHERE NOT closed) AS open,
                            count(DISTINCT race_id) AS races FROM market_links GROUP BY exchange ORDER BY exchange""")
    users = data.q(conn, "SELECT username, role, prefs->'strategy_profile'->>'name' AS profile FROM users WHERE active ORDER BY id")
    counts = {t: int(conn.execute(text(f"SELECT count(*) FROM {t}")).scalar())
              for t in ("events", "results", "athletes", "market_links", "model_runs", "paper_positions", "strategy_signals", "jobs")}
    upcoming = data.q(conn, """SELECT e.id AS event_id, co.code AS competition, e.name, e.start_date FROM events e
                               JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
                               WHERE e.status <> 'completed' AND e.start_date >= current_date - 7 ORDER BY e.start_date LIMIT 6""")
    return dict(
        sports={c: s for c, s in SPORT_OF.items()},
        seasons=[P.record(r) for r in seasons.to_dict("records")],
        forecasts=[P.record(r) for r in data.latest_forecasts(conn).to_dict("records")],
        model_runs=[P.record(r) for r in runs.to_dict("records")],
        market_links=[P.record(r) for r in links.to_dict("records")],
        venues=[dict(code=v.code, name=v.name, status=v.status, kind=v.kind) for v in V.VENUES],
        users=[P.record(r) for r in users.to_dict("records")],
        upcoming=[P.record(r) for r in upcoming.to_dict("records")],
        row_counts=counts,
        hint="Start with list_events / list_markets / get_forecast; use sql for anything else (read-only); "
             "run_job for a simulation and get_job to follow it.",
    )


def describe_schema(conn, table=None):
    """The tables with one-line meanings, or one table's columns."""
    if table is None:
        return dict(tables=[dict(table=t, what=w) for t, w in TABLES.items()])
    if not re.fullmatch(r"[a-z_]+", table):
        raise ValueError("table names are lower-case words")
    cols = data.q(conn, """SELECT column_name AS name, data_type AS type, is_nullable = 'YES' AS nullable, column_default AS "default"
                           FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position""", t=table)
    if not len(cols):
        raise ValueError(f"no table {table!r}")
    n = int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()) if table not in SQL_HIDDEN else None
    return dict(table=table, what=TABLES.get(table, ""), rows=n, columns=[P.record(r) for r in cols.to_dict("records")])


# ---------------------------------------------------------------------------------------------------
# events, athletes
# ---------------------------------------------------------------------------------------------------

def list_events(conn, sport=None, competition=None, season=None, status=None, limit=None, offset=0):
    df = data.events(conn, competition=_sport_filter(sport, competition), season=season)
    if status:
        df = df[df["status"] == status]
    return P.page(df, limit=limit, offset=offset)


def get_event(conn, event_id=None, source_key=None, include="results"):
    """One event: its summary, and with include= any of results, predictions, markets (comma-separated)."""
    if event_id is None and source_key:
        row = data.q(conn, "SELECT id FROM events WHERE source_key = :k ORDER BY id DESC LIMIT 1", k=source_key)
        if not len(row):
            raise ValueError(f"no event with source_key {source_key!r}")
        event_id = int(row["id"].iloc[0])
    ev = data.event(conn, int(event_id))
    if not ev:
        raise ValueError(f"no event {event_id}")
    wants = {w.strip() for w in (include or "").split(",") if w.strip()}
    races = data.q(conn, """SELECT ra.id AS race_id, c.code AS category, ra.format FROM races ra
                            JOIN categories c ON c.id = ra.category_id WHERE ra.event_id = :e ORDER BY c.code""", e=event_id)
    out = dict(event=P.record(ev), races=[P.record(r) for r in races.to_dict("records")])
    if "results" in wants:
        res = data.event_results(conn, event_id)
        finals = res[res["round"].isin(("final", "race"))] if len(res) else res
        out["results"] = P.page(finals if len(finals) else res, limit=60, note="final/race rounds only; sql for every round")
        if len(res):
            out["rounds"] = {str(k): int(v) for k, v in res.groupby("round").size().items()}
    if "predictions" in wants:
        pr = data.event_predictions(conn, event_id)
        out["predictions"] = P.page(pr, limit=60, note="newest run first")
    if "markets" in wants:
        out["markets"] = {int(r): list_markets(conn, race_id=int(r), limit=40) for r in races["race_id"]}
    return out


def search_athletes(conn, q=None, limit=None):
    return P.page(data.athletes(conn, q, limit=P.MAX_LIMIT), limit=limit)


def get_athlete(conn, athlete_id, include="results"):
    a = data.athlete(conn, int(athlete_id))
    if not a:
        raise ValueError(f"no athlete {athlete_id}")
    wants = {w.strip() for w in (include or "").split(",") if w.strip()}
    out = dict(athlete=P.record(a))
    if "results" in wants:
        out["results"] = P.page(data.athlete_results(conn, athlete_id), limit=60)
    if "predictions" in wants:
        out["predictions"] = P.page(data.athlete_predictions(conn, athlete_id), limit=60)
    return out


# ---------------------------------------------------------------------------------------------------
# markets: the venues matrix and the exchange time series
# ---------------------------------------------------------------------------------------------------

def _matrix_rows(df):
    rows = []
    for r in df.to_dict("records"):
        row = dict(kind=r["kind"], subject=r["subject"], detail=r["detail"], athlete_id=data._id(r["athlete_id"]), team=r["team"],
                   opponent_id=data._id(r["opponent_id"]), fair=r["fair"], result=r.get("result"))
        for venue, q in (r.get("venues") or {}).items():
            row[f"{venue}_mid"] = q.get("mid")
            row[f"{venue}_bid"], row[f"{venue}_ask"] = q.get("bid"), q.get("ask")
            row[f"{venue}_volume"] = q.get("volume")
            row[f"{venue}_token"] = q.get("token")
            row[f"{venue}_closed"] = q.get("closed")
            if q.get("at_as_of"):
                row[f"{venue}_resolved_mid"] = q.get("resolved_mid")
        p = r.get("private")
        if isinstance(p, dict):
            row.update(private_yes=p.get("yes"), private_no=p.get("no"), private_status=p.get("status"), private_bets=p.get("bets"),
                       private_settled_pnl=p.get("settled_pnl"))
        row["gap_polymarket"] = r.get("gap")
        rows.append(row)
    return rows


def list_markets(conn, race_id=None, event_id=None, competition=None, sport=None, kinds=None, limit=None, offset=0):
    """One row per outcome (kind x subject): our fair value, each venue's quote, the gap and, for a past race, the
    result. Give race_id (or event_id: its first race) for a race weekend, or competition/sport for the season markets."""
    from racinglines.markets import venues as V
    if race_id is None and event_id is not None:
        r = data.q(conn, "SELECT id FROM races WHERE event_id = :e ORDER BY id LIMIT 1", e=int(event_id))
        if not len(r):
            raise ValueError(f"event {event_id} has no races")
        race_id = int(r["id"].iloc[0])
    if race_id is not None:
        info, pricing, df = V.event_matrix(conn, int(race_id))
        if info is None:
            raise ValueError(f"no race {race_id}")
        head = dict(race_id=int(race_id), event_id=info["event_id"], title=info["title"], competition=info["competition"],
                    season=info["season"], status=info["status"], start_date=info["start_date"], race_start=info["race_start"])
    else:
        comp = _sport_filter(sport, competition)
        if not comp:
            raise ValueError("give race_id, event_id, or competition/sport (season markets)")
        info, pricing, df = V.season_matrix(conn, comp)
        if info is None:
            raise ValueError(f"no competition {comp!r}")
        head = dict(competition=comp, title=info["title"], scope="season")
    if kinds:
        want = [k.strip() for k in kinds.split(",")]
        df = df[df["kind"].isin(want)] if len(df) else df
    rows = _matrix_rows(df) if len(df) else []
    by_kind = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    return dict(**P.record(head), pricing=P.record(pricing or {}), outcomes_by_kind=by_kind,
                venues=[dict(venue=v["venue"].code, listed=v["listed"], volume=v["volume"]) for v in V.venue_summary(df)] if len(df) else [],
                outcomes=P.page(rows, limit=limit, offset=offset))


def _tokens_for(conn, race_id=None, kind=None, athlete_id=None, subject=None, exchange=None, competition=None):
    where, params = ["prediction <> 'unmodeled'"], {}
    if race_id is not None:
        where.append("ml.race_id = :r"); params["r"] = int(race_id)
    if competition:
        where.append("co.code = :c AND ml.race_id IS NULL"); params["c"] = competition
    if kind:
        where.append("ml.prediction = :k"); params["k"] = kind
    if athlete_id is not None:
        where.append("ml.athlete_id = :a"); params["a"] = int(athlete_id)
    if subject:
        where.append("(a.display_name ILIKE '%' || :s || '%' OR ml.params->>'team' ILIKE '%' || :s || '%' OR ml.question ILIKE '%' || :s || '%')")
        params["s"] = subject
    if exchange:
        where.append("ml.exchange = :x"); params["x"] = exchange
    return data.q(conn, f"""
        SELECT ml.token_id, ml.exchange, ml.prediction AS kind, coalesce(a.display_name, ml.params->>'team', ml.outcome) AS subject,
               ml.outcome, ml.question, ml.invert, ml.closed, ml.resolved_yes, ml.race_id
        FROM market_links ml LEFT JOIN athletes a ON a.id = ml.athlete_id JOIN competitions co ON co.id = ml.competition_id
        WHERE {' AND '.join(where)} ORDER BY ml.id""", **params)


def get_market_history(conn, tokens=None, race_id=None, kind=None, athlete_id=None, subject=None, exchange=None,
                       series="prices", start=None, end=None, resample="1h", limit=None, offset=0):
    """Exchange time series from the archive and the database: prices (resampled: last price per bucket), trades
    (per bucket: count, volume, VWAP; resample=None lists trades) or books (best bid/ask per bucket). Pick the
    markets by tokens (comma-separated ids) or by race_id/kind/athlete_id/subject; a race defaults to the week
    before its start. Every token is capped at 200 points."""
    from racinglines.markets import store as MS
    if series not in ("prices", "trades", "books"):
        raise ValueError("series is prices, trades or books")
    if tokens:
        toks = [t.strip() for t in str(tokens).split(",") if t.strip()]
        links = _tokens_for(conn, exchange=exchange)
        links = links[links["token_id"].isin(toks)] if len(links) else links
        names = {r["token_id"]: r for r in links.to_dict("records")}
        toks = list(dict.fromkeys(toks))
    else:
        links = _tokens_for(conn, race_id=race_id, kind=kind, athlete_id=athlete_id, subject=subject, exchange=exchange)
        if len(links) > 40:
            raise ValueError(f"{len(links)} markets match; narrow with kind/athlete_id/subject/exchange or pass tokens")
        toks = links["token_id"].tolist()
        names = {r["token_id"]: r for r in links.to_dict("records")}
    if not toks:
        return dict(tokens=[], series=series, rows=P.page([], limit=limit), note="no markets match")
    if start is None and end is None and race_id is not None:
        from racinglines.markets import venues as V
        info = V.race_info(conn, int(race_id))
        t1 = pd.Timestamp(info["race_start"] if info and info.get("race_start") is not None else info["start_date"]).tz_localize("UTC")
        start, end = t1 - pd.Timedelta(days=7), t1 + pd.Timedelta(hours=6)
    start = pd.Timestamp(start).tz_localize("UTC") if start is not None and pd.Timestamp(start).tzinfo is None else \
        (pd.Timestamp(start) if start is not None else None)
    end = pd.Timestamp(end).tz_localize("UTC") if end is not None and pd.Timestamp(end).tzinfo is None else \
        (pd.Timestamp(end) if end is not None else None)
    df = MS.read(conn, series, tokens=toks, start=start, end=end)
    if not len(df):
        return dict(tokens=[P.record(names.get(t, dict(token_id=t))) for t in toks], series=series,
                    rows=P.page([], limit=limit), note="no stored rows in that window")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    span = df["ts"].max() - df["ts"].min()
    step = None
    if resample:
        step = pd.Timedelta(resample)
        if span / step > 200:
            step = span / 200
    out = []
    for tok, g in df.groupby("token_id"):
        g = g.sort_values("ts")
        if step is None:
            cols = [c for c in ("ts", "price", "size", "side", "best_bid", "best_ask") if c in g.columns]
            s = g[cols].tail(200)
            recs = s.to_dict("records")
        elif series == "prices":
            s = g.set_index("ts")["price"].resample(step).last().dropna()
            recs = [dict(ts=t, price=v) for t, v in s.items()]
        elif series == "trades":
            gi = g.set_index("ts")
            agg = gi.resample(step).agg(trades=("price", "size"), volume=("size", "sum"))
            vw = (gi["price"] * gi["size"]).resample(step).sum() / gi["size"].resample(step).sum()
            agg["vwap"] = vw
            agg = agg[agg["trades"] > 0]
            recs = [dict(ts=t, **r) for t, r in agg.to_dict("index").items()]
        else:
            s = g.set_index("ts")[["best_bid", "best_ask"]].resample(step).last().dropna(how="all")
            recs = [dict(ts=t, **r) for t, r in s.to_dict("index").items()]
        for r in recs:
            r["token_id"] = tok
        out.extend(recs)
    out.sort(key=lambda r: (r["token_id"], r["ts"]))
    return dict(tokens=[P.record(names.get(t, dict(token_id=t))) for t in toks], series=series,
                window=dict(start=P.plain(df["ts"].min()), end=P.plain(df["ts"].max()), rows_read=int(len(df)),
                            bucket=str(step) if step is not None else None),
                rows=P.page(out, limit=limit or 200, offset=offset, max_bytes=P.MAX_BYTES * 2))


# ---------------------------------------------------------------------------------------------------
# model runs, predictions, forecasts
# ---------------------------------------------------------------------------------------------------

def list_model_runs(conn, kind=None, competition=None, sport=None, season=None, limit=None, offset=0):
    comp = _sport_filter(sport, competition)
    df = data.q(conn, """
        SELECT mr.id, mr.kind, co.code AS competition, s.year AS season, c.code AS category, mr.model, mr.created_at,
               mr.data_through, mr.params->>'variant' AS variant, mr.params->>'cutoff' AS cutoff, mr.params->>'event_key' AS event_key,
               mr.params->>'label' AS label, mr.params->>'name' AS name, mr.params->>'year' AS year,
               (SELECT count(*) FROM race_predictions rp WHERE rp.model_run_id = mr.id) AS predictions,
               pg_column_size(mr.metrics) AS metrics_bytes
        FROM model_runs mr JOIN competitions co ON co.id = mr.competition_id
        LEFT JOIN seasons s ON s.id = mr.season_id LEFT JOIN categories c ON c.id = mr.category_id
        WHERE (CAST(:k AS text) IS NULL OR mr.kind = CAST(:k AS text)) AND (CAST(:c AS text) IS NULL OR co.code = CAST(:c AS text))
          AND (CAST(:y AS int) IS NULL OR s.year = CAST(:y AS int) OR (mr.params->>'year')::int = CAST(:y AS int))
        ORDER BY mr.id DESC""", k=kind, c=comp, y=season)
    return P.page(df, limit=limit, offset=offset, note=f"kinds: {', '.join(RUN_KINDS)}")


def _dig(obj, path):
    cur = obj
    for part in [p for p in re.split(r"[./]", path) if p]:
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            if part not in cur:
                raise ValueError(f"no key {part!r}; keys: {list(cur)[:40]}")
            cur = cur[part]
        else:
            raise ValueError(f"{path}: {part!r} is not inside a dict or list")
    return cur


def get_model_run(conn, run_id, path=None):
    """One run with its params and metrics. Large metrics come back as a key map with sizes; `path` (e.g.
    'metrics.weekends' or 'metrics.weekends.0') returns that part whole (paged when it is a list)."""
    run = data.model_run(conn, int(run_id))
    if not run:
        raise ValueError(f"no model run {run_id}")
    targets = data.run_race_targets(conn, run_id)
    if path:
        part = _dig(dict(params=run.get("params") or {}, metrics=run.get("metrics") or {}), path)
        if isinstance(part, list):
            rows = part if part and isinstance(part[0], dict) else [dict(value=v) for v in part]
            return dict(run_id=int(run_id), path=path, value=P.page(rows, limit=P.DEFAULT_LIMIT))
        val = P.plain(part, preview=False)
        s = json.dumps(val, default=str)
        if len(s) > P.MAX_BYTES:
            return dict(run_id=int(run_id), path=path, size=len(s),
                        keys={k: len(json.dumps(v, default=str)) for k, v in part.items()} if isinstance(part, dict) else None,
                        note="too large; ask for a sub-path")
        return dict(run_id=int(run_id), path=path, value=val)
    params, metrics = run.get("params") or {}, run.get("metrics") or {}
    head = {k: v for k, v in run.items() if k not in ("params", "metrics")}
    out = dict(run=P.record(head), params=P.plain(params, preview=False),
               targets=[P.record(r) for r in targets.to_dict("records")][:40])
    ms = json.dumps(metrics, default=str)
    if len(ms) <= P.MAX_BYTES // 2:
        out["metrics"] = P.plain(metrics, preview=False)
    else:
        out["metrics"] = dict(_size=len(ms), keys={k: len(json.dumps(v, default=str)) for k, v in metrics.items()},
                              note="pass path='metrics.<key>' for one part")
    return out


def get_predictions(conn, run_id, target=None, top=20, standings=False):
    """A run's per-athlete probabilities for one target (race), or its projected standings."""
    if standings:
        return P.page(data.standings_predictions(conn, int(run_id)), limit=top)
    targets = data.run_race_targets(conn, int(run_id))
    if not len(targets):
        st = data.standings_predictions(conn, int(run_id))
        if len(st):
            return dict(note="this run has standings only", standings=P.page(st, limit=top))
        raise ValueError(f"run {run_id} has no predictions")
    if target is None:
        if len(targets) > 1:
            return dict(note="pick a target", targets=P.page(targets, limit=60))
        target = targets["target"].iloc[0]
    df = data.race_predictions(conn, int(run_id), target, limit=P.clamp(top, 20))
    t = targets[targets["target"] == target]
    return dict(target=P.record(t.iloc[0].to_dict()) if len(t) else dict(target=target), predictions=P.page(df, limit=top))


def get_forecast(conn, competition=None, sport=None, category=None, top=10):
    """The live forecast (the run the web app shows): its next races' top probabilities and the championship."""
    comp = _sport_filter(sport, competition)
    fc = data.latest_forecasts(conn)
    if comp:
        fc = fc[fc["competition"] == comp]
    if category:
        fc = fc[fc["category"] == category]
    if not len(fc):
        return dict(forecasts=[], note="no forecast run stored" + (f" for {comp}" if comp else ""))
    out = []
    for r in fc.to_dict("records"):
        rid = int(r["id"])
        targets = data.run_race_targets(conn, rid)
        upcoming = targets[targets["status"].fillna("scheduled") != "completed"] if len(targets) else targets
        races = []
        for t in upcoming.head(3).to_dict("records"):
            preds = data.race_predictions(conn, rid, t["target"], limit=P.clamp(top, 10))
            races.append(dict(target=t["target"], event=t.get("event_name"), start_date=P.plain(t.get("start_date")),
                              top=[P.record(x) for x in preds.to_dict("records")]))
        st = data.standings_predictions(conn, rid, limit=P.clamp(top, 10))
        out.append(dict(run=P.record(r), next_races=races, standings=[P.record(x) for x in st.to_dict("records")],
                        targets=int(len(targets))))
    return dict(forecasts=out)


# ---------------------------------------------------------------------------------------------------
# strategy research: Edge Finder, diagnostics, maker replay
# ---------------------------------------------------------------------------------------------------

def edge_finder(conn, year=2026, strategy=None, limit=None, offset=0):
    """Every configuration with a full-season sweep of `year`, with the full-season recap of each strategy
    (P&L, volume, weekends up, drawdown, consistency): what the Lab's Edge Finder shows, from saved runs only."""
    from racinglines.web import edge as E
    cfgs = E.configs(conn, int(year))
    strategies = [strategy] if strategy else E.STRATEGY_KEYS
    unknown = [s for s in strategies if s not in E.STRATEGY_LABEL]
    if unknown:
        raise ValueError(f"unknown strategy {unknown}; one of {E.STRATEGY_KEYS}")
    rows = []
    for c in cfgs.values():
        run = E._run(conn, c["run_id"])
        weekends = (run or {}).get("metrics", {}).get("weekends") or []
        for s in strategies:
            rc = E.recap(weekends, s)
            rows.append(dict(config=c["label"], settings_key=c["key"], run_id=c["run_id"], strategy=s,
                             strategy_label=E.STRATEGY_LABEL[s], **{k: v for k, v in rc.items()}))
    rows.sort(key=lambda r: -(r["pnl"] or 0))
    return dict(year=int(year), configurations=len(cfgs), strategies={k: E.STRATEGY_LABEL[k] for k in strategies},
                changed_settings={c["key"]: c["settings"].changed() for c in cfgs.values()},
                rows=P.page(rows, limit=limit, offset=offset))


def list_candidates(conn, limit=None, offset=0):
    """Named configurations x strategy saved in the Lab (searches add theirs; strategy profiles A and C are candidates)."""
    from racinglines.web import edge as E
    rows = [{k: v for k, v in c.items() if k != "settings"} | dict(settings=c["settings"]) for c in E.candidates(conn)]
    return P.page(rows, limit=limit, offset=offset)


def list_diagnostics(conn, limit=None, offset=0):
    """Events with as-of diagnostic runs (the maker replay's inputs): run ids per event and cutoffs."""
    runs = data.q(conn, """
        SELECT mr.params->>'event_key' AS event_key, count(*) AS runs, min(mr.id) AS first_run, max(mr.id) AS last_run,
               min(mr.params->>'cutoff') AS first_cutoff, max(mr.params->>'cutoff') AS last_cutoff,
               bool_or(mr.params ? 'sweep_stage') AS from_sweep
        FROM model_runs mr WHERE mr.kind = 'diagnostic' GROUP BY 1 ORDER BY max(mr.params->>'cutoff') DESC""")
    return P.page(runs, limit=limit, offset=offset, note="get_diagnostic(run_id) for one; replay_maker(run_id, ...) to re-quote it")


def get_diagnostic(conn, run_id, top=25):
    """One as-of diagnostic run: our prices vs the exchange at the cutoff, scored per kind, and the result."""
    from racinglines.web import diag as D
    d = D.load(conn, int(run_id))
    if d is None:
        raise ValueError(f"no diagnostic run {run_id}")
    mk = d["markets"]
    cols = ["kind", "subject", "outcome_label", "fair", "pm_cut", "pm_24h_before", "pm_move_24h", "edge", "paper_side", "result", "paper_pnl"]
    mk = mk[[c for c in cols if c in mk.columns]] if len(mk) else mk
    if len(mk):
        mk = mk.assign(_abs=mk["edge"].abs().fillna(-1)).sort_values("_abs", ascending=False).drop(columns="_abs")
    return dict(run=P.record({k: d["run"][k] for k in ("id", "kind", "created_at", "data_through") if k in d["run"]}),
                cutoff=P.plain(d["cutoff"]), event=P.record(d["event"]), race_id=d["race_id"],
                params=P.plain(d["params"], preview=False),
                scores=[P.record(r) for r in d["scores"].to_dict("records")], coherence=P.plain(d["coherence"], preview=False),
                predictions=P.page(d["preds"].drop(columns=["extra"], errors="ignore"), limit=top, note="by win probability"),
                markets=P.page(mk, limit=top, note="largest |edge| first"),
                result=P.page(d["result"], limit=top),
                paper_pnl=P.plain(mk["paper_pnl"].sum()) if len(mk) and "paper_pnl" in mk else None)


REPLAY_KNOBS = ("fill", "half_spread", "size", "max_pos", "max_capital", "skew", "max_disagree", "min_volume_24h", "pull_min")


def replay_maker(conn, run_id, fill="through", half_spread=0.02, size=50, max_pos=250, max_capital=1000, skew=1.0,
                 max_disagree=0.15, min_volume_24h=100, pull_min=15, exchange="polymarket", with_sweep=False, top=20):
    """Replay a maker quoting the exchange (polymarket, or kalshi with its maker fee) through an event's diagnostic
    runs against the real trade tape, with the diagnostic page's knobs. Synchronous, a few seconds; nothing is stored."""
    from racinglines.web import diag as D
    if fill not in ("through", "touch", "queue"):
        raise ValueError("fill is through, touch or queue")
    if exchange not in ("polymarket", "kalshi"):
        raise ValueError("exchange is polymarket or kalshi")
    knobs = dict(fill=fill, half_spread=float(half_spread), size=float(size), max_pos=float(max_pos), max_capital=float(max_capital),
                 skew=float(skew), max_disagree=float(max_disagree), min_volume_24h=float(min_volume_24h), pull_min=float(pull_min))
    rp = D.replay(conn, int(run_id), with_sweep=bool(with_sweep), exchange=exchange, **knobs)
    out = dict(run_ids=list(rp["runs"]), exchange=exchange, knobs=knobs,
               summary=[P.record(r) for r in rp["summary"].to_dict("records")],
               by_stage=P.page(rp["stages"], limit=20) if isinstance(rp["stages"], pd.DataFrame) else P.plain(rp["stages"]),
               skips=[P.record(r) for r in rp["skips"].to_dict("records")],
               positions=P.page(rp["positions"], limit=top, note="worst P&L first"),
               fills=dict(count=int(len(rp["fills"])),
                          first=P.page(rp["fills"], limit=min(P.clamp(top), 20), note="first fills; the count is the total")))
    if with_sweep and rp["sweep"] is not None:
        out["sweep"] = P.page(rp["sweep"], limit=40)
    return out


# ---------------------------------------------------------------------------------------------------
# paper trading: positions, track record, signals; live events; change log
# ---------------------------------------------------------------------------------------------------

TRACK_RECORD_VENUES = ("polymarket", "kalshi", "private")


def _basic_viewer(viewer):
    """A basic caller (dict(id, username, role), server.caller()): its own account only, never which strategy made
    a pick (web/roles.basic_*). None for everyone else (stdio, admin, pro): output as before."""
    from racinglines.web import roles as R
    return viewer if viewer and R.canonical(viewer.get("role")) == "basic" else None


def track_record(conn, user, venue="polymarket", viewer=None):
    """Every weekend of a user's paper record: strategy, trades or fills, positions, P&L. venue: polymarket, kalshi,
    private or all. 'all' lists one row per weekend AND venue (a `venue` column; the maker's weekends have a
    Polymarket and a Kalshi row) with `totals` per venue next to the grand total; `weekends` counts distinct weekends."""
    from racinglines.pipelines import story as S
    from racinglines.web import roles as R
    basic = _basic_viewer(viewer)
    uid = basic["id"] if basic else _user_id(conn, user)
    if basic:
        user = basic["username"]
    tr = (lambda *a, **k: [R.basic_row(r) for r in S.track_record(*a, **k)]) if basic else S.track_record
    if venue != "all":
        rows = tr(conn, uid, venue=venue)
        pnl = sum(r["pnl"] for r in rows)
        return dict(user=user, venue=venue, weekends=len(rows), pnl=P.plain(pnl), up=sum(1 for r in rows if r["pnl"] > 0),
                    rows=P.page([{k: v for k, v in r.items() if k != "date"} for r in rows], limit=P.MAX_LIMIT))
    rows, totals = [], []
    for v in TRACK_RECORD_VENUES:
        part = tr(conn, uid, venue=v)
        rows += [dict(event_key=r["event_key"], venue=v, **{k: x for k, x in r.items() if k not in ("event_key", "date")})
                 for r in part]
        if part:
            totals.append(dict(venue=v, weekends=len(part), pnl=P.plain(sum(r["pnl"] for r in part)),
                               up=sum(1 for r in part if r["pnl"] > 0)))
    rows.sort(key=lambda r: (r["event_key"], TRACK_RECORD_VENUES.index(r["venue"])))
    pnl = sum(r["pnl"] for r in rows)
    return dict(user=user, venue=venue, weekends=len({r["event_key"] for r in rows}), pnl=P.plain(pnl),
                up=sum(1 for r in rows if r["pnl"] > 0), totals=totals, rows=P.page(rows, limit=P.MAX_LIMIT))


def list_positions(conn, user, venue=None, event_key=None, open_only=False, limit=None, offset=0, viewer=None):
    basic = _basic_viewer(viewer)
    uid = basic["id"] if basic else _user_id(conn, user)
    if basic:
        user = basic["username"]
    df = data.q(conn, """
        SELECT pp.event_key, pp.venue, pp.kind, pp.subject, pp.market_key, pp.yes_shares, pp.no_shares, pp.cash, pp.mark, pp.outcome,
               pp.bid, pp.ask, pp.quote_state, pp.updated_at,
               pp.cash + pp.yes_shares * coalesce(pp.outcome::int, pp.mark, 0) + pp.no_shares * (1 - coalesce(pp.outcome::int, pp.mark, 0)) AS pnl
        FROM paper_positions pp WHERE pp.user_id = :u AND (CAST(:v AS text) IS NULL OR pp.venue = CAST(:v AS text))
          AND (CAST(:e AS text) IS NULL OR pp.event_key = CAST(:e AS text))
          AND (NOT :o OR pp.outcome IS NULL) ORDER BY pp.event_key DESC, pp.venue, pp.kind, pp.subject""",
        u=uid, v=venue, e=event_key, o=bool(open_only))
    totals = df.groupby("venue")["pnl"].agg(["sum", "count"]).reset_index() if len(df) else pd.DataFrame()
    return dict(user=user, totals=[P.record(r) for r in totals.to_dict("records")], positions=P.page(df, limit=limit, offset=offset))


def list_signals(conn, user=None, event_key=None, status=None, action=None, limit=None, offset=0, viewer=None):
    """Paper signals, newest first. A basic viewer: its own only, as roles.basic_signal shows them (no profile,
    strategy, member, fair value or edge; a `stars` rating instead)."""
    basic = _basic_viewer(viewer)
    uid = basic["id"] if basic else (_user_id(conn, user) if user else None)
    df = data.q(conn, """
        SELECT ss.id, u.username AS "user", ss.profile, ss.strategy, ss.event_key, ss.kind, ss.subject, ss.stage, ss.action, ss.side,
               ss.shares, ss.limit_price, ss.fair, ss.price, ss.edge, ss.heat, ss.target_cost, ss.status, ss.signal_ts, ss.market_key,
               ss.detail->>'venue' AS venue, ss.detail->>'backfill' AS backfill, ss.detail->>'member' AS _member
        FROM strategy_signals ss JOIN users u ON u.id = ss.user_id
        WHERE (CAST(:u AS int) IS NULL OR ss.user_id = CAST(:u AS int)) AND (CAST(:e AS text) IS NULL OR ss.event_key = CAST(:e AS text))
          AND (CAST(:s AS text) IS NULL OR ss.status = CAST(:s AS text)) AND (CAST(:a AS text) IS NULL OR ss.action = CAST(:a AS text))
        ORDER BY ss.id DESC""", u=uid, e=event_key, s=status, a=action)
    if basic:
        from racinglines.pipelines import profiles as PF
        from racinglines.web import roles as R
        prof = PF.of_user(conn, uid)
        recs = [R.basic_signal(dict(r, detail={"member": r.pop("_member")}), prof) for r in df.to_dict("records")]
        for r in recs:
            r.pop("detail", None)
        cols = [c for c in df.columns if c not in R.BASIC_HIDDEN and c != "_member"] + ["stars"]
        df = pd.DataFrame(recs, columns=cols)
    else:
        df = df.drop(columns="_member")
    return P.page(df, limit=limit, offset=offset)


def list_live_events(conn, limit=None, offset=0):
    """Settled live private-book events (the live_events table) and the run folders present on this machine."""
    from racinglines.pipelines import live as L
    df = data.q(conn, """SELECT run, sport, event_key, title, opened_at, settled_at, maker_pnl, crowd_pnl, taker_pnl, fills, volume
                         FROM live_events ORDER BY opened_at DESC NULLS LAST""")
    try:
        folders = [dict(run=e["run"], sport=e["sport"], event_key=e["event_key"], title=e["title"],
                        updated=datetime.fromtimestamp(e["mtime"], tz=timezone.utc)) for e in L.events()]
        state = L.state()
    except Exception as ex:  # noqa: BLE001
        folders, state = [], f"unreadable: {ex}"
    return dict(state=state, settled=P.page(df, limit=limit, offset=offset), run_folders=[P.record(f) for f in folders][:20])


def data_changes(conn, sport=None, limit=None, offset=0):
    df = data.q(conn, """SELECT id, at, sport, kind, summary, by, detail FROM data_changes
                         WHERE (CAST(:s AS text) IS NULL OR sport = CAST(:s AS text)) ORDER BY at DESC, id DESC""", s=sport)
    return P.page(df, limit=limit, offset=offset)


# ---------------------------------------------------------------------------------------------------
# sql: read-only, capped
# ---------------------------------------------------------------------------------------------------

_SQL_FORBIDDEN = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|vacuum|analyze|"
                            r"reindex|cluster|lock|listen|notify|set|reset|call|do|refresh|comment|security|pg_sleep|"
                            r"pg_read_file|pg_ls_dir|lo_import|lo_export|dblink)\b", re.I)
# functions that run a query given as text (which hides a table name in a string), read server files or settings,
# or reach other roles' secrets; and the catalogs holding role password hashes
_SQL_FORBIDDEN_FN = re.compile(r"\b(query_to_xml\w*|cursor_to_xml\w*|table_to_xml\w*|schema_to_xml\w*|database_to_xml\w*|"
                               r"ts_stat|ts_rewrite|set_config|pg_read_\w+|pg_stat_file|pg_ls_\w+|pg_file_\w+|lo_\w+|"
                               r"dblink\w*|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|"
                               r"pg_authid|pg_shadow|pg_user_mappings|pg_hba_file_rules)\b", re.I)


def _strip_comments(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


# one left-to-right pass, so a quote inside one kind of token never starts another: dollar-quoted, E'' (backslash
# escapes), plain '' and "identifier"
_SQL_TOKENS = re.compile(r"\$(\w*)\$.*?\$\1\$|(?<!\w)[eE]'(?:[^'\\]|\\.|'')*'|'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", re.S)


def _strip_literals(sql):
    """The query with its string constants blanked ('..', E'..', $tag$..$tag$), so a word inside a value (a variant
    named 'gridq+pretrain+reset') is not read as a keyword. Identifiers in double quotes are kept."""
    return _SQL_TOKENS.sub(lambda m: m.group(0) if m.group(0).startswith('"') else "''", sql)


def check_sql(query):
    """The query text a client may run: one SELECT (or WITH ... SELECT), no writes, no hidden tables.

    A first filter only, with friendly errors: the real boundary is the database role the sql tool connects as
    (RACINGLINES_MCP_SQL_URL, docs/mcp.md), which can read only the allowed tables."""
    q = _strip_comments(query or "").strip().rstrip(";").strip()
    if not q:
        raise ValueError("empty query")
    if ";" in q:
        raise ValueError("one statement only")
    if not re.match(r"(?is)^(select|with|table|values|explain)\b", q):
        raise ValueError("only SELECT (or WITH ... SELECT / EXPLAIN) queries")
    if re.search(r"\bu&['\"]", q, re.I):
        raise ValueError("Unicode-escaped names and strings (U&) are not accepted")
    code = _strip_literals(q)
    if _SQL_FORBIDDEN.search(code) or _SQL_FORBIDDEN_FN.search(code):
        raise ValueError("only read-only queries: no writes, DDL, settings, or server-side functions")
    for t in SQL_HIDDEN:
        if re.search(rf"\b{t}\b", q, re.I):
            raise ValueError(f"the {t} table is not readable through this tool")
    return q


def sql(conn, query, limit=None, offset=0):
    """Run a read-only query. The transaction is READ ONLY with a statement timeout, and the result is paged
    (`limit` rows, at most 500; an outer LIMIT/OFFSET is applied for you). Hidden: users, orders."""
    q = check_sql(query)
    lim, off = P.clamp(limit), max(0, int(offset or 0))
    conn.execute(text(f"SET LOCAL statement_timeout = '{SQL_TIMEOUT}'"))
    if q.lower().startswith("explain"):
        res = conn.execute(text(q))
        return dict(plan=[r[0] for r in res.fetchall()][:60])
    res = conn.execute(text(f"SELECT * FROM ({q}) AS _q LIMIT {lim + 1} OFFSET {off}"))
    cols = list(res.keys())
    fetched = res.fetchall()
    more = len(fetched) > lim
    rows = [dict(zip(cols, r)) for r in fetched[:lim]]
    total = None
    if not more and off == 0:
        total = len(rows)
    out = P.page(rows, limit=lim, offset=0, columns=cols, total=len(rows))
    out.update(offset=off, truncated=bool(more), next_offset=(off + lim) if more else None, total=total)
    out["note"] = (f"{len(rows)} rows shown, more exist; pass offset={off + lim} for the next page" if more else
                   f"{len(rows)} rows" + (f" from offset {off}" if off else "")) + ("; " + out["note"] if "cut to" in out["note"] else "")
    return out


# ---------------------------------------------------------------------------------------------------
# jobs: the Lab's simulations (a CLI subprocess per job, saved as a model run)
# ---------------------------------------------------------------------------------------------------

def list_job_types():
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.web import jobs as J
    out = []
    for jt in J.CATALOG.values():
        knobs = []
        for k in jt.knobs:
            if k.type == "sweep_settings":
                knobs.append(dict(name="settings", type="object", help="any sweep setting (see sweep_settings below); "
                                  "unset ones keep their defaults"))
            else:
                knobs.append(dict(name=k.name, type=k.type, default=k.default, min=k.min, max=k.max,
                                  choices=k.choices or None, help=k.help))
        out.append(dict(job_type=jt.code, sport=jt.sport, label=jt.label, what=jt.what, takes=jt.minutes, knobs=knobs))
    settings = [dict(name=s.name, group=s.group, type=s.type, default=(list(s.default) if isinstance(s.default, tuple) else s.default),
                     min=s.min, max=s.max, choices=list(s.choices) or None, help=s.help) for s in SS.SETTINGS]
    return dict(job_types=out, sweep_settings=settings, model_variants=J.MODEL_CHOICES,
                note="run_job(job_type, params) queues one; get_job(job_id) follows it; forecasts save as scenarios "
                     "(never the live prices); event is 'YYYY-R' (e.g. 2026-15), cutoff 'YYYY-MM-DDTHH:MM' UTC")


def _job_params(job_type, params):
    from racinglines.web import jobs as J
    jt = J.CATALOG.get(job_type)
    if jt is None:
        raise ValueError(f"unknown job type {job_type!r}; one of {list(J.CATALOG)}")
    params = dict(params or {})
    form = {}
    for k in jt.knobs:
        if k.type == "sweep_settings":
            continue
        v = params.pop(k.name, None)
        if v is not None:
            form[k.name] = str(v).strip()
    settings = params.pop("settings", None)
    if params:
        raise ValueError(f"unknown knobs for {job_type}: {sorted(params)}")
    out = J.parse(jt, form)
    if any(k.type == "sweep_settings" for k in jt.knobs):
        from racinglines.pipelines import sweep_settings as SS
        st = SS.Settings.from_dict({k: v for k, v in (settings or {}).items()})
        out["settings"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in st.changed().items()}
    return jt, out


def run_job(engine, job_type, params=None, user_id=None):
    """Queue a Lab job (filed under `user_id`: the account behind the request in --http mode, none over stdio).
    Returns its id; `get_job` follows it. The job runs once a worker (this server's, or the web app's) picks it up."""
    from racinglines.web import jobs as J
    jt, p = _job_params(job_type, params)
    job_id = J.submit(jt, p, user_id, engine=engine)
    return dict(job_id=int(job_id), job_type=jt.code, params=p, status="queued",
                note=f"{jt.label}: {jt.minutes or 'a while'}. get_job({job_id}) for progress; the run it saves is result_run_id")


def _job_row(r, log_lines):
    log = r.pop("log", None) or ""
    lines = log.splitlines()
    r["log_tail"] = lines[-int(log_lines):] if log_lines else []
    r["log_lines"] = len(lines)
    return P.record(r)


def get_job(conn, job_id, log_lines=20):
    df = data.q(conn, "SELECT * FROM jobs WHERE id = :i", i=int(job_id))
    if not len(df):
        raise ValueError(f"no job {job_id}")
    return _job_row(df.iloc[0].to_dict(), log_lines)


def list_jobs(conn, status=None, limit=None, offset=0):
    df = data.q(conn, """SELECT j.id, j.kind, j.sport, j.status, j.progress, j.created_at, j.started_at, j.finished_at, j.result_run_id,
                                j.params, u.username AS "user" FROM jobs j LEFT JOIN users u ON u.id = j.user_id
                         WHERE (CAST(:s AS text) IS NULL OR j.status = CAST(:s AS text)) ORDER BY j.id DESC""", s=status)
    return P.page(df, limit=limit, offset=offset)


def cancel_job(engine, job_id):
    """Cancel a job that is still queued (a running subprocess is left to finish)."""
    with engine.begin() as c:
        n = c.execute(text("""UPDATE jobs SET status = 'failed', finished_at = now(), progress = 'cancelled before it started'
                              WHERE id = :i AND status = 'queued'"""), dict(i=int(job_id))).rowcount
    return dict(job_id=int(job_id), cancelled=bool(n), note="" if n else "not queued (already running, done or failed)")
