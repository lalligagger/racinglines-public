"""
Load data/raw/nascar/cf/<year>/<series>/<race_id>/ (from racinglines/sources/nascar/fetch.py) into the database.

    event    one race weekend       source "nascar_cf", source_key "<year>-<race_id>", series_round = points-race number
    race     event x category DRV   format = laps, stages, cautions, caution segments, leaders, grid provenance
    rounds   fp1.. | qual1.. | qual | race   only sessions that were actually run
    results  one per driver         position, status (OK/DNF/DNS/DSQ), bib = car number, team,
                                    extra = grid, points, laps led, stage finishes, loop stats, pit stops
    laps     every lap (2020-)      lap time, running position, flag state ("1" green, "2" yellow)

Drivers are matched on AthleteIdentifier(scheme="nascar", value=<driver_id>): NASCAR's own integer, stable across
teams and seasons; names are display only (never a join key) and car numbers belong to teams.

Two source quirks the ingest records rather than hides (found in the 2026-09-29 probe):
  * qualifying rained out: the qualifying run exists with every time 0 and the grid was set by formula. No qual
    round is written and format.qualifying_ran is false.
  * lap-times can have holes and stop short of the race distance (Darlington 2026: laps 330-335 absent and nothing
    after lap 355 of 367). The laps that exist are stored and the race round's extra says laps_complete = false
    with laps_max and laps_missing (laps of the race distance that no car has), so a lap-based feature can drop
    those races.

Races still to run (in the season's race list, dated today or later) are filed as events with status "scheduled" and
no rounds, so a market on an upcoming race has a race to point at; the weekend feed turns the same event into a
completed one when the race has been run.

Idempotent like the F1 ingest: a race is rebuilt only when its files change (sha256 of all of them).
Only Cup (series 1) is wired to a competition; Xfinity and Trucks need their own competition rows first.
"""

import hashlib
from datetime import date

from sqlalchemy import delete, insert, select

from racinglines.db import models as m
from racinglines.db.ingest import _upsert, ensure_competition, resolve_venue
from racinglines.sources.nascar import fetch as F

SPORT = "nascar"
SOURCE = "nascar_cf"
SCHEME = "nascar"
SERIES_SPORT = {1: SPORT}                  # series id -> sport code (its competition comes from sports/<code>.toml)
PARSER = "nascar_cf"
FLAG = {1: "green", 2: "yellow", 4: "checkered", 8: "pre-race"}


def _clean(d):
    return {k: v for k, v in d.items() if v is not None}


def _ms(seconds):
    return int(round(float(seconds) * 1000)) if seconds not in (None, "", 0, 0.0) else None


def _clock_ms(text):
    """'4:03:05' / '03:00:36' -> ms; None when it is not a clock."""
    try:
        parts = [int(p) for p in str(text).split(":")]
    except ValueError:
        return None
    if len(parts) != 3:
        return None
    return ((parts[0] * 60 + parts[1]) * 60 + parts[2]) * 1000


def status_of(row):
    """OK / DNF / DNS / DSQ from a results row. A car in the feed with finishing_position 0 never took the
    green flag (Daytona 500 entries that missed the field) and is DNS; 'Running' at the end is OK; every other
    finishing_status ('Accident', an engine, ...) is DNF, the text kept in extra.status_text."""
    if row.get("disqualified"):
        return "DSQ"
    if not row.get("finishing_position"):
        return "DNS"
    return "OK" if str(row.get("finishing_status") or "").lower() == "running" else "DNF"


def series_rounds(race_list):
    """{race_id: points-race number} from a season's race list (exhibitions get no number)."""
    pts = sorted((r for r in race_list if r.get("race_type_id") == 1), key=lambda r: (r["race_date"], r["race_id"]))
    return {r["race_id"]: i + 1 for i, r in enumerate(pts)}


def load(year, series, race_id):
    """{feed name: parsed JSON} of the files stored for one race, and the sorted list of those files."""
    feeds, files = {}, []
    for name in F.RACE_FEEDS:
        path = F.feed_path(year, series, name, race_id)
        if path.exists():
            feeds[name] = F.read(path)
            files.append(path)
    return feeds, sorted(files)


def _runs(weekend):
    """(practice runs, qualifying runs), each chronological, only those that were run (some lap time > 0)."""
    def ran(run):
        return any((r.get("best_lap_time") or 0) > 0 for r in run.get("results") or [])
    runs = sorted((r for r in weekend.get("weekend_runs") or [] if ran(r)),
                  key=lambda r: (r.get("run_date_utc") or r.get("run_date") or "", r.get("run_name") or ""))
    return [r for r in runs if r.get("run_type") == 1], [r for r in runs if r.get("run_type") == 2]


def _session_rows(run):
    rows = []
    for r in run["results"]:
        if not r.get("driver_id"):
            continue
        timed = (r.get("best_lap_time") or 0) > 0
        rows.append(dict(
            driver_id=r["driver_id"], name=r.get("driver_name"), position=r.get("finishing_position") or None,
            status="OK" if timed else "DNS", time_ms=_ms(r.get("best_lap_time")), bib=str(r["car_number"]) if r.get("car_number") is not None else None,
            team=None, extra=_clean(dict(
                best_lap_speed_mph=r.get("best_lap_speed") or None, best_lap_number=r.get("best_lap_number") or None,
                laps=r.get("laps_completed"), manufacturer=r.get("manufacturer"), run_name=run.get("run_name"),
                delta_leader=r.get("delta_leader"), disqualified=r.get("disqualified") or None))))
    return rows


def parse_race(year, race_id, feeds, series_round=None, series=1, laps=True):
    """Everything to write for one race, as plain dicts (no database). None when there is no weekend feed or the
    race has no classified result yet."""
    wf = feeds.get("weekend-feed")
    if not wf or not wf.get("weekend_race"):
        return None
    wr = wf["weekend_race"][0]
    results = wr.get("results") or []
    if not results:
        return None
    practice, qualifying = _runs(wf)
    by_car = {}
    for r in results:
        by_car.setdefault(str(r.get("car_number")), []).append(r)
    car_driver = {c: rs[0]["driver_id"] for c, rs in by_car.items() if len(rs) == 1}     # a car number shared by two rows is ambiguous

    qualifying_ran = bool(qualifying) or any((r.get("qualifying_speed") or 0) > 0 for r in results)
    stage_laps = [wr.get(f"stage_{i}_laps") for i in (1, 2, 3)]
    fmt = _clean(dict(
        kind="nascar", series=series, race_id=race_id, track_id=wr.get("track_id"), track_name=wr.get("track_name"),
        race_type="points" if wr.get("race_type_id") == 1 else "exhibition",
        scheduled_laps=wr.get("scheduled_laps"), actual_laps=wr.get("actual_laps"), scheduled_distance=wr.get("scheduled_distance"),
        stage_laps=[n for n in stage_laps if n] or None, cautions=wr.get("number_of_cautions"),
        caution_laps=wr.get("number_of_caution_laps"), lead_changes=wr.get("number_of_lead_changes"),
        leaders=wr.get("number_of_leaders"), cars=wr.get("number_of_cars_in_field"), playoff_round=wr.get("playoff_round"),
        restrictor_plate=wr.get("restrictor_plate"), pole_winner_driver_id=wr.get("pole_winner_driver_id") or None,
        qualifying_ran=qualifying_ran, average_speed_mph=wr.get("average_speed"), total_race_time=wr.get("total_race_time"),
        margin_of_victory=wr.get("margin_of_victory"),
        caution_segments=[_clean(dict(start_lap=c.get("start_lap"), end_lap=c.get("end_lap"), reason=c.get("reason"),
                                      free_pass_car=c.get("beneficiary_car_number"))) for c in wr.get("caution_segments") or []] or None,
        race_leaders=[_clean(dict(start_lap=x.get("start_lap"), end_lap=x.get("end_lap"), car=x.get("car_number"),
                                  driver_id=car_driver.get(str(x.get("car_number"))))) for x in wr.get("race_leaders") or []] or None))

    stages = {}
    for st in wr.get("stage_results") or []:
        for r in st.get("results") or []:
            stages.setdefault(r["driver_id"], []).append(
                dict(stage=st["stage_number"], position=r.get("finishing_position"), points=r.get("stage_points")))
    loop = {d["driver_id"]: {k: v for k, v in d.items() if k != "driver_id"}
            for blk in (feeds.get("loopstats") or []) for d in blk.get("drivers") or []}
    pits = {}
    for p in feeds.get("pit-data") or []:
        if (p.get("lap_count") or 0) > 0 and str(p.get("vehicle_number")) in car_driver:
            pits.setdefault(car_driver[str(p["vehicle_number"])], []).append(_clean(dict(
                lap_count=p["lap_count"], pit_stop_type=p.get("pit_stop_type"), pit_in_flag_status=p.get("pit_in_flag_status"),
                pit_stop_duration=p["pit_stop_duration"] if (p.get("pit_stop_duration") or -1) > 0 else None,
                total_duration=p.get("total_duration"), positions_gained_lost=p.get("positions_gained_lost"),
                tires_changed=sum(bool(p.get(k)) for k in ("left_front_tire_changed", "left_rear_tire_changed",
                                                           "right_front_tire_changed", "right_rear_tire_changed")))))

    winner_ms = _clock_ms(wr.get("total_race_time"))
    race_rows = []
    for r in results:
        if not r.get("driver_id"):
            continue
        pos = r.get("finishing_position") or None
        led = pos == 1
        # diff_time is the gap to the winner in milliseconds (Darlington 2026: P2 1038 = margin_of_victory "1.038")
        time_ms = winner_ms if led else (winner_ms + int(r["diff_time"])
                                         if winner_ms and not r.get("diff_laps") and (r.get("diff_time") or 0) > 0 else None)
        race_rows.append(dict(
            driver_id=r["driver_id"], name=r.get("driver_fullname"), position=pos, status=status_of(r), time_ms=time_ms,
            bib=str(r["car_number"]) if r.get("car_number") is not None else None, team=r.get("team_name"),
            extra=_clean(dict(
                grid=r.get("starting_position") or None, qualifying_position=r.get("qualifying_position") or None,
                qualifying_speed_mph=r.get("qualifying_speed") or None, laps=r.get("laps_completed"),
                laps_led=r.get("laps_led"), times_led=r.get("times_led"), points=r.get("points_earned"),
                playoff_points=r.get("playoff_points_earned", r.get("bonus_points_earned")), points_position=r.get("points_position"),
                status_text=r.get("finishing_status"), car_make=r.get("car_make"), car_model=r.get("car_model"), sponsor=r.get("sponsor"),
                team_id=r.get("team_id"), owner_id=r.get("owner_id"), crew_chief_id=r.get("crew_chief_id"),
                official_car_number=r.get("official_car_number"), diff_laps=r.get("diff_laps"),
                disqualified=r.get("disqualified") or None, stages=stages.get(r["driver_id"]), loop=loop.get(r["driver_id"]),
                pit_stops=pits.get(r["driver_id"])))))

    rounds, ordinal = [], 0

    def add(kind, name, extra, rows):
        nonlocal ordinal
        ordinal += 1
        rounds.append(dict(kind=kind, ordinal=ordinal, name=name, extra=_clean(extra), results=rows))

    for i, run in enumerate(practice, 1):
        add(f"fp{i}", run.get("run_name"), dict(run_date_utc=run.get("run_date_utc"), run_type=1), _session_rows(run))
    for i, run in enumerate(qualifying, 1):
        final = len(qualifying) == 1 or "final" in (run.get("run_name") or "").lower()
        kind = "qual" if final and not any(x["kind"] == "qual" for x in rounds) else f"qual{i}"
        add(kind, run.get("run_name"), dict(run_date_utc=run.get("run_date_utc"), run_type=2), _session_rows(run))

    lap_rows, lap_meta = {}, {}
    lt = feeds.get("lap-times") if laps else None
    if lt:
        flags = {f["LapsCompleted"]: f["FlagState"] for f in lt.get("flags") or []}
        for d in lt.get("laps") or []:
            did = d.get("NASCARDriverID")
            rows = [dict(lap=x["Lap"], lap_time_ms=_ms(x.get("LapTime")), position=x.get("RunningPos"),
                         track_status=str(flags[x["Lap"]]) if x["Lap"] in flags else None)
                    for x in d.get("Laps") or [] if x.get("Lap")]           # lap 0 is the grid, already in extra.grid
            if did and rows:
                lap_rows[did] = rows
        seen = {x["lap"] for rows in lap_rows.values() for x in rows}
        missing = len(set(range(1, (wr.get("actual_laps") or 0) + 1)) - seen)
        lap_meta = dict(laps_max=max(seen, default=0), laps_missing=missing, laps_complete=bool(seen) and missing == 0,
                        lap_drivers=len(lap_rows))
    add("race", wr.get("race_name"), dict(
        total_race_time=wr.get("total_race_time"), race_date_local=wr.get("race_date"), **lap_meta), race_rows)
    return dict(
        key=f"{year}-{race_id}", name=wr.get("race_name"), date=date.fromisoformat(wr["race_date"][:10]),
        track=wr.get("track_name"), series_round=series_round, format=fmt, rounds=rounds, laps=lap_rows)


def write(session, comp, cat, year, parsed):
    """Rebuild one race's rows from a parse_race() result. Returns (results, laps)."""
    season = _upsert(session, m.Season, dict(competition_id=comp.id, year=year))
    venue = resolve_venue(session, parsed["track"]) if parsed["track"] else None
    event = _upsert(session, m.Event, dict(season_id=season.id, source=SOURCE, source_key=parsed["key"]),
                    name=parsed["name"], start_date=parsed["date"], venue_id=venue.id if venue else None,
                    series_round=parsed["series_round"], status="completed")
    race = _upsert(session, m.Race, dict(event_id=event.id, category_id=cat.id))
    race.format = parsed["format"]
    session.execute(delete(m.Round).where(m.Round.race_id == race.id))
    session.flush()

    ids = {row["driver_id"]: row["name"] for rd in parsed["rounds"] for row in rd["results"]}
    found = dict(session.execute(select(m.AthleteIdentifier.value, m.AthleteIdentifier.athlete_id).where(
        m.AthleteIdentifier.scheme == SCHEME, m.AthleteIdentifier.value.in_([str(i) for i in ids]))).all())
    for did, name in ids.items():
        if str(did) not in found:
            a = m.Athlete(display_name=name or f"NASCAR driver {did}")
            session.add(a)
            session.flush()
            session.add(m.AthleteIdentifier(scheme=SCHEME, value=str(did), athlete_id=a.id))
            found[str(did)] = a.id

    n_results = n_laps = 0
    for rd in parsed["rounds"]:
        row = m.Round(race_id=race.id, kind=rd["kind"], ordinal=rd["ordinal"], name=rd["name"], extra=rd["extra"])
        session.add(row)
        session.flush()
        rows = {r["driver_id"]: dict(round_id=row.id, athlete_id=found[str(r["driver_id"])], position=r["position"], status=r["status"],
                                     time_ms=r["time_ms"], bib=r["bib"], team=r["team"], extra=r["extra"]) for r in rd["results"]}
        drivers = list(rows)
        result_ids = session.scalars(insert(m.Result).returning(m.Result.id, sort_by_parameter_order=True),
                                     [rows[d] for d in drivers]).all()
        n_results += len(drivers)
        if rd["kind"] == "race":
            lap_rows = {(rid, x["lap"]): dict(result_id=rid, **x)
                        for d, rid in zip(drivers, result_ids) for x in parsed["laps"].get(d, [])}
            lap_rows = list(lap_rows.values())
            if lap_rows:
                session.execute(insert(m.Lap), lap_rows)
            n_laps += len(lap_rows)
    return n_results, n_laps


def ingest_schedule(session, comp, cat, year, series, today=None, force=False):
    """File the season's races that have not been run yet as scheduled events (no rounds, no results). A race
    dated before `today` gets its event from the weekend feed instead; a completed event is never touched.
    Returns the number written; 0 when the race list has not changed."""
    path = F.feed_path(year, series, "race_list_basic")
    if not path.exists():
        return 0
    today = today or date.today()
    key = f"nascar:{year}-{series}-schedule"
    h = hashlib.sha256(path.read_bytes() + today.isoformat().encode()).hexdigest()
    src = session.scalars(select(m.SourceFile).filter_by(path=key)).first()
    if src and src.sha256 == h and not force:
        return 0
    rows = F.read(path) or []
    rounds = series_rounds(rows)
    season = _upsert(session, m.Season, dict(competition_id=comp.id, year=year))
    n = 0
    for r in rows:
        day = date.fromisoformat(r["race_date"][:10])
        if day < today:
            continue
        skey = f"{year}-{r['race_id']}"
        old = session.scalars(select(m.Event).filter_by(season_id=season.id, source=SOURCE, source_key=skey)).first()
        if old is not None and old.status == "completed":
            continue
        venue = resolve_venue(session, r["track_name"]) if r.get("track_name") else None
        event = _upsert(session, m.Event, dict(season_id=season.id, source=SOURCE, source_key=skey), name=r["race_name"].strip(),
                        start_date=day, venue_id=venue.id if venue else None, series_round=rounds.get(r["race_id"]), status="scheduled")
        race = _upsert(session, m.Race, dict(event_id=event.id, category_id=cat.id))
        race.format = _clean(dict(
            kind="nascar", series=series, race_id=r["race_id"], track_id=r.get("track_id"), track_name=r.get("track_name"),
            race_type="points" if r.get("race_type_id") == 1 else "exhibition", scheduled_laps=r.get("scheduled_laps"),
            scheduled_distance=r.get("scheduled_distance"), stage_laps=[r[k] for k in ("stage_1_laps", "stage_2_laps", "stage_3_laps") if r.get(k)] or None,
            playoff_round=r.get("playoff_round"), restrictor_plate=r.get("restrictor_plate")))
        n += 1
    _upsert(session, m.SourceFile, dict(path=key), sha256=h, parser=PARSER)
    return n


def race_ids(year, series=1):
    """Race ids with a stored weekend feed, in date order."""
    base = F.season_dir(year, series)
    have = {int(p.parent.name) for p in base.glob("*/weekend-feed.json")} if base.exists() else set()
    listed = [r["race_id"] for r in F.race_rows(year, series) if r["race_id"] in have]
    return listed + sorted(have - set(listed))


def ingest_race(session, comp, cat, year, series, race_id, rounds, force=False, laps=True):
    feeds, files = load(year, series, race_id)
    if "weekend-feed" not in feeds:
        return "no weekend feed"
    key = f"nascar:{year}-{series}-{race_id}"
    with_laps = laps and "lap-times" in feeds                     # only a race with a lap file changes with --no-laps
    h = hashlib.sha256(b"".join(p.read_bytes() for p in files) + (b"+laps" if with_laps else b"-laps")).hexdigest()
    src = session.scalars(select(m.SourceFile).filter_by(path=key)).first()
    if src and src.sha256 == h and not force:
        return "unchanged"
    parsed = parse_race(year, race_id, feeds, rounds.get(race_id), series=series, laps=laps)
    if parsed is None:
        return "no results"
    n_results, n_laps = write(session, comp, cat, year, parsed)
    race = session.scalars(select(m.Race).join(m.Event).where(m.Event.source == SOURCE, m.Event.source_key == parsed["key"])).one()
    _upsert(session, m.SourceFile, dict(path=key), sha256=h, parser=PARSER, race_id=race.id)
    return f"{n_results} results, {n_laps} laps"


def ingest(session, years, series=1, force=False, laps=True, today=None, echo=print):
    if series not in SERIES_SPORT:
        raise ValueError(f"series {series} has no competition yet; wired: {sorted(SERIES_SPORT)}")
    comp, cat = ensure_competition(session, SERIES_SPORT[series])
    session.commit()
    counts = {}
    for year in years:
        rounds = series_rounds(F.race_rows(year, series))
        n = ingest_schedule(session, comp, cat, year, series, today=today, force=force)
        session.commit()
        if n:
            counts["scheduled"] = counts.get("scheduled", 0) + n
            echo(f"  {year}: {n} races still to run filed as scheduled")
        for rid in race_ids(year, series):
            try:
                status = ingest_race(session, comp, cat, year, series, rid, rounds, force=force, laps=laps)
                session.commit()
            except Exception as e:
                session.rollback()
                status = f"ERROR {type(e).__name__}: {e}"
            k = "ingested" if status[0].isdigit() else status.split(" ")[0]
            counts[k] = counts.get(k, 0) + 1
            echo(f"  {year} {rid}: {status}")
    return counts
