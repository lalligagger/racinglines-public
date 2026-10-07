"""Settlement parity (core backlog C9, C11): one top-n rule for the walk-forward, the taker replay, the season sweep and
the private book; the biggest mover settled from the stored starting grid; the read-only check of our settlement
against each exchange's resolved_yes (markets/settle_check.py). Synthetic data; the last test uses the Postgres test
database (skipped without one)."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from racinglines.core import walk_forward as WF
from racinglines.markets import kinds as K
from racinglines.markets import payoffs as P
from racinglines.markets import private_book as house
from racinglines.markets import settle_check as SC
from racinglines.models import outcomes as O
from racinglines.pipelines import position_replay as PR

# 1 won; 2 retired late and is still listed 3rd by laps (status DNF); 3 crossed the line 2nd and was disqualified;
# 4 finished 4th; 5 retired early with no place; 6 did not start.
RES = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4, 5, 6], position=[1, 3, 2, 4, np.nan, np.nan],
                        status=["OK", "DNF", "DSQ", "OK", "DNF", "DNS"], grid=[2, 1, 6, 5, 3, 4],
                        team_id=["a", "a", "b", "b", "c", "c"], points=[25.0, 0, 0, 12, 0, 0]))
TOP_N = ("race_win", "race_podium", "race_top5", "race_top10", "race_top20")


def _sims(entrants):
    n = len(entrants)
    rank = np.tile(np.arange(1, n + 1), (4, 1))
    return O.OutcomeSims(entrants=list(entrants), rank=rank, finished=np.ones((4, n), bool))


@pytest.mark.quick
def test_walk_forward_and_replay_settle_a_retirement_and_a_disqualification_alike():
    rows = WF.event_rows(SimpleNamespace(id=1, season=2026, name="t"), _sims(RES["athlete_id"]), RES,
                         kinds=list(TOP_N) + ["race_h2h"])
    assert len(rows) == 4 * 6 + 15                    # race_top20 is a declarative kind: not a walk-forward row
    for a in RES["athlete_id"]:
        assert PR.settle("race_top20", a, None, RES) == K.settle("race_top20", a, None, RES) == (a in (1, 4))
    for r in rows.itertuples():
        b = None if r.opponent is None or pd.isna(r.opponent) else int(r.opponent)
        replay = PR.settle(r.kind, int(r.athlete_id), b, RES)
        assert replay == r.y, (r.kind, r.athlete_id, b)
        assert house.outcome_for(r.kind, int(r.athlete_id), {"opponent_id": b}, RES) == r.y
    top = {(r.kind, r.athlete_id): r.y for r in rows.itertuples() if r.kind != "race_h2h"}
    assert top[("race_podium", 2)] is False and top[("race_top10", 2)] is False       # a DNF is NO, whatever its place
    assert top[("race_podium", 3)] is False and top[("race_win", 1)] is True          # a DSQ is NO
    assert top[("race_podium", 4)] is False and top[("race_top5", 4)] is True         # 2 and 3 don't move 4 up
    assert top[("race_top10", 6)] is False and top[("race_top10", 5)] is False


@pytest.mark.quick
def test_one_top_n_rule_for_the_declarative_kinds_too():
    for n in (1, 3, 5, 10):
        want = list(RES["status"].eq("OK") & RES["position"].le(n))
        assert list(P.top_n(RES, n)) == want
        assert list(P.PREDICATES["top"][1](RES, {"n": n})) == want
    assert K.settle("race_team_double_podium", None, {"team": "a"}, RES) is False      # car 2 retired: not on the podium
    assert K.settle("race_p3", 2, None, RES) is False                                 # an exact place: classified too


@pytest.mark.quick
def test_head_to_head_with_an_unplaced_driver():
    assert K.settle("race_h2h", 4, {"opponent_id": 5}, RES) is True            # a place beats no place
    assert K.settle("race_h2h", 5, {"opponent_id": 4}, RES) is False
    assert K.settle("race_h2h", 5, {"opponent_id": 6}, RES) is False           # neither placed: NO (walk-forward's)
    assert PR.settle("race_h2h", 4, 5, RES) is True and PR.settle("race_h2h", 5, 6, RES) is False
    assert PR.settle("race_win", 99, None, RES) is None and K.settle("race_win", 99, None, RES) is False


# --- the biggest mover -------------------------------------------------------------------------------------------

def mover(res, a):
    return K.settle("race_biggest_mover", a, None, res)


@pytest.mark.quick
def test_biggest_mover_from_the_stored_grid():
    # gains of the classified cars: 1: 2 -> 1 (+1), 4: 5 -> 4 (+1); 2 and 3 aren't classified, so their gains don't count
    assert [mover(RES, a) for a in range(1, 7)] == [True, False, False, True, False, False]   # tied: both YES
    res = RES.assign(grid=[2, 1, 6, 9, 3, 4])
    assert [mover(res, a) for a in (1, 4)] == [False, True]
    assert mover(res, 99) is False


@pytest.mark.quick
def test_biggest_mover_nobody_gained_or_no_grid():
    flat = pd.DataFrame(dict(athlete_id=[1, 2, 3], position=[1, 2, 3], status=["OK"] * 3, grid=[1, 2, 3]))
    assert [mover(flat, a) for a in (1, 2, 3)] == [False, False, False]
    assert mover(flat.drop(columns="grid"), 1) is None
    assert mover(flat.assign(grid=[1, np.nan, 3]), 1) is None                 # a classified car without a slot
    assert P.biggest_mover(flat.drop(columns="grid")) == (None, "no starting grid in the results")


@pytest.mark.quick
def test_biggest_mover_with_a_pit_lane_start():
    # 4 started from the pit lane (grid 0) and finished 4th of 5 starters: at most +1 under any reading of its slot
    res = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4, 5], position=[1, 2, 3, 4, 5], status=["OK"] * 5,
                            grid=[5, 1, 2, 0, 3]))
    assert [mover(res, a) for a in range(1, 6)] == [True, False, False, False, False]      # +4 beats anything 4 could
    tight = res.assign(grid=[2, 1, 3, 0, 4])
    assert mover(tight, 1) is None                                    # 1 gained +1; 4 could have gained +1 too
    assert "pit-lane" in P.biggest_mover(tight)[1]


@pytest.mark.quick
def test_biggest_mover_prices_and_settles_the_same_rule():
    sims = O.OutcomeSims(entrants=[1, 2, 3], rank=np.array([[1, 2, 3], [3, 1, 2]]), finished=np.array([[1, 1, 1], [1, 0, 1]], bool),
                         stage_rank={"qual": np.array([[3, 1, 2], [3, 1, 2]])})
    p = K.fair("race_biggest_mover", sims)
    for s in range(2):
        res = pd.DataFrame(dict(athlete_id=[1, 2, 3], position=sims.rank[s].astype(float),
                                status=np.where(sims.finished[s], "OK", "DNF"), grid=sims.stage_rank["qual"][s]))
        got = [mover(res, a) for a in (1, 2, 3)]
        assert got == list(K.biggest_mover(sims.stage_rank["qual"][s:s + 1], sims.rank[s:s + 1], sims.finished[s:s + 1])[0])
    assert np.allclose(p, [0.5, 0.0, 0.0])


# --- the check against the exchange's resolution ------------------------------------------------------------------

def _link(i, prediction, a, resolved, race=10, **params):
    return dict(link_id=i, token_id=f"T{i}", race_id=race, athlete_id=a, prediction=prediction, params=params or None,
                question=f"q{i}", outcome="Yes", resolved_yes=resolved, event_key="2026-99", event_status="completed")


LINKS = pd.DataFrame([
    _link(1, "race_win", 1, True), _link(2, "race_podium", 2, True),        # 2: the exchange counted the DNF's place
    _link(3, "race_podium", 4, False), _link(4, "race_h2h", 4, True, opponent_id=5),
    _link(5, "race_fastest_lap", 1, True), _link(6, "unmodeled", 1, False),
    _link(7, "unmodeled", 4, True, kind="race_top5"),                     # NASCAR / MotoGP: the kind in params
    _link(8, "race_biggest_mover", 1, True), _link(9, "race_win", 3, None, settlement="void"),
    _link(10, "race_win", 1, True, race=None),
])


@pytest.mark.quick
def test_check_lists_every_disagreement(monkeypatch):
    monkeypatch.setattr(SC, "links", lambda conn, exchange, sport="f1": LINKS)
    df = SC.check(None, "og", "f1", results=lambda rid: RES)
    v = dict(zip(df["link_id"], df["verdict"]))
    assert v == {1: "agree", 2: "disagree", 3: "agree", 4: "agree", 5: "undecided", 6: "unmodeled", 7: "agree",
                 8: "agree", 9: "void", 10: "unmodeled"}
    assert df.set_index("link_id").loc[2, "ours"] is False
    text = SC.text_report(df, "og", "f1")
    assert "disagree 1" in text and "Disagreements (1):" in text and "T2" in text
    assert SC.text_report(df.iloc[:0], "og", "f1").endswith("(nothing to check)")


@pytest.mark.quick
def test_check_says_why_it_cannot_settle():
    no_grid = RES.drop(columns="grid")
    assert SC.verdict(_link(8, "race_biggest_mover", 1, True), no_grid) == (None, "undecided", "no starting grid in the results")
    assert SC.verdict(_link(1, "race_win", 1, True), RES.iloc[:0])[1:] == ("undecided", "no result stored for the race")
    cancelled = dict(_link(1, "race_win", 1, True), event_status="cancelled")
    assert SC.verdict(cancelled, RES)[1] == "undecided"


def test_check_command_on_synthetic_links(test_engine, capsys):
    """The real query and the CLI: links of one exchange and sport, resolved or void, read-only."""
    from datetime import date

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from racinglines.cli import markets as CLI
    from racinglines.db import models as m
    from racinglines.db.ingest import seed
    from racinglines.markets.kalshi.sync import competition
    url = test_engine.url.render_as_string(hide_password=False)
    with Session(test_engine) as s:
        seed(s)
        s.commit()
        comp, cat = competition(s, "f1")
        season = s.query(m.Season).filter_by(competition_id=comp.id, year=2026).first()
        if season is None:
            season = m.Season(competition_id=comp.id, year=2026)
            s.add(season)
            s.flush()
        ev = m.Event(season_id=season.id, source="f1timing", source_key="c5-check", name="C5 check GP",
                     start_date=date(2026, 10, 4), status="completed")
        s.add(ev)
        s.flush()
        race = m.Race(event_id=ev.id, category_id=cat.id, format={"kind": "f1"})
        s.add(race)
        s.flush()
        rnd = m.Round(race_id=race.id, kind="race", ordinal=5, name="race")
        s.add(rnd)
        s.flush()
        ath = [m.Athlete(display_name=f"C5 check driver {i}") for i in range(4)]
        s.add_all(ath)
        s.flush()
        for a, pos, st, grid in zip(ath, (1, 3, 2, 4), ("OK", "DNF", "OK", "OK"), (4, 1, 2, 3)):
            s.add(m.Result(round_id=rnd.id, athlete_id=a.id, position=pos, status=st, extra={"grid": grid}))
        s.execute(text("DELETE FROM market_links WHERE exchange = 'og'"))
        for i, (kind, a, yes, closed) in enumerate((("race_win", 0, True, True), ("race_podium", 1, True, True),
                                                    ("race_biggest_mover", 0, True, True), ("race_win", 2, None, False))):
            s.add(m.MarketLink(exchange="og", token_id=f"C5-{i}", market_slug=f"C5-{i}", question=f"C5 {kind}",
                               outcome="Yes", competition_id=comp.id, category_id=cat.id, prediction=kind,
                               race_id=race.id, athlete_id=ath[a].id, closed=closed, active=not closed,
                               resolved_yes=yes, params={}))
        s.commit()
        race_id = race.id
    with test_engine.connect() as c:
        df = SC.check(c, "og", "f1")
        assert sorted(house.race_outcomes(c, race_id)["grid"]) == [1.0, 2.0, 3.0, 4.0]
    assert dict(zip(df["token_id"], df["verdict"])) == {"C5-0": "agree", "C5-1": "disagree", "C5-2": "agree"}
    assert CLI.main(["--exchange", "og", "--db", url, "settle", "--check"]) == 1
    out = capsys.readouterr().out
    assert "og f1: 3 resolved links" in out and "C5-1" in out
    assert CLI.main(["--exchange", "og", "--db", url, "settle-check"]) == 1
    capsys.readouterr()
    assert CLI.main(["--exchange", "kalshi", "--db", url, "settle-check"]) in (0, 1)      # every exchange
    assert capsys.readouterr().out.startswith("kalshi f1: ")
