"""
F1 race model: sector-aware car pace, driver offsets, grid/overtaking, Monte Carlo.

Everything is built in date order, so the features for a race only use data
from before that race (no look-ahead in backtests).

1. Measurements per past event (from the database)
   - qualifying: each driver's best clean lap, and each TEAM's best time in each
     of the 3 sectors, as a % deficit to the fastest in that sector;
   - race pace: each driver's median clean race lap (green flag, accurate timing,
     no pit in/out laps, not lap 1, within 107% of the field median), as a %
     deficit to the fastest driver's median;
   - track profile (track_profiles): sector time shares and speed-trap speeds.

2. Sector-type car model (the track/sector part)
   For each team, fit  sector_deficit = a + b * x  over its recent qualifying
   sectors, where x = (sector trap speed - 250) / 50. Positive b = the car loses
   more in fast sectors; negative b = it's relatively stronger there. Weighted by
   recency (half-life HALF_LIFE_DAYS), ridge-shrunk toward the field. At a
   target track the predicted team deficit is  a + b * x_track, with x_track the
   time-weighted sector speed of that venue (its earlier dry profiles). The same
   is done for race pace against the event-level x.

   The car is shared by both drivers: a team's sector deficit at an event is the
   average of its drivers' deficits (CAR_PACE = "mean"), so the car is not
   credited with the faster driver's pace and then again through that driver's
   offset.

3. Driver offsets vs teammate (qualifying and race pace), shrunk.

4. Finishing model (ridge regression, fit on earlier races): normalized finishing
   position from grid, predicted race pace, predicted qualifying pace, and their
   interactions with the track's overtaking ease (mean places gained at that
   venue) and street-circuit flag.

5. Simulation: grid (actual if qualifying is done, else simulated from qualifying
   pace + noise) -> finishing score + noise -> DNFs (team/driver reliability) ->
   positions and official points (race 25-18-..., sprint 8-7-...). Teammates share
   part of the noise (a car's good or bad weekend): the qualifying and finishing
   noise are split into a team part and a driver part, with the teammate
   correlation measured on earlier races (TEAMMATE_CORR).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import text

from racinglines.db.registry import STREET_CIRCUITS
from racinglines.core.stats import ranks

HALF_LIFE_DAYS = 120.0
RIDGE_A = 2.0          # prior weight (in "events") pulling team base pace to the field median
RIDGE_B = 6.0          # prior weight pulling the high-speed slope b to 0
DRIVER_PRIOR_N = 3.0   # driver-vs-teammate offset shrinkage
CAR_PACE = "mean"      # team sector pace from both drivers ("mean") or the team's best sectors ("best", old)
TEAMMATE_CORR = True   # share part of the qualifying/finishing noise between teammates
FINISH_RHO_SCALE = 1.0 # fraction of the measured teammate finishing correlation used in the simulation
X_CENTER, X_SCALE = 250.0, 50.0
RACE_POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
SPRINT_POINTS = {2021: [3, 2, 1]}
SPRINT_POINTS_DEFAULT = [8, 7, 6, 5, 4, 3, 2, 1]

# team lineage across renames, so history carries over
TEAM_ALIASES = {"racing_point": "aston_martin", "renault": "alpine", "toro_rosso": "rb", "alphatauri": "rb",
                "alfa": "sauber", "alfa_romeo": "sauber", "kick_sauber": "sauber", "audi": "sauber"}


def team_key(team_id):
    t = str(team_id or "").lower()
    return TEAM_ALIASES.get(t, t)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

RESULTS_SQL = """
SELECT e.id AS event_id, e.start_date, s.year, e.series_round, e.status AS event_status, v.slug AS venue,
       ra.id AS race_id, ro.kind AS round, r.athlete_id, a.display_name AS driver, r.position, r.status,
       r.time_ms, r.team, r.extra, ro.extra->>'session_date' AS session_ts
FROM results r JOIN rounds ro ON ro.id = r.round_id JOIN races ra ON ra.id = ro.race_id
JOIN events e ON e.id = ra.event_id JOIN seasons s ON s.id = e.season_id
JOIN competitions co ON co.id = s.competition_id LEFT JOIN venues v ON v.id = e.venue_id
JOIN athletes a ON a.id = r.athlete_id
WHERE co.code = 'f1_wdc'
"""

LAPS_SQL = """
SELECT ra.event_id, ro.kind AS round, r.athlete_id, l.lap, l.lap_time_ms, l.s1_ms, l.s2_ms, l.s3_ms,
       l.pit_in, l.pit_out, l.track_status, l.is_accurate, l.deleted, l.stint, ro.extra->>'session_date' AS session_ts
FROM laps l JOIN results r ON r.id = l.result_id JOIN rounds ro ON ro.id = r.round_id
JOIN races ra ON ra.id = ro.race_id JOIN events e ON e.id = ra.event_id JOIN seasons s ON s.id = e.season_id
JOIN competitions co ON co.id = s.competition_id
WHERE co.code = 'f1_wdc' AND ro.kind IN ('qual', 'race', 'fp1', 'fp2', 'fp3', 'sprint_qual')
"""

PROFILE_SQL = """
SELECT tp.event_id, e.start_date, v.slug AS venue, tp.features,
       (SELECT max(ro.extra->>'session_date') FROM rounds ro JOIN races ra ON ra.id = ro.race_id
         WHERE ra.event_id = tp.event_id) AS ready_ts   -- profile uses race results: usable once all sessions ran
FROM track_profiles tp JOIN events e ON e.id = tp.event_id LEFT JOIN venues v ON v.id = tp.venue_id
"""


def load_frames(engine):
    """The raw tables the model reads (results, laps, track profiles), straight from SQL."""
    with engine.connect() as c:
        return (pd.read_sql(text(RESULTS_SQL), c), pd.read_sql(text(LAPS_SQL), c), pd.read_sql(text(PROFILE_SQL), c))


def load(engine):
    return prepare(*load_frames(engine))


def prepare(res, laps, prof):
    """Typed, derived columns on the raw frames (team keys, timestamps, profile features)."""
    res, laps, prof = res.copy(), laps.copy(), prof.copy()
    extra = pd.json_normalize(res.pop("extra").fillna({}).tolist())
    for col in ("grid", "points", "team_id", "abbreviation"):
        res[col] = extra[col].to_numpy() if col in extra else None
    res["team_key"] = res["team_id"].map(team_key)
    # a few results lack a team id ("nan" in the source): recover it from the team name
    bad = res["team_key"].isin(["", "nan", "none"])
    if bad.any():
        by_name = res[~bad].groupby("team")["team_key"].agg(lambda k: k.mode().iloc[0])
        res.loc[bad, "team_key"] = res.loc[bad, "team"].map(by_name)
    res["start_date"] = pd.to_datetime(res["start_date"])
    res["session_ts"] = pd.to_datetime(res["session_ts"])
    laps["session_ts"] = pd.to_datetime(laps["session_ts"])
    prof["start_date"] = pd.to_datetime(prof["start_date"])
    prof["ready_ts"] = pd.to_datetime(prof["ready_ts"])
    prof = pd.concat([prof.drop(columns="features"), pd.json_normalize(prof["features"].tolist()).drop(
        columns=["venue"], errors="ignore")], axis=1)
    return res, laps, prof


# ---------------------------------------------------------------------------
# Per-event measurements
# ---------------------------------------------------------------------------

def event_measurements(res, laps, prof):
    """One row per (event, driver) with qualifying/race-pace deficits, plus one
    row per (event, team, sector) with sector deficits and trap speeds."""
    q = laps[(laps["round"] == "qual") & laps["lap_time_ms"].notna()].copy()
    q = q[~q["deleted"].fillna(False).astype(bool)]
    best = q.groupby(["event_id", "athlete_id"])["lap_time_ms"].min().rename("q_best").reset_index()
    best["q_def"] = best["q_best"] / best.groupby("event_id")["q_best"].transform("min") - 1
    secs = q.groupby(["event_id", "athlete_id"])[["s1_ms", "s2_ms", "s3_ms"]].min().reset_index()

    r = laps[(laps["round"] == "race") & laps["lap_time_ms"].notna()].copy()
    clean = (r["track_status"] == "1") & r["is_accurate"].fillna(False).astype(bool) & ~r["pit_in"].fillna(False) \
        & ~r["pit_out"].fillna(False) & (r["lap"] > 1)
    r = r[clean]
    r = r[r["lap_time_ms"] <= 1.07 * r.groupby("event_id")["lap_time_ms"].transform("median")]
    rp = r.groupby(["event_id", "athlete_id"])["lap_time_ms"].agg(["median", "count"]).reset_index()
    rp = rp[rp["count"] >= 8]
    rp["r_def"] = rp["median"] / rp.groupby("event_id")["median"].transform("min") - 1

    drivers = res[res["round"] == "race"][["event_id", "start_date", "year", "series_round", "venue", "race_id",
                                           "athlete_id", "driver", "team_key", "position", "status", "grid",
                                           "points", "session_ts"]].rename(columns={"session_ts": "r_ts"}).copy()
    q_ts = res[res["round"] == "qual"].groupby("event_id")["session_ts"].first()
    drivers["q_ts"] = drivers["event_id"].map(q_ts)
    drivers = drivers.merge(best[["event_id", "athlete_id", "q_def"]], on=["event_id", "athlete_id"], how="left")
    drivers = drivers.merge(rp[["event_id", "athlete_id", "r_def"]], on=["event_id", "athlete_id"], how="left")

    # team sector deficits (qualifying) + that event's trap speeds. The car is shared:
    # its deficit is the mean of its drivers' deficits (each vs the fastest driver
    # in that sector), matching driver offsets that are measured vs the team mean.
    sd = secs.merge(res[res["round"] == "qual"][["event_id", "athlete_id", "team_key"]], on=["event_id", "athlete_id"])
    rows = []
    speed_cols = {"s1_ms": "v_i1", "s2_ms": "v_i2", "s3_ms": "v_fl"}
    pmap = prof.set_index("event_id")
    for k, vcol in speed_cols.items():
        dd = sd[["event_id", "team_key", k]].dropna().copy()
        dd["def"] = dd[k] / dd.groupby("event_id")[k].transform("min") - 1
        dd = dd[dd["def"] < 0.08]                                   # aborted / red-flag laps
        t = dd.groupby(["event_id", "team_key"])["def"].agg("mean" if CAR_PACE == "mean" else "min").reset_index()
        if CAR_PACE != "mean":
            t["def"] = t["def"] - t.groupby("event_id")["def"].transform("min")
        t["v"] = t["event_id"].map(pmap[vcol]) if vcol in pmap else np.nan
        t["sector"] = k[:2]
        rows.append(t[["event_id", "team_key", "sector", "def", "v"]])
    sectors = pd.concat(rows, ignore_index=True).dropna()
    sectors = sectors[sectors["def"] < 0.08]  # drop red-flag / aborted-lap outliers
    sectors["q_ts"] = sectors["event_id"].map(q_ts)                 # usable once that qualifying has run
    sectors["start_date"] = sectors["q_ts"]
    return drivers, sectors


def venue_track_features(prof, venue, before):
    """Track features for a venue from its dry profiles before a date (median),
    falling back to the field median if the venue is new."""
    p = prof[(prof["ready_ts"] + RACE_DONE < before)]   # only profiles whose sessions (incl. the race) had all run
    dry = p[(p.get("qual_rain_share", pd.Series(0, index=p.index)).fillna(0) < 0.1)]
    v = dry[dry["venue"] == venue]
    base = dry if len(dry) else p
    def med(col, frame):
        return float(frame[col].median()) if col in frame and frame[col].notna().any() else np.nan
    x_parts = []
    src = v if len(v) else base
    for share, speed in (("s1_share", "v_i1"), ("s2_share", "v_i2"), ("s3_share", "v_fl")):
        x_parts.append(med(share, src) * (med(speed, src) - X_CENTER) / X_SCALE)
    x_track = float(np.nansum(x_parts)) if not all(np.isnan(x_parts)) else 0.0
    mpg = med("mean_places_gained", v) if len(v) else np.nan
    if np.isnan(mpg):
        mpg = med("mean_places_gained", base)
    return dict(x_track=x_track, ease=(mpg if not np.isnan(mpg) else 2.8) / 2.8,
                street=float(venue in STREET_CIRCUITS),
                venue_known=bool(len(v)))


# ---------------------------------------------------------------------------
# Rolling (walk-forward) estimates
# ---------------------------------------------------------------------------

PRACTICE_KINDS = ("fp1", "fp2", "fp3", "sprint_qual")
# a session's data is usable only once it has ended (a cutoff inside a session sees nothing of it)
SESSION_MINUTES = {"fp1": 60, "fp2": 60, "fp3": 60, "sprint_qual": 45, "qual": 60, "sprint": 45, "race": 150}
QUAL_DONE = pd.Timedelta(minutes=SESSION_MINUTES["qual"])
RACE_DONE = pd.Timedelta(minutes=SESSION_MINUTES["race"])


def session_end(round_kind, start):
    return start + pd.to_timedelta(pd.Series(round_kind).map(SESSION_MINUTES).fillna(150).to_numpy(), unit="m")
LONG_RUN_LAPS = 5


def practice_measurements(laps):
    """Per (event, practice session, driver): one-lap pace (best clean lap, % to the session's
    fastest) and long-run pace (median lap of stints with >= LONG_RUN_LAPS green laps, % to the
    best driver's). Sprint qualifying counts as a practice session here (it's before qualifying)."""
    p = laps[laps["round"].isin(PRACTICE_KINDS) & laps["lap_time_ms"].notna()].copy()
    if p.empty:
        return pd.DataFrame(columns=["event_id", "round", "athlete_id", "session_ts", "best_def", "long_def"])
    p = p[~p["deleted"].fillna(False).astype(bool)]
    p = p[p["lap_time_ms"] <= 1.07 * p.groupby(["event_id", "round"])["lap_time_ms"].transform("min")]
    key = ["event_id", "round", "athlete_id"]
    best = p.groupby(key).agg(best=("lap_time_ms", "min"), session_ts=("session_ts", "first")).reset_index()
    best["best_def"] = best["best"] / best.groupby(["event_id", "round"])["best"].transform("min") - 1
    g = p[(p["track_status"] == "1") & ~p["pit_in"].fillna(False).astype(bool) & ~p["pit_out"].fillna(False).astype(bool)]
    g = g[g.groupby(key + ["stint"])["lap"].transform("count") >= LONG_RUN_LAPS]
    lr = g.groupby(key)["lap_time_ms"].median().rename("long").reset_index()
    lr["long_def"] = lr["long"] / lr.groupby(["event_id", "round"])["long"].transform("min") - 1
    out = best.merge(lr[key + ["long_def"]], on=key, how="left")
    return out[["event_id", "round", "athlete_id", "session_ts", "best_def", "long_def"]]


def _weights(dates, now):
    age = (now - dates).dt.days.clip(lower=0).to_numpy(dtype=float)
    return 0.5 ** (age / HALF_LIFE_DAYS)


def fit_team_sector(sectors, now, use_track=True):
    """{team: (a, b)} from qualifying sector deficits before `now`."""
    s = sectors[sectors["q_ts"] + QUAL_DONE < now]
    if s.empty:
        return {}, 0.02
    w = _weights(s["start_date"], now)
    s = s.assign(w=w, x=(s["v"] - X_CENTER) / X_SCALE)
    a0 = float(np.average(s["def"], weights=s["w"]))
    out = {}
    for team, g in s.groupby("team_key"):
        W, x, y = g["w"].to_numpy(), g["x"].to_numpy(), g["def"].to_numpy()
        if not use_track:
            a = (np.sum(W * y) + RIDGE_A * a0) / (np.sum(W) + RIDGE_A)
            out[team] = (a, 0.0)
            continue
        # weighted ridge on [a, b] with priors a0, 0 (2x2 normal equations)
        A = np.array([[np.sum(W) + RIDGE_A, np.sum(W * x)], [np.sum(W * x), np.sum(W * x * x) + RIDGE_B]])
        rhs = np.array([np.sum(W * y) + RIDGE_A * a0, np.sum(W * x * y)])
        a, b = np.linalg.solve(A, rhs)
        out[team] = (float(a), float(b))
    return out, a0


def fit_team_race(drivers, xmap, now, use_track=True):
    """{team: (c, d)}: race-pace deficit vs the event's track x (event-level)."""
    d = drivers[(drivers["r_ts"] + RACE_DONE < now) & drivers["r_def"].notna()]
    if d.empty:
        return {}, 0.01
    t = d.groupby(["event_id", "team_key", "start_date"])["r_def"].mean().reset_index()
    t["x"] = t["event_id"].map(xmap).fillna(0.0)
    t["w"] = _weights(t["start_date"], now)
    c0 = float(np.average(t["r_def"], weights=t["w"]))
    out = {}
    for team, g in t.groupby("team_key"):
        W, x, y = g["w"].to_numpy(), g["x"].to_numpy(), g["r_def"].to_numpy()
        if not use_track:
            out[team] = ((np.sum(W * y) + RIDGE_A * c0) / (np.sum(W) + RIDGE_A), 0.0)
            continue
        A = np.array([[np.sum(W) + RIDGE_A, np.sum(W * x)], [np.sum(W * x), np.sum(W * x * x) + RIDGE_B]])
        rhs = np.array([np.sum(W * y) + RIDGE_A * c0, np.sum(W * x * y)])
        c, dd = np.linalg.solve(A, rhs)
        out[team] = (float(c), float(dd))
    return out, c0


def driver_offsets(drivers, col, now):
    """Driver deficit minus teammates' mean, recency-weighted and shrunk to 0."""
    ts, done = ("q_ts", QUAL_DONE) if col == "q_def" else ("r_ts", RACE_DONE)   # usable once that session has ended
    d = drivers[(drivers[ts] + done < now) & drivers[col].notna()].copy()
    if d.empty:
        return {}
    d["off"] = d[col] - d.groupby(["event_id", "team_key"])[col].transform("mean")
    d["w"] = _weights(d["start_date"], now)
    g = d.assign(wo=d["w"] * d["off"]).groupby("athlete_id")[["wo", "w"]].sum()
    return (g["wo"] / (g["w"] + DRIVER_PRIOR_N)).to_dict()


def dnf_rates(drivers, now, prior_n=10.0):
    d = drivers[drivers["r_ts"] + RACE_DONE < now]
    if d.empty:
        return {}, {}, 0.1
    d = d.assign(dnf=d["status"].isin(["DNF", "DSQ"]).astype(float), w=_weights(d["start_date"], now))
    p0 = float(np.average(d["dnf"], weights=d["w"]))
    tg = d.assign(wd=d["w"] * d["dnf"]).groupby("team_key")[["wd", "w"]].sum()
    team = ((tg["wd"] + prior_n * p0) / (tg["w"] + prior_n)).to_dict()
    return team, {}, p0


@dataclass
class Snapshot:
    """Everything known just before a date."""
    team_q: dict
    q0: float
    team_r: dict
    r0: float
    drv_q: dict
    drv_r: dict
    dnf_team: dict
    dnf0: float
    use_track: bool = True


def snapshot(drivers, sectors, xmap, now, use_track=True):
    team_q, q0 = fit_team_sector(sectors, now, use_track)
    team_r, r0 = fit_team_race(drivers, xmap, now, use_track)
    dnf_team, _, dnf0 = dnf_rates(drivers, now)
    return Snapshot(team_q, q0, team_r, r0, driver_offsets(drivers, "q_def", now),
                    driver_offsets(drivers, "r_def", now), dnf_team, dnf0, use_track)


def predict_paces(snap, entrants, tf):
    """entrants: DataFrame athlete_id, team_key. Adds qp (qualifying deficit),
    rp (race-pace deficit), p_dnf. Unknown teams get a slow default."""
    x = tf["x_track"] if snap.use_track else 0.0
    slow_q = max(v[0] for v in snap.team_q.values()) if snap.team_q else snap.q0
    slow_r = max(v[0] for v in snap.team_r.values()) if snap.team_r else snap.r0
    e = entrants.copy()
    e["qp"] = [snap.team_q.get(t, (slow_q, 0.0))[0] + snap.team_q.get(t, (slow_q, 0.0))[1] * x
               + snap.drv_q.get(a, 0.0) for a, t in zip(e["athlete_id"], e["team_key"])]
    e["rp"] = [snap.team_r.get(t, (slow_r, 0.0))[0] + snap.team_r.get(t, (slow_r, 0.0))[1] * x
               + snap.drv_r.get(a, 0.0) for a, t in zip(e["athlete_id"], e["team_key"])]
    e["p_dnf"] = [snap.dnf_team.get(t, snap.dnf0) for t in e["team_key"]]
    return e


# ---------------------------------------------------------------------------
# Walk-forward feature table + finishing model
# ---------------------------------------------------------------------------

FEATURES = ["g", "g_ease", "rp_rel", "rp_ease", "qp_rel", "street_g"]


def design(df, tf, use_track=True):
    n = len(df)
    g = df["grid_used"].fillna(n).clip(lower=1)
    g = g.where(g > 0, n)
    out = pd.DataFrame(index=df.index)
    out["g"] = (g - 1) / max(n - 1, 1)
    out["rp_rel"] = (df["rp"] - df["rp"].min()) * 100
    out["qp_rel"] = (df["qp"] - df["qp"].min()) * 100
    ease = tf["ease"] if use_track else 1.0
    street = tf["street"] if use_track else 0.0
    out["g_ease"] = out["g"] * (ease - 1)
    out["rp_ease"] = out["rp_rel"] * (ease - 1)
    out["street_g"] = out["g"] * street
    return out[FEATURES]


def event_x(prof):
    """Track x for each past event from its own profile (known once it has run)."""
    x = sum(prof[share].fillna(1 / 3) * (prof[speed] - X_CENTER) / X_SCALE
            for share, speed in (("s1_share", "v_i1"), ("s2_share", "v_i2"), ("s3_share", "v_fl"))
            if share in prof and speed in prof)
    return dict(zip(prof["event_id"], pd.Series(x).fillna(0.0)))


@dataclass
class FinishModel:
    coef: np.ndarray
    intercept: float
    sigma: float
    sigma_q: float
    use_track: bool = True
    rho_q: float = 0.0     # teammate correlation of qualifying noise
    rho_f: float = 0.0     # teammate correlation of finishing noise


def fit_finish(hist, before, use_track=True, alpha=1.0):
    """Ridge on earlier races' classified finishers: normalized finish ~ FEATURES."""
    from sklearn.linear_model import Ridge
    h = hist[(hist["r_ts"] + RACE_DONE < before)]   # only races whose results were known at the cutoff
    fin = h[h["status"] == "OK"].copy()
    n = fin.groupby("event_id")["athlete_id"].transform("count")
    fin["y"] = (fin["position"] - 1) / (n - 1).clip(lower=1)
    w = _weights(fin["start_date"], before) + 0.05
    X = fin[FEATURES].fillna(0.0)
    if not use_track:
        X = X.assign(g_ease=0.0, rp_ease=0.0, street_g=0.0)
    m = Ridge(alpha=alpha).fit(X, fin["y"], sample_weight=w)
    resid = fin["y"] - m.predict(X)
    q = h[h["q_def"].notna()]
    qcol = "qp_nopr" if "qp_nopr" in q else "qp"      # grid noise without practice (the prior sets its own)
    sigma_q = float(np.sqrt(np.average((q["q_def"] - q[qcol]) ** 2, weights=_weights(q["start_date"], before) + 0.05)))
    rho_q = rho_f = 0.0
    if TEAMMATE_CORR:
        rho_q = teammate_corr(q.assign(r=q["q_def"] - q[qcol]), "r")
        rho_f = teammate_corr(fin.assign(r=resid), "r") * FINISH_RHO_SCALE
    return FinishModel(m.coef_, float(m.intercept_), float(np.sqrt(np.average(resid ** 2, weights=w))), sigma_q,
                       use_track, rho_q, rho_f)


def teammate_corr(df, col, lo=0.0, hi=0.9):
    """Correlation of teammates' residuals in the same event (both cars present)."""
    d = df[df[col].notna()]
    d = d[d.groupby(["event_id", "team_key"])[col].transform("count") == 2].sort_values(["event_id", "team_key", "athlete_id"])
    if len(d) < 40:
        return 0.0
    a = d.groupby(["event_id", "team_key"])[col].agg(["first", "last"])
    r = a["first"].corr(a["last"])
    return float(np.clip(r, lo, hi)) if pd.notna(r) else 0.0


def _noise(rng, sigma, rho, teams, n_sims):
    """(n_sims, n) normal noise with sd `sigma`, correlation `rho` between drivers of the same team."""
    n = len(teams)
    if rho <= 0:
        return rng.normal(0, sigma, (n_sims, n))
    uniq = {t: i for i, t in enumerate(dict.fromkeys(teams))}
    shared = rng.normal(0, 1, (n_sims, len(uniq)))[:, [uniq[t] for t in teams]]
    return sigma * (np.sqrt(rho) * shared + np.sqrt(1 - rho) * rng.normal(0, 1, (n_sims, n)))


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

# Season-level pace drift (fraction of lap time), estimated from how much a team's
# race-pace prediction error persists into its next race (lag-1 correlation x variance):
# team ~0.30 %, driver-vs-teammate ~0.06 % (2020-21 + 2025-26 data). Applied as one
# random shift per simulated season, shared by all remaining races.
TEAM_DRIFT_SD = 0.0030
DRIVER_DRIFT_SD = 0.0006


def season_drift(e, n_sims, rng, team_sd=TEAM_DRIFT_SD, driver_sd=DRIVER_DRIFT_SD):
    """(n_sims, n) pace shift per simulated season (same order as e)."""
    teams = e["team_key"].astype(str).to_numpy()
    uniq = {t: i for i, t in enumerate(dict.fromkeys(teams))}
    team_shock = rng.normal(0, team_sd, (n_sims, len(uniq)))[:, [uniq[t] for t in teams]]
    return team_shock + rng.normal(0, driver_sd, (n_sims, len(teams)))


def simulate_race(fm, e, tf, n_sims=10000, rng=None, grid_known=False, points=RACE_POINTS, pace_shock=None):
    """e: entrants with qp, rp, p_dnf (and grid if grid_known). pace_shock: optional
    (n_sims, n) shift of both qualifying and race pace (see season_drift). Returns
    dict of (n_sims, n) arrays: pos (finishing position, DNFs last), dnf, points, grid."""
    rng = rng or np.random.default_rng(0)
    n = len(e)
    shock = pace_shock if pace_shock is not None else 0.0
    qp = e["qp"].to_numpy()[None, :] + shock
    rp = e["rp"].to_numpy()[None, :] + shock
    teams = e["team_key"].astype(str).to_numpy()
    if grid_known:
        grid = np.tile(e["grid"].fillna(n).replace(0, n).to_numpy(float), (n_sims, 1))
    else:
        q = qp + _noise(rng, fm.sigma_q, fm.rho_q, teams, n_sims)
        grid = ranks(q).astype(float)
    g = (grid - 1) / max(n - 1, 1)
    rp_rel = (rp - rp.min(axis=1, keepdims=True)) * 100
    qp_rel = (qp - qp.min(axis=1, keepdims=True)) * 100
    ease = (tf["ease"] - 1) if fm.use_track else 0.0
    street = tf["street"] if fm.use_track else 0.0
    feats = {"g": g, "g_ease": g * ease, "rp_rel": rp_rel, "rp_ease": rp_rel * ease, "qp_rel": qp_rel,
             "street_g": g * street}
    score = fm.intercept + sum(c * feats[f] for c, f in zip(fm.coef, FEATURES))
    score = score + _noise(rng, fm.sigma, fm.rho_f, teams, n_sims)
    dnf = rng.random((n_sims, n)) < e["p_dnf"].to_numpy()[None, :]
    score = np.where(dnf, 10 + rng.random((n_sims, n)), score)
    pos = ranks(score)
    pts = np.zeros((n_sims, n))
    for p, v in enumerate(points, start=1):
        pts += (pos == p) * v
    pts = np.where(dnf, 0, pts)
    return dict(pos=pos, dnf=dnf, points=pts, grid=grid)


def summarize(e, sim):
    pos, dnf = sim["pos"], sim["dnf"]
    return pd.DataFrame(dict(
        athlete_id=e["athlete_id"].to_numpy(), driver=e["driver"].to_numpy() if "driver" in e else None,
        team_key=e["team_key"].to_numpy(),
        win_prob=((pos == 1) & ~dnf).mean(0), podium_prob=((pos <= 3) & ~dnf).mean(0),
        top10_prob=((pos <= 10) & ~dnf).mean(0), pole_prob=(sim["grid"] == 1).mean(0),
        dnf_prob=dnf.mean(0), exp_points=sim["points"].mean(0),
        exp_position=pos.mean(0),
        qp=e["qp"].to_numpy(), rp=e["rp"].to_numpy(),
    )).sort_values("win_prob", ascending=False).reset_index(drop=True)
