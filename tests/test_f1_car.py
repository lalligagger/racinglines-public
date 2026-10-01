"""F1 model: the car is shared by teammates (no database)."""

import numpy as np
import pandas as pd

from racinglines.models.position_sim import model as M


def test_teammate_noise_is_correlated_with_the_right_spread():
    rng = np.random.default_rng(0)
    teams = np.array(["a", "a", "b", "b", "c"])
    z = M._noise(rng, 0.5, 0.49, teams, 200_000)
    assert np.allclose(z.std(0), 0.5, atol=0.01)                     # each driver keeps its spread
    assert abs(np.corrcoef(z[:, 0], z[:, 1])[0, 1] - 0.49) < 0.01     # teammates move together
    assert abs(np.corrcoef(z[:, 0], z[:, 2])[0, 1]) < 0.01            # other teams don't
    z0 = M._noise(rng, 0.5, 0.0, teams, 50_000)
    assert abs(np.corrcoef(z0[:, 0], z0[:, 1])[0, 1]) < 0.02


def test_teammate_corr_estimate():
    rng = np.random.default_rng(1)
    rows = []
    for ev in range(300):
        for t in range(5):
            shared = rng.normal()
            for d in range(2):
                rows.append(dict(event_id=ev, team_key=f"t{t}", athlete_id=t * 2 + d, r=0.6 * shared + 0.8 * rng.normal()))
    df = pd.DataFrame(rows)
    assert abs(M.teammate_corr(df, "r") - 0.36) < 0.05
    assert M.teammate_corr(df.head(10), "r") == 0.0                   # too little data -> independent


def _fm(rho_f):
    return M.FinishModel(coef=np.array([1.0, 0, 0, 0, 0, 0]), intercept=0.0, sigma=0.3, sigma_q=0.003,
                         use_track=False, rho_q=0.5, rho_f=rho_f)


def test_shared_noise_makes_teammate_order_more_decisive():
    """With a shared car, teammates' luck partly cancels: the faster-starting teammate
    beats the other more often, and team 1-2s become more likely."""
    e = pd.DataFrame(dict(athlete_id=range(6), team_key=["a", "a", "b", "b", "c", "c"], qp=0.0, rp=0.0, p_dnf=0.0,
                          grid=[1, 2, 3, 4, 5, 6]))
    tf = dict(ease=1.0, street=0.0)
    out = {}
    for rho in (0.0, 0.6):
        sim = M.simulate_race(_fm(rho), e, tf, n_sims=40_000, rng=np.random.default_rng(3), grid_known=True)
        pos = sim["pos"]
        out[rho] = dict(one_two=((pos[:, 0] <= 2) & (pos[:, 1] <= 2)).mean(), ahead=(pos[:, 0] < pos[:, 1]).mean(),
                        cross=(pos[:, 1] < pos[:, 2]).mean())
    assert out[0.6]["one_two"] > out[0.0]["one_two"] * 1.1
    assert out[0.6]["ahead"] > out[0.0]["ahead"] + 0.03                 # teammate h2h more decisive
    assert abs(out[0.6]["cross"] - out[0.0]["cross"]) < 0.03            # other teams' h2h barely changes


def test_car_pace_uses_both_drivers():
    """Team sector deficit = mean of its drivers, so a slow teammate slows the car estimate."""
    laps = pd.DataFrame([
        dict(event_id=1, athlete_id=a, round="qual", lap_time_ms=90000 + d, s1_ms=30000 + d, s2_ms=30000, s3_ms=30000,
             deleted=False, track_status="1", is_accurate=True, pit_in=False, pit_out=False, lap=2)
        for a, d in ((1, 0), (2, 600), (3, 100), (4, 100))])
    res = pd.DataFrame([dict(event_id=1, round=r, athlete_id=a, team_key=t, start_date=pd.Timestamp("2026-01-01"),
                             year=2026, series_round=1, venue="x", race_id=1, driver=str(a), position=a, status="OK",
                             grid=a, points=0, session_ts=pd.Timestamp("2026-01-01"))
                        for r in ("qual", "race") for a, t in ((1, "fast_slow"), (2, "fast_slow"), (3, "even"), (4, "even"))])
    prof = pd.DataFrame(dict(event_id=[1], v_i1=[250.0], v_i2=[250.0], v_fl=[250.0]))
    _, sectors = M.event_measurements(res, laps, prof)
    s1 = sectors[sectors["sector"] == "s1"].set_index("team_key")["def"]
    assert s1["fast_slow"] > s1["even"]          # 1% and 0% avg vs 0.33% each: the fast driver doesn't carry the car
