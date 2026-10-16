"""Closing-line value in every season sweep (pipelines/clv.py sweep, weekend_sweep.season / season_clv): a taker mode's
trades and a maker variant's fills become bets, get their CLV against a stub close-price source, and the saved run's
metrics.clv holds per strategy, strategy x stage (with an 'all' row) and strategy x event rows; the season keeps every
strategy's trades; a failed read never sinks the sweep; the Lab's run page, Edge Finder and MCP edge_finder show it."""

from contextlib import contextmanager
from dataclasses import dataclass

import pandas as pd
import pytest

from racinglines.pipelines import clv as CLV
from racinglines.pipelines import weekend_sweep as WS

RACE = pd.Timestamp("2097-03-07T14:00")      # the stub race's start: every race_win market closes here
NOW = pd.Timestamp("2097-03-10T00:00Z")


class _Engine:
    """An engine whose connection is never used: the stubs below answer every read."""
    @contextmanager
    def connect(self):
        yield None


@pytest.fixture
def stub_closes(monkeypatch):
    """Links (two tokens and a Polymarket maker's condition), the race's close, and the YES price there: 0.50 for
    tok-a (and cond-a, whose outcome-0 token it is), 0.20 for tok-b."""
    def links(conn, by_venue):
        lk = dict(race_id=1, prediction="race_win", competition="f1_wdc", params=None, start_date=None)
        out = {("polymarket", "tok-a"): dict(lk, token_id="tok-a", condition_id="cond-a"),
               ("polymarket", "cond-a"): dict(lk, token_id="tok-a", condition_id="cond-a"),
               ("polymarket", "tok-b"): dict(lk, token_id="tok-b", condition_id="cond-b")}
        return {k: v for k, v in out.items() if k[1] in by_venue.get(k[0], ())}

    monkeypatch.setattr(CLV, "links", links)
    monkeypatch.setattr(CLV, "closes", lambda conn, rows: {(1, "race_win"): (RACE, "race start")})
    monkeypatch.setattr(CLV, "close_prices", lambda conn, wants: {
        (v, t, c): {"tok-a": 0.50, "tok-b": 0.20}[t] for (v, c), toks in wants.items() for t in toks})


def _trades():
    """update: a YES buy at 0.40 (CLV +0.10), a NO buy at 0.70 on tok-b (YES 0.30 -> 0.20: +0.10), a YES buy after
    the close (undecided); hold: a YES sell at 0.55 (+0.05: sold above the 0.50 close); maker: its bid filled at
    0.45 (+0.05) and its ask at 0.48 (-0.02), on the condition whose outcome-0 token is tok-a."""
    t = pd.to_datetime(["2097-03-06T10:00", "2097-03-07T10:00", "2097-03-07T15:00"])
    update = pd.DataFrame(dict(key=["tok-a", "tok-b", "tok-a"], t=t, side=["YES", "NO", "YES"],
                               shares=[10.0, 5.0, 2.0], price=[0.40, 0.70, 0.45], mid=[0.39, 0.31, 0.45],
                               kind="race_win", subject="X", stage=["after FP1", "after Quali", "after Quali"],
                               event_key=["2097-1", "2097-1", "2097-1"]))
    hold = pd.DataFrame(dict(key=["tok-a"], t=t[:1], side=["YES"], shares=[-4.0], price=[0.55], mid=[0.56],
                             kind="race_win", subject="X", stage=["after FP1"], event_key=["2097-1"]))
    maker = pd.DataFrame(dict(ts=[int(pd.Timestamp("2097-03-07T12:00").value)] * 2, cond=["cond-a", "cond-a"],
                              side=["buy", "sell"], price=[0.45, 0.48], qty=[10.0, 10.0], mid=[0.46, 0.47],
                              kind="race_win", subject="X", run_id=[0, 1], stage=["pre-weekend", "after FP1"],
                              event_key=["2097-1", "2097-1"]))
    return dict(update=update, hold=hold, maker=maker)


def test_sweep_clv_per_strategy_stage_and_event(stub_closes):
    summary, per = CLV.sweep(_Engine(), _trades(), "polymarket", "f1", strategies=["update", "hold", "maker"],
                             stages=["pre-weekend", "after FP1", "after Quali"], now=NOW)
    assert len(per) == 6 and set(per["strategy"]) == {"update", "hold", "maker"}
    mk = per[per["strategy"] == "maker"].sort_values("entry")
    assert list(mk["action"]) == ["fill", "fill"] and list(mk["side"]) == ["YES", "NO"]   # bid filled, ask filled
    assert list(mk["token"]) == ["tok-a", "tok-a"]
    assert mk["clv"].tolist() == [pytest.approx(0.05), pytest.approx(-0.02)]

    by = {r["strategy"]: r for r in summary["by_strategy"]}
    assert [r["strategy"] for r in summary["by_strategy"]] == ["update", "hold", "maker"]
    u = by["update"]
    assert (u["bets"], u["decided"], u["undecided"]) == (3, 2, 1)
    assert u["mean_clv"] == pytest.approx(0.10) and u["positive_share"] == 1.0
    assert u["mean_clv_pct"] == pytest.approx((0.10 / 0.40 + 0.10 / 0.70) / 2)
    assert u["mean_mid_move"] == pytest.approx((0.11 + 0.11) / 2)
    assert by["hold"]["mean_clv"] == pytest.approx(0.05)          # sold YES at 0.55 before a 0.50 close
    assert by["maker"]["mean_clv"] == pytest.approx(0.015) and by["maker"]["positive_share"] == 0.5

    stages = [(r["strategy"], r["stage"]) for r in summary["by_stage"]]
    assert stages == [("update", "after FP1"), ("update", "after Quali"), ("update", "all"), ("hold", "after FP1"),
                      ("hold", "all"), ("maker", "pre-weekend"), ("maker", "after FP1"), ("maker", "all")]
    late = summary["by_stage"][1]
    assert (late["bets"], late["decided"], late["mean_clv"]) == (2, 1, pytest.approx(0.10))
    assert {k: v for k, v in summary["by_stage"][2].items() if k != "stage"} == u     # the strategy's 'all' row
    assert [(r["strategy"], r["event_key"], r["bets"]) for r in summary["by_event"]] == \
        [("update", "2097-1", 3), ("hold", "2097-1", 1), ("maker", "2097-1", 2)]
    assert summary["undecided"] == {"entered after the close": 1}

    assert CLV.sweep_line(summary, "update") == "CLV +19.64% (+0.1000) · 100% positive of 2 decided"
    assert CLV.sweep_line(summary, "last") == "CLV n/a (0 of 0 bets decided)"
    assert CLV.sweep_line(dict(error="x"), "update") == "CLV not computed"
    empty, _ = CLV.sweep(_Engine(), {}, "polymarket", "f1", now=NOW)
    assert empty == dict(by_strategy=[], by_stage=[], by_event=[], undecided={})


@dataclass
class _Q:
    mode: str


def test_the_season_keeps_every_strategys_trades_and_a_failed_clv_is_kept_as_an_error():
    tr = _trades()

    def trade_event(ev, plist, widen_kinds):
        modes = {m: dict(pnl=1.0, bought=2.0, trades=1) for m in WS.TAKER_MODES}
        u = tr["update"].drop(columns="event_key").assign(pnl=1.0)
        return dict(modes=modes, trades={"update": u, "hold": tr["hold"].drop(columns="event_key").assign(pnl=0.5),
                                         "last": u.iloc[:0], "early": u.iloc[:0]},
                    makers={"maker": dict(fills=2, notional=9.3, pnl=0.3, markout_60m=0.0, spread_pnl=0.0)},
                    maker_fills={"maker": tr["maker"].drop(columns="event_key")}, markout_by_kind={}, markets=2,
                    tradeable_first=2, tradeable_last=2, scores=[],
                    calib=[dict(stage="after FP1", kind="race_win", fair=0.4, price=0.5, y=1.0)])

    events = [dict(round=i, event_key=f"2097-{i}", event=f"GP {i}", format="conventional", stages=3, last_run_id=None)
              for i in (1, 2)]
    out = WS.season(events, trade_event, dict(bankroll=None), [_Q(m) for m in WS.TAKER_MODES], echo=lambda *a: None)
    st = out["strategy_trades"]
    assert set(st) == {"update", "hold", "maker"}                      # empty modes add no rows
    assert len(st["update"]) == 6 and st["update"]["event_key"].tolist() == ["2097-1"] * 3 + ["2097-2"] * 3
    assert st["maker"]["stage"].tolist() == ["pre-weekend", "after FP1"] * 2
    assert len(out["trades"]) == 6                                     # the update trades, as before

    class Broken:
        def connect(self):
            raise RuntimeError("no database")
    lines = []
    WS.season_clv(Broken(), out, "polymarket", "f1", echo=lines.append)
    assert out["clv"] == dict(error="RuntimeError: no database") and out["clv_bets"] is None
    assert lines == ["  CLV not computed: RuntimeError: no database"]


def _metrics():
    clv = dict(by_strategy=[dict(strategy="update", bets=3, decided=2, undecided=1, mean_clv=0.1, mean_clv_pct=0.1964,
                                 positive_share=1.0, mean_mid_move=0.11)],
               by_stage=[], by_event=[], undecided={"entered after the close": 1})
    return dict(totals=dict(update=dict(pnl=12.5, weekends_up=1, weekends=2, bought=40.0),
                            hold=dict(pnl=-3.0, weekends_up=0, weekends=2, bought=10.0)),
                weekends=[dict(round=1, event_key="2097-1", event="GP 1", update_pnl=12.5, hold_pnl=-3.0)], clv=clv)


def test_the_lab_shows_clv_next_to_pnl():
    from racinglines.web import edge as E
    from racinglines.web.formats import fmt
    m = _metrics()
    rows = E.strategy_rows(m)
    assert [(r["strategy"], r["pnl"], r["mean_clv_pct"], r["decided"]) for r in rows] == \
        [("update", 12.5, 0.1964, 2), ("hold", -3.0, None, None)]                 # no CLV row: blank, not zero
    assert E.clv_of(m, "update")["positive_share"] == 1.0 and E.clv_of(dict(totals={}), "update") is None
    assert fmt(0.1964, "mean_clv_pct") == "19.6%" and fmt(0.5, "positive_share") == "50.0%"


def test_the_run_page_and_mcp_edge_finder_read_metrics_clv(test_engine, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from racinglines.db import config
    from racinglines.db.config import get_session
    from racinglines.db.queries import save_model_run
    from racinglines.mcp import tools as T
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.web import users as U
    from racinglines.web.app import app
    from test_clv import _competition

    db = test_engine.url.render_as_string(hide_password=False)
    with test_engine.begin() as c:
        _competition(c, "f1", "F1")
        c.execute(text("DELETE FROM users WHERE username = 'clvsweep'"))
        c.execute(text("INSERT INTO users (username, password_hash, role) VALUES ('clvsweep', :h, 'pro')"),
                  dict(h=U.hash_password("pw")))
    st = SS.Settings.from_dict({"min_edge": 0.0977})                       # a configuration of its own
    with get_session(db) as s:
        rid = save_model_run(s, competition="f1_wdc", season=None, model="f1_sector_sim", kind="sweep",
                             params=dict(year=2097, rounds=None, sport="f1", venue="polymarket", settings=st.to_json(),
                                         settings_key=st.key, label=st.label(), weekends=1),
                             metrics=_metrics())
    try:
        monkeypatch.setenv("DATABASE_URL", db)
        config.get_engine.cache_clear()
        cl = TestClient(app)
        cl.post("/login", data=dict(username="clvsweep", password="pw"))
        page = cl.get(f"/lab/runs/{rid}")
        assert page.status_code == 200
        assert "Metrics: strategies" in page.text and "Metrics: clv by_stage" in page.text and "19.6%" in page.text
        with test_engine.connect() as c:
            rows = T.edge_finder(c, year=2097, strategy="update")["rows"]["rows"]
        row = next(r for r in rows if r["run_id"] == rid)
        assert row["clv"]["mean_clv_pct"] == 0.1964 and row["pnl"] == 12.5
    finally:
        with test_engine.begin() as c:
            c.execute(text("DELETE FROM model_runs WHERE id = :i"), dict(i=rid))
            c.execute(text("DELETE FROM users WHERE username = 'clvsweep'"))
        config.get_engine.cache_clear()
