"""Prediction records (racinglines/db/records.py, OutcomeSims.to_records, save_sims/load_sims): the long
records equal the catalogue's fair values, the sims archive round-trips exactly, a kind added later prices an
archived run, and the registry the readers use is the kinds' one. Synthetic data, no database."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from racinglines.db import reads
from racinglines.db import records as REC
from racinglines.markets import kinds as K
from racinglines.models import outcomes as O

pytestmark = pytest.mark.quick

OLD_PREDICTION_KINDS = ['race_win', 'race_podium', 'race_top10', 'race_make_final', 'champion', 'standings_top3',
                        'race_h2h', 'race_pole', 'race_constructor_top', 'constructors_champion', 'season_wins_ge',
                        'standings_h2h', 'race_sprint_pole', 'race_sprint_win']


def make_sims(n_sims=400, n=8, seed=5):
    rng = np.random.default_rng(seed)
    score = rng.normal(size=(n_sims, n)) + np.linspace(0, 1.5, n)
    rank = score.argsort(1).argsort(1) + 1.0
    finished = rng.random((n_sims, n)) > 0.1
    rank = np.where(finished, rank, np.inf)
    qual = (rng.normal(size=(n_sims, n)) + np.linspace(0, 1, n)).argsort(1).argsort(1) + 1.0
    made = rng.random((n_sims, n)) > 0.3
    return O.OutcomeSims(entrants=[101 + i for i in range(n)], rank=rank, finished=finished,
                         stage_rank={"qual": qual, "sprint": qual[:, ::-1].copy()}, reached={"final": made},
                         points=rng.integers(0, 26, size=(n_sims, n)).astype(float),
                         groups=["a", "a", "b", "b", "c", "c", "d", "d"])


def rec(sims, **kw):
    return sims.to_records(7, "f1", "test_model", 2026, 55, "2026-05", "pre_race", "2026-05-01 12:00", **kw)


def test_records_equal_the_catalogue_for_every_kind():
    sims = make_sims()
    df = rec(sims)
    assert list(df.columns) == O.RECORD_COLUMNS
    assert set(df["kind"]) == {"race_win", "race_podium", "race_top10", "race_pole", "race_sprint_win",
                               "race_make_final", "race_h2h", "race_constructor_top"}
    assert (df["n_sims"] == sims.n_sims).all() and (df["run_id"] == 7).all()
    for kind, g in df.groupby("kind"):
        k = K.KINDS[kind]
        if k.payoff == "h2h":
            h = K.h2h_matrix(sims)
            assert len(g) == 8 * 7 // 2
            for _, r in g.iterrows():
                b = json.loads(r["params"])["opponent_id"]
                assert r["fair"] == h[sims.index(int(r["subject"])), sims.index(b)]
        elif k.payoff == "group_top":
            want = K.fair(kind, sims)
            assert {r["subject"]: r["fair"] for _, r in g.iterrows()} == want
            assert all(json.loads(p) == {"team": s} for p, s in zip(g["params"], g["subject"]))
        else:
            np.testing.assert_array_equal(g["fair"].to_numpy(), K.fair(kind, sims))
            assert g["subject"].tolist() == [str(a) for a in sims.entrants]
            assert (g["params"] == "{}").all()
    np.testing.assert_allclose(df["se"], np.sqrt(df["fair"] * (1 - df["fair"]) / sims.n_sims))


def test_kinds_filter_and_unsupported_kinds():
    sims = make_sims()
    assert set(rec(sims, kinds=["race_win", "champion", "nope"])["kind"]) == {"race_win"}
    bare = O.OutcomeSims(entrants=[1, 2], rank=sims.rank[:, :2], finished=sims.finished[:, :2])
    assert set(rec(bare)["kind"]) == {"race_win", "race_podium", "race_top10", "race_h2h"}


def test_sims_archive_round_trips_exactly(tmp_path):
    for sims in (make_sims(), O.OutcomeSims(entrants=["x", "y"], rank=np.array([[1.0, np.inf]]),
                                            finished=np.array([[True, False]]))):
        O.save_sims(sims, tmp_path / "s.npz")
        got = O.load_sims(tmp_path / "s.npz")
        assert got.entrants == sims.entrants and got.groups == sims.groups
        np.testing.assert_array_equal(got.rank, sims.rank)
        np.testing.assert_array_equal(got.finished, sims.finished)
        assert (got.points is None) == (sims.points is None)
        if sims.points is not None:
            np.testing.assert_array_equal(got.points, sims.points)
        assert list(got.stage_rank) == list(sims.stage_rank) and list(got.reached) == list(sims.reached)
        for k in sims.stage_rank:
            np.testing.assert_array_equal(got.stage_rank[k], sims.stage_rank[k])
        for k in sims.reached:
            np.testing.assert_array_equal(got.reached[k], sims.reached[k])
        assert got.rank.dtype == sims.rank.dtype


def test_records_write_read_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv(REC.ROOT_ENV, str(tmp_path))
    sims = make_sims()
    df = rec(sims)
    d = REC.write(7, df)
    assert d == tmp_path / "7" and (d / "predictions.parquet").exists() and not (d / "sims.npz").exists()
    pd.testing.assert_frame_equal(REC.read(7), df)
    REC.write(8, df, sims=sims)
    np.testing.assert_array_equal(REC.load_sims(8).rank, sims.rank)
    REC.write(9, df, sims={"a": sims})
    np.testing.assert_array_equal(REC.load_sims(9, "a").rank, sims.rank)


def test_a_new_kind_prices_an_archived_run(tmp_path, monkeypatch):
    monkeypatch.setenv(REC.ROOT_ENV, str(tmp_path))
    sims = make_sims()
    REC.write(3, rec(sims), sims=sims)
    monkeypatch.setitem(K.KINDS, "race_top5", K.Kind("race_top5", "top_n", n=5, label="Top 5"))
    old = REC.load_sims(3)
    got = K.fair("race_top5", old)
    np.testing.assert_array_equal(got, ((sims.rank <= 5) & sims.finished).mean(0))
    assert "race_top5" in rec(old)["kind"].unique()


def test_one_kind_registry():
    assert reads.PREDICTION_KINDS == OLD_PREDICTION_KINDS
    sims = make_sims()
    for code in ("champion", "standings_top3", "constructors_champion", "season_wins_ge", "standings_h2h"):
        assert K.KINDS[code].payoff == "standings"
        with pytest.raises(ValueError):
            K.fair(code, sims)
        assert K.settle(code, 1, None, pd.DataFrame(dict(athlete_id=[1], position=[1], status=["OK"]))) is None
    assert [c for c in K.summary(sims).columns if c != "athlete_id"] == \
        ["race_win", "race_podium", "race_top10", "race_pole", "race_sprint_win", "race_make_final"]


def test_enabled_is_off_by_default(monkeypatch):
    monkeypatch.delenv(REC.SWITCH, raising=False)
    assert not REC.enabled()
    for v, want in (("1", True), ("true", True), ("0", False), ("", False)):
        monkeypatch.setenv(REC.SWITCH, v)
        assert REC.enabled() is want


def test_walk_forward_hands_back_sims_only_when_asked():
    from racinglines.core import walk_forward as WF
    sims = make_sims()
    ev = SimpleNamespace(id=1, season=2026, name="x", cutoff=pd.Timestamp("2026-01-01"))
    res = pd.DataFrame(dict(athlete_id=sims.entrants, position=np.arange(1.0, 9), status="OK",
                            qual_position=np.arange(1.0, 9), team_id=sims.groups, points=1.0))
    model = SimpleNamespace(history=lambda d, s: None, events=lambda d, s, se: [ev], price=lambda h, e, s, r: sims,
                            results=lambda d, e: res)
    st = SimpleNamespace(rng_seed=1)
    off = WF.run(model, None, st, echo=lambda *_: None)
    on = WF.run(model, None, st, echo=lambda *_: None, keep_sims=True)
    assert "sims" not in off and on["sims"] == [(ev, sims)]
    pd.testing.assert_frame_equal(off["rows"], on["rows"])


def test_f1_writer_archives_forecast_sims_but_not_stage_runs(tmp_path, monkeypatch):
    from racinglines.models.position_sim import pricing as run
    from racinglines.testing import synthetic as SY
    monkeypatch.setenv(REC.ROOT_ENV, str(tmp_path))
    m = run.Measurements.from_frames(*SY.f1_frames())
    hist = run.history(m)
    eid = int(m.drivers["event_id"].max())
    cutoff = m.sessions(eid)["qual"] + pd.Timedelta(hours=2)
    _, ex = run.price_race(m, hist, cutoff, eid, n_sims=300, rng=np.random.default_rng(1))
    sims = O.from_position_sim(ex["entrants"], ex["sim"])
    stage = dict(round=3, outcome=dict(sims=sims, stage="after FP1", cutoff=cutoff, archive=False))
    run._write_records(11, 2026, [stage], {"2026-03": eid})
    got = REC.read(11)
    assert set(got["stage"]) == {"after FP1"} and set(got["event"]) == {"2026-03"} and (got["run_id"] == 11).all()
    assert not list((tmp_path / "11").glob("sims*.npz"))
    fc = dict(round=3, outcome=dict(sims=sims, stage="pre-weekend", cutoff=cutoff, archive=True))
    run._write_records(12, 2026, [fc, dict(round=4)], {"2026-03": eid})
    np.testing.assert_array_equal(REC.load_sims(12, "2026-03").rank, sims.rank)
    summ = K.summary(sims).set_index("athlete_id")
    w = REC.read(12).query("kind == 'race_win'").set_index("subject")["fair"]
    assert w[str(sims.entrants[0])] == summ.loc[sims.entrants[0], "race_win"]
