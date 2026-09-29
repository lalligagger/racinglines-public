"""
L1 input frames (racinglines/frames, docs/frames.md): the schemas validate what they should, and the F1 and
downhill adapters produce every frame their sport schema declares, from the same pinned fixtures the pipeline tests
use (the tests that need a fixture skip when it isn't there, as those do).
"""

import numpy as np
import pandas as pd
import pytest
from conftest import need

from racinglines import sports
from racinglines.frames import FRAMES, SCHEMAS, FrameError, check_release, frames_for, validate


def _classifications(**over):
    """A tiny valid classifications frame (two riders, one session)."""
    df = pd.DataFrame({
        "event_id": [1, 1], "session": ["race", "race"], "athlete_id": [10, 11], "position": [1.0, 2.0],
        "status": ["OK", "OK"], "time_ms": [5000.0, 5100.0], "gap_ms": [0.0, 100.0], "grid": [2.0, 1.0],
        "points": [25.0, 18.0], "available_at": pd.to_datetime(["2026-01-01 15:00", "2026-01-01 15:00"])})
    return df.assign(**over)


# --- the declarations and validate() ---------------------------------------------------------------

@pytest.mark.quick
def test_a_hand_made_frame_validates():
    df = _classifications()
    assert validate("classifications", df) is df
    validate("classifications", df.assign(extra_column="a sport may carry more"))      # extra columns are allowed
    validate("classifications", df.iloc[:0])                                            # so is an empty frame


@pytest.mark.quick
def test_validate_fails_on_a_duplicate_key():
    df = pd.concat([_classifications(), _classifications().iloc[:1]], ignore_index=True)
    with pytest.raises(FrameError, match=r"1 rows repeat a key \['event_id', 'session', 'athlete_id'\]"):
        validate("classifications", df)


@pytest.mark.quick
def test_validate_fails_on_a_missing_column():
    with pytest.raises(FrameError, match=r"missing columns \['status'\]"):
        validate("classifications", _classifications().drop(columns="status"))


@pytest.mark.quick
def test_validate_fails_on_a_null_available_at():
    df = _classifications()
    df.loc[1, "available_at"] = pd.NaT
    with pytest.raises(FrameError, match="1 of 2 rows have no available_at"):
        validate("classifications", df)


@pytest.mark.quick
@pytest.mark.parametrize("column, values, message", [
    ("athlete_id", [10.5, 11.5], "'athlete_id' has dtype float64, expected int"),
    ("position", ["1", "2"], "'position' has dtype object, expected number"),
    ("status", [None, "OK"], "'status' has 1 nulls but isn't nullable"),
    ("available_at", pd.to_datetime(["2026-01-01", "2026-01-02"]).tz_localize("UTC"), "timezone-aware"),
])
def test_validate_fails_on_the_wrong_dtype_or_nulls(column, values, message):
    with pytest.raises(FrameError, match=message):
        validate("classifications", _classifications().assign(**{column: values}))


@pytest.mark.quick
def test_validate_reports_every_problem_at_once():
    df = _classifications().drop(columns="grid").assign(status=[None, "OK"])
    with pytest.raises(FrameError) as ex:
        validate("classifications", df)
    assert len(ex.value.problems) == 2


@pytest.mark.quick
def test_validate_rejects_an_unknown_frame_and_a_non_frame():
    with pytest.raises(FrameError, match="unknown frame 'nope'"):
        validate("nope", _classifications())
    with pytest.raises(FrameError, match="expected a DataFrame"):
        validate("classifications", [1, 2])


@pytest.mark.quick
@pytest.mark.parametrize("name", FRAMES)
def test_every_declaration_is_consistent(name):
    sc = SCHEMAS[name]
    assert set(sc.key) <= set(sc.column_names)
    assert sc.available_at in sc.column_names and sc.available_at not in sc.key
    assert {c.name: c for c in sc.columns}[sc.available_at].dtype == "datetime"


# --- the [data] block of the sport schemas -----------------------------------------------------------

@pytest.mark.quick
@pytest.mark.parametrize("code", sports.SPORT_CODES)
def test_sport_schemas_declare_known_frames(code):
    declared = sports.frames(code)
    assert isinstance(declared, tuple)
    assert set(declared) <= set(FRAMES)
    assert len(set(declared)) == len(declared)
    if code not in ("f1", "mtb_dh"):
        assert declared == ()                 # no block, no frames: absent means empty


@pytest.mark.quick
def test_the_modeled_sports_declare_their_frames():
    assert sports.frames("f1") == ("entrants", "sessions", "classifications", "conditions", "venue_features",
                                   "official_results")
    assert sports.frames("mtb_dh") == ("entrants", "sessions", "classifications", "official_results")


@pytest.mark.quick
def test_frames_for_without_a_block_or_an_adapter(monkeypatch):
    assert frames_for("nascar", None) == {}                                    # nothing declared: nothing built
    with pytest.raises(FrameError, match="unknown sport 'curling'"):
        frames_for("curling", None)
    monkeypatch.setattr(sports, "frames", lambda code: ("laps",))
    with pytest.raises(FrameError, match=r"declares \['laps'\], which racinglines/frames/f1.py can't build"):
        frames_for("f1", None)
    monkeypatch.setattr(sports, "frames", lambda code: ("entrants",))
    with pytest.raises(FrameError, match="no adapter racinglines/frames/nascar.py"):
        frames_for("nascar", None)
    monkeypatch.setattr(sports, "frames", lambda code: ("pit_stops",))
    with pytest.raises(FrameError, match="unknown frames"):
        frames_for("f1", None)


# --- F1 ----------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def f1(f1_meas):
    return frames_for("f1", f1_meas)


def test_f1_produces_exactly_the_declared_frames(f1):
    assert tuple(f1) == sports.frames("f1")
    for name, df in f1.items():
        assert len(df) > 0, name
        validate(name, df)
        assert df["available_at"].notna().all(), name
        assert list(df.columns) == list(SCHEMAS[name].column_names), name


def test_f1_race_classification_matches_the_fixture_results(f1, f1_frames):
    res = f1_frames[0]
    c = f1["classifications"]
    n_race = int((res["round"] == "race").sum())
    assert n_race > 0
    assert int((c["session"] == "race").sum()) == n_race
    assert len(f1["official_results"]) == n_race
    assert len(c) == len(res)                                          # every results row, once
    assert not c.duplicated(["event_id", "session", "athlete_id"]).any()
    assert set(c["session"]) <= set(sports.load("f1")["sessions"]["minutes"])     # the sport's own vocabulary
    for name in ("entrants", "sessions"):
        assert set(f1[name]["event_id"]) == set(res["event_id"])


def test_f1_classification_values(f1, f1_frames):
    c = f1["classifications"]
    race = c[c["session"] == "race"]
    assert race["gap_ms"].dropna().ge(0).all()
    assert (race.loc[race["position"] == 1, "gap_ms"] == 0).all()
    assert race.groupby("event_id")["position"].apply(lambda p: (p == 1).sum()).eq(1).all()
    res = f1_frames[0]
    win = res[(res["round"] == "race") & (res["position"] == 1)].set_index("event_id")["time_ms"]
    top = race[race["position"] == 1].set_index("event_id")["time_ms"]
    assert top.sort_index().equals(win.sort_index())


def test_f1_available_at_is_the_end_of_the_session(f1):
    minutes = sports.load("f1")["sessions"]["minutes"]
    s = f1["sessions"]
    assert (s["available_at"] == s["end"]).all()
    assert (s["end"] - s["start"] == pd.to_timedelta(s["session"].map(minutes), unit="m")).all()
    at = f1["classifications"].merge(s, on=["event_id", "session"], suffixes=("", "_s"))
    assert (at["available_at"] == at["available_at_s"]).all()
    race_end = s[s["session"] == "race"].set_index("event_id")["end"]
    official = f1["official_results"]
    assert (official["available_at"] == official["event_id"].map(race_end)).all()   # the race's end
    assert (f1["conditions"]["available_at"] == f1["conditions"]["event_id"].map(race_end)).all()
    assert (f1["venue_features"]["available_at"] == f1["venue_features"]["event_id"].map(race_end)).all()


def test_f1_available_at_agrees_with_the_measurements_view(f1, f1_meas):
    """As-of the same cutoff, the frames show the same rows as Measurements.view: the leak boundary is unchanged."""
    ev = f1_meas.drivers.drop_duplicates("event_id").sort_values("r_ts")
    cutoffs = [t - pd.Timedelta(minutes=1) for t in ev["r_ts"]] + [ev["r_ts"].iloc[3] - pd.Timedelta(hours=30),
                                                                    ev["r_ts"].iloc[-1] + pd.Timedelta(days=1)]
    s = f1["sessions"]
    for end in s.loc[s["event_id"].isin(ev["event_id"].iloc[:2]), "end"]:          # a minute either side of every
        cutoffs += [end - pd.Timedelta(minutes=1), end + pd.Timedelta(minutes=1)]   # session end of two weekends
    c = f1["classifications"]
    for cutoff in cutoffs:
        v = f1_meas.view(cutoff)
        seen = c[c["available_at"] < cutoff]
        assert set(zip(seen["event_id"], seen["session"], seen["athlete_id"])) == \
            set(zip(v.res["event_id"], v.res["round"], v.res["athlete_id"])), cutoff
        for name in ("venue_features", "conditions"):
            df = f1[name]
            assert set(df.loc[df["available_at"] < cutoff, "event_id"]) <= set(v.prof["event_id"]), (name, cutoff)
        vf = f1["venue_features"]
        assert set(vf.loc[vf["available_at"] < cutoff, "event_id"]) == set(v.prof["event_id"]), cutoff
        o = f1["official_results"]
        assert set(o.loc[o["available_at"] < cutoff, "event_id"]) == set(v.drivers["event_id"]), cutoff


def test_f1_frames_match_what_the_model_reads(f1, f1_meas):
    """official_results carries what PositionSim.results settles on; the entrants are the model's entry list."""
    from racinglines.models.position_sim import pricing as run
    from racinglines.models.race_model import Event, PositionSim
    o = f1["official_results"]
    for event_id in sorted(o["event_id"].unique())[:3]:
        want = PositionSim().results(f1_meas, Event(id=event_id, season=2026, cutoff=None))
        got = o[o["event_id"] == event_id].set_index("athlete_id").reindex(want["athlete_id"])
        assert np.allclose(got["position"], want["position"], equal_nan=True)
        assert (got["status"].to_numpy() == want["status"].to_numpy()).all()
        assert np.allclose(got["points"], want["points"], equal_nan=True)
        ent = f1["entrants"]
        ent = ent[ent["event_id"] == event_id].set_index("athlete_id")
        listed = run.entry_list(f1_meas, event_id)
        assert set(ent.index) == set(listed["athlete_id"])
        assert (ent.loc[listed["athlete_id"], "team_id"].to_numpy() == listed["team_key"].to_numpy()).all()


def test_f1_conditions_and_venue_features(f1, f1_meas):
    cond, vf = f1["conditions"], f1["venue_features"]
    assert set(cond["session"]) == {"qual", "race"}
    assert cond["rain_share"].dropna().between(0, 1).all()
    prof = f1_meas.prof.set_index("event_id")
    row = cond[(cond["session"] == "race")].iloc[0]
    assert row["track_temp"] == pytest.approx(prof.loc[row["event_id"], "race_track_temp"])
    feats = vf.set_index("event_id")["features"]
    ev = prof.index[0]
    assert feats[ev]["lap_s"] == pytest.approx(prof.loc[ev, "lap_s"])
    assert all(isinstance(d, dict) and d for d in feats)
    assert not any("ready_ts" in d or "venue" in d for d in feats)


def test_f1_declares_no_laps_because_measurements_has_none(f1_meas):
    """The adapter can't build `laps` (Measurements holds derived measures, not laps): the schema mustn't claim it."""
    assert "laps" not in sports.frames("f1")
    assert not hasattr(f1_meas, "laps")


def test_f1_rows_without_a_session_time_are_rejected(f1_meas):
    from dataclasses import replace
    res = f1_meas.res.copy()
    res.loc[res.index[0], "session_ts"] = pd.NaT
    with pytest.raises(FrameError, match="have no available_at"):
        frames_for("f1", replace(f1_meas, res=res))


# --- downhill ----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dh_data():
    """What TimedRuns.load returns for the pinned tidy frame (as the pipeline test's `dh` fixture builds its own)."""
    from racinglines.models.race_model import TimedRuns
    return TimedRuns().load(data=pd.read_parquet(need("mtb", "tidy_2025_2026.parquet")))


@pytest.fixture(scope="module")
def dh(dh_data):
    return frames_for("mtb_dh", dh_data)


def test_mtb_produces_exactly_the_declared_frames(dh):
    assert tuple(dh) == sports.frames("mtb_dh")
    for name, df in dh.items():
        assert len(df) > 0, name
        validate(name, df)
        assert df["available_at"].notna().all(), name
        assert list(df.columns) == list(SCHEMAS[name].column_names), name


def test_mtb_classifications_are_one_row_per_run(dh, dh_data):
    c = dh["classifications"]
    finish = dh_data[dh_data["sector_id"] == "FINISH"]
    assert len(c) == len(finish)
    assert not c.duplicated(["event_id", "session", "athlete_id"]).any()
    assert set(c["session"]) <= set(sports.load("mtb_dh")["rounds"]["order"])
    assert set(dh["sessions"]["session"]) == set(c["session"])
    assert set(dh["entrants"]["event_id"]) == set(finish["event_id"])
    assert c["gap_ms"].dropna().ge(0).all()
    assert (c.loc[c["position"] == 1, "gap_ms"].dropna() == 0).all()
    ok = c[(c["status"] == "OK") & c["time_ms"].notna()]
    src = finish.set_index(["event_id", "round", "athlete_id"])["cum_time_s"]
    idx = pd.MultiIndex.from_frame(ok[["event_id", "session", "athlete_id"]])
    assert np.allclose(ok["time_ms"].to_numpy(), src.reindex(idx).to_numpy() * 1000, atol=0.5)


def test_mtb_sessions_and_available_at(dh):
    s = dh["sessions"]
    assert (s["available_at"] == s["end"]).all()
    assert (s["end"] - s["start"] >= pd.Timedelta(days=1)).all()                # start is the event date, end the weekend's
    at = dh["classifications"].merge(s, on=["event_id", "session"], suffixes=("", "_s"))
    assert len(at) == len(dh["classifications"])
    assert (at["available_at"] == at["available_at_s"]).all()
    assert (dh["official_results"]["available_at"] > pd.to_datetime(
        dh["official_results"]["event_id"].str.slice(0, 8))).all()             # after the event's date has ended


def test_mtb_available_at_reproduces_the_models_own_as_of_rule(dh, dh_data):
    """The model trains on rows with event_date < cutoff (timed_runs.season._training_rows). At each event's date
    the frame shows the same rows (no two events here are on consecutive days; it is only ever stricter than that)."""
    from racinglines.models.timed_runs import _training_rows
    finish = dh_data[dh_data["sector_id"] == "FINISH"]
    for date in sorted(dh_data["event_date"].unique()):
        model_rows = _training_rows(finish, None, date)
        seen = dh["classifications"][dh["classifications"]["available_at"] < pd.Timestamp(date)]
        assert set(zip(seen["event_id"], seen["session"], seen["athlete_id"])) == \
            set(zip(model_rows["event_id"], model_rows["round"], model_rows["athlete_id"])), date


def test_mtb_official_results_match_the_models_results(dh, dh_data):
    """The same result TimedRuns.results settles on, for each completed event of the 2026 Elite Men."""
    from racinglines.models.race_model import TimedRuns
    m = TimedRuns()
    st = m.Settings.from_dict({})
    o = dh["official_results"]
    events = m.events(dh_data, st, seasons=[2026])
    assert events
    for ev in events:
        want = m.results(dh_data, ev)
        got = o[o["event_id"] == ev.id].set_index("athlete_id").reindex(want["athlete_id"].str.removeprefix("ath:").astype(int))
        assert len(got) == len(want)
        assert np.allclose(got["position"], want["position"], equal_nan=True), ev.id
        assert (got["status"].to_numpy() == want["status"].to_numpy()).all(), ev.id
        assert np.allclose(got["points"], want["points"]), ev.id
        assert (got["rounds_reached"].map(lambda r: "final" in r).to_numpy() == want["reached_final"].to_numpy()).all()
    from racinglines.models.timed_runs import completed_events
    assert set(o["event_id"]) == set(completed_events(dh_data[dh_data["sector_id"] == "FINISH"]))
    assert not o.duplicated(["event_id", "athlete_id"]).any()
    assert o["rounds_reached"].map(lambda r: isinstance(r, tuple)).all()


def test_mtb_weekend_end_is_parsed_from_the_event_name(dh, dh_data):
    """The tables have no end date: the last day of the range in the event name, plus a day and 12 hours."""
    from racinglines.frames.mtb_dh import _last_day
    finish = dh_data[dh_data["sector_id"] == "FINISH"]
    ev = finish.groupby("event_id").agg(date=("event_date", "first"), name=("event_name", "first"))
    end = dh["sessions"].groupby("event_id")["end"].max()
    for event_id, r in ev.iterrows():
        last = _last_day(r["date"], r["name"])
        assert pd.Timestamp(r["date"]) <= last <= pd.Timestamp(r["date"]) + pd.Timedelta(days=14), event_id
        assert end[event_id] == last + pd.Timedelta(days=1, hours=12), event_id
    assert _last_day("2026-08-21", "X - Les Gets, August 21-23, FRA") == pd.Timestamp("2026-08-23")
    assert _last_day("2025-05-30", "X - Loudenvielle, May 30-Jun 1, FRA") == pd.Timestamp("2025-06-01")
    assert _last_day("2025-07-09", "X - Pal Arinsal, Jul 11-13, AND") == pd.Timestamp("2025-07-13")
    assert _last_day("2025-12-30", "X - Somewhere, Dec 30-Jan 1") == pd.Timestamp("2026-01-01")
    for name in (None, "no dates here", "X - Somewhere, Aug 1-3, FRA", "X - Somewhere, May 1-30"):   # fall back
        assert _last_day("2026-08-21", name) == pd.Timestamp("2026-08-23"), name


@pytest.mark.parametrize("event_id, cutoff", [("20260821_mtb_ME", "2026-08-22 18:00"), ("20250821_mtb_ME", "2025-08-25")])
def test_mtb_a_final_is_not_visible_before_its_day_is_over(dh, event_id, cutoff):
    """Between an event's start_date and the day of its final (Les Gets: the final is on the Sunday, the 23rd, and
    for 2025 on Aug 31) nothing of the final round, and no official result, is visible."""
    cutoff = pd.Timestamp(cutoff)
    c = dh["classifications"]
    mine = c[c["event_id"] == event_id]
    assert len(mine[mine["session"] == "final"]) > 0
    assert mine[(mine["session"] == "final") & (mine["available_at"] < cutoff)].empty
    o = dh["official_results"]
    assert len(o[o["event_id"] == event_id]) > 0
    assert o[(o["event_id"] == event_id) & (o["available_at"] < cutoff)].empty


def test_mtb_needs_the_tidy_frame(dh_data):
    with pytest.raises(FrameError, match=r"load_tidy.*\['rider_name'\]"):
        frames_for("mtb_dh", dh_data.drop(columns="rider_name"))


def test_mtb_start_numbers_arrive_as_text_without_a_decimal(dh_data):
    d = dh_data.assign(bib=dh_data["bib"].map(lambda v: float(v) if str(v).isdigit() else v))
    ent = frames_for("mtb_dh", d)["entrants"]
    assert ent["bib"].dropna().map(lambda b: isinstance(b, str) and not b.endswith(".0")).all()


def test_mtb_an_uncompleted_event_gives_a_typed_empty_official_results(dh, dh_data):
    from racinglines.frames.mtb_dh import official_results
    part = dh_data[dh_data["event_id"] == "20260925_mtb_ME"]
    assert not part.empty
    out = official_results(part)
    assert out.empty
    validate("official_results", out)
    assert out.dtypes.to_dict() == dh["official_results"].dtypes.to_dict()


@pytest.mark.quick
def test_validate_checks_the_dtypes_of_an_empty_frame():
    from racinglines.frames._util import empty
    for name in FRAMES:
        validate(name, empty(name))
    with pytest.raises(FrameError, match="'athlete_id' has dtype object, expected int"):
        validate("classifications", pd.DataFrame(columns=SCHEMAS["classifications"].column_names))


def test_mtb_frames_leave_the_loaded_data_alone(dh_data):
    before = dh_data.copy(deep=True)
    frames_for("mtb_dh", dh_data)
    pd.testing.assert_frame_equal(dh_data, before)


# --- release: sources publish whole sessions, after they end ----------------------------------------------------

def _release_frames(lap_times):
    """A one-session toy: the sessions frame and three laps dated by `lap_times`."""
    end = pd.Timestamp("2026-10-04 08:00")
    sessions = pd.DataFrame({"event_id": [1], "session": ["race"], "start": [end - pd.Timedelta(minutes=150)],
                             "end": [end], "available_at": [end]})
    laps = pd.DataFrame({"event_id": [1] * 3, "session": ["race"] * 3, "athlete_id": [7] * 3, "lap": [1, 2, 3],
                         "time_ms": [95000.0] * 3, "sector_ms": [None] * 3, "pit": [False] * 3,
                         "track_status": ["1"] * 3, "available_at": pd.to_datetime(lap_times)})
    return {"sessions": sessions, "laps": laps}, end


def test_release_accepts_laps_dated_at_session_end():
    fr, _ = _release_frames(["2026-10-04 08:00"] * 3)
    assert check_release(fr) is fr


def test_release_rejects_lap_by_lap_times_without_a_live_source():
    fr, _ = _release_frames(["2026-10-04 05:32", "2026-10-04 05:34", "2026-10-04 05:36"])
    with pytest.raises(FrameError) as ex:
        check_release(fr)
    text = " ".join(ex.value.problems)
    assert "more than one available_at" in text and "before their session ends" in text


def test_release_rejects_a_session_dated_before_it_ends():
    fr, _ = _release_frames(["2026-10-04 07:59"] * 3)
    with pytest.raises(FrameError, match="before their session ends"):
        check_release(fr)


def test_release_allows_row_times_for_a_declared_live_frame():
    fr, _ = _release_frames(["2026-10-04 07:10", "2026-10-04 07:12", "2026-10-04 07:14"])
    assert check_release(fr, live=("laps",)) is fr


def test_no_sport_declares_a_live_frame_today():
    assert sports.live_frames("f1") == ()
    assert sports.live_frames("mtb_dh") == ()
