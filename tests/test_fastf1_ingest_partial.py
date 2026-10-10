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
