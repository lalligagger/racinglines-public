"""
Load data/raw/motogp/pulselive/<year>/<event_short_name>/ (from racinglines/sources/motogp/fetch.py) into the
database, in the same standard shape every sport uses:

    event    one race weekend        source "motogp_api", source_key "<year>-<short_name>"
    race     event x category RDR    format = {kind: "motogp"}
    rounds   one per session run     fp1.. | practice | qual1 | qual2 | qual | sprint | warmup | race: each session's
                                     classification; "qual" is the combined qualifying order (below)
    results  one per rider           position, status, time_ms, bib (rider number), team, extra (constructor,
                                     average_speed, points, gap to leader, laps)

Riders are matched on AthleteIdentifier(scheme="motogp", value=<rider uuid>): the pulselive API's own id, stable
across seasons (a name is never a join key). Only the MotoGP class (sports/motogp.toml's one competition).

Qualifying: the API lists Q1 and Q2 as type "Q" with number 1 / 2 (tests/fixtures/market/motogp_sessions_2026_tha_
motogp.json), stored as rounds qual1 / qual2. The weekend's qualifying order, the round the pole and grid markets read
(kind "qual", as F1 and NASCAR store it), is derived from them: Q2's classification first (the pole and the front
rows), then the Q1 riders who did not reach Q2 in their Q1 order. It is the qualifying result, not the starting grid
(grid penalties are not in this API). A rider with no position in a session (no timed lap) follows the classified
ones in it. Sprints (type "SPR", since 2023) are stored as round "sprint" wherever their classification was fetched.

Events fetched before the per-session files existed have only <event>/classification.json (the race): it stands in
for the RAC session's classification when that session has no file of its own, so re-ingesting such an event keeps
its race.

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
ROUND_ORDINAL = {"fp1": 1, "fp2": 2, "fp3": 3, "practice": 4, "qual1": 5, "qual2": 6, "qual": 6, "warmup": 7,
                 "sprint": 8, "race": 9}
LEGACY = "legacy"                 # classification_by_id key of <event>/classification.json (the race only)


def _clean(d):
    return {k: v for k, v in d.items() if v is not None}


def session_round_kind(session):
    """Map MotoGP session metadata onto the shared round names used by the F1-style engine."""
    if not session:
        return None
    kind = str(session.get("type") or "").upper()
    num = session.get("number")
    if kind.startswith("FP"):
        n = int(num) if num is not None else 1
        return f"fp{n}"
    if kind == "PR":
        return "practice"
    if kind in {"Q1", "Q2"}:
        return f"qual{int(kind[1])}"
    if kind == "Q":                     # the API's Q1 / Q2: type "Q", number 1 / 2; a single session: no number
        return f"qual{int(num)}" if num is not None else "qual"
    if kind == "SPR":
        return "sprint"
    if kind == "WUP":
        return "warmup"
    if kind == "RAC":
        return "race"
    return None


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


def _rows_from_classification(classification):
    rows = (classification or {}).get("classification") or []
    if not rows:
        return None
    out = []
    for r in rows:
        rider = r.get("rider") or {}
        team = r.get("team") or {}
        constructor = r.get("constructor") or {}
        out.append(dict(
            rider_id=rider.get("id"), name=rider.get("full_name"), nation=(rider.get("country") or {}).get("iso"),
            position=r.get("position"), status=status_of(r), time_ms=_time_ms(r.get("time")),
            bib=str(rider["number"]) if rider.get("number") is not None else None, team=team.get("name"),
            extra=_clean(dict(
                constructor=constructor.get("name"), average_speed=r.get("average_speed"),
                gap_to_leader_s=(r.get("gap") or {}).get("first"), total_laps=r.get("total_laps"),
                points=r.get("points"), status_raw=r.get("status")))))
    return out


def combined_qualifying(q1, q2):
    """The weekend's qualifying order from the Q1 and Q2 rows (each _rows_from_classification's shape): Q2's riders in
    their Q2 order, then the Q1 riders not in Q2 in their Q1 order; within each, riders with no position follow the
    placed ones. Positions are renumbered 1..n, placed riders first; status OK for a rider placed in their session,
    DNS for one without a position there. Rows copy the session row (time, bib, team, extra) and add extra.session
    (q1 / q2) and extra.session_position."""
    def ordered(rows):
        return sorted(rows, key=lambda r: (r.get("position") is None, r.get("position") or 0))
    in_q2 = {r["rider_id"] for r in q2 if r.get("rider_id")}
    picked = [(r, "q2") for r in ordered(q2)] + [(r, "q1") for r in ordered(q1) if r.get("rider_id") not in in_q2]
    out = [dict(r, status="OK" if r.get("position") is not None else "DNS",
                extra=_clean({**(r.get("extra") or {}), "session": sess, "session_position": r.get("position")}))
           for r, sess in picked]
    placed = [r for r in out if r["status"] == "OK"] + [r for r in out if r["status"] != "OK"]
    for i, r in enumerate(placed, 1):
        r["position"] = i
    return placed


def parse_event(year, ev, classification, sessions=None):
    """Everything to write for one event, as plain dicts (no database). None when there is no classified result.

    Legacy API: one classification payload for the one race session. New API: a list of session metadata plus a
    mapping of session-id to classification payloads, which are emitted as multiple rounds. The old contract remains
    supported for the existing fixtures and unit tests.
    """
    if sessions:
        rounds = []
        by_id = classification or {}
        for session in sessions or []:
            sid = session.get("id")
            kind = session_round_kind(session)
            if sid is None or kind is None:
                continue
            cls = by_id.get(sid)
            if cls is None and kind == "race":
                cls = by_id.get(LEGACY)         # fetched before per-session files: the race's own file
            rows = _rows_from_classification(cls)
            if not rows:
                continue
            rounds.append(dict(
                kind=kind,
                name=(session.get("type") or kind).upper(),
                ordinal=ROUND_ORDINAL.get(kind, 0),
                extra=_clean({"session_date": session.get("date"), "status": session.get("status"),
                              "number": session.get("number"),
                              "condition": session.get("condition")}),
                rows=rows,
            ))
        if not rounds:
            return None
        got = {r["kind"]: r for r in rounds}
        if "qual" not in got and ("qual1" in got or "qual2" in got):
            q1, q2 = got.get("qual1", {}).get("rows", []), got.get("qual2", {}).get("rows", [])
            last = got.get("qual2") or got["qual1"]
            rounds.append(dict(kind="qual", name="QUALIFYING", ordinal=ROUND_ORDINAL["qual"],
                               extra=_clean({"derived_from": [k for k in ("qual1", "qual2") if k in got],
                                             "session_date": (last.get("extra") or {}).get("session_date")}),
                               rows=combined_qualifying(q1, q2)))
        circuit = ev.get("circuit") or {}
        return dict(
            key=f"{year}-{ev['short_name']}", name=ev.get("name") or ev.get("sponsored_name"),
            date=date.fromisoformat(ev["date_start"][:10]), venue=circuit.get("name"),
            nation=(ev.get("country") or {}).get("iso"), rounds=rounds)

    rows = _rows_from_classification(classification)
    if not rows:
        return None
    circuit = ev.get("circuit") or {}
    return dict(
        key=f"{year}-{ev['short_name']}", name=ev.get("name") or ev.get("sponsored_name"),
        date=date.fromisoformat(ev["date_start"][:10]), venue=circuit.get("name"),
        nation=(ev.get("country") or {}).get("iso"), rows=rows)


def write(session, comp, cat, parsed):
    """Rebuild one event's rows from a parse_event() result. Returns the number of results written."""
    year = int(parsed["key"].split("-", 1)[0])
    season = _upsert(session, m.Season, dict(competition_id=comp.id, year=year))
    venue = resolve_venue(session, parsed["venue"], country=parsed.get("nation")) if parsed.get("venue") else None
    event = _upsert(session, m.Event, dict(season_id=season.id, source=SOURCE, source_key=parsed["key"]),
                    name=parsed["name"], start_date=parsed["date"], venue_id=venue.id if venue else None,
                    status="completed")
    race = _upsert(session, m.Race, dict(event_id=event.id, category_id=cat.id))
    race.format = dict(kind="motogp")
    session.execute(delete(m.Round).where(m.Round.race_id == race.id))
    session.flush()

    rounds = parsed.get("rounds") or [{"kind": "race", "name": "Race", "ordinal": 1, "extra": None,
                                      "rows": parsed.get("rows", [])}]
    athlete_ids = {}
    for round_ in rounds:
        for row in round_.get("rows", []):
            if row.get("rider_id"):
                athlete_ids[row["rider_id"]] = row["name"]
    found = dict(session.execute(select(m.AthleteIdentifier.value, m.AthleteIdentifier.athlete_id).where(
        m.AthleteIdentifier.scheme == SCHEME, m.AthleteIdentifier.value.in_(list(athlete_ids)))).all())
    for rid, name in athlete_ids.items():
        if rid not in found:
            a = m.Athlete(display_name=name or f"MotoGP rider {rid}")
            session.add(a)
            session.flush()
            session.add(m.AthleteIdentifier(scheme=SCHEME, value=rid, athlete_id=a.id))
            found[rid] = a.id

    count = 0
    for round_ in rounds:
        kind = round_.get("kind") or "race"
        rnd = m.Round(race_id=race.id, kind=kind, ordinal=round_.get("ordinal") or ROUND_ORDINAL.get(kind, 1),
                      name=round_.get("name") or kind, extra=round_.get("extra"))
        session.add(rnd)
        session.flush()
        rows = [dict(round_id=rnd.id, athlete_id=found[r["rider_id"]], position=r["position"], status=r["status"],
                    time_ms=r["time_ms"], bib=r["bib"], team=r["team"], nation=r["nation"], extra=r["extra"])
                for r in round_.get("rows", []) if r.get("rider_id") and r["rider_id"] in found]
        if rows:
            session.execute(insert(m.Result), rows)
        count += len(rows)
    return count


def event_names(year):
    """Every event short_name fetched for a season, in the order the events.json listed them."""
    ev_path = F.season_path(year) / "events.json"
    events = _read_json(ev_path) or []
    return [e["short_name"] for e in events if not e.get("test")]


def ingest_event(session, comp, cat, year, short_name, force=False):
    event_dir = F.event_path(year, short_name)
    cls_path = event_dir / "classification.json"
    sessions_path = F.season_path(year) / "sessions.json"
    ev_path = F.season_path(year) / "events.json"
    events = _read_json(ev_path) or []
    ev = next((e for e in events if e["short_name"] == short_name), None)
    if ev is None:
        return "no event record"
    session_list = _read_json(event_dir / "sessions.json") or []
    classification_by_id = {}
    for s in session_list:
        sid = s.get("id")
        if sid:
            data = _read_json(event_dir / f"{sid}.classification.json")
            if data is not None:
                classification_by_id[sid] = data
    legacy = _read_json(cls_path)
    if legacy is not None:
        classification_by_id[LEGACY] = legacy
    if not classification_by_id:
        return "no classification"
    key = f"motogp:{year}-{short_name}"
    files = [event_dir / "sessions.json"]
    files.extend(event_dir / f"{s['id']}.classification.json" for s in session_list if s.get("id"))
    if cls_path.exists():
        files.append(cls_path)
    h = hashlib.sha256(b"".join(p.read_bytes() for p in files if p.exists())).hexdigest()
    src = session.scalars(select(m.SourceFile).filter_by(path=key)).first()
    if src and src.sha256 == h and not force:
        return "unchanged"
    payload = classification_by_id if session_list else legacy
    parsed = parse_event(year, ev, payload, sessions=session_list or None)
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
