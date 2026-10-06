"""F1 race props (models/position_sim/props.py): per-circuit rates shrunk to the field, fastest-lap prices from
finishing odds, and their place in the live book (opt-in kinds only), on synthetic data."""

import numpy as np
import pandas as pd
import pytest

from racinglines.models.position_sim import props as P
from racinglines.pipelines import live as LV
from racinglines.pipelines import live_f1 as F


def _hist():
    # 20 races: venue 1 always has a safety car, venue 2 never; the fastest lap mostly goes to the winner
    rows = []
    for i in range(20):
        v = 1 if i % 2 == 0 else 2
        rows.append(dict(race_id=i, event_key=f"2025-{i + 1:02d}", venue_id=v, start=pd.Timestamp("2025-03-01") + pd.Timedelta(days=14 * i),
                         sc=v == 1, red=i % 5 == 0, rain=i % 4 == 0, wet=i % 4 == 0,
                         rain_share=0.3 if i % 4 == 0 else 0.0,
                         fl_athlete=100, fl_bucket="p1" if i < 12 else "p4_10", n_ok=18, n_dnf=2))
    return pd.DataFrame(rows)


@pytest.mark.quick
def test_circuit_rates_shrink_to_the_field():
    h = _hist()
    field = h["sc"].mean()
    assert P.rate(h, 1, "sc", prior_n=16) == pytest.approx((10 + 16 * field) / 26)
    assert P.rate(h, 2, "sc", prior_n=16) == pytest.approx((0 + 16 * field) / 26)
    assert P.rate(h, 99, "sc") == pytest.approx(field)                    # a new venue: the field rate
    assert P.rate(h, 1, "sc", prior_n=1e9) == pytest.approx(field)
    assert P.rate(h.iloc[:0], 1, "sc") is None


@pytest.mark.quick
def test_wet_or_dry_rates_shrink_twice():
    h = _hist()                    # 5 wet races (i % 4 == 0), all at venue 1; red flags at i % 5 == 0
    field = h["red"].mean()
    wet, dry = h[h["wet"]], h[~h["wet"]]
    fw = (wet["red"].sum() + 16 * field) / (len(wet) + 16)            # the field's wet rate, shrunk to the field
    fd = (dry["red"].sum() + 16 * field) / (len(dry) + 16)
    v1w = wet[wet["venue_id"] == 1]["red"]
    assert P.rate_given(h, 1, "red", True, 16) == pytest.approx((v1w.sum() + 16 * fw) / (len(v1w) + 16))
    assert P.rate_given(h, 2, "red", True, 16) == pytest.approx(fw)   # venue 2 has no wet race: the field's wet rate
    v2d = dry[dry["venue_id"] == 2]["red"]
    assert P.rate_given(h, 2, "red", False, 16) == pytest.approx((v2d.sum() + 16 * fd) / (len(v2d) + 16))
    assert P.rate_given(h.iloc[:0], 1, "red", True) is None and P.rate_wx(h.iloc[:0], 1, "red", 0.5) is None
    # rate_wx mixes the two; p_wet 0 / 1 are the conditional rates
    w, d = P.rate_given(h, 1, "red", True), P.rate_given(h, 1, "red", False)
    assert P.rate_wx(h, 1, "red", 1.0) == pytest.approx(w) and P.rate_wx(h, 1, "red", 0.0) == pytest.approx(d)
    assert P.rate_wx(h, 1, "red", 0.25) == pytest.approx(0.25 * w + 0.75 * d)
    # no forecast: the circuit's own shrunk wet share (climatology)
    clim = P.rate(h, 1, "wet")
    assert P.rate_wx(h, 1, "red") == pytest.approx(clim * w + (1 - clim) * d)


@pytest.mark.quick
def test_p_wet_reprices_only_the_red_flag():
    h = _hist()
    base = {m["kind"]: m["fair"] for m in P.market_set(pd.DataFrame(), 1, h, kinds=tuple(P.BINARY))}
    assert base == {k: P.rate(h, 1, c) for k, c in P.BINARY.items()}                    # default: rate()
    wx = {m["kind"]: m["fair"] for m in P.market_set(pd.DataFrame(), 1, h, kinds=tuple(P.BINARY), p_wet=0.9)}
    assert wx["race_red_flag"] == pytest.approx(P.rate_wx(h, 1, "red", 0.9))
    assert wx["race_safety_car"] == base["race_safety_car"]                              # worse when conditioned
    assert wx["race_rain"] == base["race_rain"]
    assert P.WX_KINDS == ("race_red_flag",) and set(P.WX_KINDS) <= set(P.WX_CHECKED)


@pytest.mark.quick
def test_check_runs_on_a_history_frame_with_the_wet_methods():
    h = _hist().drop(columns=["rain", "wet", "fl_athlete", "fl_bucket", "n_ok", "n_dnf"])
    h["start"] = h["start"].dt.strftime("%Y-%m-%d")              # as read from a CSV
    per, summ = P.check(history_df=h, start_year=2025, prior_n=16)
    assert len(per) == 3 * 10                                     # the first 10 races are history only
    got = {(r.kind, r.method) for r in summ.itertuples()}
    for kind in ("race_safety_car", "race_red_flag"):
        assert {(kind, m) for m in P.METHODS} <= got
    assert ("race_rain", "climatology") not in got and ("race_rain", "wet_oracle") not in got
    oracle = per[per["kind"] == "race_red_flag"]
    r = oracle.iloc[0]
    past = P.prepare(h).iloc[:10]
    assert r["wet_oracle"] == pytest.approx(P.rate_wx(past, 1, "red", float(r["wet"])))
    assert r["climatology"] == pytest.approx(P.rate_wx(past, 1, "red"))
    assert set(summ.columns) == {"kind", "method", "races", "yes_rate", "mean_price", "brier", "log_loss", "se"}


@pytest.mark.quick
def test_dnf_check_scores_the_model_against_flat_rates():
    from racinglines.models.position_sim import dnf_check as DC
    rows = []
    for race in (1, 2):
        for run, cutoff in ((10 * race, "2026-01-01"), (10 * race + 1, "2026-01-02")):    # the later run is scored
            for a, (p, st) in enumerate([(0.02, "OK"), (0.08, "OK"), (0.12, "DNF"), (0.30, "DSQ"), (0.05, "DNS"),
                                         (0.04, None), (0.18, "OK")]):
                rows.append(dict(race_id=race, run_id=run, cutoff=cutoff, athlete_id=a, team=f"t{a // 2}",
                                 dnf_prob=p if run % 10 else 0.5, status=st))
    out = DC.check(pd.DataFrame(rows))
    t = out["totals"]
    assert t["rows"] == 10 and t["races"] == 2 and t["other"] == {"DNS": 2}
    assert t["realised"] == pytest.approx(0.4) and t["mean_p"] == pytest.approx(0.14)
    s = out["summary"].set_index("method")
    assert list(s.index) == ["model", "field", "race_mean"]
    y = np.array([0, 0, 1, 1, 0] * 2, float)
    p = np.array([0.02, 0.08, 0.12, 0.30, 0.18] * 2)
    assert s.loc["model", "brier"] == pytest.approx(((p - y) ** 2).mean())
    assert s.loc["field", "brier"] == pytest.approx(((0.4 - y) ** 2).mean())
    cal = out["calibration"].set_index("bucket")
    assert list(cal.index) == list(DC.BUCKET_LABELS)
    assert cal.loc["0-5%", "n"] == 2 and cal.loc["10-15%", "realised"] == 1.0 and cal.loc["20%+", "n"] == 2
    assert "not scored: DNS 2" in DC.render(out)


@pytest.mark.quick
def test_fastest_lap_prices_sum_to_one_and_follow_the_winner():
    h = _hist()
    r = P.fl_rates(h)
    assert r["p1"] > r["p2_3"] and r["p4_10"] > r["p11"]
    preds = pd.DataFrame(dict(athlete_id=[1, 2, 3, 4], driver=list("ABCD"), win_prob=[0.6, 0.3, 0.1, 0.0],
                              podium_prob=[0.9, 0.8, 0.6, 0.1], top10_prob=[1.0, 1.0, 0.9, 0.5],
                              dnf_prob=[0.0, 0.0, 0.05, 0.2]))
    p = P.fl_probs(preds, r)
    assert p.sum() == pytest.approx(1) and list(np.argsort(-p)) == [0, 1, 2, 3]
    m = P.market_set(preds, 1, h)
    assert [x["kind"] for x in m][:3] == ["race_safety_car", "race_red_flag", "race_rain"]
    fl = [x for x in m if x["kind"] == "race_fastest_lap"]
    assert len(fl) == 4 and sum(x["fair"] for x in fl) == pytest.approx(1) and fl[0]["key"] == "race_fastest_lap:1"
    assert P.market_set(preds, 1, h, kinds=("race_rain",)) == [dict(key="race_rain", kind="race_rain", athlete_id=None,
                                                                    params=None, subject="Rain", fair=P.rate(h, 1, "rain"))]


@pytest.mark.quick
def test_props_are_opt_in():
    live = LV.settings("f1")
    assert set(live["markets"]["kinds"]) == set(F.KINDS) and not set(F.PROP_KINDS) & set(F.KINDS)
    assert F.prop_markets(None, "2026-16", None, F.KINDS) == []           # nothing read, nothing listed


@pytest.mark.quick
def test_the_live_tab_groups_the_props():
    mk = [dict(key="race_safety_car", kind="race_safety_car", subject="Safety car", fair=0.6, prev_fair=None),
          dict(key="race_rain", kind="race_rain", subject="Rain", fair=0.2, prev_fair=None),
          dict(key="race_fastest_lap:1", kind="race_fastest_lap", subject="A", fair=0.7, prev_fair=0.6),
          dict(key="race_fastest_lap:2", kind="race_fastest_lap", subject="B", fair=0.3, prev_fair=None)]
    snap = dict(markets=mk, outcomes=[], ts="2026-10-02T03:30:00+00:00")
    import racinglines.pipelines.live as live_core
    orig = live_core.book_at
    live_core.book_at = lambda run, ts: ({}, [])
    try:
        v = F.view("x", snap, [], [], "live", maker=False)
    finally:
        live_core.book_at = orig
    g = {x["kind"]: x for x in v["groups"]}
    assert list(g) == ["race_props", "race_fastest_lap"]
    assert [m["subject"] for m in g["race_props"]["markets"]] == ["Safety car", "Rain"] and g["race_props"]["target"] is None
    assert g["race_fastest_lap"]["target"] == 1.0 and g["race_fastest_lap"]["total"] == pytest.approx(1)


@pytest.mark.quick
def test_race_outcomes_add_the_props(monkeypatch):
    from racinglines.markets import private_book as PB
    res = pd.DataFrame(dict(athlete_id=list(range(1, 7)), position=list(range(1, 7)), status=["OK"] * 6,
                            team_id=["t"] * 6, points=[0.0] * 6, qual_position=list(range(1, 7))))
    monkeypatch.setattr(PB, "race_outcomes", lambda conn, rid: res)
    seen = []
    monkeypatch.setattr(P, "outcomes", lambda conn, rid, mkts: seen.append([m["key"] for m in mkts]) or {"race_rain": True})
    mk = [dict(key="race_win:1", kind="race_win", athlete_id=1, params=None),
          dict(key="race_rain", kind="race_rain", athlete_id=None, params=None)]
    assert F.outcomes(None, 7, mk) == {"race_win:1": True, "race_rain": True} and seen == [["race_rain"]]
    seen.clear()
    assert F.outcomes(None, 7, mk[:1]) == {"race_win:1": True} and seen == []   # no props listed: not read
