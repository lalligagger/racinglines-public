"""Price the 2026 European Championships men's ITT book with the engine's timed-runs model.

Reads data/raw/road_cycling/itt_results_pcs.csv and euro_itt_2026_startlist.csv, fits
racinglines.models.timed_runs.fit_season_model on every ITT (one run per rider per race, log times),
backtests the 2025-26 championship and Grand Tour ITTs walk-forward, then simulates the Euros and
prices the book's futures and matchups. Writes reports/2026-10-07-euro-itt/.
"""
import argparse
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
FULL = {"Soderqvist": "jakob soderqvist", "Roglic": "primoz roglic", "Armirail": "bruno armirail",
        "Kung": "stefan kung", "Romeo": "ivan romeo", "Decomble": "maxime decomble", "Van Wilder": "ilan van wilder",
        "Schmid": "mauro schmid", "Vacek": "mathias vacek", "Cattaneo": "mattia cattaneo",
        "Asgreen": "kasper asgreen", "Thornley": "callum thornley", "Hayter": "ethan hayter",
        "Bjerg": "mikkel bjerg", "Tratnik": "jan tratnik", "Oliveira": "nelson oliveira",
        "De Pestel": "sander de pestel", "Frigo": "marco frigo", "Pelikan": "janos pelikan",
        "Kockelmann": "mathieu kockelmann", "Bax": "sjoerd bax"}


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


def to_raw(df, flat_weight):
    d = df[df["status"].isin(["OK", "DNF", "DSQ"])].copy()
    vpk = pd.to_numeric(d["vert_m"], errors="coerce") / pd.to_numeric(d["distance_km"], errors="coerce")
    hilly = vpk.fillna(0) >= 8.0
    t = pd.to_numeric(d["winner_time_s"], errors="coerce") + pd.to_numeric(d["gap_s"], errors="coerce")
    return pd.DataFrame(dict(
        event_id=d["race"].astype(str), event_date=pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d"),
        round="final", category=np.where(hilly, "ME", "MF"), sector_id="FINISH", status=d["status"],
        cum_time_s=t.where(d["status"] == "OK"), rider_id=d["rider_url"], rider_name=d["rider"],
        rank_at_split=pd.to_numeric(d["position"], errors="coerce"))), {"MF": flat_weight}


def fit(raw, cw, half_life):
    return TM.fit_season_model(raw, category="ME" if (raw["category"] == "ME").sum() > 200 else "MF",
                               half_life_days=half_life, category_weights=cw)


def simulate(m, riders, n, seed):
    rng = np.random.default_rng(seed)
    mu = m["mu"].reindex(riders).fillna(m["mu_new"]).to_numpy()
    p_inc = m["p_inc"].reindex(riders).fillna(m["p0"]).to_numpy()
    k = len(riders)
    t = mu + rng.normal(0, m["tau"], (n, k)) + rng.normal(0, m["sigma"], (n, k))
    inc = rng.random((n, k)) < p_inc
    dnf = inc & (rng.random((n, k)) < m["dnf_share"])
    t = t + np.where(inc & ~dnf, rng.choice(m["excess"], (n, k)), 0.0)
    t[dnf] = np.inf
    return t


def backtest(raw, cw, half_life, n):
    """Walk-forward on 2025-26 races with 30+ finishers: fit on earlier dates only."""
    rows = []
    races = raw[raw["status"] == "OK"].groupby("event_id").agg(date=("event_date", "min"), n=("rider_id", "size"))
    for ev, r in races[(races["date"] >= "2025-01-01") & (races["n"] >= 30)].sort_values("date").iterrows():
        train = raw[raw["event_date"] < r["date"]]
        if train["event_id"].nunique() < 10:
            continue
        m = fit(train, cw, half_life)
        tgt = raw[(raw["event_id"] == ev) & (raw["status"] == "OK")].sort_values("rank_at_split")
        riders = tgt["rider_id"].tolist()
        t = simulate(m, riders, n, 11)
        rk = ranks(t)
        p_win = (rk == 1).mean(0)
        exp_rank = np.where(np.isfinite(rk), rk, len(riders)).mean(0)
        rows.append(dict(race=ev, date=r["date"], field=len(riders), winner=tgt["rider_name"].iloc[0],
                         p_winner=p_win[0], model_fav=tgt["rider_name"].iloc[int(np.argmax(p_win))],
                         spearman=pd.Series(exp_rank).rank().corr(pd.Series(np.arange(1.0, len(riders) + 1)))))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/raw/road_cycling")
    ap.add_argument("--out", default="reports/2026-10-07-euro-itt")
    ap.add_argument("--half-life", type=float, default=365.0)
    ap.add_argument("--flat-weight", type=float, default=0.5,
                    help="Training weight of flatter ITTs (under 8 m/km climbing); the Euros course is 16.6 m/km.")
    ap.add_argument("--sims", type=int, default=50000)
    ap.add_argument("--no-backtest", action="store_true")
    a = ap.parse_args()

    res = pd.read_csv(Path(a.data) / "itt_results_pcs.csv")
    start = pd.read_csv(Path(a.data) / "euro_itt_2026_startlist.csv")
    raw, cw = to_raw(res, a.flat_weight)
    print(f"rows {len(raw)} races {raw['event_id'].nunique()} hilly races "
          f"{raw.loc[raw['category'] == 'ME', 'event_id'].nunique()} · Euros course {EURO_M_PER_KM:.1f} m/km")

    ids, bad = book_ids(pd.concat([res[["rider", "rider_url"]], start[["rider", "rider_url"]]]))
    if bad:
        print("UNMATCHED BOOK NAMES (fix before trusting prices):\n  " + "\n  ".join(bad))
    on_list = set(start["rider_url"])
    for k, u in ids.items():
        if u not in on_list:
            print(f"not on the start list yet: {k} ({u})")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if not a.no_backtest:
        bt = backtest(raw, cw, a.half_life, 20000)
        bt.to_csv(out / "backtest.csv", index=False)
        print("\nBACKTEST (walk-forward, 2025-26 races with 30+ finishers)")
        print(bt.to_string(index=False, float_format="%.3f"))
        print(f"mean p(actual winner) {bt['p_winner'].mean():.3f} · mean spearman {bt['spearman'].mean():.3f} · "
              f"favourite won {(bt['winner'] == bt['model_fav']).mean():.0%} of {len(bt)}")

    m = fit(raw, cw, a.half_life)
    field = list(dict.fromkeys(list(start["rider_url"]) + [ids[k] for k in BOOK if k in ids]))
    t = simulate(m, field, a.sims, 7)
    rk = ranks(t)
    col = {u: j for j, u in enumerate(field)}
    nres = raw[raw["status"] == "OK"].groupby("rider_id").size()
    print(f"\nmodel: tau {m['tau']:.4f} sigma {m['sigma']:.4f} incident rate {m['p0']:.3f} · field {len(field)}")

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
    fut.to_csv(out / "futures.csv", index=False)
    print("\nFUTURES (edge = win_p x book - 1)")
    print(fut.to_string(index=False, float_format="%.3f"))

    mu_rows = []
    for x, ox, y, oy in MATCHUPS:
        if x not in ids or y not in ids:
            continue
        px = (t[:, col[ids[x]]] < t[:, col[ids[y]]]).mean()
        mu_rows.append(dict(a=x, a_odds=ox, a_p=px, a_edge=px * ox - 1, b=y, b_odds=oy, b_p=1 - px,
                            b_edge=(1 - px) * oy - 1, a_results=int(nres.get(ids[x], 0)),
                            b_results=int(nres.get(ids[y], 0))))
    mu = pd.DataFrame(mu_rows)
    mu.to_csv(out / "matchups.csv", index=False)
    print("\nMATCHUPS")
    print(mu.to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
