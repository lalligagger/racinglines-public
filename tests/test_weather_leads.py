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
