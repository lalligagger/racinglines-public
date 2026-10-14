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
# --- any sport: the schema's tape tag, and the tape_source setting on every surface ---------------------------

def test_the_tag_and_staleness_come_from_the_sport_schema():
    from datetime import timedelta
    assert PB.tag_of("f1") == PB.DEFAULT_TAG == "F1" and PB.tag_of("road_cycling") == "CYC"
    assert PB.book_stale_of("f1") == PB.BOOK_STALE == timedelta(hours=48)
    with pytest.raises(ValueError, match="markets.probalytics"):
        PB.tag_of("nascar")                                     # no tape named: an error, never F1's files


@pytest.fixture
def cyc(tmp_path):
    """A road cycling day of Kalshi books and a month of fills under the CYC tag, and an F1 decoy of the same key."""
    (tmp_path / "books").mkdir()
    (tmp_path / "fills").mkdir()
    k = dict(market_platform_id="KXCYCLING-TDF26-POG", outcome_pid="yes")
    _books(tmp_path / "books" / "2026-07-26_CYC_KALSHI.parquet", [
        dict(k, timestamp="2026-07-26 08:00", bid_px=[0.61], bid_sz=[5.0], ask_px=[0.65], ask_sz=[6.0])])
    _books(tmp_path / "books" / "2026-07-26_F1_KALSHI.parquet", [
        dict(k, timestamp="2026-07-26 09:00", bid_px=[0.10], bid_sz=[5.0], ask_px=[0.12], ask_sz=[6.0])])
    pd.DataFrame([dict(market_platform_id=k["market_platform_id"], timestamp=pd.Timestamp("2026-07-26 07:00", tz="UTC"),
                       price=0.6, size=10.0)]).to_parquet(tmp_path / "fills" / "CYC_KALSHI_2026-07.parquet")
    return tmp_path


def test_a_cyc_tape_is_read_by_its_tag(cyc):
    t0, t1 = datetime(2026, 7, 26, 0, 0), datetime(2026, 7, 26, 12, 0)
    key = ["KXCYCLING-TDF26-POG"]
    bk = PB.read_books("kalshi", None, t0, t1, key, base=cyc, tag="CYC")
    assert list(zip(bk["bid"], bk["ask"])) == [(pytest.approx(0.61), pytest.approx(0.65))]
    assert list(PB.read_books("kalshi", None, t0, t1, key, base=cyc)["bid"]) == [pytest.approx(0.10)]   # F1's default
    assert PB.read_fills("kalshi", t0, t1, key, base=cyc, tag="CYC")["usd"].tolist() == [pytest.approx(6.0)]
    assert PB.read_fills("kalshi", t0, t1, key, base=cyc).empty                                 # no F1 fills there


def test_position_replay_reads_the_sports_tape_by_the_setting(cyc, monkeypatch):
    from racinglines.markets import venue_replay as VR
    from racinglines.pipelines import position_replay as P
    monkeypatch.delenv(PB.ENV, raising=False)
    monkeypatch.setenv("PROBALYTICS_DATA", str(cyc))
    links = pd.DataFrame(dict(token_id=["KXCYCLING-TDF26-POG"], condition_id=["KXCYCLING-TDF26"],
                              prediction=["race_win"]))
    stages = [("race day", pd.Timestamp("2026-07-26 10:00"))]
    sp = dict(sport="road_cycling")

    class Ours(VR.Kalshi):
        def __init__(self, *a, **k):
            self.ours = True
    monkeypatch.setitem(VR.EXCHANGES, "kalshi", Ours)
    assert getattr(P._venue(None, "kalshi", links, stages, sp), "ours", False)                 # off by default
    assert getattr(P._venue(None, "kalshi", links, stages, sp, tape="ours"), "ours", False)
    v = P._venue(None, "kalshi", links, stages, sp, tape="probalytics")
    assert isinstance(v, PB.ProbalyticsKalshi) and v.book_stale == PB.BOOK_STALE
    assert v.quote("KXCYCLING-TDF26-POG", stages[0][1]) == (pytest.approx(0.61), pytest.approx(0.65))
    assert v.volume_24h("KXCYCLING-TDF26-POG", stages[0][1]) == pytest.approx(6.0)
    monkeypatch.setenv(PB.ENV, "probalytics")                                                   # the env var still works
    assert isinstance(P._venue(None, "kalshi", links, stages, sp), PB.ProbalyticsKalshi)
    with pytest.raises(ValueError):                                                             # a sport with no tape
        P._venue(None, "kalshi", links, stages, dict(sport="nascar"))


def test_weekend_sweep_takes_the_setting_too(monkeypatch):
    from racinglines.pipelines import weekend_sweep as W
    monkeypatch.delenv(PB.ENV, raising=False)
    links = pd.DataFrame(dict(token_id=[], condition_id=[], prediction=[]))
    v = W._venue(None, links, T, T, "kalshi", event_key="2026-07", tape="probalytics")
    assert isinstance(v, PB.ProbalyticsKalshi) and v.book_stale == PB.BOOK_STALE


def test_tape_source_setting_stays_out_of_every_key_while_unset():
    from racinglines.pipelines import sweep_settings as SS
    d = SS.Settings.from_dict()
    assert d["tape_source"] is None and d.key == "c107835cbced"           # the key test_sweep_settings pins
    ours = SS.Settings.from_dict(dict(tape_source="ours"))
    assert ours["tape_source"] is None and ours.key == d.key and ours.argv() == []
    pb = SS.Settings.from_dict(dict(tape_source="probalytics"))
    assert pb.key != d.key and pb.model_key == d.model_key and pb.argv() == ["--tape-source", "probalytics"]
    with pytest.raises(ValueError):
        SS.Settings.from_dict(dict(tape_source="betfair"))


def test_tape_source_reaches_the_cli():
    import argparse

    from racinglines.pipelines import season_sweep as SW
    from racinglines.pipelines import sweep_settings as SS
    for cls in (SS.Settings, SW.settings_class("nascar")):
        ap = argparse.ArgumentParser()
        SS.add_arguments(ap, cls)
        assert SS.from_args(ap.parse_args(["--tape-source", "probalytics"]), cls)["tape_source"] == "probalytics"
        assert SS.from_args(ap.parse_args([]), cls)["tape_source"] is None


def test_tape_source_reaches_mcp_run_job():
    from racinglines.mcp import tools
    for job in ("f1_sweep", "nascar_sweep"):
        _, p = tools._job_params(job, {"year": "2025", "settings": {"tape_source": "probalytics"}})
        assert p["settings"]["tape_source"] == "probalytics"
    cat = tools.list_job_types()
    assert any(x["name"] == "tape_source" for x in cat["sweep_settings"])
    assert any(x["name"] == "tape_source" for x in cat["sport_sweep_settings"]["nascar"])


def test_tape_source_reaches_the_lab_form():
    from racinglines.pipelines import season_sweep as SW
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.web import jobs
    from racinglines.web.app import templates
    for code in ("f1_sweep", "nascar_sweep"):
        jt = jobs.CATALOG[code]
        p = jobs.parse(jt, {"year": "2025", "tape_source": "probalytics"})
        assert p["settings"]["tape_source"] == "probalytics"
        assert jt.argv(p, "/runs/jobs/job_7.csv")[-2:] == ["--tape-source", "probalytics"]
        assert "tape_source" not in jobs.parse(jt, {"year": "2025", "tape_source": "ours"})["settings"]
    cls = SW.settings_class("nascar")
    groups = [(g, dict(SS.GROUPS).get(g, g.title()), [x for x in cls.SPEC if x.group == g])
              for g in dict.fromkeys(x.group for x in cls.SPEC)]
    jt = jobs.CATALOG["nascar_sweep"]
    html = templates.env.get_template("lab_sport_sweep_form.html").render(
        jt=jt, sel_job=jt.code, sweep_form=dict(groups=groups, defaults=cls.from_dict().to_json(),
                                                start=cls.from_dict().to_json(), year="2025"), csrf_token="t")
    assert 'name="tape_source"' in html


def test_road_cycling_syncs_the_tour_de_france_series():
    from racinglines import sports
    assert "KXTOURDEFRANCE" in sports.kalshi_series("road_cycling")       # KXCYCLING's prefix does not cover it


def test_duplicate_fill_rows_count_once(tmp_path):
    (tmp_path / "fills").mkdir()
    row = dict(fill_id="f1", market_platform_id="KXF1RACE-BARGP26-ANT", timestamp=pd.Timestamp("2026-06-14 10:00", tz="UTC"),
               price=0.32, size=50.0)
    pd.DataFrame([row, row, dict(row, fill_id="f2", size=10.0)]).to_parquet(tmp_path / "fills" / "F1_KALSHI_2026-06.parquet")
    f = PB.read_fills("kalshi", T.replace(hour=0), T, ["KXF1RACE-BARGP26-ANT"], base=tmp_path)
    assert len(f) == 2 and f["usd"].sum() == pytest.approx(0.32 * 60)
