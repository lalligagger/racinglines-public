"""
F1 race props (F1 roadmap F1-3): safety car, red flag, rain and fastest lap, priced from the race history in
the database. Off by default: nothing prices them unless a live event lists their kinds ([live.markets] kinds
in sports/f1.toml or a launch spec).

    race_safety_car            a safety car is deployed in the race (track status 4 on any lap; a VSC alone is NO)
    race_red_flag              the race is red-flagged (track status 5 on any lap)
    race_rain                  rain falls during the race (any weather sample with rainfall: rounds.extra.weather)
    race_fastest_lap:<athlete> the driver sets the race's fastest lap (the quickest timed lap, deleted laps left out)

The three yes/no props are per-circuit rates shrunk to the field's rate: the field rate counts as PRIOR_N races
against a circuit's own record, over every race finished before the event starts. Rain uses the history only:
no weather forecast. Measured walk-forward on 2022-2026 (107 races, `--check`): a circuit's own record doesn't
beat the field rate within the noise (lighter shrinkage, e.g. 4, was worse), so PRIOR_N is a heavy 16.

Fastest lap: from history, how often the fastest lap goes to a driver finishing 1st, 2nd-3rd, 4th-10th, lower,
or not finishing (per driver in that bucket); a driver's price is his bucket probabilities from the stage run
(win, podium, top 10, DNF) times those rates, scaled so the field sums to 1.

    racinglines f1 props 2026-16                  # the prices for an event
    racinglines f1 props --check --from 2022      # walk-forward calibration of the yes/no props
"""

import numpy as np
import pandas as pd
from sqlalchemy import text

PROP_KINDS = ("race_safety_car", "race_red_flag", "race_rain", "race_fastest_lap")
BINARY = {"race_safety_car": "sc", "race_red_flag": "red", "race_rain": "rain"}
LABEL = {"race_safety_car": "Safety car", "race_red_flag": "Red flag", "race_rain": "Rain",
         "race_fastest_lap": "Fastest lap"}
PRIOR_N = 16.0                # the field rate counts as this many races against a circuit's own record
FL_BUCKETS = ("p1", "p2_3", "p4_10", "p11", "dnf")
FL_SMOOTH = 0.5               # fastest laps added to each bucket (and spread over its driver slots) before rates


def history(conn, before=None):
    """Per finished race (with timed laps) before `before` (a date; None: all): race_id, event_key, venue_id,
    start (date), sc, red, rain (bools), rain_share, fl_athlete, fl_bucket, n_ok, n_dnf."""
    df = pd.read_sql(text("""
        WITH rl AS (
            SELECT ro.race_id, r.athlete_id, r.position, r.status, l.lap_time_ms, l.deleted, l.track_status
            FROM laps l JOIN results r ON r.id = l.result_id JOIN rounds ro ON ro.id = r.round_id
            WHERE ro.kind = 'race'),
        st AS (SELECT race_id, bool_or(coalesce(track_status, '') LIKE '%4%') AS sc,
                      bool_or(coalesce(track_status, '') LIKE '%5%') AS red FROM rl GROUP BY race_id),
        fl AS (SELECT DISTINCT ON (race_id) race_id, athlete_id AS fl_athlete, position AS fl_pos, status AS fl_status
               FROM rl WHERE lap_time_ms IS NOT NULL AND NOT coalesce(deleted, false)
               ORDER BY race_id, lap_time_ms, athlete_id),
        cl AS (SELECT ro.race_id, count(*) FILTER (WHERE r.status = 'OK') AS n_ok,
                      count(*) FILTER (WHERE r.status IN ('DNF', 'DSQ')) AS n_dnf,
                      max((ro.extra->'weather'->>'rain_share')::float) AS rain_share
               FROM results r JOIN rounds ro ON ro.id = r.round_id WHERE ro.kind = 'race' GROUP BY ro.race_id)
        SELECT st.race_id, e.source_key AS event_key, e.venue_id, e.start_date AS start, st.sc, st.red,
               coalesce(cl.rain_share, 0) AS rain_share, fl.fl_athlete, fl.fl_pos, fl.fl_status, cl.n_ok, cl.n_dnf
        FROM st JOIN races ra ON ra.id = st.race_id JOIN events e ON e.id = ra.event_id
        JOIN cl ON cl.race_id = st.race_id LEFT JOIN fl ON fl.race_id = st.race_id
        WHERE e.source = 'f1timing' AND (CAST(:b AS date) IS NULL OR e.start_date < CAST(:b AS date))
        ORDER BY e.start_date, st.race_id"""), conn, params=dict(b=None if before is None else str(pd.Timestamp(before).date())))
    df["rain"] = df["rain_share"] > 0
    df["fl_bucket"] = [_bucket(p, s) for p, s in zip(df["fl_pos"], df["fl_status"])]
    return df


def _bucket(pos, status):
    if status is None or (isinstance(status, float) and np.isnan(status)):
        return None
    if status != "OK":
        return "dnf"
    return "p1" if pos == 1 else "p2_3" if pos <= 3 else "p4_10" if pos <= 10 else "p11"


def rate(hist, venue_id, col, prior_n=PRIOR_N):
    """P(YES) for a yes/no prop at a venue: its own record shrunk to the field rate (None with no history)."""
    if hist.empty:
        return None
    field = float(hist[col].mean())
    v = hist.loc[hist["venue_id"] == venue_id, col]
    return float((v.sum() + prior_n * field) / (len(v) + prior_n))


def fl_rates(hist):
    """{bucket: P(fastest lap) per driver in that bucket} from history (smoothed)."""
    h = hist.dropna(subset=["fl_bucket"])
    slots = dict(p1=len(h), p2_3=2.0 * len(h), p4_10=7.0 * len(h),
                 p11=float((h["n_ok"] - 10).clip(lower=0).sum()), dnf=float(h["n_dnf"].sum()))
    n = h["fl_bucket"].value_counts()
    base = len(h) / (sum(slots.values()) or 1.0)          # the per-slot rate over every bucket
    if base == 0:
        return {b: 1.0 for b in FL_BUCKETS}
    return {b: float((n.get(b, 0) + FL_SMOOTH) / (slots[b] + FL_SMOOTH / base)) for b in FL_BUCKETS}


def fl_probs(preds, rates):
    """P(driver sets the fastest lap) from each driver's win / podium / top-10 / DNF probabilities; sums to 1."""
    win = preds["win_prob"].fillna(0).to_numpy(float)
    pod = np.maximum(preds["podium_prob"].fillna(0).to_numpy(float), win)
    top = preds["top10_prob"] if "top10_prob" in preds else pd.Series(np.nan, index=preds.index)
    top = np.maximum(top.fillna(pd.Series(np.minimum(1, pod * 10 / 3), index=preds.index)).to_numpy(float), pod)
    dnf = preds["dnf_prob"] if "dnf_prob" in preds else pd.Series(0.0, index=preds.index)
    dnf = np.clip(dnf.fillna(0).to_numpy(float), 0, 1 - top)
    b = dict(p1=win, p2_3=pod - win, p4_10=top - pod, p11=np.clip(1 - top - dnf, 0, 1), dnf=dnf)
    raw = sum(b[k] * rates[k] for k in FL_BUCKETS)
    return raw / raw.sum() if raw.sum() > 0 else np.full(len(raw), 1 / max(len(raw), 1))


def event_info(conn, event_key):
    """(venue_id, first day) of an F1 event."""
    row = conn.execute(text("SELECT venue_id, start_date FROM events WHERE source = 'f1timing' AND source_key = :k"),
                       dict(k=event_key)).first()
    return (None, None) if row is None else (row[0], row[1])


def run_preds(conn, run_id):
    """A stage run's per-driver probabilities for the fastest-lap price: athlete_id, driver, win_prob,
    podium_prob, top10_prob, dnf_prob."""
    df = pd.read_sql(text("""SELECT athlete_id, win_prob, podium_prob, top10_prob, extra->>'driver' AS driver,
                                    (extra->>'dnf_prob')::float AS dnf_prob
                             FROM race_predictions WHERE model_run_id = :r ORDER BY win_prob DESC, athlete_id"""),
                     conn, params=dict(r=run_id))
    return df


def market_set(preds, venue_id, hist, kinds=PROP_KINDS, prior_n=PRIOR_N):
    """The prop markets and their fair values (live_f1.market_set's shape): [dict(key, kind, athlete_id,
    params, subject, fair)]."""
    out = []
    for kind, col in BINARY.items():
        if kind in kinds:
            out.append(dict(key=kind, kind=kind, athlete_id=None, params=None, subject=LABEL[kind],
                            fair=rate(hist, venue_id, col, prior_n)))
    if "race_fastest_lap" in kinds and len(preds) and not hist.empty:
        p = fl_probs(preds, fl_rates(hist))
        for r, v in zip(preds.itertuples(), p):
            out.append(dict(key=f"race_fastest_lap:{int(r.athlete_id)}", kind="race_fastest_lap",
                            athlete_id=int(r.athlete_id), params=None, subject=r.driver, fair=float(v)))
    return out


def markets(conn, event_key, run_id, kinds=PROP_KINDS, prior_n=PRIOR_N):
    """The event's prop markets from the race history before it and a stage run (fastest lap)."""
    venue_id, start = event_info(conn, event_key)
    hist = history(conn, start)
    preds = run_preds(conn, run_id) if "race_fastest_lap" in kinds and run_id is not None else pd.DataFrame()
    return market_set(preds, venue_id, hist, kinds, prior_n)


def outcomes(conn, race_id, mkts):
    """{key: True / False} for the prop markets, from the race's laps and weather; {} until the race has laps."""
    h = history(conn)
    h = h[h["race_id"] == race_id]
    if h.empty:
        return {}
    r = h.iloc[0]
    out = {}
    for m in mkts:
        if m["kind"] in BINARY:
            out[m["key"]] = bool(r[BINARY[m["kind"]]])
        elif m["kind"] == "race_fastest_lap" and pd.notna(r["fl_athlete"]):
            out[m["key"]] = int(r["fl_athlete"]) == m["athlete_id"]
    return out


def check(conn, start_year=2022, prior_n=PRIOR_N):
    """Walk-forward calibration of the yes/no props: each race from `start_year` priced from the races before
    it, against the field rate alone and a coin flip. -> (per-race DataFrame, summary DataFrame: Brier and log
    loss per prop and method, with the mean YES rate and mean price)."""
    h = history(conn)
    rows = []
    for r in h[pd.to_datetime(h["start"]).dt.year >= start_year].itertuples():
        past = h[h["start"] < r.start]
        if len(past) < 10:
            continue
        for kind, col in BINARY.items():
            y = bool(getattr(r, col))
            rows.append(dict(event_key=r.event_key, kind=kind, y=y, circuit=rate(past, r.venue_id, col, prior_n),
                             field=float(past[col].mean()), coin=0.5))
    per = pd.DataFrame(rows)
    out = []
    for kind, g in per.groupby("kind", sort=False):
        y = g["y"].astype(float).to_numpy()
        for meth in ("circuit", "field", "coin"):
            p = np.clip(g[meth].to_numpy(float), 1e-4, 1 - 1e-4)
            out.append(dict(kind=kind, method=meth, races=len(g), yes_rate=y.mean(), mean_price=p.mean(),
                            brier=float(((p - y) ** 2).mean()),
                            log_loss=float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()),
                            se=float(((p - y) ** 2).std(ddof=1) / np.sqrt(len(g)))))
    return per, pd.DataFrame(out)
