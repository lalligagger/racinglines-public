"""
Shared database helpers for ingesters: idempotent upserts, seeding the sports /
leagues / competitions registry, and resolving venues and athletes.
"""

import re
import unicodedata

import pandas as pd
from sqlalchemy import insert, select

from racinglines.db import models as m
from racinglines.db import registry



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


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

