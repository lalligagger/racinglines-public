"""[sport] audience (owner, 2026-10-11, MotoGP "Hide for Alpha"; MotoGP shown again 2026-10-14): one schema key keeps a
sport off every user page while admins, recording, pricing and the CLI keep it. Flipping the key back to "all" shows it
again. The page tests hide MotoGP through the key (`motogp_hidden`): it is the sport with events, jobs and books to hide."""

import re
from datetime import date

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from racinglines import sports as SP
from racinglines.web import audience as A

ADMIN, PRO = dict(id=1, username="boss", role="admin"), dict(id=2, username="ada", role="pro")


@pytest.fixture
def motogp_hidden(monkeypatch):
    """MotoGP's schema with audience = "admin", as it was for the Alpha from 2026-10-11 to 2026-10-14."""
    real = SP.load
    monkeypatch.setattr(SP, "load", lambda code: dict(real(code), sport=dict(real(code)["sport"], audience="admin"))
                        if code == "motogp" else real(code))


@pytest.mark.quick
def test_motogp_is_shown_to_alpha_users_again():
    # owner, 2026-10-14 00:27Z (data-terms review v0.2, question 3): MotoGP results and prices may reach Alpha users
    assert SP.audience("motogp") == "all" and SP.admin_only() == {"road_cycling"}
    assert A.shown(PRO, "motogp") and A.shown(PRO, "motogp_wc") and A.shown(None, "motogp_wc")


@pytest.mark.quick
def test_the_schema_key_decides_and_admins_see_everything(motogp_hidden):
    assert SP.audience("motogp") == "admin" and SP.audience("f1") == "all" and SP.audience("nascar") == "all"
    assert SP.admin_only() == {"motogp", "road_cycling"}             # road cycling: PCS terms review (2026-10-12)
    assert SP.admin_only_competitions() == {"motogp_wc", "uci_road_wt"}
    assert A.hidden(ADMIN) == set() and A.hidden_comps(ADMIN) == set()
    for user in (PRO, None):                                      # a user, or nobody signed in
        assert A.hidden(user) == {"motogp", "road_cycling"} and not A.shown(user, "motogp") and not A.shown(user, "motogp_wc")
        assert A.shown(user, "f1") and A.shown(user, "f1_wdc") and A.shown(user, "") and A.shown(user, None)
        with pytest.raises(HTTPException):
            A.guard(user, "motogp_wc")
    A.guard(ADMIN, "motogp_wc")
    # the one gate the MCP tools share: None is an internal caller (CLI, stdio MCP), not a visitor
    assert SP.is_public("motogp", None) and SP.is_public("motogp_wc", ADMIN) and SP.is_public("f1", PRO)
    assert not SP.is_public("motogp", PRO) and not SP.is_public("motogp_wc", {}) and SP.is_public("unknown", PRO)


@pytest.mark.quick
def test_flipping_the_key_back_shows_the_sport_again(monkeypatch):
    real = SP.load

    def load(code):
        s = real(code)
        return dict(s, sport={k: v for k, v in s["sport"].items() if k != "audience"}) if code == "road_cycling" else s
    monkeypatch.setattr(SP, "load", load)
    assert SP.audience("road_cycling") == "all" and SP.admin_only() == frozenset() and A.shown(PRO, "uci_road_wt")
    monkeypatch.setattr(SP, "load", lambda code: dict(real(code), sport=dict(real(code)["sport"], audience="nobody")))
    with pytest.raises(ValueError):
        SP.audience("f1")


@pytest.mark.quick
def test_the_landing_page_leaves_a_hidden_sport_out(motogp_hidden):
    from racinglines.web import app as WA
    page = TestClient(WA.app).get("/").text
    assert "Formula 1 · NASCAR Cup · UCI downhill" in page and "MotoGP" not in page


@pytest.fixture
def site(test_engine, monkeypatch, motogp_hidden):
    """The web app on the test database: the registry seeded, one MotoGP and one F1 event, an admin and a pro."""
    from sqlalchemy import text

    from racinglines.db import config, ingest
    from racinglines.web import app as WA
    from racinglines.web import users as U
    monkeypatch.setenv("DATABASE_URL", test_engine.url.render_as_string(hide_password=False))
    config.get_engine.cache_clear()
    ids = {}
    with config.get_session() as s:
        ingest.seed(s)
        s.commit()
        for name, role in (("aud_boss", "admin"), ("aud_ada", "pro")):
            if not s.execute(text("SELECT 1 FROM users WHERE username = :u"), dict(u=name)).first():
                U.create_user(s, name, "audience-password-1", role)
    with config.get_engine().begin() as c:
        for comp, key in (("motogp_wc", "aud-motogp-1"), ("f1_wdc", "aud-f1-1")):
            cid = c.execute(text("SELECT id FROM competitions WHERE code = :c"), dict(c=comp)).scalar()
            sid = c.execute(text("""INSERT INTO seasons (competition_id, year) VALUES (:c, 2026)
                                    ON CONFLICT (competition_id, year) DO UPDATE SET year = 2026 RETURNING id"""),
                            dict(c=cid)).scalar()
            ids[comp] = c.execute(text("""INSERT INTO events (season_id, source, source_key, name, start_date, status)
                                          VALUES (:s, 'test', :k, :n, :d, 'completed')
                                          ON CONFLICT (season_id, source, source_key) DO UPDATE SET name = :n RETURNING id"""),
                                  dict(s=sid, k=key, n=key, d=date(2026, 9, 1))).scalar()
    clients = {}
    for name in ("aud_boss", "aud_ada"):
        cl = TestClient(WA.app)
        assert cl.post("/login", data=dict(username=name, password="audience-password-1"),
                       follow_redirects=False).status_code == 303
        clients[name] = cl
    yield clients["aud_boss"], clients["aud_ada"], ids
    config.get_engine.cache_clear()


def test_a_hidden_sports_pages_are_404_for_users_and_open_for_admins(site):
    boss, ada, ids = site
    for url in (f"/events/{ids['motogp_wc']}", "/markets/sport/motogp_wc", "/markets/sport/motogp_wc/recent",
                "/seasons/motogp_wc"):
        assert ada.get(url).status_code == 404, url
    assert boss.get(f"/events/{ids['motogp_wc']}").status_code == 200
    assert ada.get(f"/events/{ids['f1_wdc']}").status_code == 200       # other sports as before
    assert boss.get("/markets/sport/motogp_wc/recent").status_code == 200


def test_settings_and_the_lab_leave_a_hidden_sport_out_for_users(site):
    boss, ada, _ = site
    assert 'value="motogp"' not in ada.get("/settings").text and 'value="motogp"' in boss.get("/settings").text
    run_user, run_admin = ada.get("/lab/section/run").text, boss.get("/lab/section/run").text
    assert "motogp_sweep" not in run_user and "motogp_sweep" in run_admin
    assert not re.search(r"<option[^>]*>motogp</option>", run_user)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', run_user).group(1)
    r = ada.post("/lab/run", data=dict(csrf_token=csrf, job="motogp_sweep"), follow_redirects=False)
    assert r.status_code == 400                                         # nor can a user launch its jobs


def test_the_board_leaves_hidden_competitions_out(site, test_engine, monkeypatch):
    from racinglines.db import reads as data
    from racinglines.web import board as B
    runs = pd.DataFrame([dict(id=1, competition="f1_wdc"), dict(id=2, competition="motogp_wc")])
    monkeypatch.setattr(data, "latest_forecasts", lambda conn: runs)
    with test_engine.connect() as c:
        every = [s["code"] for s in B.board(c, 0, detail=False)]
        shown = [s["code"] for s in B.board(c, 0, detail=False, hide=A.hidden_comps(PRO))]
    assert "motogp_wc" in every and "f1_wdc" in every
    assert "motogp_wc" not in shown and "f1_wdc" in shown


def test_lab_jobs_and_book_quotes_leave_a_hidden_sport_out_for_users(site, test_engine):
    """Core review of #132: a MotoGP job's log tail (P&L) in Lab Jobs scope=all, and MotoGP races in /book/quotes."""
    from sqlalchemy import text
    boss, ada, _ = site
    races = {}
    with test_engine.begin() as c:
        for comp, key, sport in (("motogp_wc", "aud-motogp-next", "motogp"), ("f1_wdc", "aud-f1-next", "f1")):
            cid = c.execute(text("SELECT id FROM competitions WHERE code = :c"), dict(c=comp)).scalar()
            sid = c.execute(text("SELECT id FROM seasons WHERE competition_id = :c AND year = 2026"), dict(c=cid)).scalar()
            cat = c.execute(text("SELECT id FROM categories WHERE competition_id = :c ORDER BY id LIMIT 1"),
                            dict(c=cid)).scalar()
            eid = c.execute(text("""INSERT INTO events (season_id, source, source_key, name, start_date, status)
                                    VALUES (:s, 'test', :k, :n, :d, 'scheduled')
                                    ON CONFLICT (season_id, source, source_key) DO UPDATE SET status = 'scheduled'
                                    RETURNING id"""), dict(s=sid, k=key, n=key, d=date(2026, 12, 1))).scalar()
            races[comp] = c.execute(text("""INSERT INTO races (event_id, category_id) VALUES (:e, :c)
                                            ON CONFLICT (event_id, category_id) DO UPDATE SET event_id = :e
                                            RETURNING id"""), dict(e=eid, c=cat)).scalar()
            c.execute(text("""INSERT INTO jobs (user_id, kind, sport, status, log)
                              SELECT id, :k, :s, 'done', :log FROM users WHERE username = 'aud_boss'"""),
                      dict(k=f"{sport}_sweep", s=sport, log=f"aud-log-{sport}"))
    jobs_user, jobs_admin = ada.get("/lab/section/jobs?scope=all").text, boss.get("/lab/section/jobs?scope=all").text
    assert "aud-log-motogp" not in jobs_user and "aud-log-f1" in jobs_user
    assert "aud-log-motogp" in jobs_admin
    quotes_user, quotes_admin = ada.get("/book/quotes").text, boss.get("/book/quotes").text
    assert f'<option value="{races["motogp_wc"]}"' not in quotes_user and f'<option value="{races["f1_wdc"]}"' in quotes_user
    assert f'<option value="{races["motogp_wc"]}"' in quotes_admin
    for url in (f"/book/quotes?race_id={races['motogp_wc']}", f"/book/quotes/sheet?race_id={races['motogp_wc']}"):
        assert ada.get(url).status_code == 404, url
        assert boss.get(url).status_code == 200, url
    assert ada.get(f"/book/quotes?race_id={races['f1_wdc']}").status_code == 200


def test_markets_board_key_hides_downhill_from_the_markets_page_only():
    # owner, 2026-10-12: "UCI road only. Hide UCI DH for now" — off the Markets page for everyone, still public elsewhere
    assert SP.off_board_competitions() == {"uci_dhi_wc"}
    assert SP.is_public("mtb_dh", PRO) and SP.audience("mtb_dh") == "all"
