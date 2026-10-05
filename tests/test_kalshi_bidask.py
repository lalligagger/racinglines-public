from racinglines.db.models import MarketPriceHistory
from racinglines.markets.kalshi.sync import history_rows


def test_kalshi_candles_store_bid_ask_and_keep_price():
    rows = history_rows(
        "KXF1RACE-26SIN-VER",
        [
            {
                "end_period_ts": 1791806400,
                "price": {"close_dollars": "0.3100"},
                "yes_bid": {"close_dollars": "0.3000"},
                "yes_ask": {"close_dollars": "0.3300"},
            },
            {
                "end_period_ts": 1791810000,
                "price": {},
                "yes_bid": {"close_dollars": "0.3200"},
                "yes_ask": {"close_dollars": "0.3400"},
            },
            {
                "end_period_ts": 1791813600,
                "price": {},
                "yes_bid": {"close_dollars": "0.0000"},
                "yes_ask": {"close_dollars": "1.0000"},
            },
        ],
    )

    assert [(row["price"], row["bid"], row["ask"]) for row in rows] == [
        (0.31, 0.30, 0.33),
        (0.33, 0.32, 0.34),
    ]
    columns = MarketPriceHistory.__table__.columns
    assert columns["bid"].nullable and columns["ask"].nullable


def test_one_sided_candles_give_no_row_because_price_is_required():
    rows = history_rows("KXF1RACE-26SIN-VER", [
        {"end_period_ts": 1791806400, "price": {}, "yes_bid": {"close_dollars": "0.2000"}, "yes_ask": {}},
        {"end_period_ts": 1791810000, "price": {}, "yes_bid": {}, "yes_ask": {"close_dollars": "0.2500"}},
        {"end_period_ts": 1791813600, "price": {"close_dollars": "0.2200"}, "yes_bid": {}, "yes_ask": {"close_dollars": "0.2500"}},
    ])
    assert [(r["price"], r["bid"], r["ask"]) for r in rows] == [(0.22, None, 0.25)]
    assert not MarketPriceHistory.__table__.columns["price"].nullable


CANDLES = [
    {"end_period_ts": 1791806400, "price": {"close_dollars": "0.3100"},
     "yes_bid": {"close_dollars": "0.3000"}, "yes_ask": {"close_dollars": "0.3300"}},
    {"end_period_ts": 1791810000, "price": {}, "yes_bid": {"close_dollars": "0.3200"}, "yes_ask": {}},
]


class FakeKalshi:
    def __init__(self):
        self.calls = 0

    def candlesticks(self, series, ticker, start_ts, end_ts, period=60):
        self.calls += 1
        return CANDLES


def test_saved_raw_candles_reimport_to_the_same_rows(test_engine, monkeypatch, tmp_path):
    import json
    from datetime import datetime, timezone

    from sqlalchemy import text

    from racinglines.db.config import get_session
    from racinglines.markets.kalshi import sync as KS
    tok = "KXF1RACE-26TEST-RAW"
    monkeypatch.setattr(KS, "_tickers", lambda conn, events, **kw: [(tok, "KXF1RACE-26TEST", "KXF1RACE")])
    url = test_engine.url.render_as_string(hide_password=False)
    t0, t1 = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 2, tzinfo=timezone.utc)
    q = text("SELECT ts, price, bid, ask FROM market_price_history WHERE token_id = :t ORDER BY ts")
    raw, kc = tmp_path / "raw", FakeKalshi()
    try:
        with test_engine.connect() as c, get_session(url) as s:
            assert KS.fetch_history(s, c, ["KXF1RACE-26TEST"], t0, t1, 60, kc=kc, save_raw=raw) == 1
            saved = json.loads((raw / "KXF1RACE" / f"{tok}.json").read_text())
            assert saved["candlesticks"] == CANDLES and saved["ticker"] == tok and saved["period"] == 60
            before = c.execute(q, dict(t=tok)).all()
            assert [(r.price, r.bid, r.ask) for r in before] == [(0.31, 0.30, 0.33)]
            s.execute(text("DELETE FROM market_price_history WHERE token_id = :t"), dict(t=tok))
            s.commit()
            assert KS.fetch_history(s, c, ["KXF1RACE-26TEST"], t0, t1, 60, from_raw=raw) == 1
            assert c.execute(q, dict(t=tok)).all() == before and kc.calls == 1          # no network on re-import
    finally:
        with test_engine.begin() as c:
            c.execute(text("DELETE FROM market_price_history WHERE token_id = :t"), dict(t=tok))
