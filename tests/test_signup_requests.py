"""Request an account (/signup, RACINGLINES_SIGNUP_REQUESTS=1): off by default, records to activity_log only."""

import pytest

pytestmark = pytest.mark.quick


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from racinglines.web import app as A
    logged = []
    monkeypatch.setattr(A.U, "log", lambda engine, user, action, request=None, **d: logged.append((action, d)))
    monkeypatch.setattr(A, "get_engine", lambda: None)
    monkeypatch.setattr(A, "_signup_hits", {})
    c = TestClient(A.app)
    c.logged = logged
    return c


GOOD = dict(name="Ada", email="ada@example.com", tier="basic", note="")


def test_off_by_default(client, monkeypatch):
    monkeypatch.delenv("RACINGLINES_SIGNUP_REQUESTS", raising=False)
    assert client.get("/signup").status_code == 404
    assert client.post("/signup", data=GOOD).status_code == 404
    assert "/signup" not in client.get("/login").text
    assert client.logged == []


def test_a_request_is_recorded(client, monkeypatch):
    monkeypatch.setenv("RACINGLINES_SIGNUP_REQUESTS", "1")
    assert 'href="/signup"' in client.get("/login").text
    page = client.get("/signup")
    assert page.status_code == 200 and "Request account" in page.text
    r = client.post("/signup", data=GOOD)
    assert r.status_code == 200 and "we have your request" in r.text
    assert client.logged == [("signup_request", dict(name="Ada", email="ada@example.com", tier="basic", note=None))]


@pytest.mark.parametrize("bad, msg", [(dict(name=""), "your name"), (dict(email="nope"), "valid email"),
                                      (dict(tier="admin"), "pro or basic")])
def test_bad_input_is_refused_and_kept(client, monkeypatch, bad, msg):
    monkeypatch.setenv("RACINGLINES_SIGNUP_REQUESTS", "1")
    r = client.post("/signup", data=dict(GOOD, **bad))
    assert r.status_code == 400 and msg in r.text and client.logged == []


def test_honeypot_and_throttle(client, monkeypatch):
    monkeypatch.setenv("RACINGLINES_SIGNUP_REQUESTS", "1")
    assert client.post("/signup", data=dict(GOOD, website="spam.example")).status_code == 200
    assert client.logged == []
    for _ in range(5):
        assert client.post("/signup", data=GOOD).status_code == 200
    assert client.post("/signup", data=GOOD).status_code == 429
    assert len(client.logged) == 5
