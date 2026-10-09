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


# --- the schema: a session schedule beside the fixed stages ---------------------------------------------------

@pytest.mark.quick
def test_both_modes_are_in_the_schema_and_weekend_stays_the_default():
    from racinglines.pipelines import sweep_settings as SS
    for sport in ("nascar", "motogp"):
        assert SW.modes(sport)[:2] == ("sessions", "weekend") and SW.engine_of(sport) == "weekend"
        assert SW.time_key(sport) and SW.supports(sport)
        cls = SW.settings_class(sport)
        st = cls.from_dict()
        assert st["taker_stages"] == SW.stage_labels(sport, "weekend") and st["late_stages"] == ("race eve",)
        assert SW.mode_of(sport, cls.from_dict({"stages": "sessions"})) == "sessions"
        assert set(SW.stage_labels(sport, "sessions")) <= set(cls.BY["taker_stages"].choices)
    assert SW.time_key("f1") is None and SW.modes("f1") == ("sessions",)
    assert SW.stage_labels("f1", "sessions") == SS.STAGES                   # the schema's labels are F1's, as before
    assert SW.stage_labels("nascar", "sessions") == ("pre-weekend", "after P1", "after P2", "after P3", "after P4",
                                                     "after P5", "after Q1", "after Q2", "after Q")
    assert SW.stage_labels("motogp", "sessions") == ("pre-weekend", "after FP1", "after FP2", "after FP3", "after FP4",
                                                     "after PR", "after Q1", "after Q2", "after Sprint", "after WUP")
    assert SW.late_labels("nascar", "sessions") == ("after Q", "race eve")
    assert SW.kinds("nascar", "sessions") == SW.kinds("nascar", "weekend")   # no weekend_kinds: the [replay] kinds
    assert SW.modes("nascar") == ("sessions", "weekend", "race_day") and SW.modes("motogp") == ("sessions", "weekend")


@pytest.mark.quick
def test_the_race_day_mode_adds_its_stages_and_keeps_the_weekend_default():
    T = pd.Timestamp
    sp, sw = P.spec("nascar"), SW.spec("nascar")
    assert SW.stage_labels("nascar") == ("T-3d", "T-1d", "race eve")                 # the default: unchanged
    assert SW.stage_labels("nascar", "race_day") == ("T-3d", "T-1d", "race eve", "race morning")
    assert "race morning" in SW.all_labels("nascar") and SW.late_labels("nascar", "race_day") == ("race eve", "race morning")
    race = pd.Series(dict(start=T("2031-03-23")))
    week = SW.race_plan("nascar", "weekend", race, [], sp, sw)
    day = SW.race_plan("nascar", "race_day", race, [], sp, sw)
    assert week["stages"][-1] == ("race eve", T("2031-03-22 18:00")) and week["until"] == T("2031-03-23")
    assert day["stages"][-1] == ("race morning", T("2031-03-23 12:00")) and day["until"] == T("2031-03-23 15:00")
    assert P.stage_list(sp) == sp["stages"]
    with pytest.raises(ValueError):
        P.stage_list(P.spec("motogp"), "race_day")                   # no race_day_stages in its schema


@pytest.mark.quick
def test_session_stages_come_from_stored_times_and_stop_before_the_race():
    T = pd.Timestamp
    sp = P.spec("nascar")
    # practice and qualifying stored, the race not: the stages end at 00:00 UTC on race day
    got = SW.session_stages("nascar", T("2031-03-23"), [("fp1", T("2031-03-22 15:00")), ("qual", T("2031-03-22 19:00"))], sp)
    assert got["stages"] == [("pre-weekend", T("2031-03-22 14:00")), ("after P1", T("2031-03-22 16:20")),
                             ("after Q", T("2031-03-22 20:30"))]
    assert got["until"] == T("2031-03-23") and got["sessions"][0][0] == "fp1"
    # a session whose data would be in after the start is not a stage
    late = SW.session_stages("nascar", T("2031-03-23"), [("fp1", T("2031-03-22 15:00")), ("qual", T("2031-03-22 23:30"))], sp)
    assert [lab for lab, _ in late["stages"]] == ["pre-weekend", "after P1"]
    # nothing stored: no session stages (the event is traded on its [replay] stages)
    assert SW.session_stages("nascar", T("2031-03-23"), [], sp) is None
    # MotoGP: the race's stored start ends the stages (Sunday's warm-up is in, the race is not)
    m = SW.session_stages("motogp", T("2031-03-28"), [("fp1", T("2031-03-28 09:45")), ("sprint", T("2031-03-29 14:00")),
                                                     ("warmup", T("2031-03-30 08:40")), ("race", T("2031-03-30 12:00"))],
                          P.spec("motogp"))
    assert [lab for lab, _ in m["stages"]] == ["pre-weekend", "after FP1", "after Sprint", "after WUP"]
    assert m["until"] == T("2031-03-30 12:00")


@pytest.mark.quick
def test_the_start_list_leaves_out_non_starters():
    res = pd.DataFrame(dict(athlete_id=[3, 1, 2, 4], position=[1, 2, None, None], status=["OK", "ok", "DNS", None]))
    assert SW.start_list(res) == [1, 3, 4]                     # DNS out; a DNF / unknown status started


# --- "sessions": a season on the test database ----------------------------------------------------------------

def _plans(test_engine, sport, mode):
    sp, sw = P.spec(sport), SW.spec(sport)
    with test_engine.connect() as conn:
        rs = P.races(conn, sp, [YEAR])
        times = SW.session_times(conn, sport, rs["race_id"].tolist())
    return rs, {r.event_key: SW.race_plan(sport, mode, r, times.get(int(r.race_id), []), sp, sw) for r in rs.itertuples()}


@pytest.mark.parametrize("sport", ["nascar", "motogp"])
def test_a_sessions_sweep_trades_after_each_stored_session(world, test_engine, sport):
    world(sport)
    rs, plans = _plans(test_engine, sport, "sessions")
    keys = list(rs["event_key"])
    assert [plans[k]["format"] for k in keys] == ["sessions", "sessions", "weekend", "sessions"]   # the third: no times
    want = {"nascar": ["pre-weekend", "after P1", "after Q"],
            "motogp": ["pre-weekend", "after FP1", "after PR", "after Q1", "after Q2", "after Sprint"]}[sport]
    assert [lab for lab, _ in plans[keys[3]]["stages"]] == want
    assert [lab for lab, _ in plans[keys[2]]["stages"]] == ["T-3d", "T-1d", "race eve"]
    first = pd.Timestamp(WORLD[sport]["days"][3])
    until = first if sport == "nascar" else first + pd.Timedelta(hours=WORLD[sport]["race"])   # fallback / stored
    assert plans[keys[3]]["until"] == until and all(t < until for _, t in plans[keys[3]]["stages"])

    out = run(test_engine, sport, stages="sessions")
    p = out["params"]
    assert p["stages_mode"] == "sessions" and p["sessions"]["events"] == 3 and p["sessions"]["fallback_events"] == 1
    assert tuple(p["late_stages"]) == SW.late_labels(sport, "sessions")           # the mode's own late stages
    w = out["weekends"].set_index("event_key")
    assert list(w.index) == keys[2:] and w.loc[keys[3], "format"] == "sessions" and w.loc[keys[2], "format"] == "weekend"
    assert w.loc[keys[3], "stages"] == len(want) and w.loc[keys[3], "markets"] == 4
    stages = set(out["trades"]["stage"])
    assert stages & set(want[1:]), stages                                        # entries after a session ...
    assert stages <= set(want) | {"T-3d", "T-1d", "race eve"}
    assert set(out["totals"]) >= {"update", "hold", "last", "early", "maker"} and out["trades"]["pnl"].notna().all()
    # ... and the weekend mode on the same data is still the base commit's
    assert canon(run(test_engine, sport))[1] == BASE[sport]


@pytest.mark.parametrize("sport", ["nascar", "motogp"])
def test_every_stage_is_repriced_with_what_is_known_and_a_results_model_moves_nothing(world, test_engine, sport):
    """GlobalModel reads race results before the event only: asked at every stage (with the sessions run so far in
    Event.info), it prices each the same, and the same as the weekend mode's one pricing."""
    from conftest import TEST_DB
    from racinglines.models.race_model import Event
    world(sport)
    rs, plans = _plans(test_engine, sport, "sessions")
    r = list(rs.itertuples())[3]
    plan = plans[r.event_key]
    model = P.model_for(P.spec(sport))
    ms = model.Settings.from_dict({"sims": 300})
    hist = model.history(model.load(TEST_DB), ms)
    with test_engine.connect() as conn:
        field = SW.start_list(P.race_results(conn, r.race_id))
    seed = [ms.rng_seed, 7]
    seen, orig = [], model.price

    def spy(h, ev, s, rng):
        seen.append(list(ev.info["sessions"]))
        assert ev.cutoff == r.start and ev.info["field"] == field
        return orig(h, ev, s, rng)
    model.price = spy
    sims = SW.stage_sims(model, hist, ms, r, field, plan["stages"], plan["sessions"], sport, seed)
    model.price = orig
    assert list(sims) == [lab for lab, _ in plan["stages"]]
    assert [len(x) for x in seen] == list(range(len(plan["stages"])))       # one more session known at each stage
    one = model.price(hist, Event(id=r.event_key, season=int(r.season), cutoff=r.start, name=str(r.name),
                                  info={"field": field}), ms, np.random.default_rng(seed))
    for s in sims.values():
        assert s.entrants == one.entrants and np.array_equal(s.rank, one.rank) and np.array_equal(s.finished, one.finished)


def test_the_sweep_prices_the_start_list_not_the_non_starters(world, test_engine):
    """A car on the entry list that did not start (DNS) is not in the field the sweep prices, in either mode."""
    ids = world("nascar", dns=True)
    rs, _ = _plans(test_engine, "nascar", "weekend")
    with test_engine.connect() as conn:
        res = P.race_results(conn, rs["race_id"].iloc[3])
    assert ids[N] in set(res["athlete_id"]) and ids[N] not in SW.start_list(res)
    for mode in ("weekend", "sessions"):
        out = run(test_engine, "nascar", stages=mode)
        assert out["weekends"]["markets"].tolist() == [4, 4] and out["trades"]["pnl"].notna().all()
