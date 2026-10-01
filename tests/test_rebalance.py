"""Weekend taker strategy (racinglines/markets/strategies/taker_weekend.py): synthetic stages, no database."""

import math

import pytest

from racinglines.markets.strategies import taker_weekend as RB

P = RB.TakerParams(min_edge=0.05, stake_per_edge=100, max_stake=50, cost=0.01, min_trade=0.0)


def st(label, fair, price, tradeable=True):
    return dict(label=label, t=label, fair=fair, price=price, tradeable=tradeable)


def test_no_edge_no_trade():
    r = RB.run_market([st("pre", 0.30, 0.28)], True, P)
    assert r["trades"] == [] and r["pnl"] == 0


def test_buy_yes_and_settle():
    r = RB.run_market([st("pre", 0.40, 0.30)], True, P)           # 10 pt edge -> $10 at 0.31
    (tr,) = r["trades"]
    assert tr["side"] == "YES" and tr["price"] == pytest.approx(0.31)
    assert tr["shares"] == pytest.approx(10 / 0.31)
    assert r["pnl"] == pytest.approx(10 / 0.31 - 10)
    assert r["pnl"] == pytest.approx(tr["pnl"])                    # attribution adds up


def test_buy_no_when_market_too_high():
    r = RB.run_market([st("pre", 0.20, 0.40)], False, P)          # NO at 0.60 + cost
    (tr,) = r["trades"]
    assert tr["side"] == "NO" and tr["price"] == pytest.approx(0.61)
    assert r["pnl"] > 0


def test_update_closes_when_edge_disappears_and_pays_costs():
    stages = [st("pre", 0.40, 0.30), st("after Q", 0.50, 0.50)]
    r = RB.run_market(stages, None, RB.TakerParams(**{**P.__dict__, "mode": "update"}))
    assert [t["stage"] for t in r["trades"]] == ["pre", "after Q"]
    assert r["yes"] == 0                                             # flat after the edge went away
    assert r["cash"] == pytest.approx(10 / 0.31 * 0.49 - 10)         # sold at 0.50 - cost


def test_modes():
    stages = [st("pre", 0.40, 0.30), st("FP1", 0.40, 0.33), st("after Q", 0.60, 0.45)]
    upd = RB.run_market(stages, True, RB.TakerParams(**{**P.__dict__, "mode": "update"}))
    hold = RB.run_market(stages, True, RB.TakerParams(**{**P.__dict__, "mode": "hold"}))
    last = RB.run_market(stages, True, RB.TakerParams(**{**P.__dict__, "mode": "last"}))
    assert {t["stage"] for t in hold["trades"]} == {"pre"}
    assert {t["stage"] for t in last["trades"]} == {"after Q"}
    assert len(upd["trades"]) == 3


def test_untradeable_stage_keeps_position():
    stages = [st("pre", 0.40, 0.30), st("FP1", 0.10, 0.50, tradeable=False)]
    r = RB.run_market(stages, False, P)
    assert len(r["trades"]) == 1 and r["yes"] > 0


def test_stake_cap_and_flip():
    r = RB.run_market([st("pre", 0.95, 0.10), st("Q", 0.05, 0.60)], False, P)
    buys = [t for t in r["trades"] if t["shares"] > 0]
    assert buys[0]["shares"] * buys[0]["price"] == pytest.approx(50)    # capped at max_stake
    assert r["yes"] == 0 and r["no"] > 0                                 # flipped to NO


def test_early_mode_skips_late_stages():
    """The stage-aware taker trades up to FP2 and holds through FP3 and qualifying."""
    stages = [st("pre-weekend", 0.40, 0.30), st("after FP3", 0.60, 0.40), st("after Quali", 0.70, 0.40)]
    r = RB.run_market(stages, True, RB.TakerParams(**{**P.__dict__, "mode": "early"}))
    assert [t["stage"] for t in r["trades"]] == ["pre-weekend"]


# --- thin markets (thin_edge_mult): a stage under the volume floor that a recorded book vouches for ----------

def thin(label, fair, price, depth_yes=100.0, depth_no=100.0):
    return dict(label=label, t=label, fair=fair, price=price, tradeable=False, thin=True,
                depth_yes=depth_yes, depth_no=depth_no)


PT = RB.TakerParams(**{**P.__dict__, "thin_edge_mult": 2.0})


def test_thin_markets_are_skipped_unless_asked():
    r = RB.run_market([thin("after Q", 0.30, 0.05)], True, P)
    assert r["trades"] == []
    r = RB.run_market([thin("after Q", 0.30, 0.05)], True, RB.TakerParams(**{**P.__dict__, "thin_edge_mult": None}))
    assert r["trades"] == []


def test_thin_market_traded_at_twice_the_edge_and_capped_at_the_book():
    (tr,) = RB.run_market([thin("after Q", 0.30, 0.05, depth_yes=1e6)], True, PT)["trades"]     # 25 pts >= 2 x 5
    assert tr["side"] == "YES" and tr["shares"] == pytest.approx(25 / 0.06)         # $100 x 25 pts = $25 stake, book is deep
    (tr,) = RB.run_market([thin("after Q", 0.30, 0.05, depth_yes=40.0)], True, PT)["trades"]
    assert tr["shares"] == pytest.approx(40.0)                                       # the book holds 40 shares
    assert RB.run_market([thin("after Q", 0.30, 0.05, depth_yes=0.0)], True, PT)["trades"] == []


def test_thin_market_needs_the_multiple_of_the_edge():
    assert RB.run_market([thin("after Q", 0.12, 0.05)], True, PT)["trades"] == []   # 7 pts < 2 x 5
    assert len(RB.run_market([thin("after Q", 0.16, 0.05)], True, PT)["trades"]) == 1   # 11 pts


def test_thin_market_buys_no_from_the_bid_side_and_never_sells():
    (tr,) = RB.run_market([thin("after Q", 0.10, 0.40, depth_no=25.0)], False, PT)["trades"]
    assert tr["side"] == "NO" and tr["shares"] == pytest.approx(25.0)
    stages = [st("FP3", 0.40, 0.30), thin("after Q", 0.50, 0.50)]                    # the edge is gone: a liquid stage sells
    upd = RB.TakerParams(**{**PT.__dict__, "mode": "update"})
    r = RB.run_market(stages, True, upd)
    assert len(r["trades"]) == 1 and r["yes"] > 0                                     # ... a thin one is left alone


def test_liquid_stages_are_unchanged_by_the_setting():
    stages = [st("pre", 0.40, 0.30), st("after Q", 0.50, 0.50)]
    a = RB.run_market(stages, True, RB.TakerParams(**{**P.__dict__, "mode": "update"}))
    b = RB.run_market(stages, True, RB.TakerParams(**{**PT.__dict__, "mode": "update"}))
    assert a == b


def test_venue_taker_fee_is_paid_per_order_rounded_up():
    from dataclasses import replace
    k = replace(P, taker_fee=0.07)                                 # Kalshi's rate
    r = RB.run_market([st("pre", 0.40, 0.30)], True, k)
    (tr,) = r["trades"]
    n = 10 / (0.31 + 0.07 * 0.30 * 0.70)                           # sizing sees cost + fee
    fee = math.ceil(0.07 * n * 0.30 * 0.70 * 100) / 100            # per order, up to the cent
    assert tr["shares"] == pytest.approx(n)
    assert tr["price"] == pytest.approx(0.31 + fee / n)
    assert r["pnl"] == pytest.approx(n - n * tr["price"]) and r["pnl"] == pytest.approx(tr["pnl"])
    assert r["pnl"] < RB.run_market([st("pre", 0.40, 0.30)], True, P)["pnl"]


def test_zero_fee_rate_is_the_old_arithmetic():
    from dataclasses import replace
    a = RB.run_market([st("pre", 0.40, 0.30), st("q", 0.20, 0.35)], True, P)
    b = RB.run_market([st("pre", 0.40, 0.30), st("q", 0.20, 0.35)], True, replace(P, taker_fee=0.0))
    assert a == b
