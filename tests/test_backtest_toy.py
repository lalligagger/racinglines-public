"""The backtest core carries a new sport without changes (docs/backtest-core.md, step 6): a synthetic third
sport (tests/toy_backtest.py: its data source and pricing model) plus its schema runs through the pricing
model registry, the walk-forward engine, the market kinds, the generic CLI, the search queue and the search
report. Everything synthetic; no network, no database."""

import json

import numpy as np
import pytest

from racinglines import sports
from racinglines.core import walk_forward as WF
from racinglines.models import race_model as RM
from racinglines.pipelines import search as S
from racinglines.pipelines import search_report as R

pytestmark = pytest.mark.quick

SCHEMA = """
[sport]
code = "toy_race"
name = "Toy race"
result_kind = "time"
model_family = "toy"
display_order = 9
pricing_model = "toy_backtest:ToyRace"

[competition]
code = "toy_cup"
name = "Toy Cup"
"""


@pytest.fixture
def toy(tmp_path, monkeypatch):
    (tmp_path / "sports").mkdir()
    for f in sports.SCHEMAS.glob("*.toml"):
        (tmp_path / "sports" / f.name).write_text(f.read_text())
    (tmp_path / "sports" / "toy_race.toml").write_text(SCHEMA)
    monkeypatch.setattr(sports, "SCHEMAS", tmp_path / "sports")
    sports.load.cache_clear()
    yield tmp_path
    sports.load.cache_clear()


def test_the_schema_names_the_pricing_model(toy):
    m = RM.get("toy_race")
    assert m.sport == "toy_race" and RM.get("mtb_dh").sport == "mtb_dh" and RM.get("f1").sport == "f1"
    with pytest.raises(ValueError, match="pricing_model"):
        RM.get("curling")


def test_a_third_sport_runs_through_the_engine(toy):
    m = RM.get("toy_race")
    data = m.load()
    st = m.Settings.from_dict(dict(seed=4))
    out = WF.run(m, data, st, kinds=["race_win", "race_podium", "race_top10", "race_h2h"], echo=lambda s: None)
    assert len(out["events"]) == 12 and set(out["events"]["season"]) == {2025, 2026}
    cal = out["calibration"].set_index(["kind", "season"])
    assert cal.loc[("race_win", "all"), "n"] == 12 * 12 and cal.loc[("race_h2h", "all"), "n"] == 12 * 66
    # a model that learns form beats a coin: the uniform win forecast (1/12) scores 11/144 on Brier
    assert cal.loc[("race_win", "all"), "brier"] < 11 / 144
    assert cal.loc[("race_h2h", "all"), "brier"] < 0.25
    rows = out["rows"]
    assert rows.loc[rows["kind"] == "race_win"].groupby("event_id")["y"].sum().eq(1).all()      # one winner a race
    w = WF.saved_metrics(out)["weekends"]
    assert len(w) == 12 and all(x["race_win_score"] < 0 for x in w)


def test_the_generic_cli_runs_a_new_sport(toy, capsys):
    from racinglines.cli import main
    assert main(["backtest", "walk-forward", "toy_race", "--seasons", "2026", "--shrink", "1",
                 "--out-dir", str(toy / "wf")]) == 0
    assert "Walk-forward toy_race 2026 · shrink=1.0" in capsys.readouterr().out
    assert (toy / "wf" / "walk_forward_calibration.csv").exists()


def test_the_search_queue_and_report_take_the_new_sport(toy):
    q = toy / "q.toml"
    q.write_text('[search]\nname = "toy"\n[[job]]\nsport = "toy_race"\nyear = 2026\nshrink = 0.5\nreplicates = 3\n'
                 '[[job]]\nsport = "toy_race"\nyear = 2025\nshrink = 0.5\n')
    _, jobs, _ = S.load(q)
    assert {j["kind"] for j in jobs} == {"walk_forward"} and len(jobs) == 3 + 3 + 1 + 1      # replicates + baselines
    assert S.argv(jobs[0])[3:6] == ["backtest", "walk-forward", "toy_race"]
    # run each job in-process, as its command line would, and report
    m = RM.get("toy_race")
    data = m.load()
    metrics = {}
    for i, j in enumerate(jobs, 1):
        st = m.Settings.from_dict(j["settings"])
        metrics[i] = WF.saved_metrics(WF.run(m, data, st, seasons=[j["year"]], echo=lambda s: None))
        j.update(run_id=i)
    strategies = [("race_win", "Win"), ("race_podium", "Podium")]
    rows, ranking = R.write(toy, jobs, metrics, strategies, dict(R.SPORT_DEFAULTS.get("toy_race", {}), value="score",
                                                                    unit="score", target=2026, holdout=[2025]),
                            cls=m.Settings, sport="toy_race", rerun=S.argv, echo=lambda s: None)
    assert {r["verdict"] for r in ranking} <= {"baseline", "robust", "target only", "held-out-led", "not better"}
    shrunk = [r for r in ranking if r["label_settings"] == "shrink=0.5"]
    assert len(shrunk) == 2 and all(r["replicates"] == 3 for r in shrunk)
    floor, measured = R.noise_floor(rows)
    assert measured["model"] > 0                                                   # from the seed replicates
    assert json.loads((toy / "pnl_curves.json").read_text()) and (toy / "report.md").exists()
    assert np.isfinite([r["vs_base_target"] for r in shrunk]).all()
