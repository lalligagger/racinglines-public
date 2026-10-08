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


def _kalshi_venue(monkeypatch, prices, books):
    import pandas as pd

    from racinglines.markets import store as MS
    from racinglines.markets import venue_replay as VR
    tok = "KXF1RACE-26SIN-VER"
    links = pd.DataFrame(dict(token_id=[tok], condition_id=["KXF1RACE-26SIN"], prediction=["race_win"],
                              athlete_id=[1], params=[{}], exchange=["kalshi"]))
    frames = dict(prices=pd.DataFrame(prices).assign(token_id=tok),
                  trades=pd.DataFrame(columns=["token_id", "ts", "price", "size"]),
                  books=pd.DataFrame(books, columns=["ts", "best_bid", "best_ask"]).assign(token_id=tok))
    monkeypatch.setattr(MS, "read", lambda conn, store, **kw: frames[store])
    return VR.Kalshi(None, links, "2026-10-10 00:00", "2026-10-11 00:00"), tok


def test_kalshi_quote_prefers_a_fresh_book_then_the_candle(monkeypatch):
    import pandas as pd
    T = lambda s: pd.Timestamp(f"2026-10-10 {s}", tz="UTC")          # noqa: E731
    v, tok = _kalshi_venue(monkeypatch,
                           dict(ts=[T("12:00"), T("13:00")], price=[0.31, 0.33], bid=[0.30, None], ask=[0.33, None]),
                           dict(ts=[T("12:20")], best_bid=[0.28], best_ask=[0.35]))
    at = lambda s: pd.Timestamp(f"2026-10-10 {s}")                     # noqa: E731
    assert v.quote(tok, at("11:59")) is None                           # nothing yet: no look-ahead
    assert v.quote(tok, at("12:10")) == (0.30, 0.33)                   # the candle's closing quote
    assert v.quote(tok, at("12:25")) == (0.28, 0.35)                   # a book snapshot 5 min old wins
    assert v.quote(tok, at("12:45")) == (0.30, 0.33)                   # the book is 25 min old: back to the candle
    assert v.quote(tok, at("13:05")) is None                           # the latest candle quotes no side
    assert v.price(tok, at("13:05")) == 0.33                           # price() is unchanged


def test_quoted_stages_take_at_the_touch_and_unquoted_at_the_price():
    from racinglines.markets.strategies import taker_weekend as RB
    p = RB.TakerParams(cost=0.01, taker_fee=0.0, min_edge=0.05, stake_per_edge=250.0, max_stake=50.0)
    st = lambda **kw: [dict(label="s", t=None, tradeable=True, **kw)]   # noqa: E731
    yes = RB.run_market(st(fair=0.60, price=0.50, bid=0.48, ask=0.53), True, p)["trades"]
    assert [(t["side"], round(t["price"], 4)) for t in yes] == [("YES", 0.54)]          # ask + cost
    no = RB.run_market(st(fair=0.40, price=0.50, bid=0.48, ask=0.53), False, p)["trades"]
    assert [(t["side"], round(t["price"], 4)) for t in no] == [("NO", 0.53)]            # 1 - bid + cost
    # mid edge is 6 pts but fair - ask is only 2: the spread eats the edge, no trade
    assert RB.run_market(st(fair=0.56, price=0.50, bid=0.47, ask=0.54), True, p)["trades"] == []
    old = RB.run_market(st(fair=0.56, price=0.50), True, p)["trades"]
    assert [(t["side"], round(t["price"], 4)) for t in old] == [("YES", 0.51)]          # no quote: as before


def test_long_history_ranges_are_asked_in_windows():
    from datetime import datetime, timedelta, timezone

    from racinglines.markets.kalshi import sync as KS

    class Recorder:
        def __init__(self):
            self.windows = []

        def candlesticks(self, series, ticker, start_ts, end_ts, period=60):
            self.windows.append((start_ts, end_ts))
            return [{"end_period_ts": int(end_ts)}]

    a = datetime(2025, 1, 1, tzinfo=timezone.utc)
    b = a + timedelta(hours=KS.MAX_CANDLES * 2 + 10)
    kc = Recorder()
    assert len(KS._candles(kc, "S", "T", a, b, 60)) == 3
    assert kc.windows[0][0] == a.timestamp() and kc.windows[-1][1] == b.timestamp()
    assert all(e - s <= KS.MAX_CANDLES * 3600 for s, e in kc.windows)
    assert all(kc.windows[i][1] == kc.windows[i + 1][0] for i in range(len(kc.windows) - 1))
