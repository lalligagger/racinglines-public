"""Polite HTTP (racinglines/sources/http.py): per-host pacing and retries, with a fake client (no network)."""

import time

import httpx
import pytest

from racinglines.sources import http

pytestmark = pytest.mark.quick


class Fake:
    base_url = "https://clob.polymarket.com"

    def __init__(self, statuses, headers=None):
        self.statuses, self.calls, self.headers = list(statuses), [], headers or {}

    def request(self, method, url, **kw):
        self.calls.append(time.monotonic())
        s = self.statuses.pop(0)
        if s == "timeout":
            raise httpx.ReadTimeout("slow")
        return httpx.Response(s, headers=self.headers)


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    waits = []
    monkeypatch.setattr(http.time, "sleep", lambda s: waits.append(s))
    monkeypatch.setattr(http, "_next_ok", {})
    return waits


def test_retries_429_5xx_and_timeouts_then_succeeds(fast):
    c = Fake([429, 503, "timeout", 200])
    assert http.get(c, "/prices-history").status_code == 200
    assert len(c.calls) == 4
    backoffs = [w for w in fast if w >= 1]
    assert len(backoffs) == 3 and backoffs[0] < backoffs[-1]           # exponential


def test_honours_retry_after(fast):
    c = Fake([429, 200], headers={"Retry-After": "7"})
    http.get(c, "/x")
    assert 7.0 in fast


def test_client_errors_are_not_retried(fast):
    c = Fake([404, 200])
    assert http.get(c, "/x").status_code == 404 and len(c.calls) == 1


def test_gives_up_after_max_tries(fast):
    c = Fake([503] * http.MAX_TRIES)
    assert http.get(c, "/x").status_code == 503 and len(c.calls) == http.MAX_TRIES
    with pytest.raises(httpx.TimeoutException):
        http.get(Fake(["timeout"] * http.MAX_TRIES), "/x")


def test_requests_to_one_host_are_spaced(fast, monkeypatch):
    monkeypatch.setitem(http.HOST_INTERVAL, "clob.polymarket.com", 0.5)
    c = Fake([200, 200, 200])
    for _ in range(3):
        http.get(c, "/x")
    assert len(fast) == 2 and 0.45 < fast[0] <= 0.5 and 0.95 < fast[1] <= 1.0    # back-to-back calls wait their turn
    other = Fake([200])
    other.base_url = "https://en.wikipedia.org"
    http.get(other, "/y")
    assert len(fast) == 2                                                        # another host isn't held up
