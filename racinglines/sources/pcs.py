"""
ProCyclingStats results for road cycling, driven by sports/road_cycling.toml [results] (which races, which seasons,
which kinds). Runs on the owner's Mac only: the cloud sandbox can't reach procyclingstats.com, and the site sits
behind Cloudflare, so the `procyclingstats` package is used with `cloudscraper` installed (owner OK'd 2026-10-05).
Neither is in requirements.txt (nothing on the VM needs them): `pip install procyclingstats cloudscraper`.

Every page is cached as one CSV under <dir>/pcs/<kind>/, so a re-run fetches only what's missing, and the results
file for the kind ([results] files) is rebuilt from the cache at the end. One request at a time, `pace_s` apart.

    fetch(kind, seasons)                 every race of a kind -> results file (rows per finisher, see COLUMNS)
    fetch_startlist(pcs_race, out_csv)   a race's start list -> rider, rider_url, nationality, team
    stage_rows(...)                      one results page's rows (pure: takes the package's parsed table)
"""

import re
import time
from pathlib import Path

import pandas as pd

from racinglines import progress, sports
from racinglines.paths import ROOT

COLUMNS = ["race", "kind", "date", "race_class", "distance_km", "vert_m", "profile_score", "profile_icon", "rider",
           "rider_url", "nationality", "position", "gap_s", "winner_time_s", "status", "source_url"]
STATUS = {"DF": "OK", "": "OK", "DNF": "DNF", "OTL": "DNF", "DNS": "DNS", "DSQ": "DSQ"}


def _pcs():
    try:
        import procyclingstats
    except ImportError as ex:
        raise SystemExit("pip install procyclingstats cloudscraper (Mac only; see racinglines/sources/pcs.py)") from ex
    return procyclingstats


def _try(f, default=None):
    try:
        v = f()
        return default if v in (None, "") else v
    except Exception:
        return default


def hms(s):
    """'1:02:03', '27:12', '0:00:15' or '+0:15' -> seconds; None when it isn't a time."""
    s = str(s or "").strip().lstrip("+")
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}", s):
        return None
    sec = 0
    for part in s.split(":"):
        sec = sec * 60 + int(part)
    return sec


def stage_rows(table, info, race, kind, url):
    """Rows for one results page. `table` is the package's results (or GC) table, `info` the page's date and
    course. PCS gives the winner's time and, for the rest, either their own time or their gap: anything shorter
    than the winner's time is a gap."""
    rows, win = [], None
    for r in table:
        t = hms(r.get("time"))
        status = STATUS.get(str(r.get("status") or "").upper(), "OK")
        pos = r.get("rank")
        if status == "OK" and pos in (None, "", 0):
            status = "DNF"
        if status == "OK" and win is None and t:
            win = t
        if t is None or win is None:
            gap = None
        else:
            gap = t - win if t >= win else t
        rows.append(dict(race=race, kind=kind, date=info.get("date"), race_class=info.get("race_class"),
                         distance_km=info.get("distance_km"), vert_m=info.get("vert_m"),
                         profile_score=info.get("profile_score"), profile_icon=info.get("profile_icon"),
                         rider=r.get("rider_name"), rider_url=r.get("rider_url"), nationality=r.get("nationality"),
                         position=pos if status == "OK" else None, gap_s=gap,
                         winner_time_s=win, status=status, source_url=url))
    return rows


def _info(st):
    cls = _try(lambda: st._stage_info_by_label("Classification")) or _try(st.uci_points_scale)
    return dict(date=_try(st.date), distance_km=_try(st.distance), vert_m=_try(st.vertical_meters),
                profile_score=_try(st.profile_score), profile_icon=_try(st.profile_icon), race_class=cls)


def _pages(kind, block, years, pcs, pace):
    """(race label, page kind, url) for every page a kind needs, in season order."""
    for y in years:
        for slug in block.get("one_day", []):
            yield f"{slug}-{y}", "oneday", f"race/{slug}/{y}/result"
        for slug in block.get("stage_races", []) + block.get("stage_race_gc", []):
            race = _try(lambda slug=slug, y=y: pcs.Race(f"race/{slug}/{y}"))
            time.sleep(pace)
            stages = _try(lambda race=race: race.stages("stage_name", "stage_url"), []) if race else []
            if kind == "itt":
                for s in stages:
                    name = str(s.get("stage_name", ""))
                    if re.search(r"\bITT\b", name) and "TTT" not in name:
                        yield f"{slug}-{y}-{s['stage_url'].rsplit('/', 1)[-1]}", "oneday", s["stage_url"]
            elif stages and slug in block.get("stage_race_gc", []):
                yield f"{slug}-{y}", "gc", stages[-1]["stage_url"]


def fetch(kind, seasons, data_dir=None, limit=None):
    """Fetch every page of [results.<kind>] for `seasons` (cached per page), then rebuild the kind's results file.
    Returns the results frame."""
    pcs = _pcs()
    r = sports.load("road_cycling")["results"]
    block = r[kind]
    pace = float(r.get("pace_s", 2.0))
    base = Path(data_dir or ROOT / r["dir"])
    cache = base / "pcs" / kind
    cache.mkdir(parents=True, exist_ok=True)
    pages = list(_pages(kind, block, seasons, pcs, pace))[:limit]
    failed = []
    for i, (race, page_kind, url) in enumerate(pages, 1):
        progress.update(i, len(pages), race)
        f = cache / f"{race}.csv"
        if f.exists():
            continue
        try:
            st = pcs.Stage(url)
            table = st.gc("rider_name", "rider_url", "nationality", "rank", "time") if page_kind == "gc" else \
                st.results("rider_name", "rider_url", "nationality", "rank", "status", "time")
            rows = stage_rows(table, _info(st), race, page_kind, url)
            pd.DataFrame(rows, columns=COLUMNS).to_csv(f, index=False)
            print(f"{race} | {len(rows)}", flush=True)
        except Exception as ex:
            failed.append(race)
            print(f"{race} | FAILED {type(ex).__name__}: {ex}", flush=True)
        time.sleep(pace)
    out = pd.concat([pd.read_csv(p) for p in sorted(cache.glob("*.csv"))], ignore_index=True)
    dest = base / r["files"][kind]
    if dest.exists() and "kind" not in pd.read_csv(dest, nrows=1).columns:   # a file this module didn't write
        dest.rename(dest.with_suffix(".before-fetch.csv"))
        print(f"kept the earlier {dest.name} as {dest.with_suffix('.before-fetch.csv').name}", flush=True)
    out.to_csv(dest, index=False)
    print(f"{kind}: {out['race'].nunique()} races, {len(out)} rows -> {dest} · {len(failed)} failed "
          f"{failed[:10]}", flush=True)
    return out


def fetch_startlist(pcs_race, out_csv):
    """A race's start list (e.g. race/tre-valli-varesine/2026) -> rider, rider_url, nationality, team."""
    pcs = _pcs()
    sl = pcs.RaceStartlist(f"{pcs_race}/startlist").startlist("rider_name", "rider_url", "nationality", "team_name")
    df = pd.DataFrame(sl).rename(columns={"rider_name": "rider", "team_name": "team"})
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"start list {pcs_race}: {len(df)} riders -> {out_csv}", flush=True)
    return df
