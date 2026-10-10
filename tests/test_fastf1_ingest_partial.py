"""A weekend is stored as each session ends: FP1 and sprint qualifying before qualifying or the race exist."""
import json

import pandas as pd


def _session(d, rnd, code, rows, event_format="sprint_qualifying"):
    base = d / f"{rnd:02d}_{code}"
    pd.DataFrame(rows).to_parquet(base.with_suffix(".results.parquet"), index=False)
    pd.DataFrame({"Driver": [r["Abbreviation"] for r in rows], "DriverNumber": [r["DriverNumber"] for r in rows],
                  "LapNumber": [1.0] * len(rows), "LapTime": [100.0 + i for i in range(len(rows))]}).reindex(
        columns=["Driver", "DriverNumber", "Team", "LapNumber", "Stint", "LapTime", "Sector1Time", "Sector2Time",
                 "Sector3Time", "SpeedI1", "SpeedI2", "SpeedFL", "SpeedST", "Compound", "TyreLife", "PitInTime",
                 "PitOutTime", "TrackStatus", "Position", "IsAccurate", "Deleted"]).to_parquet(
        base.with_suffix(".laps.parquet"), index=False)
    base.with_suffix(".meta.json").write_text(json.dumps(dict(
        session=code, event_name="Singapore Grand Prix", official_name="SINGAPORE GP", location="Marina Bay",
        event_date="2026-10-11", session_date="2026-10-09 09:30:00", event_format=event_format)))


def _row(num, abbr, did, pos):
    return dict(DriverNumber=num, Abbreviation=abbr, DriverId=did, FullName=abbr, CountryCode="GBR", TeamName="T",
                TeamId="t", Position=float(pos), ClassifiedPosition=str(pos), GridPosition=float(pos), Status="Finished",
                Points=0.0, Laps=1.0, Q1=90.0 + pos, Q2=None, Q3=None, Time=None)


def test_practice_and_sprint_qualifying_are_stored_before_qualifying(tmp_path, test_engine, monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from racinglines.db import models as m
    from racinglines.sources.fastf1 import ingest as I
    d = tmp_path / "2026"
    d.mkdir()
    earlier = [_row("1", "AAA", "driver_a", 1), _row("2", "BBB", "driver_b", 2)]
    _session(d, 16, "Q", earlier, "conventional")
    _session(d, 16, "R", earlier, "conventional")
    # this weekend so far: FP1, and sprint qualifying without driver ids (as FastF1 gives it)
    _session(d, 17, "FP1", [_row("1", "AAA", "driver_a", 2), _row("2", "BBB", "driver_b", 1)])
    _session(d, 17, "SQ", [_row("1", "AAA", "", 1), _row("2", "BBB", None, 2)])
    monkeypatch.setattr(I, "DATA", tmp_path)
    with sessionmaker(test_engine)() as s:
        I.seed(s)
        s.commit()
        assert I.ingest_event(s, 2026, 16).startswith("4 results")
        assert I.ingest_event(s, 2026, 17).startswith("4 results")
        s.commit()
        ev = s.scalars(select(m.Event).filter_by(source_key="2026-17")).one()
        race = s.scalars(select(m.Race).filter_by(event_id=ev.id)).one()
        kinds = sorted(s.scalars(select(m.Round.kind).filter_by(race_id=race.id)))
        assert ev.status == "in_progress"
        assert race.format["sprint"] is True
        assert kinds == ["fp1", "sprint_qual"]
        sq = s.scalars(select(m.Round).filter_by(race_id=race.id, kind="sprint_qual")).one()
        assert len(s.scalars(select(m.Result).filter_by(round_id=sq.id)).all()) == 2      # ids filled from round 16
    from racinglines.models.position_sim import pricing as run
    meas = run.Measurements.load(test_engine)       # a weekend with no qualifying yet loads like any other
    ev17 = meas.res[(meas.res["year"] == 2026) & (meas.res["series_round"] == 17)]
    assert set(ev17["round"]) == {"fp1", "sprint_qual"}


def test_qualifying_order_from_laps_when_the_results_have_none():
    """Right after qualifying FastF1 gives no Position and no Q1-Q3: the knockout order is read from the laps (22 cars:
    Q3 is the 10 that ran last, then 6 out in Q2, 6 out in Q1). A Q2 lap faster than a Q3 runner's best still ranks
    11th, and a Q3 runner with no Q3 time ranks behind those who set one."""
    from racinglines.sources.fastf1 import ingest as I
    n = 22
    res = pd.DataFrame(dict(DriverNumber=[str(i) for i in range(1, n + 1)], Position=[None] * n,
                            Q1=[None] * n, Q2=[None] * n, Q3=[None] * n))
    rows = []
    for i in range(1, n + 1):
        rows.append((str(i), 100.0, 90.0 + i * 0.1))                 # Q1: everyone, slower car = higher number
        if i <= 16:
            rows.append((str(i), 1500.0, 89.0 + i * 0.1))            # Q2: the top 16
        if i <= 10 and i != 9:
            rows.append((str(i), 2400.0, 88.5 + i * 0.1))            # Q3: the top 10, car 9 sets no time
    rows.append(("11", 1510.0, 88.0))                                 # car 11's Q2 lap beats every Q3 lap
    rows.append(("9", 2300.0, None))                                  # car 9 goes out in Q3 but sets no lap time
    laps = pd.DataFrame(rows, columns=["DriverNumber", "Time", "LapTime"])
    out = I.knockout_from_laps(res, laps).set_index("DriverNumber")
    assert [int(out.loc[str(i), "Position"]) for i in range(1, 11)] == [1, 2, 3, 4, 5, 6, 7, 8, 10, 9]
    assert int(out.loc["11", "Position"]) == 11 and int(out.loc["17", "Position"]) == 17
    assert out.loc["1", "Q3"] == 88.6 and out.loc["11", "Q2"] == 88.0 and pd.isna(out.loc["9", "Q3"])
    has = res.assign(Position=range(1, n + 1))
    assert I.knockout_from_laps(has, laps) is has                    # an official classification is kept as it is
