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
