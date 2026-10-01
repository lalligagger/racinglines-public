"""
Integration tests on the 2026 Azerbaijan GP (event 2026-15), the first event with
an as-of diagnostic and a stored Polymarket tape. Temporary by design: Baku has
minute prices and trades but no order-book depth; later events recorded with
`racinglines markets record` should replace it.

Needs the database with Baku ingested, diagnostic runs for the event and its
Polymarket tape (`pm-history --fidelity 1`, `markets trades`); skipped otherwise.
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.live      # reads the live database (changes as data arrives)
from sqlalchemy import text

EVENT = "2026-15"
QUALI, RACE = pd.Timestamp("2026-09-25 12:00"), pd.Timestamp("2026-09-26 11:00")


@pytest.fixture(scope="module")
def engine():
    from racinglines.db.config import get_engine
    try:
        e = get_engine()
        with e.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as ex:  # noqa: BLE001
        pytest.skip(f"no database: {ex}")
    return e


@pytest.fixture(scope="module")
def runs(engine):
    with engine.connect() as c:
        df = pd.read_sql(text("""SELECT id, params, metrics FROM model_runs
                                 WHERE kind = 'diagnostic' AND params->>'event_key' = :k ORDER BY id"""), c,
                         params=dict(k=EVENT))
    if not len(df):
        pytest.skip("no diagnostic runs for Baku")
    df["cutoff"] = df["params"].map(lambda p: pd.Timestamp(p["cutoff"]))
    return df.sort_values("cutoff")


@pytest.fixture(scope="module")
def event(engine, runs):
    from racinglines.markets.strategies import maker_replay as R
    from racinglines.markets import store as MS
    with engine.connect() as c:
        toks = [r[0] for r in c.execute(text("SELECT token_id FROM market_links WHERE event_slug LIKE 'f1-azerbaijan%'"))]
        if not toks or not len(MS.read(c, "trades", tokens=toks)):         # Postgres buffer + Parquet archive
            pytest.skip("no Baku trade tape")
        return R.load_event(c, runs["id"].tolist())


# --- the model's inputs -------------------------------------------------------

def test_each_run_only_used_sessions_before_its_cutoff(runs):
    for _, r in runs.iterrows():
        a = r["metrics"]["audit"]
        for sess, start in a["event_sessions"].items():
            used = sess in a["sessions_used"]
            if start is None:
                continue
            assert used == (pd.Timestamp(start) < r["cutoff"]), (r["id"], sess)
        for what, ts in a["latest_data"].items():
            assert ts is None or pd.Timestamp(ts) < r["cutoff"], (r["id"], what, ts)
        assert "race" not in a["sessions_used"]


def test_measurement_view_refuses_future_data(engine):
    from racinglines.models.position_sim import pricing as run
    meas = run.Measurements.load(engine)
    cutoff = QUALI - pd.Timedelta(hours=1)
    v = meas.view(cutoff)
    run.assert_no_leak(v, cutoff)                                   # clean view passes
    bad = v.res.iloc[:1].copy()
    bad["session_ts"] = RACE
    v.res = pd.concat([v.res, bad])
    with pytest.raises(run.LeakageError):
        run.assert_no_leak(v, cutoff)


def test_pre_quali_run_simulates_the_grid(runs):
    pre = runs[runs["cutoff"] < QUALI]
    assert len(pre), "need a pre-qualifying run"
    assert all(m["audit"]["grid"].startswith("simulated") for m in pre["metrics"])


# --- the Polymarket tape ------------------------------------------------------

def test_tape_is_well_formed(event):
    for mk in event["markets"]:
        assert np.all(np.diff(mk.tr_ts) >= 0) and np.all(np.diff(mk.mid_ts) >= 0)
        assert np.all((mk.tr_px >= 0) & (mk.tr_px <= 1)) and np.all(mk.tr_sz > 0)


def test_stages_cover_pre_and_post_quali_and_stop_at_the_race(event):
    starts = [pd.Timestamp(s["start"], tz="UTC") for s in event["stages"]]
    ends = [pd.Timestamp(s["end"], tz="UTC") for s in event["stages"]]
    assert min(starts) < QUALI.tz_localize("UTC") < max(starts)
    assert max(ends) <= RACE.tz_localize("UTC")
    assert all(a < b for a, b in zip(starts, ends))


# --- the replay -----------------------------------------------------------------

@pytest.fixture(scope="module", params=["touch", "through"])
def result(request, event):
    from racinglines.markets.strategies import maker_replay as R
    return R.replay(event, R.Params(fill=request.param))


def test_fills_happen_inside_a_stage_before_its_pull(event, result):
    from racinglines.markets.strategies import maker_replay as R
    p, f = R.Params(), result["fills"]
    for st in event["stages"]:
        g = f[f["run_id"] == st["run_id"]]
        assert (g["ts"] > st["start"]).all()
        last_quote = st["end"] - (int(p.pull_min * 60e9) if st["session_end"] else 0)
        assert (g["ts"] <= last_quote + int(p.step_min * 60e9)).all()
    assert (f["ts"] < pd.Timestamp(RACE, tz="UTC").value).all()


def test_fills_priced_with_the_stage_run(event, result):
    by = {m.cond: m for m in event["markets"]}
    for r in result["fills"].itertuples():
        assert r.fair == pytest.approx(by[r.cond].fairs[r.run_id])


def test_limits_respected(result):
    from racinglines.markets.strategies import maker_replay as R
    p, pos = R.Params(), result["positions"]
    assert pos["inventory"].abs().max() <= p.max_pos + 1e-6
    assert -pos["worst_case"].clip(upper=0).sum() <= p.max_capital + 1e-6


def test_pnl_adds_up(result):
    from racinglines.markets.strategies import maker_replay as R
    s = R.summary(result).loc["total"]
    assert result["fills"]["pnl"].sum() == pytest.approx(s["pnl"])


def test_outcomes_read_only_for_scoring(event):
    """Hiding every outcome changes no quote or fill: results only enter P&L."""
    from racinglines.markets.strategies import maker_replay as R
    blind = dict(event, markets=[replace(m, outcome=None) for m in event["markets"]])
    a, b = R.replay(event), R.replay(blind)
    assert a["fills"][["ts", "cond", "side", "price", "qty"]].equals(b["fills"][["ts", "cond", "side", "price", "qty"]])


def test_touch_fills_at_least_as_much_as_through(event):
    from racinglines.markets.strategies import maker_replay as R
    t = R.summary(R.replay(event, R.Params(fill="touch"))).loc["total", "shares"]
    th = R.summary(R.replay(event, R.Params(fill="through"))).loc["total", "shares"]
    assert t >= th


# --- the web page -------------------------------------------------------------

def test_diag_page_roles(engine, runs):
    from fastapi.testclient import TestClient

    from racinglines.web.app import app
    rid = int(runs["id"].iloc[-1])
    maker, taker = TestClient(app), TestClient(app)
    maker.post("/login", data=dict(username="maker", password="password"))
    taker.post("/login", data=dict(username="taker", password="password"))
    assert maker.get(f"/lab/diagnostics/{rid}").status_code == 200
    assert taker.get(f"/lab/diagnostics/{rid}").status_code == 403
