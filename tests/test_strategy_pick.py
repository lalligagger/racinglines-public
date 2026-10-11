"""/strategy/pick (web/strategy_pick.py): an account picks its own strategy; nothing runs until it does (owner,
2026-10-11). The first test needs no database; the rest run on the test database."""

import re

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape


@pytest.mark.quick
def test_sliders_clamp_and_only_moved_settings_count():
    from racinglines.web import strategy_pick as SP
    settings, moved = SP._adjusted("T1", {})
    assert moved == {}                                                  # untouched: the strategy as tuned
    settings, moved = SP._adjusted("T1", {"T1:min_edge": "0.5", "T1:min_volume_24h": "120", "T1:pre_weekend": "1",
                                          "T2:min_edge": "0.04"})
    assert moved == {"min_edge": 0.2, "min_volume_24h": 100.0, "pre_weekend": True}   # clamped, stepped; T2's ignored
    assert settings["taker_stages"][0] == "pre-weekend" and settings["min_edge_h2h"] == 0.05
    settings, moved = SP._adjusted("C", {"C:max_disagree": "0.08"})
    assert moved == {"max_disagree": 0.08}


@pytest.fixture
def app_db(test_engine, monkeypatch):
    from sqlalchemy import text

    from racinglines.db import config
    from racinglines.web import app as A
    from racinglines.web import users as U
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM users"))
        c.execute(text("INSERT INTO sports (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
        c.execute(text("INSERT INTO leagues (code, name) VALUES ('f1', 'F1') ON CONFLICT DO NOTHING"))
        c.execute(text("""INSERT INTO competitions (code, name, league_id, sport_id)
                          SELECT 'f1_wdc', 'F1', l.id, s.id FROM leagues l, sports s WHERE l.code = 'f1' AND s.code = 'f1'
                          ON CONFLICT DO NOTHING"""))
    monkeypatch.setenv("DATABASE_URL", test_engine.url.render_as_string(hide_password=False))
    config.get_engine.cache_clear()
    with config.get_session() as s:
        U.create_user(s, "ada", "ada-password-1", "pro")
        U.create_user(s, "bea", "bea-password-1", "basic")
    yield A
    config.get_engine.cache_clear()


def _login(A, name):
    client = TestClient(A.app)
    assert client.post("/login", data=dict(username=name, password=f"{name}-password-1"),
                       follow_redirects=False).status_code == 303
    page = client.get("/strategy/pick").text
    return client, re.search(r'name="csrf_token" value="([^"]+)"', page).group(1), page


def _profile(name):
    from sqlalchemy import text

    from racinglines.db.config import get_engine
    from racinglines.pipelines import profiles as PF
    with get_engine().connect() as c:
        return PF.of_user(c, c.execute(text("SELECT id FROM users WHERE username = :n"), dict(n=name)).scalar())


def test_a_pro_account_starts_empty_then_picks_and_tunes(app_db):
    from racinglines.pipelines import profiles as PF
    client, csrf, page = _login(app_db, "ada")
    assert "nothing yet" in page and all(str(escape(PF.PROFILES[c]["name"])) in page for c in PF.TAKER_TOP)
    assert 'value="T7" checked' in page                                 # the shortlist's first is preselected
    assert "Pick a strategy" in client.get("/strategy").text            # empty states point at the picker
    assert "/strategy/pick" in client.get("/positions").text
    r = client.post("/strategy/pick", data={"csrf_token": csrf, "code": "T1", "T1:min_edge": "0.12"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/strategy?msg=Now%20running")
    p = _profile("ada")
    assert p["name"] == "T1 · update, core (A's settings) · adjusted" and p["base"] == "T1"
    assert p["settings"]["min_edge"] == 0.12 and p["adjusted"] == {"min_edge": 0.12} and p["candidate_id"]
    page = client.get("/strategy/pick").text
    assert 'value="T1" checked' in page and "12 pts" in page            # back where the user left it
    client.post("/strategy/pick", data={"csrf_token": csrf, "code": "TB"})
    assert _profile("ada")["members"]                                    # a blend runs as tuned
    client.post("/strategy/pick", data={"csrf_token": csrf, "code": "none"})
    assert _profile("ada") is None


def test_a_basic_account_runs_only_its_own_picks(app_db):
    from racinglines.web import roles as R
    client, csrf, page = _login(app_db, "bea")
    assert R.BASIC_NAME in page and "T7 ·" not in page
    r = client.post("/strategy/pick", data={"csrf_token": csrf, "code": "T7"}, follow_redirects=False)
    assert "Error" in r.headers["location"] and _profile("bea") is None
    client.post("/strategy/pick", data={"csrf_token": csrf, "code": "basic"})
    assert _profile("bea")["name"] == R.BASIC_NAME


def test_the_demo_accounts_keep_their_strategy(app_db, monkeypatch):
    from racinglines.web import demo
    monkeypatch.setattr(demo, "DEMO_USERS", ("ada",))
    client, csrf, page = _login(app_db, "ada")
    assert "read-only" in page
    r = client.post("/strategy/pick", data={"csrf_token": csrf, "code": "T1"}, follow_redirects=False)
    assert "demo" in r.headers["location"] and _profile("ada") is None     # the demo guard, or the page's own
