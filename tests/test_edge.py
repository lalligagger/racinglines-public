"""Edge Finder combo edits (racinglines/web/edge.py): pure list logic, no database."""

import pytest
import pandas as pd

from racinglines.web import edge as E

pytestmark = pytest.mark.quick


def test_default_is_baseline_with_every_strategy():
    assert E.apply([], "reset") == E.DEFAULT
    assert [s for _, s in E.DEFAULT] == E.STRATEGY_KEYS


def test_add_remove_toggle():
    cs = E.apply([], "add", "gridq+pretrain", "maker")
    assert cs == [("gridq+pretrain", "maker")]
    assert E.apply(cs, "add", "gridq+pretrain", "maker") == cs                   # no duplicates
    assert E.apply(cs, "toggle", "gridq+pretrain", "maker") == []
    assert E.apply([], "toggle", "reset", "hold") == [("reset", "hold")]
    assert E.apply(cs, "remove", "gridq+pretrain", "maker") == []


def test_add_model_and_strategy_follow_what_is_shown():
    cs = [("baseline", "maker"), ("baseline", "hold")]
    assert E.apply(cs, "add_model", "reset") == cs + [("reset", "maker"), ("reset", "hold")]
    assert E.apply([], "add_model", "reset") == [("reset", s) for s in E.STRATEGY_KEYS]
    assert E.apply(cs + [("reset", "maker")], "add_strategy", strategy="last") == \
        cs + [("reset", "maker"), ("baseline", "last"), ("reset", "last")]
    assert E.apply([], "add_strategy", strategy="last") == [("baseline", "last")]
    assert E.apply(cs + [("reset", "maker")], "remove_model", "baseline") == [("reset", "maker")]


@pytest.mark.parametrize("args", [("add", "nonsense", "maker"), ("add", "baseline", "nope"), ("add_model", "x+y"),
                                  ("add_strategy", "", "nope"), ("explode",)])
def test_rejects_unknown_models_strategies_and_actions(args):
    with pytest.raises(ValueError):
        E.apply([], *args)


def test_saved_strategy_history_is_cumulative_and_sorted_by_event_date():
    weekends = [
        dict(event_key="2025-02", round=2, update_pnl=12.0),
        dict(event_key="2025-01", round=1, update_pnl=-4.0),
        dict(event_key="2025-03", round=3, update_pnl=None),
    ]
    dates = {"2025-01": pd.Timestamp("2025-03-01"), "2025-02": pd.Timestamp("2025-02-01")}
    points, total = E.cumulative_curve(weekends, "update", dates)
    assert points == [(pd.Timestamp("2025-01-31 23:59:59"), 0.0),
                      (pd.Timestamp("2025-02-01"), 12.0), (pd.Timestamp("2025-03-01"), 8.0)]
    assert total == 8.0
    with pytest.raises(ValueError, match="no matching calendar date"):
        E.cumulative_curve(weekends, "update", {"2025-01": dates["2025-01"]})


def test_demo_pools_map_named_phases_and_t1_to_saved_sweeps(monkeypatch):
    from racinglines.pipelines import profiles as PF
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.pipelines import story

    settings = {
        "m2": SS.Settings.from_dict(PF.HISTORY_PROFILES["M2"]["settings"]),
        "c": SS.Settings.from_dict(PF.PROFILES["C"]["settings"]),
        "tw2": SS.Settings.from_dict(PF.HISTORY_PROFILES["TW2"]["settings"]),
        "t1": SS.Settings.from_dict(PF.TAKER_PROFILES["T1"]["settings"]),
    }
    ids = {"m2": 101, "c": 102, "tw2": 103, "t1": 104}
    by_year = {2025: {"m2": "m2", "tw2": "tw2"}, 2026: {"c": "c", "t1": "t1"}}

    def saved_configs(conn, year, sport, venue):
        assert sport == "f1" and venue == "polymarket"
        return {
            settings[name].key: dict(run_id=ids[name], label=settings[name].label())
            for name in by_year[year].values()
        }

    monkeypatch.setattr(E, "configs", saved_configs)

    def saved_decisions(conn, taker=False):
        codes = ["TW1", "TW2", "TW2", "TW2"] if taker else ["M1", "M3", "M3", "C"]
        return [
            dict(label=f"Decision {index}", known=(0, 8, 16, 99)[index],
                 candidates=(32 if taker else 20), table=[{}],
                 chosen=code,
                 chosen_settings=PF.HISTORY_PROFILES.get(code, PF.PROFILES.get(code))["settings"],
                 chosen_strategy=PF.HISTORY_PROFILES.get(code, PF.PROFILES.get(code))["strategy"])
            for index, code in enumerate(codes)
        ]

    monkeypatch.setattr(story, "decisions", saved_decisions)

    class Result:
        def all(self):
            return [
                (101, {"weekends": [{"round": r, "maker_pnl": 125.0 if r == 1 else 0.0} for r in range(1, 25)]}),
                (102, {"weekends": [{"round": r, "maker_pnl": 300.0 if r == 1 else 0.0} for r in range(1, 25)]}),
                (103, {"weekends": [{"round": r, "update_pnl": 50.0 if r == 1 else 0.0} for r in range(1, 25)]}),
                (104, {"weekends": [{"round": r, "update_pnl": 75.0 if r == 1 else 0.0} for r in range(1, 25)]}),
            ]

    class Connection:
        def execute(self, statement, params):
            assert set(params["ids"]) == set(ids.values())
            return Result()

    pools = E.demo_pools(Connection())
    maker, taker = pools
    assert maker["pool_size"] == 20 and taker["pool_size"] == 32
    m2 = next(row for row in maker["rows"] if any(p["code"] == "M2" for p in row["phases"]))
    c = next(row for row in maker["rows"] if any(p["code"] == "C" for p in row["phases"]))
    tw2 = next(row for row in taker["rows"] if any(p["code"] == "TW2" for p in row["phases"]))
    assert m2["results"][2025]["pnl"] == 125.0
    assert c["results"][2026]["pnl"] == 300.0
    assert tw2["results"][2025]["pnl"] == 50.0
    assert [p["period"] for p in tw2["phases"]] == ["2025 · round 9–season end", "2026 · round 1–season end"]
    assert taker["reference"]["name"].startswith("T1")
    assert taker["reference"]["results"][2026]["pnl"] == 75.0
    assert maker["decision_checks"][1]["history_matches"] is None
    assert maker["decision_checks"][1]["pool_complete"] is False
    assert taker["decision_checks"][1]["history_matches"] is None

    from racinglines.web.app import templates
    html = templates.env.get_template("lab_edge.html").render(
        combos=[], years=[2026, 2025], year=2026, sports=["f1"], sport="f1", sport_names={"f1": "Formula 1"},
        venues=["polymarket"], venue="polymarket", venue_names={"polymarket": "Polymarket"},
        sweep_job="f1_sweep", models=[], strategies=[], candidates=[], demo_pools=pools,
        ef=dict(n_weekends=0, benchmark=None, cards=[], missing=[], recaps=[], columns=[], detail=None))
    assert "F1 demo strategy history and pools" in html
    assert "M2 · 2025" in html and "C · 2026" in html and "TW2 · 2025" in html
    assert "T1/A" in html and "run #104" in html


def test_configs_and_scopes_filter_by_sport_and_venue(test_engine):
    """A sweep run's sport is params.sport (F1 when unset) and its venue the settings' venue (Polymarket when unset):
    the Edge Finder shows one sport at a time (F1 by default), and its choices list what has a sweep."""
    import json

    from sqlalchemy import text

    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    from racinglines.pipelines import season_sweep as SW
    from racinglines.web import edge
    with get_session(test_engine.url.render_as_string(hide_password=False)) as s:
        seed(s)
        s.commit()
    weekends = json.dumps(dict(weekends=[dict(event_key="2099-01"), dict(event_key="2099-02")]))
    nascar_settings = SW.settings_class("nascar").from_dict({"venue": "kalshi", "prior_weight": 4.0})
    runs = [dict(year=2099, settings={}), dict(year=2099, settings={"venue": "kalshi"}),
            dict(year=2099, sport="nascar", venue="kalshi", settings=nascar_settings.to_json(),
                 settings_key=nascar_settings.key)]
    with test_engine.begin() as c:
        comp = c.execute(text("SELECT id FROM competitions WHERE code = 'f1_wdc'")).scalar()
        for p in runs:
            c.execute(text("""INSERT INTO model_runs (competition_id, model, kind, params, metrics)
                              VALUES (:c, 'test', 'sweep', CAST(:p AS jsonb), CAST(:m AS jsonb))"""),
                      dict(c=comp, p=json.dumps(p), m=weekends))
        assert edge.scopes(c, 2099) == (["f1", "nascar"], ["polymarket", "kalshi"])
        assert len(edge.configs(c, 2099)) == len(edge.configs(c, 2099, sport=None)) == 2
        assert {cf["venue"] for cf in edge.configs(c, 2099, venue="kalshi").values()} == {"kalshi"}
        assert len(edge.configs(c, 2099, sport="f1")) == 2
        nascar = edge.configs(c, 2099, sport="nascar", venue="kalshi")
        assert len(nascar) == 1 and next(iter(nascar.values()))["settings"]["prior_weight"] == 4.0
        assert edge.configs(c, 2099, sport="nascar", venue="polymarket") == {}
        c.execute(text("DELETE FROM model_runs WHERE (params->>'year')::int = 2099"))
