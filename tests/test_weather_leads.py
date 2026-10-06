"""Forecast skill by lead time (racinglines/weather/leads.py) and the weather-aware (-WX) variants it feeds: the props
check's circuit-WX, the DNF check's model-WX and the schema's `wx` hook. Synthetic data only: the real leads fixture
(tests/fixtures/weather/open_meteo-leads-f1.csv) is not read here."""

import numpy as np
import pandas as pd
import pytest

from racinglines.weather import leads as L

# 4 races with a forecast (ids 20-23), leads 0-7; lead 3 has no precip_prob (the precip_mm rule decides)
WET = {20: True, 21: False, 22: True, 23: False}
MM3 = {20: 0.5, 21: 0.05, 22: 2.0, 23: 0.0}       # lead 3's precip_mm


def _leads_csv(tmp_path):
    rows = []
    for rid, wet in WET.items():
        for lead in range(8):
            prob = None if lead == 3 else (0.9 - 0.05 * lead if wet else 0.1 + 0.05 * lead)
            rows.append(dict(race_id=rid, event_key=f"2025-{rid:02d}", venue_slug=f"v{rid % 2}", lat=1.0, lon=2.0,
                             race_start_utc=f"2025-{(rid - 15):02d}-01T13:00:00Z",
                             window_end_utc=f"2025-{(rid - 15):02d}-01T15:00:00Z", lead_days=lead,
                             precip_prob=prob, precip_mm=(2.0 if wet else 0.0) if lead != 3 else MM3[rid],
                             temp_c=20.0, wind_kph=10.0, weather_code=61 if wet else 1, source="synthetic"))
    p = tmp_path / "leads.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def _history():
    # 24 races at venues 1 and 2, every 14 days from 2024-11-01: ids 0-19 history only, 20-23 also forecast.
    # Venue 1 is wet every other visit; DNFs are commoner in the wet (4 of 20) than the dry (2 of 20)
    rows = []
    for i in range(24):
        v = 1 if i % 2 == 0 else 2
        wet = WET.get(i, v == 1 and i % 4 == 0)
        rows.append(dict(race_id=i, event_key=f"e{i}", venue_id=v,
                         start=(pd.Timestamp("2024-11-01") + pd.Timedelta(days=14 * i)).strftime("%Y-%m-%d"),
                         sc=i % 3 == 0, red=wet and i % 2 == 0, rain_share=0.4 if wet else 0.0,
                         n=20, n_ok=16 if wet else 18, n_dnf=4 if wet else 2))
    return pd.DataFrame(rows)


@pytest.mark.quick
def test_load_types_and_rejects_bad_frames(tmp_path):
    d = L.load(_leads_csv(tmp_path))
    assert list(d.columns) == list(L.COLUMNS) and len(d) == 32
    assert str(d["race_start_utc"].dt.tz) == "UTC" and d["lead_days"].dtype == int
    assert d.loc[d["lead_days"] == 3, "precip_prob"].isna().all()
    with pytest.raises(ValueError, match="missing columns"):
        L.validate(d.drop(columns=["precip_mm"]))
    with pytest.raises(ValueError, match="outside 0-1"):
        L.validate(d.assign(precip_prob=d["precip_prob"] * 100))
    with pytest.raises(ValueError, match="given twice"):
        L.validate(pd.concat([d, d.iloc[:1]]))


@pytest.mark.quick
def test_p_wet_takes_the_probability_else_the_mm_rule(tmp_path):
    d = L.load(_leads_csv(tmp_path))
    p5 = L.p_wet(d, 5)
    assert list(p5.index) == list(WET) and p5[20] == pytest.approx(0.65) and p5[21] == pytest.approx(0.35)
    p3 = L.p_wet(d, 3)                                  # no precip_prob at lead 3: precip_mm >= 0.1
    assert p3.to_dict() == {20: 1.0, 21: 0.0, 22: 1.0, 23: 0.0}
    assert L.p_wet(d, 3, mm_threshold=1.0).to_dict() == {20: 0.0, 21: 0.0, 22: 1.0, 23: 0.0}
    assert L.p_wet(d, 9).empty


@pytest.mark.quick
def test_skill_scores_every_lead_against_climatology(tmp_path):
    d, h = L.load(_leads_csv(tmp_path)), _history()
    s = L.skill(d, h)
    assert list(s["method"]) == ["forecast"] * 7 + ["climatology", "analysis"]
    assert list(s["lead_days"].iloc[:7]) == list(range(1, 8)) and pd.isna(s["lead_days"].iloc[7])
    assert (s["races"] == 4).all() and (s["wet_rate"] == 0.5).all()
    one = s.iloc[0]
    p = np.array([0.85, 0.15, 0.85, 0.15])
    y = np.array([1, 0, 1, 0.0])
    assert one["brier"] == pytest.approx(((p - y) ** 2).mean()) and one["hit_rate"] == 1.0
    assert one["log_loss"] == pytest.approx(-np.log(0.85))
    assert s.set_index("lead_days").loc[3, "from_prob"] == 0 and s.iloc[0]["from_prob"] == 4
    clim = L.climatology(h, list(WET))
    from racinglines.models.position_sim import props as PR
    hp = PR.prepare(h)
    assert clim[22] == pytest.approx(PR.rate(hp[hp["start"] < hp.loc[22, "start"]], 1, "wet"))
    c = s[s["method"] == "climatology"].iloc[0]
    yc = np.array([WET[r] for r in clim.index], float)
    assert c["brier"] == pytest.approx(((clim.to_numpy() - yc) ** 2).mean())
    assert one["brier_vs_clim"] == pytest.approx(one["brier"] - c["brier"])
    a = s[s["method"] == "analysis"].iloc[0]
    assert a["brier"] == pytest.approx(((np.array([0.9, 0.1, 0.9, 0.1]) - y) ** 2).mean())


# --- the props check's circuit-WX and the schema's wx hook ----------------------------------------------------------

@pytest.mark.quick
def test_circuit_wx_only_for_races_with_a_forecast(tmp_path):
    from racinglines.models.position_sim import props as PR
    h, fc = _history(), L.p_wet(L.load(_leads_csv(tmp_path)), 5)
    per, summ = PR.check(history_df=h, start_year=2024, forecast=fc)
    rf = per[per["kind"] == "race_red_flag"].reset_index(drop=True)
    has = rf["event_key"].isin([f"e{r}" for r in WET])
    assert has.sum() == 4 and rf.loc[has, "circuit-WX"].notna().all() and rf.loc[~has, "circuit-WX"].isna().all()
    assert per.loc[per["kind"] == "race_rain", "circuit-WX"].isna().all()       # rain is the forecast, not conditioned
    hp = PR.prepare(h)
    r22 = rf[rf["event_key"] == "e22"].iloc[0]
    assert r22["circuit-WX"] == pytest.approx(PR.rate_wx(hp[hp["start"] < hp.loc[22, "start"]], 1, "red", fc[22]))
    s = summ.set_index(["kind", "method"])
    assert s.loc[("race_red_flag", "circuit-WX"), "races"] == 4
    assert s.loc[("race_red_flag", "circuit"), "races"] == len(rf)
    pr = s.loc[("race_red_flag", "circuit-WX - circuit")]
    both = rf[has]
    y = both["y"].astype(float).to_numpy()
    d = (both["circuit-WX"].to_numpy() - y) ** 2 - (both["circuit"].to_numpy() - y) ** 2
    assert pr["races"] == 4 and pr["brier"] == pytest.approx(d.mean()) and pr["se"] == pytest.approx(d.std(ddof=1) / 2)
    assert ("race_rain", "circuit-WX - circuit") not in s.index
    _, plain = PR.check(history_df=h, start_year=2024)                    # no forecast: no WX rows
    assert not plain["method"].str.contains("WX").any()


@pytest.mark.quick
def test_wx_is_read_from_the_schema():
    from racinglines.markets import kinds as K
    from racinglines.markets import payoffs as PO
    from racinglines.models.position_sim import props as PR
    assert PR.WX_KINDS == ("race_red_flag",) and K.wx_kinds("rate") == PR.WX_KINDS
    want = {c for c, e in PO.load().items()
            if e["payoff"]["predicate"] in ("retired", "nth_retired", "classified", "last_classified")}
    assert set(PR.WX_DNF_KINDS) == want and "race_retire" in want and "race_team_both_classified" in want
    assert K.KINDS["race_retire"].wx == "dnf" and K.KINDS["race_constructor_win"].wx is None
    assert all(K.KINDS[c].wx is None for c in K.KINDS if K.KINDS[c].spec is None)
    assert "race_red_flag" not in K.KINDS                      # a prop: not a prediction kind


@pytest.mark.quick
def test_a_bad_wx_in_the_schema_is_refused(tmp_path):
    from racinglines.markets import payoffs as PO
    p = tmp_path / "kinds.toml"
    p.write_text('[[kinds]]\ncode = "x"\nwx = "rain"\npayoff = { subject = "driver", predicate = "retired" }\n')
    with pytest.raises(ValueError, match="wx"):
        PO.load(p)


@pytest.mark.quick
def test_wx_scale_is_one_at_the_circuits_own_wet_rate():
    from racinglines.models.position_sim import props as PR
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


@pytest.mark.quick
def test_market_set_scales_dnf_prob_for_the_dnf_kinds():
    from racinglines.markets import kinds as K
    from racinglines.models.position_sim import props as PR
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


@pytest.mark.quick
def test_dnf_check_adds_model_wx(tmp_path):
    from racinglines.models.position_sim import dnf_check as DC
    from racinglines.models.position_sim import props as PR
    h, fc = _history(), L.p_wet(L.load(_leads_csv(tmp_path)), 5)
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


@pytest.mark.quick
def test_cli_runs_the_wx_checks_on_csvs(tmp_path, capsys):
    from racinglines.cli import f1
    leads, hist = _leads_csv(tmp_path), tmp_path / "history.csv"
    _history().to_csv(hist, index=False)
    f1.main(["props", "--forecast-skill", "--forecast", str(leads), "--history", str(hist)])
    out = capsys.readouterr().out
    assert "climatology" in out and "analysis" in out and "brier_vs_clim" in out
    f1.main(["props", "--check", "--from", "2024", "--history", str(hist), "--forecast", str(leads), "--lead", "2"])
    assert "circuit-WX - circuit" in capsys.readouterr().out
    dnf = tmp_path / "dnf.csv"
    pd.DataFrame([dict(race_id=20, run_id=1, cutoff="2025-01-01", athlete_id=a, team="t", dnf_prob=0.1 * (a + 1),
                       status="DNF" if a == 2 else "OK") for a in range(4)]).to_csv(dnf, index=False)
    f1.main(["props", "--dnf-check", str(dnf), "--history", str(hist), "--forecast", str(leads)])
    assert "model-WX - model" in capsys.readouterr().out
