"""fantasy/follow.py: following a strategy, the one path behind /strategy/pick and the MCP tool fantasy_follow (owner,
2026-10-14). The quick tests need no database; the rest reuse test_strategy_pick's fixture on the test database."""

import pandas as pd
import pytest

from test_strategy_pick import _profile, app_db  # noqa: F401  (the fixture)

GP = dict(name="Test GP", race_start=pd.Timestamp("2026-10-11 12:00"))


@pytest.mark.quick
def test_sizing_snaps_to_its_step_and_refuses_with_the_pages_words():
    from racinglines.fantasy import follow as FW
    assert FW.check_sizing() == ("standard", 0.25)
    assert FW.check_sizing("kelly", 0.33) == ("kelly", 0.35) and FW.check_sizing("kelly", "0.5") == ("kelly", 0.5)
    for bad, words in ((("martingale", None), "pick Standard or Kelly sizing."),
                       (("kelly", 1.5), "between 10% and 100%"), (("kelly", "lots"), "must be a number")):
        with pytest.raises(FW.FollowError) as ex:
            FW.check_sizing(*bad)
        assert ex.value.reason == "bad_sizing" and words in ex.value.message
    assert issubclass(FW.FollowError, ValueError)                       # strategy_pick.sizing_of's callers catch it


@pytest.mark.quick
def test_tweaks_clamp_step_and_only_moved_settings_count():
    from racinglines.fantasy import follow as FW
    assert FW.adjusted("T1", {})[1] == {}
    settings, moved = FW.adjusted("T1", {"min_edge": 0.5, "min_volume_24h": 120, "max_stake": 999})
    assert moved == {"min_edge": 0.15, "min_volume_24h": 100.0}         # clamped, stepped; a non-slider ignored
    assert FW.adjusted("T1", {"min_edge": 0.10})[1] == {}               # the style's own value is no tweak


@pytest.fixture
def db(app_db, monkeypatch):  # noqa: F811
    from racinglines.fantasy import follow as FW
    monkeypatch.setattr(FW, "open_weekend", lambda now=None, schedule=None: None)
    monkeypatch.setenv("RACINGLINES_LAYOUT", "alpha")
    return app_db


def _user(name):
    from sqlalchemy import text

    from racinglines.db.config import get_engine
    from racinglines.web import layout as L
    from racinglines.web import roles as R
    with get_engine().connect() as c:
        r = c.execute(text("SELECT id, username, role FROM users WHERE username = :n"), dict(n=name)).mappings().one()
    return dict(id=r["id"], username=r["username"], role=L.role(R.canonical(r["role"])))


def _follow(name, code, **kw):
    from racinglines.db.config import get_engine
    from racinglines.fantasy import follow as FW
    with get_engine().begin() as c:
        return FW.follow(c, _user(name), code, **kw)


def _refused(name, code, **kw):
    from racinglines.fantasy import follow as FW
    with pytest.raises(FW.FollowError) as ex:
        _follow(name, code, **kw)
    return ex.value.reason


def test_follow_saves_a_style_with_its_sizing_and_tweaks_then_stops(db):
    p = _follow("ada", "T6", sizing="kelly", kelly=0.48)
    assert p == _profile("ada") and p["base"] == "T6" and p["name"] == "Big markets only" and p["candidate_id"]
    assert (p["sizing"], p["kelly"]) == ("kelly", 0.5) and "adjusted" not in p
    p = _follow("ada", "T1", tweaks={"min_edge": 0.5}, rolled=True)
    assert p["name"] == "Steady · adjusted" and p["adjusted"] == {"min_edge": 0.15} and p["rolled"] is True
    assert p["settings"]["min_edge"] == 0.15 and p["sizing"] == "standard"
    assert _follow("ada", "none") is None and _profile("ada") is None


def test_every_refusal_has_its_reason_and_writes_nothing(db, monkeypatch):
    from racinglines.fantasy import follow as FW
    from racinglines.web import demo
    _follow("ada", "T1")
    before = _profile("ada")
    assert _refused("ada", "T2", slot="nascar:kalshi") == "slot_not_open"
    assert _refused("ada", "T2", weekend=GP) == "weekend_locked"
    assert _refused("ada", "none", weekend=GP) == "weekend_locked"           # a stop waits for the window too
    with pytest.raises(FW.FollowError) as ex:
        _follow("ada", "T2", weekend=GP)
    assert ex.value.message == FW.lock_note(GP)                             # the page's own words
    assert _refused("ada", "T2", sizing="kelly", kelly=3) == "bad_sizing"
    assert _refused("ada", "T3") == "bad_code" and _refused("ada", "basic") == "bad_code"
    assert _profile("ada") == before
    monkeypatch.setattr(demo, "DEMO_USERS", ("ada",))
    assert _refused("ada", "T2") == "demo_account"
    monkeypatch.setenv("RACINGLINES_LAYOUT", "classic")                     # a basic account on the classic layout
    assert _refused("bea", "T1", alpha=True) == "not_allowed" and _profile("bea") is None


def test_admins_also_follow_the_classic_codes(db):
    from racinglines.db import config
    from racinglines.web import users as U
    with config.get_session() as s:
        U.create_user(s, "dee", "dee-password-1", "admin")
    assert _follow("dee", "T3", sizing="kelly", kelly=0.5)["base"] == "T3"
    assert "sizing" not in _profile("dee")                                  # sizing is for the five styles
    assert _follow("dee", "TB")["members"]
    assert _refused("cal", "TB") == "bad_code"


def test_current_shows_the_profile_and_the_lock(db, monkeypatch):
    from racinglines.db.config import get_engine
    from racinglines.fantasy import follow as FW
    with get_engine().connect() as c:
        assert FW.current(c, _user("ada"), weekend=None) == dict(profile=None, lock=None, demo=False)
    _follow("ada", "T1", sizing="kelly", kelly=0.5, tweaks={"min_volume_24h": 200})
    with get_engine().connect() as c:
        now = FW.current(c, _user("ada"), weekend=GP)
    assert now["profile"] == dict(base="T1", name="Steady · adjusted", sizing="kelly", kelly=0.5,
                                  adjusted={"min_volume_24h": 200.0}, rolled=False)
    assert now["lock"] == dict(weekend="Test GP", reopens="2026-10-12T12:00:00", message=FW.lock_note(GP))
    assert [o["code"] for o in FW.options(_user("ada"))] == ["T1", "T2", "T8", "T6", "T5"]


def test_a_style_with_a_pre_weekend_stage_saves_as_tuned_from_follow_and_the_page(db):
    """Fixed 2026-10-14: T2 and T5 (pre-weekend in their stages) followed with no tweak saved as "· adjusted" with the
    pre-weekend stage off, as the alpha drawer sends no pre-weekend field. Now they save as tuned, from either path."""
    import re

    from test_strategy_pick import _login

    from racinglines.pipelines import profiles as PF
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.web import roles as R
    stages = lambda st: SS.Settings.from_dict(st, strict=False)["taker_stages"]          # noqa: E731
    client, _, page = _login(db, "bea")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    for code in ("T2", "T5"):
        own = stages(PF.PROFILES[code]["settings"])
        assert "pre-weekend" in own, code
        client.post("/strategy/pick", data={"csrf_token": csrf, "code": code, "sizing": "standard"})
        for p in (_follow("ada", code), _profile("bea")):
            assert p["name"] == PF.ALPHA_STYLES[code]["label"] and not p.get("adjusted"), code
            assert stages(p["settings"]) == own and R.is_alpha_style(p), code
    assert _follow("ada", "T2", tweaks={"pre_weekend": False})["adjusted"] == {"pre_weekend": False}   # explicit: moves
