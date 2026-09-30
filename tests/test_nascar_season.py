"""NASCAR Cup season simulation (racinglines/models/nascar_season.py) and the season payoffs in markets/kinds.py."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from racinglines.markets import kinds as K
from racinglines.models import nascar_season as NS
from racinglines.models import outcomes as O

FIX = Path(__file__).parent / "fixtures" / "market"
F26 = NS.FORMATS[2026]


def test_2026_chase_seeds():
    assert F26.chase_size == 16 and len(F26.seeds) == 16
    assert F26.seeds[:6] == (2100, 2075, 2065, 2060, 2055, 2050) and F26.seeds[-1] == 2000
    assert F26.rounds == () and not F26.final_by_finish


@pytest.mark.parametrize("race", [5596, 5624, 5626])
def test_finish_points_match_the_2026_feeds(race):
    """points_earned = finishing points + stage points (+ one bonus point for one driver a race)."""
    wr = json.loads((FIX / f"nascar_weekend_feed_2026_{race}.json").read_text())["weekend_race"][0]
    stage = {}
    for st in wr["stage_results"]:
        for r in st["results"]:
            stage[r["driver_id"]] = stage.get(r["driver_id"], 0) + r["stage_points"]
    rows = [r for r in wr["results"] if r["finishing_position"]]
    extra = [r["points_earned"] - stage.get(r["driver_id"], 0) - NS.finish_points(F26, r["finishing_position"])
             for r in rows]
    assert set(extra) <= {0, 1} and sum(extra) <= F26.bonus_points
    assert len(wr["stage_results"]) == F26.paid_stages


def _sims(order, n_sims=200):
    """An OutcomeSims where every simulation finishes in `order` (athlete ids, winner first)."""
    rank = np.tile(np.arange(1, len(order) + 1), (n_sims, 1))
    return O.OutcomeSims(entrants=list(order), rank=rank, finished=np.ones_like(rank, bool))


TOY = NS.ChaseFormat(season=0, chase_size=2, seeds=(2100, 2075), bonus_points=0)


def _season(done_regular=2, done_chase=0):
    sched = pd.DataFrame(dict(event_id=[1, 2, 3, 4, 5], date=pd.date_range("2026-01-01", periods=5),
                              chase=[False, False, False, True, True]))
    sched["done"] = sched["event_id"].isin([1, 2, 3][:done_regular] + [4, 5][:done_chase])
    res = []
    for e in sched.loc[sched["done"], "event_id"]:
        for pos, a in enumerate([10, 20, 30], 1):
            res.append(dict(event_id=e, athlete_id=a, position=pos, points=float(NS.finish_points(TOY, pos))))
    return sched, pd.DataFrame(res)


def test_standings_now_before_and_after_the_reset():
    sched, res = _season(done_regular=2)
    st = NS.standings_now(TOY, res, sched).set_index("athlete_id")
    assert not st["chase_set"].any() and (st["seed"] == 0).all()
    assert st.loc[10, "points"] == 110 and st.loc[10, "wins"] == 2
    sched, res = _season(done_regular=3, done_chase=1)
    st = NS.standings_now(TOY, res, sched).set_index("athlete_id")
    assert st.loc[10, "seed"] == 1 and st.loc[20, "seed"] == 2 and st.loc[30, "seed"] == 0
    assert st.loc[10, "points"] == 2100 + 55 and st.loc[20, "points"] == 2075 + 35
    assert st.loc[30, "points"] == 4 * 34         # not in the Chase: the season total, no reset


def test_simulate_season_the_reset_decides_who_can_win():
    """A driver who wins every remaining race but misses the Chase cannot be champion."""
    state = pd.DataFrame(dict(athlete_id=[10, 20, 30], regular=[200.0, 150.0, 60.0], points=[200.0, 150.0, 60.0],
                              wins=[2, 1, 0], seed=0, chase_set=False))
    remaining = [dict(chase=False), dict(chase=True), dict(chase=True)]
    rng = np.random.default_rng(0)
    # 30 wins the last regular race (still third on points: 60 + 75 < 150 + 34), then wins both Chase races
    ss = NS.simulate_season(TOY, state, remaining, [_sims([30, 10, 20]), _sims([30, 20, 10]), _sims([30, 20, 10])], rng,
                            stage_noise=0.01)
    champ = K.season_fair("champion", ss)
    assert ss.qualified[:, ss.index(30)].sum() == 0
    assert champ[ss.index(30)] == 0
    assert champ.sum() == pytest.approx(1.0)
    assert K.season_fair("champion", ss, a=10) == 1.0     # 2100 + more Chase points than 20 can close
    assert (ss.rank[:, ss.index(30)] == 3).all()           # behind both Chase drivers whatever his points


def test_simulate_season_from_the_chase_and_season_payoffs():
    sched, res = _season(done_regular=3, done_chase=1)
    state = NS.standings_now(TOY, res, sched)
    rng = np.random.default_rng(1)
    n = 500
    # the last Chase race is a coin flip between 10 and 20; 10 leads by 45 so 20 needs a 55 + big stage haul: never
    coin = rng.random(n) < 0.5
    rank = np.where(coin[:, None], [1, 2, 3], [2, 1, 3])
    last = O.OutcomeSims(entrants=[10, 20, 30], rank=rank, finished=np.ones_like(rank, bool))
    ss = NS.simulate_season(TOY, state, [dict(chase=True)], [last], rng, stage_noise=0.01)
    assert K.season_fair("champion", ss, a=10) == 1.0
    assert K.season_fair("season_wins_ge", ss, a=20, n=1) == pytest.approx((~coin).mean())
    h = K.season_fair("standings_h2h", ss)
    assert np.allclose(h + h.T, 1 - np.eye(3))
    assert K.standings_position(ss, 2)[ss.index(30)] == 0
    with pytest.raises(ValueError):
        K.season_fair("race_win", ss)


def test_close_chase_is_uncertain():
    """Two Chase drivers five points apart with races to go: both have a real chance."""
    state = pd.DataFrame(dict(athlete_id=[1, 2, 3], regular=[800.0, 790.0, 500.0], points=[2105.0, 2100.0, 600.0],
                              wins=[1, 1, 0], seed=[1, 2, 0], chase_set=True))
    rng = np.random.default_rng(2)
    n = 2000
    races = []
    for _ in range(3):
        rank = np.where((rng.random(n) < 0.5)[:, None], [1, 2, 3], [2, 1, 3])
        races.append(O.OutcomeSims(entrants=[1, 2, 3], rank=rank, finished=np.ones_like(rank, bool)))
    ss = NS.simulate_season(TOY, state, [dict(chase=True)] * 3, races, rng)
    p = K.season_fair("champion", ss)
    assert 0.3 < p[0] < 0.8 and 0.2 < p[1] < 0.7 and p[2] == 0
    frame = NS.standings_frame(ss, state, names={1: "A", 2: "B", 3: "C"})
    assert list(frame.columns[:3]) == ["athlete_id", "driver", "current_points"]
    assert frame["champion_prob"].sum() == pytest.approx(1.0)
    assert frame.loc[frame["athlete_id"] == 1, "extra"].iloc[0]["ahead_of"]["2"] == pytest.approx(p[0], abs=0.01)


def test_elimination_format_and_final_race():
    """An elimination format (2014-2025 style, without playoff points): 3 in, 2 after one race, the last race's
    best finisher among them wins."""
    fmt = NS.ChaseFormat(season=0, chase_size=3, seeds=(2000, 2000, 2000), bonus_points=0, rounds=((1, 2),),
                         final_by_finish=True)
    state = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4], regular=[500.0, 400, 300, 200], points=[2000.0, 2000, 2000, 200],
                              wins=0, seed=[1, 2, 3, 0], chase_set=True))
    rng = np.random.default_rng(3)
    ss = NS.simulate_season(fmt, state, [dict(chase=True), dict(chase=True)],
                            [_sims([3, 2, 4, 1]), _sims([4, 1, 2, 3])], rng, stage_noise=0.01)
    # after race 1, 3 and 2 lead: 1 is out; in the final 2 finishes ahead of 3, so 2 is champion though 1 was 2nd
    assert K.season_fair("champion", ss, a=2) == 1.0
    assert (ss.rank[:, ss.index(3)] == 2).all()


def test_race_sims_count_must_match():
    sched, res = _season(done_regular=2)
    state = NS.standings_now(TOY, res, sched)
    with pytest.raises(ValueError):
        NS.simulate_season(TOY, state, [dict(chase=False)], [], np.random.default_rng(0))


# --- the read-only command's pipeline (racinglines/pipelines/nascar_season.py) ------------------------------------------

def _fake_season(n_drivers=20):
    """A 2026-like season: 4 regular races and 1 Chase race run, 2 Chase races to go, driver 1 the fastest."""
    from datetime import date, timedelta
    rng = np.random.default_rng(5)
    days = [date(2026, 8, 1) + timedelta(days=7 * i) for i in range(7)]
    sched = pd.DataFrame(dict(event_id=range(101, 108), name=[f"Race {i}" for i in range(7)], date=days,
                              chase=[False] * 4 + [True] * 3, stages=[2.0] * 7, done=[True] * 5 + [False] * 2))
    rows = []
    for e, d in zip(sched["event_id"][:5], days[:5]):
        order = np.argsort(np.arange(n_drivers) + rng.normal(0, 3, n_drivers)) + 1
        for pos, a in enumerate(order, 1):
            rows.append(dict(season=2026, event_id=e, event_name=f"Race {e}", race_key=str(e), date=d, athlete_id=int(a),
                             driver=f"Driver {a}", position=pos, team=f"T{a % 5}", status="OK",
                             points=float(NS.finish_points(F26, pos)), race=f"2026::{e}"))
    return sched, pd.DataFrame(rows)


def test_forecast_and_quotes(monkeypatch):
    from racinglines.models.nascar_model import NascarCupRace
    from racinglines.pipelines import nascar_season as NSP
    from racinglines.pipelines import position_replay as PR

    sched, data = _fake_season()
    res = data[["event_id", "athlete_id", "position", "points"]]

    class Model(NascarCupRace):
        def load(self, engine_url=None, data=None):
            return _fake_season()[1]

    class Engine:
        class url:
            @staticmethod
            def render_as_string(hide_password=False):
                return "postgresql://unused"

        def connect(self):
            import contextlib
            return contextlib.nullcontext(None)

    monkeypatch.setattr(PR, "model_for", lambda sp: Model())
    monkeypatch.setattr(NS, "load_state", lambda conn, year, **kw: (res, sched))
    frame, state, audit = NSP.forecast(Engine(), 2026, n_sims=500, seed=1, standings="results")
    assert audit["races_left"] == 2 and audit["chase_races_left"] == 2 and audit["field"] == 20
    assert frame["champion_prob"].sum() == pytest.approx(1.0)
    assert (frame.loc[frame["seed"] == 0, "champion_prob"] == 0).all()        # 16 of 20 in the Chase
    assert (frame["seed"] > 0).sum() == 16
    assert frame.iloc[0]["seed"] > 0
    assert "champ" in NSP.text(frame, audit) and "NOT CALIBRATED" in NSP.text(frame, audit)
    assert audit["settings"]["noise"] > 2.0                                  # measured, not the model's 2.0

    top = int(frame.iloc[0]["athlete_id"])
    links = pd.DataFrame([
        dict(exchange="og", group_title="Driver X", athlete_id=top, invert=False, last_bid=0.05, last_ask=0.10, token_id="a"),
        dict(exchange="polymarket", group_title="Driver X", athlete_id=top, invert=True, last_bid=None, last_ask=0.5, token_id="b"),
        dict(exchange="kalshi", group_title="Nobody", athlete_id=None, invert=False, last_bid=0.1, last_ask=0.2, token_id="c")])
    q = NSP.quote_rows(links, frame)
    p = float(frame.iloc[0]["champion_prob"])
    og = q.iloc[0]
    assert og["fair"] == pytest.approx(p) and og["edge_yes"] == pytest.approx(p - 0.10 - og["fee"])
    assert q.iloc[1]["fair"] == pytest.approx(1 - p) and pd.isna(q.iloc[1]["edge_no"])
    assert pd.isna(q.iloc[2]["fair"]) and q.iloc[2]["call"] == ""
    assert "driver not matched" in NSP.quotes_text(q)


def test_season_command_is_off_by_default(monkeypatch):
    from racinglines.cli import nascar
    monkeypatch.delenv("RACINGLINES_NASCAR_SEASON", raising=False)
    with pytest.raises(SystemExit) as e:
        nascar.main(["season"])
    assert "RACINGLINES_NASCAR_SEASON" in str(e.value)


def test_seeding_ties_go_to_wins_then_top5s():
    sched = pd.DataFrame(dict(event_id=[1, 2, 3], date=pd.date_range("2026-01-01", periods=3), chase=[False, False, True],
                              done=[True, True, False]))
    # 10 and 20 tie on 70 points with no wins; 20 has the top 5, so 20 is seeded first
    res = pd.DataFrame(dict(event_id=[1, 1, 1, 2, 2, 2], athlete_id=[30, 20, 10, 30, 10, 20], position=[1, 4, 6, 1, 6, 7],
                            points=[100.0, 35, 35, 100, 35, 35]))
    st = NS.standings_now(TOY, res, sched).set_index("athlete_id")
    assert st.loc[30, "seed"] == 1 and st.loc[20, "seed"] == 2 and st.loc[10, "seed"] == 0


def test_the_points_feed_replaces_points_and_seeds():
    feed = json.loads((FIX / "nascar_points_feed_2026.json").read_text())
    ids = {r["driver_id"]: r["driver_id"] for r in feed}
    # our results-summed state: the right drivers, wrong points and seeds
    state = pd.DataFrame(dict(athlete_id=list(ids)[:12] + [1, 2, 3, 4], regular=0.0, points=2000.0, wins=0,
                              seed=list(range(1, 17)), chase_set=True, source="results"))
    fmt = NS.ChaseFormat(season=2026, chase_size=16, seeds=F26.seeds)
    out, matched = NS.apply_feed(fmt, state, feed, ids)
    o = out.set_index("athlete_id")
    assert matched == 12
    larson = next(r for r in feed if r["driver_last_name"] == "Larson")
    assert o.loc[larson["driver_id"], "points"] == 2282 and o.loc[larson["driver_id"], "seed"] == 7
    assert (o.loc[[1, 2, 3, 4], "source"] == "results").all()
    with pytest.raises(ValueError):          # a feed that leaves the Chase short of 16 seeds is refused
        NS.apply_feed(fmt, state.iloc[:12], feed, ids)


def test_noise_estimate_measures_the_spread():
    rng = np.random.default_rng(4)
    rows = []
    for race in range(30):
        pos = np.argsort(np.argsort(np.arange(30) + rng.normal(0, 8, 30))) + 1
        rows += [dict(date=pd.Timestamp("2026-01-01") + pd.Timedelta(days=7 * race), athlete_id=a, position=p)
                 for a, p in enumerate(pos)]
    est = NS.estimate_noise(pd.DataFrame(rows))
    assert 5 < est < 12
    assert NS.estimate_noise(pd.DataFrame(rows[:20])) is None


def test_feed_check_lists_the_drivers_whose_results_differ():
    from racinglines.pipelines import nascar_season as NSP
    feed = json.loads((FIX / "nascar_points_feed_2026.json").read_text())[:2]
    comp = pd.DataFrame(dict(athlete_id=[1, 2], points=[float(feed[0]["points"]), float(feed[1]["points"]) - 5],
                             seed=[feed[0]["playoff_rank"], feed[1]["playoff_rank"]], chase_set=True))
    names = {1: feed[0]["driver_name"], 2: feed[1]["driver_name"]}
    out = NSP.feed_check(dict(feed=feed, computed=comp, names=names, standings="NASCAR points feed (2 drivers matched)"))
    assert "1 drivers differ" in out and feed[1]["driver_name"] in out
    assert "not on disk" in NSP.feed_check(dict(feed=None))
    assert "not used" in NSP.feed_check(dict(feed=None, standings_mode="results"))
