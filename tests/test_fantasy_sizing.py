"""A registered player's followed strategy sized to their F$1,000 (fantasy/sizing.py, signals.for_player; owner decision
2026-10-12 19:47Z, decision log in docs/f1-roadmap.md): the scale and cap rule, the per-player re-run, and that the demo
accounts and the shared (backtest / sweep / replay) computation are unchanged."""

from dataclasses import replace

import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.fantasy import ledger as FL
from racinglines.fantasy import sizing as FS
from racinglines.markets.strategies import taker_weekend as RB
from racinglines.pipelines import signals as SG

EVENT = "2026-18"


def _stages(fair=0.60, price=0.40, day=2):
    return [dict(label="after FP1", t=pd.Timestamp(f"2026-10-0{day}"), fair=fair, price=price, tradeable=True),
            dict(label="after Quali", t=pd.Timestamp(f"2026-10-0{day + 1}"), fair=fair, price=price, tradeable=True)]


def _markets(n=3):
    return [dict(key=f"tok{i}", kind="race_win", subject=f"D{i}", outcome=None, stages=_stages()) for i in range(n)]


def _cost(positions):
    return sum(max(-p["cash"], 0.0) for p in positions)


# -- the rule ---------------------------------------------------------------------------------------------------------

def test_a_fresh_player_gets_scale_one_and_a_cap_of_the_grant():
    b = FS.StrategyBankroll(start=1000.0)
    assert (b.balance, b.scale, b.cap) == (1000.0, 1.0, 1000.0)
    p = FS.sized(RB.TakerParams(), b)
    assert (p.scale, p.max_deployed) == (1.0, 1000.0)


def test_scale_follows_the_strategy_pnl_and_floors_at_zero():
    assert FS.StrategyBankroll(1000.0, pnl=500.0).scale == pytest.approx(1.5)
    bust = FS.StrategyBankroll(1000.0, pnl=-1000.0)
    assert (bust.scale, bust.cap) == (0.0, 0.0)
    assert FS.StrategyBankroll(1000.0, pnl=-1500.0).scale == 0.0
    # open cost on other events comes off the cap, not the scale
    held = FS.StrategyBankroll(1000.0, pnl=200.0, open_cost=300.0)
    assert (held.scale, held.cap) == (pytest.approx(1.2), pytest.approx(900.0))


def test_a_blend_weight_stays_multiplied_in():
    p = FS.sized(RB.TakerParams(scale=0.5), FS.StrategyBankroll(1000.0, pnl=500.0))
    assert p.scale == pytest.approx(0.75) and p.max_deployed == pytest.approx(750.0)
    tight = FS.sized(RB.TakerParams(max_deployed=100.0), FS.StrategyBankroll(1000.0))
    assert tight.max_deployed == 100.0                          # the profile's own cap when it is tighter
    assert FS.sized(RB.TakerParams(), None) == RB.TakerParams()  # not a player: unchanged


def test_stakes_scale_and_a_busted_strategy_trades_nothing():
    base = SG.taker_signals(_markets(1), RB.TakerParams())
    up = SG.taker_signals(_markets(1), FS.sized(RB.TakerParams(), FS.StrategyBankroll(1000.0, pnl=500.0)), capped=True)
    assert _cost(up[1]) == pytest.approx(1.5 * _cost(base[1]), rel=0.02)
    sigs, pos = SG.taker_signals(_markets(), FS.sized(RB.TakerParams(), FS.StrategyBankroll(1000.0, pnl=-1000.0)),
                                 capped=True)
    assert sigs == [] and pos == []


def test_the_cap_holds_across_the_weekend_markets():
    p = FS.sized(RB.TakerParams(), FS.StrategyBankroll(1000.0, pnl=-900.0, open_cost=0.0))   # scale 0.1, cap 100
    p = replace(p, scale=1.0)                                    # full stakes, so only the cap binds: 3 x $50 > $100
    _, pos = SG.taker_signals(_markets(), p, capped=True)
    assert _cost(pos) <= 100.0 + 1e-6 and _cost(pos) > 90.0


def test_uncapped_path_is_unchanged_even_with_a_profile_cap():
    """The live pass never applied a profile's own max_deployed; taker_signals still doesn't unless capped=True."""
    plain = SG.taker_signals(_markets(), RB.TakerParams())
    assert SG.taker_signals(_markets(), RB.TakerParams(max_deployed=10.0)) == plain
    assert SG.taker_signals(_markets(), RB.TakerParams(), capped=True) == plain       # no cap set: same


# -- per player, on the test database ---------------------------------------------------------------------------------

@pytest.fixture
def players(test_engine, monkeypatch):
    """Two players with the 1,000 grant (ada, bea) and the demo taker (taker), which also has one."""
    from racinglines.db import config
    from racinglines.web import accounts as ACC
    from racinglines.web import users as U
    with test_engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS accounts CASCADE"))
        c.execute(text("DELETE FROM paper_positions"))
        c.execute(text("DELETE FROM users"))
    monkeypatch.setenv("DATABASE_URL", test_engine.url.render_as_string(hide_password=False))
    config.get_engine.cache_clear()
    with config.get_session() as s:
        for name in ("ada", "bea", "taker"):
            U.create_user(s, name, f"{name}-password-1", "pro")
    ACC.setup(config.get_engine())
    with test_engine.connect() as c:
        ids = dict(c.execute(text("SELECT username, id FROM users")).all())
    yield ids
    config.get_engine.cache_clear()


def _paper(c, uid, event_key, cash, yes=0.0, no=0.0, outcome=None, mark=None, key="m"):
    c.execute(text("""INSERT INTO paper_positions (user_id, event_key, market_key, kind, yes_shares, no_shares, cash,
                                                   mark, outcome, venue)
                      VALUES (:u, :e, :k, 'race_win', :y, :n, :c, :m, :o, 'polymarket')"""),
              dict(u=uid, e=event_key, k=key, y=yes, n=no, c=cash, m=mark, o=outcome))


def _out():
    out = dict(profile=dict(name="A", strategy="update"), event=dict(event_key=EVENT, name="US GP"),
               stages=[("after Quali", None, 1, None)], venue="polymarket")
    p = RB.TakerParams()
    out["signals"], out["positions"] = SG.taker_signals(_markets(), p)
    out["_taker"] = SG.taker_inputs(_markets(), p)
    return out


def test_player_bankroll_reads_the_grant_and_the_strategys_own_pnl(players, test_engine):
    with test_engine.begin() as c:
        b = FS.player_bankroll(c, players["ada"], EVENT)
        assert (b.start, b.pnl, b.scale, b.cap) == (1000.0, 0.0, 1.0, 1000.0)
        _paper(c, players["ada"], "2026-17", cash=-100.0, yes=600.0, outcome=True, key="won")   # +500, settled
        _paper(c, players["ada"], EVENT, cash=-50.0, yes=100.0, mark=0.9, key="now")             # this event: left out
        assert FS.player_bankroll(c, players["ada"], EVENT).scale == pytest.approx(1.5)
        _paper(c, players["bea"], "2026-17", cash=-1000.0, yes=1000.0, outcome=False, key="lost")  # -1,000
        bust = FS.player_bankroll(c, players["bea"], EVENT)
        assert (bust.scale, bust.cap) == (0.0, 0.0)
        # hand trades share the same F$1,000: a F$400 hand loss shrinks the strategy's bankroll too
        c.execute(text("""INSERT INTO accounts.fantasy_ledger (user_id, amount, reason, ref_table, ref_id)
                          VALUES (:u, -400, 'trade', 'fantasy_fills', 1)"""), dict(u=players["ada"]))
        assert FS.player_bankroll(c, players["ada"], EVENT).scale == pytest.approx(1.1)
        # and hand trades can spend only what the strategy hasn't tied up: 1,000 - 400 - 100 + 600 - 50
        assert FL.available(c, players["ada"]) == pytest.approx(1050.0)
        assert FS.player_bankroll(c, players["taker"], EVENT) is None                 # the demo account


def test_for_player_resizes_players_and_leaves_the_demo_account_alone(players, test_engine):
    out = _out()
    with test_engine.begin() as c:
        assert SG.for_player(c, players["taker"], out) is out                          # demo: the shared result
        fresh = SG.for_player(c, players["ada"], out)
        assert fresh["signals"] == out["signals"] and fresh["positions"] == out["positions"]   # 1,000: same trades
        _paper(c, players["ada"], "2026-17", cash=-100.0, yes=600.0, outcome=True, key="won")
        up = SG.for_player(c, players["ada"], out)
        assert _cost(up["positions"]) == pytest.approx(1.5 * _cost(out["positions"]), rel=0.02)
        _paper(c, players["bea"], "2026-17", cash=-1000.0, yes=1000.0, outcome=False, key="lost")
        bust = SG.for_player(c, players["bea"], out)
        assert bust["signals"] == [] and bust["positions"] == []


def test_for_player_keeps_the_rows_tags(players, test_engine):
    out = _out()
    SG.tag(out, detail=dict(venue="kalshi"), position=dict(venue="kalshi"))
    SG.tag(out, detail=dict(member="T8"))
    with test_engine.begin() as c:
        mine = SG.for_player(c, players["ada"], out)
    assert mine["signals"] and all(s["detail"]["venue"] == "kalshi" and s["detail"]["member"] == "T8"
                                   for s in mine["signals"])
    assert all(p["venue"] == "kalshi" for p in mine["positions"])
    assert mine["signals"] == out["signals"]                    # F$1,000, nothing earned yet: the same rows


def test_no_ledger_means_no_sizing(test_engine):
    with test_engine.begin() as c:
        c.execute(text("DROP SCHEMA IF EXISTS accounts CASCADE"))
        assert FS.player_bankroll(c, 1, EVENT) is None


# -- the player's sizing choice: standard or Kelly (owner, 2026-10-12 19:52Z / 19:53Z) ---------------------------------

@pytest.mark.parametrize("prof,want", [
    (dict(sizing="kelly", kelly=0.25), 0.25), (dict(sizing="kelly", kelly=1.0), 1.0), (dict(sizing="kelly", kelly=0.1), 0.1),
    (dict(sizing="kelly", kelly="0.5"), 0.5),
    (dict(sizing="kelly", kelly=0.05), None), (dict(sizing="kelly", kelly=1.5), None), (dict(sizing="kelly"), None),
    (dict(sizing="kelly", kelly="half"), None), (dict(sizing="kelly", kelly=True), None),
    (dict(sizing="standard", kelly=0.5), None), (dict(sizing="half_kelly"), None), ({}, None), (None, None)])
def test_sizing_of_validates_the_kelly_fraction(prof, want):
    from racinglines.pipelines import profiles as PF
    assert PF.sizing_of(prof) == want


def test_kelly_uses_the_strategy_bankroll_and_keeps_the_cap():
    p = FS.sized(RB.TakerParams(), FS.StrategyBankroll(1000.0, pnl=500.0), kelly=0.5)
    assert (p.kelly, p.bankroll, p.scale, p.max_deployed) == (0.5, 1500.0, 1.0, 1500.0)
    assert p.max_stake == pytest.approx(75.0)                    # the per-market cap still follows the bankroll
    blend = FS.sized(RB.TakerParams(scale=0.5), FS.StrategyBankroll(1000.0, open_cost=200.0), kelly=0.25)
    assert (blend.kelly, blend.bankroll, blend.scale, blend.max_deployed) == (0.25, 1000.0, 0.5, 400.0)
    bust = FS.sized(RB.TakerParams(), FS.StrategyBankroll(1000.0, pnl=-1200.0), kelly=1.0)
    assert bust.bankroll == 0.0 and SG.taker_signals(_markets(), bust, capped=True) == ([], [])


def test_kelly_stakes_are_kelly_of_the_bankroll():
    """fair 0.60 at 0.40 + 0.01 cost: f* = 0.19 / 0.59; quarter Kelly of F$1,000 = F$80.5, under a raised max stake."""
    p = replace(RB.TakerParams(max_stake=500.0), stake_per_edge=250.0)
    _, pos = SG.taker_signals(_markets(1), FS.sized(p, FS.StrategyBankroll(1000.0), kelly=0.25), capped=True)
    assert _cost(pos) == pytest.approx(0.25 * 0.19 / 0.59 * 1000.0, rel=0.01)


def test_for_player_applies_the_players_kelly(players, test_engine):
    out = _out()
    with test_engine.begin() as c:
        k = SG.for_player(c, players["ada"], out, kelly=0.5)
        std = SG.for_player(c, players["ada"], out)
        assert std["signals"] == out["signals"]
        assert k["bankroll"].balance == 1000.0 and k["positions"]          # half Kelly: capped at max_stake here
        assert SG.for_player(c, players["taker"], out, kelly=0.5) is out    # demo: never sized


def test_set_sizing_saves_validates_and_survives_a_new_strategy(players, test_engine):
    from racinglines.pipelines import profiles as PF
    uid = players["ada"]
    with test_engine.begin() as c:
        PF.assign(c, uid, dict(name="A", strategy="update", settings={}, candidate_id=None))
        PF.set_sizing(c, uid, "kelly", 0.25)
        assert PF.sizing_of(PF.of_user(c, uid)) == 0.25
        for bad in (("kelly", 0.05), ("kelly", 1.5), ("half_kelly", None)):
            with pytest.raises(ValueError):
                PF.set_sizing(c, uid, *bad)
        PF.assign(c, uid, dict(name="T8", strategy="early", settings={}, candidate_id=None))   # picks again
        assert PF.sizing_of(PF.of_user(c, uid)) == 0.25
        PF.set_sizing(c, uid, "standard")
        prof = PF.of_user(c, uid)
        assert PF.sizing_of(prof) is None and "kelly" not in prof
