"""/llms.txt and /llms-full.txt: the AI-readable docs index (llmstxt.org), public by exact path, served from site/."""

from fastapi.testclient import TestClient

from racinglines.web import info_routes
from racinglines.web.app import app


def test_llms_files_are_public_and_plain_text(tmp_path, monkeypatch):
    (tmp_path / "llms.txt").write_text("# racinglines\n")
    (tmp_path / "llms-full.txt").write_text("# racinglines\n\nall pages\n")
    (tmp_path / "index.html").write_text("docs")
    monkeypatch.setattr(info_routes, "SITE", tmp_path)
    cl = TestClient(app)
    for path, body in (("/llms.txt", "# racinglines\n"), ("/llms-full.txt", "# racinglines\n\nall pages\n")):
        r = cl.get(path, follow_redirects=False)
        assert r.status_code == 200 and r.text == body, path
        assert r.headers["content-type"].startswith("text/plain"), path
    assert cl.get("/docs/", follow_redirects=False).status_code in (303, 307, 401)    # the docs stay behind sign-in


def test_llms_missing_is_404(tmp_path, monkeypatch):
    monkeypatch.setattr(info_routes, "SITE", tmp_path)
    assert TestClient(app).get("/llms.txt", follow_redirects=False).status_code == 404


def test_landing_links_llms_at_the_bottom():
    r = TestClient(app).get("/", follow_redirects=False)
    assert r.status_code == 200
    assert 'href="/llms.txt"' in r.text and r.text.rindex('class="lp-llms"') > r.text.rindex('id="news"')
