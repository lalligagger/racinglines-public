"""NASCAR fetch: a recent race's feeds are asked for again, so one stored while the race was running is replaced."""
import json
from datetime import date, timedelta

import httpx
import pytest

from racinglines.sources import http
from racinglines.sources.nascar import fetch as F

TODAY = date(2026, 10, 5)            # the Monday after Las Vegas (4 Oct), whose race ends after midnight UTC


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "OUT", tmp_path)
    monkeypatch.setitem(http.HOST_INTERVAL, "cf.nascar.com", 0)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    monkeypatch.setattr(http, "_next_ok", {})
    return tmp_path


@pytest.mark.quick
def test_a_recent_race_is_asked_for_again_so_a_feed_stored_mid_race_is_replaced(raw):
    path = "cacher/2026/1/5630/weekend-feed.json"
    served = {"cacher/2026/1/race_list_basic.json":
              json.dumps([dict(race_id=5630, race_date="2026-10-04T19:00:00", race_type_id=1)]).encode(),
              path: b'{"stage": "lap 120"}'}
    asked = []

    def handler(request):
        p = request.url.path.lstrip("/")
        asked.append(p)
        return httpx.Response(200, content=served[p]) if p in served else httpx.Response(403)

    with httpx.Client(base_url=F.BASE, transport=httpx.MockTransport(handler)) as c:
        F.fetch([2026], feeds=["race_list_basic", "weekend-feed"], c=c, today=TODAY, echo=lambda *_: None)
        served[path] = b'{"stage": "final"}'
        F.fetch([2026], feeds=["weekend-feed"], c=c, today=TODAY, echo=lambda *_: None)
        assert (raw / "2026/1/5630/weekend-feed.json").read_bytes() == b'{"stage": "final"}'
        n = asked.count(path)
        F.fetch([2026], feeds=["weekend-feed"], c=c, today=TODAY + timedelta(days=F.RECENT_DAYS + 1), echo=lambda *_: None)
    assert asked.count(path) == n                                                   # no longer recent: kept as final
