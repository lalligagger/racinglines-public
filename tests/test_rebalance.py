"""Weekend taker strategy (racinglines/markets/strategies/taker_weekend.py): synthetic stages, no database."""

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
