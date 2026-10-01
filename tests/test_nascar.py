"""NASCAR content feeds (racinglines/sources/nascar): the fetch layer against a fake server, the parser on the
2026-09-29 probe fixtures (tests/fixtures/market/nascar_*.json, see nascar_README.txt), and the ingest into a
throwaway database. No network."""

import json
import shutil
from datetime import date

import httpx
import pandas as pd
import pytest

from conftest import FIX, require_market_fixtures

require_market_fixtures(
    "race_list_2026",
    "weekend_feed_2026_5624",
    "lap_times_2026_5624",
    "pit_data_2026_5624",
    "loopstats_2026_5624",
    "lap_times_2026_5628",
    "weekend_feed_2026_5596",
    "weekend_feed_2017_4599",
    "weekend_feed_2026_5624",
)

from racinglines.sources import http
from racinglines.sources.nascar import fetch as F
from racinglines.sources.nascar import identity as ID
from racinglines.sources.nascar import ingest as I

MKT = FIX / "market"
TODAY = date(2026, 9, 29)


def fx(name):
    return json.loads((MKT / f"nascar_{name}.json").read_text())


def darlington_feeds():
    return {"weekend-feed": fx("weekend_feed_2026_5624"), "lap-times": fx("lap_times_2026_5624"),
            "pit-data": fx("pit_data_2026_5624"), "loopstats": fx("loopstats_2026_5624")}


# --- parser ---------------------------------------------------------------------

@pytest.mark.quick
def test_status_of_maps_the_feeds_finishing_status():
    assert I.status_of({"finishing_position": 1, "finishing_status": "Running"}) == "OK"
    assert I.status_of({"finishing_position": 30, "finishing_status": "Accident"}) == "DNF"
    assert I.status_of({"finishing_position": 0, "finishing_status": ""}) == "DNS"        # entered, never took the green
    assert I.status_of({"finishing_position": 2, "finishing_status": "Running", "disqualified": True}) == "DSQ"


@pytest.mark.quick
def test_points_races_are_numbered_and_exhibitions_are_not():
    rounds = I.series_rounds(fx("race_list_2026"))
    assert len(rounds) == 36 and sorted(rounds.values()) == list(range(1, 37))
    assert rounds[5624] == 27 and rounds[5628] == 30
    assert 5593 not in rounds                                                              # the Clash (race_type_id 2)


@pytest.mark.quick
def test_rained_out_qualifying_writes_no_qualifying_round():
    """Darlington 2026: the qualifying run exists with every time 0 and the grid was set by formula."""
    p = I.parse_race(2026, 5624, darlington_feeds(), 27)
    assert [r["kind"] for r in p["rounds"]] == ["race"]
    assert p["format"]["qualifying_ran"] is False and "pole_winner_driver_id" not in p["format"]
    assert p["format"]["stage_laps"] == [106, 124, 137] and p["format"]["cautions"] == 6
    assert p["format"]["caution_segments"][1] == {"start_lap": 108, "end_lap": 113, "reason": "Accident", "free_pass_car": "3"}
    assert p["series_round"] == 27 and p["date"] == date(2026, 9, 6) and p["key"] == "2026-5624"


@pytest.mark.quick
def test_race_results_carry_grid_points_stages_and_loop_stats():
    p = I.parse_race(2026, 5624, darlington_feeds(), 27)
    rows = {r["driver_id"]: r for r in p["rounds"][-1]["results"]}
    bell = rows[4153]
    assert (bell["name"], bell["position"], bell["status"], bell["bib"], bell["team"]) == \
        ("Christopher Bell", 1, "OK", "20", "Joe Gibbs Racing")
    assert bell["extra"]["grid"] == 11 and bell["extra"]["points"] == 73 and bell["extra"]["laps_led"] == 46
    assert bell["extra"]["stages"] == [{"stage": 1, "position": 4, "points": 7}, {"stage": 2, "position": 1, "points": 10}]
    assert bell["extra"]["loop"]["rating"] == 126.66
    assert "qualifying_speed_mph" not in bell["extra"]                                     # 0 in the source: no speed was set
    # winner's clock time, then the gap to the winner (diff_time is milliseconds: P2's 1038 is the 1.038 s margin)
    assert bell["time_ms"] == 14_585_000                                                   # total_race_time "4:03:05"
    assert rows[4368]["time_ms"] == 14_585_000 + 1038
    assert p["format"]["margin_of_victory"] == "1.038"


@pytest.mark.quick
def test_pre_race_pit_entries_are_not_stops():
    """The probe fixture holds only the 15 pre-race entries (lap_count 0): none is a stop. Mid-race semantics of
    the pit feed are unverified until the first full pull, so stops keep the source's own field names."""
    p = I.parse_race(2026, 5624, darlington_feeds(), 27)
    assert all("pit_stops" not in r["extra"] for r in p["rounds"][-1]["results"])
    feeds = darlington_feeds()
    stop = dict(feeds["pit-data"][0], vehicle_number="20", lap_count=45, pit_stop_type="GREEN", pit_stop_duration=11.4,
                left_front_tire_changed=True, right_front_tire_changed=True)
    feeds["pit-data"] = feeds["pit-data"] + [stop]
    bell = next(r for r in I.parse_race(2026, 5624, feeds, 27)["rounds"][-1]["results"] if r["driver_id"] == 4153)
    assert bell["extra"]["pit_stops"] == [dict(lap_count=45, pit_stop_type="GREEN", pit_in_flag_status=8, pit_stop_duration=11.4,
                                               total_duration=30.303, positions_gained_lost=0, tires_changed=2)]


@pytest.mark.quick
def test_a_lap_file_with_holes_and_a_short_end_is_stored_but_flagged():
    """Darlington 2026: laps 330-335 are absent and nothing follows lap 355 of 367."""
    p = I.parse_race(2026, 5624, darlington_feeds(), 27)
    race = p["rounds"][-1]["extra"]
    assert (race["laps_complete"], race["laps_max"], race["laps_missing"], race["lap_drivers"]) == (False, 355, 6 + 12, 4)
    assert len(p["laps"][4030]) == 349 and 330 not in {x["lap"] for x in p["laps"][4030]}
    assert p["laps"][4030][0] == {"lap": 1, "lap_time_ms": 32513, "position": 26, "track_status": "1"}
    assert {x["track_status"] for x in p["laps"][4030]} == {"1", "2"}                      # green, yellow: no checkered, it is cut short


@pytest.mark.quick
def test_a_complete_lap_file_is_marked_complete():
    """Kansas 2026: max Lap 267 == actual_laps 267. (The Kansas weekend feed is not a fixture: reuse Darlington's
    results with the race distance set to Kansas's.)"""
    feeds = darlington_feeds()
    feeds["weekend-feed"]["weekend_race"][0]["actual_laps"] = 267
    feeds["lap-times"] = fx("lap_times_2026_5628")
    p = I.parse_race(2026, 5628, feeds, 30)
    race = p["rounds"][-1]["extra"]
    assert (race["laps_complete"], race["laps_max"], race["laps_missing"]) == (True, 267, 0)
    assert p["laps"][4030][-1]["lap"] == 267 and p["laps"][4030][-1]["track_status"] == "4"     # the checkered flag


@pytest.mark.quick
def test_an_overtime_lap_beyond_the_race_distance_does_not_make_the_laps_incomplete():
    """Daytona 500 2026: lap-times runs to lap 201, actual_laps is 200."""
    laps = [dict(Lap=n, LapTime=48.0 + n / 1000, LapSpeed="186.0", RunningPos=1) for n in range(0, 202)]
    lt = dict(laps=[dict(Number="5", FullName="Kyle Larson (C)", Manufacturer="Chv", RunningPos=1, NASCARDriverID=4030, Laps=laps)],
              flags=[dict(LapsCompleted=n, FlagState=1) for n in range(0, 202)])
    race = I.parse_race(2026, 5596, {"weekend-feed": fx("weekend_feed_2026_5596"), "lap-times": lt}, 1)["rounds"][-1]["extra"]
    assert (race["laps_complete"], race["laps_max"], race["laps_missing"]) == (True, 201, 0)


@pytest.mark.quick
def test_practice_qualifying_and_entries_that_never_started():
    """Daytona 500 2026: three practices, a final-round qualifying (Round 1 is all zeros in the source: dropped),
    and entries with finishing_position 0."""
    p = I.parse_race(2026, 5596, {"weekend-feed": fx("weekend_feed_2026_5596")}, 1)
    assert [(r["kind"], r["ordinal"]) for r in p["rounds"]] == [("fp1", 1), ("fp2", 2), ("fp3", 3), ("qual", 4), ("race", 5)]
    assert p["format"]["qualifying_ran"] is True
    fp1 = p["rounds"][0]["results"][0]
    assert fp1["time_ms"] == 48025 and fp1["status"] == "OK" and fp1["extra"]["run_name"] == "NCS Practice 1"
    race = p["rounds"][-1]["results"]
    assert [r["status"] for r in race].count("DNS") == 4 and all(r["position"] is None for r in race if r["status"] == "DNS")


@pytest.mark.quick
def test_the_2017_shape_parses_without_the_newer_fields():
    p = I.parse_race(2017, 4599, {"weekend-feed": fx("weekend_feed_2017_4599")})
    assert p["series_round"] is None and [r["kind"] for r in p["rounds"]] == ["fp1", "fp2", "fp3", "qual", "race"]
    logano = next(r for r in p["rounds"][-1]["results"] if r["driver_id"] == 3859)
    assert logano["extra"]["playoff_points"] == 0 and "stages" not in logano["extra"] and "crew_chief_id" not in logano["extra"]
    assert logano["status"] == "OK" and logano["position"] == 37


@pytest.mark.quick
def test_no_weekend_feed_or_no_results_is_no_race():
    assert I.parse_race(2026, 1, {}) is None
    empty = fx("weekend_feed_2026_5624")
    empty["weekend_race"][0]["results"] = []
    assert I.parse_race(2026, 1, {"weekend-feed": empty}) is None


def _nascar_data():
    rows = []
    drivers = [f"d{i:02d}" for i in range(1, 11)]
    driver_ids = {name: 1000 + idx for idx, name in enumerate(drivers)}
    for season in (2024, 2025, 2026):
        for race_idx in range(1, 5):
            base = [0.7 * (i % 5) + 0.25 * (season - 2024) for i in range(len(drivers))]
            order = sorted(range(len(drivers)), key=lambda i: base[i] + (race_idx * 0.05 * i))
            for pos, driver_idx in enumerate(order, 1):
                date = pd.Timestamp(f"{season}-04-{1 + race_idx * 7}")
                driver = drivers[driver_idx]
                rows.append(dict(
                    season=season,
                    race=f"{season}-{race_idx}",
                    date=date,
                    athlete_id=driver_ids[driver],
                    driver=driver,
                    position=pos,
                    team=f"team-{(driver_idx % 3) + 1}",
                    status="OK",
                    points=25 if pos == 1 else 0,
                ))
    return pd.DataFrame(rows)


def test_nascar_model_contract_and_in_memory_pricing_are_valid():
    from racinglines.models.nascar_model import NascarCupRace
    from racinglines.models.race_model import model_class

    assert model_class("nascar").__name__ == "NascarCupRace"

    df = pd.DataFrame([
        {"season": 2026, "event_id": "2026-5624", "race_key": "2026-5624", "date": pd.Timestamp("2026-09-06"),
         "athlete_id": 101, "driver": "Kyle Larson", "position": 1, "team": "Hendrick Motorsports", "status": "OK", "points": 40},
        {"season": 2026, "event_id": "2026-5624", "race_key": "2026-5624", "date": pd.Timestamp("2026-09-06"),
         "athlete_id": 202, "driver": "Christopher Bell", "position": 2, "team": "Joe Gibbs Racing", "status": "OK", "points": 32},
        {"season": 2026, "event_id": "2026-5624", "race_key": "2026-5624", "date": pd.Timestamp("2026-09-06"),
         "athlete_id": 303, "driver": "Ryan Blaney", "position": 3, "team": "Team Penske", "status": "OK", "points": 28},
        {"season": 2026, "event_id": "2026-5625", "race_key": "2026-5625", "date": pd.Timestamp("2026-09-13"),
         "athlete_id": 202, "driver": "Christopher Bell", "position": 1, "team": "Joe Gibbs Racing", "status": "OK", "points": 40},
        {"season": 2026, "event_id": "2026-5625", "race_key": "2026-5625", "date": pd.Timestamp("2026-09-13"),
         "athlete_id": 101, "driver": "Kyle Larson", "position": 2, "team": "Hendrick Motorsports", "status": "OK", "points": 34},
        {"season": 2026, "event_id": "2026-5625", "race_key": "2026-5625", "date": pd.Timestamp("2026-09-13"),
         "athlete_id": 303, "driver": "Ryan Blaney", "position": 5, "team": "Team Penske", "status": "OK", "points": 18},
    ])

    model = NascarCupRace()
    ev = model.events(df, {}, seasons=[2026])[0]
    rng = __import__("numpy").random.default_rng(42)
    sim = model.price(df, ev, model.Settings.from_dict({"sims": 100, "noise": 0.5, "recent_races": 2, "history_races": 0,
                                                     "team_bias": 0.2, "recency_decay": 1.5, "seed": 42}), rng)
    assert sim is not None
    assert set(sim.entrants) == {101, 202, 303}
    assert sim.rank.shape == (100, 3)


def test_nascar_model_prices_by_athlete_id_across_roster_changes():
    from racinglines.models.nascar_model import NascarCupRace

    data = pd.DataFrame([
        {"season": 2024, "event_id": "2024-r1", "race_key": "2024-r1", "date": pd.Timestamp("2024-04-01"),
         "athlete_id": 101, "driver": "A. Driver", "position": 1, "team": "Alpha", "status": "OK", "points": 25},
        {"season": 2024, "event_id": "2024-r1", "race_key": "2024-r1", "date": pd.Timestamp("2024-04-01"),
         "athlete_id": 202, "driver": "A. Driver", "position": 2, "team": "Bravo", "status": "OK", "points": 18},
        {"season": 2025, "event_id": "2025-r1", "race_key": "2025-r1", "date": pd.Timestamp("2025-04-01"),
         "athlete_id": 101, "driver": "A. Driver", "position": 2, "team": "Alpha", "status": "OK", "points": 18},
        {"season": 2025, "event_id": "2025-r1", "race_key": "2025-r1", "date": pd.Timestamp("2025-04-01"),
         "athlete_id": 303, "driver": "B. Newcomer", "position": 4, "team": "Charlie", "status": "OK", "points": 12},
    ])

    model = NascarCupRace()
    ev = model.events(data, {}, seasons=[2025])[0]
    rng = __import__("numpy").random.default_rng(7)
    sim = model.price(data, ev, model.Settings.from_dict({"sims": 100, "noise": 0.1, "recent_races": 1,
                                                        "history_races": 0, "team_bias": 0.1,
                                                        "recency_decay": 1.0, "seed": 7}), rng)
    assert sim is not None
    assert set(sim.entrants) == {101, 202}
    assert all(isinstance(a, int) for a in sim.entrants)


def test_nascar_results_deduplicate_duplicate_athlete_rows_per_event():
    from racinglines.core import walk_forward as WF
    from racinglines.models.nascar_model import NascarCupRace

    data = pd.DataFrame([
        {"season": 2026, "event_id": "2026-r1", "race_key": "2026-r1", "date": pd.Timestamp("2026-04-01"),
         "athlete_id": 101, "driver": "A. Driver", "position": 1, "team": "Alpha", "status": "OK", "points": 40},
        {"season": 2026, "event_id": "2026-r1", "race_key": "2026-r1", "date": pd.Timestamp("2026-04-01"),
         "athlete_id": 101, "driver": "A. Driver", "position": 1, "team": "Alpha", "status": "OK", "points": 40},
        {"season": 2026, "event_id": "2026-r1", "race_key": "2026-r1", "date": pd.Timestamp("2026-04-01"),
         "athlete_id": 202, "driver": "B. Driver", "position": 2, "team": "Bravo", "status": "OK", "points": 32},
        {"season": 2026, "event_id": "2026-r1", "race_key": "2026-r1", "date": pd.Timestamp("2026-04-01"),
         "athlete_id": 303, "driver": "C. Driver", "position": 3, "team": "Charlie", "status": "OK", "points": 28},
    ])

    model = NascarCupRace()
    ev = model.events(data, {}, seasons=[2026])[0]
    res = model.results(data, ev)
    assert res["athlete_id"].is_unique
    out = WF.run(model, data, model.Settings.from_dict({"sims": 200, "noise": 0.5, "recent_races": 2,
                                                      "history_races": 0, "team_bias": 0.2,
                                                      "recency_decay": 1.5, "seed": 7}),
                 seasons=[2026], kinds=["race_win"])
    cal = out["calibration"].query("kind == 'race_win'")
    assert cal["season"].isin(["all", 2026]).all()
    assert cal.shape[0] == 2


def test_nascar_model_runs_through_the_backtest_engine():
    from racinglines.models import race_model as RM
    from racinglines.core import walk_forward as WF

    model = RM.get("nascar")
    data = _nascar_data()
    settings = model.Settings.from_dict({"sims": 200, "shrink": 2.0, "noise": 0.75, "seed": 7})

    out = WF.run(model, data, settings, seasons=[2025, 2026], kinds=["race_win", "race_podium", "race_h2h"])

    assert set(out["events"]["season"]) == {2025, 2026}
    assert len(out["events"]) >= 2
    assert out["calibration"].query("season == 'all' and kind == 'race_win'")["n"].iloc[0] > 0


def test_nascar_challenger_runs_and_tracks_recent_form():
    from racinglines.models import race_model as RM
    from racinglines.models.nascar_model import NascarCupRaceChallenger
    from racinglines.core import walk_forward as WF

    data = _nascar_data()
    baseline = RM.get("nascar")
    challenger = NascarCupRaceChallenger()

    base_settings = baseline.Settings.from_dict({"sims": 200, "shrink": 2.0, "noise": 0.75, "seed": 7})
    chal_settings = challenger.Settings.from_dict({"sims": 200, "recent_races": 4, "team_bias": 0.5,
                                                "noise": 0.75, "seed": 7})

    base_out = WF.run(baseline, data, base_settings, seasons=[2025, 2026], kinds=["race_win"])
    chal_out = WF.run(challenger, data, chal_settings, seasons=[2025, 2026], kinds=["race_win"])

    base_win = base_out["calibration"].query("season == 'all' and kind == 'race_win'").iloc[0]
    chal_win = chal_out["calibration"].query("season == 'all' and kind == 'race_win'").iloc[0]

    assert int(chal_out["events"].shape[0]) >= 2
    assert chal_win["n"] > 0
    assert chal_win["logloss"] <= 0.25
    assert chal_out["rows"].query("kind == 'race_win'").shape[0] > 0


def test_nascar_search_grid_ranks_candidates_by_logloss():
    from racinglines.models.nascar_model import NascarCupRaceChallenger

    data = _nascar_data()
    candidates = [
        {"sims": 200, "recent_races": 2, "history_races": 4, "recency_decay": 1.5, "team_bias": 0.2, "noise": 0.75, "seed": 7},
        {"sims": 200, "recent_races": 4, "history_races": 12, "recency_decay": 2.5, "team_bias": 0.5, "noise": 1.0, "seed": 8},
    ]

    rows = NascarCupRaceChallenger().search_grid(data, seasons=[2025, 2026], settings_list=candidates, kinds=["race_win", "race_podium"])

    assert len(rows) == 2
    assert {"score", "race_win", "race_podium"}.issubset(rows.columns)
    assert rows["score"].notna().all()


# --- fetch ------------------------------------------------------------------------

class Server:
    """cf.nascar.com stand-in: the given paths answer 200, everything else 403 with an S3 AccessDenied body."""

    def __init__(self, served, status=None):
        self.served, self.status, self.asked = served, status or {}, []

    def __call__(self, request):
        path = request.url.path.lstrip("/")
        self.asked.append(path)
        if path in self.status:
            return httpx.Response(self.status[path])
        if path in self.served:
            return httpx.Response(200, content=self.served[path])
        return httpx.Response(403, content=b"<Error><Code>AccessDenied</Code></Error>")

    def client(self):
        return httpx.Client(base_url=F.BASE, transport=httpx.MockTransport(self))


def race_list(*races):
    return json.dumps([dict(race_id=i, race_date=d + "T15:00:00", race_type_id=1) for i, d in races]).encode()


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "OUT", tmp_path)
    monkeypatch.setitem(http.HOST_INTERVAL, "cf.nascar.com", 0)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    monkeypatch.setattr(http, "_next_ok", {})
    return tmp_path


def darlington_bytes(name):
    return (MKT / f"nascar_{name}.json").read_bytes()


@pytest.mark.quick
def test_fetch_stores_feeds_as_served_and_skips_future_races(raw):
    srv = Server({
        "cacher/2026/1/race_list_basic.json": race_list((5624, "2026-09-06"), (5628, "2026-09-27"), (9999, "2026-10-04")),
        "cacher/2026/1/points-feed.json": darlington_bytes("points_feed_2026"),
        "cacher/2026/1/5624/weekend-feed.json": darlington_bytes("weekend_feed_2026_5624"),
        "cacher/2026/1/5624/lap-times.json": darlington_bytes("lap_times_2026_5624"),
        "cacher/live/series_1/5624/live-pit-data.json": darlington_bytes("pit_data_2026_5624"),
        "loopstats/prod/2026/1/5624.json": darlington_bytes("loopstats_2026_5624"),
        "cacher/2026/1/5624/lap-notes.json": darlington_bytes("lap_notes_2026_5624"),
    })
    with srv.client() as c:
        counts = F.fetch([2026], c=c, today=TODAY, echo=lambda *_: None)
    assert counts["errors"] == 0 and counts["fetched"] == 2 + 5
    assert (raw / "2026/1/5624/weekend-feed.json").read_bytes() == darlington_bytes("weekend_feed_2026_5624")
    assert (raw / "2026/1/5624/pit-data.json").exists() and (raw / "2026/1/5624/loopstats.json").exists()
    assert not any("9999" in p for p in srv.asked)                                         # not raced yet
    # Kansas ran two days ago: its feeds may just not be published, so a 403 is not remembered
    assert srv.asked.count("cacher/2026/1/5628/lap-times.json") == 1
    assert not list((raw / "2026/1/5628").glob("*.missing"))


@pytest.mark.quick
def test_fetch_is_resumable_and_remembers_old_missing_feeds(raw):
    srv = Server({"cacher/2026/1/race_list_basic.json": race_list((5600, "2026-08-01")),
                  "cacher/2026/1/5600/weekend-feed.json": darlington_bytes("weekend_feed_2026_5624")})
    with srv.client() as c:
        first = F.fetch([2026], feeds=["race_list_basic", "weekend-feed", "lap-times"], c=c, today=TODAY, echo=lambda *_: None)
        assert (first["fetched"], first["missing"]) == (2, 1)
        assert (raw / "2026/1/5600/lap-times.missing").exists()                          # 8 weeks old: really not there
        asked = len(srv.asked)
        second = F.fetch([2026], feeds=["weekend-feed", "lap-times"], c=c, today=TODAY, echo=lambda *_: None)
        assert (second["cached"], second["skipped"], second["fetched"]) == (1, 1, 0) and len(srv.asked) == asked
        third = F.fetch([2026], feeds=["lap-times"], c=c, today=TODAY, force=True, echo=lambda *_: None)
        assert third["missing"] == 1 and len(srv.asked) == asked + 1                     # --force asks again


@pytest.mark.quick
def test_fetch_does_not_ask_for_feeds_before_they_existed(raw):
    srv = Server({"cacher/2016/1/race_list_basic.json": race_list((100, "2016-06-01"))})
    with srv.client() as c:
        F.fetch([2014, 2016], c=c, today=TODAY, echo=lambda *_: None)
    assert srv.asked == ["cacher/2016/1/race_list_basic.json", "cacher/2016/1/points-feed.json"]   # weekend feeds start 2017


@pytest.mark.quick
def test_dry_run_asks_for_nothing_and_counts_the_requests(raw):
    (raw / "2026/1").mkdir(parents=True)
    (raw / "2026/1/race_list_basic.json").write_bytes(race_list((5600, "2026-08-01"), (5601, "2026-08-08")))
    srv = Server({})
    with srv.client() as c:
        counts = F.fetch([2026], c=c, today=TODAY, dry_run=True, echo=lambda *_: None)
    assert srv.asked == [] and counts["planned"] == 2 + 2 * 5                              # 2 season feeds + 5 per race


@pytest.mark.quick
def test_a_null_body_is_a_missing_feed_and_a_server_error_is_counted_not_stored(raw):
    srv = Server({"cacher/2026/1/race_list_basic.json": race_list((5600, "2026-08-01")),
                  "loopstats/prod/2026/1/5600.json": b"null"}, status={"cacher/2026/1/5600/weekend-feed.json": 500})
    with srv.client() as c:
        counts = F.fetch([2026], feeds=["race_list_basic", "weekend-feed", "loopstats"], c=c, today=TODAY, echo=lambda *_: None)
    assert counts["errors"] == 1 and counts["missing"] == 1
    assert not (raw / "2026/1/5600/loopstats.json").exists() and not (raw / "2026/1/5600/weekend-feed.json").exists()


@pytest.mark.quick
def test_cli_dry_run(raw, capsys):
    from racinglines import cli
    assert cli.main(["nascar", "fetch", "--years", "2014", "--dry-run"]) == 0
    assert "Would ask for" in capsys.readouterr().out


# --- ingest into a database ---------------------------------------------------------

def stage(raw):
    """The probe fixtures laid out as fetch.py stores them."""
    def put(rel, name):
        dest = raw / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(MKT / f"nascar_{name}.json", dest)
    put("2026/1/race_list_basic.json", "race_list_2026")
    for rid, feed in ((5624, "weekend_feed_2026_5624"), (5596, "weekend_feed_2026_5596"), (5626, "weekend_feed_2026_5626")):
        put(f"2026/1/{rid}/weekend-feed.json", feed)
    put("2026/1/5624/lap-times.json", "lap_times_2026_5624")
    put("2026/1/5624/lap-notes.json", "lap_notes_2026_5624")
    put("2026/1/5624/pit-data.json", "pit_data_2026_5624")
    put("2026/1/5624/loopstats.json", "loopstats_2026_5624")
    put("2017/1/4599/weekend-feed.json", "weekend_feed_2017_4599")


@pytest.fixture
def db(test_engine, raw):
    from sqlalchemy import delete, select
    from sqlalchemy.orm import sessionmaker
    from racinglines.db import models as m
    stage(raw)
    S = sessionmaker(test_engine)

    def clean():
        with S() as s:
            s.execute(delete(m.Event).where(m.Event.source == I.SOURCE))
            s.execute(delete(m.SourceFile).where(m.SourceFile.parser == I.PARSER))
            ids = s.scalars(select(m.AthleteIdentifier.athlete_id).where(m.AthleteIdentifier.scheme == I.SCHEME)).all()
            s.execute(delete(m.AthleteIdentifier).where(m.AthleteIdentifier.scheme == I.SCHEME))
            s.execute(delete(m.Athlete).where(m.Athlete.id.in_(ids)))
            s.commit()
    clean()
    yield S
    clean()


def counts(s):
    from sqlalchemy import func, select
    from racinglines.db import models as m
    return {t.__tablename__: s.scalar(select(func.count()).select_from(t))
            for t in (m.Event, m.Race, m.Round, m.Result, m.Lap, m.AthleteIdentifier)} | {
        "nascar_athletes": s.scalar(select(func.count()).select_from(m.AthleteIdentifier).where(m.AthleteIdentifier.scheme == I.SCHEME))}


def test_ingest_writes_events_rounds_results_and_laps(db):
    from sqlalchemy import select
    from racinglines.db import models as m
    with db() as s:
        assert I.ingest(s, [2026, 2017], today=TODAY, echo=lambda *_: None) == {"scheduled": 6, "ingested": 4}
        ev = {e.source_key: e for e in s.scalars(select(m.Event).where(m.Event.source == I.SOURCE))}
        assert {k for k, e in ev.items() if e.status == "completed"} == {"2026-5624", "2026-5596", "2026-5626", "2017-4599"}
        assert {k for k, e in ev.items() if e.status == "scheduled"} == {f"2026-{i}" for i in (5630, 5629, 5633, 5631, 5632, 5601)}
        dar = ev["2026-5624"]
        assert (dar.name, str(dar.start_date), dar.series_round, dar.status, dar.venue.slug) == \
            ("Cook Out Southern 500", "2026-09-06", 27, "completed", "darlington-raceway")
        assert dar.season.year == 2026
        comp = s.get(m.Competition, dar.season.competition_id)
        assert comp.code == "nascar_cup"

        def kinds(key):
            race = s.scalars(select(m.Race).where(m.Race.event_id == ev[key].id)).one()
            return [r.kind for r in sorted(race.rounds, key=lambda r: r.ordinal)], race
        assert kinds("2026-5624")[0] == ["race"]                                            # rained out: no qualifying round
        assert kinds("2026-5596")[0] == ["fp1", "fp2", "fp3", "qual", "race"]
        assert kinds("2017-4599")[0] == ["fp1", "fp2", "fp3", "qual", "race"]
        race_dar = kinds("2026-5624")[1]
        assert race_dar.format["qualifying_ran"] is False and race_dar.format["cautions"] == 6

        rnd = s.scalars(select(m.Round).where(m.Round.race_id == race_dar.id)).one()
        assert (rnd.extra["laps_complete"], rnd.extra["laps_max"], rnd.extra["laps_missing"]) == (False, 355, 18)
        bell = s.scalars(select(m.Result).join(m.AthleteIdentifier, m.AthleteIdentifier.athlete_id == m.Result.athlete_id).where(
            m.Result.round_id == rnd.id, m.AthleteIdentifier.scheme == "nascar", m.AthleteIdentifier.value == "4153")).one()
        assert (bell.position, bell.status, bell.bib, bell.time_ms) == (1, "OK", "20", 14_585_000)
        laps = s.scalars(select(m.Lap).where(m.Lap.result_id == bell.id).order_by(m.Lap.lap)).all()
        assert len(laps) == 349 and (laps[0].lap, laps[0].lap_time_ms, laps[0].position, laps[0].track_status) == (1, 32224, 12, "1")
        assert 330 not in {x.lap for x in laps}

        daytona = s.scalars(select(m.Round).join(m.Race).where(m.Race.event_id == ev["2026-5596"].id, m.Round.kind == "race")).one()
        dns = s.scalars(select(m.Result).where(m.Result.round_id == daytona.id, m.Result.status == "DNS")).all()
        assert len(dns) == 4 and all(r.position is None for r in dns)
        assert s.scalars(select(m.Athlete).join(m.AthleteIdentifier).where(
            m.AthleteIdentifier.scheme == "nascar", m.AthleteIdentifier.value == "4153")).one().display_name == "Christopher Bell"


def test_reingest_is_a_no_op_and_force_rebuilds_without_duplicating(db):
    with db() as s:
        I.ingest(s, [2026], today=TODAY, echo=lambda *_: None)
        before = counts(s)
        assert I.ingest(s, [2026], today=TODAY, echo=lambda *_: None) == {"unchanged": 3}
        assert counts(s) == before
        assert I.ingest(s, [2026], force=True, today=TODAY, echo=lambda *_: None) == {"scheduled": 6, "ingested": 3}
        assert counts(s) == before                                                          # rounds replaced, athletes reused
        assert before["nascar_athletes"] > 12 and before["laps"] == 4 * 349


def test_changed_file_rebuilds_and_no_laps_skips_the_lap_table(db, raw):
    with db() as s:
        assert I.ingest(s, [2026], laps=False, today=TODAY, echo=lambda *_: None) == {"scheduled": 6, "ingested": 3}
        assert counts(s)["laps"] == 0
        assert I.ingest(s, [2026], laps=True, today=TODAY, echo=lambda *_: None) == {"ingested": 1, "unchanged": 2}   # only the race with laps changes
        assert counts(s)["laps"] == 4 * 349
        p = raw / "2026/1/5626/weekend-feed.json"
        feed = json.loads(p.read_text())
        feed["weekend_race"][0]["results"][0]["points_earned"] = 99
        p.write_text(json.dumps(feed))
        assert I.ingest(s, [2026], today=TODAY, echo=lambda *_: None) == {"ingested": 1, "unchanged": 2}


def test_a_series_without_a_competition_is_refused(db):
    with db() as s, pytest.raises(ValueError, match="no competition yet"):
        I.ingest(s, [2026], series=2)


def test_races_still_to_run_are_filed_as_scheduled_and_become_completed_when_run(db, raw):
    from sqlalchemy import select
    from racinglines.db import models as m
    with db() as s:
        I.ingest(s, [2026], today=TODAY, echo=lambda *_: None)
        sched = {e.name: e for e in s.scalars(select(m.Event).where(m.Event.source == I.SOURCE, m.Event.status == "scheduled"))}
        assert sorted(e.series_round for e in sched.values()) == [31, 32, 33, 34, 35, 36]
        finale = sched["NASCAR Championship Race"]
        assert (str(finale.start_date), finale.series_round, finale.venue.slug) == ("2026-11-08", 36, "homestead-miami-speedway")
        race = s.scalars(select(m.Race).where(m.Race.event_id == finale.id)).one()
        assert race.format["scheduled_laps"] == 267 and race.rounds == [] and "actual_laps" not in race.format
        assert I.ingest(s, [2026], today=TODAY, echo=lambda *_: None) == {"unchanged": 3}          # nothing new to file
        # a later day: the Las Vegas race (Oct 4) has passed, so it is no longer filed as scheduled
        I.ingest(s, [2026], today=date(2026, 10, 5), echo=lambda *_: None)
        assert len(s.scalars(select(m.Event).where(m.Event.source == I.SOURCE, m.Event.status == "scheduled")).all()) == 6
        # the weekend feed of a race that was scheduled completes the same event, not a second one
        lv = s.scalars(select(m.Event).where(m.Event.source_key == "2026-5630")).one()
        assert lv.status == "scheduled"
        wf = json.loads((MKT / "nascar_weekend_feed_2026_5624.json").read_text())
        wf["weekend_race"][0]["race_id"] = 5630
        (raw / "2026/1/5630").mkdir()
        (raw / "2026/1/5630/weekend-feed.json").write_text(json.dumps(wf))
        I.ingest(s, [2026], today=date(2026, 10, 5), echo=lambda *_: None)
        s.refresh(lv)
        assert lv.status == "completed" and len(s.scalars(select(m.Event).where(m.Event.source_key == "2026-5630")).all()) == 1


# --- identity ---------------------------------------------------------------------------

@pytest.mark.quick
def test_names_are_normalized_across_accents_punctuation_and_suffixes():
    assert ID.norm("A.J. Allmendinger") == ID.norm("AJ Allmendinger") == "aj allmendinger"
    assert ID.norm("Daniel Suárez") == "daniel suarez"
    assert ID.strip_suffix(ID.norm("Ricky Stenhouse Jr.")) == "ricky stenhouse"
    assert ID.first_last("john hunter nemechek") == "john nemechek" and ID.first_last("ty gibbs") == "ty gibbs"


def add_driver(s, name, driver_id, race_event_key="2026-5624"):
    """A driver with a race result in one ingested race (so the resolver's pool has them)."""
    from sqlalchemy import select
    from racinglines.db import models as m
    a = m.Athlete(display_name=name)
    s.add(a)
    s.flush()
    s.add(m.AthleteIdentifier(scheme="nascar", value=str(driver_id), athlete_id=a.id))
    rnd = s.scalars(select(m.Round).join(m.Race).join(m.Event).where(m.Event.source_key == race_event_key, m.Round.kind == "race")).one()
    s.add(m.Result(round_id=rnd.id, athlete_id=a.id, position=None, status="DNS"))
    s.flush()
    return a.id


def athlete_of(s, driver_id):
    from sqlalchemy import select
    from racinglines.db import models as m
    return s.scalars(select(m.AthleteIdentifier.athlete_id).where(
        m.AthleteIdentifier.scheme == "nascar", m.AthleteIdentifier.value == str(driver_id))).one()


def test_resolver_finds_a_driver_under_the_spellings_venues_use(db):
    with db() as s:
        I.ingest(s, [2026, 2017], today=TODAY, echo=lambda *_: None)
        R = ID.Resolver(s.connection(), 2026)
        want = lambda did: athlete_of(s, did)                                   # noqa: E731
        assert R.driver("Kyle Larson") == R.driver("kyle larson") == R.driver("LARSON") == want(4030)
        assert R.driver("Ricky Stenhouse Jr.") == R.driver("Ricky Stenhouse") == want(3888)     # the feed says "Jr" with no dot
        old = ID.Resolver(s.connection(), 2017)                                                   # Allmendinger: in the 2017 fixture only
        assert old.driver("A.J. Allmendinger") == old.driver("AJ Allmendinger") == want(3774)
        assert R.driver("Chris Bell") == R.driver("Christopher Bell") == want(4153)              # a short first name
        assert R.driver("Alexander Bowman") == want(4045) and R.driver("Chris Buescher") == want(3989)
        assert R.driver("Darrell Wallace Jr.") == R.driver("Bubba Wallace") == want(4025)        # a nickname the feed has used both ways
        assert R.driver_id(want(4030)) == 4030
        assert R.driver("Daniel Suarez") is None and R.unresolved["Daniel Suarez"] == "unknown"
        assert R.driver("") is None and R.driver(None) is None


def test_the_pool_is_the_market_season_and_the_one_before(db):
    with db() as s:
        I.ingest(s, [2026, 2017], today=TODAY, echo=lambda *_: None)
        kenseth = athlete_of(s, 1810)                                               # raced in the 2017 fixture only
        assert ID.Resolver(s.connection(), 2017).driver("Matt Kenseth") == kenseth
        assert ID.Resolver(s.connection(), 2018).driver("Matt Kenseth") == kenseth   # the season before still counts
        r = ID.Resolver(s.connection(), 2026)
        assert r.driver("Matt Kenseth") is None and r.unresolved["Matt Kenseth"] == "unknown"      # not in 2025 or 2026
        assert ID.Resolver(s.connection(), None).driver("Matt Kenseth") == kenseth  # no season given: everyone


def test_a_name_that_fits_two_drivers_is_never_guessed(db):
    with db() as s:
        I.ingest(s, [2026], today=TODAY, echo=lambda *_: None)
        kyle, kurt = add_driver(s, "Kyle Busch", 1234), add_driver(s, "Kurt Busch", 1235)
        R = ID.Resolver(s.connection(), 2026)
        assert (R.driver("Kyle Busch"), R.driver("Kurt Busch")) == (kyle, kurt)
        assert R.driver("Busch") is None and R.unresolved["Busch"] == "ambiguous: Kurt Busch, Kyle Busch"
        assert R.driver("K. Busch") is None                                          # an initial is not a first name


def test_race_is_looked_up_by_date_and_name(db):
    from sqlalchemy import select
    from racinglines.db import models as m
    with db() as s:
        I.ingest(s, [2026], today=TODAY, echo=lambda *_: None)
        R = ID.Resolver(s.connection(), 2026)
        dar = s.scalars(select(m.Race).join(m.Event).where(m.Event.source_key == "2026-5624")).one().id
        fin = s.scalars(select(m.Race).join(m.Event).where(m.Event.source_key == "2026-5601")).one().id
        assert R.race(date(2026, 9, 6))[0] == dar and R.race(date(2026, 9, 7))[0] == dar and R.race(date(2026, 9, 5))[0] == dar
        assert R.race(date(2026, 9, 8)) == (None, None) and R.race(None) == (None, None)
        assert R.race(date(2026, 11, 8), "Homestead")[0] == fin                      # an upcoming race resolves too
        assert [rid for rid, *_ in R.race_window(date(2026, 11, 1), date(2026, 11, 30))] == [
            s.scalars(select(m.Race).join(m.Event).where(m.Event.source_key == "2026-5632")).one().id, fin]
        # two events inside the window: the name decides, and without a usable name it is ambiguous, not a guess
        R.events = [(1, "Cook Out Clash", date(2026, 2, 4), "c"), (2, "DAYTONA 500", date(2026, 2, 5), "c")]
        assert R.race(date(2026, 2, 4), "Daytona 500 winner") == (2, "DAYTONA 500")
        assert R.race(date(2026, 2, 4), "Winner") == (None, None) and R.race(date(2026, 2, 4)) == (None, None)


# --- the season state for the season forecast (models/nascar_season.load_state) -------------------------------------

def test_season_state_reads_points_races_chase_flags_and_the_races_left(db):
    from racinglines.models import nascar_season as NS
    with db() as s:
        I.ingest(s, [2026], today=TODAY, echo=lambda *_: None)
        s.commit()
        results, schedule = NS.load_state(s.connection(), 2026)
    by = schedule.set_index("name")
    assert not by.loc["DAYTONA 500", "chase"] and by.loc["DAYTONA 500", "done"]
    assert by.loc["Cook Out Southern 500", "chase"] and by.loc["Cook Out Southern 500", "done"]
    left = schedule[~schedule["done"]]
    assert len(left) == 6 and left["chase"].all() and left["name"].iloc[-1] == "NASCAR Championship Race"
    assert (schedule["stages"].dropna() >= 1).all()
    assert set(results["event_id"]) == set(schedule.loc[schedule["done"], "event_id"])
    darl = results[results["event_id"] == by.loc["Cook Out Southern 500", "event_id"]]
    assert darl.loc[darl["position"] == 1, "points"].iloc[0] == 73          # the feed's points, stage and bonus included
