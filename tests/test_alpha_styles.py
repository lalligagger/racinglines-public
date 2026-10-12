"""/strategy/pick under the alpha layout (web/strategy_pick.py alpha_picker; owner, 2026-10-12 19:23-19:55Z): five
styles by name (profiles.ALPHA_STYLES), a sizing choice, and a two-slider tweak drawer. The quick tests need no
database; the rest reuse test_strategy_pick's fixture on the test database."""

import re

import pytest

from test_strategy_pick import _login, _profile, app_db  # noqa: F401  (the fixture)


@pytest.mark.quick
def test_alpha_styles_are_five_validated_takers_with_their_backtests_copied_exactly():
    from racinglines.pipelines import profiles as PF
    assert PF.ALPHA_ORDER == ("T1", "T2", "T8", "T6", "T5") and set(PF.ALPHA_ORDER) == set(PF.ALPHA_STYLES)
    assert [PF.ALPHA_STYLES[c]["label"] for c in PF.ALPHA_ORDER] == \
        ["Steady", "Head start", "Early bird", "Big markets only", "Hair trigger"]
    for code, st in PF.ALPHA_STYLES.items():
        why = PF.PROFILES[code]["why"]
        y26, y25 = st["backtest"]
        assert f"2026 +{y26:,}" in why and f"2025 +{y25:,}" in why, code      # never invented: the `why` line's own
        assert not PF.is_maker(PF.PROFILES[code]) and not PF.is_combo(PF.PROFILES[code])
    assert [c for c, st in PF.ALPHA_STYLES.items() if st.get("in_sample")] == ["T8"]


@pytest.mark.quick
def test_sizing_is_validated_and_the_kelly_tiers_cover_every_step():
    from racinglines.web import strategy_pick as SP
    assert SP.sizing_of({}) == ("standard", 0.25)
    assert SP.sizing_of({"sizing": "kelly", "kelly": "0.5"}) == ("kelly", 0.5)
    for bad in ({"sizing": "martingale"}, {"sizing": "kelly", "kelly": "1.5"}, {"sizing": "kelly", "kelly": "0.05"},
                {"sizing": "kelly", "kelly": "lots"}):
        with pytest.raises(ValueError):
            SP.sizing_of(bad)
    tiers = [SP.kelly_label(i / 20) for i in range(2, 21)]
    assert [t.split()[0] for t in tiers] == ["Nitty"] * 4 + ["Shark"] * 5 + ["Spicy"] * 6 + ["Degen"] * 4
    assert [SP.kelly_label(f).split()[0] for _, f in SP.KELLY_PICKS] == ["Nitty", "Shark", "Degen"]


@pytest.fixture
def alpha(monkeypatch):
    monkeypatch.setenv("RACINGLINES_LAYOUT", "alpha")


def _post(client, csrf, **data):
    return client.post("/strategy/pick", data={"csrf_token": csrf, **data}, follow_redirects=False)


def test_the_alpha_picker_shows_the_five_styles_by_name_and_no_codes(app_db, alpha):  # noqa: F811
    from markupsafe import escape

    from racinglines.pipelines import profiles as PF
    from racinglines.web import roles as R
    for who in ("ada", "bea"):
        client, csrf, page = _login(app_db, who)
        labels = re.findall(r'<div class="style-card[^"]*">\s*<h3>([^<]+?)\s*(?:<|$)', page)
        assert labels == [PF.ALPHA_STYLES[c]["label"] for c in PF.ALPHA_ORDER], who
        body = page.split('<form method="post" action="/strategy/pick"', 1)[1]
        visible = re.sub(r"<[^>]+>", " ", body)                       # what a user reads, not attribute values
        assert not re.search(r"\bT\d+\b|\bTB\b", visible), who
        assert not any(str(escape(PF.PROFILES[c]["why"])) in page for c in PF.PROFILES)
        assert "backtest, season P&amp;L at our standard sizing" in page and "2026 +1,376" in page
        assert "in-sample: tuned on the same seasons it" in page
        assert "untested for this strategy" in page and "Kelly sizes each bet by how big the edge is" in page
        assert "above half Kelly" not in page.lower()                  # owner, 19:54Z: no swing warning
        assert R.BASIC_NAME not in page and 'value="C"' not in page


def test_the_tweak_drawer_has_exactly_two_sliders_closed_for_everyone(app_db, alpha):  # noqa: F811
    page = _login(app_db, "ada")[2]
    drawer = re.search(r"<details class=\"pick-tweak\" data-tweak>(.*?)</details>", page, re.S)
    assert drawer, "a closed <details> drawer"
    names = re.findall(r'<input type="range" name="([^"]+)"', drawer.group(1))
    assert names == ["tweak:min_edge", "tweak:min_volume_24h"] and "data-roll" in drawer.group(1)
    assert "untested: scored live from the next race weekend" in drawer.group(1)
    assert "pick-tweak" in _login(app_db, "bea")[2]                     # one user level: basic gets it too (21:04Z)


def test_alpha_refuses_codes_outside_the_five_except_for_admins(app_db, alpha):  # noqa: F811
    from racinglines.db import config
    from racinglines.web import users as U
    client, csrf, _ = _login(app_db, "ada")
    for code in ("T3", "C", "TB", "basic"):
        r = _post(client, csrf, code=code)
        assert "Error" in r.headers["location"] and _profile("ada") is None, code
    with config.get_session() as s:
        U.create_user(s, "dee", "dee-password-1", "admin")
    client, csrf, _ = _login(app_db, "dee")
    r = _post(client, csrf, code="T3")
    assert "Error" not in r.headers["location"] and _profile("dee")["base"] == "T3"


def test_basic_and_pro_follow_a_style_by_name_with_their_sizing(app_db, alpha):  # noqa: F811
    for who in ("bea", "ada"):
        client, csrf, _ = _login(app_db, who)
        r = _post(client, csrf, code="T6", sizing="kelly", kelly="0.5")
        assert r.status_code == 303 and "Error" not in r.headers["location"], who
        p = _profile(who)
        assert p["base"] == "T6" and p["name"] == "Big markets only" and p["candidate_id"]
        assert p["sizing"] == "kelly" and p["kelly"] == 0.5 and p["settings"]["min_volume_24h"] == 200
        page = client.get("/strategy/pick").text
        assert "Following now: <b>Big markets only</b>" in page and "Shark" in page
    client, csrf, _ = _login(app_db, "ada")
    r = _post(client, csrf, code="T1", sizing="kelly", kelly="3")
    assert "Error" in r.headers["location"] and _profile("ada")["base"] == "T6"     # refused, nothing saved
    _post(client, csrf, code="T1")
    assert _profile("ada")["sizing"] == "standard"


def test_tweaks_are_saved_for_basic_and_pro_alike(app_db, alpha):  # noqa: F811
    client, csrf, _ = _login(app_db, "bea")
    _post(client, csrf, code="T1", **{"tweak:min_edge": "0.15", "tweak_from:min_edge": "0.10"})
    assert _profile("bea")["adjusted"] == {"min_edge": 0.15}           # basic runs as pro under the alpha layout
    client, csrf, _ = _login(app_db, "ada")
    _post(client, csrf, code="T1", **{"tweak:min_edge": "0.12", "tweak_from:min_edge": "0.10",
                                     "tweak:min_volume_24h": "0", "tweak_from:min_volume_24h": "0"})
    p = _profile("ada")
    assert p["name"] == "Steady · adjusted" and p["adjusted"] == {"min_edge": 0.12}
    page = client.get("/strategy/pick").text
    assert "12 pts" in page and '<span class="pill no" data-untested>' in page   # shown as untested


def test_the_alpha_strategy_page_drops_the_how_it_chooses_tab(app_db, monkeypatch):  # noqa: F811
    client, csrf, _ = _login(app_db, "ada")
    _post(client, csrf, code="T1")
    monkeypatch.setenv("RACINGLINES_LAYOUT", "alpha")
    page = client.get("/strategy").text
    assert 'data-tab="how"' not in page and 'name="sport"' not in page
    assert "Fantasy P&amp;L" in page                                     # the hero KPIs stay


def test_basic_runs_as_pro_only_under_the_alpha_layout(monkeypatch):
    from racinglines.web import layout
    monkeypatch.setenv("RACINGLINES_LAYOUT", "alpha")
    assert (layout.role("basic"), layout.role("pro"), layout.role("admin")) == ("pro", "pro", "admin")
    monkeypatch.setenv("RACINGLINES_LAYOUT", "classic")
    assert layout.role("basic") == "basic"
