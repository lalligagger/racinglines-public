"""The weather forecast frame (racinglines/weather/schema.py) and the Weather Underground parser, offline: the
parser reads tests/fixtures/weather/wunderground-sample.json, hand-written to the declared (unverified) field names."""

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from racinglines.frames.schema import FrameError
from racinglines.weather import schema as S
from racinglines.weather import wunderground as W

pytestmark = pytest.mark.quick

FIXTURE = Path(__file__).parent / "fixtures" / "weather" / "wunderground-sample.json"
ISSUED = pd.Timestamp("2026-10-03 06:00")


def _frame(**over):
    n = 3
    df = pd.DataFrame({
        "event_key": ["2026-17"] * n, "session": ["race", "race", "day"],
        "valid_utc": pd.to_datetime(["2026-10-04 12:00", "2026-10-04 13:00", "2026-10-04 00:00"]),
        "issued_utc": pd.Timestamp(ISSUED), "precip_prob": [0.2, 0.7, 0.8], "precip_mm": [1.0, 3.0, 12.0],
        "temp_c": [30.0, 28.0, 28.5], "humidity": [80.0, 90.0, 92.0], "wind_kph": [10.0, 16.0, 15.0],
        "condition": ["Showers", "Rain", None], "source": "wunderground", "lat": 0.0, "lon": 0.0})
    for k, v in over.items():
        df[k] = v
    return df


def test_validate_passes_a_good_frame():
    df = _frame()
    assert S.validate(df) is df
    assert S.problems(df) == []


@pytest.mark.parametrize("over, column", [
    ({"precip_prob": [0.2, 1.5, 0.8]}, "precip_prob"),
    ({"humidity": [80.0, 101.0, 92.0]}, "humidity"),
    ({"session": ["race", "warmup", "day"]}, "session"),
    ({"valid_utc": pd.to_datetime(["2026-10-04 12:00"] * 3).tz_localize("UTC")}, "valid_utc"),
    ({"source": [None, "wunderground", "wunderground"]}, "source"),
    ({"lat": [0.0, 95.0, 0.0]}, "lat"),
])
def test_validate_names_the_column(over, column):
    with pytest.raises(FrameError) as ex:
        S.validate(_frame(**over))
    assert any(repr(column) in p for p in ex.value.problems), ex.value.problems


def test_validate_missing_column_and_duplicate_key():
    assert "missing column 'wind_kph'" in S.problems(_frame().drop(columns="wind_kph"))
    dup = _frame(valid_utc=pd.to_datetime(["2026-10-04 12:00"] * 2 + ["2026-10-04 00:00"]))
    assert any("duplicate" in p for p in S.problems(dup))


def test_summary_per_session():
    df = _frame()
    race = S.summary(df, "race")
    assert race["precip_prob"] == 0.7 and race["precip_mm"] == 4.0 and race["temp_c"] == 29.0
    assert race["wind_kph"] == 16.0 and race["issued_utc"] == pd.Timestamp(ISSUED) and race["source"] == "wunderground"
    assert S.summary(df, "day")["precip_mm"] == 12.0
    assert S.summary(df, "qual") is None


def test_save_load_round_trip_keeps_the_latest_issue(tmp_path, monkeypatch):
    monkeypatch.setenv(S.ROOT_ENV, str(tmp_path))
    old = _frame()
    new = _frame(issued_utc=pd.Timestamp("2026-10-03 12:00"), precip_prob=[0.1, 0.2, 0.3])
    p_old, p_new = S.save(old), S.save(new)
    assert p_old.parent == tmp_path / "weather" / "2026-17" and p_new.name == "wunderground-20261003T120000Z.parquet"
    got = S.load("2026-17")
    pd.testing.assert_frame_equal(got, new[list(S.COLUMNS)], check_dtype=False)
    assert S.load("2026-17", source="wunderground")["issued_utc"].iloc[0] == pd.Timestamp("2026-10-03 12:00")
    with pytest.raises(FileNotFoundError):
        S.load("2026-17", source="other")
    with pytest.raises(FileNotFoundError):
        S.load("2026-18")


def test_save_needs_one_issue_per_file(tmp_path, monkeypatch):
    monkeypatch.setenv(S.ROOT_ENV, str(tmp_path))
    with pytest.raises(FrameError):
        S.save(_frame(issued_utc=pd.to_datetime(["2026-10-03 06:00", "2026-10-03 07:00", "2026-10-03 06:00"])))


def test_parse_hand_written_fixture():
    raw = json.loads(FIXTURE.read_text())
    sessions = {"race": (pd.Timestamp("2026-10-04 12:00"), pd.Timestamp("2026-10-04 14:00"))}
    df = W.parse(raw, "2026-17", 0.0, 0.0, ISSUED, sessions)
    assert S.problems(df) == []
    assert df["session"].value_counts().to_dict() == {"day": 2, "race": 2, "hour": 2}
    day1, day2 = df[df["session"] == "day"].itertuples()
    assert day1.precip_prob == 0.4 and day1.wind_kph == 9 and day1.humidity == 85 and day1.temp_c == 25
    assert day2.precip_prob == 0.8 and day2.precip_mm == 12.0 and day2.temp_c == 28.5 and day2.humidity == 92
    race = S.summary(df, "race")
    assert race["precip_prob"] == 0.7 and race["precip_mm"] == pytest.approx(4.6) and race["wind_kph"] == 16
    assert (df["source"] == "wunderground").all() and (df["issued_utc"] == pd.Timestamp(ISSUED)).all()
    assert W.missing_fields(raw) == []


def test_parse_daily_only_and_a_wrong_field_fails_loudly():
    raw = json.loads(FIXTURE.read_text())
    daily = W.parse({**raw, "hourly": None}, "2026-17", 0.0, 0.0, ISSUED)
    assert set(daily["session"]) == {"day"}
    bad = copy.deepcopy(raw)
    bad["hourly"]["precipProbability"] = bad["hourly"].pop(W.H_PRECIP_CHANCE)
    with pytest.raises(W.WundergroundFieldError, match=W.H_PRECIP_CHANCE):
        W.parse(bad, "2026-17", 0.0, 0.0, ISSUED)
    assert W.missing_fields(bad) == [f"hourly.{W.H_PRECIP_CHANCE}"]
    bad = copy.deepcopy(raw)
    del bad["daily"]["daypart"][0][W.DP_WIND]
    with pytest.raises(W.WundergroundFieldError, match=W.DP_WIND):
        W.parse(bad, "2026-17", 0.0, 0.0, ISSUED)
    bad = copy.deepcopy(raw)
    bad["daily"][W.D_QPF] = [1.0]                      # one value for two days
    with pytest.raises(W.WundergroundFieldError, match=W.D_QPF):
        W.parse(bad, "2026-17", 0.0, 0.0, ISSUED)


def test_fetch_raw_needs_a_key():
    with pytest.raises(SystemExit, match=W.KEY_ENV):
        W.fetch_raw(0.0, 0.0, "")


def test_no_nan_columns_from_the_fixture():
    df = W.parse(json.loads(FIXTURE.read_text()), "2026-17", 0.0, 0.0, ISSUED)
    for c in ("precip_prob", "precip_mm", "temp_c", "humidity", "wind_kph"):
        assert not np.isnan(df[c]).all(), c
