"""
Download MotoGP's public results API (https://api.motogp.pulselive.com/motogp/v1/, no auth) into
data/raw/motogp/pulselive/<year>/, one JSON file per call, byte-for-byte as served. Endpoints and shape
were probed from the owner's machine on 2026-09-29 (tests/fixtures/market/motogp_README.txt).

    seasons.json                                every season (id, year), fetched once
    <year>/events.json                          the season's events (circuit, dates, status)
    <year>/categories.json                       the season's categories (MotoGP/Moto2/Moto3, id + legacy_id)
    <year>/<event_short_name>/sessions.json      MotoGP-class sessions of that event (FP1, PR, FP2, Q1, Q2, SPR, WUP, RAC)
    <year>/<event_short_name>/classification.json   the RAC (race) session's classification: one row per rider

Only the MotoGP class is fetched (sports/motogp.toml's only competition, "Riders"); Moto2/Moto3 are a separate
competition this repo does not track. Only the race session's classification is fetched for now (sprints,
listed since 2023, are a follow-up). Terms of use: sports/motogp.toml [results].terms.

Requests go through sources/http.py (paced per host). Already-downloaded files are skipped, so this is safe to
re-run; --force asks again. An event with no RAC session yet (not run, or a test) is recorded as such and skipped.
"""

import json

import httpx

from racinglines import paths
from racinglines.sources import http

BASE = "https://api.motogp.pulselive.com/motogp/v1"
OUT = paths.raw("motogp", "pulselive")
CATEGORY_NAME = "MotoGP"          # the only class this repo tracks (sports/motogp.toml)


def client():
    return httpx.Client(base_url=BASE, timeout=30, headers={"User-Agent": "racinglines-research/1.0"})


def get(c, path, **params):
    r = http.get(c, path, params=params or None)
    r.raise_for_status()
    return r.json()


def season_path(year):
    return OUT / str(year)


def event_path(year, short_name):
    return season_path(year) / short_name


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def _read(path):
    return json.loads(path.read_text()) if path.exists() else None


def seasons(force=False):
    """{year: seasonUuid}, fetching once (cached at seasons.json) unless --force."""
    path = OUT / "seasons.json"
    rows = None if force else _read(path)
    if rows is None:
        with client() as c:
            rows = get(c, "/results/seasons")
        _write(path, rows)
    return {r["year"]: r["id"] for r in rows}


def fetch(years, force=False, dry_run=False):
    """Download events, the MotoGP category id, every finished session and its classification for each season in
    `years`. The public JSON does not expose lap-by-lap or sector data, but it does expose a result table per
    session (FP/Q/WUP/SPR/RAC), which is enough to match the F1-like session pipeline without inventing a richer
    source. A dry run still fetches the cheap season-level lists (events, categories: one call each) to count
    accurately, but never the many per-event sessions/classification calls. Returns counts: {seasons, events,
    classifications, skipped, errors}."""
    counts = dict(seasons=0, events=0, classifications=0, skipped=0, errors=0)
    season_ids = seasons(force=force)
    with client() as c:
        for year in years:
            season_id = season_ids.get(year)
            if season_id is None:
                counts["errors"] += 1
                continue
            ev_path = season_path(year) / "events.json"
            events = None if force else _read(ev_path)
            cat_path = season_path(year) / "categories.json"
            cats = None if force else _read(cat_path)
            if events is None:
                events = get(c, "/results/events", seasonUuid=season_id)
                if not dry_run:
                    _write(ev_path, events)
            if cats is None:
                cats = get(c, "/results/categories", seasonUuid=season_id)
                if not dry_run:
                    _write(cat_path, cats)
            if dry_run:
                counts["seasons"] += 1
                counts["events"] += sum(1 for ev in events if not ev.get("test"))
                continue
            cat_id = next((cc["id"] for cc in cats if cc["name"].startswith(CATEGORY_NAME)), None)
            counts["seasons"] += 1
            if cat_id is None:
                counts["errors"] += 1
                continue
            for ev in events:
                if ev.get("test"):
                    continue
                short = ev["short_name"]
                sess_path = event_path(year, short) / "sessions.json"
                cls_path = event_path(year, short) / "classification.json"
                if dry_run:
                    counts["events"] += 1
                    continue
                sessions = None if force else _read(sess_path)
                if sessions is None:
                    try:
                        sessions = get(c, "/results/sessions", eventUuid=ev["id"], categoryUuid=cat_id)
                    except httpx.HTTPStatusError:
                        counts["errors"] += 1
                        continue
                    _write(sess_path, sessions)
                race = next((s for s in sessions if s.get("type") == "RAC"), None)
                counts["events"] += 1
                if race is None:
                    counts["skipped"] += 1
                    continue
                fetched = False
                for session in sessions:
                    stype = session.get("type")
                    sid = session.get("id")
                    if not sid or stype not in {"FP", "PR", "Q1", "Q2", "SPR", "WUP", "RAC"}:
                        continue
                    if session.get("status") == "NOT-STARTED":
                        continue
                    session_cls_path = event_path(year, short) / f"{sid}.classification.json"
                    if not force and session_cls_path.exists():
                        continue
                    try:
                        cls = get(c, f"/results/session/{sid}/classification", test="false")
                    except httpx.HTTPStatusError:
                        counts["errors"] += 1
                        continue
                    _write(session_cls_path, cls)
                    if stype == "RAC":
                        _write(cls_path, cls)
                    fetched = True
                    counts["classifications"] += 1
                if not fetched and race.get("status") != "FINISHED":
                    counts["skipped"] += 1
    return counts
