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
    for path in ["/", "/book", "/lab", "/pm", "/season/f1_wdc", "/season/uci_dhi_wc", "/events", "/athletes"] + \
            [f"/race/{r}" for r in races]:
        r = m.get(path)
        assert r.status_code == 200, path
        assert not re.search(r">\s*nan\b|\bnan\s*<|\bNan <", r.text, re.I), f"NaN printed in a cell on {path}"


def test_taker_is_kept_to_prices(clients):
    cl, races = clients
    t = cl["taker"]
    assert t.get("/", follow_redirects=False).headers["location"] == "/bet"
    assert t.get(f"/race/{races[0]}", follow_redirects=False).status_code == 303
    for path in ("/lab", "/book", "/season/f1_wdc"):
        assert t.get(path).status_code == 403, path
    assert t.get("/me").status_code == 200


def test_old_urls_redirect(clients):
    m = clients[0]["maker"]
    for old, new in (("/diag", "/lab"), ("/runs", "/lab"), ("/me", "/book")):
        assert m.get(old, follow_redirects=False).headers["location"].startswith(new)


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
        _remember_knobs(uid, "f1_sweep", dict(variant="gridq+reset", min_edge=0.07, stake_per_edge=250, max_stake=50,
                                              cost=0.01))
        html = m.get("/lab/section/run").text
        assert "selected>gridq+reset" in html and 'value="0.07"' in html
    finally:
        with get_engine().connect() as c:
            P.put(c, uid, "job_knobs", before or {})


def test_edge_finder_benchmark_is_the_default_settings_conservative_maker(clients):
    from racinglines.db.config import get_engine
    from racinglines.web import edge as E
    with get_engine().connect() as c:
        b = E.benchmark(c)
        if b is None:
            pytest.skip("no default-settings baseline sweep saved")
        params = c.execute(text("SELECT params FROM model_runs WHERE id = :i"), dict(i=b["run_id"])).scalar()
    assert (b["variant"], b["strategy"]) == ("baseline", "maker")
    assert params.get("variant", "baseline") == "baseline"
    assert all(float(params[k]) == v for k, v in E.DEFAULT_SWEEP.items())         # other knobs never replace it
    assert "Benchmark · " in clients[0]["maker"].get("/lab").text                   # shown even with no combos chosen
