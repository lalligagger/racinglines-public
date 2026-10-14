"""markets/probalytics.py: Probalytics' tape as a backtest venue, on tiny synthetic files (no network, no data)."""

from datetime import datetime

import pandas as pd
import pytest

from racinglines.markets import probalytics as PB

T = datetime(2026, 6, 14, 12, 0)


def _books(path, rows):
    pd.DataFrame(rows).assign(timestamp=lambda d: pd.to_datetime(d["timestamp"], utc=True)).to_parquet(path)


@pytest.fixture
def base(tmp_path):
    (tmp_path / "stages").mkdir()
    (tmp_path / "fills").mkdir()
    pm = dict(market_platform_id="0xc1", outcome_pid="tokA")
    _books(tmp_path / "stages" / "2026-07_POLYMARKET.parquet", [
        dict(pm, timestamp="2026-06-14 11:00", bid_px=[0.40, 0.38], bid_sz=[10.0, 5.0], ask_px=[0.44, 0.50],
             ask_sz=[7.0, 9.0]),
        dict(pm, timestamp="2026-06-14 12:30", bid_px=[0.90], bid_sz=[1.0], ask_px=[0.95], ask_sz=[1.0]),  # after T
        dict(market_platform_id="0xc2", outcome_pid="tokB", timestamp="2026-06-11 00:00", bid_px=[0.2],
             bid_sz=[1.0], ask_px=[0.3], ask_sz=[1.0]),                                                    # > 48 h old
    ])
    ks = dict(market_platform_id="KXF1RACE-BARGP26-ANT")
    _books(tmp_path / "stages" / "2026-07_KALSHI.parquet", [
        dict(ks, outcome_pid="yes", timestamp="2026-06-14 09:00", bid_px=[0.31, 0.30], bid_sz=[4.0, 2.0],
             ask_px=[0.33], ask_sz=[3.0]),
        dict(ks, outcome_pid="no", timestamp="2026-06-14 09:00", bid_px=[0.66], bid_sz=[3.0], ask_px=[0.69],
             ask_sz=[4.0]),
    ])
    fills = lambda key, rows: pd.DataFrame(  # noqa: E731
        [dict(market_platform_id=key, timestamp=pd.Timestamp(t, tz="UTC"), price=p, size=s) for t, p, s in rows])
    fills("0xc1", [("2026-06-13 13:00", 0.5, 10.0), ("2026-06-14 11:59", 0.4, 5.0), ("2026-06-14 12:01", 0.4, 100.0),
                   ("2026-06-12 00:00", 0.5, 1000.0)]).to_parquet(tmp_path / "fills" / "F1_POLYMARKET_2026-06.parquet")
    fills("KXF1RACE-BARGP26-ANT", [("2026-06-14 10:00", 0.32, 50.0)]).to_parquet(
        tmp_path / "fills" / "F1_KALSHI_2026-06.parquet")
    return tmp_path


def _pm(base):
    links = pd.DataFrame(dict(token_id=["tokA", "tokB", "tokZ"], condition_id=["0xc1", "0xc2", "0xcz"],
                              prediction=["race_win"] * 3))
    return PB.ProbalyticsPolymarket(None, links, T.replace(hour=0), T, event_key="2026-07", base=base)


def test_polymarket_mid_as_of_t_never_after(base):
    v = _pm(base)
    assert v.price("tokA", T) == pytest.approx(0.42)        # the 11:00 book; the 12:30 one is after T
    assert v.price("tokA", datetime(2026, 6, 14, 13, 0)) == pytest.approx(0.925)
    assert v.price("tokA", datetime(2026, 6, 14, 10, 0)) is None    # nothing yet
    assert v.quote("tokA", T) is None                       # Polymarket trades at the price, as ours does


def test_stale_after_48_hours_and_exact_keys(base):
    v = _pm(base)
    assert v.price("tokB", T) is None                       # last snapshot 60 h before T
    assert v.price("tokZ", T) is None                       # not on their tape
    assert v.price("tokA ", T) is None                      # exact keys only


def test_volume_24h_counts_fills_up_to_t(base):
    v = _pm(base)
    assert v.volume_24h("0xc1", T) == pytest.approx(0.5 * 10 + 0.4 * 5)    # not 12:01, not two days before
    p, vol, ok = v.view(dict(token_id="tokA", condition_id="0xc1"), T, 5.0)
    assert (p, ok) == (pytest.approx(0.42), True)
    assert v.view(dict(token_id="tokA", condition_id="0xc1"), T, 100.0)[2] is False


def test_kalshi_touch_from_the_yes_book(base):
    links = pd.DataFrame(dict(token_id=["KXF1RACE-BARGP26-ANT"], condition_id=["KXF1RACE-BARGP26"],
                              prediction=["race_win"]))
    v = PB.ProbalyticsKalshi(None, links, T.replace(hour=0), T, event_key="2026-07", base=base)
    assert v.quote("KXF1RACE-BARGP26-ANT", T) == (pytest.approx(0.31), pytest.approx(0.33))
    assert v.price("KXF1RACE-BARGP26-ANT", T) == pytest.approx(0.32)
    assert v.touch_depth("KXF1RACE-BARGP26-ANT", T) == (pytest.approx(3.0), pytest.approx(4.0))
    assert v.volume_24h("KXF1RACE-BARGP26-ANT", T) == pytest.approx(16.0)
    assert v.taker_fee(0.33, 10) == pytest.approx(0.16)     # Kalshi's fee schedule is unchanged


def test_off_by_default(monkeypatch):
    from racinglines.markets import venue_replay as VR
    from racinglines.pipelines import weekend_sweep as W
    monkeypatch.delenv(PB.ENV, raising=False)
    assert not PB.enabled()
    links = pd.DataFrame(dict(token_id=[], condition_id=[], prediction=[]))
    called = {}

    class Ours(VR.Polymarket):
        def __init__(self, *a, **k):
            called["ours"] = True
    monkeypatch.setitem(VR.EXCHANGES, "polymarket", Ours)
    W._venue(None, links, T, T, "polymarket", event_key="2026-07")
    assert called == {"ours": True}
    monkeypatch.setenv(PB.ENV, "probalytics")
    assert PB.enabled()


def test_best_levels_matches_a_loop_whatever_the_level_order():
    import numpy as np
    import pyarrow as pa
    rng = np.random.default_rng(7)
    rows_px, rows_sz = [], []
    for _ in range(300):
        n = int(rng.integers(0, 6))
        px = list(np.round(rng.uniform(0.01, 0.99, n), 2))
        if n >= 2 and rng.random() < 0.3:
            px[1] = px[0]                                   # a tie at the touch: sizes add
        rows_px.append(px)
        rows_sz.append(list(np.round(rng.uniform(1, 50, n), 1)))
    px, sz = pa.array(rows_px, pa.list_(pa.float64())), pa.array(rows_sz, pa.list_(pa.float64()))
    for highest in (True, False):
        price, size = PB.best_levels(px.slice(5), sz.slice(5), highest)   # a sliced array: offsets don't start at 0
        for i, (p, s) in enumerate(zip(rows_px[5:], rows_sz[5:])):
            if not p:
                assert np.isnan(price[i]) and size[i] == 0
                continue
            b = max(p) if highest else min(p)
            assert price[i] == b
            assert size[i] == pytest.approx(sum(q for x, q in zip(p, s) if x == b))


def test_book_at_and_the_fantasy_get_book_walk_the_book_as_of_t(base):
    from datetime import timezone

    from racinglines.fantasy import exchange as EX
    links = pd.DataFrame(dict(token_id=["tokA"], condition_id=["0xc1"], prediction=["race_win"]))
    v = PB.ProbalyticsPolymarket(None, links, T.replace(hour=0), T, event_key="2026-07", base=base, levels=True)
    b = v.book_at("tokA", T)
    assert b["bids"] == [(0.40, 10.0), (0.38, 5.0)] and b["asks"] == [(0.44, 7.0), (0.50, 9.0)]
    assert v.book_at("tokA", datetime(2026, 6, 14, 10, 0)) is None
    got = PB.fantasy_book(v, T.replace(tzinfo=timezone.utc))("tokA")
    assert got["ts"] == T.replace(tzinfo=timezone.utc) and got["snapshot_ts"].hour == 11
    assert EX.walk(got["asks"], 10, 0.50, buy=True) == [(0.44, 7), (0.50, 3)]      # 7 at the touch, 3 one level up


def test_bucket_fetch_and_evict(base, tmp_path, monkeypatch):
    import shutil
    import subprocess
    remote = tmp_path / "remote"
    shutil.copytree(base, remote)
    local = tmp_path / "local"
    local.mkdir()
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd[:3])
        if cmd[2] == "ls":
            d = remote / cmd[3].split("gs://b/pb/", 1)[1].rstrip("/")
            out = "\n".join(f"gs://b/pb/{d.relative_to(remote).as_posix()}/{p.name}" for p in d.iterdir()) if d.exists() else ""
            return subprocess.CompletedProcess(cmd, 0 if d.exists() else 1, out, "")
        for u in cmd[3:-1]:
            shutil.copy(remote / u.split("gs://b/pb/", 1)[1], cmd[-1])
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(PB.subprocess, "run", fake_run)
    monkeypatch.setattr(PB, "_LISTED", {})
    monkeypatch.setenv("PROBALYTICS_BUCKET", "gs://b/pb")
    monkeypatch.setenv("PROBALYTICS_CACHE_EVICT", "1")
    v = _pm(local)
    assert v.price("tokA", T) == pytest.approx(0.42)                 # read from the fetched stage file
    assert v.volume_24h("0xc1", T) == pytest.approx(7.0)
    assert ["gcloud", "storage", "cp"] in calls
    assert not any(local.rglob("*.parquet"))                          # evicted after loading
