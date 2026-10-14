"""/docs/internal/: the internal onboarding book, served from INTERNAL_DOCS (data on the VM, never in git) to admins
only. Non-admins and signed-out clients get a 404 or a sign-in redirect, also through a dotted path that the /docs
catch-all would otherwise resolve, so those are sent as raw ASGI paths (TestClient normalizes the dots away)."""

import asyncio

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from racinglines.web import app as A
from racinglines.web import info_routes


@pytest.fixture
def book(tmp_path, monkeypatch):
    site, internal = tmp_path / "site", tmp_path / "internal-docs"
    (site / "webapp").mkdir(parents=True)
    (site / "index.html").write_text("public docs")
    (site / "internal").mkdir()
    (site / "internal" / "index.html").write_text("a stray mkdocs copy")
    (internal / "history").mkdir(parents=True)
    (internal / "index.html").write_text("the internal book")
    (internal / "history" / "whistler.html").write_text("whistler chapter")
    (tmp_path / "secret.txt").write_text("outside")
    monkeypatch.setattr(info_routes, "SITE", site)
    monkeypatch.setattr(info_routes, "INTERNAL_DOCS", internal)
    yield
    A.app.dependency_overrides.clear()


def _as(role):
    def dep(request: Request):
        request.state.user = dict(id=1, username=f"t_{role}", role=role, sid=None)
        return request.state.user
    A.app.dependency_overrides[A.authenticate] = dep
    return TestClient(A.app)


def _raw(path, role=None):
    """Status and body for a raw ASGI path, as `role` (or signed out)."""
    if role:
        _as(role)

    async def go():
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            sent.append(msg)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                 "headers": [(b"host", b"testserver")], "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
        await A.app(scope, receive, send)
        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return sent[0]["status"], body.decode(errors="replace")
    return asyncio.run(go())


def test_admin_reads_the_book(book):
    cl = _as("admin")
    assert cl.get("/docs/internal/").text == "the internal book"
    assert cl.get("/docs/internal/history/whistler.html").text == "whistler chapter"
    r = cl.get("/docs/internal", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/docs/internal/"
    assert cl.get("/docs/").text == "public docs"                       # the public docs are unchanged


@pytest.mark.parametrize("role", ["pro", "basic"])
def test_other_roles_get_404_and_still_see_the_public_docs(book, role):
    cl = _as(role)
    for path in ("/docs/internal/", "/docs/internal", "/docs/internal/history/whistler.html"):
        assert cl.get(path, follow_redirects=False).status_code == 404, path
    assert cl.get("/docs/").text == "public docs"


@pytest.mark.parametrize("role", ["pro", "basic"])
def test_dotted_paths_cannot_reach_the_book_or_the_stray_copy(book, role):
    for path in ("/docs/quickstart/term/../../internal/", "/docs/webapp/../internal/index.html",
                 "/docs/./internal/history/whistler.html", "/docs//internal/"):
        status, body = _raw(path, role)
        assert status == 404 and "internal book" not in body and "stray" not in body, path


def test_signed_out_clients_are_sent_to_sign_in(book):
    for path in ("/docs/internal/", "/docs/quickstart/term/../../internal/"):
        status, body = _raw(path)
        assert status in (303, 307, 401) and "internal book" not in body, path


def test_admin_cannot_climb_out_of_the_book(book):
    for path in ("/docs/internal/../../secret.txt", "/docs/internal/../../../secret.txt"):
        status, body = _raw(path, "admin")
        assert status == 404 and "outside" not in body, path
