"""The weather forecast frame (racinglines/weather/schema.py) and the provider parsers, offline. The
Open-Meteo parser reads tests/fixtures/weather/open_meteo-sample.json (a captured response, the probe of
2026-10-06); Weather Underground reads wunderground-sample.json, hand-written to its declared (unverified) field names."""

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from racinglines.frames.schema import FrameError
from racinglines.weather import schema as S
from racinglines.weather import open_meteo as OM
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


OM_FIXTURE = Path(__file__).parent / "fixtures" / "weather" / "open_meteo-sample.json"


def test_open_meteo_fixture_is_a_captured_response():
    raw = json.loads(OM_FIXTURE.read_text())
    assert raw["provider"] == OM.SOURCE and raw["lat"] == 1.2914 and raw["lon"] == 103.864
    assert OM.missing_fields(raw) == []
    assert all(0 <= v <= 100 for v in raw["hourly"][OM.H_PRECIP_CHANCE] + raw["daily"][OM.D_PRECIP_CHANCE])
    assert raw["meta"]["hourly_units"][OM.H_WIND] == "km/h" and raw["meta"]["hourly_units"][OM.H_PRECIP] == "mm"


def test_open_meteo_parse_and_summary():
    raw = json.loads(OM_FIXTURE.read_text())
    sessions = {"race": (pd.Timestamp("2026-10-07 08:00"), pd.Timestamp("2026-10-07 10:00"))}
    df = OM.parse(raw, "2026-17", raw["lat"], raw["lon"], ISSUED, sessions)
    assert S.problems(df) == []
    assert df["session"].value_counts().to_dict() == {"hour": 46, "day": 2, "race": 2}
    assert df["precip_prob"].between(0, 1).all() and (df["source"] == "open_meteo").all()
    day1 = df[df["session"] == "day"].iloc[0]
    assert day1["valid_utc"] == pd.Timestamp("2026-10-05 16:00")          # local midnight in Singapore (UTC+8)
    assert day1["precip_prob"] == 0.28 and day1["temp_c"] == pytest.approx(30.4)
    assert day1["condition"] == "Light drizzle"
    race = S.summary(df, "race")
    assert race["precip_prob"] == 0.49 and race["precip_mm"] == pytest.approx(0.5) and race["wind_kph"] == 11.2


def test_open_meteo_hourly_only_and_a_missing_field_fails_loudly():
    raw = json.loads(OM_FIXTURE.read_text())
    assert set(OM.parse({**raw, "daily": None}, "2026-17", 0.0, 0.0, ISSUED)["session"]) == {"hour"}
    bad = copy.deepcopy(raw)
    del bad["hourly"][OM.H_PRECIP_CHANCE]
    with pytest.raises(OM.OpenMeteoFieldError, match=OM.H_PRECIP_CHANCE):
        OM.parse(bad, "2026-17", 0.0, 0.0, ISSUED)
    assert OM.missing_fields(bad) == [f"hourly.{OM.H_PRECIP_CHANCE}"]
    bad = copy.deepcopy(raw)
    bad["daily"][OM.D_WIND] = [1.0]                    # one value for two days
    with pytest.raises(OM.OpenMeteoFieldError, match=OM.D_WIND):
        OM.parse(bad, "2026-17", 0.0, 0.0, ISSUED)


# --- the wet-race forecast (weather/wet.py) and the forecasts of past races (open_meteo.lead_rows) ---

from racinglines.models.position_sim import props as P  # noqa: E402
from racinglines.weather import wet as WET  # noqa: E402

LEADS_FIXTURE = Path(__file__).parent / "fixtures" / "weather" / "open_meteo-leads-f1.csv"
HISTORY_FIXTURE = Path(__file__).parent / "fixtures" / "weather" / "f1-wet-history.csv"
PREV_FIXTURE = Path(__file__).parent / "fixtures" / "weather" / "open_meteo-previous-runs-sample.json"


def test_venues_cover_every_race_slug():
    v = WET.venues()
    hist = pd.read_csv(HISTORY_FIXTURE)
    assert set(hist["slug"]) <= set(v) and len(v) == 34
    assert all(-90 <= x["lat"] <= 90 and -180 <= x["lon"] <= 180 for x in v.values())
    assert v["marina-bay"]["lat"] == 1.2914 and v["kuala-lumpur"]["circuit"] == "sepang"


def test_window_values_from_a_captured_previous_runs_response():
    hourly = json.loads(PREV_FIXTURE.read_text())["hourly"]
    start = pd.Timestamp("2024-09-22 12:00")
    gfs = OM.window_values(hourly, start, "_previous_day5", "gfs_seamless")
    assert gfs["max_hour_mm"] == 0.1 and gfs["precip_mm"] == pytest.approx(0.1)   # 0.1 mm at 11:00 and 12:00
    cma = OM.window_values(hourly, start, "_previous_day5", "cma_grapes_global")
    assert cma["max_hour_mm"] == 1.3 and cma["precip_mm"] == pytest.approx(1.3)   # 13:00 in, 14:00 out of the race window
    assert OM.window_values(hourly, start, "_previous_day5", "bom_access_global") is None
    rows = OM.lead_rows(dict(race_id=238, event_key="2024-18", venue_slug="marina-bay", lat=1.2914, lon=103.864,
                             race_start_utc="2024-09-22 12:00:00"), {"lead0": None, "previous": {"hourly": hourly}},
                        leads=(5,))
    assert len(rows) == 6 and set(rows[0]) == set(OM.LEAD_COLUMNS) and rows[0]["precip_prob"] is None
    assert sum(r["max_hour_mm"] >= WET.WET_MM for r in rows) == 4


def test_leads_fixture_shape():
    ld = pd.read_csv(LEADS_FIXTURE)
    assert list(ld.columns) == list(OM.LEAD_COLUMNS)
    assert ld["race_id"].nunique() == 147 and set(ld["lead_days"]) <= set(range(8))
    assert ld["precip_prob"].isna().all() and (ld["precip_mm"] >= -0.5).all()     # JMA once sends -0.2 mm (2024-06)
    since = ld[pd.to_datetime(ld["race_start_utc"]) >= WET.FIRST_ARCHIVED]
    assert (since.groupby("race_id")["lead_days"].apply(lambda s: 5 in set(s))).all()


def test_p_wet_shrinks_the_vote_to_climatology():
    assert WET.p_wet(0, 0, 0.3) == pytest.approx(0.3)
    assert WET.p_wet(7, 7, 0.2, prior=3.0) == pytest.approx((7 + 0.6) / 10)
    assert WET.p_wet(3, 5, 0.286) == pytest.approx(0.482, abs=1e-3)


def test_vote_from_a_forecast_block():
    t0 = pd.Timestamp("2026-10-11 10:00")
    times = [int((t0 + pd.Timedelta(hours=i)).timestamp()) for i in range(6)]       # 10:00 .. 15:00
    hourly = {"time": times, "precipitation_ecmwf_ifs025": [0, 0.0, 0.2, 0, 0, 0],
              "precipitation_gfs_seamless": [5.0, 0, 0, 0, 0, 0.0], "precipitation_icon_seamless": [None] * 6}
    v = WET.vote(hourly, pd.Timestamp("2026-10-11 12:00"))       # window 11:00-15:00
    assert v["models"] == 2 and v["wet_votes"] == 1


def test_save_and_load_vote_as_of(tmp_path, monkeypatch):
    monkeypatch.setenv(S.ROOT_ENV, str(tmp_path))
    start = pd.Timestamp("2026-10-11 12:00")
    WET.save_vote("2026-17", start, 1.2914, 103.864, {"models": 5, "wet_votes": 3, "max_mm": 0.36}, "2026-10-06 08:00")
    WET.save_vote("2026-17", start, 1.2914, 103.864, {"models": 5, "wet_votes": 1, "max_mm": 0.1}, "2026-10-08 08:00")
    assert WET.load_vote("2026-17", "2026-10-07")["wet_votes"] == 3
    assert WET.load_vote("2026-17", "2026-10-09")["wet_votes"] == 1
    assert WET.load_vote("2026-17", "2026-10-05") is None and WET.load_vote("2026-18") is None
    assert WET.load_vote("2026-17", "2026-10-07")["lead_hours"] == 124.0


def test_market_set_prices_rain_at_p_wet():
    hist = P.prepare(pd.read_csv(HISTORY_FIXTURE))
    base = {m["kind"]: m["fair"] for m in P.market_set(pd.DataFrame(), 17, hist, tuple(P.BINARY))}
    wx = {m["kind"]: m["fair"] for m in P.market_set(pd.DataFrame(), 17, hist, tuple(P.BINARY), p_wet=0.9)}
    assert wx["race_rain"] == 0.9 and base["race_rain"] != 0.9
    assert wx["race_red_flag"] > base["race_red_flag"]                 # red flags likelier in the wet
    assert wx["race_safety_car"] == base["race_safety_car"]            # not conditioned (decision log 2026-10-06)


def test_backtest_from_the_fixtures_pins_the_5_day_result():
    hist = pd.read_csv(HISTORY_FIXTURE)
    rows = WET.backtest(hist)
    assert len(rows) == 63 and int(rows["wet"].sum()) == 13
    _, summ = WET.score(rows, hist, 5)
    s = summ.set_index(["prop", "method"])
    assert s.loc[("rain", "circuit-WX"), "brier"] < s.loc[("rain", "circuit"), "brier"] - 0.03
    corr = WET.correlations(hist)
    assert corr.loc["wet", "red_flag"] > 2 * corr.loc["dry", "red_flag"]


def test_wx_names():
    assert WET.wx_name("A") == "A-WX" and WET.wx_name("gridq+pretrain+reset-WX") == "gridq+pretrain+reset-WX"
    _, summ = WET.score(WET.backtest(pd.read_csv(HISTORY_FIXTURE)), pd.read_csv(HISTORY_FIXTURE), 5)
    assert {"circuit-WX", "climatology-WX"} <= set(summ["method"]) and "forecast" not in set(summ["method"])
