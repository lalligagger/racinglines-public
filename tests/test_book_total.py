"""The Positions chart of the private book: each live event's running P&L is summed by time, not interleaved."""

import pandas as pd


def test_book_total_sums_each_event_at_every_poll_time(monkeypatch):
    from racinglines.pipelines import live as LV
    from racinglines.web import views
    curves = {
        "ev-a": [(pd.Timestamp("2026-09-27 10:00"), 100.0), (pd.Timestamp("2026-09-27 12:00"), 500.0)],
        "ev-b": [(pd.Timestamp("2026-10-04 10:00"), -50.0), (pd.Timestamp("2026-10-05 09:00"), 200.0)],
    }
    monkeypatch.setattr(LV, "book_curve", lambda ev, maker=True: curves[ev])
    got = views.book_total(["ev-a", "ev-b"])
    assert got == [
        (pd.Timestamp("2026-09-27 10:00"), 100.0),
        (pd.Timestamp("2026-09-27 12:00"), 500.0),
        (pd.Timestamp("2026-10-04 10:00"), 450.0),      # ev-a carried forward at 500, ev-b at -50
        (pd.Timestamp("2026-10-05 09:00"), 700.0),      # ev-a 500 + ev-b 200
    ]


def test_book_total_with_no_polls_is_empty(monkeypatch):
    from racinglines.pipelines import live as LV
    from racinglines.web import views
    monkeypatch.setattr(LV, "book_curve", lambda ev, maker=True: [])
    assert views.book_total(["ev-a"]) == []
