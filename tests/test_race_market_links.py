"""Linking the race markets the 2026 Bahrain GP (round 16) link probe found unlinked: Kalshi's top 5 and biggest mover
(priced from the race simulation), Polymarket's driver fastest lap and race props (safety car, red flag, rain),
OG.com's race winner, and Polymarket's placeholder slots ("Driver A", "Other": linked, unmodeled, tagged and counted
on the race page). Synthetic data and mocked responses; the sync and model_prob checks use the test database."""

import json
from datetime import date, datetime, timezone

import httpx
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select, text

from racinglines import exchanges as EX
from racinglines.markets import exchange_driver as D
from racinglines.markets import kinds as K
from racinglines.markets.kalshi import sync as KS
from racinglines.markets.polymarket import sync as PS
from racinglines.models import outcomes as O
from racinglines.models.position_sim import model as M

# --- the two simulated kinds ---------------------------------------------------------------------------------

def _sims():
    """Three simulations, four cars. grid: 1-4 each time."""
    grid = np.array([[1, 2, 3, 4]] * 3)
    rank = np.array([[2, 1, 3, 4],      # car 1 gains one place: the only mover
                     [4, 3, 1, 2],      # car 2 gains two (3 -> 1), car 3 gains two (4 -> 2): both movers
                     [1, 2, 3, 4]])     # nobody gains: no mover
    fin = np.array([[True] * 4, [True] * 4, [True, True, True, False]])
    return O.OutcomeSims(entrants=[10, 11, 12, 13], rank=rank, finished=fin, stage_rank={"qual": grid})


@pytest.mark.quick
def test_biggest_mover_takes_the_largest_gain_ties_all_yes_and_none_without_a_gain():
    s = _sims()
    yes = K.biggest_mover(s.stage_rank["qual"], s.rank, s.finished)
    assert yes.tolist() == [[False, True, False, False], [False, False, True, True], [False] * 4]
    np.testing.assert_allclose(K.fair("race_biggest_mover", s), [0, 1 / 3, 1 / 3, 1 / 3])
    # a retired car is never the mover, whatever its rank says
    s2 = O.OutcomeSims(entrants=[1, 2], rank=np.array([[1, 2]]), finished=np.array([[False, True]]),
                       stage_rank={"qual": np.array([[2, 1]])})
    assert K.fair("race_biggest_mover", s2).tolist() == [0.0, 0.0]
    with pytest.raises(ValueError):
        K.fair("race_biggest_mover", O.OutcomeSims(entrants=[1], rank=np.array([[1]]), finished=np.array([[True]])))


@pytest.mark.quick
def test_top5_prices_classified_finishes_and_neither_kind_joins_the_default_summary():
    rank = np.array([[5, 6, 1], [1, 5, 6]])
    fin = np.array([[False, True, True], [True, True, True]])
    s = O.OutcomeSims(entrants=[1, 2, 3], rank=rank, finished=fin, stage_rank={"qual": rank})
    np.testing.assert_allclose(K.fair("race_top5", s), [0.5, 0.5, 0.5])
    assert {"race_top5", "race_biggest_mover"}.isdisjoint(K.summary(s).columns)
    assert {"race_top5", "race_biggest_mover"}.isdisjoint(set(s.to_records(1, "f1", "m", 2026, 1, "e", "s", None)["kind"]))
    res = pd.DataFrame(dict(athlete_id=[1, 2], position=[5, 6], status=["OK", "OK"], qual_position=[9, 1]))
    assert K.settle("race_top5", 1, None, res) is True and K.settle("race_top5", 2, None, res) is False
    assert K.settle("race_biggest_mover", 1, None, res) is None        # no starting grid in the results


@pytest.mark.quick
def test_position_sim_stores_top5_and_mover_as_the_kinds_price_them():
    rng = np.random.default_rng(3)
    n_sims, n = 400, 8
    grid = np.argsort(rng.random((n_sims, n)), axis=1) + 1
    pos = np.argsort(rng.random((n_sims, n)), axis=1) + 1
    dnf = rng.random((n_sims, n)) < 0.1
    sim = dict(pos=pos, dnf=dnf, grid=grid, points=np.zeros((n_sims, n)))
    e = pd.DataFrame(dict(athlete_id=range(100, 100 + n), team_key=[f"t{i // 2}" for i in range(n)], qp=0.0, rp=0.0))
    summ = M.summarize(e, sim).set_index("athlete_id").loc[e["athlete_id"]]
    sims = O.from_position_sim(e, sim)
    np.testing.assert_allclose(summ["top5_prob"], K.fair("race_top5", sims))
    np.testing.assert_allclose(summ["mover_prob"], K.fair("race_biggest_mover", sims))


# --- Kalshi --------------------------------------------------------------------------------------------------

class Resolver:
    """driver / team / race lookups as polymarket.sync.Resolver, over fixed names."""
    DRIVERS = {"max verstappen": 9002, "lando norris": 9001}

    def __init__(self, race=(134, "2026-16")):
        self._race, self.calls = race, []

    def driver(self, name):
        return self.DRIVERS.get(str(name).lower())

    def team(self, name):
        return None

    def race(self, gp, end_date=None, near=None):
        self.calls.append((gp, end_date, near))
        return self._race if gp and "Bahrain" in gp else (None, None)


@pytest.mark.quick
def test_kalshi_classifies_and_links_top5_and_biggest_mover():
    c = KS.classify
    assert c("Bahrain Grand Prix Main Race: Top 5 Finishers", "Main Race: Max Verstappen to finish top 5") == \
        ("race_top5", "Bahrain Grand Prix")
    assert c("Bahrain Grand Prix Main Race: Biggest Mover", "Biggest Mover: Max Verstappen") == \
        ("race_biggest_mover", "Bahrain Grand Prix")
    assert c("Bahrain Grand Prix Main Race: Top 10 Finishers", "Main Race: Max Verstappen to finish top 10")[0] == "race_top10"
    assert c("Singapore Grand Prix Sprint Race: Top 5 Finishers", "x", sprints=True)[0] == "unmodeled"
    ev = dict(event_ticker="KXF1TOP5-BAH26", series_ticker="KXF1TOP5", title="Bahrain Grand Prix Main Race: Top 5 Finishers",
              markets=[dict(ticker="KXF1TOP5-BAH26-VER", event_ticker="KXF1TOP5-BAH26", status="active",
                            title="Main Race: Max Verstappen to finish top 5", yes_sub_title="Max Verstappen",
                            close_time="2026-10-04T09:00:00Z", rules_primary="If Max Verstappen finishes in the top 5 ...")])
    mv = dict(ev, event_ticker="KXF1BIGGESTMOVER-BAH26", series_ticker="KXF1BIGGESTMOVER",
              title="Bahrain Grand Prix Main Race: Biggest Mover",
              markets=[dict(ev["markets"][0], ticker="KXF1BIGGESTMOVER-BAH26-NOR", event_ticker="KXF1BIGGESTMOVER-BAH26",
                            title="Biggest Mover: Lando Norris", yes_sub_title="Lando Norris")])
    rows = {r["token_id"]: r for r in KS.link_rows([ev, mv], Resolver())}
    top5, mover = rows["KXF1TOP5-BAH26-VER"], rows["KXF1BIGGESTMOVER-BAH26-NOR"]
    assert (top5["prediction"], top5["athlete_id"], top5["race_id"]) == ("race_top5", 9002, 134)
    assert (mover["prediction"], mover["athlete_id"], mover["race_id"]) == ("race_biggest_mover", 9001, 134)


# --- OG.com --------------------------------------------------------------------------------------------------

def _og(symbol, who, contract="Race Winner", name="Bahrain Grand Prix 2026"):
    return dict(symbol=symbol, underlying_symbol="F1-00036-2026", display_name=f"{name} {who}", price_tick_size="0.01",
                tradable=True, expiry_timestamp_ms=1796079600000,
                event_details=dict(metaData=dict(PARTICIPANT=who, PREDICT_CONTRACT_TYPE=contract, NAME=name)))


@pytest.mark.quick
def test_og_race_winner_links_to_the_race_its_event_names_nearest_today():
    s = EX.load("og")
    assert D.classify(s, "f1", "Race Winner") == ("race_win", "driver")
    assert D.classify(s, "f1", "Azerbaijan Grand Prix winner") == ("unmodeled", None)
    r = Resolver()
    rows = {x["token_id"]: x for x in D.link_rows(s, "f1", [_og("og-ver", "Max Verstappen"), _og("og-pia", "Oscar Piastri"),
                                                             _og("og-sgp", "Lando Norris", name="Singapore Grand Prix 2026")], {}, r)}
    ver = rows["og-ver"]
    assert (ver["prediction"], ver["athlete_id"], ver["race_id"], ver["params"]["event_key"]) == ("race_win", 9002, 134, "2026-16")
    assert r.calls[0] == ("Bahrain Grand Prix", None, date.today())          # the expiry (Nov 30) isn't the race date
    assert rows["og-pia"]["prediction"] == "unmodeled" and rows["og-pia"]["race_id"] is None     # a driver we can't match
    assert rows["og-sgp"]["prediction"] == "unmodeled" and rows["og-sgp"]["athlete_id"] == 9001   # a race we can't match

    class NoRaces:                     # a resolver without race lookups (Coinbase's): race markets stay as before
        DRIVERS, driver, team = Resolver.DRIVERS, Resolver.driver, Resolver.team
    rows = D.link_rows(s, "f1", [_og("og-ver", "Max Verstappen")], {}, NoRaces())
    assert (rows[0]["prediction"], rows[0]["race_id"]) == ("race_win", None)


@pytest.mark.quick
def test_resolver_race_near_picks_the_closest_race_of_that_name():
    R = object.__new__(PS.Resolver)
    R.races = [(1, "Bahrain Grand Prix", "2026-04", date(2026, 4, 12)), (134, "Bahrain Grand Prix", "2026-16", date(2026, 10, 4))]
    assert R.race("Bahrain Grand Prix") == (1, "2026-04")                        # unchanged without a date
    assert R.race("Bahrain Grand Prix", near=date(2026, 10, 3)) == (134, "2026-16")
    assert R.race("Bahrain Grand Prix", near=date(2026, 5, 1)) == (1, "2026-04")
    assert R.race("Bahrain Grand Prix", datetime(2026, 10, 11, tzinfo=timezone.utc)) == (134, "2026-16")
    assert R.race("Monaco Grand Prix", near=date(2026, 10, 3)) == (None, None)


# --- Polymarket ----------------------------------------------------------------------------------------------

@pytest.mark.quick
def test_polymarket_classifies_fastest_lap_props_and_other_race_events():
    c = PS.classify
    q = "the 2026 F1 Bahrain Grand Prix?"
    assert c("Bahrain Grand Prix: Driver Fastest Lap", f"Will Max Verstappen achieve the fastest lap at {q}") == \
        ("race_fastest_lap", "Bahrain Grand Prix")
    assert c("Bahrain Grand Prix: Constructor Fastest Lap", f"Will Ferrari achieve the fastest lap at {q}") == \
        ("unmodeled", "Bahrain Grand Prix")
    for t, kind in ((f"Will there be a safety car during {q}", "race_safety_car"),
                    (f"Will there be a red flag during {q}", "race_red_flag"),
                    ("Rain during the Bahrain Grand Prix?", "race_rain")):
        assert c(t, t) == (kind, "Bahrain Grand Prix")
    assert c("How many safety cars at the Bahrain Grand Prix?", "2+") == ("unmodeled", None)
    assert c("Bahrain Grand Prix: Driver Winner", f"Will Driver A win {q}") == ("race_win", "Bahrain Grand Prix")
    assert c("Will it rain in London?", "Will it rain in London?") == ("unmodeled", None)


def _pm(slug, question, group, tokens, bid=0.1, ask=0.2):
    return dict(slug=slug, question=question, conditionId="0x" + slug, clobTokenIds=json.dumps(tokens), groupItemTitle=group,
                outcomes=json.dumps(["Yes", "No"]), outcomePrices=json.dumps(["0.15", "0.85"]), bestBid=bid, bestAsk=ask,
                endDate="2026-10-11T07:00:00Z", closed=False, volume="100")


def _pm_events():
    q = "the 2026 F1 Bahrain Grand Prix?"
    fl = dict(slug="rl-fl", title="Bahrain Grand Prix: Driver Fastest Lap", markets=[
        _pm("rl-fl-ver", f"Will Max Verstappen achieve the fastest lap at {q}", "Max Verstappen", ["rl-fl-ver-y", "rl-fl-ver-n"]),
        _pm("rl-fl-a", f"Will Driver A achieve the fastest lap at {q}", "Driver A", ["rl-fl-a-y", "rl-fl-a-n"]),
        _pm("rl-fl-o", f"Will any other driver achieve the fastest lap at {q}", "Other", ["rl-fl-o-y", "rl-fl-o-n"])])
    win = dict(slug="rl-win", title="Bahrain Grand Prix: Driver Winner", markets=[
        _pm("rl-win-a", f"Will Driver A win {q}", "Driver A", ["rl-win-a-y", "rl-win-a-n"])])
    sc = dict(slug="rl-sc", title=f"Will there be a safety car during {q}", markets=[
        _pm("rl-sc", f"Will there be a safety car during {q}", "", ["rl-sc-y", "rl-sc-n"])])
    cfl = dict(slug="rl-cfl", title="Bahrain Grand Prix: Constructor Fastest Lap", markets=[
        _pm("rl-cfl-f", f"Will Ferrari achieve the fastest lap at {q}", "Ferrari", ["rl-cfl-f-y", "rl-cfl-f-n"])])
    return [fl, win, sc, cfl]


def test_polymarket_sync_links_fastest_lap_props_and_tags_placeholders(test_engine, monkeypatch):
    from racinglines.db import models as m
    from racinglines.db.config import get_session
    from racinglines.db.ingest import _upsert, seed
    from racinglines.markets import venues
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        comp = s.scalars(select(m.Competition).filter_by(code="f1_wdc")).one()
        cat = s.scalars(select(m.Category).filter_by(competition_id=comp.id, code="DRV")).one()
        season = _upsert(s, m.Season, dict(competition_id=comp.id, year=2026))
        ver = m.Athlete(display_name="Max Verstappen (links test)", nation="NED")
        ev = m.Event(season_id=season.id, source="test", source_key="rl-2026-16", name="Bahrain Grand Prix (links test)",
                     start_date=date(2026, 10, 4), series_round=16)
        s.add_all([ver, ev])
        s.flush()
        race = m.Race(event_id=ev.id, category_id=cat.id, format=dict(kind="f1"))
        s.add(race)
        s.commit()
        ids = dict(ver=ver.id, race=race.id)
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'rl-%'"))

    class R:
        def __init__(self, conn, year):
            pass

        def driver(self, name):
            return ids["ver"] if name == "Max Verstappen" else None

        def team(self, name):
            return "ferrari" if name == "Ferrari" else None

        def race(self, gp, end_date=None, near=None):
            return (ids["race"], "rl-2026-16") if gp == "Bahrain Grand Prix" else (None, None)
    monkeypatch.setattr(PS, "Resolver", R)

    def handler(req):
        p = dict(req.url.params)
        return httpx.Response(200, json=_pm_events() if p.get("tag_slug") == "f1" and p.get("closed") == "false" else [])
    real = httpx.Client
    monkeypatch.setattr(PS.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    with test_engine.connect() as c, get_session(url) as s:
        PS.sync(s, c, 2026)
    with test_engine.connect() as c:
        got = {r["token_id"]: r for r in c.execute(text("""SELECT token_id, prediction, athlete_id, race_id, params
                                                           FROM market_links WHERE token_id LIKE 'rl-%'""")).mappings()}
        counts = venues.placeholders(c, ids["race"])
    assert (got["rl-fl-ver-y"]["prediction"], got["rl-fl-ver-y"]["athlete_id"], got["rl-fl-ver-y"]["race_id"]) == \
        ("race_fastest_lap", ids["ver"], ids["race"])
    assert (got["rl-sc-y"]["prediction"], got["rl-sc-y"]["athlete_id"], got["rl-sc-y"]["race_id"]) == \
        ("race_safety_car", None, ids["race"])
    assert (got["rl-cfl-f-y"]["prediction"], got["rl-cfl-f-y"]["race_id"]) == ("unmodeled", ids["race"])
    for tok, kind in (("rl-fl-a-y", "race_fastest_lap"), ("rl-fl-o-y", "race_fastest_lap"), ("rl-win-a-y", "race_win")):
        assert (got[tok]["prediction"], got[tok]["race_id"], got[tok]["params"]["placeholder"]) == ("unmodeled", ids["race"], kind)
    assert "placeholder" not in got["rl-fl-ver-y"]["params"] and "placeholder" not in got["rl-cfl-f-y"]["params"]
    assert counts == {"race_fastest_lap": 2, "race_win": 1}


# --- model_prob ----------------------------------------------------------------------------------------------

def test_model_prob_reads_top5_and_mover(test_engine):
    from racinglines.db import models as m
    from racinglines.db.config import get_session
    from racinglines.db.ingest import _upsert, seed
    from racinglines.db.reads import model_prob
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        comp = s.scalars(select(m.Competition).filter_by(code="f1_wdc")).one()
        cat = s.scalars(select(m.Category).filter_by(competition_id=comp.id, code="DRV")).one()
        season = _upsert(s, m.Season, dict(competition_id=comp.id, year=2026))
        a = m.Athlete(display_name="Top Five", nation="GBR")
        ev = m.Event(season_id=season.id, source="test", source_key="t5-2026-98", name="Top Five GP",
                     start_date=date(2026, 10, 4), series_round=98)
        s.add_all([a, ev])
        s.flush()
        race = m.Race(event_id=ev.id, category_id=cat.id, format=dict(kind="f1"))
        new = m.ModelRun(competition_id=comp.id, season_id=season.id, category_id=cat.id, model="f1_sector_sim", kind="diagnostic")
        old = m.ModelRun(competition_id=comp.id, season_id=season.id, category_id=cat.id, model="f1_sector_sim", kind="diagnostic")
        s.add_all([race, new, old])
        s.flush()
        s.add_all([m.RacePrediction(model_run_id=new.id, race_id=race.id, target="asof:2026-98", athlete_id=a.id, win_prob=0.2,
                                    extra=dict(pole_prob=0.1, top5_prob=0.61, mover_prob=0.08)),
                   m.RacePrediction(model_run_id=old.id, race_id=race.id, target="asof:2026-98", athlete_id=a.id, win_prob=0.2,
                                    extra=dict(pole_prob=0.1))])
        s.commit()
        ids = dict(a=a.id, race=race.id, comp=comp.id, cat=cat.id, new=new.id, old=old.id)
    link = dict(prediction="race_top5", competition_id=ids["comp"], category_id=ids["cat"], athlete_id=ids["a"],
                race_id=ids["race"], params={}, invert=False)
    with test_engine.connect() as c:
        assert model_prob(c, link, run_id=ids["new"]) == (pytest.approx(0.61), ids["new"])
        assert model_prob(c, dict(link, prediction="race_biggest_mover"), run_id=ids["new"])[0] == pytest.approx(0.08)
        assert model_prob(c, link, run_id=ids["old"]) == (None, ids["old"])         # a run saved before these columns
        assert model_prob(c, dict(link, prediction="race_pole"), run_id=ids["old"])[0] == pytest.approx(0.1)
        assert model_prob(c, dict(link, prediction="race_safety_car"), run_id=ids["new"]) == (None, None)    # no model
