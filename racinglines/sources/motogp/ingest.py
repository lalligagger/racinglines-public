"""
Load data/raw/motogp/pulselive/<year>/<event_short_name>/ (from racinglines/sources/motogp/fetch.py) into the
database, in the same standard shape every sport uses:

    event    one race weekend        source "motogp_api", source_key "<year>-<short_name>"
    race     event x category RDR    format = {kind: "motogp"}
    round    one, kind "race"        the RAC session's classification
    results  one per rider           position, status, time_ms, bib (rider number), team, extra (constructor,
                                     average_speed, points, gap to leader, laps)

Riders are matched on AthleteIdentifier(scheme="motogp", value=<rider uuid>): the pulselive API's own id, stable
across seasons (a name is never a join key). Only the MotoGP class (sports/motogp.toml's one competition); only
the race session (sprints, listed since 2023, are not ingested yet — a follow-up).

`status`: the source's own `status` field is not yet documented; "INSTND" (every finisher seen in the 2026-09-29
probe) is treated as classified ("OK"). Any other value is recorded as "DNF" and kept verbatim in extra.status_raw
so a DNS/DSQ/retired code found in a later season doesn't get silently mis-mapped - review this against a fuller
sample before trusting DNF counts for a model.

Idempotent like the NASCAR ingest: an event is rebuilt only when its classification file changes (sha256).
"""

import hashlib
import re
from datetime import date

from sqlalchemy import delete, insert, select

from racinglines import paths
from racinglines.db import models as m
from racinglines.db.ingest import _upsert, ensure_competition, resolve_venue
from racinglines.sources.motogp import fetch as F

SPORT = "motogp"
SOURCE = "motogp_api"
SCHEME = "motogp"
CAT_CODE = "RDR"
PARSER = "motogp_api"


def _clean(d):
    return {k: v for k, v in d.items() if v is not None}


def _time_ms(text):
    """'39:36.270' or '1:39:36.270' -> ms; None when it is not a clock (blank, DNF rows without a time)."""
    if not text:
        return None
    parts = text.split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return None
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, mnt, s = parts[-3:]
    return int(round(((h * 60 + mnt) * 60 + s) * 1000))


def status_of(row):
    """OK for a classified finish (every status seen in the 2026-09-29 probe was "INSTND"); DNF otherwise. See
    the module docstring: unseen codes (DNS, DSQ, retired) are not yet distinguished."""
    return "OK" if (row.get("status") or "").upper() == "INSTND" else "DNF"


def _read_json(path):
    import json
    return json.loads(path.read_text()) if path.exists() else None


def parse_event(year, ev, classification):
    """Everything to write for one event, as plain dicts (no database). None when there is no classified result."""
    rows = (classification or {}).get("classification") or []
    if not rows:
        return None
    circuit = ev.get("circuit") or {}
    race_rows = []
    for r in rows:
        rider = r.get("rider") or {}
        team = r.get("team") or {}
        constructor = r.get("constructor") or {}
        race_rows.append(dict(
            rider_id=rider.get("id"), name=rider.get("full_name"), nation=(rider.get("country") or {}).get("iso"),
            position=r.get("position"), status=status_of(r), time_ms=_time_ms(r.get("time")),
            bib=str(rider["number"]) if rider.get("number") is not None else None, team=team.get("name"),
            extra=_clean(dict(
                constructor=constructor.get("name"), average_speed=r.get("average_speed"),
                gap_to_leader_s=(r.get("gap") or {}).get("first"), total_laps=r.get("total_laps"),
                points=r.get("points"), status_raw=r.get("status")))))
    return dict(
        key=f"{year}-{ev['short_name']}", name=ev.get("name") or ev.get("sponsored_name"),
        date=date.fromisoformat(ev["date_start"][:10]), venue=circuit.get("name"),
        nation=(ev.get("country") or {}).get("iso"), rows=race_rows)


def write(session, comp, cat, parsed):
    """Rebuild one event's rows from a parse_event() result. Returns the number of results written."""
    year = int(parsed["key"].split("-", 1)[0])
    season = _upsert(session, m.Season, dict(competition_id=comp.id, year=year))
    venue = resolve_venue(session, parsed["venue"], country=parsed.get("nation")) if parsed["venue"] else None
    event = _upsert(session, m.Event, dict(season_id=season.id, source=SOURCE, source_key=parsed["key"]),
                    name=parsed["name"], start_date=parsed["date"], venue_id=venue.id if venue else None,
                    status="completed")
    race = _upsert(session, m.Race, dict(event_id=event.id, category_id=cat.id))
    race.format = dict(kind="motogp")
    session.execute(delete(m.Round).where(m.Round.race_id == race.id))
    session.flush()

    ids = {row["rider_id"]: row["name"] for row in parsed["rows"] if row["rider_id"]}
    found = dict(session.execute(select(m.AthleteIdentifier.value, m.AthleteIdentifier.athlete_id).where(
        m.AthleteIdentifier.scheme == SCHEME, m.AthleteIdentifier.value.in_(list(ids)))).all())
    for rid, name in ids.items():
        if rid not in found:
            a = m.Athlete(display_name=name or f"MotoGP rider {rid}")
            session.add(a)
            session.flush()
            session.add(m.AthleteIdentifier(scheme=SCHEME, value=rid, athlete_id=a.id))
            found[rid] = a.id

    round_ = m.Round(race_id=race.id, kind="race", ordinal=1, name="Race", extra=None)
    session.add(round_)
    session.flush()
    rows = [dict(round_id=round_.id, athlete_id=found[r["rider_id"]], position=r["position"], status=r["status"],
                time_ms=r["time_ms"], bib=r["bib"], team=r["team"], nation=r["nation"], extra=r["extra"])
            for r in parsed["rows"] if r["rider_id"]]
    if rows:
        session.execute(insert(m.Result), rows)
    return len(rows)


def event_names(year):
    """Every event short_name fetched for a season, in the order the events.json listed them."""
    ev_path = F.season_path(year) / "events.json"
    events = _read_json(ev_path) or []
    return [e["short_name"] for e in events if not e.get("test")]


def ingest_event(session, comp, cat, year, short_name, force=False):
    cls_path = F.event_path(year, short_name) / "classification.json"
    ev_path = F.season_path(year) / "events.json"
    if not cls_path.exists():
        return "no classification"
    events = _read_json(ev_path) or []
    ev = next((e for e in events if e["short_name"] == short_name), None)
    if ev is None:
        return "no event record"
    key = f"motogp:{year}-{short_name}"
    h = hashlib.sha256(cls_path.read_bytes()).hexdigest()
    src = session.scalars(select(m.SourceFile).filter_by(path=key)).first()
    if src and src.sha256 == h and not force:
        return "unchanged"
    parsed = parse_event(year, ev, _read_json(cls_path))
    if parsed is None:
        return "no results"
    n = write(session, comp, cat, parsed)
    race = session.scalars(select(m.Race).join(m.Event).where(m.Event.source == SOURCE, m.Event.source_key == parsed["key"])).one()
    _upsert(session, m.SourceFile, dict(path=key), sha256=h, parser=PARSER, race_id=race.id)
    return f"{n} results"


def ingest(session, years, force=False, echo=print):
    comp, cat = ensure_competition(session, SPORT)
    report = {}
    for year in years:
        for short_name in event_names(year):
            outcome = ingest_event(session, comp, cat, year, short_name, force=force)
            report[f"{year}-{short_name}"] = outcome
            echo(f"{year} {short_name}: {outcome}")
            session.commit()
    return report
