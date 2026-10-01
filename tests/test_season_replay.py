"""The champion-market replay of the result-only sports (pipelines/season_replay.py) and the MotoGP season simulation
(models/motogp_season.py): points, standings as of a date, the listing classifier, decisions, and a whole replay on a
synthetic season for NASCAR and MotoGP (no database: the readers are replaced)."""

import contextlib
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from racinglines.markets.strategies import season as SS
from racinglines.models import motogp_season as MS
from racinglines.models import nascar_season as NS
from racinglines.models import outcomes as O
from racinglines.pipelines import position_replay as PR
from racinglines.pipelines import season_replay as SR

@pytest.mark.quick
def test_motogp_points_tables():
    assert list(MS.points_for(MS.RACE_POINTS, [1, 2, 3, 15, 16, np.inf])) == [25, 20, 16, 1, 0, 0]
    assert list(MS.points_for(MS.SPRINT_POINTS, [1, 2, 9, 10])) == [12, 9, 1, 0]


@pytest.mark.quick
def test_standings_as_of_a_date_count_only_rounds_before_it():
    pts = pd.DataFrame(dict(date=pd.to_datetime(["2026-03-01", "2026-02-28", "2026-03-08", "2026-03-01"]),
                            athlete_id=[1, 1, 1, 2], kind=["race", "sprint", "race", "race"], position=[1, 1, 1, 2],
                            points=[25.0, 12.0, 25.0, 20.0]))
    st = MS.standings_asof(pts, date(2026, 3, 2)).set_index("athlete_id")
    assert st.loc[1, "points"] == 37 and st.loc[1, "wins"] == 1 and st.loc[2, "points"] == 20
    assert MS.standings_asof(pts, date(2026, 2, 1)).empty
    assert MS.standings_asof(pts).set_index("athlete_id").loc[1, "wins"] == 2


def _sims(n_sims, order, rng, noise=0.0):
    """OutcomeSims over `order` (fastest first), with Gaussian noise in places."""
    score = np.arange(len(order))[None, :] + rng.normal(0, noise, (n_sims, len(order))) if noise else \
        np.tile(np.arange(len(order), dtype=float), (n_sims, 1))
    rank = np.argsort(np.argsort(score, axis=1), axis=1) + 1
    return O.OutcomeSims(entrants=list(order), rank=rank, finished=np.ones_like(rank, bool))


@pytest.mark.quick
def test_motogp_season_simulation_adds_race_and_sprint_points():
    rng = np.random.default_rng(0)
    state = pd.DataFrame(dict(athlete_id=[1, 2, 3], points=[0.0, 40.0, 0.0], wins=[0, 0, 0]))
    race, sprint = _sims(100, [1, 2, 3], rng), _sims(100, [1, 2, 3], rng)
    ss = MS.simulate_season(state, [race, race], [sprint, None], rng)       # two GPs, one sprint
    i = ss.index(1)
    assert (ss.points[:, i] == 25 + 25 + 12).all() and (ss.points[:, ss.index(2)] == 40 + 20 + 20 + 9).all()
    assert (ss.rank[:, ss.index(2)] == 1).all() and (ss.wins[:, i] == 2).all()
    with pytest.raises(ValueError):
        MS.simulate_season(state, [race], [], rng)


@pytest.mark.quick
def test_the_motogp_champion_listing_classifier():
    k = lambda **kw: SR.motogp_champion(dict(kw))                            # noqa: E731
    assert k(exchange="kalshi", event_slug="KXMOTOGP-26", params={"series": "KXMOTOGP"})
    assert not k(exchange="kalshi", event_slug="KXMOTOGPTEAMS-26", params={"series": "KXMOTOGPTEAMS"})
    assert not k(exchange="kalshi", event_slug="KXMOTOGPRACE-26GER", params={"series": "KXMOTOGPRACE"})
    assert k(exchange="polymarket", event_title="MotoGP Championship Winner 2026", question="Will Marc Marquez win?")
    assert not k(exchange="polymarket", event_title="MotoGP Teams Championship 2026", question="Ducati Lenovo?")
    assert not k(exchange="polymarket", event_title="Grand Prix of Germany Winner", question="Will Bagnaia win?")
    assert not k(exchange="polymarket", event_title="Moto2 World Champion 2026", question="?")
    assert SR._year_of(dict(event_title="MotoGP Championship Winner 2026")) == 2026
    assert SR._year_of(dict(event_slug="KXMOTOGP-25")) == 2025
    assert SR._year_of(dict(end_date=pd.Timestamp("2026-11-30", tz="UTC"))) == 2026


@pytest.mark.quick
def test_decisions_are_noon_utc_the_day_after_each_raced_race():
    sch = pd.DataFrame(dict(event_id=[1, 2, 3], name=["A", "B", "C"], race_day=[date(2026, 9, 6), date(2026, 9, 13),
                                                                                date(2026, 9, 20)],
                            done=[True, True, False]))
    got = SR.decision_times(sch)
    assert [lab for lab, _ in got] == ["after R01 A", "after R02 B"]
    assert got[0][1] == pd.Timestamp("2026-09-07 12:00", tz="UTC")


@pytest.mark.quick
def test_link_fairs_invert_a_no_token_and_skip_unmatched():
    links = pd.DataFrame([dict(token_id="y", athlete_id=1, invert=False), dict(token_id="n", athlete_id=1, invert=True),
                          dict(token_id="u", athlete_id=None, invert=False)])
    assert SR.link_fairs(links, {1: 0.3}) == {"y": 0.3, "n": pytest.approx(0.7)}


@pytest.mark.quick
def test_the_replay_is_off_by_default(monkeypatch):
    from racinglines.cli import motogp
    monkeypatch.delenv(SR.SWITCH, raising=False)
    with pytest.raises(SystemExit, match="off by default"):
        motogp.main(["season-replay", "--venue", "kalshi"])


# --- a whole replay on a synthetic season ----------------------------------------------------------------------------

class _Engine:
    class url:
        @staticmethod
        def render_as_string(hide_password=False):
            return "postgresql://unused"

    def connect(self):
        return contextlib.nullcontext(None)


def _season(n=12, run=4, left=3, sprint=False):
    """`run` races run and `left` to go, weekly from 2 Aug 2026; rider/driver 1 always wins, 2 second, ... ."""
    days = [date(2026, 8, 2) + timedelta(days=7 * i) for i in range(run + left)]
    sched = pd.DataFrame(dict(event_id=range(101, 101 + run + left), name=[f"R{i}" for i in range(run + left)],
                              date=days, race_day=days, done=[True] * run + [False] * left))
    rows = []
    for e, d in zip(sched["event_id"][:run], days[:run]):
        for pos in range(1, n + 1):
            rows.append(dict(season=2026, event_id=int(e), event_name=f"R{e}", race_key=str(e), date=d, athlete_id=pos,
                             driver=f"D{pos}", rider=f"D{pos}", position=pos, team=f"T{pos % 4}", status="OK",
                             points=float(MS.points_for(MS.RACE_POINTS, pos)), race=f"2026::{e}"))
    return sched, pd.DataFrame(rows)


def _markets(links, prices, t0):
    """Hourly flat prices from t0 for 60 days, one market per link."""
    ts = np.array([t0 + timedelta(hours=h) for h in range(0, 24 * 60, 6)])
    return {lk["token_id"]: SS.SeasonMarket(key=lk["token_id"], kind="champion", subject=str(lk["athlete_id"]),
                                            ts=ts, px=np.full(len(ts), prices[lk["token_id"]]), cost=0.01)
            for lk in links.to_dict("records")}


@pytest.mark.quick
@pytest.mark.parametrize("sport", ["motogp", "nascar"])
def test_a_champion_replay_trades_the_favourite_the_exchange_underprices(sport, monkeypatch):
    sched, data = _season()
    sp = PR.spec(sport)
    model = PR.model_for(sp)
    monkeypatch.setattr(type(model), "load", staticmethod(lambda engine_url=None, data=None: _season()[1]))
    monkeypatch.setattr(PR, "model_for", lambda sp: model)
    if sport == "nascar":
        sch = sched.assign(chase=False, stages=2.0)
        monkeypatch.setattr(NS, "load_state", lambda conn, year, **kw: (data[["event_id", "athlete_id", "position",
                                                                                "points"]], sch.drop(columns="race_day")))
        monkeypatch.setattr(SR, "schedule", lambda conn, sport, year: sch)
    else:
        monkeypatch.setattr(SR, "schedule", lambda conn, sport, year: sched)
        pts = data.assign(kind="race", date=pd.to_datetime(data["date"]))[["event_id", "date", "athlete_id", "kind",
                                                                             "position", "points"]]
        monkeypatch.setattr(SR, "motogp_points", lambda conn, sp, year: pts)
    links = pd.DataFrame([dict(token_id="lead", athlete_id=1, invert=False), dict(token_id="second", athlete_id=2,
                                                                                  invert=False)])
    prices = {"lead": 0.40, "second": 0.40}                   # the runaway leader cheap, the runner-up dear
    monkeypatch.setattr(SR, "champion_links", lambda conn, sport, year, venue: links)
    t0 = pd.Timestamp("2026-08-01", tz="UTC")
    monkeypatch.setattr(SR, "build_markets", lambda conn, links, venue, asof=None: _markets(links, prices, t0))
    now = pd.Timestamp("2026-09-15", tz="UTC")
    out = SR.run(_Engine(), sport, 2026, venue="kalshi", n_sims=300, now=now, echo=lambda *a: None)
    d = out["decisions"]
    assert list(d["races_left"]) == [6, 5, 4, 3]
    assert len(d) == 4 and (d["favourite"] == 1).all() and d["favourite_fair"].iloc[-1] > 0.4
    tr = out["result"]["trades"]
    assert len(tr) and set(tr.loc[tr["key"] == "lead", "side"]) == {"YES"}
    assert set(tr.loc[tr["key"] == "second", "side"]) <= {"NO"}
    assert "champion replay on kalshi" in SR.format_report(out)
    assert out["sprints"] is (False if sport == "motogp" else None)       # the synthetic season stores no sprints
    assert ("SPRINT POINTS MISSING" in SR.format_report(out)) is (sport == "motogp")


from test_nascar import db, raw  # noqa: E402,F401  (fixtures)
from test_nascar_links import world  # noqa: E402,F401  (fixture: the fixtures' 2026 Cup races and drivers)


@pytest.mark.parametrize("venue", ["kalshi", "og"])
def test_a_nascar_champion_replay_reads_the_real_schema(world, test_engine, venue):
    """On the test database's 2026 Cup races (three run): the schedule, the as-of forecasts and, with no champion
    contract on file, NO TAPE instead of a P&L."""
    with test_engine.connect() as c:
        sch = SR.schedule(c, "nascar", 2026)
    assert sch["done"].sum() >= 2 and {"chase", "race_day"} <= set(sch.columns)
    out = SR.run(test_engine, "nascar", 2026, venue=venue, n_sims=100, now=pd.Timestamp("2027-01-01", tz="UTC"),
                 echo=lambda *a: None)
    d = out["decisions"]
    assert len(d) == int(sch["done"].sum()) and (d["races_left"].diff().dropna() < 0).all()
    assert out["links"] == 0 and "NO TAPE" in SR.format_report(out)
