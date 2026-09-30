"""The championship sleeve (pipelines/season_strategy.py, `f1 season-strategy --paper`): the paper_positions rows
built from a replay, Kalshi's fee-based costs, and storing them without touching the weekend records."""

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.markets.strategies import season as SS
from racinglines.pipelines import season_strategy as SE

T0 = pd.Timestamp("2026-03-01", tz="UTC")
P = SS.SeasonParams(min_edge=0.05, stake_per_edge=100, max_stake=50, capital=1000, min_trade=0.0,
                    exec_delay=timedelta(hours=1))


def mk(key, prices, cost=0.01, outcome=None, closed_h=None, kind="champion"):
    ts = np.array([T0 + timedelta(hours=h) for h, _ in prices])
    return SS.SeasonMarket(key=key, kind=kind, subject=key.upper(), ts=ts, px=np.array([p for _, p in prices], float),
                           cost=cost, outcome=outcome, closed_at=T0 + timedelta(hours=closed_h) if closed_h else None)


def test_sleeve_positions_carry_the_shares_the_mark_and_the_outcome():
    won = mk("w", ((0, 0.30),), outcome=True, closed_h=48)                 # bought at the decision, settled YES later
    live = mk("o", ((0, 0.30), (24, 0.50)))                                  # still open, marked at the latest price
    idle = mk("i", ((0, 0.30),))                                             # no edge: never traded, no row
    dec = [dict(t=T0, label="pre-season", fairs={"w": 0.40, "o": 0.40, "i": 0.30})]
    now = T0 + timedelta(hours=72)
    res = SS.replay({"w": won, "o": live, "i": idle}, dec, P, now=T0 + timedelta(hours=1), marks=[T0 + timedelta(hours=1)])
    rows = {r["market_key"]: r for r in SE.sleeve_positions({"w": won, "o": live, "i": idle}, res["trades"], now)}
    assert set(rows) == {"w", "o"}
    sh = 10 / 0.31
    assert rows["w"]["yes_shares"] == pytest.approx(sh) and rows["w"]["cash"] == pytest.approx(-10)
    assert rows["w"]["outcome"] is True and rows["o"]["outcome"] is None
    assert rows["o"]["mark"] == 0.50 and rows["o"]["no_shares"] == 0.0
    assert rows["o"]["kind"] == "champion" and rows["o"]["subject"] == "O"
    # valued as the track record values paper positions: settled at the outcome, open at the mark
    assert SE.sleeve_pnl(list(rows.values())) == pytest.approx((sh - 10) + (sh * 0.50 - 10))
    # before the market closed, the same rows carry no outcome
    early = {r["market_key"]: r for r in SE.sleeve_positions({"w": won, "o": live}, res["trades"], T0 + timedelta(hours=2))}
    assert early["w"]["outcome"] is None and early["w"]["mark"] == 0.30


def test_a_closed_position_is_stored_as_zero_shares_not_minus_zero():
    m = mk("a", ((0, 0.30), (30, 0.30)))
    dec = [dict(t=T0, label="d1", fairs={"a": 0.40}), dict(t=T0 + timedelta(hours=29), label="d2", fairs={"a": 0.30})]
    res = SS.replay({"a": m}, dec, P, now=T0 + timedelta(hours=40), marks=[T0 + timedelta(hours=40)])
    (row,) = SE.sleeve_positions({"a": m}, res["trades"], T0 + timedelta(hours=40))
    assert row["yes_shares"] == 0.0 and str(row["yes_shares"]) == "0.0"
    assert row["cash"] == pytest.approx(-(10 / 0.31) * 0.02)               # bought at +1c, sold at -1c


def test_kalshi_costs_are_the_taker_fee_at_the_price_plus_slippage():
    px = pd.DataFrame(dict(token_id=["k", "k"], ts=[T0, T0 + timedelta(hours=5)], price=[0.5, 0.9]))
    by = dict(tuple(px.groupby("token_id")))
    fee = SE.KALSHI_TAKER_FEE
    assert SE.kalshi_costs(by, ["k"])["k"] == pytest.approx(fee * 0.9 * 0.1 + SE.SLIPPAGE)         # latest price
    assert SE.kalshi_costs(by, ["k"], asof=T0 + timedelta(hours=1))["k"] == pytest.approx(fee * 0.25 + SE.SLIPPAGE)
    worst = fee * 0.25 + SE.SLIPPAGE
    assert SE.kalshi_costs(by, ["k"], asof=T0 - timedelta(hours=1))["k"] == pytest.approx(worst)   # nothing yet
    assert SE.kalshi_costs(by, ["none"])["none"] == pytest.approx(worst)                            # no prices at all
    assert SE.sleeve_venue("kalshi") == "season:kalshi"


def test_store_sleeve_leaves_the_weekend_records_alone(test_engine):
    from racinglines.pipelines import story as ST
    sig = dict(profile="A · core taker (update)", strategy="update", event_key="2026-15", market_key="tok-w",
               kind="race_win", subject="X", stage="after FP1", dedupe="after FP1", action="buy", side="YES",
               shares=10.0, limit_price=0.4, price=0.4, status="filled_paper", signal_ts=pd.Timestamp("2026-09-25", tz="UTC"))
    with test_engine.begin() as c:
        uid = c.execute(text("INSERT INTO users (username, password_hash, role) VALUES ('sleevetest', 'x', 'maker') "
                             "RETURNING id")).scalar()
        c.execute(text("""INSERT INTO strategy_signals (user_id, profile, strategy, event_key, market_key, kind, subject,
                            stage, dedupe, action, side, shares, limit_price, price, status, signal_ts)
                          VALUES (:u, :profile, :strategy, :event_key, :market_key, :kind, :subject, :stage, :dedupe,
                                  :action, :side, :shares, :limit_price, :price, :status, :signal_ts)"""), dict(sig, u=uid))
        for venue, mark in (("polymarket", 0.6), ("kalshi", 0.55)):
            c.execute(text("""INSERT INTO paper_positions (user_id, event_key, market_key, kind, subject, yes_shares,
                                no_shares, cash, mark, venue)
                              VALUES (:u, '2026-15', 'tok-w', 'race_win', 'X', 10, 0, -4, :m, :v)"""),
                      dict(u=uid, m=mark, v=venue))
        before = {v: ST.track_record(c, uid, v) for v in ("polymarket", "kalshi", "private", "all")}
    assert [r["event_key"] for r in before["polymarket"]] == ["2026-15"] and before["polymarket"][0]["pnl"] == pytest.approx(2.0)

    def out(exchange, rows):
        return dict(venue=SE.sleeve_venue(exchange), event_key=SE.SLEEVE_EVENT.format(year=2026), positions=rows)
    row = dict(market_key="champ-a", kind="champion", subject="A", yes_shares=20.0, no_shares=0.0, cash=-6.0, mark=0.5,
               outcome=None)
    with test_engine.begin() as c:
        assert SE.store_sleeve(c, uid, out("polymarket", [row])) == 1
        assert SE.store_sleeve(c, uid, out("kalshi", [row, dict(row, market_key="champ-b", subject="B")])) == 2
        assert SE.store_sleeve(c, uid, out("kalshi", [dict(row, market_key="champ-b", subject="B", mark=0.7)])) == 1   # replaced
        stored = c.execute(text("SELECT venue, market_key, mark FROM paper_positions WHERE user_id = :u "
                                "AND venue LIKE 'season:%' ORDER BY venue, market_key"), dict(u=uid)).all()
        assert [tuple(r) for r in stored] == [("season:kalshi", "champ-b", 0.7), ("season:polymarket", "champ-a", 0.5)]
        after = {v: ST.track_record(c, uid, v) for v in ("polymarket", "kalshi", "private", "all")}
        weekend = c.execute(text("SELECT count(*) FROM paper_positions WHERE user_id = :u AND venue IN ('polymarket', 'kalshi')"),
                            dict(u=uid)).scalar()
    assert weekend == 2
    assert after == before                                                    # every venue's record, the sleeve invisible


def test_og_costs_are_its_flat_fee_plus_slippage():
    from racinglines.markets.venue_replay import OG
    assert SE.og_costs(["o1", "o2"]) == {t: pytest.approx(OG.fee_per_contract() + SE.SLIPPAGE) for t in ("o1", "o2")}
    assert SE.MIN_VOLUME_BY.get("og") == 0 and "polymarket" not in SE.MIN_VOLUME_BY   # Polymarket keeps MIN_VOLUME


def test_og_markets_read_the_replay_venues_prices_and_drop_the_empty_books_half(monkeypatch):
    from racinglines.markets import store as MS
    ts = [T0, T0 + timedelta(hours=1), T0 + timedelta(hours=2)]
    tables = dict(prices=pd.DataFrame(dict(token_id=["o"] * 3, ts=ts, price=[0.5, 0.04, 0.5])),
                  trades=pd.DataFrame(dict(token_id=["o"], ts=[T0 + timedelta(hours=3)], price=[0.05], size=[10.0])),
                  books=pd.DataFrame(dict(token_id=["o"], ts=[T0 + timedelta(hours=4)], best_bid=[0.0], best_ask=[0.03])))
    seen = []
    monkeypatch.setattr(MS, "read", lambda conn, name, tokens=None, root=None, **kw: seen.append(root) or tables[name])
    links = pd.DataFrame([dict(token_id="o", prediction="champion", athlete="Lando Norris", params=None, group_title=None,
                               closed=False, resolved_yes=None)])
    (mk,) = SE.build_markets(None, links, exchange="og").values()
    assert list(mk.px) == [0.04, 0.05, 0.03]                  # the two 0.50s dropped; trade, then the ask-only book
    assert mk.ts[0] == T0 + timedelta(hours=1) and str(mk.ts[0].tz) == "UTC"
    assert mk.cost == pytest.approx(SE.og_costs(["o"])["o"]) and mk.outcome is None
    assert set(seen) == {MS.root_for("og")}                    # OG.com's own archive tree
