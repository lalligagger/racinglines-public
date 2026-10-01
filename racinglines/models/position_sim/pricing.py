"""
F1 pricing, backtesting and forecasting, with a hard as-of boundary.

ONE pricing function, used everywhere:

    price_race(meas, hist, cutoff, event_id)   fair prices for one race, using only
                                               data from sessions that STARTED before `cutoff`

and three drivers of it that never mix:

    backtest(...)      historical: cutoff = just before each past race's qualifying
                       ("pre_quali") or just before its race ("pre_race"); scored
                       against outcomes read separately after pricing.
    diagnostic(...)    one past event at a chosen cutoff (e.g. "yesterday"), scored
                       against the outcome and compared with exchange prices *at that cutoff*.
    forecast(...)      live: cutoff = now; prices upcoming races + the championship.

Leakage guards:
  - Measurements.view(cutoff) is the only way pricing code gets data; it filters
    every table by session start time and asserts nothing at/after the cutoff
    remains (LeakageError otherwise). Track profiles (which use race results)
    are only usable after all of that event's sessions have run.
  - Per-race measurements (qualifying gaps, race pace, sector gaps) depend only
    on that race's own session, so computing them once is safe; they are
    time-stamped and filtered by the view.
  - The finishing model is trained only on races whose results were known at
    the cutoff, each row with features computed as of just before that race.
  - The grid is the QUALIFYING order (in the view), not the official grid
    stored with race results; grid penalties are therefore ignored.
  - Exchange (Polymarket) prices never enter fitting or pricing. They are only
    compared with our prices after the fact.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from racinglines.models import outcomes as O
from racinglines.models.position_sim import model as M
from racinglines.core.stats import brier, ranks

ONE_MIN = pd.Timedelta(minutes=1)
PRE_WEEKEND, PRE_QUALI, PRE_RACE = "pre_weekend", "pre_quali", "pre_race"


class LeakageError(AssertionError):
    pass


def _naive(ts):
    ts = pd.Timestamp(ts)
    return ts.tz_convert("UTC").tz_localize(None) if ts.tzinfo else ts


@dataclass
class Measurements:
    res: pd.DataFrame        # results rows (all sessions), with session_ts
    prof: pd.DataFrame       # track profiles, with ready_ts
    drivers: pd.DataFrame    # per race x driver: outcome, q_def, r_def, r_ts, q_ts
    sectors: pd.DataFrame    # per qualifying x team x sector: deficit, trap speed, q_ts
    practice: pd.DataFrame = None   # per practice session x driver: best_def, long_def, session_ts
    cutoff: pd.Timestamp | None = None
    xmap: dict = field(default_factory=dict)
    audit: dict = field(default_factory=dict)
    races: pd.DataFrame = None      # per past race: safety car / red flag / rain, disrupted (model.race_disruption)

    @classmethod
    def load(cls, engine):
        return cls.from_frames(*M.load_frames(engine))

    @classmethod
    def from_frames(cls, res, laps, prof):
        """From the raw SQL frames (see position_sim.model.load_frames), e.g. pinned test fixtures."""
        res, laps, prof = M.prepare(res, laps, prof)
        drivers, sectors = M.event_measurements(res, laps, prof)
        return cls(res, prof, drivers, sectors, M.practice_measurements(laps), None, M.event_x(prof),
                   races=M.race_disruption(laps, prof))

    def view(self, cutoff):
        """Everything knowable strictly before `cutoff` (session start times, UTC)."""
        cutoff = _naive(cutoff)
        prof = self.prof[self.prof["ready_ts"] + M.RACE_DONE < cutoff]
        v = Measurements(
            res=self.res[M.session_end(self.res["round"], self.res["session_ts"]) < cutoff],
            prof=prof,
            drivers=self.drivers[self.drivers["r_ts"] + M.RACE_DONE < cutoff],
            sectors=self.sectors[self.sectors["q_ts"] + M.QUAL_DONE < cutoff],
            practice=self.practice[M.session_end(self.practice["round"], self.practice["session_ts"]) < cutoff],
            cutoff=cutoff,
            xmap={k: x for k, x in self.xmap.items() if k in set(prof["event_id"])},
            races=None if self.races is None else self.races[self.races["r_ts"] + M.RACE_DONE < cutoff])
        v.audit = assert_no_leak(v, cutoff)
        return v

    def sessions(self, event_id):
        s = self.res[self.res["event_id"] == event_id].groupby("round")["session_ts"].first()
        return {k: s.get(k) for k in ("fp1", "fp2", "fp3", "sprint_qual", "qual", "sprint", "race")}


def assert_no_leak(v, cutoff):
    """Every session in the view must have ENDED before the cutoff. Reports the latest session starts."""
    ends = {"results": M.session_end(v.res["round"], v.res["session_ts"]).max() if len(v.res) else None,
            "race measurements": v.drivers["r_ts"].max() + M.RACE_DONE if len(v.drivers) else None,
            "qualifying sectors": v.sectors["q_ts"].max() + M.QUAL_DONE if len(v.sectors) else None,
            "track profiles": v.prof["ready_ts"].max() + M.RACE_DONE if len(v.prof) else None,
            "practice": M.session_end(v.practice["round"], v.practice["session_ts"]).max()
            if v.practice is not None and len(v.practice) else None}
    if v.races is not None and len(v.races):
        ends["race disruption"] = v.races["r_ts"].max() + M.RACE_DONE
    for what, ts in ends.items():
        if ts is not None and pd.notna(ts) and ts >= cutoff:
            raise LeakageError(f"{what}: a session ending {ts} is not over before the cutoff {cutoff}")
    latest = {"results": v.res["session_ts"].max(), "race measurements": v.drivers["r_ts"].max(),
              "qualifying sectors": v.sectors["q_ts"].max(), "track profiles": v.prof["ready_ts"].max(),
              "practice": v.practice["session_ts"].max() if v.practice is not None and len(v.practice) else None}
    return {k: (None if t is None or pd.isna(t) else str(t)) for k, t in latest.items()}


# ---------------------------------------------------------------------------
# Training rows for the finishing model
# ---------------------------------------------------------------------------

def entry_list(meas, event_id):
    """Drivers entered for an event (from the qualifying classification, which lists
    every entrant). Only identities and teams are used, never results."""
    q = meas.res[(meas.res["event_id"] == event_id) & (meas.res["round"] == "qual")]
    if q.empty:
        q = meas.res[(meas.res["event_id"] == event_id) & (meas.res["round"] == "race")]
    return q[["athlete_id", "driver", "team_key"]].drop_duplicates("athlete_id").reset_index(drop=True)


def qualifying_grid(view, event_id, entrants):
    """Grid = qualifying classification from the as-of view (None if qualifying hasn't run)."""
    q = view.res[(view.res["event_id"] == event_id) & (view.res["round"] == "qual")]
    if q.empty:
        return None
    pos = q.set_index("athlete_id")["position"].astype(float)
    return entrants["athlete_id"].map(pos).fillna(len(entrants)).to_numpy(float)


def history(meas, use_track=True):
    """One row per entrant per completed race, with features computed as of one
    minute before that race's start (qualifying known) and its outcome."""
    from racinglines.models.position_sim import practice as PR
    ptrain = PR.training_rows(meas, use_track) if PR.USE_PRACTICE else pd.DataFrame()
    rows = []
    events = meas.drivers.drop_duplicates("event_id").sort_values("r_ts")
    for ev in events.itertuples():
        cutoff = ev.r_ts - ONE_MIN
        v = meas.view(cutoff)
        snap = M.snapshot(v.drivers, v.sectors, v.xmap if use_track else {}, cutoff, use_track)
        if not snap.team_q:
            continue
        tf = M.venue_track_features(v.prof, ev.venue, cutoff)
        ent = entry_list(meas, ev.event_id)
        e = M.predict_paces(snap, ent, tf)
        e["qp_nopr"] = e["qp"]                    # before the practice prior (for the no-practice grid noise)
        e_nopr = e.copy()
        e, _ = PR.apply(e, v.practice, ev.event_id, PR.fit(ptrain, cutoff))
        grid = qualifying_grid(v, ev.event_id, ent)
        e["grid_used"] = grid if grid is not None else np.nan
        if M.PRE_PRACTICE_TRAIN:                  # the same features from paces before the practice prior
            nopr = M.design(e_nopr.assign(grid_used=e["grid_used"].to_numpy()), tf, use_track)
            e = pd.concat([e, nopr.add_suffix("_nopr")], axis=1)
        outcome_rows = meas.drivers[meas.drivers["event_id"] == ev.event_id].drop(columns=["team_key", "driver"])
        e = e.merge(outcome_rows, on="athlete_id", how="left")
        e["status"] = e["status"].fillna("DNS")
        e[["event_id", "r_ts", "start_date", "year", "venue"]] = e[["event_id", "r_ts", "start_date", "year", "venue"]].ffill().bfill()
        e = pd.concat([e, M.design(e, tf, use_track)], axis=1)
        for k, val in tf.items():
            e[f"tf_{k}"] = val
        e["cutoff"] = cutoff
        if meas.races is not None:
            e["disrupted"] = bool(meas.races.set_index("event_id")["disrupted"].get(ev.event_id, False))
        rows.append(e)
    out = pd.concat(rows, ignore_index=True)
    out.attrs["practice_train"] = ptrain
    return out


# ---------------------------------------------------------------------------
# The pricing function
# ---------------------------------------------------------------------------

def price_race(meas, hist, cutoff, event_id, n_sims=10000, rng=None, use_track=True, entrants=None,
               venue=None, points=M.RACE_POINTS):
    """Fair prices for one race using only data from before `cutoff`.

    Returns (summary, extras): summary has per-driver win/podium/top10/pole/DNF
    probabilities, expected points and head-to-head probabilities; extras has the
    per-team top-scorer probabilities, the leakage audit, track features and model."""
    rng = rng if rng is not None else np.random.default_rng(0)
    v = meas.view(cutoff)
    if entrants is None:
        entrants = entry_list(meas, event_id)
    if venue is None:
        venue = meas.res.loc[meas.res["event_id"] == event_id, "venue"].iloc[0]
    snap = M.snapshot(v.drivers, v.sectors, v.xmap if use_track else {}, v.cutoff, use_track)
    tf = M.venue_track_features(v.prof, venue, v.cutoff)
    e = M.predict_paces(snap, entrants, tf).reset_index(drop=True)
    from racinglines.models.position_sim import practice as PR
    e, sigma_q = PR.apply(e, v.practice, event_id, PR.fit(hist.attrs.get("practice_train"), v.cutoff))
    grid = qualifying_grid(v, event_id, e) if event_id is not None else None
    fm = M.fit_finish(hist, v.cutoff, use_track, no_practice=M.PRE_PRACTICE_TRAIN and sigma_q is None,
                      grid_known=grid is not None)
    if sigma_q is not None:
        from dataclasses import replace as _replace
        fm = _replace(fm, sigma_q=sigma_q)
    if grid is not None:
        e["grid"] = grid
    chaos_p = M.chaos_prob(hist, venue, v.cutoff, fm.chaos["p"]) if fm.chaos else None
    sim = M.simulate_race(fm, e, tf, n_sims=n_sims, rng=rng, grid_known=grid is not None, points=points,
                          chaos_p=chaos_p)
    summ = M.summarize(e, sim)
    ids = e["athlete_id"].tolist()
    h2h = (sim["pos"][:, :, None] < sim["pos"][:, None, :]).mean(0)
    summ["h2h"] = summ["athlete_id"].map({a: {str(b): round(float(h2h[i, j]), 4) for j, b in enumerate(ids) if b != a}
                                         for i, a in enumerate(ids)})
    teams = sorted(set(e["team_key"]))
    tpts = np.zeros((n_sims, len(teams)))
    np.add.at(tpts.T, np.array([teams.index(t) for t in e["team_key"]]), sim["points"].T)
    top = np.argmax(tpts + rng.random(tpts.shape) * 1e-3, axis=1)
    sessions = meas.sessions(event_id) if event_id is not None else {}
    extras = dict(constructor_top={t: float((top == i).mean()) for i, t in enumerate(teams)},
                  audit=dict(cutoff=str(v.cutoff), latest_data=v.audit,
                             event_sessions={k: (None if ts is None or pd.isna(ts) else str(ts)) for k, ts in sessions.items()},
                             sessions_used=[k for k, ts in sessions.items() if ts is not None and pd.notna(ts) and ts < v.cutoff],
                             grid="qualifying order" if grid is not None else "simulated from qualifying pace",
                             practice_prior=sigma_q is not None,
                             training_races=int(hist.loc[hist["r_ts"] + M.RACE_DONE < v.cutoff, "event_id"].nunique())),
                  track=tf, sim=sim, entrants=e, model=fm)
    return summ, extras


# ---------------------------------------------------------------------------
# Backtest (historical only)
# ---------------------------------------------------------------------------

def _logloss(p, y, eps=1e-4):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def grid_baseline(hist, before, max_grid=22, prior=2.0):
    """Empirical P(win / podium / top 10 | qualifying position) from races known before `before`."""
    h = hist[(hist["r_ts"] + M.RACE_DONE < before) & hist["grid_used"].notna()]
    g = h["grid_used"].astype(int).clip(1, max_grid)
    ok = h["status"] == "OK"
    out = {}
    for k, lim in (("win", 1), ("podium", 3), ("top10", 10)):
        y = (ok & (h["position"] <= lim)).astype(float)
        base = y.mean()
        stats = y.groupby(g).agg(["sum", "count"])
        out[k] = ((stats["sum"] + prior * base) / (stats["count"] + prior)).reindex(range(1, max_grid + 1)).fillna(base)
    return out


def outcome(meas, event_id, athlete_ids):
    """Actual result for scoring (read only after pricing)."""
    o = meas.drivers[meas.drivers["event_id"] == event_id].set_index("athlete_id")
    status = pd.Series(athlete_ids).map(o["status"]).fillna("DNS").to_numpy()
    pos = pd.Series(athlete_ids).map(o["position"]).to_numpy(float)
    ok = status == "OK"
    return dict(status=status, position=pos, win=ok & (pos <= 1), podium=ok & (pos <= 3), top10=ok & (pos <= 10))


def backtest(meas, hist, start_year=2021, n_sims=4000, use_track=True, modes=(PRE_WEEKEND, PRE_QUALI, PRE_RACE), seed=0,
             echo=None, last_n=None, keep_probs=False):
    """One row per race x mode with Brier / log-loss scores. keep_probs: also keep each
    driver's win / podium / top-10 probability and outcome (column `pred`), for
    reliability curves (position_sim/evaluate.py)."""
    rng = np.random.default_rng(seed)
    rows = []
    events = meas.drivers[meas.drivers["year"] >= start_year].drop_duplicates("event_id").sort_values("r_ts")
    if last_n:
        events = events.tail(last_n)
    for i, ev in enumerate(events.itertuples(), 1):
        sessions = meas.sessions(ev.event_id)
        for mode in modes:
            if mode == PRE_WEEKEND:     # before the first practice session (events with practice data only)
                pr = [sessions.get(k) for k in ("fp1", "fp2", "fp3", "sprint_qual")]
                pr = [t for t in pr if t is not None and pd.notna(t)]
                anchor = min(pr) if pr else None
            else:
                anchor = sessions.get("qual") if mode == PRE_QUALI else sessions.get("race")
            if anchor is None or pd.isna(anchor):
                continue
            cutoff = anchor - ONE_MIN
            if not (hist["r_ts"] + M.RACE_DONE < cutoff).any():
                continue
            summ, ex = price_race(meas, hist, cutoff, ev.event_id, n_sims=n_sims, rng=rng, use_track=use_track)
            y = outcome(meas, ev.event_id, summ["athlete_id"].tolist())       # scored AFTER pricing
            n = len(summ)
            ok = y["status"] == "OK"
            row = dict(event_id=ev.event_id, year=ev.year, round=ev.series_round, venue=ev.venue, mode=mode,
                       cutoff=str(cutoff), n=n, training_races=ex["audit"]["training_races"],
                       winner=summ.loc[y["win"], "driver"].squeeze() if y["win"].any() else None,
                       winner_prob=float(summ["win_prob"].to_numpy()[y["win"]].sum()),
                       favourite=summ.loc[summ["win_prob"].idxmax(), "driver"],
                       spearman=float(pd.Series(summ["exp_position"].to_numpy()[ok]).rank().corr(
                           pd.Series(y["position"][ok]).rank())))
            row.update(_teammate_scores(meas, ev.event_id, summ, ex))
            if keep_probs:
                row["pred"] = {**{k: summ[f"{k}_prob"].round(5).tolist() for k in ("win", "podium", "top10")},
                               **{f"y_{k}": y[k].astype(int).tolist() for k in ("win", "podium", "top10")}}
            gb = grid_baseline(hist, cutoff) if mode == PRE_RACE else None
            for k, share in (("win", 1), ("podium", 3), ("top10", 10)):
                row[f"brier_{k}"] = brier(summ[f"{k}_prob"], y[k])
                row[f"logloss_{k}"] = _logloss(summ[f"{k}_prob"], y[k])
                row[f"brier_{k}_uniform"] = brier(np.full(n, share / n), y[k])
                if gb is not None:
                    g = pd.Series(summ["athlete_id"]).map(dict(zip(ex["entrants"]["athlete_id"], ex["entrants"]["grid"])))
                    row[f"brier_{k}_grid"] = brier(g.fillna(n).clip(1, 22).astype(int).map(gb[k]).to_numpy(), y[k])
            rows.append(row)
        if echo:
            echo(f"progress {i}/{len(events)} {ev.year} R{ev.series_round:02d} {ev.venue}")
    return pd.DataFrame(rows)


def _teammate_scores(meas, event_id, summ, ex):
    """Brier of teammate head-to-heads (who finishes ahead; a DNF is behind) and of the
    top-scoring constructor, both scored after pricing."""
    o = meas.drivers[meas.drivers["event_id"] == event_id].set_index("athlete_id")
    out = {}
    pairs = []
    for team, g in summ.groupby("team_key"):
        if len(g) != 2:
            continue
        a, b = g["athlete_id"].tolist()
        sa, sb = o["status"].get(a), o["status"].get(b)
        if sa is None or sb is None or (sa != "OK" and sb != "OK"):
            continue
        pa = o["position"].get(a) if sa == "OK" else 99
        pb = o["position"].get(b) if sb == "OK" else 99
        p = (summ.loc[summ["athlete_id"] == a, "h2h"].iloc[0] or {}).get(str(b))
        if p is not None and pa != pb:
            pairs.append((p, float(pa < pb)))
    if pairs:
        p, y = np.array(pairs).T
        out["brier_teammate_h2h"] = float(np.mean((p - y) ** 2))
        out["teammate_pairs"] = len(pairs)
    pts = o.groupby("team_key")["points"].sum() if "points" in o else None
    ct = ex.get("constructor_top") or {}
    if pts is not None and len(pts) and ct and (pts == pts.max()).sum() == 1:
        top = pts.idxmax()
        out["brier_constructor_top"] = float(np.mean([(ct.get(t, 0.0) - float(t == top)) ** 2 for t in ct]))
    return out


def summarize_backtest(bt):
    cols = [c for c in bt.columns if c.startswith(("brier_", "logloss_"))] + ["winner_prob", "spearman"]
    return bt.groupby("mode")[cols].mean()


# ---------------------------------------------------------------------------
# Diagnostic: one past event priced at a chosen cutoff
# ---------------------------------------------------------------------------

def diagnostic(meas, hist, event_key, cutoff, n_sims=10000, seed=42, use_track=True):
    """Price one completed event as of `cutoff`, then (separately) read its result."""
    year, rnd = (int(x) for x in event_key.split("-"))
    ev = meas.res[(meas.res["year"] == year) & (meas.res["series_round"] == rnd)]
    if ev.empty:
        raise ValueError(f"no event {event_key}")
    event_id = int(ev["event_id"].iloc[0])
    summ, ex = price_race(meas, hist, cutoff, event_id, n_sims=n_sims, rng=np.random.default_rng(seed),
                          use_track=use_track)
    y = outcome(meas, event_id, summ["athlete_id"].tolist())
    result = pd.DataFrame(dict(athlete_id=summ["athlete_id"], status=y["status"], position=y["position"]))
    return event_id, summ, ex, result


# ---------------------------------------------------------------------------
# Live forecast (cutoff = now)
# ---------------------------------------------------------------------------

def upcoming_schedule(year):
    """Season schedule from FastF1 (dates/venues/sprint flags only, no results)."""
    import logging

    import fastf1
    from racinglines.sources.fastf1.fetch import CACHE, SPRINT_FORMATS
    logging.getLogger("fastf1").setLevel(logging.ERROR)
    CACHE.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE))
    s = fastf1.get_event_schedule(year, include_testing=False)
    return pd.DataFrame(dict(round=s["RoundNumber"].astype(int), name=s["EventName"], official=s["OfficialEventName"],
                             location=s["Location"], date=pd.to_datetime(s["EventDate"]),
                             sprint=s["EventFormat"].astype(str).isin(SPRINT_FORMATS)))


def estimate_drift(hist, cutoff):
    """Season-level pace drift (fraction of lap) from races known before `cutoff`:
    how much a team's / driver's race-pace prediction error persists into the next race."""
    h = hist[(hist["r_ts"] + M.RACE_DONE < cutoff) & hist["r_def"].notna()]
    t = h.groupby(["event_id", "r_ts", "team_key"]).agg(pred=("rp", "mean"), act=("r_def", "mean")).reset_index()
    t["err"] = t["act"] - t["pred"]
    t = t.sort_values(["team_key", "r_ts"])
    t["nxt"] = t.groupby("team_key")["err"].shift(-1)
    t = t.dropna()
    team_sd = float(np.sqrt(max(t["err"].corr(t["nxt"]), 0) * t["err"].var())) if len(t) > 20 else M.TEAM_DRIFT_SD
    d = h.assign(err=h["r_def"] - h["rp"])
    d["drv"] = d["err"] - d.groupby(["event_id", "team_key"])["err"].transform("mean")
    d = d.sort_values(["athlete_id", "r_ts"])
    d["nxt"] = d.groupby("athlete_id")["drv"].shift(-1)
    d = d.dropna(subset=["nxt"])
    drv_sd = float(np.sqrt(max(d["drv"].corr(d["nxt"]), 0) * d["drv"].var())) if len(d) > 20 else M.DRIVER_DRIFT_SD
    return team_sd, drv_sd


def forecast(meas, hist, year, cutoff=None, n_sims=10000, seed=42, schedule=None, use_track=True, field=None,
             race_prices=True):
    """Live pricing: every not-yet-raced round of `year` and the championships, using
    data before `cutoff` (default now, UTC). Per-race prices come from the same
    price_race used in backtests (no drift); season totals add an as-of drift.
    field: the entrants to simulate (default: the last raced event's classification in
    the as-of view); race_prices=False skips per-race prices (championships only)."""
    rng = np.random.default_rng(seed)
    cutoff = _naive(cutoff if cutoff is not None else pd.Timestamp.now(tz="UTC"))
    v = meas.view(cutoff)
    season_res = v.res[v.res["year"] == year]
    raced = set(season_res.loc[season_res["round"] == "race", "series_round"])
    schedule = schedule if schedule is not None else upcoming_schedule(year)
    remaining = schedule[~schedule["round"].isin(raced)].sort_values("round")
    last = v.drivers.sort_values("r_ts")["event_id"].iloc[-1]
    field_ = field if field is not None else entry_list(v, last)
    team_sd, drv_sd = estimate_drift(hist, cutoff)

    pts_now = season_res.groupby("athlete_id")["points"].sum().astype(float)
    wins_now = season_res[(season_res["round"] == "race") & (season_res["status"] == "OK")
                          & (season_res["position"] == 1)].groupby("athlete_id").size()
    team_now = season_res.groupby("team_key")["points"].sum().astype(float)
    ids = list(dict.fromkeys(list(pts_now.index) + list(field_["athlete_id"])))
    col = {a: i for i, a in enumerate(ids)}
    teams = sorted(set(team_now.index) | set(field_["team_key"]))
    tcol = {t: i for i, t in enumerate(teams)}
    total = np.tile(pts_now.reindex(ids).fillna(0).to_numpy(), (n_sims, 1))
    wins = np.tile(wins_now.reindex(ids).fillna(0).to_numpy(float), (n_sims, 1))
    team_total = np.tile(team_now.reindex(teams).fillna(0).to_numpy(), (n_sims, 1))
    drift = M.season_drift(field_, n_sims, rng, team_sd, drv_sd)
    fm = M.fit_finish(hist, cutoff, no_practice=M.PRE_PRACTICE_TRAIN, grid_known=False)   # future races: no practice, no grid
    snap = M.snapshot(v.drivers, v.sectors, v.xmap, cutoff)
    per_event, race_constructor_top = [], {}
    from racinglines.db.ingest import _slugify
    for ev in remaining.itertuples():
        venue = _slugify(ev.location)
        ev_rows = meas.res[(meas.res["year"] == year) & (meas.res["series_round"] == ev.round)]
        event_id = int(ev_rows["event_id"].iloc[0]) if len(ev_rows) else None
        entrants = entry_list(v, event_id) if event_id is not None and len(entry_list(v, event_id)) else field_
        if race_prices:
            # published race prices: the backtested single-race model (no season drift)
            summ, ex = price_race(meas, hist, cutoff, event_id, n_sims=n_sims, rng=rng, entrants=entrants, venue=venue,
                                  use_track=use_track)
            race_constructor_top[f"{year}-{ev.round:02d}"] = ex["constructor_top"]
            tf = ex["track"]
        else:
            summ, tf = None, M.venue_track_features(v.prof, venue, v.cutoff)
        # season totals: same model plus a season-long pace drift shared across the remaining races
        e = M.predict_paces(snap, field_, tf).reset_index(drop=True)
        idx = [col[a] for a in e["athlete_id"]]
        tidx = np.array([tcol[t] for t in e["team_key"]])
        for pts in [M.RACE_POINTS] + ([M.SPRINT_POINTS.get(year, M.SPRINT_POINTS_DEFAULT)] if ev.sprint else []):
            s = M.simulate_race(fm, e, tf, n_sims=n_sims, rng=rng, grid_known=False, points=pts, pace_shock=drift,
                                chaos_p=M.chaos_prob(hist, venue, cutoff, fm.chaos["p"]) if fm.chaos else None)
            total[:, idx] += s["points"]
            if pts is M.RACE_POINTS:
                wins[:, idx] += (s["pos"] == 1) & ~s["dnf"]
            tp = np.zeros((n_sims, len(teams)))
            np.add.at(tp.T, tidx, s["points"].T)
            team_total += tp
        if race_prices:
            per_event.append(dict(round=ev.round, name=ev.name, official=ev.official, location=ev.location, venue=venue,
                                  date=ev.date, sprint=bool(ev.sprint), grid_known=ex["audit"]["grid"] == "qualifying order",
                                  track=tf, summary=summ))
            if records_enabled():         # prediction records: keep the event's simulations for save_forecast
                from racinglines.core import stages as STG
                per_event[-1]["outcome"] = dict(sims=O.from_position_sim(ex["entrants"], ex["sim"]),
                                                stage=STG.spec("f1")["pre_label"], cutoff=cutoff, archive=True)

    rank = ranks(-(total + rng.random(total.shape) * 1e-3))
    ahead = (rank[:, :, None] < rank[:, None, :]).mean(0)
    names = meas.res.drop_duplicates("athlete_id", keep="last").set_index("athlete_id")["driver"]
    standings = pd.DataFrame(dict(
        athlete_id=ids, driver=[names.get(a, a) for a in ids], current_points=pts_now.reindex(ids).fillna(0).to_numpy(),
        exp_points=total.mean(0), points_p10=np.percentile(total, 10, 0), points_p90=np.percentile(total, 90, 0),
        champion_prob=(rank == 1).mean(0), top3_prob=(rank <= 3).mean(0), top10_prob=(rank <= 10).mean(0),
        exp_rank=rank.mean(0)))
    standings["extra"] = [dict(
        wins_now=int(wins_now.get(a, 0)), exp_wins=round(float(wins[:, i].mean()), 3),
        wins_ge={str(k): round(float((wins[:, i] >= k).mean()), 4) for k in range(1, 11)},
        ahead_of={str(b): round(float(ahead[i, j]), 4) for j, b in enumerate(ids) if b != a})
        for i, a in enumerate(ids)]
    standings = standings.sort_values("exp_points", ascending=False).reset_index(drop=True)
    standings["current_rank"] = standings["current_points"].rank(ascending=False, method="min")
    trank = ranks(-(team_total + rng.random(team_total.shape) * 1e-3))
    team_names = meas.res.sort_values("start_date").drop_duplicates("team_key", keep="last").set_index("team_key")["team"]
    constructors = pd.DataFrame(dict(
        team_key=teams, team=[team_names.get(t, t) for t in teams], current_points=team_now.reindex(teams).fillna(0).to_numpy(),
        exp_points=team_total.mean(0), champion_prob=(trank == 1).mean(0), top3_prob=(trank <= 3).mean(0),
        exp_rank=trank.mean(0))).sort_values("exp_points", ascending=False).reset_index(drop=True)
    extras = dict(constructors=constructors, race_constructor_top=race_constructor_top, cutoff=str(cutoff),
                  latest_data=v.audit, drift=dict(team_sd=team_sd, driver_sd=drv_sd), model=fm)
    return per_event, standings, extras


def save_forecast(engine_url, year, per_event, standings, params, metrics, kind="forecast"):
    """Create scheduled events/races for upcoming rounds (if missing) and store the run."""
    from datetime import date as _date

    from sqlalchemy import select

    from racinglines.db import models as m
    from racinglines.db.config import get_session
    from racinglines.db.ingest import _upsert, resolve_venue
    from racinglines.db.queries import save_model_run

    preds, event_ids = [], {}
    with get_session(engine_url) as s:
        comp = s.scalars(select(m.Competition).filter_by(code="f1_wdc")).one()
        cat = s.scalars(select(m.Category).filter_by(competition_id=comp.id, code="DRV")).one()
        season = _upsert(s, m.Season, dict(competition_id=comp.id, year=year))
        for ev in per_event:
            key = f"{year}-{ev['round']:02d}"
            event = s.scalars(select(m.Event).filter_by(season_id=season.id, source="f1timing", source_key=key)).first()
            if event is None:
                venue = resolve_venue(s, ev["location"])
                event = m.Event(season_id=season.id, source="f1timing", source_key=key, name=ev["official"] or ev["name"],
                                start_date=pd.Timestamp(ev["date"]).date(), venue_id=venue.id, series_round=ev["round"],
                                status="scheduled")
                s.add(event)
                s.flush()
            event_ids[key] = event.id
            race = _upsert(s, m.Race, dict(event_id=event.id, category_id=cat.id))
            if race.format is None:
                race.format = dict(kind="f1", sprint=ev["sprint"], event_name=ev["name"])
            elif ev["name"] and race.format.get("event_name") != ev["name"]:     # repair a stale name
                race.format = dict(race.format, event_name=ev["name"])
            s.commit()
            preds.append(ev["summary"].assign(rider_id=lambda d: "ath:" + d["athlete_id"].astype(str),
                                              target=ev.get("target", f"event:{key}"), race_id=race.id,
                                              make_final_prob=None))
    with get_session(engine_url) as s:
        run_id = save_model_run(
            s, competition="f1_wdc", season=year, category="DRV", model="f1_sector_sim", kind=kind,
            data_through=_date.today(), params=params, metrics=metrics,
            race_predictions=pd.concat(preds, ignore_index=True) if preds else None,
            standings=standings.assign(rider_id=lambda d: "ath:" + d["athlete_id"].astype(str)) if standings is not None else None)
    if records_enabled():
        _write_records(run_id, year, per_event, event_ids)
    return run_id


def records_enabled():
    from racinglines.db import records as REC
    return REC.enabled()


def _write_records(run_id, year, per_event, event_ids):
    """Prediction records beside race_predictions (racinglines/db/records.py): per event that kept its
    simulations. Only forecasts and scenarios archive the sims (D3); a stage (diagnostic) run stays light."""
    from racinglines.db import records as REC
    frames, archive = [], {}
    for ev in per_event:
        oc = ev.get("outcome")
        if not oc:
            continue
        key = f"{year}-{ev['round']:02d}"
        frames.append(oc["sims"].to_records(run_id, "f1", "f1_sector_sim", year, event_ids.get(key), key, oc["stage"],
                                            oc["cutoff"]))
        if oc.get("archive"):
            archive[key] = oc["sims"]
    df = REC.concat(frames)
    if df is not None:
        REC.write(run_id, df, sims=archive or None)


def save_diagnostic(engine_url, event_key, cutoff, summ, ex, sims, **extra_params):
    """Store one as-of pricing of a past event as kind='diagnostic'."""
    year, rnd = (int(x) for x in event_key.split("-"))
    params = dict(event_key=event_key, cutoff=str(cutoff), sims=sims, mode="as-of diagnostic",
                  coef=[float(c) for c in ex["model"].coef], sigma=ex["model"].sigma,
                  half_life_days=M.HALF_LIFE_DAYS, **extra_params)
    metrics = dict(audit=ex["audit"], track={k: float(v) for k, v in ex["track"].items()},
                   race_constructor_top={event_key: ex["constructor_top"]})
    per_event = [dict(round=rnd, name=None, official=None, location=None, date=None, sprint=False, summary=summ,
                      target=f"asof:{event_key}")]
    if records_enabled():             # stage runs write records but never archive the sims (D3)
        per_event[0]["outcome"] = dict(sims=O.from_position_sim(ex["entrants"], ex["sim"]), archive=False,
                                       stage=extra_params.get("sweep_stage", "asof"), cutoff=cutoff)
    return save_forecast(engine_url, year, per_event, None, params, metrics, kind="diagnostic")
