"""Settlement of cancelled and relocated races (racinglines/markets/settlement_rules.py, roadmap U8): each venue's
table, the switch that is off by default, the paper-position P&L under a void or 50/50 payout, and the private
book on synthetic data: Bahrain 2026 (round 16, run at Sepang) settles on its result; a cancelled race settles as
each venue's published rule says (Polymarket: named NO / "Other" YES / head-to-head 50-50; Kalshi: every market
at its last fair price; the private book: void)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from racinglines.markets import private_book as house
from racinglines.markets import settlement_rules as SR
from racinglines.markets.strategies import taker_weekend as RB
from racinglines.pipelines import signals as SG

pytestmark = pytest.mark.quick


def test_switch_is_off_by_default(monkeypatch):
    monkeypatch.delenv(SR.ENV, raising=False)
    assert SR.enabled() is False and SR.enabled(True) is True and SR.enabled(False) is False
    monkeypatch.setenv(SR.ENV, "1")
    assert SR.enabled() is True and SR.enabled(False) is False


def test_bahrain_2026_is_relocated_and_settles_on_the_result(monkeypatch):
    monkeypatch.delenv(SR.STATUS_ENV, raising=False)
    assert SR.race_status("f1", "2026-16") == SR.RELOCATED
    for venue in ("polymarket", "kalshi", "private"):
        assert SR.payout(venue, SR.RELOCATED, "race_win", "Max Verstappen") == SR.RESULT
        assert SR.apply(venue, SR.RELOCATED, "race_win", "Max Verstappen", True) is True
        assert SR.apply(venue, SR.RELOCATED, "race_h2h", None, False) is False
    assert SR.race_status("f1", "2026-15") is None
    assert SR.apply("polymarket", None, "race_win", "X", None) is None


def test_race_status_from_the_database_and_the_environment(monkeypatch):
    assert SR.race_status("f1", "2026-22", db_status="cancelled") == SR.CANCELLED
    assert SR.race_status("f1", "2026-22", db_status="completed") is None
    monkeypatch.setenv(SR.STATUS_ENV, "f1:2026-22=cancelled, f1:2026-23=cancelled,junk")
    assert SR.race_status("f1", "2026-22") == SR.CANCELLED and SR.race_status("f1", "2026-23") == SR.CANCELLED
    assert SR.race_status("mtb_dh", "2026-22") is None


def test_cancelled_race_pays_by_the_venues_table():
    # Polymarket: the April 2026 Bahrain markets in the archive (named NO, "Other" YES); its head-to-head rule
    # ("If a Grand Prix is permanently canceled, the market will resolve 50-50")
    assert SR.payout("polymarket", SR.CANCELLED, "race_win", "Max Verstappen") is False
    assert SR.payout("polymarket", SR.CANCELLED, "race_win", "Other") is True
    assert SR.payout("polymarket", SR.CANCELLED, "race_constructor_top", "Other") is True
    assert SR.payout("polymarket", SR.CANCELLED, "race_h2h", "Lando Norris") == 0.5
    # Kalshi: "if the race is cancelled or not started within 48 hours of its originally scheduled start, all
    # markets will resolve to a fair price": the market's last price stands in for it
    assert SR.payout("kalshi", SR.CANCELLED, "race_win", "Max Verstappen") == SR.FAIR
    assert SR.payout("kalshi", SR.CANCELLED, "race_win", "Other") == SR.FAIR
    assert SR.payout("kalshi", SR.CANCELLED, "race_h2h", "Yes") == SR.FAIR
    assert SR.apply("kalshi", SR.CANCELLED, "race_win", "Max Verstappen", None) == SR.FAIR
    assert SR.apply("kalshi", SR.CANCELLED, "race_win", "Max Verstappen", None, last_price=0.37) == 0.37
    assert SR.apply("kalshi", SR.CANCELLED, "race_win", "Max Verstappen", None, last_price=float("nan")) == SR.FAIR
    assert SR.apply("polymarket", SR.CANCELLED, "race_h2h", None, None, last_price=0.37) == 0.5   # price only for FAIR
    assert SR.ASSUMED == set()
    # the private book voids
    assert SR.payout("private", SR.CANCELLED, "race_win", "X") == SR.VOID
    assert SR.payout("private", SR.CANCELLED, "race_h2h", None) == SR.VOID
    assert SR.describe("kalshi", SR.CANCELLED, "race_win") == ("kalshi rule for a cancelled race: named outcome settles at "
                                                                "the last fair price (the market's last recorded price stands in for Kalshi's figure)")
    assert "assumed" not in SR.describe("polymarket", SR.CANCELLED, "race_win", "Other")
    assert SR.describe("polymarket", SR.CANCELLED, "race_h2h") == "polymarket rule for a cancelled race: binary outcome pays 0.5"
    assert SR.describe("private", SR.CANCELLED, "race_win").endswith("void, stakes returned")
    with pytest.raises(ValueError):
        SR.payout("polymarket", "postponed", "race_win")


def _stages():
    return [dict(label="after FP1", t=pd.Timestamp("2026-10-02"), fair=0.60, price=0.40, tradeable=True),
            dict(label="after Quali", t=pd.Timestamp("2026-10-03"), fair=0.60, price=0.40, tradeable=True)]


def test_paper_positions_settle_void_at_zero_and_half_at_half():
    p = RB.TakerParams()
    won = RB.run_market(_stages(), True, p)
    assert won["yes"] > 0 and won["pnl"] == pytest.approx(won["cash"] + won["yes"])
    void = RB.run_market(_stages(), SR.VOID, p)
    assert void["yes"] == won["yes"] and void["pnl"] == 0.0 and all(t["pnl"] == 0.0 for t in void["trades"])
    half = RB.run_market(_stages(), 0.5, p)
    assert half["pnl"] == pytest.approx(half["cash"] + 0.5 * half["yes"])
    assert RB.run_market(_stages(), None, p)["pnl"] is None
    fair = RB.run_market(_stages(), SR.FAIR, p)                   # Kalshi's fair price, none recorded: unresolved
    assert fair["pnl"] is None and fair["yes"] == won["yes"]
    priced = RB.run_market(_stages(), 0.37, p)                    # ... and at the last recorded price
    assert priced["pnl"] == pytest.approx(priced["cash"] + 0.37 * priced["yes"])
    assert SR.settle_position(10, 0, -4, SR.FAIR) is None and SR.settle_position(10, 0, -4, 0.37) == pytest.approx(-0.3)
    assert SR.value(SR.FAIR) is None
    assert SR.settle_position(10, 0, -4, SR.VOID) == 0.0 and SR.settle_position(10, 0, -4, 0.5) == 1.0
    assert SR.settle_position(10, 0, -4, True) == 6.0 and SR.settle_position(10, 0, -4, None) is None
    assert SR.value(SR.VOID) is None and SR.value(0.5) == 0.5 and SR.value(True) == 1.0


def test_signal_positions_close_a_void_or_half_market_to_cash():
    mk = dict(key="tok", kind="race_win", subject="X", stages=_stages())
    _, pos = SG.taker_signals([dict(mk, outcome=True)], RB.TakerParams())
    assert pos[0]["outcome"] is True and pos[0]["yes_shares"] > 0                       # unchanged path
    _, pos = SG.taker_signals([dict(mk, outcome=np.bool_(False))], RB.TakerParams())
    assert pos[0]["yes_shares"] > 0
    _, pos = SG.taker_signals([dict(mk, outcome=SR.VOID)], RB.TakerParams())
    assert (pos[0]["yes_shares"], pos[0]["no_shares"], pos[0]["cash"], pos[0]["outcome"]) == (0.0, 0.0, 0.0, None)
    _, pos = SG.taker_signals([dict(mk, outcome=0.5)], RB.TakerParams())
    won = SG.taker_signals([dict(mk, outcome=True)], RB.TakerParams())[1][0]
    assert pos[0]["outcome"] is None and pos[0]["cash"] == pytest.approx(won["cash"] + 0.5 * won["yes_shares"])
    _, pos = SG.taker_signals([dict(mk, outcome=SR.FAIR)], RB.TakerParams())     # no price yet: still open
    assert pos[0]["outcome"] is None and pos[0]["yes_shares"] == won["yes_shares"] and pos[0]["cash"] == won["cash"]


# --- the private book on a database ------------------------------------------------------------------------

def _ensure(s, model, **kw):
    row = s.scalars(select(model).filter_by(**{k: v for k, v in kw.items() if k in ("code", "slug", "display_name")})).first()
    if row is None:
        row = model(**kw)
        s.add(row)
        s.flush()
    return row


def _race(s, key, name, status, results):
    """An F1 event (source f1timing) with a race round and its classification: {athlete name: position}."""
    from racinglines.db import models as m
    sport = _ensure(s, m.Sport, code="f1_sr", name="F1 (settlement test)")
    league = _ensure(s, m.League, code="fia_sr", name="FIA (settlement test)")
    comp = _ensure(s, m.Competition, code="f1_wdc_sr", name="F1 (settlement test)", league_id=league.id, sport_id=sport.id)
    cat = _ensure(s, m.Category, code="DRV_SR", name="Drivers", competition_id=comp.id)
    season = s.scalars(select(m.Season).filter_by(competition_id=comp.id, year=2026)).first()
    if season is None:
        season = m.Season(competition_id=comp.id, year=2026)
        s.add(season)
        s.flush()
    venue = _ensure(s, m.Venue, slug="sepang-sr", name="Sepang")
    ev = m.Event(season_id=season.id, source="f1timing", source_key=key, name=name, start_date=date(2026, 10, 4),
                 venue_id=venue.id, status=status)
    s.add(ev)
    s.flush()
    race = m.Race(event_id=ev.id, category_id=cat.id, format={"kind": "f1", "event_name": name})
    s.add(race)
    s.flush()
    rnd = m.Round(race_id=race.id, kind="race", ordinal=1, name="Race")
    s.add(rnd)
    s.flush()
    ath = {}
    for i, n in enumerate(["Verstappen", "Norris", "Leclerc", "Piastri", "Russell", "Hamilton", "Antonelli"]):
        a = _ensure(s, m.Athlete, display_name=f"{n} (settlement test)")
        ath[n] = a.id
        if results:
            s.add(m.Result(round_id=rnd.id, athlete_id=a.id, position=results[n], status="OK", team=f"team{i // 2}",
                           extra={"team_id": f"team{i // 2}", "points": max(0, 26 - 2 * results[n])}))
    s.flush()
    return race.id, ath, comp.id, cat.id


def _market(s, race_id, athlete_id, kind, title, link=None, params=None):
    from racinglines.db import models as m
    mk = m.HouseMarket(race_id=race_id, athlete_id=athlete_id, kind=kind, title=title, fair_prob=0.3, spread=0.06,
                       yes_price=0.33, no_price=0.73, market_link_id=link, params=params)
    s.add(mk)
    s.flush()
    return mk.id


def _link(s, comp, cat, race_id, athlete_id, exchange, kind, name, question, params=None):
    from racinglines.db import models as m
    ln = m.MarketLink(exchange=exchange, question=question, token_id=f"{exchange}-{kind}-{name}-{race_id}", outcome="Yes",
                      competition_id=comp, category_id=cat, athlete_id=athlete_id, race_id=race_id, prediction=kind,
                      group_title=name, params=params)
    s.add(ln)
    s.flush()
    return ln.id


def test_private_book_settles_bahrain_2026_on_the_result_and_a_cancelled_race_by_venue(test_engine, monkeypatch):
    from racinglines.db import models as m
    monkeypatch.delenv(SR.ENV, raising=False)
    monkeypatch.delenv(SR.STATUS_ENV, raising=False)
    with Session(test_engine) as s:
        # round 16: the Bahrain GP run at Sepang, with its classification
        rid, ath, comp, cat = _race(s, "2026-16", "Bahrain Grand Prix in Malaysia", "completed",
                                    dict(Verstappen=1, Norris=2, Leclerc=3, Piastri=4, Russell=5, Hamilton=6, Antonelli=7))
        win = _market(s, rid, ath["Verstappen"], "race_win", "Verstappen wins the Bahrain Grand Prix")
        pod = _market(s, rid, ath["Piastri"], "race_podium", "Piastri on the podium")
        s.commit()
        assert SR.race_status("f1", "2026-16", SR.db_status(s.connection(), rid)) == SR.RELOCATED
        with test_engine.connect() as c:
            off = sorted(house.settle_from_results(s, c, rid))
        assert off == sorted([win, pod])
        assert (s.get(m.HouseMarket, win).outcome, s.get(m.HouseMarket, pod).outcome) == (True, False)
        assert s.get(m.HouseMarket, win).settle_note == "auto: official race classification"

        # the same race, rules on: a relocated race still settles on the result, with the same note
        win2 = _market(s, rid, ath["Norris"], "race_win", "Norris wins the Bahrain Grand Prix")
        s.commit()
        with test_engine.connect() as c:
            assert house.settle_from_results(s, c, rid, rules=True) == [win2]
        assert (s.get(m.HouseMarket, win2).outcome, s.get(m.HouseMarket, win2).settle_note) == \
            (False, "auto: official race classification")

        # a cancelled race (events.status = 'cancelled', no classification)
        rid2, ath2, comp, cat = _race(s, "2026-23", "Abu Dhabi Grand Prix", "cancelled", None)
        own = _market(s, rid2, ath2["Norris"], "race_win", "Norris wins the Abu Dhabi Grand Prix")
        house.record_bet(s, own, "alice", "YES", 10.0)
        pm = _market(s, rid2, ath2["Verstappen"], "race_win", "Will Max Verstappen win?",
                     link=_link(s, comp, cat, rid2, ath2["Verstappen"], "polymarket", "race_win", "Max Verstappen",
                                "Will Max Verstappen win the 2026 F1 Abu Dhabi Grand Prix?"))
        pm_other = _market(s, rid2, None, "race_win", "Will any other driver win?",
                           link=_link(s, comp, cat, rid2, None, "polymarket", "race_win", "Other",
                                      "Will any other driver win the 2026 F1 Abu Dhabi Grand Prix?"))
        pm_h2h = _market(s, rid2, ath2["Norris"], "race_h2h", "Norris ahead of Piastri",
                         link=_link(s, comp, cat, rid2, ath2["Norris"], "polymarket", "race_h2h", "Lando Norris",
                                    "Norris vs Piastri", params={"opponent_id": ath2["Piastri"]}),
                         params={"opponent_id": ath2["Piastri"]})
        ks = _market(s, rid2, ath2["Leclerc"], "race_podium", "Leclerc podium (Kalshi)",
                     link=_link(s, comp, cat, rid2, ath2["Leclerc"], "kalshi", "race_podium", "Charles Leclerc",
                                "Will Charles Leclerc finish on the podium?"))
        s.commit()
        with test_engine.connect() as c:
            assert house.settle_from_results(s, c, rid2) == []                # switch off: nothing settles (as before)
            assert house.settle_from_results(s, c, rid2, rules=False) == []
            done = house.settle_from_results(s, c, rid2, rules=True)
        assert sorted(done) == sorted([own, pm, pm_other, pm_h2h, ks])
        got = {k: (s.get(m.HouseMarket, k).status, s.get(m.HouseMarket, k).outcome, s.get(m.HouseMarket, k).settle_note)
               for k in done}
        assert got[own] == ("void", None, "auto: private rule for a cancelled race: named outcome void, stakes returned")
        assert got[pm] == ("settled", False, "auto: polymarket rule for a cancelled race: named outcome pays 0")
        assert got[pm_other] == ("settled", True, "auto: polymarket rule for a cancelled race: other outcome pays 1")
        assert got[pm_h2h] == ("void", None, "auto: polymarket rule for a cancelled race: binary outcome pays 0.5; "
                                             "a YES/NO book can't pay 0.5: voided")
        assert got[ks] == ("void", None, "auto: kalshi rule for a cancelled race: named outcome settles at the last fair "
                                         "price (the market's last recorded price stands in for Kalshi's figure); "
                                         "a YES/NO book can't settle at a price: voided")
        bet = s.scalars(select(m.HouseBet).filter_by(market_id=own)).one()
        assert bet.status == "void"

        # the environment switch does the same as rules=True
        late = _market(s, rid2, ath2["Russell"], "race_top10", "Russell in the points")
        s.commit()
        monkeypatch.setenv(SR.ENV, "1")
        with test_engine.connect() as c:
            assert house.settle_from_results(s, c, rid2) == [late]
        assert s.get(m.HouseMarket, late).status == "void"
