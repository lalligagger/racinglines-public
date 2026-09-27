"""
F1 regression suite: every pipeline stage on pinned inputs (tests/fixtures), checked
against golden outputs (tests/golden). Small sims, fixed seeds; runs in seconds.

Stages: raw files -> ingest -> measurements -> practice -> car / driver model -> history
-> finishing model -> race pricing -> backtest -> season forecast -> weekend trading
(taker) -> maker replay -> season strategy.
"""

import json

import numpy as np
import pandas as pd
import pytest
from conftest import need, replay_fixture, season_fixture, weekend_fixture
from golden import check

BAKU = "2026-15"


def _event_id(meas, key=BAKU):
    y, r = (int(x) for x in key.split("-"))
    ev = meas.res[(meas.res["year"] == y) & (meas.res["series_round"] == r)]
    return int(ev["event_id"].iloc[0])


def _sessions(meas, key=BAKU):
    return meas.sessions(_event_id(meas, key))


# --- 1. raw FastF1 files -------------------------------------------------------

def test_raw_files():
    raw = need("f1", "raw", "2026")
    out = {}
    for f in sorted(raw.glob("*.parquet")):
        df = pd.read_parquet(f)
        num = df.select_dtypes("number")
        out[f.name] = dict(rows=len(df), cols=sorted(df.columns), sum=float(num.sum().sum()))
    for f in sorted(raw.glob("*.meta.json")):
        m = json.loads(f.read_text())
        out[f.name] = {k: m.get(k) for k in ("session", "event_name", "session_date", "event_format", "total_laps")}
    check("f1_raw_files", out)


# --- 2. ingest into a fresh database -------------------------------------------

def test_ingest(test_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from racinglines.sources.fastf1 import ingest as I
    from racinglines.models.position_sim import model as M
    monkeypatch.setattr(I, "DATA", need("f1", "raw"))
    with sessionmaker(test_engine)() as s:
        I.seed(s)
        s.commit()
        status = I.ingest_event(s, 2026, 15)
        s.commit()
    res, laps, prof = M.load_frames(test_engine)
    check("f1_ingest", dict(
        status=status, results=res.groupby("round").size().to_dict(), laps=laps.groupby("round").size().to_dict(),
        positions=res[res["round"] == "race"].sort_values("position")["driver"].head(5).tolist(),
        profile=json.loads(json.dumps(prof["features"].iloc[0], default=str))))


# --- 3. measurements ------------------------------------------------------------

def test_measurements(f1_meas):
    d, s, p = f1_meas.drivers, f1_meas.sectors, f1_meas.practice
    check("f1_measurements", dict(
        drivers=len(d), sectors=len(s), practice_rows=len(p),
        q_def=d["q_def"].agg(["mean", "std", "count"]).to_dict(), r_def=d["r_def"].agg(["mean", "std", "count"]).to_dict(),
        sector_def=s.groupby("sector")["def"].mean().to_dict(),
        practice=p.groupby("round")[["best_def", "long_def"]].mean().to_dict(),
        team_keys=sorted(d["team_key"].dropna().unique())))


# --- 4. car / driver model at a cutoff -----------------------------------------

def test_car_model(f1_meas):
    from racinglines.models.position_sim import model as M
    from racinglines.models.position_sim import pricing as run
    s = _sessions(f1_meas)
    cutoff = s["fp1"] - pd.Timedelta(minutes=1)
    v = f1_meas.view(cutoff)
    snap = M.snapshot(v.drivers, v.sectors, v.xmap, cutoff)
    tf = M.venue_track_features(v.prof, "baku", cutoff)
    e = M.predict_paces(snap, run.entry_list(f1_meas, _event_id(f1_meas)), tf)
    check("f1_car_model", dict(
        audit=v.audit, team_q={k: list(v_) for k, v_ in snap.team_q.items()}, team_r={k: list(v_) for k, v_ in snap.team_r.items()},
        dnf=snap.dnf_team, track=tf, paces=e[["athlete_id", "qp", "rp", "p_dnf"]].sort_values("athlete_id")))


# --- 5. history + finishing model + practice prior ------------------------------

def test_history_and_finishing_model(f1_meas, f1_hist):
    from racinglines.models.position_sim import model as M
    from racinglines.models.position_sim import practice as PR
    h = f1_hist
    s = _sessions(f1_meas)
    fm = M.fit_finish(h, s["race"])
    tr = h.attrs["practice_train"]
    blend = PR.fit(tr, s["fp1"])
    check("f1_history_model", dict(
        rows=len(h), events=h["event_id"].nunique(), features=h[M.FEATURES].mean().to_dict(),
        coef=list(fm.coef), intercept=fm.intercept, sigma=fm.sigma, sigma_q=fm.sigma_q, rho_q=fm.rho_q, rho_f=fm.rho_f,
        practice_rows=len(tr), blend={f"{k[0]}{k[1]}": [list(c), sd] for k, (c, sd) in sorted(blend.items())}))


# --- 6. race pricing at three cutoffs ------------------------------------------

@pytest.mark.parametrize("stage", ["pre_weekend", "after_fp3", "after_quali"])
def test_price_race(f1_meas, f1_hist, stage):
    from racinglines.models.position_sim import pricing as run
    s = _sessions(f1_meas)
    cutoff = {"pre_weekend": s["fp1"] - pd.Timedelta(hours=1), "after_fp3": s["qual"] - pd.Timedelta(minutes=5),
              "after_quali": s["qual"] + pd.Timedelta(hours=2)}[stage]
    summ, ex = run.price_race(f1_meas, f1_hist, cutoff, _event_id(f1_meas), n_sims=2000, rng=np.random.default_rng(7))
    top = summ.sort_values("athlete_id")
    check(f"f1_price_race_{stage}", dict(
        audit={k: v for k, v in ex["audit"].items() if k != "latest_data"},
        probs=top[["athlete_id", "win_prob", "podium_prob", "top10_prob", "pole_prob", "dnf_prob", "exp_points"]],
        constructor_top=ex["constructor_top"],
        h2h_first=sorted(summ["h2h"].iloc[0].items())[:5]))


# --- 7. backtest ----------------------------------------------------------------

def test_backtest(f1_meas, f1_hist):
    from racinglines.models.position_sim import pricing as run
    bt = run.backtest(f1_meas, f1_hist, 2026, 1500, True, seed=3, last_n=3)
    check("f1_backtest", dict(rows=bt[["event_id", "mode", "brier_win", "brier_podium", "brier_top10", "winner_prob",
                                       "brier_teammate_h2h"]].sort_values(["event_id", "mode"]),
                              summary=run.summarize_backtest(bt).round(10)))


# --- 8. season forecast (championships) -----------------------------------------

def test_season_forecast(f1_meas, f1_hist, f1_schedule):
    from racinglines.models.position_sim import pricing as run
    s = _sessions(f1_meas)
    _, st, ex = run.forecast(f1_meas, f1_hist, 2026, cutoff=s["race"] + pd.Timedelta(hours=4), n_sims=1500,
                             schedule=f1_schedule, race_prices=False)
    check("f1_season_forecast", dict(
        drivers=st[["athlete_id", "current_points", "exp_points", "champion_prob", "top3_prob"]].sort_values("athlete_id"),
        constructors=ex["constructors"][["team_key", "current_points", "exp_points", "champion_prob"]].sort_values("team_key"),
        drift=ex["drift"]))


# --- 9. weekend taker strategies (sweep) ----------------------------------------

def test_weekend_trading():
    from racinglines.markets.strategies import taker_weekend as RB
    out = {}
    for key, markets in weekend_fixture().items():
        for mode in ("update", "hold", "last"):
            tr, per = RB.run_weekend(markets, RB.TakerParams(mode=mode))
            out[f"{key}_{mode}"] = dict(summary=RB.summarize(tr, per), by_stage=RB.by(tr, "stage"), by_kind=RB.by(tr, "kind"))
    check("f1_weekend_trading", out)


# --- 10. maker replay on the Baku tape -----------------------------------------

def test_maker_replay():
    from racinglines.markets.strategies import maker_replay as R
    data = replay_fixture()
    out = {}
    for fill in ("touch", "through"):
        res = R.replay(data, R.Params(fill=fill))
        out[fill] = dict(summary=R.summary(res).round(10), skips=R.skip_reasons(res).to_dict(),
                         fills=res["fills"][["ts", "side", "price", "qty"]].head(20))
    check("f1_maker_replay", out)


# --- 11. season strategy ----------------------------------------------------------

def test_season_strategy():
    from racinglines.markets.strategies import season as SS
    markets, decisions = season_fixture()
    now = pd.Timestamp("2026-09-27", tz="UTC")
    marks = pd.date_range(decisions[0]["t"].normalize(), now, freq="7D")
    out = {}
    for mode in ("update", "hold"):
        r = SS.replay(markets, decisions, SS.SeasonParams(mode=mode), now=now, marks=marks)
        out[mode] = dict(summary=r["summary"], positions=r["positions"].drop(columns=["key"]) if len(r["positions"]) else [],
                         equity=r["equity"], trades=len(r["trades"]))
    check("f1_season_strategy", out)
