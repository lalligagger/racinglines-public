"""Closing-line value per paper bet (racinglines/pipelines/clv.py, `racinglines backtest clv`): one rule for every sport,
kind and venue. Synthetic bets and tape on a far-future season (as tests/test_coverage.py) so the shared test
database's other rows don't count: F1 and NASCAR, Polymarket and Kalshi, YES and NO exposure, taker and maker, the
undecided cases with their reasons, and the aggregate."""

import json
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from racinglines import sports
from racinglines.pipelines import clv as CLV

SEASON = 2097
NOW = pd.Timestamp(f"{SEASON}-03-10T00:00:00Z")


def _competition(c, sport, name):
    code = sports.load(sport)["competition"]["code"]
    comp = c.execute(text("SELECT id FROM competitions WHERE code = :c"), dict(c=code)).scalar()
    if comp is None:
        sid = c.execute(text("INSERT INTO sports (code, name) VALUES (:s, :n) "
                             "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id"), dict(s=sport, n=name)).scalar()
        league = c.execute(text("INSERT INTO leagues (code, name) VALUES (:s, :n) "
                                "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code RETURNING id"), dict(s=sport, n=name)).scalar()
        comp = c.execute(text("INSERT INTO competitions (code, name, league_id, sport_id) VALUES (:c, :n, :l, :s) "
                              "RETURNING id"), dict(c=code, n=name, l=league, s=sid)).scalar()
    return comp


def _race(c, comp, key, day):
    cat = c.execute(text("INSERT INTO categories (competition_id, code, name) VALUES (:c, :k, 'CLV test') RETURNING id"),
                    dict(c=comp, k=f"C{key[-1]}")).scalar()
    sid = c.execute(text("INSERT INTO seasons (competition_id, year) VALUES (:c, :y) RETURNING id"),
                    dict(c=comp, y=SEASON)).scalar()
    ev = c.execute(text("INSERT INTO events (season_id, source, source_key, name, start_date) "
                        "VALUES (:s, 'test', :k, 'Race', :d) RETURNING id"), dict(s=sid, k=key, d=day)).scalar()
    race = c.execute(text("INSERT INTO races (event_id, category_id) VALUES (:e, :c) RETURNING id"),
                     dict(e=ev, c=cat)).scalar()
    return race, sid, cat


@pytest.fixture
def season(test_engine):
    """An F1 race (rounds with stored starts: qualifying Fri 15:00, race Sat 14:00 UTC) and a NASCAR race on Sunday with
    no stored start (closes at 00:00 UTC on race day, the schema's rule); links on Polymarket and Kalshi; tape in
    Postgres; paper bets of one user."""
    with test_engine.begin() as c:
        f1c, nac = _competition(c, "f1", "F1"), _competition(c, "nascar", "NASCAR")
        f1r, f1s, f1cat = _race(c, f1c, "clv-f1", date(SEASON, 3, 7))
        nar, nas, nacat = _race(c, nac, "clv-na", date(SEASON, 3, 8))
        for kind, start in (("qual", f"{SEASON}-03-06T15:00:00"), ("race", f"{SEASON}-03-07T14:00:00")):
            c.execute(text("INSERT INTO rounds (race_id, kind, ordinal, extra) VALUES (:r, :k, 1, CAST(:x AS jsonb))"),
                      dict(r=f1r, k=kind, x=json.dumps({"session_date": start})))
        for tok, cond, ex, comp, race, pred in (
                ("clv-pm-1", "clv-c1", "polymarket", f1c, f1r, "race_win"),
                ("clv-pm-1n", "clv-c1", "polymarket", f1c, f1r, "race_win"),
                ("clv-pm-2", "clv-c2", "polymarket", f1c, f1r, "race_pole"),
                ("clv-k-1", "CLVEV", "kalshi", f1c, f1r, "race_win"),
                ("clv-k-2", "CLVNA", "kalshi", nac, nar, "race_win"),
                ("clv-pm-3", "clv-c3", "polymarket", nac, nar, "race_win"),
                ("clv-fut", "clv-c4", "polymarket", f1c, None, "champion")):
            c.execute(text("""INSERT INTO market_links (token_id, condition_id, exchange, prediction, question, outcome,
                                  competition_id, race_id) VALUES (:t, :cd, :x, :p, 'q', 'Yes', :c, :r)"""),
                      dict(t=tok, cd=cond, x=ex, p=pred, c=comp, r=race))
        for tok, ts, px in (("clv-pm-1", "03-07T13:00", 0.50), ("clv-pm-1", "03-07T15:00", 1.0),   # after the close
                            ("clv-pm-2", "03-06T14:30", 0.25), ("clv-k-1", "03-07T13:00", 0.70),
                            ("clv-k-2", "03-07T23:00", 0.25), ("clv-fut", "03-07T13:00", 0.3)):
            c.execute(text("INSERT INTO market_price_history (token_id, ts, price) VALUES (:t, :ts, :p)"),
                      dict(t=tok, ts=f"{SEASON}-{ts}:00+00:00", p=px))
        c.execute(text("INSERT INTO market_book_snapshots (token_id, ts, best_bid, best_ask, bids, asks) "
                       "VALUES ('clv-k-1', :t, 0.62, 0.66, '[]', '[]')"), dict(t=f"{SEASON}-03-07T13:58:00+00:00"))
        uid = c.execute(text("INSERT INTO users (username, password_hash, role) VALUES ('clvtest', 'x', 'taker') "
                             "RETURNING id")).scalar()
        bets = [  # race, event, key, kind, action, side, price paid, mid, time, detail
            (f1r, "clv-f1", "clv-pm-1", "race_win", "buy", "YES", 0.40, 0.39, "03-07T10:00", {"followed": True}),
            (f1r, "clv-f1", "clv-pm-2", "race_pole", "buy", "NO", 0.70, 0.31, "03-06T12:00", {"followed": True}),
            (f1r, "clv-f1", "clv-pm-2", "race_pole", "sell", "NO", 0.66, 0.33, "03-06T16:00", {"followed": True}),
            (f1r, "clv-f1", "clv-pm-1", "race_win", "buy", "NO", 0.55, 0.44, "03-07T11:00", {"followed": False}),
            (f1r, "clv-f1", "clv-c1", "race_win", "fill", "YES", 0.45, None, "03-07T12:00", {}),
            (f1r, "clv-f1", "clv-k-1", "race_win", "fill", "NO", 0.60, None, "03-07T09:00", {"venue": "kalshi"}),
            (f1r, "clv-f1", "clv-k-9", "race_win", "buy", "YES", 0.50, 0.5, "03-07T09:00", {"venue": "kalshi"}),
            (None, "clv-f1", "clv-fut", "champion", "buy", "YES", 0.20, 0.2, "03-07T09:00", {"followed": True}),
            (nar, "clv-na", "clv-k-2", "race_win", "buy", "YES", 0.20, 0.19, "03-07T18:00",
             {"followed": True, "sport": "nascar", "venue": "kalshi"}),
            (nar, "clv-na", "clv-pm-3", "race_win", "buy", "YES", 0.10, 0.1, "03-07T20:00",
             {"followed": True, "sport": "nascar", "venue": "polymarket"}),
        ]
        for i, (race, ev, key, kind, action, side, px, mid, ts, detail) in enumerate(bets):
            maker = action == "fill"
            c.execute(text("""INSERT INTO strategy_signals (user_id, profile, strategy, race_id, event_key, market_key, kind,
                                  stage, dedupe, action, side, shares, limit_price, price, signal_ts, status, detail)
                              VALUES (:u, :pr, :st, :r, :e, :k, :kind, 's', :d, :a, :sd, 10, :px, :mid, :ts, :status,
                                      CAST(:det AS jsonb))"""),
                      dict(u=uid, pr="M" if maker else "T", st="maker" if maker else "update", r=race, e=ev, k=key,
                           kind=kind, d=f"d{i}", a=action, sd=side, px=px, mid=mid, ts=f"{SEASON}-{ts}:00+00:00",
                           status="filled_paper" if maker else "new", det=json.dumps(detail)))
    yield test_engine
    with test_engine.begin() as c:
        c.execute(text("DELETE FROM strategy_signals WHERE user_id = :u"), dict(u=uid))
        c.execute(text("DELETE FROM users WHERE id = :u"), dict(u=uid))
        c.execute(text("DELETE FROM market_price_history WHERE token_id LIKE 'clv-%'"))
        c.execute(text("DELETE FROM market_book_snapshots WHERE token_id LIKE 'clv-%'"))
        c.execute(text("DELETE FROM market_links WHERE token_id LIKE 'clv-%'"))
        for sid, cat in ((f1s, f1cat), (nas, nacat)):
            c.execute(text("DELETE FROM events WHERE season_id = :s"), dict(s=sid))
            c.execute(text("DELETE FROM seasons WHERE id = :s"), dict(s=sid))
            c.execute(text("DELETE FROM categories WHERE id = :c"), dict(c=cat))


def test_exposure_and_deciding_round():
    assert CLV.exposure("buy", "YES", 0.4) == (0.4, 1)
    assert CLV.exposure("buy", "NO", 0.7) == (pytest.approx(0.3), -1)
    assert CLV.exposure("sell", "NO", 0.7) == (pytest.approx(0.3), 1)
    assert CLV.exposure("sell", "YES", 0.4) == (0.4, -1)
    assert CLV.exposure("fill", "NO", 0.6) == (0.6, -1)          # a maker's ask filled: sold YES at 0.60
    assert CLV.deciding_round("race_win") == "race" and CLV.deciding_round("race_pole") == "qual"
    assert CLV.deciding_round("race_sprint_win") == "sprint"
    assert CLV.deciding_round("not_a_kind") == "race"
    assert CLV.race_day_close(date(2026, 3, 6), "motogp") == pd.Timestamp("2026-03-08")   # [replay] race_day_offset 2


def test_clv_per_bet_and_aggregate(season):
    with season.connect() as c:
        res = CLV.run(c, users=["clvtest"], now=NOW)
    b = res["bets"]
    assert len(b) == 9                                         # the unfollowed taker trade is not a bet
    by = {(r["market_key"], r["action"], r["side"]): r for r in b.to_dict("records")}

    win = by[("clv-pm-1", "buy", "YES")]                       # F1 · Polymarket, YES: closes at the race's stored start
    assert (win["sport"], win["venue"], win["close_rule"]) == ("f1", "polymarket", "race start")
    assert win["close_ts"] == pd.Timestamp(f"{SEASON}-03-07T14:00")
    assert win["close"] == pytest.approx(0.50)                 # the 15:00 price (after the close) is not read
    assert (win["clv"], win["clv_pct"]) == (pytest.approx(0.10), pytest.approx(0.25))
    assert win["mid_move"] == pytest.approx(0.11)

    pole = by[("clv-pm-2", "buy", "NO")]                       # NO exposure; pole closes at qualifying's start
    assert pole["close_rule"] == "qual start" and pole["close"] == pytest.approx(0.25)
    assert (pole["clv"], pole["clv_pct"]) == (pytest.approx(0.05), pytest.approx(0.05 / 0.70))

    late = by[("clv-pm-2", "sell", "NO")]
    assert (late["status"], late["reason"]) == ("undecided", "entered after the close")

    mk = by[("clv-c1", "fill", "YES")]                         # a Polymarket maker keyed by condition: its first token
    assert mk["token"] == "clv-pm-1" and mk["clv"] == pytest.approx(0.05)

    k = by[("clv-k-1", "fill", "NO")]                          # F1 · Kalshi maker, NO: the book's mid, not the candle
    assert k["venue"] == "kalshi" and k["close"] == pytest.approx(0.64)
    assert (k["clv"], k["clv_pct"]) == (pytest.approx(-0.04), pytest.approx(-0.10))

    na = by[("clv-k-2", "buy", "YES")]                         # NASCAR · Kalshi: no stored start, race day 00:00 UTC
    assert (na["sport"], na["close_rule"], na["close_ts"]) == ("nascar", "race day (schema)", pd.Timestamp(f"{SEASON}-03-08"))
    assert (na["clv"], na["clv_pct"]) == (pytest.approx(0.05), pytest.approx(0.25))

    assert by[("clv-pm-3", "buy", "YES")]["reason"] == "no polymarket price in the 6 h before the close"
    assert by[("clv-k-9", "buy", "YES")]["reason"] == "no kalshi link for this market key"
    assert by[("clv-fut", "buy", "YES")]["reason"] == "season market: no race close"

    s = res["summary"].set_index(CLV.GROUP)
    f1pm = s.loc[("f1", "polymarket", "race_win", "update", "T")]
    assert (f1pm["bets"], f1pm["decided"], f1pm["mean_clv"], f1pm["positive_share"]) == (1, 1, pytest.approx(0.10), 1.0)
    pole_row = s.loc[("f1", "polymarket", "race_pole", "update", "T")]
    assert (pole_row["bets"], pole_row["decided"], pole_row["undecided"]) == (2, 1, 1)
    allr = s.loc[("all",) * 5]
    assert (allr["bets"], allr["decided"]) == (9, 5)
    assert allr["mean_clv"] == pytest.approx((0.10 + 0.05 + 0.05 - 0.04 + 0.05) / 5)
    assert allr["positive_share"] == pytest.approx(0.8)
    assert allr["mean_clv_pct"] == pytest.approx((0.25 + 0.05 / 0.7 + 0.05 / 0.45 - 0.10 + 0.25) / 5)

    out = CLV.format_text(res)
    assert "=== CLV per sport x venue x kind" in out and "=== CLV per bet" in out and "undecided:" in out
    assert json.loads(json.dumps(CLV.to_json(res)))["summary"][-1]["bets"] == 9


def test_not_closed_yet_and_filters(season):
    with season.connect() as c:
        res = CLV.run(c, users=["clvtest"], sport="nascar", venue="kalshi", now=pd.Timestamp(f"{SEASON}-03-07T20:00Z"))
    b = res["bets"]
    assert list(b["market_key"]) == ["clv-k-2"] and b["reason"].iloc[0] == "not closed yet"


def test_sweep_trades_get_clv(season):
    """A sweep's in-memory taker trades (key = token, t = the stage time) take the same path."""
    trades = pd.DataFrame(dict(key=["clv-pm-1", "clv-pm-1"], t=pd.to_datetime([f"{SEASON}-03-07T10:00", f"{SEASON}-03-07T12:00"]),
                               side=["YES", "YES"], shares=[10.0, -4.0], price=[0.40, 0.48], mid=[0.39, 0.49],
                               kind="race_win", subject="X", event_key="clv-f1", stage=["a", "b"]))
    with season.connect() as c:
        b = CLV.compute(c, CLV.from_trades(trades, "polymarket", strategy="update"), now=NOW)
    assert list(b["action"]) == ["buy", "sell"] and b["sport"].tolist() == ["f1", "f1"]
    assert b["clv"].tolist() == [pytest.approx(0.10), pytest.approx(-0.02)]   # selling YES at 0.48 before a 0.50 close


def test_clv_writes_nothing(season, tmp_path):
    def snapshot(c):
        return [c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                for t in ("strategy_signals", "paper_positions", "market_links", "market_price_history", "data_changes")]
    with season.connect() as c:
        before = snapshot(c)
        res = CLV.run(c, users=["clvtest"], now=NOW)
        assert snapshot(c) == before
    out = CLV.write(res, tmp_path / "out")
    assert sorted(p.name for p in out.iterdir()) == ["clv_bets.csv", "clv_summary.csv"]


def test_cli_prints_per_bet_and_aggregate(season, capsys, tmp_path):
    from racinglines.cli import backtest as BT
    url = season.url.render_as_string(hide_password=False)
    assert BT.main(["clv", "--db", url, "--user", "clvtest", "--asof", f"{SEASON}-03-10T00:00", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "=== CLV per sport x venue x kind" in out and "=== CLV per bet" in out
    for sport, venue in (("f1", "polymarket"), ("f1", "kalshi"), ("nascar", "kalshi"), ("nascar", "polymarket")):
        assert any(line.split()[:2] == [sport, venue] for line in out.splitlines())
    assert "+25.00%" in out and (tmp_path / "clv_summary.csv").exists()
    assert BT.main(["clv", "--db", url, "--user", "clvtest", "--asof", f"{SEASON}-03-10T00:00", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"][-1]["decided"] == 5
