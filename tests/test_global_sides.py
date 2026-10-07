"""The GlobalModel's side classifications (racinglines/models/model_global.py, package C12b): NASCAR's pole from past
qualifying results and its fastest lap from past races' best laps ([model] sessions / best_lap in sports/nascar.toml).
Synthetic histories for the model; the 2026-09-29 NASCAR probe fixtures (tests/fixtures/market/nascar_*.json) for
the best-lap order and the database round trip."""

import json

import numpy as np
import pandas as pd
import pytest
from conftest import FIX, require_market_fixtures

from racinglines.markets import kinds as K
from racinglines.models import model_global as G
from racinglines.models.race_model import Event

MKT = FIX / "market"


def nascar():
    return G.GlobalModel.for_sport("nascar")()


def history(races=8, n=10, seed=4, strength=None, start="2025-03-01"):
    """`races` races, one a week, of entrants 1..n finishing in the order of strength + noise."""
    rng = np.random.default_rng(seed)
    s = np.asarray(strength if strength is not None else np.linspace(1.5, -1.5, n))
    rows = []
    for r in range(races):
        order = np.argsort(-(s + rng.normal(0, 0.6, n))) + 1
        date = pd.Timestamp(start) + pd.Timedelta(days=7 * r)
        rows += [dict(season=date.year, race=f"r{r}", date=date, athlete_id=int(a), position=p, status="OK",
                      team=f"t{(int(a) - 1) // 2}") for p, a in enumerate(order, 1)]
    return pd.DataFrame(rows)


def price(model, data, sides, cutoff="2025-06-01", seed=1, field=None, sims=4000):
    d = model.load(data=data, sides=sides)
    st = model.Settings.from_dict({"sims": sims, "seed": seed})
    ev = Event(id="next", season=2025, cutoff=pd.Timestamp(cutoff), name="next",
               info={"field": field or sorted(d["athlete_id"].unique().tolist())})
    return d, model.price(model.history(d, st), ev, st, np.random.default_rng(seed))


@pytest.mark.quick
def test_the_schema_names_nascars_side_classifications():
    m = nascar()
    assert m.cfg["sessions"] == ["qual"] and m.cfg["best_lap"] == "race_fastest_lap"


@pytest.mark.quick
def test_pole_and_fastest_lap_fairs_sum_to_one_over_the_field():
    race = history()
    qual = history(seed=5, strength=np.linspace(-1.5, 1.5, 10))           # entrant 10 qualifies best
    laps = history(seed=6, strength=np.linspace(1.0, -1.0, 10))
    _, sims = price(nascar(), race, {"qual": qual, "race_fastest_lap": laps})
    pole, fl = K.fair("race_pole", sims), K.fair("race_fastest_lap", sims)
    assert pole.sum() == pytest.approx(1.0) and fl.sum() == pytest.approx(1.0)
    assert int(np.argmax(pole)) == sims.index(10) and int(np.argmax(fl)) == sims.index(1)
    # the team aggregates over them price too: the constructor fastest lap sums to 1 over the teams
    assert sum(K.fair("race_constructor_fastest_lap", sims).values()) == pytest.approx(1.0)


@pytest.mark.quick
def test_the_race_prices_are_the_same_with_or_without_the_side_classifications():
    race = history()
    sides = {"qual": history(seed=5), "race_fastest_lap": history(seed=6)}
    _, with_sides = price(nascar(), race, sides)
    _, without = price(nascar(), race, {})
    assert np.array_equal(with_sides.rank, without.rank) and np.array_equal(with_sides.finished, without.finished)
    assert without.stage_rank == {} and without.indicators == {}
    assert "race_pole" not in K.summary(without) and "race_pole" in K.summary(with_sides)


@pytest.mark.quick
def test_side_history_from_the_cutoff_on_is_not_used():
    race = history()
    qual = history(seed=5)
    late = qual.assign(date=qual["date"] + pd.Timedelta(days=400))      # every qualifying after the cutoff
    _, sims = price(nascar(), race, {"qual": late})
    assert "qual" not in sims.stage_rank                                 # nothing before the cutoff: not priced
    flip = qual.copy()                                                   # results on the cutoff day change nothing
    _, a = price(nascar(), race, {"qual": qual}, cutoff="2025-04-26")
    flip.loc[flip["date"] >= "2025-04-26", "position"] = flip["position"][::-1].to_numpy()[
        :int((flip["date"] >= "2025-04-26").sum())]
    _, b = price(nascar(), race, {"qual": flip}, cutoff="2025-04-26")
    assert np.array_equal(a.stage_rank["qual"], b.stage_rank["qual"])


@pytest.mark.quick
def test_results_settle_the_pole_and_the_fastest_lap():
    race, qual = history(races=3), history(races=3, seed=9)
    laps = history(races=3, seed=10).assign(laps_complete=True)
    m = nascar()
    d = m.load(data=race, sides={"qual": qual, "race_fastest_lap": laps})
    ev = Event(id="r2", season=2025, cutoff=pd.Timestamp("2025-03-15"), name="r2")
    res = m.results(d, ev)
    q, fl = qual[qual["race"] == "r2"], laps[laps["race"] == "r2"]
    pole, fast = int(q.loc[q["position"] == 1, "athlete_id"].iloc[0]), int(fl.loc[fl["position"] == 1, "athlete_id"].iloc[0])
    assert K.settle("race_pole", pole, {}, res) is True
    assert K.settle("race_pole", next(a for a in range(1, 11) if a != pole), {}, res) is False
    assert K.settle("race_fastest_lap", fast, {}, res) is True
    assert K.settle("race_fastest_lap", next(a for a in range(1, 11) if a != fast), {}, res) is False
    # incomplete laps: undecided; no qualifying stored for the race: undecided
    d = m.load(data=race, sides={"race_fastest_lap": laps.assign(laps_complete=False)})
    res = m.results(d, ev)
    assert K.settle("race_fastest_lap", fast, {}, res) is None and K.settle("race_pole", pole, {}, res) is None


@pytest.mark.quick
def test_best_lap_order_ranks_each_cars_fastest_lap():
    require_market_fixtures("nascar_lap_times_2026_5628")
    lt = json.loads((MKT / "nascar_lap_times_2026_5628.json").read_text())
    rows = [dict(race="kan", athlete_id=d["NASCARDriverID"], lap_time_ms=x.get("LapTime", 0) * 1000)
            for d in lt["laps"] for x in d["Laps"] if x.get("Lap")]
    o = G.best_lap_order(pd.DataFrame(rows))
    best = {d["NASCARDriverID"]: min(x["LapTime"] for x in d["Laps"] if x.get("Lap") and (x.get("LapTime") or 0) > 0)
            for d in lt["laps"]}
    want = sorted(best, key=best.get)
    assert o.sort_values("position")["athlete_id"].tolist() == want and o["position"].min() == 1
    assert len(o) == len(lt["laps"]) and set(o["status"]) == {"OK"}
    tie = G.best_lap_order(pd.DataFrame([dict(race="x", athlete_id=1, lap_time_ms=30_000),
                                         dict(race="x", athlete_id=2, lap_time_ms=30_000),
                                         dict(race="x", athlete_id=3, lap_time_ms=0)]))
    assert tie["position"].tolist() == [1.0, 1.0]                       # a tie shares the place; no time is no lap


# --- from the database --------------------------------------------------------------------------------------------

@pytest.fixture
def db(test_engine):
    from sqlalchemy import delete, select
    from sqlalchemy.orm import sessionmaker

    from racinglines.db import models as m
    from racinglines.sources.nascar import ingest as I
    S = sessionmaker(test_engine)

    def clean():
        with S() as s:
            s.execute(delete(m.Event).where(m.Event.source == I.SOURCE))
            ids = s.scalars(select(m.AthleteIdentifier.athlete_id).where(m.AthleteIdentifier.scheme == I.SCHEME)).all()
            s.execute(delete(m.AthleteIdentifier).where(m.AthleteIdentifier.scheme == I.SCHEME))
            s.execute(delete(m.Athlete).where(m.Athlete.id.in_(ids)))
            s.commit()

    clean()
    yield S
    clean()


def test_the_model_reads_qualifying_and_best_laps_from_the_database(db):
    """Daytona 2026 (a qualifying run with times) and Darlington's feed with Kansas's complete lap file (as
    tests/test_nascar.py builds it): the qualifying round and the best-lap order come back as side classifications
    and settle the race's pole and fastest lap."""
    require_market_fixtures("nascar_weekend_feed_2026_5596", "nascar_weekend_feed_2026_5624", "nascar_lap_times_2026_5628")
    from conftest import TEST_DB
    from racinglines.db.ingest import ensure_competition
    from racinglines.sources.nascar import ingest as I

    def fx(name):
        return json.loads((MKT / f"nascar_{name}.json").read_text())

    dar = {"weekend-feed": fx("weekend_feed_2026_5624"), "lap-times": fx("lap_times_2026_5628")}
    dar["weekend-feed"]["weekend_race"][0]["actual_laps"] = 267
    with db() as s:
        comp, cat = ensure_competition(s, "nascar")
        day = I.parse_race(2026, 5596, {"weekend-feed": fx("weekend_feed_2026_5596")}, 1)
        I.write(s, comp, cat, 2026, day)
        I.write(s, comp, cat, 2026, I.parse_race(2026, 5624, dar, 26))
        s.commit()
    m = nascar()
    data = m.load(TEST_DB)
    assert set(m.sides) == {"qual", "race_fastest_lap"}
    qual = next(r for r in day["rounds"] if r["kind"] == "qual")
    assert len(m.sides["qual"]) == len(qual["results"])
    evs = {e.name: e for e in m.events(data, m.Settings.from_dict({}))}
    daytona = m.results(data, next(e for k, e in evs.items() if "DAYTONA" in k.upper()))
    # the fixture keeps 8 qualifying rows and 12 race rows (README): one driver is in both, 8th in qualifying
    placed = daytona.dropna(subset=["qual_position"])
    assert placed["qual_position"].tolist() == [8.0]
    assert K.settle("race_pole", int(placed["athlete_id"].iloc[0]), {}, daytona) is False
    qual_frame = m.sides["qual"]
    pole = int(qual_frame.loc[qual_frame["position"] == 1, "athlete_id"].iloc[0])
    with_pole = pd.concat([daytona, pd.DataFrame([dict(athlete_id=pole, position=40.0, status="DNF",
                                                       qual_position=1.0)])], ignore_index=True)
    assert K.settle("race_pole", pole, {}, with_pole) is True
    darl = m.results(data, next(e for k, e in evs.items() if "DAYTONA" not in k.upper()))
    fast = darl.loc[darl["race_fastest_lap"], "athlete_id"].tolist()
    assert len(fast) == 1 and K.settle("race_fastest_lap", fast[0], {}, darl) is True
    assert darl["qual_position"].isna().all()                         # rained out: no qualifying round, undecided


@pytest.mark.quick
def test_the_walk_forward_scores_the_pole_and_the_fastest_lap():
    from racinglines.core import walk_forward as WF
    m = nascar()
    race, qual = history(races=16), history(races=16, seed=5)
    laps = history(races=16, seed=6).assign(laps_complete=True)
    d = m.load(data=race, sides={"qual": qual, "race_fastest_lap": laps})
    out = WF.run(m, d, m.Settings.from_dict({"sims": 400, "seed": 2}), seasons=[2025], echo=lambda *_: None)
    cal = out["calibration"].query("season == 'all'").set_index("kind")
    assert {"race_pole", "race_fastest_lap", "race_win"} <= set(cal.index)
    assert cal.loc["race_pole", "n"] == cal.loc["race_fastest_lap", "n"] == cal.loc["race_win", "n"]
    for kind in ("race_pole", "race_fastest_lap"):     # one YES per race among the scored rows, fairs sum to 1
        r = out["rows"].query("kind == @kind").dropna(subset=["y"])
        assert (r.groupby("event_id")["y"].sum() == 1).all()
        assert np.allclose(r.groupby("event_id")["fair"].sum(), 1.0)
