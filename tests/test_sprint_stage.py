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
