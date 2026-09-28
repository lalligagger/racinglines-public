"""The pricing-model contract (racinglines/models/race_model.py) and the shared walk-forward engine
(racinglines/core/walk_forward.py): the engine's downhill run equals walk_forward_season rider for
rider, the F1 wrapper prices exactly as price_race, and settings keys don't move. Synthetic data."""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from racinglines.core import walk_forward as WF
from racinglines.models import race_model as RM
from racinglines.pipelines import sweep_settings as SS

pytestmark = pytest.mark.quick


@pytest.fixture(scope="module")
def dh():
    from racinglines.models.timed_runs import RUN_WEIGHTS
    from racinglines.sources.chronorace.parse import parse_markdown_tables_file
    from racinglines.testing import synthetic as SY
    d = Path(tempfile.mkdtemp(prefix="racinglines-test-"))
    for name, text in SY.mtb_results_md(n_events=5).items():
        (d / name).write_text(text)
    raw = pd.concat([pd.DataFrame(parse_markdown_tables_file(f)) for f in sorted(d.glob("*.md"))], ignore_index=True)
    m = RM.get("mtb_dh")
    return m, m.load(data=raw[raw["round"].isin(RUN_WEIGHTS)])


def test_downhill_engine_equals_walk_forward_season(dh):
    from racinglines.models.timed_runs import completed_events, select_target, walk_forward_season
    m, data = dh
    st = m.Settings.from_dict(dict(sims=400, seed=7))
    seasons = m.seasons(data, st)
    out = WF.run(m, data, st, seasons=seasons, echo=lambda s: None)
    rng, riders = np.random.default_rng(7), []
    for s in seasons:
        t = select_target(data, s, "ME")
        walk_forward_season(data, t[t["event_id"].isin(completed_events(t))], n_sims=400, rng=rng,
                            rider_rows=riders, **st.fit_kw())
    old = pd.concat(riders, ignore_index=True).rename(columns={"rider_id": "athlete_id"})
    assert len(out["events"]) == old["event_id"].nunique() > 0
    for kind, p, y in (("race_win", "win_prob", "won"), ("race_podium", "podium_prob", "podium"),
                       ("race_top10", "top10_prob", "top10"), ("race_make_final", "make_final_prob", "made_final")):
        j = out["rows"][out["rows"]["kind"] == kind].merge(old, on=["event_id", "athlete_id"], validate="1:1")
        assert len(j) == len(old)
        np.testing.assert_array_equal(j["fair"].to_numpy(), j[p].to_numpy(), err_msg=kind)
        np.testing.assert_array_equal(j["y"].astype(bool).to_numpy(), j[y].to_numpy(bool), err_msg=kind)


def test_downhill_results_settle_every_kind(dh):
    from racinglines.markets import kinds as K
    m, data = dh
    st = m.Settings.from_dict()
    ev = m.events(data, st)[-1]
    res = m.results(data, ev)
    assert res["reached_final"].any() and (res["position"] == 1).sum() == 1
    winner = res.loc[res["position"] == 1, "athlete_id"].iloc[0]
    assert K.settle("race_win", winner, None, res) and K.settle("race_make_final", winner, None, res)
    assert K.settle("race_make_final", "nobody", None, res) is False
    assert K.settle("race_make_final", winner, None, res.drop(columns="reached_final")) is None


def test_seed_and_settings_change_the_run_and_the_key(dh):
    m, data = dh
    a, b = m.Settings.from_dict(dict(sims=300)), m.Settings.from_dict(dict(sims=300, seed=1))
    assert a.key != b.key and m.Settings.from_dict().key == m.Settings.from_dict(dict(prior_n=0.5)).key
    ra, rb = (WF.run(m, data, s, echo=lambda x: None)["rows"] for s in (a, b))
    assert not np.array_equal(ra["fair"], rb["fair"])
    with pytest.raises(ValueError):
        m.Settings.from_dict(dict(variant="gridq"))              # F1's settings aren't downhill's


def test_f1_settings_keys_did_not_move():
    # saved sweeps are found by these keys (same values as before the settings schema became a class attribute)
    assert SS.Settings.from_dict().key == "c107835cbced"
    assert SS.Settings.from_dict().model_key == "56f55ac79102"
    assert SS.Settings.from_dict(dict(variant="gridq+pretrain", half_life_days=90, min_edge_h2h=0.08)).key == "dfcd2cf94ffc"


def test_f1_wrapper_prices_as_price_race():
    from racinglines.markets import kinds as K
    from racinglines.models.position_sim import pricing as run
    from racinglines.testing import synthetic as SY
    m = RM.get("f1")
    data = m.load(data=run.Measurements.from_frames(*SY.f1_frames()))
    st = m.Settings.from_dict(dict(sims=1000))
    hist = m.history(data, st)
    ev = m.events(data, st)[-1]
    sims = m.price(hist, ev, st, np.random.default_rng(5))
    with st.applied():
        summ, _ = run.price_race(data, hist.hist, ev.cutoff, ev.id, n_sims=1000, rng=np.random.default_rng(5))
    got = K.summary(sims).set_index("athlete_id")
    np.testing.assert_array_equal(got["race_win"].to_numpy(), summ.set_index("athlete_id").loc[got.index, "win_prob"])
    rows = WF.event_rows(ev, sims, m.results(data, ev), ["race_win", "race_h2h", "race_constructor_top"])
    assert rows.groupby("kind")["y"].apply(lambda y: y.notna().all()).all()
    assert rows.loc[rows["kind"] == "race_win", "y"].sum() == 1
    assert rows.loc[rows["kind"] == "race_constructor_top", "y"].sum() == 1
