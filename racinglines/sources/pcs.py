"""
ProCyclingStats results for road cycling, driven by sports/road_cycling.toml [results] (which races, which seasons,
which kinds). Runs on the owner's Mac only: the cloud sandbox can't reach procyclingstats.com, and the site sits
behind Cloudflare, so pages are fetched with `cloudscraper` (owner OK'd 2026-10-05) and parsed here with
`selectolax`. Neither is in requirements.txt (nothing on the VM needs them): `pip install cloudscraper selectolax`.

The pages are parsed here rather than by the `procyclingstats` package because the package's results selector
(`.resultCont .resTab .general table.results`) stopped matching PCS's markup on 2026-10-05 ("Results table not in
page HTML" on every page). This module looks for the first `table.results` with rider links anywhere on the page
and reads columns by their header, so a moved container doesn't break it.

Every page is cached as one CSV under <dir>/pcs/<kind>/, so a re-run fetches only what's missing, and the results
file for the kind ([results] files) is rebuilt from the cache at the end. One request at a time, `pace_s` apart.

    fetch(kind, seasons)                 every race of a kind -> results file (rows per finisher, see COLUMNS)
    fetch_startlist(pcs_race, out_csv)   a race's start list -> rider, rider_url, nationality, team
    probe(url, out_dir)                  fetch one page, save its HTML, print what parses (for debugging)
    parse_results(html) / page_info(html) / parse_startlist(html) / stage_rows(...)   pure, tested on fixtures
"""

import re
import time
from pathlib import Path

import pandas as pd

from racinglines import progress, sports
from racinglines.paths import ROOT

BASE = "https://www.procyclingstats.com/"
COLUMNS = ["race", "kind", "date", "race_class", "distance_km", "vert_m", "profile_score", "profile_icon", "rider",
           "rider_url", "nationality", "position", "gap_s", "winner_time_s", "status", "source_url"]
STATUS = {"DF": "OK", "": "OK", "DNF": "DNF", "OTL": "DNF", "DNS": "DNS", "DSQ": "DSQ", "DSQ*": "DSQ"}
_session = None


def _get(url):
    global _session
    if _session is None:
        try:
            import cloudscraper
        except ImportError as ex:
            raise SystemExit("pip install cloudscraper selectolax (Mac only; see racinglines/sources/pcs.py)") from ex
        _session = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin", "mobile": False})
    r = _session.get(BASE + url.lstrip("/"), timeout=60)
    r.raise_for_status()
    if "Page not found" in r.text[:5000]:
        raise ValueError(f"PCS has no page {url}")
    return r.text


def _tree(html):
    try:
        from selectolax.lexbor import LexborHTMLParser as Parser   # selectolax 0.3.x and 1.x
    except ImportError:
        from selectolax.parser import HTMLParser as Parser          # older releases
    return Parser(html)


def hms(s):
    """'1:02:03', '27:12', '0:00:15' or '+0:15' -> seconds; None when it isn't a time."""
    s = str(s or "").strip().lstrip("+").replace(" ", "")
    if not re.fullmatch(r"\d+(:\d{1,2}){0,2}", s):
        return None
    sec = 0
    for part in s.split(":"):
        sec = sec * 60 + int(part)
    return sec


def _rider_href(href):
    """'/rider/tadej-pogacar', 'https://www.procyclingstats.com/rider/tadej-pogacar' -> 'rider/tadej-pogacar'."""
    i = href.find("rider/")
    return href[i:].rstrip("/") if i >= 0 else None


def _rider_table(tree):
    for t in tree.css("table.results") + tree.css("table"):
        if t.css_first('tbody a[href*="rider/"]'):
            return t
    return None


def _cell_time(td):
    """A time cell's own time: the first line that isn't a ',,' (same as the rider above) or a seconds mark."""
    for line in td.text(separator="\n").split("\n"):
        line = line.strip()
        if line and line != "-" and ",," not in line and "″" not in line:
            return line
    return None


def parse_results(html):
    """The page's results table -> [{rider_name, rider_url, nationality, rank, status, time}], in table order.
    `time` is the cell as shown (the winner's time, then gaps); a blank or ',,' cell repeats the row above."""
    tree = _tree(html)
    table = _rider_table(tree)
    if table is None:
        raise ValueError("no results table with rider links on the page")
    heads = [th.text(strip=True).lower() for th in table.css("thead th")]

    def col(*names):
        return next((i for i, h in enumerate(heads) if h in names), None)

    i_rank, i_time = col("rnk", "pos", "#", "result"), col("time")
    rows, prev = [], None
    for tr in table.css("tbody tr"):
        a = tr.css_first('a[href*="rider/"]')
        if a is None:
            continue
        tds = tr.css("td")
        rank_txt = tds[i_rank if i_rank is not None and i_rank < len(tds) else 0].text(strip=True)
        tcell = next((td for td in tds if "time" in (td.attributes.get("class") or "").split()), None)
        if tcell is None and i_time is not None and i_time < len(tds):
            tcell = tds[i_time]
        t = _cell_time(tcell) if tcell is not None else None
        t = t if hms(t) is not None else prev
        prev = t
        flag = tr.css_first(".flag")
        fl = (flag.attributes.get("class") or "").split() if flag else []
        rows.append(dict(rider_name=a.text(strip=True), rider_url=_rider_href(a.attributes.get("href") or ""),
                         nationality=fl[1].upper() if len(fl) > 1 else None,
                         rank=int(rank_txt) if rank_txt.isdigit() else None,
                         status="DF" if rank_txt.isdigit() else rank_txt.upper(), time=t))
    if not rows:
        raise ValueError("results table has no rider rows")
    return rows


INFO = {"date": "Date", "distance_km": "Distance", "vert_m": "Vertical meters", "profile_score": "ProfileScore",
        "race_class": "Classification"}


def page_info(html):
    """Date (ISO), distance (km), vertical metres, ProfileScore, UCI class and profile icon (p0-p5), read from the
    page's labelled info lines wherever they sit. Missing values are None."""
    tree = _tree(html)
    body = tree.body or tree.root
    lines = [x.strip() for x in body.text(separator="\n").split("\n") if x.strip()]
    out = {}
    for key, label in INFO.items():
        val = None
        for i, x in enumerate(lines):
            if x.rstrip(":") == label or x.startswith(label + ":"):
                rest = x[len(label):].lstrip(":").strip()
                val = rest or (lines[i + 1] if i + 1 < len(lines) else None)
                break
        out[key] = val
    d = re.search(r"\d{1,2} \w+ \d{4}|\d{4}-\d{2}-\d{2}", out["date"] or "")
    out["date"] = pd.to_datetime(d.group(0)).date().isoformat() if d else None
    for key in ("distance_km", "vert_m", "profile_score"):
        m = re.search(r"\d+(\.\d+)?", (out[key] or "").replace(",", ""))
        out[key] = float(m.group(0)) if m else None
    m = re.search(r"\bprofile (p[0-5])\b", html)
    out["profile_icon"] = m.group(1) if m else None
    return out


def parse_startlist(html):
    """A start list page -> [{rider, rider_url, nationality, team}]: every rider link inside the start list block
    (the smallest element holding nearly all the page's rider links), with the nearest team link above it."""
    tree = _tree(html)
    nodes = [(len(n.css('a[href*="rider/"]')), len(n.html or ""), n) for n in tree.css("ul, table, div")]
    top = max((n for n, _, _ in nodes), default=0)
    if not top:
        return []
    best = min((x for x in nodes if x[0] >= 0.9 * top), key=lambda x: x[1])[2]   # smallest block holding them
    rows, team, seen = [], None, set()
    for a in best.css("a"):
        href = a.attributes.get("href") or ""
        if "team/" in href:
            team = a.text(strip=True)
        elif "rider/" in href:
            u = _rider_href(href)
            if u and u not in seen:
                seen.add(u)
                rows.append(dict(rider=a.text(strip=True), rider_url=u, nationality=None, team=team))
    return rows


def stage_rows(table, info, race, kind, url):
    """Rows for one results page. `table` is parse_results' output, `info` page_info's. The first finisher's time
    is the winner's; every later time shorter than it is a gap."""
    rows, win = [], None
    for r in table:
        t = hms(r.get("time"))
        status = STATUS.get(str(r.get("status") or "").upper(), "DNF")
        pos = r.get("rank")
        if status == "OK" and pos in (None, "", 0):
            status = "DNF"
        if status == "OK" and win is None and t:
            win = t
        if t is None or win is None or status != "OK":
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


def _itt_stages(html, slug, year):
    """ITT stage pages of a stage race, from its overview page: stage links whose row says ITT (not TTT)."""
    out = []
    for tr in _tree(html).css("tr"):
        a = tr.css_first(f'a[href*="race/{slug}/{year}/stage-"]')
        txt = tr.text(separator=" ")
        if a is not None and re.search(r"\bITT\b", txt) and "TTT" not in txt:
            href = a.attributes.get("href") or ""
            out.append(href[href.find("race/"):].split("?")[0].rstrip("/"))
    return list(dict.fromkeys(out))


def _pages(kind, block, years, pace):
    """(race label, page kind, url) for every page a kind needs, in season order."""
    for y in years:
        for slug in block.get("one_day", []):
            yield f"{slug}-{y}", "oneday", f"race/{slug}/{y}/result"
        for slug in block.get("stage_race_gc", []):
            yield f"{slug}-{y}", "gc", f"race/{slug}/{y}/gc"
        for slug in block.get("stage_races", []):
            try:
                stages = _itt_stages(_get(f"race/{slug}/{y}"), slug, y)
            except Exception as ex:
                print(f"{slug}-{y} | FAILED stage list {type(ex).__name__}: {ex}", flush=True)
                stages = []
            time.sleep(pace)
            for u in stages:
                yield f"{slug}-{y}-{u.rsplit('/', 1)[-1]}", "oneday", u


def fetch(kind, seasons, data_dir=None, limit=None):
    """Fetch every page of [results.<kind>] for `seasons` (cached per page), then rebuild the kind's results file.
    Returns the results frame."""
    r = sports.load("road_cycling")["results"]
    block = r[kind]
    pace = float(r.get("pace_s", 2.0))
    base = Path(data_dir or ROOT / r["dir"])
    cache = base / "pcs" / kind
    cache.mkdir(parents=True, exist_ok=True)
    pages = list(_pages(kind, block, seasons, pace))[:limit]
    failed, fetched = [], 0
    for i, (race, page_kind, url) in enumerate(pages, 1):
        progress.update(i, len(pages), race)
        f = cache / f"{race}.csv"
        if f.exists():
            continue
        try:
            html = _get(url)
            rows = stage_rows(parse_results(html), page_info(html), race, page_kind, url)
            pd.DataFrame(rows, columns=COLUMNS).to_csv(f, index=False)
            fetched += 1
            print(f"{race} | {len(rows)}", flush=True)
        except Exception as ex:
            failed.append(race)
            print(f"{race} | FAILED {type(ex).__name__}: {ex}", flush=True)
        time.sleep(pace)
        if fetched == 0 and len(failed) >= 10:
            raise SystemExit(f"the first {len(failed)} pages all failed; stopping. Run `racinglines cycling probe "
                             f"{pages[0][2]}` and report what it prints.")
    cached = sorted(cache.glob("*.csv"))
    if not cached:
        raise SystemExit(f"no pages fetched for {kind} ({len(failed)} failed); nothing written")
    out = pd.concat([pd.read_csv(p) for p in cached], ignore_index=True)
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
    df = pd.DataFrame(parse_startlist(_get(f"{pcs_race}/startlist")),
                      columns=["rider", "rider_url", "nationality", "team"])
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"start list {pcs_race}: {len(df)} riders, {df['team'].nunique()} teams -> {out_csv}", flush=True)
    return df


def probe(url, out_dir):
    """Fetch one page, save its HTML under out_dir, and print what parses from it."""
    html = _get(url)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    f = out / (url.strip("/").replace("/", "_") + ".html")
    f.write_text(html)
    print(f"{url}: {len(html)} bytes -> {f}")
    print(f"tables: {[t.attributes.get('class') for t in _tree(html).css('table')][:8]}")
    print(f"info: {page_info(html)}")
    if url.rstrip("/").endswith("startlist"):
        rows = parse_startlist(html)
        print(f"start list: {len(rows)} riders; first 3: {rows[:3]}")
    else:
        rows = parse_results(html)
        print(f"results: {len(rows)} rows; first 3: {rows[:3]}; last: {rows[-1]}")
