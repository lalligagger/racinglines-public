"""The weather-aware (-WX) variants and their forecast: weather/wet.p_wet_series (the leads CSV's per-model rows as a
walk-forward p_wet per race), the props check's climatology-WX, the DNF check's model-WX and the schema's `wx` hook.
Synthetic data only: the real leads fixture (tests/fixtures/weather/open_meteo-leads-f1.csv) is read in
test_weather.py."""

import numpy as np
import pandas as pd
import pytest

from racinglines.models.position_sim import props as PR
from racinglines.weather import open_meteo as OM
from racinglines.weather import wet as WET

pytestmark = pytest.mark.quick

# 4 races with a forecast (ids 20-23); per race at lead 5 the models' wettest hour (mm), several models per race
WETRACE = {20: True, 21: False, 22: True, 23: False}
MM5 = {20: [0.5, 0.1, 0.0, 2.0, 0.3, 0.0, 0.05],          # 4 of 7 wet (0.1 counts: >= WET_MM)
       21: [0.0, 0.05, 0.2, 0.0, 0.0, 0.0, 0.0],          # 1 of 7
       22: [3.0, 1.0, 0.4, 2.2, 0.9],                     # 5 of 5 (two models missing)
       23: [0.0, 0.0, 0.0, 0.0]}                          # 0 of 4
MM2 = {r: [9.0 if not w else 0.0] * 3 for r, w in WETRACE.items()}    # lead 2: the opposite, 3 models


def _leads(extra=()):
    rows = []
    for lead, mm in ((5, MM5), (2, MM2)):
        for rid, vals in mm.items():
            for i, x in enumerate(vals):
                rows.append(dict(race_id=rid, event_key=f"e{rid}", venue_slug=f"v{rid % 2}", lat=1.0, lon=2.0,
                                 race_start_utc="2025-06-01 13:00:00", window_end_utc="2025-06-01 15:00:00",
                                 lead_days=lead, precip_prob=None, precip_mm=x, temp_c=20.0, wind_kph=10.0,
                                 weather_code=61 if x else 1, max_hour_mm=x, source=f"open_meteo:{OM.MODELS[i]}"))
    rows += list(extra)
    return pd.DataFrame(rows, columns=list(OM.LEAD_COLUMNS))


def _history():
    # 24 races at venues 1 and 2, every 14 days from 2024-11-01: ids 0-19 history only, 20-23 also forecast.
    # Venue 1 is wet every other visit; DNFs are commoner in the wet (4 of 20) than the dry (2 of 20)
    rows = []
    for i in range(24):
        v = 1 if i % 2 == 0 else 2
        wet = WETRACE.get(i, v == 1 and i % 4 == 0)
        rows.append(dict(race_id=i, event_key=f"e{i}", venue_id=v,
                         start=(pd.Timestamp("2024-11-01") + pd.Timedelta(days=14 * i)).strftime("%Y-%m-%d"),
                         sc=i % 3 == 0, red=wet and i % 2 == 0, rain_share=0.4 if wet else 0.0,
                         n=20, n_ok=16 if wet else 18, n_dnf=4 if wet else 2))
    return pd.DataFrame(rows)


def _expected(h, rid, votes, models, prior=WET.PRIOR_VOTES, prior_n=PR.PRIOR_N):
    hp = PR.prepare(h)
    r = hp[hp["race_id"] == rid].iloc[0]
    clim = PR.rate(hp[hp["start"] < r["start"]], r["venue_id"], "wet", prior_n)
    return (votes + prior * clim) / (models + prior)


# --- the forecast: weather/wet.p_wet_series ----------------------------------------------------------------------

def test_votes_count_models_per_race_and_lead():
    v = WET.votes(_leads()).set_index(["race_id", "lead_days"])
    assert v.loc[(20, 5), "models"] == 7 and v.loc[(20, 5), "votes"] == 4
    assert v.loc[(22, 5), "models"] == 5 and v.loc[(22, 5), "votes"] == 5
    assert v.loc[(23, 5), "votes"] == 0 and v.loc[(21, 2), "models"] == 3 and v.loc[(21, 2), "votes"] == 3


def test_p_wet_series_aggregates_the_models_and_shrinks_to_climatology():
    h = _history()
    s = WET.p_wet_series(h, _leads(), 5)
    assert s.name == "p_wet" and list(s.index) == [20, 21, 22, 23]
    for rid, (votes, models) in {20: (4, 7), 21: (1, 7), 22: (5, 5), 23: (0, 4)}.items():
        assert s[rid] == pytest.approx(_expected(h, rid, votes, models))
    assert s[22] > s[20] > s[21] > s[23] > 0                       # climatology keeps 0 votes off zero
    # the lead picks the rows: lead 2 votes the other way
    s2 = WET.p_wet_series(h, _leads(), 2)
    assert s2[21] == pytest.approx(_expected(h, 21, 3, 3)) and s2[20] == pytest.approx(_expected(h, 20, 0, 3))
    assert WET.p_wet_series(h, _leads(), 7).empty                   # no rows at that lead


def test_p_wet_series_is_walk_forward_and_takes_its_settings():
    h = _history()
    base = WET.p_wet_series(h, _leads(), 5)
    # a later race's weather never moves an earlier race's climatology
    later = pd.concat([h, h.iloc[[0]].assign(race_id=99, start="2026-12-01", rain_share=0.9)])
    assert WET.p_wet_series(later, _leads(), 5).equals(base)
    # the prior (in votes) and the shrinkage (in races) are passed through
    assert WET.p_wet_series(h, _leads(), 5, prior=1.0)[20] == pytest.approx(_expected(h, 20, 4, 7, prior=1.0))
    assert WET.p_wet_series(h, _leads(), 5, prior_n=4.0)[20] == pytest.approx(_expected(h, 20, 4, 7, prior_n=4.0))
    # races before `since` and races not in the history are left out
    assert list(WET.p_wet_series(h, _leads(), 5, since="2025-09-01").index) == [22, 23]
    stray = dict(race_id=500, event_key="x", venue_slug="x", lat=0, lon=0, race_start_utc="2025-06-01 13:00:00",
                 window_end_utc="2025-06-01 15:00:00", lead_days=5, precip_mm=1.0, max_hour_mm=1.0, source="x")
    assert 500 not in WET.p_wet_series(h, _leads([stray]), 5).index


# --- the props check's climatology-WX and the schema's wx hook ---------------------------------------------------

def test_climatology_wx_only_for_races_with_a_forecast():
    h = _history()
    fc = WET.p_wet_series(h, _leads(), 5)
    per, summ = PR.check(history_df=h, start_year=2024, forecast=fc)
    rf = per[per["kind"] == "race_red_flag"].reset_index(drop=True)
    has = rf["event_key"].isin([f"e{r}" for r in WETRACE])
    col = "climatology-WX"
    assert has.sum() == 4 and rf.loc[has, col].notna().all() and rf.loc[~has, col].isna().all()
    assert per.loc[per["kind"] == "race_rain", col].isna().all()             # rain is the forecast, not conditioned
    hp = PR.prepare(h)
    r22 = rf[rf["event_key"] == "e22"].iloc[0]
    assert r22[col] == pytest.approx(PR.rate_wx(hp[hp["start"] < hp.loc[22, "start"]], 1, "red", fc[22]))
    s = summ.set_index(["kind", "method"])
    assert s.loc[("race_red_flag", col), "races"] == 4
    assert s.loc[("race_red_flag", "climatology"), "races"] == len(rf)
    pr = s.loc[("race_red_flag", "climatology-WX - climatology")]
    both = rf[has]
    y = both["y"].astype(float).to_numpy()
    d = (both[col].to_numpy() - y) ** 2 - (both["climatology"].to_numpy() - y) ** 2
    assert pr["races"] == 4 and pr["brier"] == pytest.approx(d.mean()) and pr["se"] == pytest.approx(d.std(ddof=1) / 2)
    assert ("race_rain", "climatology-WX - climatology") not in s.index
    assert not summ["method"].str.contains("circuit-WX").any()
    _, plain = PR.check(history_df=h, start_year=2024)                    # no forecast: no WX rows
    assert not plain["method"].str.contains("WX").any()


def test_wx_is_read_from_the_schema():
    from racinglines.markets import kinds as K
    from racinglines.markets import payoffs as PO
    assert PR.WX_KINDS == ("race_red_flag",) and K.wx_kinds("rate") == PR.WX_KINDS
    want = {c for c, e in PO.load().items()
            if e["payoff"]["predicate"] in ("retired", "nth_retired", "classified", "last_classified")}
    assert set(PR.WX_DNF_KINDS) == want and "race_retire" in want and "race_team_both_classified" in want
    assert K.KINDS["race_retire"].wx == "dnf" and K.KINDS["race_constructor_win"].wx is None
    assert all(K.KINDS[c].wx is None for c in K.KINDS if K.KINDS[c].spec is None)
    assert "race_red_flag" not in K.KINDS                      # a prop: not a prediction kind


def test_a_bad_wx_in_the_schema_is_refused(tmp_path):
    from racinglines.markets import payoffs as PO
    p = tmp_path / "kinds.toml"
    p.write_text('[[kinds]]\ncode = "x"\nwx = "rain"\npayoff = { subject = "driver", predicate = "retired" }\n')
    with pytest.raises(ValueError, match="wx"):
        PO.load(p)


def test_wx_scale_is_one_at_the_circuits_own_wet_rate():
    h = PR.prepare(_history())
    assert "dnf_rate" in h and h.loc[0, "dnf_rate"] == pytest.approx(4 / 20)        # race 0 is wet
    for v in (1, 2):
        assert PR.wx_scale(h, v, PR.rate(h, v, "wet")) == pytest.approx(1.0)
    assert PR.wx_scale(h, 1, 1.0) > 1 > PR.wx_scale(h, 1, 0.0)                     # wet races retire more here
    assert PR.wx_scale(h, 1, None) == 1.0 and PR.wx_scale(h.iloc[:0], 1, 0.9) == 1.0
    assert PR.wx_scale(h.assign(dnf_rate=0.0), 1, 0.9) == 1.0                      # nothing to scale
    # a fractional column shrinks like a bool one: rate() is the mean, shrunk
    v = h.loc[h["venue_id"] == 1, "dnf_rate"]
    assert PR.rate(h, 1, "dnf_rate", 16) == pytest.approx((v.sum() + 16 * h["dnf_rate"].mean()) / (len(v) + 16))
    # n missing: n_ok + n_dnf
    assert PR.prepare(_history().drop(columns="n")).loc[0, "dnf_rate"] == pytest.approx(4 / 20)


def test_market_set_scales_dnf_prob_for_the_dnf_kinds():
    from racinglines.markets import kinds as K
    h = PR.prepare(_history())
    preds = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4], driver=list("ABCD"), team_key=["x", "x", "y", "y"],
                              win_prob=[0.4, 0.3, 0.2, 0.1], podium_prob=[0.8, 0.7, 0.6, 0.5],
                              top10_prob=[1.0] * 4, dnf_prob=[0.1, 0.2, 0.0, 0.5]))
    kinds = ("race_red_flag", "race_retire", "race_team_both_classified", "race_n_retirements")
    base = PR.market_set(preds, 1, h, kinds, lines={"race_n_retirements": [0.5]})
    by = {m["key"]: m for m in base}
    assert by["race_retire:2"]["fair"] == pytest.approx(0.2, abs=0.01) and by["race_retire:3"]["fair"] == 0.0
    assert by["race_team_both_classified:x"]["params"] == {"team": "x"}
    assert by["race_team_both_classified:x"]["fair"] == pytest.approx(0.9 * 0.8, abs=0.01)
    assert by["race_n_retirements:0.5"]["fair"] == pytest.approx(1 - 0.9 * 0.8 * 0.5, abs=0.01)
    assert PR.market_set(preds, 1, h, ("race_n_retirements",)) == []               # a field kind needs a line
    wet = {m["key"]: m["fair"] for m in PR.market_set(preds, 1, h, kinds, p_wet=1.0, lines={"race_n_retirements": [0.5]})}
    sc = PR.wx_scale(h, 1, 1.0)
    assert sc > 1
    assert wet["race_retire:2"] == pytest.approx(0.2 * sc, abs=0.01) and wet["race_retire:3"] == 0.0
    assert wet["race_red_flag"] == pytest.approx(PR.rate_wx(h, 1, "red", 1.0))
    # the scaled preds price exactly as preds with that dnf_prob would
    same = PR.dnf_markets(preds.assign(dnf_prob=(preds["dnf_prob"] * sc).clip(0, 1)), ("race_retire",))
    assert [m["fair"] for m in same] == [wet[f"race_retire:{a}"] for a in (1, 2, 3, 4)]
    assert set(K.wx_kinds("dnf")) >= {"race_retire", "race_n_retirements"}


def test_dnf_check_adds_model_wx():
    from racinglines.models.position_sim import dnf_check as DC
    h = _history()
    fc = WET.p_wet_series(h, _leads(), 5)
    rows = []
    for race in (19, 20, 22):                                 # 19 has no forecast
        for a, (p, st) in enumerate([(0.05, "OK"), (0.10, "DNF"), (0.20, "OK"), (0.30, "DSQ")]):
            rows.append(dict(race_id=race, run_id=race, cutoff="2025-01-01", athlete_id=a, team=f"t{a // 2}",
                             dnf_prob=p, status=st))
    df = pd.DataFrame(rows)
    plain = DC.check(df)
    assert list(plain["summary"]["method"]) == ["model", "field", "race_mean"]
    out = DC.check(df, forecast=fc, history_df=h)
    s = out["summary"].set_index("method")
    assert list(s.index) == ["model", "field", "race_mean", "model-WX", "model-WX - model"]
    assert s.loc["model-WX", "rows"] == 8 and out["totals"]["wx_races"] == 2
    hp = PR.prepare(h)
    sc = {r: PR.wx_scale(hp[hp["start"] < hp.loc[r, "start"]], hp.loc[r, "venue_id"], fc[r]) for r in (20, 22)}
    p = np.array([0.05, 0.10, 0.20, 0.30])
    y = np.array([0, 1, 0, 1.0])
    wx = np.concatenate([np.clip(p * sc[20], 0, 1), np.clip(p * sc[22], 0, 1)])
    yy = np.concatenate([y, y])
    assert s.loc["model-WX", "brier"] == pytest.approx(((wx - yy) ** 2).mean())
    assert s.loc["model-WX - model", "rows"] == 8
    assert s.loc["model-WX - model", "brier"] == pytest.approx(((wx - yy) ** 2).mean() - ((np.tile(p, 2) - yy) ** 2).mean())
    assert "model-WX on the 2 races" in DC.render(out) and "model-WX - model" in DC.render(out)
    assert list(DC.check(df, forecast=fc)["summary"]["method"]) == ["model", "field", "race_mean"]   # needs both


def test_cli_runs_the_wx_checks_on_csvs(tmp_path, capsys):
    from racinglines.cli import f1
    leads, hist = tmp_path / "leads.csv", tmp_path / "history.csv"
    _leads().to_csv(leads, index=False)
    _history().to_csv(hist, index=False)
    f1.main(["props", "--check", "--from", "2024", "--history", str(hist), "--forecast", str(leads), "--lead", "2"])
    out = capsys.readouterr().out
    assert "climatology-WX - climatology" in out and "circuit-WX" not in out
    dnf = tmp_path / "dnf.csv"
    pd.DataFrame([dict(race_id=20, run_id=1, cutoff="2025-01-01", athlete_id=a, team="t", dnf_prob=0.1 * (a + 1),
                       status="DNF" if a == 2 else "OK") for a in range(4)]).to_csv(dnf, index=False)
    f1.main(["props", "--dnf-check", str(dnf), "--history", str(hist), "--forecast", str(leads), "--lead", "5"])
    assert "model-WX - model" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        f1.main(["props", "--forecast-skill", "--forecast", str(leads), "--history", str(hist)])
