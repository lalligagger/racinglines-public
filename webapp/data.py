"""Read-side queries for the admin app. Each returns a pandas DataFrame or dict."""

import pandas as pd
from sqlalchemy import text


def q(conn, sql, **params):
    return pd.read_sql(text(sql), conn, params=params)


def latest_forecasts(conn):
    """Latest forecast run per competition x category."""
    return q(conn, """
        SELECT DISTINCT ON (mr.competition_id, mr.category_id)
               mr.id, mr.created_at, mr.data_through, mr.code_version, co.code AS competition,
               co.name AS competition_name, c.code AS category, c.name AS category_name, s.year AS season
        FROM model_runs mr
        JOIN competitions co ON co.id = mr.competition_id
        LEFT JOIN categories c ON c.id = mr.category_id
        LEFT JOIN seasons s ON s.id = mr.season_id
        WHERE mr.kind = 'forecast'
        ORDER BY mr.competition_id, mr.category_id, mr.id DESC""")


def run_race_targets(conn, run_id):
    """Distinct prediction targets in a run, with event info when linked to a race."""
    return q(conn, """
        SELECT rp.target, rp.race_id, e.id AS event_id, e.name AS event_name, e.start_date, e.status,
               v.name AS venue, count(*) AS n
        FROM race_predictions rp
        LEFT JOIN races ra ON ra.id = rp.race_id
        LEFT JOIN events e ON e.id = ra.event_id
        LEFT JOIN venues v ON v.id = e.venue_id
        WHERE rp.model_run_id = :run
        GROUP BY 1, 2, 3, 4, 5, 6, 7
        ORDER BY e.start_date NULLS LAST, rp.target""", run=run_id)


def race_predictions(conn, run_id, target, limit=None):
    df = q(conn, f"""
        SELECT a.id AS athlete_id, a.display_name AS athlete, a.nation, rp.win_prob, rp.podium_prob,
               rp.top10_prob, rp.make_final_prob, rp.exp_points, rp.extra
        FROM race_predictions rp JOIN athletes a ON a.id = rp.athlete_id
        WHERE rp.model_run_id = :run AND rp.target = :target
        ORDER BY rp.win_prob DESC NULLS LAST, rp.exp_points DESC NULLS LAST
        {'LIMIT :limit' if limit else ''}""", run=run_id, target=target, limit=limit)
    extra = pd.json_normalize(df.pop("extra").fillna({}).tolist()) if len(df) else pd.DataFrame()
    for col in ("attend_prob", "actual_final_rank", "actual_points"):
        if col in extra:
            df[col] = extra[col].to_numpy()
    return df


def standings_predictions(conn, run_id, limit=None):
    return q(conn, f"""
        SELECT a.id AS athlete_id, a.display_name AS athlete, sp.current_points, sp.exp_points,
               sp.points_p10, sp.points_p90, sp.champion_prob, sp.top3_prob, sp.top10_prob, sp.exp_rank
        FROM standings_predictions sp JOIN athletes a ON a.id = sp.athlete_id
        WHERE sp.model_run_id = :run
        ORDER BY sp.exp_points DESC {'LIMIT :limit' if limit else ''}""", run=run_id, limit=limit)


def model_runs(conn, kind=None):
    return q(conn, """
        SELECT mr.id, mr.created_at, mr.kind, mr.model, co.code AS competition, s.year AS season,
               c.code AS category, mr.data_through, mr.code_version,
               (SELECT count(*) FROM race_predictions rp WHERE rp.model_run_id = mr.id) AS race_preds,
               (SELECT count(*) FROM standings_predictions sp WHERE sp.model_run_id = mr.id) AS standings_rows
        FROM model_runs mr JOIN competitions co ON co.id = mr.competition_id
        LEFT JOIN seasons s ON s.id = mr.season_id LEFT JOIN categories c ON c.id = mr.category_id
        WHERE (CAST(:kind AS text) IS NULL OR mr.kind = CAST(:kind AS text))
        ORDER BY mr.id DESC""", kind=kind)


def model_run(conn, run_id):
    df = q(conn, """
        SELECT mr.*, co.code AS competition, s.year AS season, c.code AS category_code
        FROM model_runs mr JOIN competitions co ON co.id = mr.competition_id
        LEFT JOIN seasons s ON s.id = mr.season_id LEFT JOIN categories c ON c.id = mr.category_id
        WHERE mr.id = :run""", run=run_id)
    return df.iloc[0].to_dict() if len(df) else None


def events(conn, competition=None, season=None):
    return q(conn, """
        SELECT e.id, s.year AS season, e.start_date, e.name, v.name AS venue, v.country, e.series_round,
               e.status, e.source_key,
               (SELECT count(*) FROM races ra WHERE ra.event_id = e.id) AS races
        FROM events e JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
        LEFT JOIN venues v ON v.id = e.venue_id
        WHERE (CAST(:comp AS text) IS NULL OR co.code = CAST(:comp AS text)) AND (CAST(:season AS int) IS NULL OR s.year = CAST(:season AS int))
        ORDER BY e.start_date DESC""", comp=competition, season=season)


def event(conn, event_id):
    df = q(conn, """
        SELECT e.*, s.year AS season, v.name AS venue, v.country, co.code AS competition
        FROM events e JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
        LEFT JOIN venues v ON v.id = e.venue_id WHERE e.id = :id""", id=event_id)
    return df.iloc[0].to_dict() if len(df) else None


def event_results(conn, event_id):
    return q(conn, """
        SELECT ra.id AS race_id, c.code AS category, ro.kind AS round, ro.ordinal, r.position, a.id AS athlete_id,
               a.display_name AS athlete, r.nation, r.team, r.status, r.time_ms / 1000.0 AS time_s
        FROM results r JOIN rounds ro ON ro.id = r.round_id JOIN races ra ON ra.id = ro.race_id
        JOIN categories c ON c.id = ra.category_id JOIN athletes a ON a.id = r.athlete_id
        WHERE ra.event_id = :id
        ORDER BY c.code, ro.ordinal, r.position NULLS LAST, a.display_name""", id=event_id)


def event_predictions(conn, event_id):
    """Every stored prediction for this event's races, newest run first, with the actual Final result."""
    return q(conn, """
        SELECT rp.model_run_id AS run, mr.kind, mr.created_at, c.code AS category, a.id AS athlete_id,
               a.display_name AS athlete, rp.win_prob, rp.podium_prob, rp.top10_prob, rp.make_final_prob,
               rp.exp_points, fin.position AS actual_final_pos
        FROM race_predictions rp JOIN model_runs mr ON mr.id = rp.model_run_id
        JOIN races ra ON ra.id = rp.race_id JOIN categories c ON c.id = ra.category_id
        JOIN athletes a ON a.id = rp.athlete_id
        LEFT JOIN rounds fr ON fr.race_id = ra.id AND fr.kind = 'final'
        LEFT JOIN results fin ON fin.round_id = fr.id AND fin.athlete_id = rp.athlete_id
        WHERE ra.event_id = :id
        ORDER BY rp.model_run_id DESC, rp.win_prob DESC NULLS LAST""", id=event_id)


def athletes(conn, search=None, limit=200):
    return q(conn, """
        SELECT a.id, a.display_name AS athlete, a.nation, count(r.id) AS results,
               max(e.start_date) AS last_race,
               count(*) FILTER (WHERE ro.kind = 'final' AND r.position = 1) AS wins
        FROM athletes a
        LEFT JOIN results r ON r.athlete_id = a.id LEFT JOIN rounds ro ON ro.id = r.round_id
        LEFT JOIN races ra ON ra.id = ro.race_id LEFT JOIN events e ON e.id = ra.event_id
        WHERE (CAST(:s AS text) IS NULL OR a.display_name ILIKE '%' || CAST(:s AS text) || '%')
        GROUP BY a.id ORDER BY last_race DESC NULLS LAST, results DESC LIMIT :limit""", s=search, limit=limit)


def athlete(conn, athlete_id):
    df = q(conn, "SELECT * FROM athletes WHERE id = :id", id=athlete_id)
    if not len(df):
        return None
    out = df.iloc[0].to_dict()
    out["identifiers"] = q(conn, "SELECT scheme, value FROM athlete_identifiers WHERE athlete_id = :id",
                           id=athlete_id).to_dict("records")
    return out


def athlete_results(conn, athlete_id):
    return q(conn, """
        SELECT e.id AS event_id, e.start_date, v.name AS venue, c.code AS category, ro.kind AS round,
               r.position, r.status, r.time_ms / 1000.0 AS time_s, r.team
        FROM results r JOIN rounds ro ON ro.id = r.round_id JOIN races ra ON ra.id = ro.race_id
        JOIN events e ON e.id = ra.event_id JOIN categories c ON c.id = ra.category_id
        LEFT JOIN venues v ON v.id = e.venue_id
        WHERE r.athlete_id = :id AND ro.kind <> 'practice'
        ORDER BY e.start_date DESC, ro.ordinal DESC""", id=athlete_id)


def athlete_predictions(conn, athlete_id):
    return q(conn, """
        SELECT rp.model_run_id AS run, mr.kind, mr.created_at, rp.target, e.id AS event_id,
               v.name AS venue, rp.win_prob, rp.podium_prob, rp.top10_prob, rp.make_final_prob, rp.exp_points
        FROM race_predictions rp JOIN model_runs mr ON mr.id = rp.model_run_id
        LEFT JOIN races ra ON ra.id = rp.race_id LEFT JOIN events e ON e.id = ra.event_id
        LEFT JOIN venues v ON v.id = e.venue_id
        WHERE rp.athlete_id = :id ORDER BY rp.model_run_id DESC, rp.target""", id=athlete_id)


def market_links(conn):
    return q(conn, """
        SELECT ml.*, a.display_name AS athlete, e.name AS event_name, v.name AS venue, co.code AS competition,
               c.code AS category
        FROM market_links ml JOIN athletes a ON a.id = ml.athlete_id
        JOIN competitions co ON co.id = ml.competition_id LEFT JOIN categories c ON c.id = ml.category_id
        LEFT JOIN races ra ON ra.id = ml.race_id LEFT JOIN events e ON e.id = ra.event_id
        LEFT JOIN venues v ON v.id = e.venue_id
        ORDER BY ml.active DESC, ml.id DESC""")


PREDICTION_COLUMNS = {
    "race_win": "win_prob", "race_podium": "podium_prob", "race_top10": "top10_prob",
    "race_make_final": "make_final_prob", "champion": "champion_prob", "standings_top3": "top3_prob",
}


def _id(v):
    """Row values from pandas: NaN -> None, numpy ints -> int."""
    return None if v is None or pd.isna(v) else int(v)


def model_prob(conn, link):
    """(probability, model_run_id) for a market link from the latest forecast
    run of its competition/category; inverted for "No"-type tokens."""
    col = PREDICTION_COLUMNS[link["prediction"]]
    link = dict(link, competition_id=_id(link.get("competition_id")), category_id=_id(link.get("category_id")),
                athlete_id=_id(link.get("athlete_id")), race_id=_id(link.get("race_id")))
    run = q(conn, """
        SELECT id FROM model_runs WHERE kind = 'forecast' AND competition_id = :comp
          AND (CAST(:cat AS int) IS NULL OR category_id = CAST(:cat AS int)) ORDER BY id DESC LIMIT 1""",
            comp=link["competition_id"], cat=link.get("category_id"))
    if not len(run):
        return None, None
    run_id = int(run["id"].iloc[0])
    if link["prediction"] in ("champion", "standings_top3"):
        df = q(conn, f"SELECT {col} AS p FROM standings_predictions WHERE model_run_id = :run AND athlete_id = :a",
               run=run_id, a=link["athlete_id"])
    elif link.get("race_id"):
        df = q(conn, f"""SELECT {col} AS p FROM race_predictions
                         WHERE model_run_id = :run AND athlete_id = :a AND race_id = :race""",
               run=run_id, a=link["athlete_id"], race=link["race_id"])
    else:
        df = q(conn, f"""SELECT {col} AS p FROM race_predictions
                         WHERE model_run_id = :run AND athlete_id = :a AND target = 'remaining_round'""",
               run=run_id, a=link["athlete_id"])
    if not len(df) or pd.isna(df["p"].iloc[0]):
        return None, run_id  # athlete not in this run's predictions (e.g. not on the start list)
    p = float(df["p"].iloc[0])
    return (1 - p if link["invert"] else p), run_id


def orders(conn, limit=200):
    return q(conn, """
        SELECT o.*, ml.question, ml.outcome, a.display_name AS athlete
        FROM orders o LEFT JOIN market_links ml ON ml.id = o.market_link_id
        LEFT JOIN athletes a ON a.id = ml.athlete_id
        ORDER BY o.id DESC LIMIT :limit""", limit=limit)


def upcoming_races(conn):
    """Races of events that aren't completed yet (for linking markets)."""
    return q(conn, """
        SELECT ra.id AS race_id, e.name AS event_name, v.name AS venue, e.start_date, c.code AS category,
               co.id AS competition_id, c.id AS category_id
        FROM races ra JOIN events e ON e.id = ra.event_id JOIN categories c ON c.id = ra.category_id
        JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
        LEFT JOIN venues v ON v.id = e.venue_id
        WHERE e.status <> 'completed' ORDER BY e.start_date, c.code""")
