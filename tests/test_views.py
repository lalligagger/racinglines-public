"""Web app: job-form validation (no database) and page smoke tests per role (database)."""

import re

import pytest

pytestmark = pytest.mark.live      # reads the live database (changes as data arrives)
from sqlalchemy import text

from racinglines.web import jobs


# --- job knobs (no database) --------------------------------------------------

def test_job_defaults_parse():
    for jt in jobs.CATALOG.values():
        form = {k.name: "" for k in jt.knobs}
        form.update({"event": "2026-15", "cutoff": "2026-09-25T23:59"})
        p = jobs.parse(jt, form)
        assert set(p) == {k.name for k in jt.knobs}


@pytest.mark.parametrize("field,value", [("half_life", "5"), ("half_life", "99999"), ("sims", "abc"),
                                         ("track", "maybe"), ("races", "0")])
def test_job_knobs_rejected(field, value):
    with pytest.raises((ValueError, TypeError)):
        jobs.parse(jobs.CATALOG["f1_backtest"], {field: value})


@pytest.mark.parametrize("field,value", [("half_life_days", "5"), ("variant", "nope"), ("sims", "10"),
                                         ("fill", "maybe"), ("min_edge", "2")])
def test_sweep_settings_rejected(field, value):
    with pytest.raises(ValueError):
        jobs.parse(jobs.CATALOG["f1_sweep"], {"year": "2026", field: value})


def test_sweep_form_to_command_line():
    p = jobs.parse(jobs.CATALOG["f1_sweep"], {"year": "2025", "variant": "gridq", "half_spread": "0.03",
                                              "practice_prior": "false", "taker_stages__present": "1",
                                              "taker_stages": ["pre-weekend", "after FP1"]})
    assert p == {"year": "2025", "settings": {"variant": "gridq", "practice_prior": False,
                                              "taker_stages": ["pre-weekend", "after FP1"], "half_spread": 0.03}}
    assert jobs._sweep_argv(p)[3:] == ["--variant", "gridq", "sweep", "--year", "2025", "--no-fetch", "--save",
                                       "--practice-prior", "false", "--taker-stages", "pre-weekend,after FP1",
                                       "--half-spread", "0.03"]


@pytest.mark.parametrize("label", ["x; rm -rf /", "a" * 61])
def test_scenario_label_rejected(label):
    with pytest.raises(ValueError):
        jobs.parse(jobs.CATALOG["f1_scenario"], {"label": label or " "})


def test_diagnostic_needs_event_and_cutoff_format():
    jt = jobs.CATALOG["f1_diagnostic"]
    with pytest.raises(ValueError):
        jobs.parse(jt, {"event": "2026-15", "cutoff": "yesterday"})
    with pytest.raises(ValueError):
        jobs.parse(jt, {"event": "baku", "cutoff": "2026-09-25T23:59"})


def test_argv_is_a_list_of_plain_arguments():
    """Jobs run without a shell: every knob is its own argv element."""
    p = jobs.parse(jobs.CATALOG["f1_scenario"], {"label": "my scenario"})
    argv = jobs.CATALOG["f1_scenario"].argv(p, "/tmp/x.csv")
    assert "my scenario" in argv and all(isinstance(a, str) for a in argv)


# --- pages (database) ---------------------------------------------------------

@pytest.fixture(scope="module")
def clients():
    from racinglines.db.config import get_engine
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
            races = [r[0] for r in c.execute(text("""
                SELECT DISTINCT ON (e.status) ra.id FROM races ra JOIN events e ON e.id = ra.event_id
                ORDER BY e.status, e.start_date DESC"""))]
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"no database: {ex}")
    from fastapi.testclient import TestClient

    from racinglines.web.app import app
    out = {}
    for role in ("maker", "taker"):
        cl = TestClient(app)
        cl.post("/login", data=dict(username=role, password="password"))
        out[role] = cl
    return out, races


def test_maker_pages(clients):
    cl, races = clients
    m = cl["maker"]
    for path in ["/", "/book", "/lab", "/markets/polymarket", "/seasons/f1_wdc", "/seasons/uci_dhi_wc", "/events", "/athletes"] + \
            [f"/races/{r}" for r in races]:
        r = m.get(path)
        assert r.status_code == 200, path
        assert not re.search(r">\s*nan\b|\bnan\s*<|\bNan <", r.text, re.I), f"NaN printed in a cell on {path}"


def test_taker_is_kept_to_prices(clients):
    cl, races = clients
    t = cl["taker"]
    assert t.get("/", follow_redirects=False).headers["location"] == "/markets"
    assert t.get(f"/races/{races[0]}", follow_redirects=False).status_code == 303
    for path in ("/lab", "/book", "/seasons/f1_wdc"):
        assert t.get(path).status_code == 403, path
    assert t.get("/positions").status_code == 200


def test_old_urls_redirect(clients):
    """Routes match page names; every old URL redirects (web/legacy.py), keeping its query string."""
    m = clients[0]["maker"]
    for old, new in (("/", "/markets"), ("/bet", "/markets"), ("/me", "/positions"), ("/signals?event=2026-15", "/strategy?event=2026-15"),
                     ("/pm", "/markets/polymarket"), ("/house?race_id=5", "/book/quotes?race_id=5"),
                     ("/house/7", "/book/markets/7"), ("/race/3", "/races/3"), ("/season/f1_wdc", "/seasons/f1_wdc"),
                     ("/diag/9", "/lab/diagnostics/9"), ("/runs/4", "/lab/runs/4"), ("/markets/12", "/markets/linked/12")):
        r = m.get(old, follow_redirects=False)
        assert r.status_code == 308 and r.headers["location"] == new, old
    for index, new in (("/lab/diagnostics", "/lab"), ("/lab/runs", "/lab")):
        assert m.get(index, follow_redirects=False).headers["location"].startswith(new)


def test_docs_behind_login(clients):
    from fastapi.testclient import TestClient

    from racinglines.web.app import SITE, app
    m = clients[0]["maker"]
    assert TestClient(app).get("/docs/", headers={"accept": "text/html"},
                               follow_redirects=False).status_code == 303   # not logged in -> /login
    assert m.get("/docs/%2e%2e/pyproject.toml").status_code == 404           # nothing outside site/
    if not (SITE / "index.html").is_file():
        pytest.skip("docs not built (python -m mkdocs build -d site)")
    for path in ("/docs", "/docs/", "/docs/market-making/"):
        r = m.get(path)
        assert r.status_code == 200 and "<html" in r.text.lower(), path


def test_lab_leads_with_the_edge_finder_and_loads_sections_on_demand(clients):
    from racinglines.web.views import LAB_SECTIONS
    m, t = clients[0]["maker"], clients[0]["taker"]
    page = m.get("/lab").text
    assert 'id="edge"' in page and "Edge Finder" in page and 'data-section="run"' in page
    assert "<table" not in page.split('data-section="run"')[1]                  # other sections not rendered
    for key, _ in LAB_SECTIONS:
        r = m.get(f"/lab/section/{key}")
        assert r.status_code == 200, key
        assert not re.search(r">\s*nan\b|\bnan\s*<", r.text, re.I), f"NaN printed in lab section {key}"
    assert m.get("/lab/section/nope").status_code == 404
    assert t.get("/lab/section/models").status_code == 403


def test_edge_finder_combos_are_saved_per_user(clients):
    from racinglines.web.app import CSRF_TOKEN
    m, t = clients[0]["maker"], clients[0]["taker"]
    post = lambda **f: m.post("/lab/edge", data=dict(csrf_token=CSRF_TOKEN, **f))    # noqa: E731
    try:
        assert post(action="clear").status_code == 200
        assert post(action="add", variant="baseline", strategy="maker").status_code == 200
        assert post(action="add", variant="nonsense", strategy="maker").status_code == 400
        page = m.get("/lab").text                                                   # a fresh visit, from the database
        assert "data-combos='[[\"baseline\", \"maker\"]]'" in page
        assert t.post("/lab/edge", data=dict(csrf_token=CSRF_TOKEN, action="reset")).status_code == 403
        assert m.post("/lab/edge", data=dict(csrf_token="bad", action="reset")).status_code == 403
    finally:
        post(action="reset")


def test_run_forms_start_from_the_users_last_knobs(clients):
    from racinglines.db.config import get_engine
    from racinglines.web import prefs as P
    from racinglines.web.views import _remember_knobs
    m = clients[0]["maker"]
    with get_engine().connect() as c:
        uid = c.execute(text("SELECT id FROM users WHERE username = 'maker'")).scalar()
        before = P.get(c, uid).get("job_knobs")
    try:
        _remember_knobs(uid, "f1_sweep", dict(year="2026", settings=dict(variant="gridq+reset", min_edge=0.07)))
        html = m.get("/lab/section/run").text
        assert 'name="variant" value="gridq+reset"' in html and 'name="min_edge" type="number" value="0.07"' in html
    finally:
        with get_engine().connect() as c:
            P.put(c, uid, "job_knobs", before or {})


def test_edge_finder_benchmark_is_the_default_settings_conservative_maker(clients):
    from racinglines.db.config import get_engine
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.web import edge as E
    with get_engine().connect() as c:
        b = E.build(c, [], 2026)["benchmark"]
        if b is None:
            pytest.skip("no default-settings baseline sweep saved")
        params = c.execute(text("SELECT params FROM model_runs WHERE id = :i"), dict(i=b["run_id"])).scalar()
    assert SS.Settings.from_run_params(params) == SS.Settings.from_dict()        # default settings, baseline model
    assert "Benchmark · " in clients[0]["maker"].get("/lab").text                   # shown even with no combos chosen


def test_signals_page_hides_fair_from_takers(clients):
    """Demo taker sees action, size, limit and heat but never our fair value or edge; the maker sees quotes."""
    from sqlalchemy import text as T

    from racinglines.db.config import get_engine
    cl, _ = clients
    eng = get_engine()
    with eng.begin() as c:
        c.execute(T("DELETE FROM strategy_signals WHERE event_key = '2099-01'"))
        ids = dict(c.execute(T("SELECT username, id FROM users WHERE username IN ('taker', 'maker')")).all())
        for u, action, side in (("taker", "buy", "YES"), ("maker", "quote", "both")):
            c.execute(T("""INSERT INTO strategy_signals (user_id, profile, strategy, event_key, market_key, kind, subject,
                             stage, dedupe, action, side, shares, limit_price, fair, price, edge, heat, status, signal_ts)
                           VALUES (:u, 'test', :s, '2099-01', 'tok-test', 'race_h2h', 'Zed ahead of Yan', 'after FP2',
                             'after FP2', :a, :sd, 62, 0.41, 0.5234, 0.40, 0.1234, 2, 'new', now())"""),
                      dict(u=ids[u], s="update" if u == "taker" else "maker", a=action, sd=side))
    try:
        r = cl["taker"].get("/strategy")
        assert r.status_code == 200 and "Zed ahead of Yan" in r.text and "BUY YES" in r.text
        assert "hot" in r.text and "Our fair" not in r.text and "0.523" not in r.text and "+12.3 pts" not in r.text
        r = cl["maker"].get("/strategy")
        assert r.status_code == 200 and "quoting" in r.text and "Our fair" in r.text
    finally:
        with eng.begin() as c:
            c.execute(T("DELETE FROM strategy_signals WHERE event_key = '2099-01'"))


def test_racinglines101_is_public_and_linked_from_login():
    from fastapi.testclient import TestClient

    from racinglines.web.app import app
    cl = TestClient(app)
    r = cl.get("/racinglines101", follow_redirects=False)
    assert r.status_code == 200 and "Racinglines 101" in r.text and "paper trades" in r.text
    assert 'href="/racinglines101">I\'m already confused.</a>' in cl.get("/login").text


def test_replay_counterparty_is_not_the_demo_taker(test_engine):
    """Replay fills belong to the polymarket-takers system account: no login, never the demo taker."""
    from sqlalchemy.orm import Session

    from racinglines.web import users as U
    with Session(test_engine) as s:
        u = U.ensure_replay_taker(s)
        assert U.ensure_replay_taker(s).id == u.id                     # created once
        assert u.username == U.REPLAY_TAKER != "taker" and not u.active
        assert U.authenticate(s, U.REPLAY_TAKER, "!no-login") is None


def test_demo_context_bubbles_are_tagged_and_switchable():
    """Demo-only text sits in data-tag="demo-context" bubbles; RACINGLINES_DEMO_CONTEXT=0 hides every one."""
    from fastapi.testclient import TestClient

    from racinglines.web import app as A
    cl = TestClient(A.app)
    cl.post("/login", data=dict(username="taker", password="password"))
    t = cl.get("/strategy").text
    assert 'data-tag="demo-context"' in t and "demo context" not in t.lower().replace('data-tag="demo-context"', "")
    assert "early demo" in cl.get("/racinglines101").text and 'data-tag="demo-context"' not in cl.get("/racinglines101").text
    A.DEMO_CONTEXT["on"] = False
    try:
        t = cl.get("/strategy").text
        assert 'data-tag="demo-context"' not in t and "This demo taker" not in t and "Track record" in t
    finally:
        A.DEMO_CONTEXT["on"] = True


def test_taker_markets_are_polymarket_not_a_makers_book(clients):
    cl, _ = clients
    r = cl["taker"].get("/markets")
    assert r.status_code == 200 and "Every open F1 market on Polymarket" in r.text and "Upcoming races" in r.text
    assert "Our fair" not in r.text and "fair_prob" not in r.text
    r = cl["taker"].get("/positions")
    assert r.status_code == 200 and "Every Polymarket position" in r.text and "Coming up" in r.text


def test_demo_sessions_are_disposable_and_logged(clients):
    """Demo accounts (web/demo.py): view changes live in the session only, data changes are refused,
    each sign-in starts from the saved baseline, and every request is logged with its session id."""
    import re

    from fastapi.testclient import TestClient
    from sqlalchemy import text as T

    from racinglines.db.config import get_engine
    from racinglines.web.app import CSRF_TOKEN, app
    eng = get_engine()

    def saved():
        with eng.connect() as c:
            return c.execute(T("SELECT prefs FROM users WHERE username = 'maker'")).scalar()

    def combos(cl):
        m = re.search(r"data-combos='([^']*)'", cl.get("/lab").text)
        return m.group(1) if m else None

    base = saved()
    a, b = TestClient(app), TestClient(app)
    for cl in (a, b):
        cl.post("/login", data=dict(username="maker", password="password"))
    start = combos(a)
    assert a.post("/lab/edge", data=dict(csrf_token=CSRF_TOKEN, action="clear")).status_code == 200
    assert combos(a) == "[]" and combos(b) == start and saved() == base          # session only; other session untouched
    fresh = TestClient(app)
    fresh.post("/login", data=dict(username="maker", password="password"))
    assert combos(fresh) == start                                                # a new sign-in starts from the baseline
    r = a.post("/lab/candidate", data=dict(csrf_token=CSRF_TOKEN, action="add"), headers={"sec-fetch-mode": "cors"})
    assert r.status_code == 403 and "demo" in r.text
    r = a.post("/lab/run", data=dict(csrf_token=CSRF_TOKEN, job="f1_sweep"), follow_redirects=False,
               headers={"referer": "http://testserver/lab"})
    assert r.status_code == 303 and "isn't available in the demo" in r.headers["location"]
    with eng.connect() as c:
        got = dict(c.execute(T("""SELECT action, count(*) FROM activity_log WHERE username = 'maker'
                                   AND ts > now() - interval '5 minutes' GROUP BY 1""")).all())
        sid = c.execute(T("""SELECT detail->>'sid' FROM activity_log WHERE username = 'maker' AND action = 'demo_blocked'
                             ORDER BY id DESC LIMIT 1""")).scalar()
    assert got.get("demo_view") and got.get("demo_post") and got.get("demo_blocked") and sid
    assert saved() == base


def test_admin_totals_leave_out_the_replay_counterparty():
    import pandas as pd

    from racinglines.web import users as U
    from racinglines.web.admin import bet_totals
    bets = pd.DataFrame(dict(taker=["taker", U.REPLAY_TAKER, U.REPLAY_TAKER, "demo-7"],
                             stake=[10.0, 500.0, 300.0, 5.0], pnl=[-10.0, 120.0, -40.0, 4.0]))
    t = bet_totals(bets)
    assert (t["bets"], t["staked"], t["taker_pnl"]) == (2, 15.0, -6.0)
    assert (t["replay_bets"], t["replay_pnl"]) == (2, 80.0)
    assert bet_totals(bets.iloc[0:0]) == dict(bets=0, staked=0.0, taker_pnl=0.0, replay_bets=0, replay_pnl=0.0)


def test_disagreement_panel_needs_the_switch(clients):
    """The Markets page is byte-identical without RACINGLINES_DISAGREE=1; with it, the cross-venue panel shows the
    log's latest tick (or nothing at all while the log is empty)."""
    from racinglines.db.config import get_engine
    from racinglines.markets import disagree as D
    m = clients[0]["maker"]
    was = D.ON["on"]
    D.ON["on"] = False
    off = m.get("/markets").text
    assert "Cross-venue disagreement" not in off
    D.ON["on"] = True
    try:
        on = m.get("/markets").text
        with get_engine().connect() as c:
            panel = D.panel(c)
        if panel is None:
            assert on == off
        else:
            assert "Cross-venue disagreement" in on and f"{panel['n_above']} of {len(panel['rows'])} outcomes above fees" in on
            assert not re.search(r">\s*nan\b|\bnan\s*<", on, re.I)
    finally:
        D.ON["on"] = False
    assert m.get("/markets").text == off
    D.ON["on"] = was


def test_kalshi_pages_need_the_switch(clients):
    """With RACINGLINES_KALSHI_VENUE=0 the Kalshi list is a 404 and its Positions filter is ignored (the page
    still renders); by default, the list and the filters render (racinglines.markets.venues.KALSHI_VENUE)."""
    from racinglines.markets import venues as V
    m = clients[0]["maker"]
    assert m.get("/markets/kalshi").status_code == (200 if V.KALSHI_VENUE else 404)
    for path in ("/positions?venue=kalshi", "/strategy?venue=kalshi"):
        r = m.get(path)
        assert r.status_code == 200, path
        assert not re.search(r">\s*nan\b|\bnan\s*<", r.text, re.I), path


def test_strategy_and_positions_have_a_modeled_sport_catalog_even_when_rows_are_sparse():
    """The dropdown should be built from the modeled sport catalog, not only the rows that happen to exist."""
    from racinglines.web.views import _sport_options

    options = _sport_options([{"sport": "f1"}])
    assert "f1" in options and "nascar" in options and "motogp" in options
    assert len(options) == len(set(options))


def test_strategy_and_positions_have_a_nascar_sport_filter(clients):
    """The web app should treat NASCAR and MotoGP as first-class sports in the demo track-record views."""
    from sqlalchemy import text as T

    from racinglines.db.config import get_engine
    cl, _ = clients
    eng = get_engine()
    event_key = "2099-nascar"
    motogp_key = "2099-motogp"
    with eng.begin() as c:
        c.execute(T("INSERT INTO sports (code, name) VALUES ('nascar', 'NASCAR') ON CONFLICT (code) DO NOTHING"))
        c.execute(T("INSERT INTO sports (code, name) VALUES ('motogp', 'MotoGP') ON CONFLICT (code) DO NOTHING"))
        c.execute(T("INSERT INTO leagues (code, name, organizer) VALUES ('nascar', 'NASCAR', 'NASCAR') ON CONFLICT (code) DO NOTHING"))
        c.execute(T("INSERT INTO leagues (code, name, organizer) VALUES ('motogp', 'MotoGP', 'MotoGP') ON CONFLICT (code) DO NOTHING"))
        c.execute(T("""INSERT INTO competitions (code, name, league_id, sport_id)
                       VALUES ('nascar_cup', 'NASCAR Cup', (SELECT id FROM leagues WHERE code = 'nascar'),
                               (SELECT id FROM sports WHERE code = 'nascar')),
                              ('motogp_wc', 'MotoGP World Championship', (SELECT id FROM leagues WHERE code = 'motogp'),
                               (SELECT id FROM sports WHERE code = 'motogp'))
                       ON CONFLICT (code) DO NOTHING"""))
        c.execute(T("""INSERT INTO seasons (competition_id, year)
                       VALUES ((SELECT id FROM competitions WHERE code = 'nascar_cup'), 2026),
                              ((SELECT id FROM competitions WHERE code = 'motogp_wc'), 2026)
                       ON CONFLICT (competition_id, year) DO NOTHING"""))
        c.execute(T("""INSERT INTO events (season_id, source, source_key, name, start_date, status)
                       VALUES ((SELECT id FROM seasons WHERE competition_id = (SELECT id FROM competitions WHERE code = 'nascar_cup') AND year = 2026),
                               'nascar_cf', :k, 'NASCAR South Point 400', '2026-10-04', 'completed'),
                              ((SELECT id FROM seasons WHERE competition_id = (SELECT id FROM competitions WHERE code = 'motogp_wc') AND year = 2026),
                               'motogp_api', :mk, 'MotoGP Austrian GP', '2026-08-17', 'completed')
                       ON CONFLICT (season_id, source, source_key) DO NOTHING"""),
                   dict(k=event_key, mk=motogp_key))
        uid = c.execute(T("SELECT id FROM users WHERE username = 'maker'")).scalar()
        c.execute(T("""INSERT INTO strategy_signals (user_id, profile, strategy, event_key, market_key, kind, subject,
                         stage, dedupe, action, side, shares, limit_price, fair, price, edge, heat, status, signal_ts, detail)
                       VALUES (:u, 'maker', 'maker', :k, 'tok-nascar', 'race_win', 'NASCAR South Point 400 Winner',
                               'before race', 'before race', 'fill', 'YES', 10, 0.60, 0.55, 0.62, 0.10, 2, 'new', now(),
                               '{\"venue\": \"polymarket\"}'),
                              (:u, 'maker', 'maker', :mk, 'tok-motogp', 'race_win', 'MotoGP Austrian GP Winner',
                               'before race', 'before race', 'fill', 'YES', 8, 0.58, 0.51, 0.60, 0.08, 2, 'new', now(),
                               '{\"venue\": \"polymarket\"}')"""), dict(u=uid, k=event_key, mk=motogp_key))
        c.execute(T("""INSERT INTO paper_positions (user_id, event_key, market_key, kind, subject, yes_shares, no_shares,
                         cash, mark, outcome, venue)
                       VALUES (:u, :k, 'tok-nascar', 'race_win', 'NASCAR South Point 400 Winner', 10, 0, 0.0,
                               0.82, NULL, 'polymarket'),
                              (:u, :mk, 'tok-motogp', 'race_win', 'MotoGP Austrian GP Winner', 8, 0, 0.0,
                               0.74, NULL, 'polymarket')"""), dict(u=uid, k=event_key, mk=motogp_key))
    try:
        r = cl["maker"].get("/strategy?sport=nascar")
        assert r.status_code == 200 and "NASCAR South Point 400" in r.text
        r = cl["maker"].get("/positions?sport=nascar")
        assert r.status_code == 200 and "NASCAR South Point 400" in r.text and 'name="sport"' in r.text
        r = cl["maker"].get("/strategy?sport=motogp")
        assert r.status_code == 200 and "MotoGP Austrian GP" in r.text
        r = cl["maker"].get("/positions?sport=motogp")
        assert r.status_code == 200 and "MotoGP Austrian GP" in r.text and 'name="sport"' in r.text
    finally:
        with eng.begin() as c:
            c.execute(T("DELETE FROM paper_positions WHERE event_key IN (:k, :mk)"), dict(k=event_key, mk=motogp_key))
            c.execute(T("DELETE FROM strategy_signals WHERE event_key IN (:k, :mk)"), dict(k=event_key, mk=motogp_key))
            c.execute(T("DELETE FROM events WHERE source_key IN (:k, :mk)"), dict(k=event_key, mk=motogp_key))


def test_basic_pages_never_name_the_strategy_behind_a_pick(clients):
    """A basic account's picks (here from a blend member) show as "Your picks" with a star rating: no profile,
    strategy or member name or code, no fair value or edge. Pro pages are unchanged."""
    from sqlalchemy import text as T

    from racinglines.db.config import get_engine
    cl, _ = clients
    eng = get_engine()
    with eng.begin() as c:
        uid = c.execute(T("SELECT id FROM users WHERE username = 'taker'")).scalar()
        c.execute(T("""INSERT INTO strategy_signals (user_id, profile, strategy, event_key, market_key, kind, subject,
                         stage, dedupe, action, side, shares, limit_price, fair, price, edge, heat, status, signal_ts, detail)
                       VALUES (:u, 'TB · blended taker (update + stage-aware)', 'early', '2099-03', 'tok-test-b', 'race_h2h',
                         'Zed ahead of Yan', 'after FP2', 'after FP2', 'buy', 'YES', 62, 0.41, 0.5234, 0.40, 0.1234, 2, 'new',
                         now(), '{"member": "T8", "followed": true}')"""), dict(u=uid))
    try:
        for path in ("/strategy?event=2099-03", "/positions?event=2099-03"):
            r = cl["taker"].get(path)
            assert r.status_code == 200, path
            for leak in ("TB ·", "blended taker", "T8", "stage-aware", "0.523", "+12.3 pts", "Our fair"):
                assert leak not in r.text, (path, leak)
        r = cl["taker"].get("/strategy?event=2099-03")
        assert "Zed ahead of Yan" in r.text, "subject"
        assert "Your picks" in r.text, "name"
        assert "★★★" in r.text, "stars"
    finally:
        with eng.begin() as c:
            c.execute(T("DELETE FROM strategy_signals WHERE event_key = '2099-03'"))
