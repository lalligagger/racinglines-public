"""NASCAR and MotoGP pricing (core package C3): every model prices the event's start list, not everyone ever seen;
the global results model (models/model_global.py) runs for both sports through `racinglines backtest walk-forward`,
draws retirements, and carries the teams the team markets read. In memory, and on the 2026-09-29 probe fixtures
ingested into the test database (tests/fixtures/market/, see nascar_README.txt and motogp_README.txt)."""

import json
import shutil
from datetime import date

import numpy as np
import pandas as pd
import pytest
from conftest import FIX, require_market_fixtures

from racinglines.markets import kinds as K
from racinglines.models import model_global as G
from racinglines.models.motogp_model import MotoGPRace, MotoGPRaceChallenger
from racinglines.models.nascar_model import NascarCupRace, NascarCupRaceChallenger

MKT = FIX / "market"


def _frame():
    """Three races: driver 9 runs the first two and is not on the third race's entry list; 4 retires twice."""
    rows = []
    order = {"2026-1": [1, 2, 3, 4, 5, 6, 9], "2026-2": [2, 1, 9, 3, 5, 6, 4], "2026-3": [1, 3, 2, 5, 4, 6]}
    for k, (race, ids) in enumerate(order.items()):
        for pos, a in enumerate(ids, 1):
            dnf = a == 4 and race != "2026-3"
            rows.append(dict(season=2026, event_id=race, race_key=race, race=race, name=f"Race {k + 1}",
                             event_name=f"Race {k + 1}", date=pd.Timestamp("2026-03-01") + pd.Timedelta(weeks=k),
                             athlete_id=a, driver=f"D{a}", rider=f"D{a}", position=np.nan if dnf else pos,
                             status="DNF" if dnf else "OK", team=f"T{(a + 1) // 2}", points=0.0))
    rows.append(dict(rows[-1], athlete_id=7, driver="D7", rider="D7", position=np.nan, status="DNS", team="T4"))
    return pd.DataFrame(rows)


@pytest.mark.quick
@pytest.mark.parametrize("cls", [NascarCupRace, NascarCupRaceChallenger, MotoGPRace, MotoGPRaceChallenger, G.GlobalModel])
def test_every_model_prices_the_start_list_only(cls):
    model = cls()
    data = model.load(data=_frame())
    st = model.Settings.from_dict({"sims": 200, "seed": 1})
    ev = model.events(data, st)[-1]
    sims = model.price(model.history(data, st), ev, st, np.random.default_rng(1))
    assert sorted(sims.entrants) == [1, 2, 3, 4, 5, 6]        # 9 raced before but is not entered; 7 did not start
    assert ev.info["field"] == [1, 2, 3, 4, 5, 6]


@pytest.mark.quick
def test_the_global_model_draws_retirements_and_carries_teams():
    m = G.GlobalModel()
    data = m.load(data=_frame())
    st = m.Settings.from_dict({"sims": 2000, "seed": 3})
    ev = m.events(data, st)[-1]
    sims = m.price(m.history(data, st), ev, st, np.random.default_rng(3))
    retire = K.fair("race_retire", sims)
    assert (~sims.finished).any() and retire[sims.index(4)] > retire[sims.index(1)]    # 4 retired twice
    assert sims.groups == ["T1", "T1", "T2", "T2", "T3", "T3"]                          # the entry list's teams
    team_win = K.fair("race_constructor_win", sims)
    assert set(team_win) == {"T1", "T2", "T3"} and abs(sum(team_win.values()) - 1) < 1e-9
    for kind in ("race_win", "race_podium", "race_top5", "race_top10"):
        assert len(K.fair(kind, sims)) == 6
    assert 0 < K.fair("race_h2h", sims, 1, 4) < 1


@pytest.mark.quick
def test_the_teams_change_no_price():
    """Adding the groups draws nothing from the generator: the ranks are what they were without teams."""
    m = G.GlobalModel()
    with_teams = m.load(data=_frame())
    without = m.load(data=_frame().drop(columns=["team"]))
    st = m.Settings.from_dict({"sims": 300, "seed": 5})
    a = m.price(m.history(with_teams, st), m.events(with_teams, st)[-1], st, np.random.default_rng(5))
    b = m.price(m.history(without, st), m.events(without, st)[-1], st, np.random.default_rng(5))
    assert b.groups is None and np.array_equal(a.rank, b.rank) and np.array_equal(a.finished, b.finished)


@pytest.mark.quick
@pytest.mark.parametrize("sport", ["nascar", "motogp"])
def test_the_schema_keeps_the_earlier_models_runnable(sport):
    from racinglines.cli import backtest as B
    from racinglines.models import race_model as RM
    names = RM.challengers(sport)
    assert names and set(B.model_choices(sport)) == {"global", *names}
    for name in names:
        assert B.pricing_model(sport, name).name == name
    with pytest.raises(ValueError, match="challengers"):
        RM.challenger(sport, "nope")


# --- the CLI on the probe fixtures, in the test database --------------------------------------------------------

def _clean(S, I):
    from sqlalchemy import delete, select

    from racinglines.db import models as m
    with S() as s:
        s.execute(delete(m.Event).where(m.Event.source == I.SOURCE))
        s.execute(delete(m.SourceFile).where(m.SourceFile.parser == I.PARSER))
        ids = s.scalars(select(m.AthleteIdentifier.athlete_id).where(m.AthleteIdentifier.scheme == I.SCHEME)).all()
        s.execute(delete(m.AthleteIdentifier).where(m.AthleteIdentifier.scheme == I.SCHEME))
        s.execute(delete(m.Athlete).where(m.Athlete.id.in_(ids)))
        s.commit()


@pytest.fixture
def nascar_db(test_engine, tmp_path, monkeypatch):
    require_market_fixtures("nascar_race_list_2026", "nascar_weekend_feed_2026_5624", "nascar_weekend_feed_2026_5596",
                            "nascar_weekend_feed_2026_5626")
    from sqlalchemy.orm import sessionmaker

    from racinglines.sources import http
    from racinglines.sources.nascar import fetch as F
    from racinglines.sources.nascar import ingest as I
    monkeypatch.setattr(F, "OUT", tmp_path)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    for rel, name in (("2026/1/race_list_basic.json", "race_list_2026"),
                      *((f"2026/1/{r}/weekend-feed.json", f"weekend_feed_2026_{r}") for r in (5624, 5596, 5626))):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(MKT / f"nascar_{name}.json", tmp_path / rel)
    S = sessionmaker(test_engine)
    _clean(S, I)
    with S() as s:
        I.ingest(s, [2026], today=date(2026, 9, 29), echo=lambda *_: None)
    yield S
    _clean(S, I)


@pytest.fixture
def motogp_db(test_engine, tmp_path, monkeypatch):
    """THA as probed, and two later rounds made from it (BRA without its winner, USA in reverse order)."""
    require_market_fixtures("motogp_events_2026", "motogp_classification_2026_tha_motogp_race")
    from sqlalchemy.orm import sessionmaker

    from racinglines.db.ingest import ensure_competition
    from racinglines.sources.motogp import fetch as F
    from racinglines.sources.motogp import ingest as I
    monkeypatch.setattr(F, "OUT", tmp_path)
    (tmp_path / "2026").mkdir()
    (tmp_path / "2026" / "events.json").write_text((MKT / "motogp_events_2026.json").read_text())
    tha = json.loads((MKT / "motogp_classification_2026_tha_motogp_race.json").read_text())
    rows = tha["classification"]
    done = [r for r in rows if r.get("position")]
    rounds = {"THA": rows,
              "BRA": [dict(r, position=i) for i, r in enumerate(done[1:], 1)] + [r for r in rows if not r.get("position")],
              "USA": [dict(r, position=i) for i, r in enumerate(reversed(done), 1)] +
                     [r for r in rows if not r.get("position")]}
    for short, cl in rounds.items():
        (tmp_path / "2026" / short).mkdir()
        (tmp_path / "2026" / short / "classification.json").write_text(json.dumps({"classification": cl}))
    S = sessionmaker(test_engine)
    _clean(S, I)
    with S() as s:
        comp, cat = ensure_competition(s, I.SPORT)
        for short in rounds:
            I.ingest_event(s, comp, cat, 2026, short)
        s.commit()
    yield S, rows[0]["rider"]["full_name"]
    _clean(S, I)


def _walk_forward(sport, out, *extra):
    from conftest import TEST_DB

    from racinglines.cli import backtest as B
    assert B.main(["walk-forward", sport, "--db", TEST_DB, "--seasons", "2026", "--out-dir", str(out),
                   "--sims", "300", "--seed", "7", *extra]) == 0
    return pd.read_csv(out / "walk_forward_events.csv"), pd.read_csv(out / "walk_forward_calibration.csv")


def test_global_model_walk_forward_prices_nascar(nascar_db, tmp_path):
    from sqlalchemy import text
    ev, cal = _walk_forward("nascar", tmp_path, "--model", "global", "--kinds",
                            "race_win,race_podium,race_top5,race_top10,race_h2h")
    assert len(ev) == 2                                        # the first race has no history before it
    with nascar_db() as s:
        starters = dict(s.execute(text("""
            SELECT e.name, count(*) FROM results r JOIN rounds ro ON ro.id = r.round_id AND ro.kind = 'race'
            JOIN races ra ON ra.id = ro.race_id JOIN events e ON e.id = ra.event_id
            WHERE e.source = 'nascar_cf' AND e.start_date >= '2026-01-01' AND upper(r.status) <> 'DNS'
            GROUP BY e.name""")).all())
    assert all(n == starters[name] for name, n in zip(ev["event"], ev["n_entrants"]))    # the start list, no one else
    assert set(cal.loc[cal["season"] == "all", "kind"]) == {"race_win", "race_podium", "race_top5", "race_top10", "race_h2h"}


def test_global_model_walk_forward_prices_motogp_without_the_absent_rider(motogp_db, tmp_path):
    from conftest import TEST_DB
    from sqlalchemy import text

    from racinglines.cli import backtest as B
    S, winner = motogp_db
    ev, cal = _walk_forward("motogp", tmp_path, "--model", "global")
    assert list(ev["n_entrants"]) == [5, 6]                    # BRA: THA's winner is not entered; USA: all six
    m = B.pricing_model("motogp", "global")
    data = m.load(TEST_DB)
    st = m.Settings.from_dict({"sims": 500, "seed": 7})
    events = m.events(data, st)
    sims = m.price(m.history(data, st), events[1], st, np.random.default_rng(7))
    with S() as s:
        wid = s.execute(text("SELECT id FROM athletes WHERE display_name = :n"), dict(n=winner)).scalar()
    assert wid not in sims.entrants and len(sims.entrants) == 5
    assert (~sims.finished).any()                              # THA's retirement is in the history
    assert set(K.fair("race_constructor_win", sims)) <= set(data["team"].dropna())
