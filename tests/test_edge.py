"""Edge Finder combo edits (racinglines/web/edge.py): pure list logic, no database."""

import pytest

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


def test_configs_and_scopes_filter_by_sport_and_venue(test_engine):
    """A sweep run's sport is params.sport (F1 when unset) and its venue the settings' venue (Polymarket when unset):
    the Edge Finder shows one sport at a time (F1 by default), and its choices list what has a sweep."""
    import json

    from sqlalchemy import text

    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    from racinglines.web import edge
    with get_session(test_engine.url.render_as_string(hide_password=False)) as s:
        seed(s)
        s.commit()
    weekends = json.dumps(dict(weekends=[dict(event_key="2099-01"), dict(event_key="2099-02")]))
    runs = [dict(year=2099, settings={}), dict(year=2099, settings={"venue": "kalshi"}),
            dict(year=2099, sport="nascar", settings={"venue": "kalshi", "min_edge": 0.07})]
    with test_engine.begin() as c:
        comp = c.execute(text("SELECT id FROM competitions WHERE code = 'f1_wdc'")).scalar()
        for p in runs:
            c.execute(text("""INSERT INTO model_runs (competition_id, model, kind, params, metrics)
                              VALUES (:c, 'test', 'sweep', CAST(:p AS jsonb), CAST(:m AS jsonb))"""),
                      dict(c=comp, p=json.dumps(p), m=weekends))
        assert edge.scopes(c, 2099) == (["f1", "nascar"], ["polymarket", "kalshi"])
        assert len(edge.configs(c, 2099)) == len(edge.configs(c, 2099, sport=None)) == 2
        assert {cf["settings"]["venue"] for cf in edge.configs(c, 2099, venue="kalshi").values()} == {"kalshi"}
        assert len(edge.configs(c, 2099, sport="f1")) == 2
        assert len(edge.configs(c, 2099, sport="nascar", venue="kalshi")) == 1
        assert edge.configs(c, 2099, sport="nascar", venue="polymarket") == {}
        c.execute(text("DELETE FROM model_runs WHERE (params->>'year')::int = 2099"))
