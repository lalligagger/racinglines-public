"""
The maker's home page: every sport, what's next, what's live, what just happened.

Per sport: the next races (fair favourites, venue status, my exposure), the season
markets, and recent results with how our pre-race price did. Plus a few headline
numbers across everything.
"""

from datetime import datetime, timezone

import pandas as pd

from racinglines.db import reads as data
from racinglines.markets import private_book as house
from racinglines.markets.venues import SPORT_NAME, SPORT_ORDER, event_matrix, season_matrix, venue_summary


def _countdown(d):
    if d is None or pd.isna(d):
        return ""
    days = (pd.Timestamp(d).date() - datetime.now(timezone.utc).date()).days
    return "today" if days == 0 else ("tomorrow" if days == 1 else (f"in {days} days" if days > 0 else f"{-days} days ago"))


def _top(df, kind, n=3):
    g = df[df["kind"] == kind] if len(df) else df
    return g.head(n).to_dict("records") if len(g) else []


def _mine(df):
    p = [x for x in (df["private"].dropna() if len(df) else []) if x["status"] == "open"]
    return dict(open=len(p), worst=sum(x["worst"] for x in p), staked=sum(x["staked"] for x in p))


def _card(conn, race_id, maker_id, show_kind="race_win"):
    info, pricing, df = event_matrix(conn, race_id, maker_id)
    return dict(info=info, pricing=pricing, top=_top(df, show_kind), venues=venue_summary(df), mine=_mine(df),
                countdown=_countdown(info["start_date"]), outcomes=len(df))


def recent_results(conn, competition_id, n=3):
    races = data.q(conn, """
        SELECT ra.id AS race_id FROM races ra JOIN events e ON e.id = ra.event_id JOIN seasons s ON s.id = e.season_id
        JOIN categories c ON c.id = ra.category_id
        WHERE s.competition_id = :c AND e.status = 'completed' AND c.code IN ('DRV', 'ME')
          AND EXISTS (SELECT 1 FROM rounds ro JOIN results r ON r.round_id = ro.id
                      WHERE ro.race_id = ra.id AND ro.kind IN ('race', 'final'))
        ORDER BY e.start_date DESC LIMIT :n""", c=competition_id, n=n)
    bt = data.q(conn, """SELECT metrics->'events' AS ev FROM model_runs WHERE kind = 'backtest' AND competition_id = :c
                         ORDER BY id DESC LIMIT 1""", c=competition_id)
    bt_ev = {}
    for e in (bt["ev"].iloc[0] if len(bt) and bt["ev"].iloc[0] else []):
        if e.get("mode") == "pre_race" and e.get("track_features") in (True, None):
            bt_ev[e["event_id"]] = e
    out = []
    for rid in races["race_id"]:
        info, pricing, df = event_matrix(conn, int(rid))
        res = house.race_outcomes(conn, int(rid)).sort_values("position")
        win = res[(res["position"] == 1) & (res["status"] == "OK")]
        winner_id = int(win["athlete_id"].iloc[0]) if len(win) else None
        w = df[(df["kind"] == "race_win") & (df["athlete_id"] == winner_id)] if len(df) and winner_id else pd.DataFrame()
        our = float(w["fair"].iloc[0]) if len(w) and w["fair"].iloc[0] is not None else None
        pm = float(w["pm_mid"].iloc[0]) if len(w) and w["pm_mid"].iloc[0] is not None and pd.notna(w["pm_mid"].iloc[0]) else None
        source = pricing["source"]
        if our is None and info["event_id"] in bt_ev:
            our, source = bt_ev[info["event_id"]].get("winner_prob"), "backtest (as of before the race)"
        name = data.q(conn, "SELECT display_name FROM athletes WHERE id = :a", a=winner_id)["display_name"].iloc[0] \
            if winner_id else None
        diag = data.q(conn, """SELECT max(id) AS id FROM model_runs WHERE kind = 'diagnostic'
                               AND params->>'event_key' = :k""", k=info["source_key"])["id"].iloc[0]
        out.append(dict(info=info, winner=name, our=our, pm=pm, source=source,
                        diag=int(diag) if diag is not None and pd.notna(diag) else None,
                        countdown=_countdown(info["start_date"])))
    return out


def board(conn, maker_id):
    sports = []
    for run in data.latest_forecasts(conn).to_dict("records"):
        comp_id = int(data.q(conn, "SELECT id FROM competitions WHERE code = :c", c=run["competition"])["id"].iloc[0])
        targets = data.run_race_targets(conn, run["id"])
        targets = targets[targets["race_id"].notna() & ~targets["target"].astype(str).str.startswith("backtest:")]
        upcoming = [_card(conn, int(r), maker_id) for r in targets["race_id"].head(3)]
        later = [dict(title=f"{t['venue']} GP" if run["competition"] == "f1_wdc" else t["venue"], event_id=t["event_id"],
                      race_id=int(t["race_id"]), date=t["start_date"]) for t in targets.iloc[3:].to_dict("records")]
        s_info, s_pricing, s_df = season_matrix(conn, run["competition"], maker_id)
        from racinglines.web.views import latest_season_strategy
        season = dict(info=s_info, top=_top(s_df, "champion"), venues=venue_summary(s_df), mine=_mine(s_df),
                      outcomes=len(s_df), constructors=_top(s_df, "constructors_champion", 2),
                      strategy=latest_season_strategy(conn, run["competition"]))
        sports.append(dict(code=run["competition"], name=SPORT_NAME.get(run["competition"], run["competition_name"]),
                           run=run, upcoming=upcoming, later=later, season=season,
                           recent=recent_results(conn, comp_id)))
    sports.sort(key=lambda s: SPORT_ORDER.get(s["code"], 9))
    return sports


def headline(conn, maker_id):
    ex = data.q(conn, """
        SELECT count(*) AS outcomes, count(DISTINCT market_slug) AS markets,
               coalesce(sum(DISTINCT volume), 0) AS volume, max(synced_at) AS synced
        FROM market_links WHERE NOT closed AND prediction <> 'unmodeled'""").iloc[0]
    rec = data.q(conn, "SELECT max(ts) AS ts, count(DISTINCT token_id) AS n FROM market_book_snapshots "
                       "WHERE ts > now() - interval '10 minutes'").iloc[0]
    bk = house.book(conn, maker_id=maker_id, status="open")
    bt = data.q(conn, """SELECT metrics->'summary'->'pre_race|track=True' AS s FROM model_runs
                         WHERE kind = 'backtest' ORDER BY id DESC LIMIT 1""")
    s = bt["s"].iloc[0] if len(bt) else None
    jobs = data.q(conn, "SELECT count(*) FILTER (WHERE status IN ('queued', 'running')) AS active FROM jobs").iloc[0]
    return dict(outcomes=int(ex["outcomes"]), markets=int(ex["markets"]), volume=float(ex["volume"]), synced=ex["synced"],
                recording=int(rec["n"] or 0), recorded_at=rec["ts"],
                my_open=len(bk), my_worst=float(bk["worst"].sum()) if len(bk) else 0.0,
                my_staked=float(bk["staked"].sum()) if len(bk) else 0.0,
                bt_win=s.get("brier_win") if s else None, bt_grid=s.get("brier_win_grid") if s else None,
                jobs_active=int(jobs["active"]))
