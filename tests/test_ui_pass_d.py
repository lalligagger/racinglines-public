"""UI pass D: the post-login redirect accepts only same-site relative paths, the 303 to /login keeps the query."""

import re

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
    assert r.headers["location"] == "/signin?next=/positions%3Fvenue%3Dkalshi%26event%3Dx"


@pytest.mark.quick
def test_the_landing_has_news_and_no_sign_in_form_and_sign_in_has_its_own_page():
    """Owner, 2026-10-12: the sign-in form leaves the landing for /signin (the form still posts to /login), and the
    landing gets a News section under the infographic."""
    from racinglines.web import app as A
    client = TestClient(A.app)
    landing = client.get("/login").text
    assert 'name="password" type="password"' not in landing and 'href="/signin"' in landing
    assert 'id="news"' in landing and landing.index('id="news"') > landing.index('class="biz"')
    assert "Fantasy sign-ups are live for alpha testers." in landing and "open-source PyPI package this week" in landing
    assert '<a href="https://x.com/racinglines_bet" rel="noopener" target="_blank">Follow us on X (@racinglines_bet)</a>' in landing
    assert 'href="https://racinglinesdotbet.substack.com"' in landing
    assert 'value="maker"' in landing and 'value="taker"' in landing           # the demo buttons stay on the landing
    page = client.get("/signin?next=/positions").text
    assert 'action="/login"' in page and 'name="password" type="password"' in page and 'value="/positions"' in page
    assert "Wrong username" not in page and "Wrong username" in client.get("/signin?error=1").text
    r = client.get("/login?error=1&next=/lab", follow_redirects=False)       # an old sign-in link with an error
    assert r.status_code == 303 and r.headers["location"] == "/signin?next=/lab&error=1"


@pytest.mark.quick
def test_the_landing_is_a_strip_a_hero_and_a_dated_news_feed():
    """Owner, 2026-10-12: the fantasy block is one strip above the hero, "Something else" and "Talk to us" are gone, and
    the news feed is dated, newest first, with the package release marked upcoming."""
    from racinglines.web import app as A
    landing = TestClient(A.app).get("/login").text
    assert landing.index('class="lp-alpha"') < landing.index('class="lp-hero"')
    assert "Sportsbook pricing for all racing disciplines" in landing and "Motorsport pricing for sportsbooks" not in landing
    assert "Something else in mind" not in landing and 'id="contact"' not in landing and "Fantasy trade with us" not in landing
    days = re.findall(r'<time datetime="(\d{4}-\d\d-\d\d)">', landing)
    assert days and days == sorted(days, reverse=True)
    assert landing.index('class="upcoming"') < landing.index("<time ")
