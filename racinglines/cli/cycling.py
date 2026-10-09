"""
racinglines cycling <command>: road cycling sportsbook lines (winner, head-to-head) from results, on the timed-runs
engine (racinglines/models/cycling.py; workflow in docs/road-cycling.md). Everything per race is in an event file,
sports/road_cycling/events/<event>.toml; everything per kind of race (itt, road) in sports/road_cycling.toml.

    events       List the event files.
    fetch        Fetch ProCyclingStats results for a kind (itt | road) into data/raw/road_cycling/ (Mac only:
                 cached per page, safe to re-run; `pip install cloudscraper selectolax` first).
    startlist    Fetch an event's start list (its [event] pcs race) into its startlist_file.
    probe        Fetch one PCS page (e.g. race/milano-sanremo/2025/result), save its HTML under
                 data/raw/road_cycling/pcs/probe/ and print what parses from it: the first check when a fetch fails.
    price        Price an event's book: futures, matchups and fractional-Kelly stakes, written to
                 reports/<event>/. --calibrate grid-searches the kind's [model.<kind>.grid] walk-forward first
                 and prices with the best setting; --settings-from prices with a saved setting row.
    reliability  Calibration check for a kind (itt | road): every rider's walk-forward win / top-3 / top-10 chance
                 in every backtest race vs what happened, by probability bucket and by model rank (favourites vs
                 long shots), plus the best-fitting temperature. Writes reports/reliability-<kind>/.

Nothing here runs by default, writes to the database, or touches the VM.
"""

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from racinglines.paths import ROOT


def _years(spec):
    a, _, b = spec.partition("-")
    return list(range(int(a), int(b or a) + 1))


def _value(v):
    try:
        return float(v)
    except ValueError:
        return v


def _show(title, df):
    print(f"\n{title}")
    print(df.to_string(index=False, float_format="%.3f") if len(df) else "(none)")


def cmd_price(a):
    from racinglines.models import cycling as C
    ev = C.load_event(a.event)
    kind = ev["event"]["kind"]
    block = C.model_block(kind)
    s = dict(ev["settings"])
    if a.settings_from:
        row = pd.read_csv(a.settings_from).iloc[0]
        s = {k: float(row[k]) if k in row else v for k, v in s.items()}
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        if k not in s:
            raise SystemExit(f"unknown setting {k!r}; settings for {kind}: {', '.join(s)}")
        s[k] = _value(v)

    res = C.load_results(kind, a.data)
    start = pd.read_csv(C.startlist_file(ev, a.data))
    raw = C.to_raw(res, kind, block["rules"])
    kinds = raw.groupby("event_id")["category"].first().value_counts().to_dict()
    print(f"{ev['event']['name']} ({kind}, {ev['event']['date']}) · {len(raw)} rows, {raw['event_id'].nunique()} "
          f"races by kind {kinds} (ME/MF hilly/flat strong field, WH/WF weak field, GC stage-race GC) · start list "
          f"{len(start)}")
    ids, bad = C.book_ids(ev, start, res)
    if bad:
        print("UNMATCHED BOOK NAMES (these lines are not priced; fix [names] in the event file):\n  " +
              "\n  ".join(bad))
    off = [k for k, u in ids.items() if u not in set(start["rider_url"])]
    if off:
        print(f"not on the start list: {', '.join(off)} (priced anyway; check the book's non-starter rule)")

    out = Path(a.out or ROOT / "reports" / ev["id"])
    out.mkdir(parents=True, exist_ok=True)
    terrain = ev["event"].get("terrain", "hilly")
    if a.calibrate:
        tr = C.target_races(raw, kind, a.since)
        seasons = tr["date"].str[:4].value_counts().sort_index().to_dict()
        print(f"backtest races since {a.since}: {len(tr)} by season {seasons}")
        full = [y for y in range(int(a.since[:4]), int(ev["event"]["date"][:4])) if seasons.get(str(y), 0) >= 5]
        if len(full) < 5:
            print(f"WARNING: only {len(full)} complete seasons with 5+ backtest races ({full})")
        grid = block["grid"]
        settings = [{**s, **dict(zip(grid, v))} for v in itertools.product(*grid.values())]
        if s not in settings:
            settings.append(dict(s))                       # the current default is always scored too
        print(f"calibrating {len(settings)} settings walk-forward ...", flush=True)
        bt = C.backtest(raw, kind, settings, a.since, terrain)
        bt.to_csv(out / "calibration_races.csv", index=False)
        summ = C.summarize(bt, list(s))
        summ.to_csv(out / "calibration.csv", index=False)
        _show("CALIBRATION (best 12 by mean rank of win_ll and pair_ll; lower is better)", summ.head(12))
        print(f"reference: a coin flip scores pair_ll {np.log(2):.3f}; picking the winner uniformly from a "
              f"{int(tr['n'].median())}-rider field scores win_ll {np.log(tr['n'].median()):.3f}")
        before = summ.merge(pd.DataFrame([s]), on=list(s))
        _show("schema / event default", before)
        s = {k: float(summ.iloc[0][k]) for k in s}
        mine = bt.merge(pd.DataFrame([s]), on=list(s))
        print("\nchosen setting by season:")
        print(mine.groupby(mine["date"].str[:4]).agg(races=("race", "size"), win_ll=("win_ll", "mean"),
                                                     pair_ll=("pair_ll", "mean"), fav_won=("fav_won", "mean"))
              .to_string(float_format="%.3f"))

    fut, mu, m = C.price(ev, raw, start, ids, s, a.sims)
    noise = s["noise_scale"] * np.hypot(m["tau"], m["sigma"])
    print(f"\nsettings {json.dumps(s)}\nmodel: noise {noise:.4f} (fitted {np.hypot(m['tau'], m['sigma']):.4f}) "
          f"incident rate {s['incident_scale'] * m['p0']:.3f}")
    _show("FUTURES (edge = win_p x book - 1; results = race results, gc = stage-race GCs, out_p = DNF or out)", fut)
    _show("MATCHUPS (p leaves out sims where both riders are out, which most books void)", mu)
    b = C.stakes(fut, mu, a.bankroll, a.kelly)
    _show(f"STAKES ({a.kelly:g} Kelly on ${a.bankroll:.0f}; thin_data = under 5 results)", b)
    print(f"total ${b['stake'].sum():.2f} · futures ${b.loc[b['bet'].str.endswith('to win'), 'stake'].sum():.2f}")
    pd.DataFrame([s]).to_csv(out / "settings.csv", index=False)
    fut.to_csv(out / "futures.csv", index=False)
    mu.to_csv(out / "matchups.csv", index=False)
    b.to_csv(out / "stakes.csv", index=False)
    print(f"wrote {out}/ settings.csv futures.csv matchups.csv stakes.csv")
    return 0


def cmd_reliability(a):
    from racinglines.models import cycling as C
    block = C.model_block(a.kind)
    s = dict(block["defaults"])
    if a.settings_from:
        row = pd.read_csv(a.settings_from).iloc[0]
        s = {k: float(row[k]) if k in row else v for k, v in s.items()}
    raw = C.to_raw(C.load_results(a.kind, a.data), a.kind, block["rules"])
    tr = C.target_races(raw, a.kind, a.since)
    print(f"{a.kind}: {len(tr)} backtest races since {a.since} "
          f"{tr['date'].str[:4].value_counts().sort_index().to_dict()} · settings {json.dumps(s)}", flush=True)
    rel = C.reliability(raw, a.kind, s, a.since, a.terrain, a.sims)
    if rel.empty:
        raise SystemExit("no backtest race had 10+ earlier races to fit on")
    out = Path(a.out or ROOT / "reports" / f"reliability-{a.kind}")
    out.mkdir(parents=True, exist_ok=True)
    rel.to_csv(out / "reliability_riders.csv", index=False)
    tables = {"win_by_prob": ("p_win", "won", C.WIN_BUCKETS), "win_by_rank": ("model_rank", "won", C.RANK_BUCKETS),
              "top3_by_rank": ("model_rank", "top3", C.RANK_BUCKETS),
              "top10_by_rank": ("model_rank", "top10", C.RANK_BUCKETS)}
    for name, (by, hit, edges) in tables.items():
        t = C.reliability_table(rel, by, hit, edges)
        t.to_csv(out / f"{name}.csv", index=False)
        _show(f"{name.upper()} (z > 2: the model under-rates this bucket; z < -2: over-rates it)", t)
    temp = C.temperature(rel)
    pd.DataFrame([temp]).to_csv(out / "temperature.csv", index=False)
    print(f"\ntemperature over {temp['races']} races: best a = {temp['a']:.2f} (a > 1: favourites too long) · "
          f"winner log loss {temp['win_ll_a1']:.3f} at a = 1, {temp['win_ll_best']:.3f} at best a (in-sample)")
    print(f"wrote {out}/ reliability_riders.csv {' '.join(f'{n}.csv' for n in tables)} temperature.csv")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines cycling", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("events", help="list the event files")
    f = sub.add_parser("fetch", help="fetch ProCyclingStats results for a kind (Mac only)")
    f.add_argument("kind", choices=["itt", "road"])
    f.add_argument("--seasons", default="2020-2026", help="e.g. 2020-2026")
    f.add_argument("--data", help="results folder (default: [results] dir)")
    f.add_argument("--limit", type=int, help="fetch at most this many pages (a dry check)")
    sl = sub.add_parser("startlist", help="fetch an event's start list (Mac only)")
    sl.add_argument("event")
    sl.add_argument("--data")
    pr = sub.add_parser("probe", help="fetch one PCS page, save it and show what parses (Mac only)")
    pr.add_argument("url", help="PCS path, e.g. race/milano-sanremo/2025/result")
    p = sub.add_parser("price", help="price an event's book")
    p.add_argument("event", help="event id (file stem in sports/road_cycling/events/) or a path to an event file")
    p.add_argument("--data", help="results folder (default: [results] dir)")
    p.add_argument("--out", help="output folder (default: reports/<event>/)")
    p.add_argument("--calibrate", action="store_true", help="grid-search [model.<kind>.grid] walk-forward first")
    p.add_argument("--since", default="2021-01-01", help="first backtest race date (--calibrate)")
    p.add_argument("--settings-from", help="price with the first row of this CSV (calibration.csv, settings.csv)")
    p.add_argument("--set", action="append", metavar="KEY=VALUE", help="override one setting, e.g. noise_scale=1.2")
    p.add_argument("--sims", type=int, default=50000)
    p.add_argument("--bankroll", type=float, default=400.0)
    p.add_argument("--kelly", type=float, default=0.25, help="Kelly fraction (0.25 = quarter Kelly)")
    r = sub.add_parser("reliability", help="calibration check: favourites vs long shots, walk-forward")
    r.add_argument("kind", choices=["itt", "road"])
    r.add_argument("--data", help="results folder (default: [results] dir)")
    r.add_argument("--out", help="output folder (default: reports/reliability-<kind>/)")
    r.add_argument("--since", default="2021-01-01", help="first backtest race date")
    r.add_argument("--settings-from", help="settings row CSV (settings.csv from a price run); default: schema")
    r.add_argument("--terrain", default="hilly", choices=["hilly", "flat"])
    r.add_argument("--sims", type=int, default=4000)
    a = ap.parse_args(argv)

    if a.cmd == "events":
        from racinglines.models import cycling as C
        for e in C.list_events():
            ev = C.load_event(e)["event"]
            print(f"{e:40} {ev['kind']:5} {ev['date']}  {ev['name']}")
        return 0
    if a.cmd == "fetch":
        from racinglines.sources import pcs
        pcs.fetch(a.kind, _years(a.seasons), a.data, a.limit)
        return 0
    if a.cmd == "startlist":
        from racinglines.models import cycling as C
        from racinglines.sources import pcs
        ev = C.load_event(a.event)
        pcs.fetch_startlist(ev["event"]["pcs"], C.startlist_file(ev, a.data))
        return 0
    if a.cmd == "probe":
        from racinglines.models import cycling as C
        from racinglines.sources import pcs
        pcs.probe(a.url, ROOT / C.schema()["results"]["dir"] / "pcs" / "probe")
        return 0
    if a.cmd == "reliability":
        return cmd_reliability(a)
    return cmd_price(a)
