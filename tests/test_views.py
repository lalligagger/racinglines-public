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
