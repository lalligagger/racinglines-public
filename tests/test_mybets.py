"""/mybets serves the bets page from the data folder to anyone, no sign-in, and 404 when the file is missing."""

import pytest
from fastapi.testclient import TestClient

from racinglines.web import app as A


@pytest.mark.quick
def test_serves_the_file_without_sign_in(tmp_path, monkeypatch):
    f = tmp_path / "index.html"
    f.write_text("<!doctype html><title>Bets</title><p>calendar</p>")
    monkeypatch.setenv("RACINGLINES_MYBETS", str(f))
    r = TestClient(A.app).get("/mybets", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 200 and "calendar" in r.text and r.headers["cache-control"] == "no-store"


@pytest.mark.quick
def test_missing_file_is_404(tmp_path, monkeypatch):
    monkeypatch.setenv("RACINGLINES_MYBETS", str(tmp_path / "none.html"))
    assert TestClient(A.app).get("/mybets").status_code == 404
