"""/mybets serves the bets page from the data folder, admin only, 404 when the file is missing."""

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from racinglines.web import app as A


def client(role):
    def auth(request: Request):
        request.state.user = {"id": 1, "username": "u", "role": role}
    A.app.dependency_overrides[A.authenticate] = auth
    return TestClient(A.app)


@pytest.fixture(autouse=True)
def _clear():
    yield
    A.app.dependency_overrides.clear()


@pytest.mark.quick
def test_serves_the_file_to_admin(tmp_path, monkeypatch):
    f = tmp_path / "index.html"
    f.write_text("<!doctype html><title>Bets</title><p>calendar</p>")
    monkeypatch.setenv("RACINGLINES_MYBETS", str(f))
    r = client("admin").get("/mybets")
    assert r.status_code == 200 and "calendar" in r.text and r.headers["cache-control"] == "no-store"


@pytest.mark.quick
def test_missing_file_is_404(tmp_path, monkeypatch):
    monkeypatch.setenv("RACINGLINES_MYBETS", str(tmp_path / "none.html"))
    assert client("admin").get("/mybets").status_code == 404


@pytest.mark.quick
@pytest.mark.parametrize("role", ["pro", "basic"])
def test_other_roles_are_refused(tmp_path, monkeypatch, role):
    f = tmp_path / "index.html"
    f.write_text("x")
    monkeypatch.setenv("RACINGLINES_MYBETS", str(f))
    assert client(role).get("/mybets").status_code == 403
