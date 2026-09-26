"""
Load parsed result files into the database.

Each downloaded file (data/script-generated/*.md) is one event x category,
which becomes one Race. Ingest is idempotent:

- A file whose content hash hasn't changed since the last ingest is skipped
  (unless force=True).
- Otherwise the race's rounds, results and splits are deleted and re-inserted
  from the file, so re-downloading a file and re-ingesting it just works.

Athletes are matched through AthleteIdentifier(scheme="name", value=<name key>),
where the key is parser.normalize_rider_id without its "name:" prefix. When the
downloader starts writing UCI IDs, add a "uci" identifier here and match on it
first.
"""

import hashlib
import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, insert, select

from . import models as m
from . import registry

SOURCE = "chronorace"
PARSER = "chronorace_md"


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

def _upsert(session, model, lookup, **values):
    obj = session.scalars(select(model).filter_by(**lookup)).first()
    if obj is None:
        obj = model(**lookup, **values)
        session.add(obj)
        session.flush()
    else:
        for k, v in values.items():
            setattr(obj, k, v)
    return obj


def seed(session):
    """Upsert the sports, leagues, competitions, categories and venues from
    registry.py. Safe to run any number of times."""
    sports = {code: _upsert(session, m.Sport, dict(code=code), name=name, result_kind=kind)
              for code, (name, kind) in registry.SPORTS.items()}
    leagues = {code: _upsert(session, m.League, dict(code=code), name=name, organizer=org)
               for code, (name, org) in registry.LEAGUES.items()}
    for code, spec in registry.COMPETITIONS.items():
        comp = _upsert(session, m.Competition, dict(code=code), name=spec["name"],
                       league_id=leagues[spec["league"]].id, sport_id=sports[spec["sport"]].id)
        for cat_code, (name, gender, age) in spec["categories"].items():
            _upsert(session, m.Category, dict(competition_id=comp.id, code=cat_code),
                    name=name, gender=gender, age_group=age)
    venues = {slug: _upsert(session, m.Venue, dict(slug=slug), name=name, country=country)
              for slug, (name, country) in registry.VENUES.items()}
    for alias, slug in registry.VENUE_ALIASES.items():
        _upsert(session, m.VenueAlias, dict(alias=alias), venue_id=venues[slug].id)
    session.flush()


def _slugify(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def resolve_venue(session, raw_slug, country=None):
    slug = _slugify(raw_slug)
    alias = session.get(m.VenueAlias, slug)
    if alias:
        return session.get(m.Venue, alias.venue_id)
    venue = session.scalars(select(m.Venue).filter_by(slug=slug)).first()
    if venue is None:  # unseen venue: create it; add it to registry.VENUES for a proper name
        venue = _upsert(session, m.Venue, dict(slug=slug), name=slug.replace("-", " ").title(), country=country)
    return venue


def resolve_athletes(session, riders):
    """riders: DataFrame with rider_id ("name:<key>"), rider_name, nation.
    Returns {rider_id: athlete_id}, creating athletes that don't exist yet."""
    riders = riders.drop_duplicates("rider_id")
    keys = {rid: rid.split(":", 1)[1] for rid in riders["rider_id"]}
    found = dict(session.execute(
        select(m.AthleteIdentifier.value, m.AthleteIdentifier.athlete_id)
        .where(m.AthleteIdentifier.scheme == "name", m.AthleteIdentifier.value.in_(list(keys.values())))
    ).all())
    out = {rid: found[key] for rid, key in keys.items() if key in found}
    new = riders[~riders["rider_id"].isin(out)]
    if len(new):
        ids = session.scalars(
            insert(m.Athlete).returning(m.Athlete.id, sort_by_parameter_order=True),
            [dict(display_name=r.rider_name, nation=_none(r.nation)) for r in new.itertuples()],
        ).all()
        session.execute(insert(m.AthleteIdentifier), [
            dict(scheme="name", value=keys[rid], athlete_id=aid) for rid, aid in zip(new["rider_id"], ids)])
        out.update(zip(new["rider_id"], ids))
    return out


def _none(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or v == "" else v


def _ms(seconds):
    return None if seconds is None or pd.isna(seconds) else int(round(float(seconds) * 1000))


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def ingest_file(session, path, competition="uci_dhi_wc", force=False):
    """Ingest one downloaded event file. Returns a short status string."""
    from parser import is_markdown_tables_file, parse_markdown_tables_file
    from predictor import event_format

    path = Path(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    key = path.resolve().as_posix()
    src = session.scalars(select(m.SourceFile).filter_by(path=key)).first()
    if src and src.sha256 == sha and not force:
        return "unchanged"
    if not is_markdown_tables_file(path):
        return "skipped (not a results-table file)"

    df = pd.DataFrame(parse_markdown_tables_file(path))
    if df.empty:
        _upsert(session, m.SourceFile, dict(path=key), sha256=sha, parser=PARSER, race_id=None)
        return "no timing data (PDF-only)"

    comp = session.scalars(select(m.Competition).filter_by(code=competition)).one()
    first = df.iloc[0]
    category = session.scalars(select(m.Category).filter_by(competition_id=comp.id, code=first["category"])).first()
    if category is None:
        category = _upsert(session, m.Category, dict(competition_id=comp.id, code=first["category"]),
                           name=first["category"])
    event_date = date.fromisoformat(first["event_date"])
    season = _upsert(session, m.Season, dict(competition_id=comp.id, year=event_date.year))
    title = first.get("event_name") or ""
    country = title.rsplit(",", 1)[-1].strip() if re.search(r",\s*[A-Z]{3}\s*$", title) else None
    venue = resolve_venue(session, first["venue"], country)
    event = _upsert(session, m.Event, dict(season_id=season.id, source=SOURCE, source_key=first["source_key"]),
                    name=title, start_date=event_date, venue_id=venue.id,
                    series_round=None if pd.isna(first["series_round"]) else int(first["series_round"]),
                    status="completed")
    race = _upsert(session, m.Race, dict(event_id=event.id, category_id=category.id))
    race.format = event_format(df, df["event_id"].iloc[0])

    # replace this race's rounds (results and splits cascade)
    session.execute(delete(m.Round).where(m.Round.race_id == race.id))
    round_ids = {}
    for kind in df["round"].unique():
        rnd = m.Round(race_id=race.id, kind=kind, ordinal=registry.ROUND_ORDER.get(kind, 9), name=kind)
        session.add(rnd)
        session.flush()
        round_ids[kind] = rnd.id

    athletes = resolve_athletes(session, df[["rider_id", "rider_name", "nation"]])

    fin = df[df["sector_id"] == "FINISH"].drop_duplicates(["round", "rider_id"])
    result_rows = [dict(
        round_id=round_ids[r.round], athlete_id=athletes[r.rider_id],
        position=None if pd.isna(r.rank_at_split) else int(r.rank_at_split),
        status=r.status, time_ms=_ms(r.cum_time_s),
        bib=_none(str(r.bib)) if _none(r.bib) is not None else None,
        team=_none(r.team), nation=_none(r.nation),
    ) for r in fin.itertuples()]
    result_ids = session.scalars(
        insert(m.Result).returning(m.Result.id, sort_by_parameter_order=True), result_rows).all()
    rid_by_key = dict(zip(zip(fin["round"], fin["rider_id"]), result_ids))

    sp = df[(df["sector_id"] != "FINISH") & df["cum_time_s"].notna()]
    split_rows = [dict(
        result_id=rid_by_key[(r.round, r.rider_id)], idx=int(r.sector_id[1:]), cum_time_ms=_ms(r.cum_time_s),
        rank=None if pd.isna(r.rank_at_split) else int(r.rank_at_split),
    ) for r in sp.itertuples() if (r.round, r.rider_id) in rid_by_key]
    if split_rows:
        session.execute(insert(m.Split), split_rows)

    _upsert(session, m.SourceFile, dict(path=key), sha256=sha, parser=PARSER, race_id=race.id)
    return f"{len(result_rows)} results, {len(split_rows)} splits"


def ingest_paths(session, paths, competition="uci_dhi_wc", force=False, echo=print):
    """Ingest files and/or directories (non-recursive, *.md). Commits per file."""
    seed(session)
    session.commit()
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.md")) if p.is_dir() else [p]
    counts = {}
    for f in files:
        try:
            status = ingest_file(session, f, competition=competition, force=force)
            session.commit()
        except Exception as e:  # keep going; report at the end
            session.rollback()
            status = f"ERROR: {e}"
        kind = "ingested" if status[0].isdigit() else status.split(" ")[0].rstrip(":")
        counts[kind] = counts.get(kind, 0) + 1
        echo(f"  {f.name}: {status}")
    return counts
