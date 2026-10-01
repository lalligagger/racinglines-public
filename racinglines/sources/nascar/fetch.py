"""
Download NASCAR's content feeds (https://cf.nascar.com/, no auth: static objects behind CloudFront) into
data/raw/nascar/cf/<year>/<series>/, one JSON file per feed, byte-for-byte as served. The endpoints and where
each one starts were probed from the owner's machine on 2026-09-29 (tests/fixtures/market/nascar_README.txt).

    <year>/<series>/race_list_basic.json          the season's races (id, name, date, track, laps, winner)
    <year>/<series>/points-feed.json              standings after the last race
    <year>/<series>/<race_id>/weekend-feed.json   results, stages, cautions, leaders, practice and qualifying   2017-
    <year>/<series>/<race_id>/lap-times.json      every lap of every car + a flag state per lap               2020-
    <year>/<series>/<race_id>/lap-notes.json      race-control notes per lap                                  2020-
    <year>/<series>/<race_id>/pit-data.json       every pit stop (live/ path on the server)                   2018-
    <year>/<series>/<race_id>/loopstats.json      driver rating, passes, fast laps, running positions         2019-

Series ids: 1 Cup, 2 Xfinity, 3 Trucks. A MISSING object is HTTP 403 (S3 AccessDenied), not 404: it means "no
such file" and is never retried. A missing feed is recorded as <name>.missing beside where it would be, so a
re-run does not ask again; --force asks again. Races run in the last few days are not marked missing (a feed
may simply not be published yet). Already-downloaded files are skipped, so this is safe to re-run after each
race weekend. Requests go through sources/http.py (one per second to the host).
"""

import json
from datetime import date, datetime, timedelta

import httpx

from racinglines import paths
from racinglines.sources import http

BASE = "https://cf.nascar.com/"
OUT = paths.NASCAR_RAW
SERIES = {1: "Cup", 2: "Xfinity", 3: "Trucks"}
RECENT_DAYS = 3                    # a race this recent that returns 403 is not marked missing

# season-level feeds: name -> (path template, first season it exists)
SEASON_FEEDS = {
    "race_list_basic": ("cacher/{year}/{series}/race_list_basic.json", 2015),
    "points-feed": ("cacher/{year}/{series}/points-feed.json", 2016),
}
# per-race feeds: name -> (path template, first season it exists)
RACE_FEEDS = {
    "weekend-feed": ("cacher/{year}/{series}/{race}/weekend-feed.json", 2017),
    "pit-data": ("cacher/live/series_{series}/{race}/live-pit-data.json", 2018),
    "loopstats": ("loopstats/prod/{year}/{series}/{race}.json", 2019),
    "lap-times": ("cacher/{year}/{series}/{race}/lap-times.json", 2020),
    "lap-notes": ("cacher/{year}/{series}/{race}/lap-notes.json", 2020),
}


def season_dir(year, series=1):
    return OUT / str(year) / str(series)


def feed_path(year, series, name, race=None):
    base = season_dir(year, series) / str(race) if race is not None else season_dir(year, series)
    return base / f"{name}.json"


def read(path):
    """The parsed JSON of a stored feed, or None when the file is absent or holds `null`."""
    return json.loads(path.read_text()) if path.exists() else None


def race_rows(year, series=1):
    """The season's races from the stored race list (empty until it has been fetched)."""
    rows = read(feed_path(year, series, "race_list_basic")) or []
    return sorted(rows, key=lambda r: (r.get("race_date") or "", r["race_id"]))


def _day(text):
    return date.fromisoformat(text[:10]) if text else None


def client():
    return httpx.Client(base_url=BASE, timeout=60, headers={"User-Agent": "racinglines-research/1.0"})


def get(c, url):
    """(status, body): the body of a 200; (403 or 404, None) for a missing object; anything else raises."""
    r = http.get(c, url)
    if r.status_code == 200:
        return 200, r.content
    if r.status_code in (403, 404):
        return r.status_code, None
    raise RuntimeError(f"{url}: HTTP {r.status_code}")


def _store(path, body):
    """Write a feed after checking it parses; a body of `null` (an empty feed) counts as missing."""
    if json.loads(body) is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    path.with_suffix(".missing").unlink(missing_ok=True)
    return True


def fetch_feed(c, url, path, force=False, mark_missing=True):
    """One feed to `path`: 'cached', 'fetched', 'missing' or 'skipped' (asked before and it was not there)."""
    marker = path.with_suffix(".missing")
    if not force:
        if path.exists():
            return "cached"
        if marker.exists():
            return "skipped"
    status, body = get(c, url)
    if body is not None and _store(path, body):
        return "fetched"
    if mark_missing:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"HTTP {status} at {datetime.now().astimezone().isoformat(timespec='seconds')}\n")
    return "missing"


def wanted(feeds, table):
    return list(table) if feeds is None else [f for f in feeds if f in table]


def fetch(years, series=1, feeds=None, races=None, force=False, dry_run=False, c=None, today=None, echo=print):
    """Fetch `feeds` (default all) for every finished race of the given seasons. `races` limits to those ids.
    Returns {"fetched", "cached", "missing", "skipped", "errors", "planned"}. With dry_run nothing is requested:
    "planned" counts the requests a real run would make, from the race lists already on disk (a season whose list
    was never fetched plans only its two season-level feeds, since its races are not known yet)."""
    today = today or date.today()
    counts = dict(fetched=0, cached=0, missing=0, skipped=0, errors=0, planned=0)
    own = c is None
    c = c if c is not None else client()
    try:
        for year in years:
            for name in wanted(feeds, SEASON_FEEDS):
                tpl, first = SEASON_FEEDS[name]
                if year < first:
                    continue
                path = feed_path(year, series, name)
                url = tpl.format(year=year, series=series)
                refresh = force or year == today.year         # the current season's list and standings change every race
                if dry_run:
                    counts["planned"] += 0 if path.exists() and not refresh else 1
                    continue
                _tally(counts, echo, f"{year} {name}", url, lambda: fetch_feed(c, url, path, force=refresh))
            for row in race_rows(year, series):
                rid = row["race_id"]
                if races and rid not in races:
                    continue
                day = _day(row.get("race_date"))
                if day is None or day >= today:
                    continue
                recent = (today - day) <= timedelta(days=RECENT_DAYS)
                for name in wanted(feeds, RACE_FEEDS):
                    tpl, first = RACE_FEEDS[name]
                    if year < first:
                        continue
                    path = feed_path(year, series, name, rid)
                    url = tpl.format(year=year, series=series, race=rid)
                    if dry_run:
                        if force or not (path.exists() or path.with_suffix(".missing").exists()):
                            counts["planned"] += 1
                        continue
                    _tally(counts, echo, f"{year} {rid} {name}", url,
                           lambda: fetch_feed(c, url, path, force=force, mark_missing=not recent))
    finally:
        if own:
            c.close()
    return counts


def _tally(counts, echo, label, url, run):
    try:
        status = run()
    except Exception as e:                       # keep going: one bad feed should not stop a backfill
        counts["errors"] += 1
        echo(f"  {label}: ERROR {type(e).__name__}: {e}")
        return
    counts[status] += 1
    if status in ("fetched", "missing"):
        echo(f"  {label}: {status}")
