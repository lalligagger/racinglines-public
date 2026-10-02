"""UI pass D: the post-login redirect accepts only same-site relative paths, the 303 to /login keeps the query."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.quick
@pytest.mark.parametrize("nxt,ok", [("/markets/kalshi?sport=f1", True), ("/lab", True), ("//evil.example", False),
                                    ("https://evil.example", False), ("/\\evil.example", False), ("evil", False),
                                    ("/a\r\nb", False)])
def test_safe_next(nxt, ok):
    from racinglines.web import app as A
    assert (A._safe_next(nxt) == nxt) is ok
    assert A._safe_next(nxt) == (nxt if ok else "/markets")


@pytest.mark.quick
def test_login_redirect_keeps_query():
    from racinglines.web import app as A
    r = TestClient(A.app).get("/positions?venue=kalshi&event=x", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=/positions%3Fvenue%3Dkalshi%26event%3Dx"
