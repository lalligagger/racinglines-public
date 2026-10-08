"""The track record per venue: each exchange's record holds only its own signals and positions (OG.com included),
and the web helpers read the venues from the registry (no database for those)."""

import json

from sqlalchemy import text as T


def test_track_record_keeps_each_exchange_to_its_own_rows(test_engine):
    from racinglines.pipelines import story
    with test_engine.begin() as c:
        uid = c.execute(T("""INSERT INTO users (username, password_hash, role) VALUES ('venue-maker', 'x', 'pro')
                             RETURNING id""")).scalar()
        for venue, ev, pnl in (("polymarket", "2099-01", 3.0), ("kalshi", "2099-02", -1.0), ("og", "2099-03", 2.0)):
            c.execute(T("""INSERT INTO strategy_signals (user_id, profile, strategy, event_key, market_key, kind, subject, stage,
                             dedupe, action, side, shares, limit_price, fair, price, edge, heat, status, signal_ts, detail)
                           VALUES (:u, 'test', 'maker', :e, :mk, 'race_win', 'Zed', 'after FP2', :mk, 'fill', 'YES',
                             10, 0.4, 0.5, 0.4, 0.1, 1, 'done', now(), CAST(:d AS jsonb))"""),
                      dict(u=uid, e=ev, mk=f"tok-{venue}", d=json.dumps({} if venue == "polymarket" else dict(venue=venue))))
            c.execute(T("""INSERT INTO paper_positions (user_id, event_key, market_key, kind, subject, yes_shares, cash, outcome, venue)
                           VALUES (:u, :e, :mk, 'race_win', 'Zed', 0, :pnl, true, :v)"""),
                      dict(u=uid, e=ev, mk=f"tok-{venue}", pnl=pnl, v=venue))
        rec = {v: [(r["event_key"], r["pnl"]) for r in story.track_record(c, uid, v)] for v in ("polymarket", "kalshi", "og")}
    assert rec == {"polymarket": [("2099-01", 3.0)], "kalshi": [("2099-02", -1.0)], "og": [("2099-03", 2.0)]}


def test_venue_helpers_follow_the_registry():
    from racinglines.markets import venues as V
    from racinglines.web import views
    live = views._live_venues()
    assert "polymarket" in live and "private" in live
    assert ("kalshi" in live) == V.KALSHI_VENUE
    assert views._venue_order(["private", "og", "polymarket"]) == ["polymarket", "og", "private"]
    assert "og" in views._other_exchanges() and "polymarket" not in views._other_exchanges()
