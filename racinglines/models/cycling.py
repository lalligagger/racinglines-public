"""
Road cycling: price a race's book (winner and head-to-head lines) on the timed-runs engine, schema-driven.

Everything sport-specific is data: sports/road_cycling.toml says where results live and holds each race kind's
model settings ([model.itt], [model.road]: defaults, calibration grid, course and field rules, backtest races);
an event file (sports/road_cycling/events/<id>.toml) holds the course, the start list file and the book. A new
race is a new event file; a new kind of race is a new [model.<kind>] block.

Two kinds of result, one engine (racinglines.models.timed_runs.fit_season_model):

  itt   Individual time trials: log finishing times. Optional per-rider climbing term (slope of a rider's
        residual log time on the course's climbing in m/km), scaled by climb_scale for the event's course.
  road  Mass-start races finish in bunches, so the time says little. Each result becomes a pseudo-time instead:
        the finisher's normal score z = Phi^-1((position - 0.5) / finishers), stored as log time Z_SCALE * z.
        A stage race's final GC can be added as its own result kind (gc_weight).

Training weight per result = recency (half_life) x course (flat_weight off the event's terrain) x field
(weak_weight below the strong-field rule) x kind (gc_weight). The simulation scales the fitted day-to-day noise
by noise_scale and the incident (DNF / bad day) rate by incident_scale.

    load_event(path)                    the event file, with its kind's settings merged in
    load_results(kind, data_dir)        the results CSV for a kind ([results] files)
    to_raw(df, kind, rules)             engine rows
    fit / simulate / score              one fit, sims x riders log times (inf = out), backtest scores
    backtest(raw, kind, settings)       walk-forward: refit monthly on earlier months, score each target race
    summarize(bt)                       per-setting means, ranked on winner and pairwise log loss
    reliability / reliability_table     every rider's walk-forward win / top-3 / top-10 chance vs what happened,
    temperature                         by probability and model-rank bucket (favourites vs long shots)
    price(event, raw, start, s, ...)    futures and matchup frames for the event's book
    stakes(fut, mu, bankroll, kelly)    fractional-Kelly stakes on every positive edge

The CLI is `racinglines cycling` (racinglines/cli/cycling.py); docs/road-cycling.md has the workflow.
"""

import itertools
import tomllib
import unicodedata
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from racinglines import progress, sports
from racinglines.core.stats import ranks
from racinglines.models.timed_runs import model as TM
from racinglines.paths import ROOT

SPORT = "road_cycling"
EVENTS = ROOT / "sports" / SPORT / "events"
Z_SCALE = 0.01          # road pseudo-time: log-time units per normal-score unit (keeps every OK finish under the
                        # engine's 4% incident line, so road incidents are DNFs only)
SIM_ONLY = ("noise_scale", "incident_scale", "climb_scale")   # settings that change the simulation, not the fit


# --- schema and event files ------------------------------------------------------------------------------------

def schema():
    return sports.load(SPORT)


def model_block(kind):
    try:
        return schema()["model"][kind]
    except KeyError:
        raise ValueError(f"no [model.{kind}] block in sports/{SPORT}.toml") from None


def event_path(name):
    p = Path(name)
    return p if p.suffix == ".toml" and p.exists() else EVENTS / f"{name}.toml"


def load_event(name):
    """The event file plus `id` (its file stem) and `settings` (its kind's defaults, then the event's own
    [settings] overrides)."""
    p = event_path(name)
    ev = tomllib.loads(p.read_text())
    ev["id"] = p.stem
    kind = ev["event"]["kind"]
    ev["settings"] = {**model_block(kind)["defaults"], **ev.get("settings", {})}
    return ev


def list_events():
    return sorted(p.stem for p in EVENTS.glob("*.toml"))


def results_file(kind, data_dir=None):
    r = schema()["results"]
    return Path(data_dir or ROOT / r["dir"]) / r["files"][kind]


def startlist_file(ev, data_dir=None):
    return Path(data_dir or ROOT / schema()["results"]["dir"]) / ev["event"]["startlist_file"]


def load_results(kind, data_dir=None):
    return pd.read_csv(results_file(kind, data_dir))


# --- names -----------------------------------------------------------------------------------------------------

def fold(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def words(name):
    return set(fold(name).replace("-", " ").replace("'", " ").split())


def labels(ev):
    book = ev["book"]
    return sorted(set(book.get("futures", {})) | {r for m in book.get("matchups", []) for r in (m["a"], m["b"])})


def book_ids(ev, start, res):
    """Book label -> rider_url. Every word of the label's name in [names] (default: the label) must be a word of
    the ASCII-folded PCS name ("POGACAR Tadej" or "Tadej Pogačar"). The start list is searched first (fewer
    namesakes), then every result. A label must match exactly one rider; the others come back in `bad`."""
    names = ev.get("names", {})
    pools = [start.drop_duplicates("rider_url"), res.drop_duplicates("rider_url")]
    out, bad = {}, []
    for k in labels(ev):
        want = words(names.get(k, k))
        hits = pools[0].iloc[:0]
        for pool in pools:
            hits = pool[pool["rider"].map(lambda r, want=want: want <= words(r))]
            if len(hits):
                break
        if len(hits) == 1:
            out[k] = hits["rider_url"].iloc[0]
        else:
            bad.append(f"{k}: {len(hits)} matches {list(hits['rider'])[:5]}")
    return out, bad


# --- engine rows -----------------------------------------------------------------------------------------------

def _col(d, name, default=""):
    return d[name] if name in d else pd.Series(default, index=d.index)


def course_vpk(distance_km, vert_m):
    vpk = pd.to_numeric(vert_m, errors="coerce") / pd.to_numeric(distance_km, errors="coerce")
    return vpk.where(np.isfinite(vpk) & (vpk >= 0) & (vpk <= 60))   # zero or missing distance gives inf


def hilly_mask(d, rules):
    """The course rule from [model.<kind>.rules]: a PCS profile icon in hilly_icons, else ProfileScore at least
    hilly_score, else at least hilly_m_per_km of climbing."""
    icon = _col(d, "profile_icon").fillna("").astype(str).str.lower()
    hilly = icon.isin(rules.get("hilly_icons", []))
    no_icon = icon == ""
    if "hilly_score" in rules:
        hilly |= no_icon & (pd.to_numeric(_col(d, "profile_score", np.nan), errors="coerce") >= rules["hilly_score"])
    if "hilly_m_per_km" in rules:
        vpk = course_vpk(_col(d, "distance_km", np.nan), _col(d, "vert_m", np.nan))
        hilly |= no_icon & (vpk >= rules["hilly_m_per_km"])
    return hilly


def weak_mask(d, rules, finishers):
    """The field rule: a race label matching weak_label (national championships), a race class outside
    strong_classes (when the data has classes), or fewer than weak_field finishers."""
    label = (d["race"].astype(str) + " " + _col(d, "source_url").astype(str)).map(fold)
    weak = finishers < rules.get("weak_field", 0)
    if rules.get("weak_label"):
        weak |= label.str.contains(rules["weak_label"], regex=True)
    cls = _col(d, "race_class").fillna("").astype(str).str.upper()
    if rules.get("strong_classes") and (cls != "").any():
        weak |= ~cls.str.startswith(tuple(c.upper() for c in rules["strong_classes"]))
    return weak


def to_raw(df, kind, rules):
    """Engine rows. category encodes course and field: ME hilly strong, MF flat strong, WH / WF the same in a weak
    field, GC a stage race's final GC (road only). `vpk` (m/km) is carried for the ITT climbing term."""
    d = df[df["status"].isin(["OK", "DNF", "DSQ"])].copy()
    d["kind"] = _col(d, "kind", "oneday").fillna("oneday")
    key = d["race"].astype(str) + "|" + d["kind"]
    ok = d["status"] == "OK"
    finishers = key.map(d[ok].groupby(key[ok]).size()).fillna(0)
    hilly = hilly_mask(d, rules)
    weak = weak_mask(d, rules, finishers)
    cat = np.where(weak, np.where(hilly, "WH", "WF"), np.where(hilly, "ME", "MF"))
    cat = np.where(d["kind"] == "gc", "GC", cat)
    pos = pd.to_numeric(d["position"], errors="coerce")
    if kind == "itt":
        t = pd.to_numeric(d["winner_time_s"], errors="coerce") + pd.to_numeric(d["gap_s"], errors="coerce")
    else:
        rank = pos.where(ok).groupby(key).rank(method="first")
        q = ((rank - 0.5) / finishers).clip(1e-4, 1 - 1e-4)
        inv = NormalDist().inv_cdf
        z = q.map(lambda v: inv(v) if pd.notna(v) else np.nan)
        t = 1000.0 * np.exp(Z_SCALE * z)
    vpk = course_vpk(_col(d, "distance_km", np.nan), _col(d, "vert_m", np.nan))
    return pd.DataFrame(dict(
        event_id=key if kind != "itt" else d["race"].astype(str),
        event_date=pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d"), round="final", category=cat,
        sector_id="FINISH", status=d["status"], cum_time_s=t.where(ok), rider_id=d["rider_url"],
        rider_name=d["rider"], rank_at_split=pos, vpk=vpk.fillna(vpk.median() if vpk.notna().any() else 0.0)))


# --- fit and simulate ------------------------------------------------------------------------------------------

def weights(s):
    return {"ME": 1.0, "MF": s["flat_weight"], "WH": s["weak_weight"], "WF": s["flat_weight"] * s["weak_weight"],
            "GC": s.get("gc_weight", 0.0)}


def fit(raw, kind, s, terrain="hilly"):
    """One engine fit. `terrain` is the event's course: on a flat course the flat races are the target ones, so
    the course weights swap (flat_weight then weighs the hilly races)."""
    cw = weights(s)
    if terrain == "flat":
        cw.update(ME=cw["MF"], MF=1.0, WH=cw["WF"], WF=s["weak_weight"])
    if not cw["GC"]:
        raw = raw[raw["category"] != "GC"]
    # noise and incidents pool over the results most like the event: its terrain in a strong field first
    n = raw["category"].value_counts()
    prefs = ["MF", "WF", "ME", "WH"] if terrain == "flat" else ["ME", "WH", "MF", "WF"]
    pool = next((c for c in prefs if n.get(c, 0) >= 200), max(prefs, key=lambda c: n.get(c, 0)))
    m = TM.fit_season_model(raw, category=pool, half_life_days=s["half_life"], category_weights=cw)
    m["beta"], m["x0"] = (climb_slopes(raw, m, cw, s) if kind == "itt" and s.get("climb_scale")
                          else (pd.Series(dtype=float), 0.0))
    return m


def climb_slopes(raw, m, cw, s):
    """Per-rider climbing term: the slope of a rider's residual log time (after race effect and pace) on the
    course's climbing in m/km, weighted like the fit and shrunk toward 0 by climb_prior races' worth of typical
    course spread. Incident runs (4%+ slow) are left out."""
    ok = raw[(raw["status"] == "OK") & (raw["cum_time_s"] > 0)].copy()
    ok["y"] = np.log(ok["cum_time_s"])
    ok["mu"] = ok["rider_id"].map(m["mu"]).fillna(0.0)
    ok["e"] = ok["y"] - ok["event_id"].map((ok["y"] - ok["mu"]).groupby(ok["event_id"]).median()) - ok["mu"]
    ok = ok[ok["e"] < TM.INCIDENT_THRESHOLD]
    age = (pd.to_datetime(ok["event_date"]).max() - pd.to_datetime(ok["event_date"])).dt.days
    w = ok["category"].map(cw).fillna(1.0) * 0.5 ** (age / s["half_life"])
    x0 = float((w * ok["vpk"]).sum() / w.sum())
    x = ok["vpk"] - x0
    var_x = float((w * x * x).sum() / w.sum())
    if not np.isfinite(x0) or not var_x > 0:
        raise ValueError(f"climbing term: bad course data (x0 {x0}, var {var_x}); check vert_m and distance_km")
    num = (w * ok["e"] * x).groupby(ok["rider_id"]).sum()
    den = (w * x * x).groupby(ok["rider_id"]).sum() + s["climb_prior"] * var_x
    return num / den, x0


def simulate(m, riders, n, seed, s, kind, vpk=None):
    """sims x riders log times; inf = out (DNF). An ITT incident is a slow ride (the fitted excess) or a DNF; a
    road incident is a DNF or a finish out of contention, so it is out."""
    rng = np.random.default_rng(seed)
    mu = m["mu"].reindex(riders).fillna(m["mu_new"]).to_numpy()
    if vpk is not None and s.get("climb_scale") and len(m["beta"]):
        mu = mu + s["climb_scale"] * m["beta"].reindex(riders).fillna(0.0).to_numpy() * (vpk - m["x0"])
    p_inc = np.clip(s["incident_scale"] * m["p_inc"].reindex(riders).fillna(m["p0"]).to_numpy(), 0, 0.95)
    k = len(riders)
    t = mu + rng.normal(0, s["noise_scale"] * np.hypot(m["tau"], m["sigma"]), (n, k))
    inc = rng.random((n, k)) < p_inc
    if kind == "itt":
        dnf = inc & (rng.random((n, k)) < m["dnf_share"])
        t = t + np.where(inc & ~dnf, rng.choice(m["excess"], (n, k)), 0.0)
        t[dnf] = np.inf
    else:
        t[inc] = np.inf
    return t


def score(t, top=40):
    """t: sims x riders in actual finishing order. Winner log loss, top-`top` pairwise log loss, favourite's p."""
    p_win = (ranks(t) == 1).mean(0)
    k = min(top, t.shape[1])
    tt = t[:, :k]
    beats = (tt[:, :, None] < tt[:, None, :]).mean(0) + 0.5 * (tt[:, :, None] == tt[:, None, :]).mean(0)
    iu = np.triu_indices(k, 1)
    p_pair = np.clip(beats[iu], 1e-3, 1 - 1e-3)
    return dict(win_ll=-np.log(max(p_win[0], 1e-4)), pair_ll=float(-np.log(p_pair).mean()),
                fav_p=float(p_win.max()), fav_won=bool(np.argmax(p_win) == 0), p_winner=float(p_win[0]))


# --- backtest --------------------------------------------------------------------------------------------------

def target_races(raw, kind, since):
    """[model.<kind>.backtest]: races since `since` with min_field+ finishers in `categories`."""
    bt = model_block(kind)["backtest"]
    ok = raw[raw["status"] == "OK"]
    r = ok.groupby("event_id").agg(date=("event_date", "min"), n=("rider_id", "size"), cat=("category", "first"),
                                   vpk=("vpk", "first"))
    return r[(r["date"] >= since) & (r["n"] >= bt["min_field"]) & r["cat"].isin(bt["categories"])].sort_values("date")


def backtest(raw, kind, settings, since, terrain="hilly", n_sims=2000):
    """Walk-forward scores for each setting: one fit per month per fit-setting group, on results before that
    month; the simulation-only settings reuse it. Reports its position to the CLI heartbeat (progress.py)."""
    races = target_races(raw, kind, since).copy()
    races["month"] = races["date"].str[:7]
    groups = {}
    for s in settings:
        groups.setdefault(tuple(sorted((k, v) for k, v in s.items() if k not in SIM_ONLY)), []).append(s)
    months = races["month"].unique()
    total, done, rows = len(groups) * len(months), 0, []
    for ss in groups.values():
        for mo in months:
            done += 1
            progress.update(done, total, f"fit month {mo}")
            train = raw[raw["event_date"] < mo + "-01"]
            if train["event_id"].nunique() < 10:
                continue
            m = fit(train, kind, ss[0], terrain)
            for ev, r in races[races["month"] == mo].iterrows():
                tgt = raw[(raw["event_id"] == ev) & (raw["status"] == "OK")].sort_values("rank_at_split")
                for s in ss:
                    t = simulate(m, tgt["rider_id"].tolist(), n_sims, 11, s, kind, vpk=r["vpk"])
                    rows.append(dict(**s, race=ev, date=r["date"], field=len(tgt), cat=r["cat"],
                                     winner=tgt["rider_name"].iloc[0], **score(t)))
    return pd.DataFrame(rows)


def reliability(raw, kind, s, since, terrain="hilly", n_sims=4000):
    """Every rider's walk-forward probabilities in every backtest race, for a calibration check: one fit per month
    on earlier results (as backtest), simulated over the race's whole field, DNFs included (they lost). One row per
    rider per race: p_win / p_top3 / p_top10, the model's rank, and what happened (won, top3, top10)."""
    races = target_races(raw, kind, since).copy()
    races["month"] = races["date"].str[:7]
    months = races["month"].unique()
    rows = []
    for i, mo in enumerate(months, 1):
        progress.update(i, len(months), f"fit month {mo}")
        train = raw[raw["event_date"] < mo + "-01"]
        if train["event_id"].nunique() < 10:
            continue
        m = fit(train, kind, s, terrain)
        for ev, r in races[races["month"] == mo].iterrows():
            tgt = raw[raw["event_id"] == ev].drop_duplicates("rider_id")
            pos = tgt["rank_at_split"].where(tgt["status"] == "OK").rank(method="first").to_numpy()
            rk = ranks(simulate(m, tgt["rider_id"].tolist(), n_sims, 11, s, kind, vpk=r["vpk"]))
            p = {k: (rk <= k).mean(0) for k in (1, 3, 10)}
            rows.append(pd.DataFrame(dict(
                race=ev, date=r["date"], cat=r["cat"], field=len(tgt), rider=tgt["rider_name"].to_numpy(),
                p_win=p[1], p_top3=p[3], p_top10=p[10], model_rank=pd.Series(-p[1]).rank(method="first").to_numpy(),
                won=pos == 1, top3=pos <= 3, top10=pos <= 10)))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


WIN_BUCKETS = [0, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.35, 1.0]
RANK_BUCKETS = [0, 1, 3, 5, 10, 20, 10**6]
TEMPERATURES = np.arange(0.5, 3.01, 0.05)


def reliability_table(rel, by, hit, edges):
    """Predicted vs actual per bucket of `by` (a probability, or model_rank): riders, mean predicted, actual rate,
    expected and actual hits, and z = (actual - expected) / sd. z above 2 means the model under-rates that bucket."""
    rank = by == "model_rank"
    names = [f"{a + 1}" if b == a + 1 else f"{a + 1}+" if b >= 10**6 else f"{a + 1}-{b}" for a, b in
             itertools.pairwise(edges)] if rank else None
    b = pd.cut(rel[by], edges, right=rank, include_lowest=True, labels=names)
    pcol = {"won": "p_win", "top3": "p_top3", "top10": "p_top10"}[hit]
    g = rel.assign(bucket=b, var=rel[pcol] * (1 - rel[pcol])).groupby("bucket", observed=True)
    t = g.agg(riders=(pcol, "size"), predicted=(pcol, "mean"), actual=(hit, "mean"), expected_hits=(pcol, "sum"),
              hits=(hit, "sum"), var=("var", "sum")).reset_index()
    t["z"] = (t["hits"] - t["expected_hits"]) / np.sqrt(t.pop("var")).replace(0, np.nan)
    return t


def temperature(rel, grid=TEMPERATURES):
    """The power a in p_i^a / sum_j p_j^a (per race) that best fits the actual winners, and the winner log loss at
    a = 1 and at the best a. a > 1 means the model's favourites should be sharper (long shots too long a chance).
    Fitted on the same races it scores: a diagnostic, not a setting."""
    d = rel[["race", "p_win", "won"]].copy()
    d["lp"] = np.log(d["p_win"].clip(lower=1e-4))
    d = d[d["race"].isin(d.loc[d["won"], "race"])]
    def ll(a):
        lse = (a * d["lp"]).groupby(d["race"]).transform(lambda x: np.log(np.exp(x).sum()))
        return float(-(a * d["lp"] - lse)[d["won"]].mean())
    scores = {round(float(a), 2): ll(a) for a in grid}
    best = min(scores, key=scores.get)
    return dict(races=int(d["race"].nunique()), a=best, win_ll_a1=ll(1.0), win_ll_best=scores[best])


def summarize(bt, keys):
    if bt.empty:
        return pd.DataFrame(columns=list(keys) + ["races", "win_ll", "pair_ll", "rank"])
    g = bt.groupby(list(keys)).agg(races=("race", "size"), win_ll=("win_ll", "mean"), pair_ll=("pair_ll", "mean"),
                                   fav_p=("fav_p", "mean"), fav_won=("fav_won", "mean"),
                                   p_winner=("p_winner", "mean")).reset_index()
    g["rank"] = (g["win_ll"].rank() + g["pair_ll"].rank()) / 2
    return g.sort_values("rank")


# --- pricing ---------------------------------------------------------------------------------------------------

def event_vpk(ev):
    e = ev["event"]
    return e["vert_m"] / e["distance_km"] if e.get("vert_m") and e.get("distance_km") else None


def price(ev, raw, start, ids, s, sims=50000, seed=7):
    """(futures, matchups, model) for the event's book. Book riders missing from the start list are priced too
    (flagged), so a late start list doesn't drop a line silently."""
    kind = ev["event"]["kind"]
    m = fit(raw, kind, s, ev["event"].get("terrain", "hilly"))
    on_list = set(start["rider_url"])
    field = list(dict.fromkeys(list(start["rider_url"]) + [ids[k] for k in labels(ev) if k in ids]))
    t = simulate(m, field, sims, seed, s, kind, vpk=event_vpk(ev))
    rk = ranks(t)
    col = {u: j for j, u in enumerate(field)}
    ok = raw[raw["status"] == "OK"]
    nres = ok[ok["category"] != "GC"].groupby("rider_id").size()
    ngc = ok[ok["category"] == "GC"].groupby("rider_id").size()
    futures = ev["book"].get("futures", {})
    fut = []
    for k in labels(ev):
        if k not in ids:
            continue
        u = ids[k]
        j = col[u]
        p = (rk[:, j] == 1).mean()
        o = futures.get(k)
        fut.append(dict(rider=k, results=int(nres.get(u, 0)), gc=int(ngc.get(u, 0)), on_start_list=u in on_list,
                        win_p=p, fair=1 / p if p else np.inf, book=o, edge=p * o - 1 if o else np.nan,
                        top3_p=(rk[:, j] <= 3).mean(), top10_p=(rk[:, j] <= 10).mean(),
                        out_p=np.isinf(t[:, j]).mean()))
    fut = pd.DataFrame(fut).sort_values("win_p", ascending=False)
    rows = []
    for mt in ev["book"].get("matchups", []):
        x, y = mt["a"], mt["b"]
        if x not in ids or y not in ids:
            continue
        a, b = t[:, col[ids[x]]], t[:, col[ids[y]]]
        both_out = np.isinf(a) & np.isinf(b)
        px = float((a < b)[~both_out].mean()) if (~both_out).any() else 0.5   # both out: void on most books
        n = int(min(nres.get(ids[x], 0) + ngc.get(ids[x], 0), nres.get(ids[y], 0) + ngc.get(ids[y], 0)))
        rows.append(dict(a=x, a_odds=mt["a_odds"], a_p=px, a_edge=px * mt["a_odds"] - 1, b=y, b_odds=mt["b_odds"],
                         b_p=1 - px, b_edge=(1 - px) * mt["b_odds"] - 1, both_out_p=float(both_out.mean()),
                         results=n))
    return fut, pd.DataFrame(rows), m


def stakes(fut, mu, bankroll, kelly, thin=5):
    """Fractional-Kelly stake on every positive-edge line, each sized on its own; thin_data marks a rider (or the
    thinner rider of a pair) with under `thin` results."""
    bets = [dict(bet=f"{r.rider} to win", odds=r.book, p=r.win_p, results=r.results + r.gc)
            for r in fut.itertuples() if r.book == r.book]
    for r in mu.itertuples():
        bets.append(dict(bet=f"{r.a} over {r.b}", odds=r.a_odds, p=r.a_p, results=r.results))
        bets.append(dict(bet=f"{r.b} over {r.a}", odds=r.b_odds, p=r.b_p, results=r.results))
    b = pd.DataFrame(bets, columns=["bet", "odds", "p", "results"])
    b["edge"] = b["p"] * b["odds"] - 1
    b = b[b["edge"] > 0].copy()
    b["kelly_pct"] = 100 * kelly * b["edge"] / (b["odds"] - 1)
    b["stake"] = (bankroll * b["kelly_pct"] / 100).round(2)
    b["thin_data"] = b["results"] < thin
    return b.sort_values("stake", ascending=False)
