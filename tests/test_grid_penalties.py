"""Confirmed grid penalties (sports/f1/grid_penalties.toml, models/position_sim/penalties.py): apply() moves the
penalised drivers on known arrays; price_race starts a back-of-grid driver from the back without adding or moving a
random draw; a weekend without a penalty prices exactly as before; the sprint stage takes its own session's
penalties; a penalty announced after the cutoff is left out (the as-of rule). Synthetic data, no database; every
pricing test reads a temporary penalty file, so none depends on the real file's rows."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from racinglines.models import outcomes as O
from racinglines.models.position_sim import penalties as GP
from racinglines.models.position_sim import pricing as run
from racinglines.testing import synthetic as SY

pytestmark = pytest.mark.quick
GP_KEYS = ("pos", "dnf", "points")
NAMES = ["Max Verstappen", "George Russell", "Charles Leclerc", "Lando Norris", "Nico Hülkenberg", "Oscar Piastri"]


def _ents(names=NAMES):
    return pd.DataFrame(dict(athlete_id=range(1, len(names) + 1), driver=names, team_key="t"))


def _pen(driver, kind, places=None, event="2026-06", session="race", **kw):
    row = dict(event=event, driver=driver, session=session, kind=kind, source="https://example.org", **kw)
    if places is not None:
        row["places"] = places
    return GP._validate(0, row)


def _toml(tmp_path, *rows):
    out = []
    for r in rows:
        out.append("[[penalty]]")
        out += [f"{k} = {v if isinstance(v, (int, dt.date)) else repr(v)}".replace("'", '"') for k, v in r.items()]
    p = tmp_path / "grid_penalties.toml"
    p.write_text("\n".join(out) + "\n")
    return p


# --- apply() ------------------------------------------------------------------------------------------------------

def test_back_and_pit_lane_go_behind_everyone_in_their_qualifying_order():
    grid = np.array([1, 2, 3, 4, 5, 6.0])
    assert GP.apply(grid, _ents(), [_pen("russell", "back")]).tolist() == [1, 6, 2, 3, 4, 5]
    out = GP.apply(grid, _ents(), [_pen("norris", "pit_lane"), _pen("George Russell", "back")])
    assert out.tolist() == [1, 5, 2, 6, 3, 4]                     # Russell (P2) ahead of Norris (P4) at the back
    assert grid.tolist() == [1, 2, 3, 4, 5, 6]                    # a new array


def test_places_close_up_and_clamp_ahead_of_the_back_of_grid_group():
    grid = np.array([1, 2, 3, 4, 5, 6.0])
    assert GP.apply(grid, _ents(), [_pen("russell", "places", 3)]).tolist() == [1, 5, 2, 3, 4, 6]
    assert GP.apply(grid, _ents(), [_pen("hulkenberg", "places", 10)]).tolist() == [1, 2, 3, 4, 6, 5]
    both = GP.apply(grid, _ents(), [_pen("hulkenberg", "places", 10), _pen("verstappen", "back")])
    assert both.tolist() == [6, 1, 2, 3, 5, 4]                    # clamped behind the field, ahead of the back


def test_two_dimensional_sims_and_ties_renumber_every_row():
    grid = np.array([[1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1], [2, 1, 6, 6, 3, 4.0]])
    out = GP.apply(grid, _ents(), [_pen("russell", "back")])
    assert out.tolist() == [[1, 6, 2, 3, 4, 5], [5, 6, 4, 3, 2, 1], [1, 6, 4, 5, 2, 3]]
    assert (np.sort(out, axis=1) == np.arange(1, 7)).all()


def test_a_driver_matching_no_entrant_or_two_entrants_is_an_error():
    with pytest.raises(GP.PenaltyError, match="'russel'.*matches no entrant"):
        GP.apply(np.arange(1, 7.0), _ents(), [_pen("russel", "back")])
    two = _ents(NAMES[:5] + ["Mick Verstappen"])
    with pytest.raises(GP.PenaltyError, match="matches 2 entrants"):
        GP.apply(np.arange(1, 7.0), two, [_pen("verstappen", "back")])
    assert GP.apply(np.arange(1, 7.0), two, [_pen("max verstappen", "back")])[0] == 6


def test_the_file_loads_and_validates(tmp_path):
    rows = GP.load()
    rus = [r for r in rows if r["event"] == "2026-17" and r["driver"] == "russell"]
    assert len(rus) == 1 and rus[0]["session"] == "race" and rus[0]["kind"] == "back" and rus[0]["source"]
    assert not [r for r in GP.for_event("2026-17", "sprint") if r["driver"] == "russell"]     # sprint unaffected
    assert GP.load(tmp_path / "missing.toml") == []
    (tmp_path / "empty.toml").write_text("# nothing yet\n")
    assert GP.load(tmp_path / "empty.toml") == []
    for bad, msg in ((dict(kind="grid"), "kind must be"), (dict(kind="places"), "places = N"),
                     (dict(session="qual"), "session must be"), (dict(event="2026-6"), "YYYY-RR"),
                     (dict(source=""), "missing")):
        row = dict(event="2026-06", driver="x", session="race", kind="back", source="s") | bad
        with pytest.raises(GP.PenaltyError, match=msg):
            GP.load(_toml(tmp_path, row))


def test_a_penalty_announced_after_the_cutoff_is_left_out(tmp_path):
    p = _toml(tmp_path, dict(event="2026-06", driver="a", session="race", kind="back", source="s",
                             announced=dt.date(2026, 4, 20)))
    assert GP.for_event("2026-06", "race", "2026-04-19 23:59", path=p) == []
    assert len(GP.for_event("2026-06", "race", "2026-04-20 00:00", path=p)) == 1
    assert len(GP.for_event("2026-06", "race", None, path=p)) == 1
    assert GP.for_event("2026-06", "sprint", None, path=p) == [] and GP.for_event("2026-05", "race", None, path=p) == []


# --- the pricer ---------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def plain():
    m = run.Measurements.from_frames(*SY.f1_frames())
    eid = int(m.drivers["event_id"].max())
    assert run.event_key_of(m, eid) == "2026-06"
    return m, run.history(m), eid


@pytest.fixture(scope="module")
def sprint():
    res, laps, prof = SY.f1_frames()
    ev = sorted(res["event_id"].unique())
    m = run.Measurements.from_frames(*SY.f1_sprint(res, laps, prof, [ev[-1], ev[-3]]))
    return m, run.history(m), ev[-1]


def _price(m, hist, cutoff, eid, seed=3, **kw):
    rng = np.random.default_rng(seed)
    summ, ex = run.price_race(m, hist, cutoff, eid, n_sims=600, rng=rng, **kw)
    return summ, ex, rng.random(4)


def _base(monkeypatch, tmp_path, m, hist, cutoff, eid, rows):
    monkeypatch.setattr(GP, "PATH", tmp_path / "none.toml")
    base = _price(m, hist, cutoff, eid)
    monkeypatch.setattr(GP, "PATH", _toml(tmp_path, *rows))
    return base, _price(m, hist, cutoff, eid)


@pytest.mark.parametrize("when", ["pre_quali", "after_quali"])
def test_a_back_of_grid_driver_starts_last_and_nothing_else_moves(plain, monkeypatch, tmp_path, when):
    m, hist, eid = plain
    q = m.sessions(eid)["qual"]
    cutoff = q - pd.Timedelta(minutes=1) if when == "pre_quali" else q + pd.Timedelta(hours=2)
    (b_summ, b_ex, b_nxt), (summ, ex, nxt) = _base(monkeypatch, tmp_path, m, hist, cutoff, eid, [
        dict(event="2026-06", driver="Driver 03", session="race", kind="back", source="https://example.org")])
    ids = ex["entrants"]["athlete_id"].tolist()
    who = ids[ex["entrants"]["driver"].tolist().index("Driver 03")]
    i, n = ids.index(who), len(ids)
    qual, start = b_ex["sim"]["grid"], ex["sim"]["grid"]
    np.testing.assert_array_equal(ex["sim"]["qual"], qual)       # the grid's draws didn't move
    assert (nxt == b_nxt).all()                                   # nor did the caller's stream
    assert (start[:, i] == n).all()
    behind, ahead = qual > qual[:, [i]], qual < qual[:, [i]]
    assert (start[behind] == qual[behind] - 1).all() and (start[ahead] == qual[ahead]).all()
    win, b_win = (s.set_index("athlete_id")["win_prob"] for s in (summ, b_summ))
    assert win[who] < b_win[who]
    pd.testing.assert_series_equal(summ.set_index("athlete_id")["pole_prob"].sort_index(),
                                   b_summ.set_index("athlete_id")["pole_prob"].sort_index())   # pole: qualifying
    sims = O.from_position_sim(ex["entrants"], ex["sim"])
    np.testing.assert_array_equal(sims.stage_rank["qual"], qual)
    assert ex["audit"]["grid_penalties"] == [dict(event="2026-06", session="race", driver="Driver 03", kind="back",
                                                  source="https://example.org")]
    assert "grid_penalties" not in b_ex["audit"]


def test_a_weekend_without_a_penalty_prices_exactly_as_before(plain, monkeypatch, tmp_path):
    m, hist, eid = plain
    others = [dict(event="2026-05", driver="Driver 03", session="race", kind="back", source="s"),
              dict(event="2026-06", driver="Driver 03", session="sprint", kind="pit_lane", source="s"),
              dict(event="2026-06", driver="Driver 04", session="race", kind="back", source="s",
                   announced=dt.date(2030, 1, 1))]
    q = m.sessions(eid)["qual"]
    for cutoff in (q - pd.Timedelta(minutes=1), q + pd.Timedelta(hours=2)):
        (b_summ, b_ex, b_nxt), (summ, ex, nxt) = _base(monkeypatch, tmp_path, m, hist, cutoff, eid, others)
        for k in GP_KEYS + ("grid",):
            np.testing.assert_array_equal(ex["sim"][k], b_ex["sim"][k])
        assert "qual" not in ex["sim"] and "grid_penalties" not in ex["audit"]
        pd.testing.assert_frame_equal(summ, b_summ)
        assert ex["audit"] == b_ex["audit"] and ex["constructor_top"] == b_ex["constructor_top"]
        assert (nxt == b_nxt).all()


def test_a_sprint_penalty_moves_only_the_sprint_grid(sprint, monkeypatch, tmp_path):
    m, hist, eid = sprint
    cutoff = m.sessions(eid)["sprint"] - pd.Timedelta(minutes=1)          # SQ has run: the sprint grid is known
    (b_summ, b_ex, b_nxt), (summ, ex, nxt) = _base(monkeypatch, tmp_path, m, hist, cutoff, eid, [
        dict(event="2026-06", driver="Driver 01", session="sprint", kind="places", places=5, source="s")])
    for k in GP_KEYS + ("grid",):                                            # the Grand Prix is untouched
        np.testing.assert_array_equal(ex["sim"][k], b_ex["sim"][k])
    assert (nxt == b_nxt).all()
    s, b = ex["sim"]["stages"]["sprint"], b_ex["sim"]["stages"]["sprint"]
    np.testing.assert_array_equal(s["grid"], b["grid"])                      # its pole: the SQ order
    pd.testing.assert_series_equal(summ["sprint_pole_prob"], b_summ["sprint_pole_prob"])
    assert not np.array_equal(s["pos"], b["pos"])
    assert [p["session"] for p in ex["audit"]["grid_penalties"]] == ["sprint"]


def test_a_typo_in_the_file_fails_the_price(plain, monkeypatch, tmp_path):
    m, hist, eid = plain
    monkeypatch.setattr(GP, "PATH", _toml(tmp_path, dict(event="2026-06", driver="Drivr 03", session="race",
                                                          kind="back", source="s")))
    with pytest.raises(GP.PenaltyError, match="matches no entrant"):
        _price(m, hist, m.sessions(eid)["qual"] - pd.Timedelta(minutes=1), eid)
