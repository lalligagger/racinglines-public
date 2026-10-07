"""The f1_combo Lab job (racinglines/web/jobs.py, models/position_sim/combo_job.py): registered with its knobs, legs
validated before queueing, names resolved by exact keys only, the calibration checks and flags, and the metrics it
stores. Synthetic data, no database."""

import json

import numpy as np
import pandas as pd
import pytest

from racinglines.models.outcomes import OutcomeSims
from racinglines.models.position_sim import combo_job as CJ
from racinglines.web import jobs as J

pytestmark = pytest.mark.quick

LEGS = [{"kind": "race_win", "driver": "Max Verstappen"}, {"kind": "race_fastest_lap", "driver": "Verstappen"}]


def _entrants():
    return pd.DataFrame(dict(athlete_id=[1, 2, 3, 4], driver=["Max Verstappen", "Lando Norris", "Oscar Piastri",
                                                              "Charles Leclerc"],
                             team_key=["red_bull", "mclaren", "mclaren", "ferrari"]))


def test_job_is_registered_and_builds_its_command():
    jt = J.CATALOG["f1_combo"]
    assert {k.name for k in jt.knobs} >= {"event", "cutoff", "legs", "variant", "sims"}
    variant = next(k for k in jt.knobs if k.name == "variant")
    assert variant.default == J.combo_variants()[0] and variant.default.endswith("flpos")
    p = J.parse(jt, {"event": "2026-17", "legs": json.dumps(LEGS)})
    assert p["cutoff"] == "now" and p["variant"] == variant.default and json.loads(p["legs"]) == LEGS
    argv = jt.argv(p, "/tmp/x.csv")
    assert argv[argv.index("--variant") + 1] == variant.default and "combo" in argv and "--save" in argv
    assert "--cutoff" not in argv and json.loads(argv[argv.index("--legs") + 1]) == LEGS
    p2 = J.parse(jt, {"event": "2026-17", "legs": json.dumps({"win+pole": LEGS}), "cutoff": "2026-10-09T08:00"})
    a2 = jt.argv(p2, "x")
    assert a2[a2.index("--cutoff") + 1] == "2026-10-09T08:00" and json.loads(p2["legs"]) == {"win+pole": LEGS}


@pytest.mark.parametrize("legs, msg", [("not json", "not JSON"), ("[]", "a list of legs"),
                                       (json.dumps(LEGS[:1]), "at least two legs"),
                                       (json.dumps([LEGS[0], {"kind": "race_safety_car"}]), "race_safety_car"),
                                       (json.dumps([LEGS[0], {"kind": "race_h2h", "driver": "x"}]), "needs pair")])
def test_bad_legs_are_rejected_before_queueing(legs, msg):
    with pytest.raises(ValueError, match=msg):
        J.parse(J.CATALOG["f1_combo"], {"event": "2026-17", "legs": legs})


def test_mcp_passes_legs_as_json():
    from racinglines.mcp import tools as T
    jt, p = T._job_params("f1_combo", {"event": "2026-17", "legs": LEGS})
    assert jt.code == "f1_combo" and json.loads(p["legs"]) == LEGS


def test_resolve_uses_exact_keys():
    e = _entrants()
    got = CJ.resolve([LEGS[0], {"kind": "race_h2h", "pair": ["norris", 3]},
                      {"kind": "race_constructor_top", "team": "McLaren"}], e)
    assert got[0]["athlete"] == 1 and "driver" not in got[0]
    assert got[1]["pair"] == [2, 3] and got[2]["team"] == "mclaren"
    with pytest.raises(ValueError, match="matches no entrant"):
        CJ.resolve([{"kind": "race_win", "driver": "Verstapen"}, LEGS[1]], e)
    with pytest.raises(ValueError, match="not one of"):
        CJ.resolve([{"kind": "race_constructor_top", "team": "mclaren racing"}, LEGS[0]], e)


def _sims(n_sims=1000, seed=0):
    """Pole and win independent (the pole-sitter wins about a quarter of the time); the fastest lap to the winner."""
    rng = np.random.default_rng(seed)
    rank = np.array([rng.permutation(4) + 1.0 for _ in range(n_sims)])
    qual = np.array([rng.permutation(4) + 1.0 for _ in range(n_sims)])
    return OutcomeSims(entrants=[1, 2, 3, 4], rank=rank, finished=np.ones((n_sims, 4), bool), stage_rank={"qual": qual},
                       indicators={"race_fastest_lap": rank == 1})


def test_checks_and_flags():
    s = _sims()
    rates = CJ.checks(s)
    assert rates["pole_sitter_wins"] == pytest.approx(0.25, abs=0.05) and rates["winner_sets_fastest_lap"] == 1.0
    win_pole = [{"kind": "race_win", "athlete": 1}, {"kind": "race_pole", "athlete": 1}]
    win_fl = [{"kind": "race_win", "athlete": 1}, {"kind": "race_fastest_lap", "athlete": 1}]
    m = CJ.combo_metrics([("wp", win_pole), ("wf", win_fl)], s, grid_known=False, names={1: "Max Verstappen"})
    wp, wf = m["combos"]
    assert wp["calibrated"] is False and wp["flags"][0]["check"] == "pole_sitter_wins"
    assert wp["flags"][0]["gap"] == pytest.approx(rates["pole_sitter_wins"] - 64 / 108, abs=1e-4)
    assert wf["calibrated"] is False and wf["flags"][0]["check"] == "winner_sets_fastest_lap"
    assert wp["legs"][0]["label"] == "Win: Max Verstappen" and wp["legs"][1]["marginal"] == pytest.approx(0.25, abs=0.05)
    assert m["checks"]["historical"]["pole_sitter_wins"]["2022-2026"] == dict(n=64, races=108, rate=0.5926)
    # after qualifying the pole leg is decided: no flag for it
    after = CJ.combo_metrics([("wp", win_pole)], s, grid_known=True)
    assert after["combos"][0]["calibrated"] is True
    json.dumps(m)                                                    # storable as JSON


def test_parse_combos_shapes():
    assert CJ.parse_combos(json.dumps(LEGS)) == [("combo 1", LEGS)]
    assert [n for n, _ in CJ.parse_combos(json.dumps([LEGS, LEGS]))] == ["combo 1", "combo 2"]
    assert CJ.parse_combos(json.dumps({"a": LEGS})) == [("a", LEGS)]


def test_run_prices_a_synthetic_event_end_to_end():
    from racinglines.models.position_sim import pricing as run
    from racinglines.models.position_sim import variants as V
    from racinglines.testing import synthetic as SY
    m = run.Measurements.from_frames(*SY.f1_frames())
    hist = run.history(m)
    eid = int(m.drivers["event_id"].max())
    row = m.res[m.res["event_id"] == eid].iloc[0]
    key = f"{int(row['year'])}-{int(row['series_round'])}"
    ent = run.entry_list(m, eid)
    a = ent["driver"].iloc[0]
    legs = {"win+fl": [{"kind": "race_win", "driver": a}, {"kind": "race_fastest_lap", "driver": a}],
            "win+pole+fl": [{"kind": "race_win", "driver": a}, {"kind": "race_pole", "driver": a},
                            {"kind": "race_fastest_lap", "driver": a}]}
    with V.use("flpos"):
        metrics, ex = CJ.run(m, hist, key, m.sessions(eid)["qual"] - pd.Timedelta(minutes=1), json.dumps(legs),
                             n_sims=2000)
    c = {x["name"]: x for x in metrics["combos"]}
    assert set(c) == set(legs) and all(0 <= x["fair"] <= 1 for x in c.values())
    assert c["win+fl"]["fair"] >= c["win+pole+fl"]["fair"]
    assert metrics["checks"]["grid_known"] is False and "winner_sets_fastest_lap" in metrics["checks"]["simulated"]
    json.dumps(metrics)
