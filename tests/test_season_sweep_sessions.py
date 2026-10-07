"""Session-aware repricing for NASCAR and MotoGP (pipelines/season_sweep.py, "sessions" stage mode; C12a).

A synthetic season per sport on the test database: four completed events with race results, session rounds that
carry their start time where the ingest stores one (NASCAR: rounds.extra.run_date_utc on practice and qualifying;
MotoGP: rounds.extra.session_date on every session), and Kalshi race-winner links with an hourly tape on the last
two events. The third event stores no session time, so its stages fall back to the fixed [replay] stages.

The "weekend" mode is pinned to the base commit's output on the same data (a digest of every table and the params,
the database-id-dependent data_key left out): the session schedule added to the schemas changes nothing there.
"""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete, select, text

from racinglines.pipelines import position_replay as P
from racinglines.pipelines import season_sweep as SW

YEAR = 2031
TAG = "c12a"
N = 8                                   # entrants per race
PRICES = [0.05, 0.40, 0.25, 0.30]       # a coherent race-winner group (sums to 1), before the last qualifying ...
LATE = [0.10, 0.30, 0.35, 0.25]         # ... and after it: the market moves on the session, the model doesn't

# per sport: the event dates (start_date: NASCAR race day; MotoGP the Friday), the stored session rounds as
# (kind, hours from 00:00 UTC of the event's first day), the time key the ingest writes, and its format
WORLD = {
    "nascar": dict(days=["2031-03-02", "2031-03-09", "2031-03-16", "2031-03-23"],
                   sessions=[("fp1", -9.0), ("qual", -5.0)], key="run_date_utc", fmt="%Y-%m-%dT%H:%M:%S",
                   race=None),
    "motogp": dict(days=["2031-03-07", "2031-03-14", "2031-03-21", "2031-03-28"],
                   sessions=[("fp1", 9.75), ("practice", 14.0), ("qual1", 33.83), ("qual2", 34.25), ("sprint", 38.0)],
                   key="session_date", fmt="%Y-%m-%dT%H:%M:%S+00:00", race=61.0),
}
NO_TIMES = 2                             # the event (0-based) whose rounds store no session time
TRADED = (2, 3)                          # the events with links and tape


def _iso(day, hours, fmt):
    return (pd.Timestamp(day) + pd.Timedelta(hours=hours)).strftime(fmt)


def _clean(s, sport):
    from racinglines.db import models as m
    sp = P.spec(sport)
    s.execute(text("DELETE FROM market_price_history WHERE token_id LIKE :p"), dict(p=f"KX{TAG.upper()}-%"))
    s.execute(text("DELETE FROM market_trades WHERE token_id LIKE :p"), dict(p=f"KX{TAG.upper()}-%"))
    s.execute(delete(m.MarketLink).where(m.MarketLink.token_id.like(f"KX{TAG.upper()}-%")))
    s.execute(delete(m.Event).where(m.Event.source == sp["source"], m.Event.source_key.like(f"{YEAR}-{TAG}-%")))
    ids = s.scalars(select(m.Athlete.id).where(m.Athlete.display_name.like(f"{TAG} {sport} %"))).all()
    if ids:
        s.execute(delete(m.Athlete).where(m.Athlete.id.in_(ids)))
    s.commit()


def build(s, sport, dns=False):
    """The synthetic season; returns its athlete ids (best first in the last event). dns: one more entrant on the
    traded events' entry lists who did not start (status DNS, no position), as the NASCAR feed files a car that
    missed the field."""
    from racinglines.db import models as m
    from racinglines.db.ingest import ensure_competition
    w, sp = WORLD[sport], P.spec(sport)
    comp, cat = ensure_competition(s, sport)
    others = s.execute(text("SELECT count(*) FROM events WHERE source = :s"), dict(s=sp["source"])).scalar()
    assert others == 0, f"the test database already holds {others} {sp['source']} events"
    season = s.scalars(select(m.Season).filter_by(competition_id=comp.id, year=YEAR)).one_or_none()
    if season is None:
        season = m.Season(competition_id=comp.id, year=YEAR)
        s.add(season)
        s.flush()
    ath = [m.Athlete(display_name=f"{TAG} {sport} {i}") for i in range(N + 1)]
    s.add_all(ath)
    s.flush()
    ids = [a.id for a in ath]
    for e, day in enumerate(w["days"]):
        ev = m.Event(season_id=season.id, source=sp["source"], source_key=f"{YEAR}-{TAG}-{e}", name=f"{TAG} race {e}",
                     start_date=pd.Timestamp(day).date(), status="completed")
        s.add(ev)
        s.flush()
        race = m.Race(event_id=ev.id, category_id=cat.id)
        s.add(race)
        s.flush()
        order = ids[:N][e % 3:] + ids[:N][:e % 3]               # the finishing order rotates from event to event
        timed = e != NO_TIMES
        for o, (kind, h) in enumerate(w["sessions"], 1):
            rd = m.Round(race_id=race.id, kind=kind, ordinal=o, name=kind,
                         extra={w["key"]: _iso(day, h, w["fmt"])} if timed else {})
            s.add(rd)
            s.flush()
            for p, a in enumerate(order, 1):
                s.add(m.Result(round_id=rd.id, athlete_id=a, position=p, status="OK"))
        rd = m.Round(race_id=race.id, kind="race", ordinal=len(w["sessions"]) + 1, name="race",
                     extra={w["key"]: _iso(day, w["race"], w["fmt"])} if timed and w["race"] is not None else {})
        s.add(rd)
        s.flush()
        for p, a in enumerate(order, 1):
            s.add(m.Result(round_id=rd.id, athlete_id=a, position=p, status="OK"))
        if dns and e in TRADED:
            s.add(m.Result(round_id=rd.id, athlete_id=ids[N], position=None, status="DNS"))
        if e in TRADED:
            _links(s, comp, cat, race, f"{sport.upper()}{e}", day, sport, [(ids.index(a), a) for a in order])
    s.commit()
    return ids


def _links(s, comp, cat, race, ev, day, sport, order):
    """Kalshi race-winner links (stored identified) on the race's top three and last, and an hourly tape from four
    days before the event to two days after it: PRICES until the last stored qualifying, then LATE."""
    from racinglines.db import models as m
    w = WORLD[sport]
    day = pd.Timestamp(day)
    switch = day + pd.Timedelta(hours=max(h for k, h in w["sessions"] if k.startswith("qual")) + 1)
    for n, (i, a) in enumerate([order[0], order[1], order[2], order[-1]]):
        tok = f"KX{TAG.upper()}-{ev}-{i}"              # no database id: the output is the same in any database
        s.add(m.MarketLink(competition_id=comp.id, category_id=cat.id, exchange="kalshi", token_id=tok, market_slug=tok,
                           question=f"Will {i} win?", condition_id=f"KX{TAG.upper()}-{ev}", outcome=str(i),
                           group_title=str(i), event_slug=f"KX{TAG.upper()}-{ev}", event_title="winner",
                           prediction="unmodeled", athlete_id=a, race_id=race.id,
                           params=dict(kind="race_win", season=YEAR),
                           end_date=(day + pd.Timedelta(days=3)).tz_localize("UTC").to_pydatetime()))
        for h in range(-96, 49):
            t = day + pd.Timedelta(hours=h)
            p = (PRICES if t < switch else LATE)[n]
            ts = t.tz_localize("UTC").to_pydatetime()
            s.execute(text("INSERT INTO market_price_history (token_id, ts, price) VALUES (:t, :ts, :p)"),
                      dict(t=tok, ts=ts, p=p))
            s.execute(text("""INSERT INTO market_trades (token_id, condition_id, outcome_index, ts, side, price, size,
                                                         tx_hash, wallet)
                              VALUES (:t, :c, 0, :ts, 'BUY', :p, :z, :h, '')"""),
                      dict(t=tok, c=f"KX{TAG.upper()}-{ev}", ts=ts, p=p, z=80 / p, h=f"{TAG}{ev}-{i}-{h}"))


@pytest.fixture
def world(test_engine):
    from sqlalchemy.orm import sessionmaker
    S = sessionmaker(test_engine)
    made = []

    def make(sport, dns=False):
        with S() as s:
            _clean(s, sport)
            ids = build(s, sport, dns)
        made.append(sport)
        return ids
    yield make
    with S() as s:
        for sport in made:
            _clean(s, sport)


def _settings(sport, **kw):
    return SW.settings_class(sport).from_dict(dict({"venue": "kalshi", "sims": 400, "market_kinds": "race_win"}, **kw))


def canon(out):
    """Every table of a sweep's output and its params as one JSON text (data_key left out: it sums the model's
    frame, whose event ids are this throwaway database's)."""
    def frame(df):
        if not isinstance(df, pd.DataFrame) or not len(df):
            return None
        return json.loads(df.to_json(orient="split", date_format="iso", double_precision=12, default_handler=str))
    body = {k: frame(out[k]) for k in ("weekends", "by_stage", "by_kind", "trades", "scores", "calibration", "reliability")}
    body["totals"] = out["totals"]
    body["params"] = {k: v for k, v in out["params"].items() if k != "data_key"}
    blob = json.dumps(body, sort_keys=True, default=str)
    return blob, hashlib.sha256(blob.encode()).hexdigest()


def run(test_engine, sport, **kw):
    from conftest import TEST_DB
    return SW.run(test_engine, TEST_DB, sport, YEAR, settings=_settings(sport, **kw), echo=lambda *a: None)


# --- "weekend": the base commit's output, unchanged ---------------------------------------------------------

# canon(run(sport, stages unset)) on this world, computed on the base commit (origin/claude/project-thread-hm4wyb,
# 11a6805) before the session schedule existed
BASE = {"nascar": "5203bf105533aaccbe22f0bd04cde03f5e59d1e34f5dd5e06a8ea323939df1e5",
        "motogp": "a7ad8eeaa0ec0cefe9e53ec734888c4c734f08e6b35380f2d8bf63dfdaa195f1"}


@pytest.mark.parametrize("sport", ["nascar", "motogp"])
def test_the_weekend_mode_reproduces_the_base_commit(world, test_engine, sport):
    world(sport)
    blob, digest = canon(run(test_engine, sport))
    assert digest == BASE[sport], blob[:2000]
    assert canon(run(test_engine, sport, stages="weekend"))[1] == BASE[sport]        # named or unset: the same
