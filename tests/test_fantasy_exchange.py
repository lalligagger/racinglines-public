"""First-cut manual trading, the pure parts (fantasy/exchange.py): the walk, the NO side, the fee, and the guard that
fantasy code never reaches an order path. No database."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.quick
def test_buy_walks_ask_levels_to_the_limit():
    from racinglines.fantasy import exchange as FX
    asks = [(0.41, 120), (0.42, 300), (0.44, 500)]          # docs/fantasy-trading.md worked example
    assert FX.walk(asks, 200, 0.42) == [(0.41, 120), (0.42, 80)]
    assert FX.walk(asks, 1000, 0.42) == [(0.41, 120), (0.42, 300)]          # stops at the limit, not at 0.44
    assert FX.walk(asks, 10, 0.40) == []


@pytest.mark.quick
def test_depth_cap_makes_a_partial_fill():
    from racinglines.fantasy import exchange as FX
    asks = [(0.30 + i / 100, 1) for i in range(15)]
    fills = FX.walk(asks, 100, 0.99)
    assert len(fills) == FX.DEPTH and sum(s for _, s in fills) == FX.DEPTH        # only the visible depth fills


@pytest.mark.quick
def test_sell_closes_at_the_bid_and_never_shorts():
    from racinglines.fantasy import exchange as FX
    bids = [(0.55, 50), (0.54, 100), (0.50, 100)]
    assert FX.walk(bids, 120, 0.54, buy=False) == [(0.55, 50), (0.54, 70)]
    assert FX.walk(bids, 10, 0.56, buy=False) == []                               # nothing at or above the limit


@pytest.mark.quick
def test_yes_to_no_derives_prices():
    from racinglines.fantasy import exchange as FX
    bids, asks = [(0.39, 150), (0.38, 400)], [(0.41, 120), (0.42, 300)]
    no_bids, no_asks = FX.yes_to_no(bids, asks)
    assert no_asks == [(0.61, 150), (0.62, 400)] and no_bids == [(0.59, 120), (0.58, 300)]


@pytest.mark.quick
def test_fee_kalshi_matches_expected():
    from racinglines.fantasy import exchange as FX
    from racinglines.markets import venue_replay as VR
    assert FX.fee("kalshi", [(0.41, 120), (0.42, 80)]) == 3.40                    # 3.39612 rounded up, once per order
    assert FX.fee("kalshi", [(0.55, 10)]) == 0.18                                 # 0.17325
    assert FX.fee("kalshi", [(0.61, 100)]) == 1.67
    for p, c in ((0.55, 10), (0.07, 33), (0.5, 1)):
        assert FX.fee("kalshi", [(p, c)]) == VR.Kalshi.taker_fee(p, c)            # single level = the replay's fee
    assert FX.fee("polymarket", [(0.41, 120)]) == 0.0


@pytest.mark.quick
def test_levels_drop_bad_rows():
    from racinglines.fantasy import exchange as FX
    assert FX.levels('[[0.4, 10], [1.2, 5], ["x", 1], [0.3, 0]]') == [(0.4, 10.0)]


@pytest.mark.quick
def test_rate_limit_per_user():
    from racinglines.fantasy import exchange as FX
    FX._HITS.clear()
    assert all(FX.rate_ok(-1, now=1000 + i) for i in range(FX.RATE_MINUTE))
    assert not FX.rate_ok(-1, now=1000 + FX.RATE_MINUTE)
    assert FX.rate_ok(-1, now=1100)                                                # a minute later
    FX._HITS.clear()


@pytest.mark.quick
def test_fantasy_code_never_touches_the_order_path():
    for f in (ROOT / "racinglines" / "fantasy").glob("*.py"):
        src = f.read_text()
        for bad in ("polymarket.trade", "polymarket import trade", "kalshi.trade", "kalshi import trade", "post_order"):
            assert bad not in src, f"{f.name} mentions {bad}"
    code = ("import sys; import racinglines.fantasy.exchange, racinglines.fantasy.ledger; "
            "bad = [m for m in sys.modules if m.endswith(('polymarket.trade', 'kalshi.trade'))]; "
            "print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.quick
def test_off_unless_switched_on_or_staging(monkeypatch):
    from racinglines.fantasy import ledger as FL
    monkeypatch.delenv("RACINGLINES_FANTASY", raising=False)
    monkeypatch.delenv("RACINGLINES_ENV", raising=False)
    assert not FL.on()
    monkeypatch.setenv("RACINGLINES_ENV", "staging")
    assert FL.on()
    monkeypatch.setenv("RACINGLINES_FANTASY", "0")
    assert not FL.on()
    monkeypatch.delenv("RACINGLINES_ENV")
    monkeypatch.setenv("RACINGLINES_FANTASY", "1")
    assert FL.on()


@pytest.mark.quick
def test_score_is_roi_times_sqrt_trades_from_min_trades():
    """The leaderboard's score (fantasy/ledger.score): ROI = P&L / staked, score = ROI x sqrt(trades), none below
    MIN_TRADES or with nothing staked."""
    from racinglines.fantasy import ledger as FL
    n = FL.MIN_TRADES
    roi, s = FL.score(20.0, 200.0, n)
    assert roi == pytest.approx(0.1) and s == pytest.approx(round(0.1 * n ** 0.5, 4))
    roi, s = FL.score(-50.0, 100.0, 4 * n)
    assert roi == pytest.approx(-0.5) and s == pytest.approx(-0.5 * (4 * n) ** 0.5, abs=1e-4)
    assert FL.score(20.0, 200.0, n - 1) == (pytest.approx(0.1), None)          # too few trades to be ranked
    assert FL.score(5.0, 0.0, n + 3) == (None, None)                          # nothing staked: no ROI
    # more trades at the same ROI score higher
    assert FL.score(10.0, 100.0, 4 * n)[1] > FL.score(10.0, 100.0, n)[1]


@pytest.mark.quick
def test_alpha_layout_switch(monkeypatch):
    """web/layout.alpha(): RACINGLINES_LAYOUT=alpha|classic wins; unset, it follows the fantasy switch (staging)."""
    from racinglines.web import layout as L
    for k in ("RACINGLINES_LAYOUT", "RACINGLINES_FANTASY", "RACINGLINES_ENV"):
        monkeypatch.delenv(k, raising=False)
    assert not L.alpha()
    monkeypatch.setenv("RACINGLINES_ENV", "staging")
    assert L.alpha()
    monkeypatch.setenv("RACINGLINES_LAYOUT", "classic")
    assert not L.alpha()
    monkeypatch.delenv("RACINGLINES_ENV")
    monkeypatch.setenv("RACINGLINES_LAYOUT", "alpha")
    assert L.alpha()
    admin, pro = dict(role="admin"), dict(role="pro")
    assert L.hidden("/live", pro) and L.hidden("/book/quotes", pro) and L.hidden("/live/f1", None)
    assert not L.hidden("/live", admin) and not L.hidden("/markets", pro) and not L.hidden("/trade", pro)
    monkeypatch.setenv("RACINGLINES_LAYOUT", "classic")
    assert not L.hidden("/live", pro) and not L.hidden("/book", pro)
