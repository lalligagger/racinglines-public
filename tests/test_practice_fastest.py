"""F1 practice fastest lap (models/position_sim/practice.py, model.PRACTICE_FASTEST, variant "practicefast", package
C12b): off by default; when on, every other price is byte-identical, each practice session's fair sums to 1 over the
field, the real order replaces the draw once the session has run, the kinds settle on the stored laps' order, and the
walk-forward scores it. The pinned F1 fixtures (tests/fixtures/f1), plus the throwaway test database for outcomes()."""

import numpy as np
import pandas as pd
import pytest

from racinglines.markets import kinds as K
from racinglines.models import outcomes as O
from racinglines.models.position_sim import model as M
from racinglines.models.position_sim import practice as PR
from racinglines.models.position_sim import pricing as run
from racinglines.models.position_sim import variants as V

KINDS = ("race_fp1_fastest", "race_fp2_fastest", "race_fp3_fastest")


def _event(meas):
    """The latest fixture event with FP1, FP2 and FP3 laps."""
    c = PR.classification(meas.practice)
    full = c.groupby("event_id")["round"].nunique()
    evs = meas.drivers.drop_duplicates("event_id").sort_values("r_ts")
    return next(e for e in reversed(evs["event_id"].tolist()) if full.get(e, 0) == 3)


def _price(meas, hist, cutoff, event_id, variant="baseline", seed=3, n_sims=400):
    rng = np.random.default_rng(seed)
    with V.use(variant):
        summ, ex = run.price_race(meas, hist, cutoff, event_id, n_sims=n_sims, rng=rng)
    return summ, ex, rng.random(4)


def test_off_by_default_and_the_kinds_are_rows():
    assert M.PRACTICE_FASTEST is False and "practicefast" in V.SWITCHES and V.describe("practicefast")
    assert M.PRACTICE_CLASSIFIED == ("fp1", "fp2", "fp3")                       # Sprint Qualifying is the sprint grid
    for k in KINDS:
        assert K.KINDS[k].spec is not None and not K.KINDS[k].default


def test_practice_draws_move_no_other_price_and_sum_to_one(f1_meas, f1_hist):
    ev = _event(f1_meas)
    start = f1_meas.sessions(ev)["fp1"]
    cut = start - pd.Timedelta(minutes=1)                                       # before FP1: every session drawn
    s_off, x_off, next_off = _price(f1_meas, f1_hist, cut, ev)
    s_on, x_on, next_on = _price(f1_meas, f1_hist, cut, ev, "practicefast")
    assert "practice" not in x_off["sim"] and set(x_on["sim"]["practice"]) == {"fp1", "fp2", "fp3"}
    for k in ("pos", "dnf", "points", "grid"):
        assert x_on["sim"][k].tobytes() == x_off["sim"][k].tobytes(), k
    assert np.array_equal(next_on, next_off)                                    # the caller's stream didn't move
    pd.testing.assert_frame_equal(s_on, s_off)
    sims = O.from_position_sim(x_on["entrants"], x_on["sim"])
    for k in KINDS:
        p = K.fair(k, sims)
        assert p.sum() == pytest.approx(1.0) and (p > 0).sum() > 3              # a draw, not a certainty
    off = O.from_position_sim(x_off["entrants"], x_off["sim"])
    with pytest.raises(ValueError):
        K.fair("race_fp1_fastest", off)                                         # not drawn: not priced


def test_after_a_session_its_real_order_and_its_settlement(f1_meas, f1_hist):
    ev = _event(f1_meas)
    starts = f1_meas.sessions(ev)
    cut = starts["fp2"] - pd.Timedelta(minutes=1)                               # FP1 over, FP2 not started
    _, x, _ = _price(f1_meas, f1_hist, cut, ev, "practicefast")
    sims = O.from_position_sim(x["entrants"], x["sim"])
    c = PR.classification(f1_meas.practice, ev)
    fp1 = c[c["round"] == "fp1"]
    fastest = int(fp1.loc[fp1["position"] == 1, "athlete_id"].iloc[0])
    p1 = K.fair("race_fp1_fastest", sims)
    assert p1[sims.index(fastest)] == 1.0 and p1.sum() == 1.0                   # known
    assert K.fair("race_fp2_fastest", sims).max() < 1.0                         # still drawn
    # the walk-forward's result frame settles each session on its order of best laps
    from racinglines.models.race_model import Event, PositionSim
    res = PositionSim().results(f1_meas, Event(id=ev, season=0, cutoff=None, name=""))
    assert {"fp1_position", "fp2_position", "fp3_position"} <= set(res.columns)
    assert K.settle("race_fp1_fastest", fastest, {}, res) is True
    other = int(fp1.loc[fp1["position"] == 2, "athlete_id"].iloc[0])
    assert K.settle("race_fp1_fastest", other, {}, res) is False
    assert K.settle("race_fp1_fastest", -1, {}, res) is False                   # not in the results: NO
    assert K.settle("race_fp1_fastest", fastest, {}, res.drop(columns=["fp1_position"])) is None   # not stored


def test_classification_is_the_order_of_best_valid_laps(f1_frames, f1_meas):
    _, laps, _ = f1_frames
    ev = _event(f1_meas)
    l = laps[(laps["event_id"] == ev) & (laps["round"] == "fp1") & laps["lap_time_ms"].notna()]
    l = l[~l["deleted"].fillna(False).astype(bool)]
    want = l.groupby("athlete_id")["lap_time_ms"].min().sort_values()
    c = PR.classification(f1_meas.practice, ev)
    got = c[c["round"] == "fp1"].sort_values(["position", "athlete_id"])
    assert got["athlete_id"].iloc[0] == want.index[0] and len(got) == len(want)
    assert got["position"].min() == 1


def test_the_walk_forward_scores_each_session(f1_meas, f1_hist):
    ev = _event(f1_meas)
    out = PR.score(f1_meas, f1_hist, n_sims=200, seed=1, events=[ev])
    assert set(out["session"]) == {"fp1", "fp2", "fp3"} and (out["event_id"] == ev).all()
    assert ((out["p_fastest"] > 0) & (out["p_fastest"] <= 1)).all() and np.isfinite(out["logloss"]).all()
    assert (out["uniform"] == np.log(out["n"])).all()
    assert M.PRACTICE_FASTEST is False                                          # restored


def test_outcomes_from_the_database(test_engine):
    """outcomes() ranks each practice session's best non-deleted lap per driver; a session without laps: no column."""
    from sqlalchemy import delete
    from sqlalchemy.orm import sessionmaker

    from racinglines.db import models as m
    from racinglines.db.ingest import ensure_competition
    S = sessionmaker(test_engine)
    with S() as s:
        comp, cat = ensure_competition(s, "f1")
        season = m.Season(competition_id=comp.id, year=1999)
        s.add(season)
        s.flush()
        event = m.Event(season_id=season.id, source="c12b_test", source_key="1999-01", name="Test GP",
                        start_date=pd.Timestamp("1999-03-07").date(), status="completed")
        s.add(event)
        s.flush()
        race = m.Race(event_id=event.id, category_id=cat.id)
        s.add(race)
        s.flush()
        athletes = [m.Athlete(display_name=f"c12b driver {i}") for i in range(3)]
        s.add_all(athletes)
        s.flush()
        fp1 = m.Round(race_id=race.id, kind="fp1", ordinal=1, name="FP1")
        s.add(fp1)
        s.flush()
        laps = {0: [(1, 90_500, False), (2, 89_900, True)],     # the deleted 89.9 doesn't count
                1: [(1, 90_100, False)], 2: [(1, 0, False)]}     # 0 is no lap
        for i, a in enumerate(athletes):
            r = m.Result(round_id=fp1.id, athlete_id=a.id, status="OK")
            s.add(r)
            s.flush()
            s.add_all([m.Lap(result_id=r.id, lap=n, lap_time_ms=t, deleted=d) for n, t, d in laps[i]])
        s.commit()
        ids, race_id, comp_id = [a.id for a in athletes], race.id, comp.id
    try:
        with test_engine.connect() as conn:
            out = PR.outcomes(conn, race_id)
        assert set(out.columns) == {"athlete_id", "fp1_position"}
        pos = out.set_index("athlete_id")["fp1_position"]
        assert pos[ids[1]] == 1 and pos[ids[0]] == 2 and ids[2] not in pos.index
        res = pd.DataFrame(dict(athlete_id=ids, position=[1.0, 2.0, 3.0], status="OK")).merge(out, how="left")
        assert K.settle("race_fp1_fastest", ids[1], {}, res) is True
        assert K.settle("race_fp1_fastest", ids[2], {}, res) is False            # no lap, the session ran: NO
        assert K.settle("race_fp2_fastest", ids[1], {}, res) is None             # FP2 not stored
    finally:
        with S() as s:
            s.execute(delete(m.Event).where(m.Event.source == "c12b_test"))
            s.execute(delete(m.Season).where(m.Season.year == 1999, m.Season.competition_id == comp_id))
            s.execute(delete(m.Athlete).where(m.Athlete.id.in_(ids)))
            s.commit()
