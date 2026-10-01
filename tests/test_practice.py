"""Practice-pace prior: leakage and behaviour, on the pinned F1 fixture (2026 R06-R15 incl. practice)."""

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def meas(f1_meas):
    return f1_meas          # pinned inputs (tests/fixtures/f1), not the live database


def _event(meas, key="2026-15"):
    y, r = (int(x) for x in key.split("-"))
    ev = meas.res[(meas.res["year"] == y) & (meas.res["series_round"] == r)]
    return int(ev["event_id"].iloc[0]), meas.sessions(int(ev["event_id"].iloc[0]))


def test_view_only_has_practice_sessions_before_the_cutoff(meas):
    eid, s = _event(meas)
    v = meas.view(s["fp2"] + pd.Timedelta(minutes=30))           # FP2 under way: nothing from it yet
    assert set(v.practice.loc[v.practice["event_id"] == eid, "round"]) == {"fp1"}
    v = meas.view(s["fp3"] - pd.Timedelta(minutes=1))
    assert set(v.practice.loc[v.practice["event_id"] == eid, "round"]) == {"fp1", "fp2"}


def test_future_practice_row_raises(meas):
    from racinglines.models.position_sim import pricing as run
    eid, s = _event(meas)
    cutoff = s["fp1"] - pd.Timedelta(minutes=1)
    v = meas.view(cutoff)
    bad = meas.practice[meas.practice["event_id"] == eid].head(1)
    v.practice = pd.concat([v.practice, bad])
    with pytest.raises(run.LeakageError):
        run.assert_no_leak(v, cutoff)


def test_training_rows_are_priced_before_that_weekends_practice(meas):
    from racinglines.models.position_sim import practice as PR
    tr = PR.training_rows(meas)
    assert len(tr) and {"qp_pre", "best_1", "q_def"} <= set(tr.columns)
    # a blend fitted as of an event's start uses only events whose race had finished
    eid, s = _event(meas)
    before = s["fp1"]
    used = tr[tr["r_ts"] < before]["event_id"].unique()
    assert eid not in used


def test_prior_moves_prices_only_once_practice_has_run(meas):
    from racinglines.models.position_sim import practice as PR
    eid, s = _event(meas)
    blend = PR.fit(PR.training_rows(meas), s["fp1"])
    e = pd.DataFrame(dict(athlete_id=meas.practice.loc[meas.practice["event_id"] == eid, "athlete_id"].unique(), qp=0.01, rp=0.01))
    pre = meas.view(s["fp1"] - pd.Timedelta(minutes=1))
    same, sq = PR.apply(e, pre.practice, eid, blend)
    assert sq is None and same["qp"].equals(e["qp"])
    after = meas.view(s["qual"] - pd.Timedelta(minutes=1))
    moved, sq = PR.apply(e, after.practice, eid, blend)
    if blend:
        assert sq is not None and moved["qp"].nunique() > 1          # practice differentiates drivers


def test_pre_weekend_backtest_anchor_is_before_any_running(meas):
    eid, s = _event(meas)
    first = min(t for k, t in s.items() if k in ("fp1", "fp2", "fp3", "sprint_qual") and t is not None and pd.notna(t))
    assert first == s["fp1"]


def test_cutoff_inside_a_session_sees_nothing_of_it(meas):
    """Qualifying is usable only after it ends: 30 min into it, its results aren't in the view."""
    eid, s = _event(meas)
    v = meas.view(s["qual"] + pd.Timedelta(minutes=30))
    assert not ((v.res["event_id"] == eid) & (v.res["round"] == "qual")).any()
    assert not ((v.sectors["event_id"] == eid)).any()
    v = meas.view(s["qual"] + pd.Timedelta(minutes=61))
    assert ((v.res["event_id"] == eid) & (v.res["round"] == "qual")).any()
