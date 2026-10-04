"""Fastest lap from the race simulation (position_sim `fastlap` variant, model.FASTEST_LAP, off by default):
the switch adds `fl` and leaves every other output byte-identical, the draw respects retirements and pace, the
quote doesn't see the race it prices, and the kind reaches the catalogue, the records and db.reads.model_prob.
Synthetic data; the model_prob check uses the throwaway test database."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from racinglines.markets import kinds as K
from racinglines.models import outcomes as O
from racinglines.models.position_sim import model as M
from racinglines.models.position_sim import variants as V

SIM_KEYS = ("pos", "dnf", "points", "grid")


def _field(rp, p_dnf=0.1):
    n = len(rp)
    return pd.DataFrame(dict(athlete_id=range(100, 100 + n), team_key=[f"t{i // 2}" for i in range(n)], qp=rp, rp=rp,
                             p_dnf=p_dnf, grid=range(1, n + 1)))


def _fm(**kw):
    return M.FinishModel(coef=np.array([1.0, 0, 0.1, 0, 0, 0]), intercept=0.0, sigma=0.3, sigma_q=0.003,
                         use_track=False, rho_q=0.5, rho_f=0.3, **kw)


def _sim(fm, e, n_sims=2000, seed=11, shock=False, **kw):
    """simulate_race on a fresh stream; also returns the stream's next draws (has the main stream moved?)."""
    rng = np.random.default_rng(seed)
    ps = rng.normal(0, 0.003, (n_sims, len(e))) if shock else None
    s = M.simulate_race(fm, e, dict(ease=1.0, street=0.0), n_sims=n_sims, rng=rng, pace_shock=ps, **kw)
    return s, rng.random(8)


def _same(a, b):
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


def test_off_by_default_and_restored():
    assert M.FASTEST_LAP is False and "fastlap" in V.SWITCHES and V.describe("fastlap")
    with V.use("gridq+fastlap"):
        assert M.FASTEST_LAP is True
    assert M.FASTEST_LAP is False
    s, _ = _sim(_fm(), _field([0.0, 0.001, 0.002, 0.003]), n_sims=50)
    assert "fl" not in s and "fl_prob" not in M.summarize(_field([0.0, 0.001, 0.002, 0.003]), s)


# sha256 of pos, dnf, points, grid from the case below, computed with the code before the switch existed (5df5aba);
# only a deliberate model change (or a numpy release that changes its random streams) may move it
BEFORE_SHA = "c8104984a253d930b4709376f2946bb9e22ce3bb151acb7219cf91a77d97f240"


@pytest.mark.parametrize("variant", ["baseline", "fastlap"])
def test_simulation_is_byte_identical_to_before_the_switch(variant):
    import hashlib
    e = _field([0.0, 0.001, 0.002, 0.003, 0.004, 0.005])
    with V.use(variant):
        s, _ = _sim(_fm(rho_dnf=0.4), e, n_sims=300, seed=11, shock=True)
    h = hashlib.sha256()
    for k in SIM_KEYS:
        h.update(s[k].tobytes())
    assert h.hexdigest() == BEFORE_SHA


@pytest.mark.parametrize("case", [dict(), dict(grid_known=True), dict(shock=True), dict(fm=dict(rho_dnf=0.4))])
def test_switch_adds_fl_and_every_other_output_is_byte_identical(case):
    case = dict(case)
    fm = _fm(**case.pop("fm", {}))
    e = _field([0.0, 0.001, 0.002, 0.004, 0.006, 0.009], p_dnf=0.15)
    off, off_next = _sim(fm, e, **case)
    with V.use("fastlap"):
        on, on_next = _sim(fm, e, **case)
    assert set(on) == set(off) | {"fl"}
    for k in SIM_KEYS:
        assert _same(off[k], on[k]), k
    assert _same(off_next, on_next)                  # the caller's stream is where it would have been
    so, sn = M.summarize(e, off), M.summarize(e, on)
    pd.testing.assert_frame_equal(so, sn.drop(columns="fl_prob"))


def test_price_race_with_fastlap_is_otherwise_identical():
    """Through the one pricing path: the summary, head-to-heads and the constructor tie-break (drawn from the
    main stream after the simulation) are unchanged; fl_prob is the catalogue's fair value and is recorded."""
    from racinglines.models.position_sim import pricing as run
    from racinglines.testing import synthetic as SY
    m = run.Measurements.from_frames(*SY.f1_frames())
    hist = run.history(m)
    eid = int(m.drivers["event_id"].max())
    for cutoff in (m.sessions(eid)["qual"] - pd.Timedelta(minutes=1), m.sessions(eid)["qual"] + pd.Timedelta(hours=2)):
        base, bex = run.price_race(m, hist, cutoff, eid, n_sims=1500, rng=np.random.default_rng(5))
        with V.use("fastlap"):
            summ, ex = run.price_race(m, hist, cutoff, eid, n_sims=1500, rng=np.random.default_rng(5))
        pd.testing.assert_frame_equal(base, summ.drop(columns="fl_prob"))
        assert bex["constructor_top"] == ex["constructor_top"]
        for k in SIM_KEYS:
            assert _same(bex["sim"][k], ex["sim"][k]), k
        ok = ~ex["sim"]["dnf"]
        assert summ["fl_prob"].sum() == pytest.approx(ok.any(axis=1).mean())        # one per race with a finisher
        assert summ["fl_prob"].sum() == pytest.approx(1.0, abs=0.01)
        sims = O.from_position_sim(ex["entrants"], ex["sim"])
        fair = pd.Series(K.fair("race_fastest_lap", sims), index=sims.entrants)
        np.testing.assert_array_equal(fair.loc[summ["athlete_id"]].to_numpy(), summ["fl_prob"].to_numpy())
        rec = sims.to_records(1, "f1", "f1_sector_sim", 2026, eid, "2026-06", "after Quali", cutoff)
        got = rec[rec["kind"] == "race_fastest_lap"].set_index("subject")["fair"]
        assert len(got) == len(sims.entrants) and got[str(sims.entrants[0])] == fair.iloc[0]
        assert "race_fastest_lap" not in set(O.from_position_sim(bex["entrants"], bex["sim"])
                                             .to_records(1, "f1", "m", 2026, eid, "e", "s", cutoff)["kind"])


def test_fastest_lap_goes_to_one_classified_car_and_follows_pace():
    rp = [0.0, 0.002, 0.004, 0.006, 0.008, 0.010, 0.012, 0.014]
    p_dnf = np.array([0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 1.0])          # the last car always retires
    e = _field(rp, p_dnf=p_dnf)
    with V.use("fastlap"):
        s, _ = _sim(_fm(), e, n_sims=20000, shock=True)
    fl, dnf = s["fl"], s["dnf"]
    assert not (fl & dnf).any()                                           # a retired car never has it
    assert set(fl.sum(axis=1)) == {1}                                     # one per race (someone finished)
    p = M.summarize(e, s).set_index("athlete_id")["fl_prob"].loc[e["athlete_id"]].to_numpy()
    assert p.sum() == pytest.approx(1.0) and p[-1] == 0.0
    assert (np.diff(p[:-1]) < 0).all()                                    # faster race pace, likelier fastest lap
    assert p[0] > 2 * p[4]
    # nobody classified: no fastest lap
    with V.use("fastlap"):
        none, _ = _sim(_fm(), _field([0.0, 0.001], p_dnf=1.0), n_sims=200)
    assert not none["fl"].any()


def test_side_stream_is_reproducible_and_differs_between_races():
    e = _field([0.0, 0.001, 0.002, 0.003, 0.004, 0.005])
    with V.use("fastlap"):
        a, _ = _sim(_fm(), e, n_sims=500)
        b, _ = _sim(_fm(), e, n_sims=500)
        rng = np.random.default_rng(11)
        first = M.simulate_race(_fm(), e, dict(ease=1.0, street=0.0), n_sims=500, rng=rng)
        second = M.simulate_race(_fm(), e, dict(ease=1.0, street=0.0), n_sims=500, rng=rng)
    assert _same(a["fl"], b["fl"])                                        # same stream state, same draw
    assert _same(first["fl"], a["fl"]) and not _same(first["fl"], second["fl"])   # a shared stream moves it on


def test_fastest_lap_quote_doesnt_see_the_race_it_prices():
    """Leakage rule: rewrite the priced race's own laps (after the cutoff) so another car is fastest; the
    fastest-lap prices don't move."""
    from racinglines.models.position_sim import pricing as run
    from racinglines.testing import synthetic as SY
    res, laps, prof = SY.f1_frames()
    eid = int(res.loc[res["event_status"] == "completed", "event_id"].max())
    qual = res[(res["event_id"] == eid) & (res["round"] == "qual")]
    slow = int(qual.sort_values("position")["athlete_id"].iloc[-1])          # last on the grid
    hot = laps.copy()
    rows = (hot["event_id"] == eid) & (hot["round"] == "race") & (hot["athlete_id"] == slow)
    hot.loc[rows, "lap_time_ms"] = (hot.loc[rows, "lap_time_ms"] * 0.9).round()
    out = []
    for lp in (laps, hot):
        m = run.Measurements.from_frames(res, lp, prof)
        cutoff = m.sessions(eid)["qual"] + pd.Timedelta(hours=2)
        with V.use("fastlap"):
            hist = run.history(m)
            summ, _ = run.price_race(m, hist, cutoff, eid, n_sims=1000, rng=np.random.default_rng(2))
        out.append(summ.set_index("athlete_id")["fl_prob"].sort_index())
    pd.testing.assert_series_equal(out[0], out[1])


def test_indicator_kind_in_the_catalogue(tmp_path):
    from racinglines.db import reads
    from racinglines.markets import venues
    k = K.KINDS["race_fastest_lap"]
    assert k.payoff == "indicator" and k.label == "Fastest lap" and "race_fastest_lap" in reads.PREDICTION_KINDS
    assert venues.KIND_LABEL["race_fastest_lap"] == "Fastest lap"
    rank = np.array([[1.0, 2.0, 3.0], [2.0, 1.0, 3.0], [1.0, 3.0, 2.0], [3.0, 2.0, 1.0]])
    plain = O.OutcomeSims(entrants=[1, 2, 3], rank=rank, finished=np.ones_like(rank, bool))
    with pytest.raises(ValueError):
        K.fair("race_fastest_lap", plain)
    assert "race_fastest_lap" not in K.summary(plain)
    fl = np.array([[True, False, False], [True, False, False], [False, True, False], [False, False, True]])
    sims = O.OutcomeSims(entrants=[1, 2, 3], rank=rank, finished=np.ones_like(rank, bool),
                         indicators={"race_fastest_lap": fl})
    np.testing.assert_array_equal(K.fair("race_fastest_lap", sims), [0.5, 0.25, 0.25])
    assert K.fair("race_fastest_lap", sims, a=2) == 0.25
    assert K.summary(sims)["race_fastest_lap"].tolist() == [0.5, 0.25, 0.25]
    res = pd.DataFrame(dict(athlete_id=[1, 2, 3], position=[1, 2, 3], status="OK", qual_position=[1, 2, 3]))
    assert K.settle("race_fastest_lap", 1, None, res) is None             # the classification doesn't record it
    O.save_sims(sims, tmp_path / "s.npz")
    np.testing.assert_array_equal(O.load_sims(tmp_path / "s.npz").indicators["race_fastest_lap"], fl)
    O.save_sims(plain, tmp_path / "p.npz")
    assert O.load_sims(tmp_path / "p.npz").indicators == {}


def test_model_prob_reads_fl_prob(test_engine):
    from sqlalchemy import select

    from racinglines.db import models as m
    from racinglines.db.config import get_session
    from racinglines.db.ingest import _upsert, seed
    from racinglines.db.reads import model_prob
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        comp = s.scalars(select(m.Competition).filter_by(code="f1_wdc")).one()
        cat = s.scalars(select(m.Category).filter_by(competition_id=comp.id, code="DRV")).one()
        season = _upsert(s, m.Season, dict(competition_id=comp.id, year=2026))
        a, b = m.Athlete(display_name="Fast Lap", nation="GBR"), m.Athlete(display_name="No Lap", nation="GBR")
        ev = m.Event(season_id=season.id, source="test", source_key="fl-2026-99", name="Fastest Lap GP",
                     start_date=date(2026, 10, 4), series_round=99)
        s.add_all([a, b, ev])
        s.flush()
        race = m.Race(event_id=ev.id, category_id=cat.id, format=dict(kind="f1"))
        on = m.ModelRun(competition_id=comp.id, season_id=season.id, category_id=cat.id, model="f1_sector_sim",
                        kind="diagnostic", params=dict(variant="fastlap"))
        off = m.ModelRun(competition_id=comp.id, season_id=season.id, category_id=cat.id, model="f1_sector_sim",
                         kind="diagnostic")
        s.add_all([race, on, off])
        s.flush()
        s.add_all([m.RacePrediction(model_run_id=on.id, race_id=race.id, target="asof:2026-99", athlete_id=a.id,
                                    win_prob=0.3, extra=dict(pole_prob=0.2, fl_prob=0.27)),
                   m.RacePrediction(model_run_id=on.id, race_id=race.id, target="asof:2026-99", athlete_id=b.id,
                                    win_prob=0.1, extra=dict(pole_prob=0.1, fl_prob=0.0)),
                   m.RacePrediction(model_run_id=off.id, race_id=race.id, target="asof:2026-99", athlete_id=a.id,
                                    win_prob=0.3, extra=dict(pole_prob=0.2))])
        s.commit()
        ids = dict(a=a.id, b=b.id, race=race.id, comp=comp.id, cat=cat.id, on=on.id, off=off.id)
    link = dict(prediction="race_fastest_lap", competition_id=ids["comp"], category_id=ids["cat"], athlete_id=ids["a"],
                race_id=ids["race"], params={}, invert=False)
    with test_engine.connect() as c:
        assert model_prob(c, link, run_id=ids["on"]) == (pytest.approx(0.27), ids["on"])
        assert model_prob(c, dict(link, invert=True), {}, run_id=ids["on"])[0] == pytest.approx(0.73)
        assert model_prob(c, dict(link, athlete_id=ids["b"]), run_id=ids["on"])[0] == 0.0
        assert model_prob(c, link, run_id=ids["off"]) == (None, ids["off"])      # a run without the switch
        assert model_prob(c, dict(link, prediction="race_pole"), run_id=ids["off"])[0] == pytest.approx(0.2)
