"""The one engine (racinglines/models/model_global.py GlobalModel; decision log 2026-10-11 "One engine"): every modelled
sport's [sport] pricing_model, its inputs declared in the schema ([model] inputs), its defaults the schema's
([model.defaults]), and its prices the same as each sport's engine before it, with the same seed and data:

    F1         GlobalModel[f1]      == race_model.PositionSim (challenger f1_sector_sim) == laps_pricing.price_race
    downhill   GlobalModel[mtb_dh]  == race_model.TimedRuns   (challenger timed_runs)
    NASCAR     GlobalModel[nascar]  == the counts origin/staging's GlobalModel gave (pinned below)
    MotoGP     GlobalModel[motogp]  == the same

Synthetic data only (racinglines/testing/synthetic.py and frames built here); no tests/fixtures, no database. The
F1 and downhill checks compare in one process, so they hold on any machine; the NASCAR / MotoGP counts were recorded
from origin/staging (2b7b410) on Linux x86-64 and use no BLAS (probit, recency weights, argsort)."""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from racinglines import sports
from racinglines.models import inputs as INP
from racinglines.models import model_global as G
from racinglines.models import race_model as RM
from racinglines.models.race_model import Event
from racinglines.pipelines import sweep_settings as SS

pytestmark = pytest.mark.quick

ROOT = Path(__file__).resolve().parent.parent
ENGINE = "racinglines.models.model_global:GlobalModel"
MODELLED = [c for c in sports.SPORT_CODES if sports.modeled(c)]


def same_sims(a, b):
    """Two OutcomeSims are equal array for array (None only with None)."""
    assert (a is None) == (b is None)
    if a is None:
        return
    assert list(a.entrants) == list(b.entrants) and a.groups == b.groups
    np.testing.assert_array_equal(a.rank, b.rank)
    np.testing.assert_array_equal(a.finished, b.finished)
    if a.points is None or b.points is None:
        assert a.points is None and b.points is None
    else:
        np.testing.assert_array_equal(a.points, b.points)
    for d in ("stage_rank", "reached", "indicators", "stage_finished", "stage_points"):
        x, y = getattr(a, d), getattr(b, d)
        assert sorted(x) == sorted(y), d
        for k in x:
            np.testing.assert_array_equal(x[k], y[k], err_msg=f"{d}[{k}]")


# --- the guard: one engine, schemas declare the rest ---------------------------------------------------------------
@pytest.mark.parametrize("code", sports.SPORT_CODES)
def test_every_modelled_sport_prices_with_the_one_engine(code):
    s = sports.load(code)["sport"]
    if s.get("model_family", "none") == "none":
        assert "pricing_model" not in s                             # a tape-only sport has no model
        return
    assert s["model_family"] == "global" and s["pricing_model"] == ENGINE
    m = RM.model_class(code)
    assert issubclass(m, G.GlobalModel) and m.sport == code
    assert set(m.inputs) <= set(INP.INPUTS) and m.core in INP.BY_KEY


def test_the_schemas_pick_the_cores_by_their_inputs():
    got = {c: (RM.model_class(c).core, RM.model_class(c).name) for c in MODELLED}
    assert got == {"f1": ("laps", "f1_sector_sim"), "mtb_dh": ("run_times", "timed_runs"),
                   "nascar": ("results", "global_results"), "motogp": ("results", "global_results"),
                   "road_cycling": ("results", "global_results")}


def test_no_engine_module_names_a_sport():
    """The engine and its input layers choose by declared inputs, never by sport (no `if sport == "f1"`)."""
    files = [ROOT / "racinglines/models/model_global.py", *sorted((ROOT / "racinglines/models/inputs").rglob("*.py"))]
    codes = "|".join(sports.SPORT_CODES)
    for f in files:
        assert not re.search(rf"""["']({codes})["']""", f.read_text()), f


def test_core_selection_rules():
    assert INP.core_for(["results"]).key == "results"
    assert INP.core_for(["results", "qualifying", "grid", "laps"]).key == "laps"          # the most specific fit
    assert INP.core_for(["run_times"]).key == "run_times"
    with pytest.raises(ValueError, match="aren't read"):
        INP.core_for(["results", "laps"])                  # laps without a grid: only the results core fits
    with pytest.raises(ValueError, match="several cores"):
        INP.core_for(["results", "run_times"])
    with pytest.raises(ValueError, match="no engine core"):
        INP.core_for(["sectors"])
    with pytest.raises(ValueError, match="each one of"):
        INP.declared({"inputs": ["telemetry"]})
    assert INP.declared({"sessions": ["qual"], "best_lap": "race_fastest_lap"}) == ("results", "qualifying",
                                                                                     "fastest_lap")
    with pytest.raises(ValueError, match="lack"):
        G.GlobalModel.for_sport("motogp", core="laps")


def test_an_undeclared_optional_input_turns_its_setting_off(monkeypatch):
    real = sports.load

    def load(code):
        s = real(code)
        if code != "f1":
            return s
        m = dict(s["model"], inputs=["results", "qualifying", "grid", "laps"],
                 defaults={k: v for k, v in s["model"]["defaults"].items() if k not in ("practice_prior", "track_features")})
        return dict(s, model=m)
    monkeypatch.setattr(sports, "load", load)
    st = G.GlobalModel.for_sport("f1").Settings.from_dict()
    assert st["practice_prior"] is False and st["track_features"] is False


def test_the_results_level_of_a_lap_sport_is_the_old_global_model():
    """`--model global` on F1: finishing positions only, as GlobalModel.for_sport("f1") was before the one engine."""
    m = G.GlobalModel.for_sport("f1", core="results")
    assert m.core == "results" and m.name == "global_results" and m.inputs == ("results", "qualifying")
    assert m.cfg == dict(competition="f1_wdc", source="f1timing", group="team", prior=None)
    assert m.Settings.from_dict().key == G.GlobalSettings.from_dict().key


# --- settings: the schema's defaults are the engines' as they were -------------------------------------------------
def test_f1_and_downhill_defaults_live_in_the_schema_and_equal_the_code():
    from racinglines.models.inputs.run_times.settings import DHSettings
    for code, old in (("f1", SS.Settings), ("mtb_dh", DHSettings)):
        new = RM.model_class(code).Settings
        assert sports.load(code)["model"]["defaults"], code
        assert {s.name: s.default for s in new.SPEC} == {s.name: s.default for s in old.SPEC}, code
        assert new.from_dict().key == old.from_dict().key and new.from_dict().model_key == old.from_dict().model_key
        st = dict(sims=2000, half_life_days=90) if code == "f1" else dict(sims=300, prior_n=1.5)
        assert new.from_dict(st).key == old.from_dict(st).key
    assert RM.model_class("f1").Settings.from_dict().key == "c107835cbced"           # test_walk_forward's pins
    assert RM.model_class("f1").Settings.from_dict().model_key == "56f55ac79102"


# --- prices --------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def f1_data():
    from racinglines.models.inputs import laps_pricing as run
    from racinglines.testing import synthetic as SY
    res, laps, prof = SY.f1_frames(n_events=8)
    ev = sorted(res["event_id"].unique())
    return run.Measurements.from_frames(*SY.f1_sprint(res, laps, prof, [ev[-1], ev[-3]]))


@pytest.mark.parametrize("variant", ["baseline", "gridq+pretrain+reset"])
def test_f1_engine_prices_as_position_sim_and_price_race(f1_data, variant):
    from racinglines.markets import kinds as K
    from racinglines.models.inputs import laps_pricing as run
    eng, old = RM.get("f1"), RM.challenger("f1", "f1_sector_sim")()
    assert type(old) is RM.PositionSim
    data = eng.load(data=f1_data)
    st_e = eng.Settings.from_dict(dict(sims=1000, variant=variant))
    st_o = old.Settings.from_dict(dict(sims=1000, variant=variant))
    he, ho = eng.history(data, st_e), old.history(data, st_o)
    evs = eng.events(data, st_e)
    assert [e.id for e in evs] == [e.id for e in old.events(data, st_o)] and len(evs) >= 6
    for ev in evs[3:]:
        a = eng.price(he, ev, st_e, np.random.default_rng(11))
        same_sims(a, old.price(ho, ev, st_o, np.random.default_rng(11)))
        pd.testing.assert_frame_equal(eng.results(data, ev), old.results(data, ev))
        with st_e.applied():
            summ, _ = run.price_race(data, he.hist, ev.cutoff, ev.id, n_sims=1000, rng=np.random.default_rng(11))
        got = K.summary(a).set_index("athlete_id")
        np.testing.assert_array_equal(got["race_win"].to_numpy(), summ.set_index("athlete_id").loc[got.index, "win_prob"])
    assert any("sprint" in eng.price(he, ev, st_e, np.random.default_rng(1)).stage_rank for ev in evs[3:])


def test_downhill_engine_prices_as_timed_runs(tmp_path):
    from racinglines.sources.chronorace.parse import parse_markdown_tables_file
    from racinglines.testing import synthetic as SY
    for name, text in SY.mtb_results_md(n_events=5).items():
        (tmp_path / name).write_text(text)
    raw = pd.concat([pd.DataFrame(parse_markdown_tables_file(f)) for f in sorted(tmp_path.glob("*.md"))],
                    ignore_index=True)
    eng, old = RM.get("mtb_dh"), RM.challenger("mtb_dh", "timed_runs")()
    assert type(old) is RM.TimedRuns
    de, do = eng.load(data=raw), old.load(data=raw)
    pd.testing.assert_frame_equal(de, do)
    assert (de["round"] == "practice").any()                # the practice input keeps the timed training runs
    st_e, st_o = eng.Settings.from_dict(dict(sims=400)), old.Settings.from_dict(dict(sims=400))
    evs = eng.events(de, st_e)
    assert [e.id for e in evs] == [e.id for e in old.events(do, st_o)] and evs
    assert {e.info["stage"] for e in evs} == {"pre-event"}
    re_, ro = np.random.default_rng(7), np.random.default_rng(7)
    priced = 0
    for ev in evs:
        a = eng.price(eng.history(de, st_e), ev, st_e, re_)
        same_sims(a, old.price(old.history(do, st_o), ev, st_o, ro))
        priced += a is not None
        pd.testing.assert_frame_equal(eng.results(de, ev), old.results(do, ev))
    assert priced > 0


def _results(races=10, n=12, seed=4, start="2025-03-01", dnf=0.1):
    """`races` weekly races of entrants 1..n finishing in the order of a fixed strength + noise, some retiring."""
    rng = np.random.default_rng(seed)
    s = np.linspace(1.5, -1.5, n)
    rows = []
    for r in range(races):
        order = np.argsort(-(s + rng.normal(0, 0.6, n))) + 1
        date = pd.Timestamp(start) + pd.Timedelta(days=7 * r)
        for p, a in enumerate(order, 1):
            rows.append(dict(season=date.year, race=f"r{r}", name=f"Race {r}", date=date, athlete_id=int(a),
                             position=p, status="DNF" if rng.random() < dnf else "OK", team=f"t{(int(a) - 1) // 2}"))
    return pd.DataFrame(rows)


# Counts over 700 simulations of entrants 1..12, from origin/staging's GlobalModel.for_sport(sport) (2b7b410)
GOLDEN = {
    "win": [188, 107, 160, 72, 82, 31, 13, 17, 11, 8, 8, 3],
    "top3": [408, 320, 372, 261, 218, 154, 92, 88, 76, 61, 37, 13],
    "finished": [680, 633, 678, 687, 630, 678, 687, 588, 639, 626, 647, 686],
    "pole": [199, 108, 143, 77, 62, 45, 19, 14, 12, 12, 7, 2],
    "fastest_lap": [182, 134, 100, 98, 64, 58, 30, 12, 10, 8, 4, 0],
}


@pytest.mark.parametrize("code", ["nascar", "motogp"])
def test_results_sports_price_as_before_the_one_engine(code):
    m = RM.get(code)
    sides = {"qual": _results(seed=5)}
    if code == "nascar":
        sides["race_fastest_lap"] = _results(seed=6, dnf=0.0)
    data = m.load(data=_results(), sides=sides)
    st = m.Settings.from_dict(dict(sims=700))
    sims = m.price(m.history(data, st), Event(id="next", season=2025, cutoff=pd.Timestamp("2025-06-01"), name="next",
                                              info={}), st, np.random.default_rng(9))
    assert sims.entrants == list(range(1, 13))
    assert (sims.rank == 1).sum(axis=0).tolist() == GOLDEN["win"]
    assert (sims.rank <= 3).sum(axis=0).tolist() == GOLDEN["top3"]
    assert sims.finished.sum(axis=0).tolist() == GOLDEN["finished"]
    assert (sims.stage_rank["qual"] == 1).sum(axis=0).tolist() == GOLDEN["pole"]
    if code == "nascar":
        assert sims.indicators["race_fastest_lap"].sum(axis=0).tolist() == GOLDEN["fastest_lap"]
    else:
        assert sims.indicators == {}


def test_the_old_import_paths_are_the_new_modules():
    from racinglines.models import timed_runs
    from racinglines.models.inputs import laps, laps_pricing, run_times
    from racinglines.models.inputs.run_times import model as run_times_model
    from racinglines.models.position_sim import model, pricing
    from racinglines.models.timed_runs import model as timed_runs_model
    assert model is laps and pricing is laps_pricing and timed_runs_model is run_times_model
    assert timed_runs.fit_season_model is run_times.fit_season_model
