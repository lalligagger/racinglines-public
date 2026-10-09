"""Positions must not multiply an event's ledger rows by its race categories."""

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session


@pytest.mark.parametrize("venue,sort", [("", ""), ("private", ""), ("private", "pnl")])
def test_multicategory_event_counts_each_private_position_once(test_engine, monkeypatch, venue, sort):
    from racinglines.db import models as M
    from racinglines.pipelines import profiles, live
    from racinglines.web import book_routes, views

    monkeypatch.setenv("RACINGLINES_SPORT_PAPER", "0")
    monkeypatch.setattr(profiles, "of_user", lambda c, u: None)
    monkeypatch.setattr(live, "book_curve", lambda *args: [])
    monkeypatch.setattr(book_routes, "polymarket_calls", lambda *args, **kwargs: [])
    monkeypatch.setattr(views, "render", lambda request, template, **ctx: ctx)
    with test_engine.connect() as c:
        transaction = c.begin()
        try:
            s = Session(bind=c)
            sport = M.Sport(code="position_count_test", name="Position test")
            league = M.League(code="position_count_test", name="Position test")
            s.add_all([sport, league])
            s.flush()
            comp = M.Competition(code="position_count_test", name="Position test",
                                 league_id=league.id, sport_id=sport.id)
            s.add(comp)
            s.flush()
            season = M.Season(competition_id=comp.id, year=2026)
            categories = [M.Category(competition_id=comp.id, code=code, name=code) for code in ("ME", "MJ")]
            s.add_all([season, *categories])
            s.flush()
            event = M.Event(season_id=season.id, source="test", source_key="position-count-event",
                            name="Position-count event", start_date=date(2026, 9, 27))
            s.add(event)
            s.flush()
            s.add_all([M.Race(event_id=event.id, category_id=cat.id, format={"event_name": "Position-count race"})
                       for cat in categories])
            s.flush()
            uid = c.execute(text("""INSERT INTO users (username, password_hash, role, prefs)
                                    VALUES ('position_count_test', 'x', 'pro', '{}') RETURNING id""")).scalar_one()
            c.execute(text("""INSERT INTO paper_positions
                              (user_id, venue, event_key, market_key, kind, subject, outcome, cash, yes_shares, no_shares)
                              VALUES (:u, 'private', 'position-count-event', 'position-count-market',
                                      'race_win', 'Test driver', true, 7, 3, 0)"""), dict(u=uid))
            request = SimpleNamespace(state=SimpleNamespace(user=dict(id=uid, role="pro")))
            ctx = views.positions_page(request, venue=venue, sort=sort, c=c)
            assert len(ctx["shown"]) == 1
            assert ctx["shown"][0]["event_name"] == "Position-count race"
            assert ctx["paper"]["n"] == 1
            assert ctx["paper"]["settled_pnl"] == 10
            assert ctx["venues"]["private"]["n"] == 1
            assert ctx["venues"]["private"]["pnl"] == 10
            assert ctx["vtotal"] == 10
            assert ctx["by_kind"][0]["pnl"] == 10
            assert ctx["weekends"][0]["pnl"] == 10
        finally:
            transaction.rollback()
