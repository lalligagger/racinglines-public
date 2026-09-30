"""The taker replay of the result-only sports (pipelines/position_replay.py): the pieces on synthetic data, then a
NASCAR season on the test database (the fixtures' 2026 Cup races, synthetic Kalshi links and tape)."""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select, text

from racinglines.markets import venue_replay as VR
from racinglines.markets.strategies import taker_weekend as RB
from racinglines.models import outcomes as O
from racinglines.models.race_model import Event
from racinglines.pipelines import position_replay as P
from racinglines.sources.motogp import links as ML

UTC = timezone.utc


def _sims():
    # 4 entrants, 4 sims: athlete 1 wins twice, 2 once, 3 once; 4 is always last
    rank = np.array([[1, 2, 3, 4], [2, 1, 3, 4], [1, 3, 2, 4], [3, 2, 1, 4]])
    return O.OutcomeSims(entrants=[1, 2, 3, 4], rank=rank, finished=np.ones_like(rank, bool))


@pytest.mark.quick
def test_fair_values_from_the_simulations():
    s = _sims()
    assert P.fair(s, "race_win", 1) == 0.5 and P.fair(s, "race_win", 4) == 0.0
    assert P.fair(s, "race_podium", 4) == 0.0 and P.fair(s, "race_podium", 3) == 1.0
    assert P.fair(s, "race_top5", 4) == 1.0 and P.fair(s, "race_top20", 2) == 1.0
    assert P.fair(s, "race_h2h", 1, 2) == 0.5 and P.fair(s, "race_h2h", 3, 4) == 1.0
    assert P.fair(s, "race_win", 99) is None and P.fair(s, "race_h2h", 1, 99) is None     # not in the field


@pytest.mark.quick
def test_settlement_by_classified_position():
    res = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4], position=[1, 2, 12, np.nan], status=["OK", "DNF", "OK", "DNF"]))
    assert P.settle("race_win", 1, None, res) is True and P.settle("race_win", 2, None, res) is False
    assert P.settle("race_podium", 2, None, res) is True          # NASCAR: a retirement is still classified by laps
    assert P.settle("race_top10", 3, None, res) is False and P.settle("race_top20", 3, None, res) is True
    assert P.settle("race_top20", 4, None, res) is False          # unclassified (MotoGP DNF): NO for every top-n
    assert P.settle("race_h2h", 3, 4, res) is True and P.settle("race_h2h", 4, 3, res) is False
    assert P.settle("race_win", 99, None, res) is None and P.settle("race_h2h", 1, 99, res) is None


@pytest.mark.quick
def test_stages_are_hours_from_race_day_midnight_utc():
    sp = P.spec("motogp")
    st = P.stage_times(date(2026, 9, 25), sp)                     # a Friday: the Grand Prix is Sunday 27th
    assert [l for l, _ in st] == ["T-3d", "T-1d", "race eve"]
    assert st[-1][1] == pd.Timestamp("2026-09-26 18:00") and st[0][1] == pd.Timestamp("2026-09-24 00:00")
    assert P.stage_times(date(2026, 9, 27), P.spec("nascar"))[-1][1] == pd.Timestamp("2026-09-26 18:00")


@pytest.mark.quick
def test_both_sports_are_on_by_default_and_f1_is_unchanged():
    from racinglines import sports
    from racinglines.markets import venues
    for sport in ("nascar", "motogp"):
        sp = P.spec(sport)
        assert set(sp["kinds"]) <= set(P.N_OF) | {"race_h2h"} and sp["stages"] and sp["source"]
        assert P.venues(sport) == ("polymarket", "kalshi") and sports.identity(sport) == sport
    assert venues.STANDARD_KINDS["nascar_cup"] == ("race_win", "race_podium", "race_top10")
    assert venues.STANDARD_KINDS["motogp_wc"] == ("race_win",)
    assert venues.STANDARD_KINDS["f1_wdc"] == ("race_win", "race_podium", "race_top10")
    with pytest.raises(ValueError):
        P.spec("indycar")


@pytest.mark.quick
def test_replay_records_are_on_unless_switched_off(monkeypatch):
    from racinglines.db import records as REC
    monkeypatch.delenv(REC.SWITCH, raising=False)
    assert P.records_on() and not REC.enabled()                  # the global switch keeps its own default (off)
    monkeypatch.setenv(REC.SWITCH, "0")
    assert not P.records_on()
    monkeypatch.setenv(REC.SWITCH, "1")
    assert P.records_on()


def _venue(prices, t0, volume=100.0, group=None):
    v = VR.Kalshi.__new__(VR.Kalshi)
    v.links = pd.DataFrame(dict(token_id=list(prices), prediction="race_win"))
    v.prices = {k: pd.DataFrame(dict(ts=[t0 - timedelta(minutes=30)], price=[p])) for k, p in prices.items()}
    v.trades = {k: pd.DataFrame(dict(ts=[t0 - timedelta(hours=1)], usd=[volume])) for k in prices}
    v.stale, v.coherence_tol, v.group_target = timedelta(hours=6), 0.25, group or {"race_win": 1}
    return v


@pytest.mark.quick
def test_race_markets_feed_the_taker_and_settle_after():
    t0 = pd.Timestamp("2026-09-26 18:00")
    links = pd.DataFrame(dict(token_id=["a", "b", "c", "d"], prediction="race_win", athlete_id=[1, 2, 3, 4],
                              params=[{}] * 4, athlete=["A", "B", "C", "D"], group_title=None,
                              end_date=[datetime(2026, 9, 27, 22, tzinfo=UTC)] * 3 + [datetime(2026, 9, 26, 12, tzinfo=UTC)]))
    res = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4], position=[2, 1, 3, 4], status="OK"))
    v = _venue({"a": 0.30, "b": 0.40, "c": 0.10, "d": 0.20}, t0)
    mk = P.race_markets(v, links, _sims(), res, [("race eve", t0)])
    by = {m["key"]: m for m in mk}
    assert [by[k]["outcome"] for k in "abcd"] == [False, True, False, False]
    assert by["a"]["stages"][0]["fair"] == 0.5 and by["a"]["stages"][0]["tradeable"]
    assert not by["d"]["stages"][0]["tradeable"]                                 # closed before the stage
    tr, per = RB.run_weekend(mk, RB.TakerParams())
    assert set(tr["key"]) == {"a", "b", "c"}                                     # |fair - price| >= 15 pts on each
    sides = tr.groupby("key")["side"].first().to_dict()
    assert sides == {"a": "YES", "b": "NO", "c": "YES"}
    pnl = per.set_index("key")["pnl"]
    assert pnl["a"] < 0 and pnl["b"] < 0 and pnl["c"] < 0                      # settled on the result: b won, a and c lost
    assert P.kalshi_fees(tr) > 0
    incoherent = _venue({"a": 0.9, "b": 0.9, "c": 0.9, "d": 0.2}, t0)            # sums to 2.9: no race_win trades
    assert not any(s["tradeable"] for m in P.race_markets(incoherent, links, _sims(), res, [("x", t0)]) for s in m["stages"])


@pytest.mark.quick
def test_the_models_price_the_start_list_only_when_given_one():
    from racinglines.models.motogp_model import MotoGPRaceChallenger
    from racinglines.models.nascar_model import NascarCupRace
    for model in (NascarCupRace(), MotoGPRaceChallenger()):
        hist = pd.DataFrame(dict(season=2026, date=[date(2026, 5, d) for d in (1, 1, 1, 8, 8, 8)], athlete_id=[1, 2, 3, 1, 2, 4],
                                 position=[1.0, 2, 3, 2, 1, 3], team=["x", "y", "z", "x", "y", "z"], driver="n", rider="n"))
        st = model.Settings.from_dict({"sims": 200, "seed": 1})
        full = model.price(hist, Event(id="e", season=2026, cutoff=date(2026, 5, 15)), st, np.random.default_rng(1))
        assert full.entrants == [1, 2, 3, 4]                                     # walk-forward: everyone in the history
        f = model.price(hist, Event(id="e", season=2026, cutoff=date(2026, 5, 15), info={"field": [2, 4, 9]}), st,
                        np.random.default_rng(1))
        assert f.entrants == [2, 4, 9] and f.rank.shape == (200, 3)              # 9: a newcomer at the no-form base
        assert abs(sum(P.fair(f, "race_win", a) for a in (2, 4, 9)) - 1) < 1e-9


@pytest.mark.quick
def test_motogp_listing_kinds():
    k = ML.kind_of
    assert k(dict(exchange="kalshi", params={"series": "KXMOTOGPRACE"})) == "race_win"
    assert k(dict(exchange="kalshi", event_slug="KXMOTOGPRACE-26THA")) == "race_win"
    assert k(dict(exchange="kalshi", params={"series": "KXMOTOGP"})) is None                 # the championship
    assert k(dict(exchange="kalshi", params={"series": "KXMOTOGPTEAMS"})) is None
    assert k(dict(exchange="polymarket", question="Will Marc Marquez win the Thai Grand Prix?")) == "race_win"
    assert k(dict(exchange="polymarket", question="Will Marc Marquez win the Thai GP sprint?")) is None
    assert k(dict(exchange="polymarket", question="Will Marc Marquez win the 2026 MotoGP championship?")) is None


@pytest.mark.quick
def test_motogp_fill_never_raises_and_tags_the_kind():
    L = ML.Linker.__new__(ML.Linker)
    L.conn, L._by_year, L.counts = None, {}, __import__("collections").Counter()
    rows = [dict(exchange="kalshi", params={"series": "KXMOTOGP"}, end_date=None),          # the championship: nothing
            dict(exchange="kalshi", params={"series": "KXMOTOGPRACE"}, end_date=None),      # a race, no close date
            dict(exchange="kalshi", params={"series": "KXMOTOGPRACE"}, group_title="Marc Marquez",
                 end_date=datetime(2026, 9, 28, tzinfo=UTC))]                               # no database: an error, kept going
    n = L.fill(rows)
    assert n["links"] == 3 and n["errors"] == 1
    assert rows[0]["params"] == {"series": "KXMOTOGP"} and rows[1]["params"]["kind"] == "race_win"
    assert "athlete_id" not in rows[2]


# --- a NASCAR season on the test database ---------------------------------------------------------------

from test_nascar import db, raw  # noqa: E402,F401  (fixtures)
from test_nascar_links import world  # noqa: E402,F401  (fixture: the fixtures' 2026 Cup races and drivers)


def _seed(s, race, res, prices):
    """Kalshi race-winner links on `race` for the drivers in `prices` (the first two stored as `nascar link --apply`
    leaves them, the rest unidentified, as the tape-only sync stored them) and a tape: one price and one $80 trade
    before every stage."""
    from racinglines.db import models as m
    from racinglines.markets.kalshi import sync as KS
    comp, cat = KS.competition(s, "nascar")
    day = pd.Timestamp(race.start)
    names = dict(s.execute(text("SELECT id, display_name FROM athletes WHERE id = ANY(:i)"), dict(i=list(prices))).all())
    for n, (a, p) in enumerate(prices.items()):
        tok = f"KXNASCARRACE-RPTST26-{a}"
        known = n < 2
        s.add(m.MarketLink(competition_id=comp.id, category_id=cat.id, exchange="kalshi", token_id=tok, market_slug=tok,
                           question=f"Will {names[a]} win the {race['name']}?", condition_id="KXNASCARRACE-RPTST26",
                           outcome=names[a], group_title=names[a], event_slug="KXNASCARRACE-RPTST26",
                           event_title=f"{race['name']} Winner", prediction="unmodeled",
                           athlete_id=a if known else None, race_id=int(race.race_id) if known else None,
                           params=dict(series="KXNASCARRACE", **({"kind": "race_win", "nascar_series": "cup", "season": 2026} if known else {})),
                           end_date=(day + pd.Timedelta(hours=26)).tz_localize("UTC").to_pydatetime()))
        for h in (-73, -25, -7):
            ts = (day + pd.Timedelta(hours=h)).tz_localize("UTC").to_pydatetime()
            s.execute(text("INSERT INTO market_price_history (token_id, ts, price) VALUES (:t, :ts, :p)"), dict(t=tok, ts=ts, p=p))
            s.execute(text("""INSERT INTO market_trades (token_id, condition_id, outcome_index, ts, side, price, size, tx_hash, wallet)
                              VALUES (:t, 'KXNASCARRACE-RPTST26', 0, :ts, 'BUY', :p, :z, :h, '')"""),
                      dict(t=tok, ts=ts, p=p, z=80 / p, h=f"rp{a}{h}"))
    s.commit()


def _wipe(s):
    s.execute(text("DELETE FROM market_price_history WHERE token_id LIKE 'KXNASCARRACE-RPTST26-%'"))
    s.execute(text("DELETE FROM market_trades WHERE token_id LIKE 'KXNASCARRACE-RPTST26-%'"))
    s.execute(text("DELETE FROM market_links WHERE token_id LIKE 'KXNASCARRACE-RPTST26-%'"))
    s.commit()


def test_a_nascar_season_replays_on_kalshi_and_saves_and_undoes(world, test_engine, monkeypatch, tmp_path):
    from conftest import TEST_DB
    from racinglines.db import models as m
    monkeypatch.setenv("RACINGLINES_PREDICTION_RECORDS", "1")
    monkeypatch.setenv("RACINGLINES_RECORDS_DIR", str(tmp_path))
    with world() as s:
        rs = P.races(s.connection(), P.spec("nascar"), [2026])
        assert len(rs) >= 2
        race = rs.iloc[-1]
        res = P.race_results(s.connection(), race.race_id)
        top = res.sort_values("position")["athlete_id"].astype(int).tolist()
        prices = {top[0]: 0.05, top[1]: 0.40, top[2]: 0.25, top[-1]: 0.30}         # sums to 1: a coherent group
        _wipe(s)
        _seed(s, race, res, prices)
        try:
            lk = P.links(s.connection(), P.spec("nascar"), "kalshi")
            assert len(lk) == 4 and set(lk["athlete_id"]) == set(prices)           # two stored, two identified in memory
            assert set(lk["race_id"]) == {int(race.race_id)} and set(lk["prediction"]) == {"race_win"}
            out = P.run(test_engine, "nascar", [2026], venue="kalshi", echo=lambda *a: None,
                        save=dict(engine_url=TEST_DB, batch="replay-test"))
            r = out["races"].set_index("event_key").loc[race.event_key]
            assert r["markets"] == 4 and r["tradeable"] == 4 and r["update_trades"] > 0
            assert out["totals"]["update"]["fees"] > 0 and out["totals"]["update"]["net"] < out["totals"]["update"]["pnl"]
            assert len(out["trades"]) and out["trades"]["pnl"].notna().all()           # every trade settled on the result
            assert "update" in P.format_report(out)
            P.write(out, tmp_path / "out")
            assert (tmp_path / "out" / "summary.json").is_file()
            runs = s.execute(text("SELECT id FROM model_runs WHERE params->>'replay_batch' = 'replay-test'")).scalars().all()
            assert len(runs) == len(rs)                                           # one as-of run per race, traded or not
            n_pred = s.execute(text("SELECT count(*) FROM race_predictions WHERE model_run_id = ANY(:i)"), dict(i=runs)).scalar()
            assert n_pred == sum(len(P.race_results(s.connection(), rid)) for rid in rs["race_id"])
            assert (tmp_path / str(runs[-1]) / "predictions.parquet").is_file()
            again = P.run(test_engine, "nascar", [2026], venue="kalshi", echo=lambda *a: None)
            assert again["totals"] == out["totals"]                               # reproducible from its settings
            one = P.run(test_engine, "nascar", [2026], venue="kalshi", events=["latest"], echo=lambda *a: None)
            assert list(one["races"]["event_key"]) == [race.event_key]            # the spot check: the last race only
            assert P.undo(s, "replay-test") == len(rs)
            s.commit()
            assert not s.execute(select(m.ModelRun.id).where(m.ModelRun.id.in_(runs))).all()
        finally:
            s.rollback()
            s.execute(text("DELETE FROM model_runs WHERE params->>'replay_batch' = 'replay-test'"))
            _wipe(s)


@pytest.mark.quick
def test_recent_form_weights_the_latest_race_most():
    """The recency weights run from the oldest race (weight e^-decay) to the latest (weight 1): of two drivers
    with the same results in the opposite order, the one whose good result is the latest is priced higher."""
    from racinglines.models.motogp_model import MotoGPRaceChallenger
    from racinglines.models.nascar_model import NascarCupRace, NascarCupRaceChallenger
    days = [date(2026, 5, d) for d in (1, 8, 15, 22)]
    hist = pd.DataFrame(dict(season=2026, date=days * 2, athlete_id=[1] * 4 + [2] * 4,
                             position=[10.0, 10, 10, 1] + [1.0, 10, 10, 10], team=["a"] * 4 + ["b"] * 4,
                             driver="n", rider="n"))
    for model in (NascarCupRace(), NascarCupRaceChallenger(), MotoGPRaceChallenger()):
        st = model.Settings.from_dict({"sims": 4000, "seed": 3, "noise": 1.0, "team_bias": 0.0})
        sims = model.price(hist, Event(id="e", season=2026, cutoff=date(2026, 5, 29)), st, np.random.default_rng(3))
        assert P.fair(sims, "race_win", 1) > 0.7 > P.fair(sims, "race_win", 2), model.name


@pytest.mark.quick
def test_history_and_team_form_count_races_not_results():
    from racinglines.models import motogp_model as MM
    from racinglines.models import nascar_model as NM
    days = [date(2026, 5, d) for d in (1, 8, 15)]
    # team "a" runs two cars: 10th and 12th, then 20th and 22nd, then 1st and 3rd
    past = pd.DataFrame(dict(date=[d for d in days for _ in range(2)], athlete_id=[1, 2] * 3,
                             position=[10.0, 12, 20, 22, 1, 3], team="a"))
    for mod in (NM, MM):
        assert len(mod._last_races(past, 2)) == 4 and set(mod._last_races(past, 2)["date"]) == set(days[1:])
        st = dict(recent_races=1, recency_decay=2.5)
        assert mod._team_form(past, st) == {"a": 2.0}                       # the last race: mean of 1st and 3rd
        two = mod._team_form(past, dict(st, recent_races=2))["a"]           # races 2 and 3, the latest weighted most
        assert 2.0 < two < 11.5 and two < (21 + 2) / 2


class _Kalshi:
    """A stand-in Kalshi client: one trade and one hourly price per market before each stage of the race."""

    def __init__(self, day, prices):
        self.day, self.prices, self.calls = day, prices, []

    def _p(self, ticker):
        return self.prices[int(ticker.rsplit("-", 1)[1])]

    def trades(self, ticker, min_ts=None):
        self.calls.append(("trades", ticker))
        return [dict(trade_id=f"t{ticker}{h}", yes_price_dollars=str(self._p(ticker)), taker_side="yes",
                     count=int(80 / self._p(ticker)),
                     created_time=(self.day + pd.Timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")) for h in (-73, -25, -7)]

    def candlesticks(self, series, ticker, start_ts, end_ts, period=60):
        self.calls.append(("candles", ticker))
        return [dict(end_period_ts=int((self.day + pd.Timedelta(hours=h)).tz_localize("UTC").timestamp()),
                     price=dict(close_dollars=str(self._p(ticker)))) for h in (-73, -25, -7)]


def test_no_tape_says_so_then_a_pull_makes_the_race_tradeable(world, test_engine, capsys):
    from racinglines.cli import replay_cmd
    with world() as s:
        rs = P.races(s.connection(), P.spec("nascar"), [2026])
        race = rs.iloc[-1]
        res = P.race_results(s.connection(), race.race_id)
        top = res.sort_values("position")["athlete_id"].astype(int).tolist()
        prices = {top[0]: 0.05, top[1]: 0.40, top[2]: 0.25, top[-1]: 0.30}
        _wipe(s)
        _seed(s, race, res, prices)
        s.execute(text("DELETE FROM market_price_history WHERE token_id LIKE 'KXNASCARRACE-RPTST26-%'"))
        s.execute(text("DELETE FROM market_trades WHERE token_id LIKE 'KXNASCARRACE-RPTST26-%'"))
        s.commit()
        try:
            bare = P.run(test_engine, "nascar", [2026], venue="kalshi", events=["latest"], echo=lambda *a: None)
            assert bare["tape"]["markets"] == 4 and bare["tape"]["priced"] == 0 and bare["tape"]["no_tape"] == [race.event_key]
            text_ = P.format_report(bare)
            assert "NOT TRADED" in text_ and "NO TAPE" in text_ and "P&L" not in text_.split("No P&L")[0]
            assert not P.traded(bare)
            plan = P.tape_plan(test_engine, "nascar", "kalshi", [2026], ["latest"])
            assert len(plan) == 1 and len(plan[0][1]) == 4
            r, g, start, end = plan[0]
            assert start < pd.Timestamp(race.start).tz_localize("UTC") - pd.Timedelta(hours=72) and end > start
            kc = _Kalshi(pd.Timestamp(race.start), prices)
            got = P.probe(plan, "kalshi", kc=kc, echo=lambda *a: None)
            assert len(got) == 3 and all(tr == 3 and px == 3 for _, tr, px in got)
            assert not s.execute(text("SELECT count(*) FROM market_trades WHERE token_id LIKE 'KXNASCARRACE-RPTST26-%'")).scalar()
            with test_engine.connect() as c:
                n = P.pull(s, c, plan, "kalshi", kc=kc, echo=lambda *a: None)
            assert n == dict(races=1, trades=12, prices=12)
            after = P.run(test_engine, "nascar", [2026], venue="kalshi", events=["latest"], echo=lambda *a: None)
            assert P.traded(after) and after["tape"]["tradeable"] == 4 and not after["tape"]["no_tape"]
            assert "WARNING" not in P.format_report(after) and "update" in P.format_report(after)
            with pytest.raises(SystemExit):                  # a pull writes: it needs a fresh backup, as --save does
                replay_cmd._backup_ok(type("A", (), dict(backup=None))(), "nascar", "--tape pull")
        finally:
            s.rollback()
            _wipe(s)
