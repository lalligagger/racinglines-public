"""Price the 2026 European Championships men's ITT book with the engine's timed-runs model.

Reads data/raw/road_cycling/itt_results_pcs.csv and euro_itt_2026_startlist.csv and fits
racinglines.models.timed_runs.fit_season_model on every ITT (one run per rider per race, log times).

Training weight per race = recency (half-life) x course (flat_weight for ITTs under 8 m/km climbing; the Euros
course is 16.6 m/km) x field strength (weak_weight for national championships and fields under 40 finishers,
whose weak fields flatter their winners). The simulation scales the fitted day-to-day noise by noise_scale and
the incident (bad day / DNF) rate by incident_scale.

--calibrate grid-searches those five settings walk-forward on the strong-field races since --backtest-from (default 2021, five full seasons plus 2026) with 30+
finishers (fit on earlier dates only), scored on the actual winner's log loss (futures) and the pairwise log
loss of the top 40 finishers (matchups), then prices the book with the best setting by mean rank of the two.
Writes reports/2026-10-07-euro-itt/.
"""
import argparse
import itertools
import time
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from racinglines.core.stats import ranks
from racinglines.models.timed_runs import model as TM

FUTURES = {"Soderqvist": 2.38, "Roglic": 2.75, "Armirail": 13, "Kung": 13, "Romeo": 13, "Decomble": 13,
           "Van Wilder": 21, "Schmid": 23, "Vacek": 26, "Cattaneo": 26, "Asgreen": 34, "Thornley": 41,
           "Hayter": 67, "Bjerg": 81, "Tratnik": 101, "Oliveira": 126}
MATCHUPS = [("Thornley", 1.85, "Bjerg", 1.85), ("Cattaneo", 2.35, "Armirail", 1.53),
            ("De Pestel", 2.25, "Frigo", 1.57), ("Tratnik", 2.45, "Schmid", 1.47),
            ("Romeo", 1.47, "Van Wilder", 2.45), ("Pelikan", 1.85, "Kockelmann", 1.85),
            ("Bax", 2.25, "Oliveira", 1.57)]
BOOK = sorted(set(FUTURES) | {r for m in MATCHUPS for r in (m[0], m[2])})
EURO_M_PER_KM = 367 / 22.1
HILLY_M_PER_KM = 8.0
WEAK_FIELD = 40
FULL = {"Soderqvist": "jakob soderqvist", "Roglic": "primoz roglic", "Armirail": "bruno armirail",
        "Kung": "stefan kung", "Romeo": "ivan romeo", "Decomble": "maxime decomble", "Van Wilder": "ilan van wilder",
        "Schmid": "mauro schmid", "Vacek": "mathias vacek", "Cattaneo": "mattia cattaneo",
        "Asgreen": "kasper asgreen", "Thornley": "callum thornley", "Hayter": "ethan hayter",
        "Bjerg": "mikkel bjerg", "Tratnik": "jan tratnik", "Oliveira": "nelson oliveira",
        "De Pestel": "sander de pestel", "Frigo": "marco frigo", "Pelikan": "janos pelikan",
        "Kockelmann": "mathieu kockelmann", "Bax": "sjoerd bax"}
DEFAULT = dict(half_life=365.0, flat_weight=0.5, weak_weight=1.0, noise_scale=1.0, incident_scale=1.0)
GRID = dict(half_life=[240.0, 365.0, 730.0], flat_weight=[0.5, 1.0], weak_weight=[0.15, 0.4, 1.0],
            noise_scale=[0.6, 0.75, 0.9, 1.0, 1.15], incident_scale=[0.3, 1.0])


def fold(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def book_ids(names):
    """Book surname -> rider_url: every word of the rider's full name must be a word of the ASCII-folded PCS name
    (PCS writes "Bjerg Mikkel" or "BJERG Mikkel"). Every book name must match exactly one rider_url."""
    names = names.drop_duplicates("rider_url")
    words = names["rider"].map(lambda r: set(fold(r).replace("-", " ").split()))
    out, bad = {}, []
    for k in BOOK:
        want = set(FULL[k].split())
        hit = names[words.map(lambda w: want <= w)]
        if len(hit) == 1:
            out[k] = hit["rider_url"].iloc[0]
        else:
            bad.append(f"{k}: {len(hit)} matches {hit['rider'].tolist()[:5]}")
    return out, bad


def to_raw(df):
    """Engine rows. category encodes the course and field: ME hilly strong, MF flat strong, WH/WF weak fields."""
    d = df[df["status"].isin(["OK", "DNF", "DSQ"])].copy()
    vpk = pd.to_numeric(d["vert_m"], errors="coerce") / pd.to_numeric(d["distance_km"], errors="coerce")
    hilly = vpk.fillna(0) >= HILLY_M_PER_KM
    src = d["source_url"].astype(str) if "source_url" in d else ""
    label = (d["race"].astype(str) + " " + src).map(fold)
    finishers = d["race"].map(d[d["status"] == "OK"].groupby("race").size()).fillna(0)
    weak = label.str.contains("national|/nc-", regex=True) | (finishers < WEAK_FIELD)
    cat = np.where(weak, np.where(hilly, "WH", "WF"), np.where(hilly, "ME", "MF"))
    t = pd.to_numeric(d["winner_time_s"], errors="coerce") + pd.to_numeric(d["gap_s"], errors="coerce")
    return pd.DataFrame(dict(
        event_id=d["race"].astype(str), event_date=pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d"),
        round="final", category=cat, sector_id="FINISH", status=d["status"],
        cum_time_s=t.where(d["status"] == "OK"), rider_id=d["rider_url"], rider_name=d["rider"],
        rank_at_split=pd.to_numeric(d["position"], errors="coerce")))


def fit(raw, s):
    cw = {"ME": 1.0, "MF": s["flat_weight"], "WH": s["weak_weight"], "WF": s["flat_weight"] * s["weak_weight"]}
    strong = raw[raw["category"].isin(["ME", "MF"])]
    pool = "ME" if (strong["category"] == "ME").sum() >= 200 else "MF"
    return TM.fit_season_model(raw, category=pool, half_life_days=s["half_life"], category_weights=cw)


def simulate(m, riders, n, seed, s):
    rng = np.random.default_rng(seed)
    mu = m["mu"].reindex(riders).fillna(m["mu_new"]).to_numpy()
    p_inc = s["incident_scale"] * m["p_inc"].reindex(riders).fillna(m["p0"]).to_numpy()
    k = len(riders)
    noise = s["noise_scale"] * np.hypot(m["tau"], m["sigma"])
    t = mu + rng.normal(0, noise, (n, k))
    inc = rng.random((n, k)) < p_inc
    dnf = inc & (rng.random((n, k)) < m["dnf_share"])
    t = t + np.where(inc & ~dnf, rng.choice(m["excess"], (n, k)), 0.0)
    t[dnf] = np.inf
    return t


def score(t, top=40):
    """t: sims x riders in actual finishing order. Winner log loss, top-`top` pairwise log loss, favourite's p."""
    p_win = (ranks(t) == 1).mean(0)
    k = min(top, t.shape[1])
    tt = t[:, :k]
    beats = (tt[:, :, None] < tt[:, None, :]).mean(0)
    iu = np.triu_indices(k, 1)
    p_pair = np.clip(beats[iu], 1e-3, 1 - 1e-3)
    return dict(win_ll=-np.log(max(p_win[0], 1e-4)), pair_ll=float(-np.log(p_pair).mean()),
                fav_p=float(p_win.max()), fav_won=bool(np.argmax(p_win) == 0), p_winner=float(p_win[0]))


BACKTEST_FROM = "2021-01-01"


def target_races(raw):
    ok = raw[raw["status"] == "OK"]
    r = ok.groupby("event_id").agg(date=("event_date", "min"), n=("rider_id", "size"), cat=("category", "first"))
    return r[(r["date"] >= BACKTEST_FROM) & (r["n"] >= 30) & r["cat"].isin(["ME", "MF"])].sort_values("date")


def backtest(raw, settings, n_sims=2000, log_every=300):
    """Walk-forward scores for each setting in `settings`. Fits are shared across the simulation-only settings."""
    races = target_races(raw)
    fit_keys = ("half_life", "flat_weight", "weak_weight")
    rows, t0, last = [], time.time(), time.time()
    groups = {}
    for s in settings:
        groups.setdefault(tuple(s[k] for k in fit_keys), []).append(s)
    total = len(groups) * len(races)
    done = 0
    for fk, ss in groups.items():
        for ev, r in races.iterrows():
            done += 1
            train = raw[raw["event_date"] < r["date"]]
            if train["event_id"].nunique() < 10:
                continue
            m = fit(train, ss[0])
            tgt = raw[(raw["event_id"] == ev) & (raw["status"] == "OK")].sort_values("rank_at_split")
            for s in ss:
                t = simulate(m, tgt["rider_id"].tolist(), n_sims, 11, s)
                rows.append(dict(**s, race=ev, date=r["date"], field=len(tgt), winner=tgt["rider_name"].iloc[0],
                                 **score(t)))
            if time.time() - last > log_every:
                last = time.time()
                print(f"progress backtest: {(time.time() - t0) / 60:.0f} min elapsed · fit {done} of {total}",
                      flush=True)
    return pd.DataFrame(rows)


def summarize(bt):
    keys = list(DEFAULT)
    g = bt.groupby(keys).agg(races=("race", "size"), win_ll=("win_ll", "mean"), pair_ll=("pair_ll", "mean"),
                             fav_p=("fav_p", "mean"), fav_won=("fav_won", "mean"),
                             p_winner=("p_winner", "mean")).reset_index()
    g["rank"] = (g["win_ll"].rank() + g["pair_ll"].rank()) / 2
    return g.sort_values("rank")


def price(raw, res, start, ids, s, sims, out, tag):
    m = fit(raw, s)
    on_list = set(start["rider_url"])
    field = list(dict.fromkeys(list(start["rider_url"]) + [ids[k] for k in BOOK if k in ids]))
    t = simulate(m, field, sims, 7, s)
    rk = ranks(t)
    col = {u: j for j, u in enumerate(field)}
    nres = raw[raw["status"] == "OK"].groupby("rider_id").size()
    print(f"\n[{tag}] {s}\nmodel: noise {s['noise_scale'] * np.hypot(m['tau'], m['sigma']):.4f} "
          f"(fitted {np.hypot(m['tau'], m['sigma']):.4f}) incident rate {s['incident_scale'] * m['p0']:.3f} "
          f"· field {len(field)}")
    fut = []
    for k in BOOK:
        if k not in ids:
            continue
        j = col[ids[k]]
        p = (rk[:, j] == 1).mean()
        o = FUTURES.get(k)
        fut.append(dict(rider=k, results=int(nres.get(ids[k], 0)), on_start_list=ids[k] in on_list,
                        pace_pct=100 * (np.exp(m["mu"].get(ids[k], m["mu_new"])) - 1), win_p=p,
                        fair=1 / p if p else np.inf, book=o, edge=p * o - 1 if o else np.nan,
                        top3_p=(rk[:, j] <= 3).mean()))
    fut = pd.DataFrame(fut).sort_values("win_p", ascending=False)
    fut.to_csv(out / f"futures_{tag}.csv", index=False)
    print("FUTURES (edge = win_p x book - 1)")
    print(fut.to_string(index=False, float_format="%.3f"))
    rows = []
    for x, ox, y, oy in MATCHUPS:
        if x in ids and y in ids:
            px = (t[:, col[ids[x]]] < t[:, col[ids[y]]]).mean()
            rows.append(dict(a=x, a_odds=ox, a_p=px, a_edge=px * ox - 1, b=y, b_odds=oy, b_p=1 - px,
                             b_edge=(1 - px) * oy - 1, a_results=int(nres.get(ids[x], 0)),
                             b_results=int(nres.get(ids[y], 0))))
    mu = pd.DataFrame(rows)
    mu.to_csv(out / f"matchups_{tag}.csv", index=False)
    print("MATCHUPS")
    print(mu.to_string(index=False, float_format="%.3f"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw/road_cycling")
    ap.add_argument("--out", default="reports/2026-10-07-euro-itt")
    for k, v in DEFAULT.items():
        ap.add_argument("--" + k.replace("_", "-"), type=float, default=v)
    ap.add_argument("--sims", type=int, default=50000)
    ap.add_argument("--calibrate", action="store_true", help="grid-search the settings walk-forward, then price")
    ap.add_argument("--no-backtest", action="store_true")
    ap.add_argument("--backtest-from", default=BACKTEST_FROM)
    a = ap.parse_args()
    globals()["BACKTEST_FROM"] = a.backtest_from

    res = pd.read_csv(Path(a.data) / "itt_results_pcs.csv")
    start = pd.read_csv(Path(a.data) / "euro_itt_2026_startlist.csv")
    raw = to_raw(res)
    per_race = raw.groupby("event_id")["category"].first().value_counts().to_dict()
    print(f"rows {len(raw)} races {raw['event_id'].nunique()} by kind {per_race} "
          f"(ME hilly strong, MF flat strong, WH/WF weak field) · Euros course {EURO_M_PER_KM:.1f} m/km")
    tr = target_races(raw)
    seasons = tr["date"].str[:4].value_counts().sort_index().to_dict()
    print(f"backtest races since {BACKTEST_FROM} (strong field, 30+ finishers): {len(tr)} by season {seasons}")
    full = [y for y in range(int(BACKTEST_FROM[:4]), 2026) if seasons.get(str(y), 0) >= 5]
    if len(full) < 5:
        print(f"WARNING: only {len(full)} seasons with 5+ backtest races ({full}); the owner asked for 5 complete seasons")

    ids, bad = book_ids(pd.concat([res[["rider", "rider_url"]], start[["rider", "rider_url"]]]))
    if bad:
        print("UNMATCHED BOOK NAMES (fix before trusting prices):\n  " + "\n  ".join(bad))
    on_list = set(start["rider_url"])
    for k, u in ids.items():
        if u not in on_list:
            print(f"not on the start list yet: {k} ({u})")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    chosen = {k: getattr(a, k) for k in DEFAULT}
    if a.calibrate:
        grid = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
        print(f"\ncalibrating {len(grid)} settings ...", flush=True)
        bt = backtest(raw, grid)
        bt.to_csv(out / "calibration_races.csv", index=False)
        summ = summarize(bt)
        summ.to_csv(out / "calibration.csv", index=False)
        print("\nCALIBRATION (best 12 by mean rank of win_ll and pair_ll; lower is better)")
        print(summ.head(12).to_string(index=False, float_format="%.3f"))
        base = summ.merge(pd.DataFrame([DEFAULT]), on=list(DEFAULT))
        print("\nprevious default:")
        print(base.to_string(index=False, float_format="%.3f"))
        chosen = {k: float(summ.iloc[0][k]) for k in DEFAULT}
    elif not a.no_backtest:
        summ = summarize(backtest(raw, [chosen]))
        print("\nBACKTEST")
        print(summ.to_string(index=False, float_format="%.3f"))

    price(raw, res, start, ids, chosen, a.sims, out, "chosen")
    if a.calibrate and chosen != DEFAULT:
        price(raw, res, start, ids, DEFAULT, a.sims, out, "previous")


if __name__ == "__main__":
    main()
