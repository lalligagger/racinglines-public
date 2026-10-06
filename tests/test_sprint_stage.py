"""The sprint as a stage of its own (models/position_sim/pricing.price_stages, sports/f1.toml [sessions.sim],
docs/todo.md U13): a sprint weekend prices the sprint from the Grand Prix's paces and finishing model with the
schema's points and retirement scale, the grid from Sprint Qualifying's laps, the actual result once it has run;
the Grand Prix's arrays and the caller's random stream don't move; a stage before SQ or the sprint never reads
their results (the as-of rule). Synthetic data (racinglines/testing/synthetic.py), no database."""

import numpy as np
import pandas as pd
import pytest

from racinglines.models import outcomes as O
from racinglines.models.position_sim import model as M
from racinglines.models.position_sim import pricing as run
from racinglines.testing import synthetic as SY

pytestmark = pytest.mark.quick
GP_KEYS = ("pos", "dnf", "points", "grid")


def _frames():
    res, laps, prof = SY.f1_frames()
    ev = sorted(res["event_id"].unique())
    return SY.f1_sprint(res, laps, prof, [ev[-1], ev[-3]]), ev[-1]


@pytest.fixture(scope="module")
def sprint():
    (res, laps, prof), eid = _frames()
    m = run.Measurements.from_frames(res, laps, prof)
    return m, run.history(m), eid


@pytest.fixture(scope="module")
def plain():
    m = run.Measurements.from_frames(*SY.f1_frames())
    return m, run.history(m), int(m.drivers["event_id"].max())


def _price(m, hist, cutoff, eid, seed=3, **kw):
    rng = np.random.default_rng(seed)
    summ, ex = run.price_race(m, hist, cutoff, eid, n_sims=600, rng=rng, **kw)
    return summ, ex, rng.random(4)            # where the caller's stream is afterwards


def _cutoffs(m, eid):
    s = m.sessions(eid)
    one = pd.Timedelta(minutes=1)
    return dict(pre_weekend=s["fp1"] - pd.Timedelta(hours=1), pre_sq=s["sprint_qual"] - one,
                pre_sprint=s["sprint"] - one, pre_quali=s["qual"] - one, after_quali=s["qual"] + pd.Timedelta(hours=2))


def test_schema_declares_the_race_like_sessions():
    assert M.SIM_SESSIONS["race"] == {"grid_from": "qual", "points": "race"}
    assert M.SIM_SESSIONS["sprint"] == {"grid_from": "sprint_qual", "points": "sprint", "dnf_scale": 0.5}
    assert M.points_table("sprint", 2021) == [3, 2, 1] and M.points_table("sprint", 2026) == M.SPRINT_POINTS_DEFAULT
    assert M.points_table("race", 2026) == M.RACE_POINTS


def test_a_weekend_without_a_sprint_prices_exactly_as_before(plain):
    m, hist, eid = plain
    assert run.side_stages(m, eid) == []
    q = m.sessions(eid)["qual"]
    for cutoff in (q - pd.Timedelta(minutes=1), q + pd.Timedelta(hours=2)):
        summ, ex, nxt = _price(m, hist, cutoff, eid)
        assert "stages" not in ex["sim"] and "stages" not in ex["audit"]
        assert not [c for c in summ.columns if c.startswith("sprint_")]
        b_summ, b_ex, b_nxt = _price(m, hist, cutoff, eid, stages=())       # no side stage at all
        pd.testing.assert_frame_equal(summ, b_summ)
        assert ex["constructor_top"] == b_ex["constructor_top"] and (nxt == b_nxt).all()
        sims = O.from_position_sim(ex["entrants"], ex["sim"])
        assert set(sims.stage_rank) == {"qual"} and not sims.stage_finished and not sims.stage_points


def test_the_sprint_moves_no_grand_prix_price_or_the_callers_stream(sprint):
    m, hist, eid = sprint
    assert run.side_stages(m, eid) == ["sprint"]
    for name, cutoff in _cutoffs(m, eid).items():
        summ, ex, nxt = _price(m, hist, cutoff, eid)
        b_summ, b_ex, b_nxt = _price(m, hist, cutoff, eid, stages=())
        for k in GP_KEYS:
            np.testing.assert_array_equal(ex["sim"][k], b_ex["sim"][k], err_msg=f"{name} {k}")
        pd.testing.assert_frame_equal(summ.drop(columns=["sprint_win_prob", "sprint_pole_prob"]), b_summ)
        assert ex["constructor_top"] == b_ex["constructor_top"] and (nxt == b_nxt).all(), name
        assert set(ex["sim"]["stages"]) == {"sprint"} and "stages" not in b_ex["sim"]


def test_sprint_points_retirements_and_grid_sources(sprint):
    m, hist, eid = sprint
    c = _cutoffs(m, eid)
    summ, ex, _ = _price(m, hist, c["pre_weekend"], eid)
    s = ex["sim"]["stages"]["sprint"]
    assert s["points"].max() == 8 and set(np.unique(s["points"])) <= {0, 1, 2, 3, 4, 5, 6, 7, 8}
    assert s["points"][s["dnf"]].max() == 0
    # retirements at the schema's dnf_scale of the race's rate (0.5), within Monte Carlo error
    want = ex["entrants"]["p_dnf"].to_numpy() * 0.5
    assert abs(s["dnf"].mean() - want.mean()) < 4 * np.sqrt(want.mean() / s["dnf"].size)
    assert summ["sprint_win_prob"].sum() == pytest.approx(1.0, abs=0.01)
    assert summ["sprint_pole_prob"].sum() == pytest.approx(1.0)
    assert ex["audit"]["stages"]["sprint"] == dict(grid="simulated from qualifying pace", result="simulated",
                                                   dnf_scale=0.5, points="sprint")
    # after SQ: the grid is SQ's best-lap order (its classification has no positions), the same in every simulation
    _, ex, _ = _price(m, hist, c["pre_sprint"], eid)
    s = ex["sim"]["stages"]["sprint"]
    assert ex["audit"]["stages"]["sprint"]["grid"] == "sprint_qual best laps"
    assert (s["grid"] == s["grid"][0]).all()
    laps = m.practice[(m.practice["event_id"] == eid) & (m.practice["round"] == "sprint_qual")]
    pole = laps.loc[laps["best_def"].idxmin(), "athlete_id"]
    assert s["grid"][0][ex["entrants"]["athlete_id"].tolist().index(pole)] == 1
    # after the sprint: its actual result, as the Grand Prix uses the actual qualifying order
    summ, ex, _ = _price(m, hist, c["pre_quali"], eid)
    assert ex["audit"]["stages"]["sprint"]["result"] == "actual"
    sp = m.res[(m.res["event_id"] == eid) & (m.res["round"] == "sprint")]
    winner = sp.loc[sp["position"] == 1, "athlete_id"].iloc[0]
    assert summ.set_index("athlete_id")["sprint_win_prob"].to_dict() == {a: float(a == winner) for a in summ["athlete_id"]}
    pts = ex["sim"]["stages"]["sprint"]["points"][0]
    got = dict(zip(ex["entrants"]["athlete_id"], pts))
    assert all(got[a] == p for a, p in zip(sp["athlete_id"], sp["points"].astype(float)))


def _corrupt(res, laps, eid, what):
    """The event's SQ laps or its sprint classification scrambled (what a leak would read)."""
    res, laps = res.copy(), laps.copy()
    if "sq" in what:
        q = (laps["event_id"] == eid) & (laps["round"] == "sprint_qual")
        laps.loc[q, "lap_time_ms"] = laps.loc[q, "lap_time_ms"].to_numpy()[::-1]
    if "sprint" in what:
        q = (res["event_id"] == eid) & (res["round"] == "sprint")
        res.loc[q, "position"] = res.loc[q, "position"].to_numpy()[::-1]
        res.loc[q, "status"] = "OK"
    return res, laps


def test_the_sprint_stage_never_reads_sq_or_the_sprint_before_they_have_run():
    (res, laps, prof), eid = _frames()
    clean = run.Measurements.from_frames(res, laps, prof)
    c = _cutoffs(clean, eid)
    hist = run.history(clean)

    def stage(meas, cutoff):
        _, ex, _ = _price(meas, hist, cutoff, eid)
        return ex["sim"]["stages"]["sprint"]

    def same(a, b):
        return all(np.array_equal(a[k], b[k]) for k in GP_KEYS)

    both = run.Measurements.from_frames(*_corrupt(res, laps, eid, ("sq", "sprint")), prof)
    sprint_only = run.Measurements.from_frames(*_corrupt(res, laps, eid, ("sprint",)), prof)
    for cutoff in (c["pre_weekend"], c["pre_sq"]):                          # before SQ: neither is read
        assert same(stage(clean, cutoff), stage(both, cutoff))
    assert same(stage(clean, c["pre_sprint"]), stage(sprint_only, c["pre_sprint"]))    # before the sprint
    # ... and each is read once it has run (the check above would pass vacuously otherwise)
    assert not same(stage(clean, c["pre_sprint"]), stage(both, c["pre_sprint"]))
    assert not same(stage(clean, c["pre_quali"]), stage(sprint_only, c["pre_quali"]))
    for cutoff in (c["pre_sq"], c["pre_sprint"]):
        _, ex, _ = _price(clean, hist, cutoff, eid)
        used = ex["audit"]["sessions_used"]
        assert "sprint" not in used and ("sprint_qual" in used) == (cutoff > c["pre_sq"])


def test_a_future_weekend_takes_the_sprint_from_the_schedule(sprint):
    m, hist, eid = sprint
    sched = SY.f1_schedule()
    sched.loc[sched["round"] == sched["round"].max(), "sprint"] = True
    cutoff = m.sessions(eid)["race"] + pd.Timedelta(hours=4)
    per_event, _, _ = run.forecast(m, hist, 2026, cutoff=cutoff, n_sims=300, schedule=sched)
    by = {ev["round"]: ev["summary"] for ev in per_event}
    last = sched["round"].max()
    assert "sprint_win_prob" in by[last] and by[last]["sprint_win_prob"].sum() == pytest.approx(1.0, abs=0.02)
    assert all("sprint_win_prob" not in s for r, s in by.items() if r != last)


# --- the sims and the kinds ---------------------------------------------------------------------------------

def test_a_sprint_weekend_prices_race_sprint_win_from_its_sprint_stage(sprint):
    from racinglines.markets import kinds as K
    m, hist, eid = sprint
    summ, ex, _ = _price(m, hist, _cutoffs(m, eid)["pre_sprint"], eid)
    sims = O.from_position_sim(ex["entrants"], ex["sim"])
    s = ex["sim"]["stages"]["sprint"]
    assert sims.stage_rank["sprint"] is s["pos"] and sims.stage_rank["sprint_qual"] is s["grid"]
    by = summ.set_index("athlete_id").loc[sims.entrants]
    np.testing.assert_array_equal(K.fair("race_sprint_win", sims), (s["pos"] == 1).mean(0))
    np.testing.assert_array_equal(K.fair("race_sprint_win", sims), by["sprint_win_prob"].to_numpy())
    np.testing.assert_array_equal(K.fair("race_sprint_pole", sims), by["sprint_pole_prob"].to_numpy())
    # the summary and the records gain the two sprint kinds (default) and nothing else
    assert {"race_sprint_win", "race_sprint_pole"} <= set(K.summary(sims).columns)
    assert not {"race_sprint_podium", "race_sprint_top8"} & set(K.summary(sims).columns)
    rec = sims.to_records(1, "f1", "f1_sector_sim", 2026, eid, "2026-06", "after SQ", _cutoffs(m, eid)["pre_sprint"])
    assert set(rec["kind"]) & {k for k in K.KINDS if k.startswith("race_sprint")} == {"race_sprint_win", "race_sprint_pole"}


def test_sprint_kinds_are_the_race_payoffs_on_the_sprint_view(sprint):
    from racinglines.markets import kinds as K
    m, hist, eid = sprint
    _, ex, _ = _price(m, hist, _cutoffs(m, eid)["pre_weekend"], eid)
    sims = O.from_position_sim(ex["entrants"], ex["sim"])
    s = ex["sim"]["stages"]["sprint"]
    view = sims.at("sprint")
    assert view.rank is s["pos"] and view.points is s["points"] and view.groups == sims.groups
    np.testing.assert_array_equal(view.finished, ~s["dnf"])
    for kind, n in (("race_sprint_podium", 3), ("race_sprint_top8", 8)):
        assert not K.KINDS[kind].default and K.KINDS[kind].session == "sprint"
        np.testing.assert_array_equal(K.fair(kind, sims), ((s["pos"] <= n) & ~s["dnf"]).mean(0))
    a, b = sims.entrants[:2]
    assert K.fair("race_sprint_h2h", sims, a, b) == (s["pos"][:, 0] < s["pos"][:, 1]).mean()
    assert K.fair("race_sprint_h2h", sims, a, b) != K.fair("race_h2h", sims, a, b)
    np.testing.assert_array_equal(K.fair("race_sprint_h2h", sims), K.h2h_matrix(view))
    top = K.fair("race_sprint_constructor_top", sims)
    assert top == K.group_top(view) and abs(sum(top.values()) - 1) < 1e-9
    # none of them in the default records; named, they price the sprint
    assert not {"race_sprint_h2h", "race_sprint_constructor_top"} & set(
        sims.to_records(1, "f1", "m", 2026, eid, "e", "s", None)["kind"])
    rec = sims.to_records(1, "f1", "m", 2026, eid, "e", "s", None, kinds=["race_sprint_h2h", "race_sprint_constructor_top"])
    h = rec[(rec["kind"] == "race_sprint_h2h") & (rec["subject"] == str(a))].set_index("params")["fair"]
    assert h[f'{{"opponent_id": {b}}}'] == K.fair("race_sprint_h2h", sims, a, b)
    assert rec[rec["kind"] == "race_sprint_constructor_top"].set_index("subject")["fair"].to_dict() == top
    # a weekend without a sprint has no sprint view: the sprint kinds aren't priced from the race
    plain = O.from_position_sim(ex["entrants"], {k: ex["sim"][k] for k in GP_KEYS})
    with pytest.raises(ValueError):
        K.fair("race_sprint_podium", plain)
    assert not {k for k in rec["kind"]} - {"race_sprint_h2h", "race_sprint_constructor_top"}
    assert plain.to_records(1, "f1", "m", 2026, eid, "e", "s", None, kinds=["race_sprint_h2h"]).empty


def test_save_and_load_round_trip_the_stage_arrays(sprint, tmp_path):
    m, hist, eid = sprint
    _, ex, _ = _price(m, hist, _cutoffs(m, eid)["pre_weekend"], eid)
    sims = O.from_position_sim(ex["entrants"], ex["sim"])
    O.save_sims(sims, tmp_path / "s.npz")
    got = O.load_sims(tmp_path / "s.npz")
    assert set(got.stage_rank) == {"qual", "sprint_qual", "sprint"}
    for k in ("sprint_qual", "sprint"):
        np.testing.assert_array_equal(got.stage_rank[k], sims.stage_rank[k])
    np.testing.assert_array_equal(got.stage_finished["sprint"], sims.stage_finished["sprint"])
    np.testing.assert_array_equal(got.stage_points["sprint"], sims.stage_points["sprint"])
    # an archive without stages keeps its old meta (no new keys)
    import json
    plain = O.from_position_sim(ex["entrants"], {k: ex["sim"][k] for k in GP_KEYS})
    O.save_sims(plain, tmp_path / "p.npz")
    with np.load(tmp_path / "p.npz") as z:
        assert set(json.loads(str(z["meta"]))) == {"entrants", "stage_rank", "reached", "groups", "has_points"}
    assert not O.load_sims(tmp_path / "p.npz").stage_finished


def test_sprint_kinds_settle_on_the_sprint_columns():
    from racinglines.markets import kinds as K
    res = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4], position=[1, 2, 3, 4], status=["OK"] * 4, qual_position=[2, 1, 3, 4],
                            team_id=["a", "a", "b", "b"], points=[25, 18, 15, 12],
                            sprint_position=[4, 3, 1, 2], sprint_status=["OK", "OK", "OK", "DNF"],
                            sprint_points=[2, 3, 8, 0], sprint_qual_position=[3, 4, 1, 2]))
    assert K.settle("race_sprint_win", 3, None, res) is True and K.settle("race_sprint_win", 1, None, res) is False
    assert K.settle("race_sprint_pole", 3, None, res) is True and K.settle("race_sprint_pole", 2, None, res) is False
    assert K.settle("race_sprint_podium", 2, None, res) is True and K.settle("race_sprint_podium", 1, None, res) is False
    assert K.settle("race_sprint_podium", 4, None, res) is False            # retired in the sprint
    assert K.settle("race_sprint_top8", 4, None, res) is False and K.settle("race_sprint_top8", 1, None, res) is True
    assert K.settle("race_sprint_h2h", 3, {"opponent_id": 1}, res) is True
    assert K.settle("race_h2h", 3, {"opponent_id": 1}, res) is False        # the Grand Prix, unchanged
    assert K.settle("race_sprint_constructor_top", None, {"team": "b"}, res) is True
    assert K.settle("race_constructor_top", None, {"team": "a"}, res) is True
    # before the sprint's results are in (or a weekend without one): undecidable, never settled from the race
    gp = res[["athlete_id", "position", "status", "qual_position", "team_id", "points"]]
    for kind in ("race_sprint_podium", "race_sprint_top8", "race_sprint_h2h", "race_sprint_constructor_top"):
        assert K.settle(kind, 1, {"opponent_id": 2, "team": "a"}, gp) is None, kind
    assert K.settle("race_sprint_podium", 1, None, res.assign(sprint_status=None)) is None


def test_every_head_to_head_kind_is_a_binary_market_for_the_cancelled_race_rules():
    from racinglines.markets import kinds as K
    from racinglines.markets import settlement_rules as SR
    assert SR.BINARY_KINDS == {k for k, v in K.KINDS.items() if v.payoff == "h2h"}
    assert SR.payout("polymarket", SR.CANCELLED, "race_sprint_h2h") == 0.5


# --- settlement from the database (private_book.race_outcomes) ----------------------------------------------

def _ensure(s, model, **kw):
    from sqlalchemy import select
    row = s.scalars(select(model).filter_by(**{k: v for k, v in kw.items() if k in ("code", "slug", "display_name")})).first()
    if row is None:
        row = model(**kw)
        s.add(row)
        s.flush()
    return row


@pytest.mark.parametrize("sprint_ran", [True, False])
def test_race_outcomes_carry_the_sprint_and_the_private_book_settles_it(test_engine, sprint_ran):
    from datetime import date

    from sqlalchemy.orm import Session

    from racinglines.db import models as m
    from racinglines.markets import private_book as house
    with Session(test_engine) as s:
        sport = _ensure(s, m.Sport, code="f1_sp", name="F1 (sprint test)")
        league = _ensure(s, m.League, code="fia_sp", name="FIA (sprint test)")
        comp = _ensure(s, m.Competition, code="f1_wdc_sp", name="F1 (sprint test)", league_id=league.id, sport_id=sport.id)
        cat = _ensure(s, m.Category, code="DRV_SP", name="Drivers", competition_id=comp.id)
        season = _ensure(s, m.Season, competition_id=comp.id, year=2026)
        ev = m.Event(season_id=season.id, source="f1timing", source_key=f"sp-{sprint_ran}", name="Sprint test GP",
                     start_date=date(2026, 10, 11), status="completed")
        s.add(ev)
        s.flush()
        race = m.Race(event_id=ev.id, category_id=cat.id, format={"kind": "f1", "sprint": True})
        s.add(race)
        s.flush()
        rnd = {k: m.Round(race_id=race.id, kind=k, ordinal=i, name=k)
               for i, k in enumerate(("sprint_qual", "sprint", "qual", "race"))}
        s.add_all(rnd.values())
        s.flush()
        ath = [_ensure(s, m.Athlete, display_name=f"Sprint test driver {i}") for i in range(6)]
        gp = [1, 2, 3, 4, 5, 6]
        sprint = [(3, "OK", 6), (5, "OK", 4), (1, "OK", 8), (2, "OK", 7), (4, "OK", 5), (6, "DNF", 0)]
        sq_grid = [4, 0, 2, 1, 3, 5]                       # driver 1 started from the pit lane (GridPosition 0)
        for i, a in enumerate(ath):
            team = f"t{i // 2}"
            s.add(m.Result(round_id=rnd["race"].id, athlete_id=a.id, position=gp[i], status="OK", team=team,
                           extra={"team_id": team, "points": [25, 18, 15, 12, 10, 8][i]}))
            s.add(m.Result(round_id=rnd["qual"].id, athlete_id=a.id, position=gp[i], status="OK", team=team))
            s.add(m.Result(round_id=rnd["sprint_qual"].id, athlete_id=a.id, position=None, status="DNS", team=team))
            if sprint_ran:
                pos, st, pts = sprint[i]
                s.add(m.Result(round_id=rnd["sprint"].id, athlete_id=a.id, position=pos, status=st, team=team,
                               extra={"team_id": team, "points": pts, "grid": sq_grid[i]}))
        s.flush()
        mk = {}
        for kind, who, params in (("race_sprint_podium", 2, None), ("race_sprint_podium", 0, None),
                                  ("race_sprint_win", 2, None), ("race_sprint_pole", 3, None), ("race_sprint_pole", 1, None),
                                  ("race_sprint_h2h", 2, {"opponent_id": ath[0].id}),
                                  ("race_sprint_constructor_top", None, {"team": "t1"}), ("race_win", 0, None)):
            hm = m.HouseMarket(race_id=race.id, athlete_id=None if who is None else ath[who].id, kind=kind, title=kind,
                               fair_prob=0.3, spread=0.06, yes_price=0.33, no_price=0.73, params=params)
            s.add(hm)
            s.flush()
            mk[(kind, who)] = hm.id
        s.commit()
        with test_engine.connect() as c:
            res = house.race_outcomes(c, race.id)
            settled = set(house.settle_from_results(s, c, race.id))
        by = res.set_index("athlete_id")
        assert s.get(m.HouseMarket, mk[("race_win", 0)]).outcome is True
        if not sprint_ran:                      # before the sprint: nothing of it settles
            assert "sprint_status" not in res or by["sprint_status"].isna().all()
            assert settled == {mk[("race_win", 0)]}
            return
        assert by.loc[ath[2].id, "sprint_position"] == 1 and by.loc[ath[5].id, "sprint_status"] == "DNF"
        assert by.loc[ath[3].id, "sprint_qual_position"] == 1 and pd.isna(by.loc[ath[1].id, "sprint_qual_position"])
        assert by.loc[ath[2].id, "sprint_points"] == 8
        want = {("race_sprint_podium", 2): True, ("race_sprint_podium", 0): True, ("race_sprint_win", 2): True,
                ("race_sprint_pole", 3): True, ("race_sprint_h2h", 2): True,
                ("race_sprint_constructor_top", None): True, ("race_win", 0): True}
        for key, y in want.items():
            assert s.get(m.HouseMarket, mk[key]).outcome is y, key
        assert mk[("race_sprint_pole", 1)] not in settled          # pit-lane start: no SQ position, undecided
