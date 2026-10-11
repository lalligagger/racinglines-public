"""Owner rule (2026-10-10): when a session ends, the model re-runs before anything is re-priced. An F1 model price
older than the latest finished session is flagged stale, and a slip gets no model price from it."""
import pandas as pd
import pytest

T = pd.Timestamp
STAGES = [("pre-weekend", T("2026-10-09 07:30")), ("after FP1", T("2026-10-09 09:45")),
          ("after SQ", T("2026-10-09 13:45")), ("after S", T("2026-10-10 10:30")), ("after Q", T("2026-10-10 14:45"))]
INFO = dict(competition="f1_wdc", status="scheduled", source_key="2026-17")


@pytest.fixture
def venues(monkeypatch):
    from racinglines.markets import venues as V
    monkeypatch.setattr(V, "_f1_stages", lambda key: STAGES)
    return V


def _run_as_of(monkeypatch, V, as_of):
    monkeypatch.setattr(V.data, "q", lambda conn, sql, **kw: pd.DataFrame({"as_of": [T(as_of)]}))


def test_a_run_before_the_last_finished_session_is_stale(venues, monkeypatch):
    _run_as_of(monkeypatch, venues, "2026-10-09 07:30")          # run 9781: the book's opening, before FP1
    s = venues.stale_model(None, INFO, 9781, now=T("2026-10-10 09:30"))
    assert s["stage"] == "after SQ" and s["due"] == T("2026-10-09 13:45")
    assert s["why"].startswith("model not updated since after SQ: run 9781")


def test_a_run_priced_on_the_last_session_is_fresh(venues, monkeypatch):
    _run_as_of(monkeypatch, venues, "2026-10-09 13:45")
    assert venues.stale_model(None, INFO, 1, now=T("2026-10-10 09:30")) is None


def test_before_any_session_ends_or_after_the_race_nothing_is_stale(venues, monkeypatch):
    _run_as_of(monkeypatch, venues, "2026-10-05 00:00")
    assert venues.stale_model(None, INFO, 1, now=T("2026-10-09 08:00")) is None       # only the pre-weekend stage
    assert venues.stale_model(None, dict(INFO, status="completed"), 1, now=T("2026-10-12")) is None
    assert venues.stale_model(None, dict(INFO, competition="nascar_cup"), 1, now=T("2026-10-10 09:30")) is None


def test_no_schedule_no_verdict(monkeypatch):
    from racinglines.markets import venues as V
    monkeypatch.setattr(V, "_f1_stages", lambda key: None)
    assert V.stale_model(None, INFO, 1, now=T("2026-10-10 09:30")) is None


def test_a_slip_leg_gets_no_model_price_from_a_stale_run(monkeypatch):
    from racinglines.books import slips as B
    from racinglines.markets import venues as V
    stale = dict(stage="after SQ", why="model not updated since after SQ")
    monkeypatch.setattr(V, "race_info", lambda conn, r: INFO)
    monkeypatch.setattr(V, "pricing_run", lambda conn, info: dict(run_id=9781, source="live stage", stale=stale))

    class DB:
        conn, cache = None, {}
    leg = dict(kind="race_win", race_id=135, competition="f1_wdc", side="yes")
    assert B._model(DB, leg, None) == (None, 9781, "live stage", "model not updated since after SQ")
