"""
Load ProCyclingStats results (the CSVs racinglines/sources/pcs.py writes on the owner's Mac, columns pcs.COLUMNS) and
upcoming races with their start lists into the database, in the standard shape every sport uses, so the one engine
(models/model_global.py, its results core) prices road cycling from the schema like any other sport:

    event    one race (a one-day race, or a stage race's final GC)   source "pcs_<kind>", source_key the PCS race
                                                                     label ("tre-valli-varesine-2026")
    race     event x category RDR                                    format = {kind: "pcs", page: oneday | gc, class,
                                                                     distance_km, vert_m, profile ...}
    rounds   "race": the classification                              results: position, status, time_ms, extra.gap_s
             "startlist": the entry list of a scheduled race         results: status ENTRY, team (no position)
    results  one per rider

The kind is the results file's ([results] files in sports/road_cycling.toml): "road" (one-day races and stage-race
GCs: events.source "pcs_road", the history [model] source names) or "itt" (time trials: "pcs_itt", stored but not
in the road history). Riders are matched on AthleteIdentifier(scheme="pcs", value=<rider_url>, e.g.
"rider/tadej-pogacar"): PCS's own stable rider slug, exact keys only (a name is never a join key); a rider seen for
the first time is created.

Idempotent: each race is rebuilt only when its rows change (sha256 of its rows, kept in source_files under
"pcs:<kind>:<race>"); its "race" round is replaced, a "startlist" round loaded earlier is kept. A scheduled race
(`schedule`) is the same event as the results that arrive for it later (same source and key), so ingesting them
completes it.

Nothing here fetches (pcs.py does, on the Mac); nothing runs by default.
"""

import hashlib
import re
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, insert, select

from racinglines import progress
from racinglines.db import models as m
from racinglines.db.ingest import _upsert, ensure_competition

SPORT = "road_cycling"
SCHEME = "pcs"
PARSER = "pcs_csv"
KINDS = ("road", "itt")
ENTRY = "ENTRY"                       # results.status of a start-list row (not a result: no position)
SMALL = {"de", "d", "di", "del", "della", "dell", "van", "la", "le", "of", "the", "a", "du", "des", "y", "en"}


def source(kind):
    """events.source of a results kind: "pcs_road" or "pcs_itt"."""
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r}: one of {KINDS}")
    return f"pcs_{kind}"


def _none(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip()) \
        else v


def _num(v):
    v = _none(v)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def title(label, page="oneday"):
    """'tre-valli-varesine-2026' -> 'Tre Valli Varesine'; a GC page adds ' (GC)'; an ITT stage keeps 'Stage 4'."""
    words = re.sub(r"-(19|20)\d\d(?=-|$)", "", str(label)).split("-")
    out = " ".join(w if i and w in SMALL else w.capitalize() for i, w in enumerate(words) if w)
    return out + (" (GC)" if page == "gc" else "")


def event_key(pcs_race):
    """An event file's [event] pcs path -> the race label the results file uses: 'race/tre-valli-varesine/2026' ->
    'tre-valli-varesine-2026' (pcs._pages: f"{slug}-{year}")."""
    parts = [p for p in str(pcs_race).strip("/").split("/") if p]
    if len(parts) < 3 or parts[0] != "race" or not re.fullmatch(r"\d{4}", parts[2]):
        raise ValueError(f"pcs race {pcs_race!r}: expected race/<slug>/<year>")
    return f"{parts[1]}-{parts[2]}"


def _sha(g):
    return hashlib.sha256(g.to_csv(index=False).encode()).hexdigest()


def parse(df, kind):
    """A results file's rows (pcs.COLUMNS) -> one dict per race, in date order: key, name, date, format, sha, rows
    (rider_url, name, nation, position, status, time_ms, extra). Rows without a rider_url or a date are dropped
    (the count is in `skipped`). Pure: no database."""
    source(kind)
    need = {"race", "date", "rider", "rider_url", "position", "status"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"results file lacks columns {sorted(missing)} (pcs.COLUMNS)")
    d = df.copy()
    d["rider_url"] = d["rider_url"].map(_none)
    d["date"] = d["date"].map(_none)
    ok = d["rider_url"].notna() & d["date"].notna() & d["race"].notna()
    skipped = int((~ok).sum())
    d = d[ok]
    out = []
    for race, g in d.groupby("race", sort=False):
        g = g.drop_duplicates("rider_url", keep="first")
        first = g.iloc[0]
        page = str(_none(first.get("kind")) or "oneday")
        rows = []
        for r in g.itertuples(index=False):
            status = str(_none(getattr(r, "status", None)) or "OK").upper()
            pos = _num(r.position)
            if status == "OK" and pos is None:
                status = "DNF"
            win, gap = _num(getattr(r, "winner_time_s", None)), _num(getattr(r, "gap_s", None))
            rows.append(dict(rider_url=str(r.rider_url), name=_none(r.rider) or str(r.rider_url),
                             nation=(_none(getattr(r, "nationality", None)) or None),
                             position=int(pos) if status == "OK" and pos is not None else None, status=status,
                             time_ms=int(round((win + gap) * 1000)) if status == "OK" and win is not None
                             and gap is not None else None,
                             extra={k: v for k, v in dict(gap_s=gap).items() if v is not None} or None))
        fmt = dict(kind="pcs", page=page, race_class=_none(first.get("race_class")),
                   distance_km=_num(first.get("distance_km")), vert_m=_num(first.get("vert_m")),
                   profile_score=_num(first.get("profile_score")), profile_icon=_none(first.get("profile_icon")),
                   source_url=_none(first.get("source_url")))
        out.append(dict(key=str(race), name=title(race, page), date=date.fromisoformat(str(first["date"])[:10]),
                        format={k: v for k, v in fmt.items() if v is not None}, sha=_sha(g), rows=rows))
    out.sort(key=lambda p: (p["date"], p["key"]))
    return out, skipped


def parse_startlist(df):
    """A start list file (pcs.fetch_startlist: rider, rider_url, nationality, team) -> rows for the "startlist"
    round, one per rider_url. Pure."""
    missing = {"rider", "rider_url"} - set(df.columns)
    if missing:
        raise ValueError(f"start list lacks columns {sorted(missing)} (rider, rider_url, nationality, team)")
    rows, seen = [], set()
    for r in df.to_dict("records"):
        url = _none(r.get("rider_url"))
        if url is None or url in seen:
            continue
        seen.add(url)
        nation = _none(r.get("nationality"))
        rows.append(dict(rider_url=str(url), name=_none(r.get("rider")) or str(url),
                         nation=str(nation)[:3] if nation else None, team=_none(r.get("team"))))
    return rows


# --- the database -------------------------------------------------------------------------------------------------

def athletes(session, rows):
    """{rider_url: athlete_id} for the rows' riders: matched on AthleteIdentifier(pcs, rider_url), created when new."""
    want = {}
    for r in rows:
        want.setdefault(r["rider_url"], r)
    found = {}
    urls = list(want)
    for i in range(0, len(urls), 1000):
        found.update(session.execute(select(m.AthleteIdentifier.value, m.AthleteIdentifier.athlete_id).where(
            m.AthleteIdentifier.scheme == SCHEME, m.AthleteIdentifier.value.in_(urls[i:i + 1000]))).all())
    new = [u for u in urls if u not in found]
    if new:
        ids = session.scalars(insert(m.Athlete).returning(m.Athlete.id, sort_by_parameter_order=True),
                              [dict(display_name=str(want[u]["name"])[:200],
                                    nation=(str(want[u]["nation"])[:3] if want[u].get("nation") else None))
                               for u in new]).all()
        session.execute(insert(m.AthleteIdentifier),
                        [dict(scheme=SCHEME, value=u, athlete_id=a) for u, a in zip(new, ids)])
        found.update(zip(new, ids))
    return found


def _event(session, comp, cat, src, key, day, name=None, status=None):
    """The (event, race) of a source key, created or updated; `name` and `status` only replace when given."""
    season = _upsert(session, m.Season, dict(competition_id=comp.id, year=day.year))
    ev = session.scalars(select(m.Event).filter_by(season_id=season.id, source=src, source_key=key)).first()
    if ev is None:
        ev = m.Event(season_id=season.id, source=src, source_key=key, name=name or title(key), start_date=day,
                     status=status or "scheduled")
        session.add(ev)
        session.flush()
    else:
        ev.start_date = day
        if status:
            ev.status = status
        if name and (status == "scheduled" or not ev.name):
            ev.name = name
    race = _upsert(session, m.Race, dict(event_id=ev.id, category_id=cat.id))
    return ev, race


def _round(session, race, kind, ordinal, name, rows, ids, team=False, extra=None):
    session.execute(delete(m.Round).where(m.Round.race_id == race.id, m.Round.kind == kind))
    session.flush()
    rnd = m.Round(race_id=race.id, kind=kind, ordinal=ordinal, name=name, extra=extra)
    session.add(rnd)
    session.flush()
    out = [dict(round_id=rnd.id, athlete_id=ids[r["rider_url"]], position=r.get("position"),
                status=r.get("status") or ENTRY, time_ms=r.get("time_ms"), team=r.get("team") if team else None,
                nation=r.get("nation"), extra=r.get("extra"))
           for r in rows if r["rider_url"] in ids]
    if out:
        session.execute(insert(m.Result), out)
    return len(out)


def write(session, comp, cat, kind, parsed, ids):
    """Rebuild one race's "race" round from a parse() dict (the event completed). Returns (results written, race)."""
    ev, race = _event(session, comp, cat, source(kind), parsed["key"], parsed["date"], name=parsed["name"],
                      status="completed")
    race.format = {**(race.format or {}), **parsed["format"]}
    name = "General classification" if parsed["format"].get("page") == "gc" else "Result"
    return _round(session, race, "race", 2, name, parsed["rows"], ids), race


def ingest(session, csv, kind="road", force=False, echo=print):
    """Load a results file into the database. Returns {race label: outcome}; the caller commits."""
    df = pd.read_csv(csv)
    races, skipped = parse(df, kind)
    if skipped:
        echo(f"{skipped} rows without a rider, race or date skipped")
    comp, cat = ensure_competition(session, SPORT)
    prefix = f"pcs:{kind}:"
    seen = dict(session.execute(select(m.SourceFile.path, m.SourceFile.sha256)
                                .where(m.SourceFile.path.like(prefix + "%"))).all())
    todo = [p for p in races if force or seen.get(prefix + p["key"]) != p["sha"]]
    ids = athletes(session, [r for p in todo for r in p["rows"]]) if todo else {}
    report = {p["key"]: "unchanged" for p in races}
    for i, p in enumerate(todo, 1):
        progress.update(i, len(todo), p["key"])
        n, race = write(session, comp, cat, kind, p, ids)
        _upsert(session, m.SourceFile, dict(path=prefix + p["key"]), sha256=p["sha"], parser=PARSER, race_id=race.id)
        report[p["key"]] = f"{n} results"
        if i % 100 == 0:
            session.flush()
            echo(f"{i} of {len(todo)} races written ({p['key']})")
    return report


def schedule(session, key, day, name, kind="road", startlist=None, pcs_race=None):
    """A scheduled race (event status "scheduled", or the existing one kept as it is when already completed) and,
    with `startlist` (a start list frame), its "startlist" round: the field `model forecast road_cycling` prices.
    Returns (event, race, riders loaded)."""
    comp, cat = ensure_competition(session, SPORT)
    src = source(kind)
    season = session.scalars(select(m.Season).filter_by(competition_id=comp.id, year=day.year)).first()
    old = season and session.scalars(select(m.Event).filter_by(season_id=season.id, source=src, source_key=key)).first()
    status = None if old is not None and old.status == "completed" else "scheduled"
    ev, race = _event(session, comp, cat, src, key, day, name=name, status=status)
    if race.format is None:
        race.format = {k: v for k, v in dict(kind="pcs", page="oneday", pcs=pcs_race).items() if v}
    n = 0
    if startlist is not None:
        rows = parse_startlist(startlist)
        n = _round(session, race, "startlist", 1, "Start list", rows, athletes(session, rows), team=True)
    return ev, race, n


def schedule_event(session, event, startlist_csv=None, data_dir=None):
    """`schedule` from an event file (sports/road_cycling/events/<id>.toml, models/cycling.py load_event): its [event]
    name, date, kind and pcs race, and its start list file (or `startlist_csv`; none on disk: the race is scheduled
    without a field). Returns dict(event, race, riders, startlist: the file read or None)."""
    from racinglines.models import cycling as C
    ev = C.load_event(event)
    e = ev["event"]
    path = Path(startlist_csv) if startlist_csv else C.startlist_file(ev, data_dir)
    start = pd.read_csv(path) if path.exists() else None
    if start is None and startlist_csv:
        raise FileNotFoundError(path)
    kind = "itt" if e.get("kind") == "itt" else "road"
    got, race, n = schedule(session, event_key(e["pcs"]), date.fromisoformat(str(e["date"])), e.get("name"),
                            kind=kind, startlist=start, pcs_race=e["pcs"])
    return dict(event=got, race=race, riders=n, startlist=path if start is not None else None)
