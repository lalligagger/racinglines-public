"""
Practice-pace prior: update the model's qualifying and race pace with what the
weekend's practice sessions showed, like downhill's timed-training prior.

Training rows (one per past event x driver), all as of 1 minute before the event's
first practice session, so the model's prediction contains nothing from that weekend:
    qp_pre, rp_pre           the model's predicted qualifying / race-pace deficit
    best_k, long_k           practice one-lap and long-run deficits after the first k sessions
    q_def, r_def             what happened (qualifying deficit, race-pace deficit)

Blend (fit per k, only on events whose race finished before the cutoff, recency-weighted):
    q_def ~ a + b * qp_pre + c * best_k          -> new qp, and a smaller grid noise
    r_def ~ a + b * rp_pre + c * long_k          -> new rp
With fewer than MIN_EVENTS training events for a k, the model is left unchanged.
"""

import numpy as np
import pandas as pd

from racinglines.models.position_sim import model as M

USE_PRACTICE = True
MIN_EVENTS = 6
CLIP = 0.05      # deficits beyond 5% are crashes / aborted laps, not pace
ONE_MIN = pd.Timedelta(minutes=1)


def session_features(prac, event_id):
    """(k, best, long): sessions seen, and each driver's best one-lap deficit / mean long-run deficit."""
    p = prac[prac["event_id"] == event_id] if prac is not None and len(prac) else None
    if p is None or p.empty:
        return 0, pd.Series(dtype=float), pd.Series(dtype=float)
    k = p["round"].nunique()
    return (k, p.groupby("athlete_id")["best_def"].min().clip(upper=CLIP),
            p.groupby("athlete_id")["long_def"].mean().clip(upper=CLIP))


def training_rows(meas, use_track=True):
    """One pass over events with practice data (see module docstring)."""
    from racinglines.models.position_sim.pricing import entry_list
    if meas.practice is None or meas.practice.empty:
        return pd.DataFrame()
    first = meas.practice.groupby("event_id")["session_ts"].min()
    rows = []
    for ev in meas.drivers.drop_duplicates("event_id").itertuples():
        if ev.event_id not in first.index:
            continue
        cutoff = first[ev.event_id] - ONE_MIN
        v = meas.view(cutoff)
        snap = M.snapshot(v.drivers, v.sectors, v.xmap if use_track else {}, cutoff, use_track)
        if not snap.team_q:
            continue
        tf = M.venue_track_features(v.prof, ev.venue, cutoff)
        e = M.predict_paces(snap, entry_list(meas, ev.event_id), tf)[["athlete_id", "qp", "rp"]]
        e = e.rename(columns={"qp": "qp_pre", "rp": "rp_pre"})
        p = meas.practice[meas.practice["event_id"] == ev.event_id].sort_values("session_ts")
        order = list(dict.fromkeys(p["round"]))
        for k in range(1, len(order) + 1):
            pk = p[p["round"].isin(order[:k])]
            e[f"best_{k}"] = e["athlete_id"].map(pk.groupby("athlete_id")["best_def"].min()).clip(upper=CLIP)
            e[f"long_{k}"] = e["athlete_id"].map(pk.groupby("athlete_id")["long_def"].mean()).clip(upper=CLIP)
        out = meas.drivers[meas.drivers["event_id"] == ev.event_id][["athlete_id", "q_def", "r_def"]]
        e = e.merge(out, on="athlete_id", how="left")
        e["event_id"], e["r_ts"], e["start_date"] = ev.event_id, ev.r_ts, ev.start_date
        rows.append(e)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _fit(d, x_pre, x_prac, y, before):
    d = d[d[x_prac].notna() & d[y].notna() & d[x_pre].notna()]
    if d["event_id"].nunique() < MIN_EVENTS:
        return None
    w = M._weights(d["start_date"], before) + 0.05
    X = np.column_stack([np.ones(len(d)), d[x_pre], d[x_prac]])
    Y = d[y].clip(upper=CLIP).to_numpy()
    W = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(X * W[:, None], Y * W, rcond=None)
    sd = float(np.sqrt(np.average((Y - X @ coef) ** 2, weights=w)))
    return coef, sd


def fit(train, before):
    """{('q'|'r', k): (coef[a, b, c], resid_sd)} from events whose race finished before `before`."""
    if train is None or not len(train) or not USE_PRACTICE:
        return {}
    t = train[train["r_ts"] + M.RACE_DONE < before]
    out = {}
    for k in (1, 2, 3, 4):
        if f"best_{k}" not in t:
            continue
        q = _fit(t, "qp_pre", f"best_{k}", "q_def", before)
        r = _fit(t, "rp_pre", f"long_{k}", "r_def", before)
        if q:
            out[("q", k)] = q
        if r:
            out[("r", k)] = r
    return out


def apply(e, prac_view, event_id, blend):
    """Blend e's qp / rp with this weekend's practice (only sessions in the as-of view).
    Returns (e, sigma_q or None)."""
    k, best, long_ = session_features(prac_view, event_id)
    if not k or not blend:
        return e, None
    e = e.copy()
    sigma_q = None
    kq = max((kk for (w, kk) in blend if w == "q" and kk <= k), default=None)
    if kq is not None and len(best):
        (a, b, c), sd = blend[("q", kq)]
        x = e["athlete_id"].map(best).fillna(best.median())
        e["qp"] = a + b * e["qp"] + c * x
        sigma_q = sd
    kr = max((kk for (w, kk) in blend if w == "r" and kk <= k), default=None)
    lr = long_.dropna()
    if kr is not None and len(lr) >= 5:
        (a, b, c), _ = blend[("r", kr)]
        x = e["athlete_id"].map(lr).fillna(lr.median())
        e["rp"] = a + b * e["rp"] + c * x
    return e, sigma_q
