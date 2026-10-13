"""
Road cycling stage races: the general classification (GC) as the sum of simulated stage times, schema-driven.

A stage race is an event file with a [[stages]] list (kind itt or road, distance, climbing, PCS profile icon) and
[model.gc] in sports/road_cycling.toml holds everything else as data: the finish bonus seconds, the time trials'
winning speed, the abandon rate, the field size and how profile icons group into road-stage classes.

Per simulated race, every stage is drawn on the book model (racinglines/models/cycling.py) for its kind:

  itt   the fitted time-trial model (log times, climbing term at the stage's m/km) -> seconds behind the fastest:
        stage time = distance / [model.gc] itt_kmh, gap = time x (exp(t - min t) - 1).
  road  the fitted road model gives the finishing order; the time gaps come from one past road stage of the same
        class (flat, rolling, hilly, mountain), drawn at random: the gap that stage gave at the same place in the
        field (its gap-by-quantile curve). The same draw serves every rider, so a split or a summit finish moves
        the whole field together. The top places at the finish take the bonus seconds.

GC = sum of the gaps minus the bonuses; an abandon on any stage is out (inf). When there is no start list, the
field is filled up to field_size with stand-in riders whose abilities are drawn from the fitted ones, so places
and bonus seconds are taken against a field of the right size.

    history(kind, stages)               engine rows: a kind's results file plus the stages file's stages of that kind
    gap_curves(stages)                  past road stages -> {class: (dates, curves)} gap by place quantile
    simulate_gc(...)                    sims x riders GC seconds (inf = out)
    price_gc(ev, ...)                   GC winner futures and matchups for an event's book
    backtest_gc(...)                    walk-forward on past stage races: winner and pairwise log loss
"""

import numpy as np
import pandas as pd

from racinglines import progress
from racinglines.core.stats import ranks
from racinglines.models import cycling as C

QGRID = np.linspace(0.0, 1.0, 201)


def gc_block():
    return C.schema()["model"]["gc"]


def stage_class(icon, kind, classes):
    """A stage's class: 'itt' for a time trial or prologue, else the road class its PCS profile icon maps to in
    [model.gc] classes (p1 flat, p2 rolling, ...); an unknown icon is 'rolling'."""
    if str(kind).lower() in ("itt", "prologue"):
        return "itt"
    if str(kind).upper() == "TTT":
        return "ttt"
    return classes.get(str(icon or "").lower(), "rolling")


def gap_curves(stages, classes):
    """{class: (dates array, curves array n x len(QGRID))}: every past road stage's gap in seconds at each place
    quantile of its finishers (place - 0.5) / finishers, from the stages results file (pcs.STAGE_COLUMNS)."""
    d = stages[(stages["status"] == "OK") & stages["gap_s"].notna()].copy()
    d["cls"] = [stage_class(i, k, classes) for i, k in zip(d["profile_icon"], d["stage_type"])]
    d = d[~d["cls"].isin(["itt", "ttt"])]
    out = {}
    for (race, stage), g in d.groupby(["race", "stage"]):
        g = g.sort_values("position")
        if len(g) < 30:
            continue
        q = (np.arange(len(g)) + 0.5) / len(g)
        curve = np.interp(QGRID, q, np.maximum.accumulate(g["gap_s"].to_numpy(dtype=float)))
        out.setdefault(g["cls"].iloc[0], []).append((g["date"].iloc[0], curve))
    return {c: (np.array([x[0] for x in v]), np.vstack([x[1] for x in v])) for c, v in out.items()}


def _curves_before(curves, cls, date):
    dates, cv = curves.get(cls, (np.array([]), np.empty((0, len(QGRID)))))
    keep = dates < date
    if not keep.any():
        raise ValueError(f"no past {cls} road stages before {date} to draw time gaps from")
    return cv[keep]


def _stand_ins(m_itt, m_road, n, rng):
    """n stand-in riders: (itt mu, road mu) pairs drawn together from riders the two fits share, so a stand-in is a
    plausible rider of the training population."""
    both = m_itt["mu"].index.intersection(m_road["mu"].index)
    pick = rng.choice(len(both), n, replace=True)
    ids = both[pick]
    return m_itt["mu"].reindex(ids).to_numpy(), m_road["mu"].reindex(ids).to_numpy()


def simulate_gc(stages, field, m_itt, m_road, s_itt, s_road, curves, g, date, sims=20000, seed=7, field_size=None,
                full=False):
    """sims x riders GC seconds behind a nominal zero (inf = out) for `field` (rider ids) over `stages` (list of
    dicts: kind, distance_km, vert_m, profile; `actual` a Series of real gaps for a stage already run). Stand-ins
    fill the field up to field_size; only `field` columns come back, unless `full`: then (total, [per-stage gaps])
    over the whole field, `field` first and the stand-ins after."""
    rng = np.random.default_rng(seed)
    k = len(field)
    extra = max(0, int(field_size or g["field_size"]) - k)
    mi_x, mr_x = _stand_ins(m_itt, m_road, extra, rng) if extra else (np.empty(0), np.empty(0))
    ids = list(field) + [f"__stand_in_{i}" for i in range(extra)]
    n = k + extra
    total = np.zeros((sims, n))
    per_stage = []
    bonus = np.asarray(g["bonus"], dtype=float)
    for st in stages:
        if st.get("actual") is not None:                       # a stage already run: its real gaps for everyone
            a = st["actual"]                                   # Series rider id -> seconds (inf = out)
            gap = a.reindex(ids[:k]).to_numpy(dtype=float)
            known = np.isfinite(gap) | a.reindex(ids[:k]).notna().to_numpy()
            fill = np.nanmedian(a[np.isfinite(a)]) if np.isfinite(a).any() else 0.0
            gap = np.where(known, gap, fill)                   # a field rider missing from the result: mid-field
            stand = rng.choice(a[np.isfinite(a)].to_numpy(), extra) if extra and np.isfinite(a).any() else \
                np.full(extra, fill)
            total += np.concatenate([gap, stand])[None, :]
            per_stage.append(np.broadcast_to(np.concatenate([gap, stand]), (sims, n)))
            continue
        cls = stage_class(st.get("profile"), st["kind"], g["classes"])
        if cls == "itt":
            m = dict(m_itt, mu=pd.concat([m_itt["mu"], pd.Series(mi_x, index=ids[k:])]))
            vpk = (st.get("vert_m") or 0) / st["distance_km"] if st.get("distance_km") else None
            t = C.simulate(m, ids, sims, int(rng.integers(1 << 31)), s_itt, "itt", vpk=vpk)
            secs = st["distance_km"] / g["itt_kmh"] * 3600.0
            out = ~np.isfinite(t)
            tt = np.where(out, np.nan, t)
            gap = secs * (np.exp(tt - np.nanmin(tt, axis=1, keepdims=True)) - 1.0)
            total += np.where(out, np.inf, gap)
            per_stage.append(np.where(out, np.inf, gap))
            continue
        m = dict(m_road, mu=pd.concat([m_road["mu"], pd.Series(mr_x, index=ids[k:])]))
        s_inc = dict(s_road)
        t = C.simulate(m, ids, sims, int(rng.integers(1 << 31)), s_inc, "road")
        hit = ~np.isfinite(t)                                   # an incident: a bad day, mostly not an abandon
        t = np.where(hit, np.inf, t)
        rk = ranks(np.where(hit, 1e9 + rng.random(t.shape), t)).astype(int)
        q = (rk - 0.5) / n
        q = np.where(hit, rng.uniform(g["incident_q"][0], g["incident_q"][1], t.shape), q)
        cv = _curves_before(curves, cls, date)
        draw = cv[rng.integers(len(cv), size=sims)]             # one past stage per simulated race
        gap = np.take_along_axis(draw, np.clip(np.rint(q * (len(QGRID) - 1)).astype(int), 0, len(QGRID) - 1), 1)
        gap = gap - np.where(rk <= len(bonus), bonus[np.clip(rk - 1, 0, len(bonus) - 1)], 0.0)
        aband = rng.random(t.shape) < g["abandon"]
        total += np.where(aband, np.inf, gap)
        per_stage.append(np.where(aband, np.inf, gap))
    return (total, per_stage) if full else total[:, :k]


def gc_ranks(total):
    """GC places per sim (1 = winner); riders out rank last. Ties broken at random."""
    jitter = np.random.default_rng(3).random(total.shape) * 1e-3
    return ranks(np.where(np.isfinite(total), total + jitter, 1e12 + jitter))


def price_gc(ev, ids, start, fits, curves, sims=20000):
    """(futures, matchups) for an event's GC book: win / top-3 / top-10 per book rider with the book's odds and
    edge, and every matchup's probability (both out void)."""
    g = {**gc_block(), **ev.get("gc", {})}
    m_itt, m_road, s_itt, s_road = fits
    on_list = list(start["rider_url"]) if len(start) else []
    field = list(dict.fromkeys(on_list + [ids[k] for k in C.labels(ev) if k in ids]))
    full, per_stage = simulate_gc(ev["stages"], field, m_itt, m_road, s_itt, s_road, curves, g, ev["event"]["date"],
                                  sims, field_size=max(len(field), int(ev["event"].get("field_size", g["field_size"]))),
                                  full=True)
    rk = gc_ranks(full)[:, :len(field)]
    total = full[:, :len(field)]
    col = {u: j for j, u in enumerate(field)}
    book = ev["book"].get("futures", {})
    fut = []
    for k in C.labels(ev):
        if k not in ids:
            continue
        j = col[ids[k]]
        p = float((rk[:, j] == 1).mean())
        o = book.get(k)
        fut.append(dict(rider=k, win_p=p, fair=1 / p if p else np.inf, book=o, edge=p * o - 1 if o else np.nan,
                        top3_p=float((rk[:, j] <= 3).mean()), top10_p=float((rk[:, j] <= 10).mean()),
                        out_p=float((~np.isfinite(total[:, j])).mean())))
    rows = []
    for mt in ev["book"].get("matchups", []):
        x, y = mt["a"], mt["b"]
        if x not in ids or y not in ids:
            continue
        a, b = total[:, col[ids[x]]], total[:, col[ids[y]]]
        both = ~np.isfinite(a) & ~np.isfinite(b)
        px = float((a < b)[~both].mean()) if (~both).any() else 0.5
        rows.append(dict(a=x, a_odds=mt["a_odds"], a_p=px, a_edge=px * mt["a_odds"] - 1, b=y, b_odds=mt["b_odds"],
                         b_p=1 - px, b_edge=(1 - px) * mt["b_odds"] - 1, both_out_p=float(both.mean())))
    return pd.DataFrame(fut).sort_values("win_p", ascending=False), pd.DataFrame(rows), full, per_stage, field


def history(kind, stages, data_dir=None):
    """Engine rows for a kind: its results file plus the stages file's stages of that kind (each stage its own
    race), without a stage the results file already holds (same date and winner)."""
    b = C.model_block(kind)
    res = C.load_results(kind, data_dir)
    if stages is not None and len(stages):
        st = stages.copy()
        is_tt = st["stage_type"].astype(str).str.lower().isin(["itt", "prologue"])
        st = st[is_tt] if kind == "itt" else st[~is_tt & (st["stage_type"].astype(str).str.upper() != "TTT")]
        st = st.assign(race=st["race"].astype(str) + "-" + st["stage"].astype(str), kind="oneday")
        seen = set(zip(res["date"].astype(str), res["rider_url"].where(res["position"] == 1)))
        win = st[st["position"] == 1].set_index("race")["rider_url"]
        dup = [r for r, u in win.items() if (str(st.loc[st["race"] == r, "date"].iloc[0]), u) in seen]
        res = pd.concat([res, st[~st["race"].isin(dup)][res.columns.intersection(st.columns)]], ignore_index=True)
    return C.to_raw(res, kind, b["rules"])


def fits_before(itt_raw, road_raw, date, s_itt, s_road):
    """The two book-model fits on results before `date` (flat-course weights: a stage race's GC is decided on time
    trials and the road stages' gaps, not on one-day hilly form alone)."""
    m_itt = C.fit(itt_raw[itt_raw["event_date"] < date], "itt", s_itt, "flat")
    m_road = C.fit(road_raw[road_raw["event_date"] < date], "road", s_road, "hilly")
    return m_itt, m_road


def race_stages(stages, race):
    """A past race's stage list in event-file shape, from the stages results file."""
    d = stages[stages["race"] == race]
    first = d.drop_duplicates("stage").sort_values("date")
    return [dict(kind="itt" if str(r.stage_type).lower() in ("itt", "prologue") else
                 "ttt" if str(r.stage_type).upper() == "TTT" else "road",
                 distance_km=r.distance_km, vert_m=r.vert_m, profile=r.profile_icon, stage=r.stage)
            for r in first.itertuples()]


def backtest_gc(stages, itt_raw, road_raw, s_itt, s_road, since, sims=4000, settings=None):
    """Walk-forward on every past stage race since `since` with no team time trial and 30+ finishers: refit both
    models on results before the race's first stage, simulate its GC over its starters, score the final GC
    (winner log loss, top-40 pairwise log loss, favourite's chance). `settings` overrides [model.gc] values."""
    g = {**gc_block(), **(settings or {})}
    curves = gap_curves(stages, g["classes"])
    races = (stages.groupby("race").agg(date=("date", "min"), types=("stage_type", lambda x: set(x)))
             .query("date >= @since").sort_values("date"))
    rows, fits = [], {}
    for i, (race, r) in enumerate(races.iterrows(), 1):
        progress.update(i, len(races), race)
        if "TTT" in r["types"]:
            continue
        st = race_stages(stages, race)
        d = stages[stages["race"] == race]
        last = d[d["stage"] == st[-1]["stage"]]
        final = last[last["gc_position"].notna()].sort_values("gc_position")
        starters = d[d["stage"] == st[0]["stage"]]["rider_url"].dropna().unique().tolist()
        if len(final) < 30 or not starters:
            continue
        mo = r["date"][:7] + "-01"
        if mo not in fits:
            fits[mo] = fits_before(itt_raw, road_raw, mo, s_itt, s_road)
        m_itt, m_road = fits[mo]
        try:
            total = simulate_gc(st, starters, m_itt, m_road, s_itt, s_road, curves, g, r["date"], sims,
                                field_size=len(starters))
        except ValueError as ex:
            print(f"{race}: skipped ({ex})", flush=True)
            continue
        col = {u: j for j, u in enumerate(starters)}
        order = [u for u in final["rider_url"] if u in col]
        t = np.where(np.isfinite(total), total, 1e12)[:, [col[u] for u in order]]
        sc = C.score(t)
        rows.append(dict(race=race, date=r["date"], stages=len(st), field=len(starters),
                         itt_km=sum(x["distance_km"] or 0 for x in st if x["kind"] == "itt"),
                         winner=final["rider"].iloc[0], **sc))
    return pd.DataFrame(rows)
