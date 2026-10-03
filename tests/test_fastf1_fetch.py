import pandas as pd

from racinglines.sources.fastf1.fetch import session_started


def _weekend():
    """A conventional weekend as FastF1's schedule row has it: EventDate is the race day."""
    return {"EventDate": pd.Timestamp("2026-10-04"),
            "Session1": "Practice 1", "Session1DateUtc": pd.Timestamp("2026-10-02 04:30"),
            "Session2": "Practice 2", "Session2DateUtc": pd.Timestamp("2026-10-02 08:00"),
            "Session3": "Practice 3", "Session3DateUtc": pd.Timestamp("2026-10-03 04:30"),
            "Session4": "Qualifying", "Session4DateUtc": pd.Timestamp("2026-10-03 08:00"),
            "Session5": "Race", "Session5DateUtc": pd.Timestamp("2026-10-04 07:00")}


def test_sessions_of_a_weekend_in_progress_are_fetched_before_race_day():
    ev, now = _weekend(), pd.Timestamp("2026-10-03 12:00")
    assert [k for k in ("FP1", "FP2", "FP3", "Q", "R", "SQ", "S") if session_started(ev, k, now)] == ["FP1", "FP2", "FP3", "Q"]


def test_nothing_before_the_weekend_and_everything_after():
    ev = _weekend()
    assert not any(session_started(ev, k, pd.Timestamp("2026-10-01 12:00")) for k in ("FP1", "Q", "R"))
    assert all(session_started(ev, k, pd.Timestamp("2026-10-05")) for k in ("FP1", "FP2", "FP3", "Q", "R"))


def test_an_undated_session_falls_back_to_the_race_day():
    ev = dict(_weekend(), Session4DateUtc=pd.NaT)
    assert not session_started(ev, "Q", pd.Timestamp("2026-10-03 12:00"))
    assert session_started(ev, "Q", pd.Timestamp("2026-10-04 12:00"))
