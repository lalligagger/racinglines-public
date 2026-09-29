"""Cross-venue disagreement log (racinglines/markets/disagree.py): fees and edges, the grid, the table."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import text

from racinglines.markets import disagree as D
from racinglines.markets import store as MS

T0 = datetime(2026, 9, 24, tzinfo=timezone.utc)
PM, KS = "test-disagree-pm-token", "KXTEST-DISAGREE-VER"


def _pairs(pm_invert=False, competition_id=1):
    return pd.DataFrame([dict(kind="race_win", athlete_id=None, team=None, opponent_id=None, n=None, subject="A. Driver",
                              competition_id=competition_id, race_id=None, pm_token=PM, pm_invert=pm_invert, pm_link={},
                              kalshi_token=KS, kalshi_invert=False, kalshi_link={})])


class Flat:
    """A fair value of `p` from one run (7), in force from T0 + 2 h."""

    def __init__(self, p, run_id=7):
        self.p, self.run_id = p, run_id

    def runs_at(self, ts):
        return [self.run_id if t >= T0 + timedelta(hours=2) else None for t in ts]

    def prob(self, pair, run_id):
        return self.p


def _stores(root):
    pm = pd.DataFrame(dict(token_id=PM, ts=[T0 + timedelta(minutes=5 * i) for i in range(12 * 12)], price=0.30))
    ks = pd.DataFrame(dict(token_id=KS, ts=[T0 + timedelta(hours=h) for h in (1, 2, 3)], price=[0.36, 0.40, 0.40]))
    MS._write("prices", pd.concat([pm, ks], ignore_index=True), root=root)
    MS._write("books", pd.DataFrame(dict(token_id=[PM], ts=[T0 + timedelta(hours=2, minutes=30)], best_bid=[0.28],
                                         best_ask=[0.32], bids=["[]"], asks=["[]"])), root=root)
    MS._write("trades", pd.DataFrame(dict(token_id=KS, condition_id="KXTEST", outcome_index=0,
                                          ts=[T0 + timedelta(minutes=30), T0 + timedelta(hours=2, minutes=10)],
                                          side="BUY", price=0.4, size=[10.0, 5.0], tx_hash=["a", "b"], wallet="")), root=root)


def test_fees_and_edges():
    assert D.fee("polymarket", 0.5) == 0
    assert D.fee("kalshi", 0.5) == pytest.approx(0.07 * 0.25)
    e, side = D.edge("kalshi", 0.40, 0.30, bid=0.29, ask=0.31)              # buy YES at the ask, Kalshi's fee off
    assert side == "buy" and e == pytest.approx(0.40 - 0.31 - 0.07 * 0.31 * 0.69)
    e, side = D.edge("polymarket", 0.20, 0.30)                              # no book: sell at the mid, no fee
    assert side == "sell" and e == pytest.approx(0.10)
    assert D.edge("kalshi", None, 0.3) == (None, None)
    assert D.gap_net(0.30, 0.35) == pytest.approx(0.05 - 0.07 * 0.35 * 0.65)


def test_build_aligns_both_venues_on_the_grid(tmp_path):
    _stores(tmp_path)
    df = D.build(None, _pairs(), T0, T0 + timedelta(hours=12), fair=Flat(0.40), root=tmp_path)
    # Kalshi closes at 1-3 h, stale after 6 h: rows at ticks 1..9 only (no Kalshi quote at 0 h, none after 9 h)
    assert [int((t - pd.Timestamp(T0)) / pd.Timedelta(hours=1)) for t in df["ts"]] == list(range(1, 10))
    r = df.set_index(df["ts"].map(lambda t: int((t - pd.Timestamp(T0)) / pd.Timedelta(hours=1))))
    assert r.loc[1, "kalshi_mid"] == 0.36 and r.loc[2, "kalshi_mid"] == 0.40 and r.loc[9, "kalshi_mid"] == 0.40
    assert pd.isna(r.loc[1, "fair"]) and pd.isna(r.loc[1, "pm_edge"]) and r.loc[1, "run_id"] is None    # before the run
    assert r.loc[3, "fair"] == 0.40 and r.loc[3, "run_id"] == 7
    # the book recorded at 2:30 gives the 3 h tick its top of book (within one step), not the 2 h or 4 h ticks
    assert pd.isna(r.loc[2, "pm_bid"]) and pd.isna(r.loc[4, "pm_bid"])
    assert (r.loc[3, "pm_bid"], r.loc[3, "pm_ask"], r.loc[3, "pm_mid"]) == (0.28, 0.32, pytest.approx(0.30))
    assert r.loc[3, "pm_side"] == "buy" and r.loc[3, "pm_edge"] == pytest.approx(0.40 - 0.32)
    assert r.loc[3, "kalshi_edge"] == pytest.approx(-0.07 * 0.4 * 0.6)                   # at fair: only the fee
    assert r.loc[3, "gap"] == pytest.approx(0.10) and r.loc[3, "gap_net"] == pytest.approx(0.10 - 0.07 * 0.4 * 0.6)
    # 24 h volume from the tape: Kalshi traded $4 by 1 h and $6 by 3 h; Polymarket has no tape stored (None)
    assert r.loc[1, "kalshi_vol24"] == pytest.approx(4.0) and r.loc[3, "kalshi_vol24"] == pytest.approx(6.0)
    assert pd.isna(r.loc[1, "pm_vol24"]) and D.liquid(df).all()
    rep = D.report(df, "toy")
    assert "toy" in rep and "2026-09-24" in rep and "Win · A. Driver" in rep
    assert len(D.by_day(df)) == 1 and D.by_day(df)["liquid"].iloc[0] == 9


def test_build_flips_an_inverted_link_and_a_dead_tape_is_not_liquid(tmp_path):
    _stores(tmp_path)
    df = D.build(None, _pairs(pm_invert=True), T0, T0 + timedelta(hours=12), fair=Flat(0.40), root=tmp_path)
    r = df.set_index(df["ts"].map(lambda t: int((t - pd.Timestamp(T0)) / pd.Timedelta(hours=1))))
    assert r.loc[3, "pm_mid"] == pytest.approx(0.70) and (r.loc[3, "pm_bid"], r.loc[3, "pm_ask"]) == (pytest.approx(0.68), pytest.approx(0.72))
    assert r.loc[3, "pm_side"] == "sell" and r.loc[3, "pm_edge"] == pytest.approx(0.68 - 0.40)
    # Kalshi's last trade was at 2:10, so from the 27 h tick on its 24 h volume is 0: a gap on paper
    late = D.build(None, _pairs(), T0 + timedelta(hours=27), T0 + timedelta(hours=28), stale=timedelta(days=2),
                   fair=Flat(0.40), root=tmp_path)
    assert len(late) == 2 and late["kalshi_vol24"].tolist() == [pytest.approx(0.0)] * 2 and not D.liquid(late).any()
    assert D.by_day(late)["above_fees"].iloc[0] == 0 and "no liquid row" in D.report(late)


def test_empty_inputs():
    assert len(D.build(None, _pairs().iloc[0:0], T0, T0 + timedelta(hours=1))) == 0
    assert "no tick" in D.report(pd.DataFrame(columns=D.COLS + ["subject"]))
    assert D.runs_at(None, [T0]) == [None]
    runs = pd.DataFrame(dict(run_id=[3, 5], as_of=pd.to_datetime([T0, T0 + timedelta(hours=2)], utc=True)))
    assert D.runs_at(runs, pd.DatetimeIndex([T0 - timedelta(hours=1), T0, T0 + timedelta(hours=3)])) == [None, 3, 5]


def test_table_upserts_and_the_panel_reads_it(test_engine, tmp_path):
    from racinglines.db.config import get_session
    from racinglines.db.ingest import seed
    url = test_engine.url.render_as_string(hide_password=False)
    with get_session(url) as s:
        seed(s)
        s.commit()
    _stores(tmp_path)
    with test_engine.begin() as c:
        comp = c.execute(text("SELECT id FROM competitions WHERE code = 'f1_wdc'")).scalar()
        rid = c.execute(text("INSERT INTO model_runs (competition_id, model, kind, params, metrics) "
                             "VALUES (:c, 'test', 'forecast', '{}', '{}') RETURNING id"), dict(c=comp)).scalar()
        c.execute(text("DELETE FROM market_disagreements WHERE pm_token = :t"), dict(t=PM))
        df = D.build(None, _pairs(competition_id=comp), T0, T0 + timedelta(hours=12), fair=Flat(0.40, rid), root=tmp_path)
        assert D.save(c, df) == 9 and D.save(c, df) == 9                                   # idempotent
        assert c.execute(text("SELECT count(*) FROM market_disagreements WHERE pm_token = :t"), dict(t=PM)).scalar() == 9
        got = pd.read_sql(text("SELECT * FROM market_disagreements WHERE pm_token = :t ORDER BY ts"), c, params=dict(t=PM))
        assert got["gap_net"].iloc[-1] == pytest.approx(0.10 - 0.07 * 0.4 * 0.6) and got["run_id"].iloc[-1] == rid
        assert pd.isna(got["fair"].iloc[0]) and got["pm_side"].iloc[2] == "buy"
        p = D.panel(c, days=10_000)
        row = next(r for r in p["rows"] if r["pm_token"] == PM)
        assert row["kind_label"] == "Win" and row["event"] == "Championship" and row["above"] and row["liquid"]
        assert row["ts"] == pd.Timestamp(T0 + timedelta(hours=9)) and p["last"] >= row["ts"]
        c.execute(text("DELETE FROM market_disagreements WHERE pm_token = :t"), dict(t=PM))
        c.execute(text("DELETE FROM model_runs WHERE id = :r"), dict(r=rid))
