"""Calibration power on simulated race outcomes (racinglines/models/calibration.py, C48): the walk-forward fit never
sees a later race (leakage), unset changes nothing, and the resample moves win shares to p^a."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from racinglines.models import calibration as CAL

pytestmark = pytest.mark.quick


def _history(n_races=14, n=10, sharp=2.0, seed=0):
    """Synthetic stored predictions: model win chances flatter than the truth (truth = p^sharp), one grid and one
    nogrid stage per race, one race a week."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_races):
        p = rng.dirichlet(np.ones(n) * 2)
        truth = CAL.win_power(p, sharp)
        winner = rng.choice(n, p=truth)
        for g in ("grid", "nogrid"):
            for i in range(n):
                rows.append(dict(event_key=f"2025-{k + 1:02d}", race_date=pd.Timestamp("2025-03-02") + pd.Timedelta(weeks=k),
                                 group=g, run=f"{k}-{g}", p=p[i], won=int(i == winner)))
    return pd.DataFrame(rows)


def _scramble(df, keys):
    d = df.copy()
    m = d["event_key"].isin(keys)
    d.loc[m, "won"] = d.loc[m].groupby("run")["won"].transform(lambda w: w.shift(1, fill_value=w.iloc[-1]))
    return d


def test_walk_forward_rows_never_see_a_later_race():
    """Scramble every result from race k on: each fit applying before race k is unchanged (the leak test)."""
    df = _history()
    base = CAL.fit_walk_forward(df)
    races = sorted(df["event_key"].unique())
    changed = 0
    for k in range(CAL.MIN_RACES, len(races)):
        refit = CAL.fit_walk_forward(_scramble(df, races[k:]))
        n = k - CAL.MIN_RACES + 1
        assert refit[:n] == base[:n], races[k]
        changed += refit != base
    assert changed, "the scramble never moved a later fit: the test would not catch a leak"


def test_fit_applies_only_after_its_last_race_is_settled():
    df = _history()
    dates = df.drop_duplicates("event_key").set_index("event_key")["race_date"]
    for f in CAL.fit_walk_forward(df):
        last = dates.sort_values().iloc[f["races"] - 1]
        assert f["from"] == (last + pd.Timedelta(days=CAL.SETTLE_DAYS)).date()
        if "next_event" in f:                 # the race this row prices is after the row's start and not in the fit
            assert dates[f["next_event"]].date() >= f["from"]
            assert sorted(dates.index)[: f["races"]] == sorted(dates[dates < dates[f["next_event"]]].index)


def test_fit_recovers_a_sharper_truth():
    f = CAL.fit_walk_forward(_history(n_races=200, sharp=2.0))[-1]
    assert 1.5 <= f["grid"] <= 2.6 and 1.5 <= f["nogrid"] <= 2.6


def test_power_picks_the_latest_fit_on_or_before_the_cutoff(monkeypatch):
    fits = ({"from": date(2025, 5, 1), "grid": 2.0, "nogrid": 1.5}, {"from": date(2025, 6, 1), "grid": 3.0, "nogrid": 1.0})
    monkeypatch.setattr(CAL, "table", lambda sport: fits)
    assert CAL.power("walk_forward", "f1", pd.Timestamp("2025-04-30 23:59"), True) is None      # before any fit
    assert CAL.power("walk_forward", "f1", pd.Timestamp("2025-05-01 00:00"), True) == 2.0
    assert CAL.power("walk_forward", "f1", pd.Timestamp("2025-05-31 23:59"), False) == 1.5
    assert CAL.power("walk_forward", "f1", pd.Timestamp("2025-06-01 12:00"), False) is None     # a = 1 is off
    assert CAL.power(None, "f1", pd.Timestamp("2025-06-01"), True) is None
    assert CAL.power("", "f1", pd.Timestamp("2025-06-01"), True) is None
    assert CAL.power("2.5", "f1", None, True) == 2.5


def test_setting_parses_and_keys_the_table(monkeypatch):
    from racinglines.pipelines import sweep_settings as SS
    assert [CAL.parse(v) for v in ("", "off", "walk-forward", "2", "2.50")] == [None, None, "walk_forward", "2.0", "2.5"]
    for bad in ("abc", "0.5", "11"):
        with pytest.raises(ValueError):
            CAL.parse(bad)
    base = SS.Settings.from_dict()
    assert SS.Settings.from_dict(dict(calib_power="")).model_key == base.model_key            # unset: no key change
    wf = SS.Settings.from_dict(dict(calib_power="walk_forward")).model_key
    assert wf != base.model_key and SS.Settings.from_dict(dict(calib_power="2")).model_key == SS.Settings.from_dict(dict(calib_power="2.0")).model_key
    monkeypatch.setattr(CAL, "table_hash", lambda: "refitted")                       # a refit table prices afresh
    assert SS.Settings.from_dict(dict(calib_power="walk_forward")).model_key != wf


def test_committed_f1_table_is_ordered_and_settled():
    fits = CAL.table("f1")
    assert fits and all(1.0 <= f["grid"] <= 4.0 and 1.0 <= f["nogrid"] <= 4.0 for f in fits)
    assert [f["races"] for f in fits] == sorted(f["races"] for f in fits)
    assert all(a["from"] < b["from"] for a, b in zip(fits, fits[1:]))


def test_resample_moves_win_shares_to_p_power():
    rng = np.random.default_rng(1)
    n_sims, n = 40000, 5
    p = np.array([0.4, 0.25, 0.15, 0.12, 0.08])
    winner = rng.choice(n, size=n_sims, p=p)
    pos = np.tile(np.arange(2, n + 2), (n_sims, 1))
    pos[np.arange(n_sims), winner] = 1
    sim = dict(pos=pos, points=rng.random((n_sims, n)), stages={"sprint": "kept"})
    out = CAL.apply(sim, 2.0, np.random.default_rng(2))
    share = np.bincount(np.argmax(out["pos"] == 1, axis=1), minlength=n) / n_sims
    target = CAL.win_power(np.bincount(winner, minlength=n) / n_sims, 2.0)
    assert np.abs(share - target).max() < 0.01
    assert out["stages"] == {"sprint": "kept"} and out["points"].shape == sim["points"].shape
    assert CAL.apply(sim, None, rng) is sim


def test_unset_leaves_prices_and_key_unchanged(monkeypatch):
    """Through the pricing path: with calib_power unset the summary is byte-identical and the audit has no key;
    with a power, the favourite's win price goes up and every other market is priced from the same resampled draws."""
    from racinglines.models.inputs import laps as M
    from racinglines.models.inputs import laps_pricing as run
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.testing import synthetic as SY
    assert M.CALIB_POWER is None and SS.BY_NAME["calib_power"].default is None
    m = run.Measurements.from_frames(*SY.f1_frames())
    hist = run.history(m)
    eid = int(m.drivers["event_id"].max())
    cutoff = m.sessions(eid)["qual"] + pd.Timedelta(hours=2)
    base, bex = run.price_race(m, hist, cutoff, eid, n_sims=2000, rng=np.random.default_rng(5))
    again, ex = run.price_race(m, hist, cutoff, eid, n_sims=2000, rng=np.random.default_rng(5))
    pd.testing.assert_frame_equal(base, again)
    assert "calib_power" not in bex["audit"]
    monkeypatch.setattr(M, "CALIB_POWER", 2.0)
    cal, cex = run.price_race(m, hist, cutoff, eid, n_sims=2000, rng=np.random.default_rng(5))
    assert cex["audit"]["calib_power"] == 2.0
    fav = base["win_prob"].idxmax()
    assert cal.loc[fav, "win_prob"] > base.loc[fav, "win_prob"]
    assert (cal["podium_prob"] >= cal["win_prob"] - 1e-12).all()      # podium priced from the same resampled races
    assert cal["win_prob"].sum() == pytest.approx(1.0, abs=1e-6)


def test_every_surface_takes_the_setting():
    """CLI flag, MCP job catalogue, Lab sweep form and the Lab job parser (owner rule: every surface)."""
    import argparse
    from racinglines.mcp import tools
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.web import jobs
    from racinglines.web.app import templates
    ap = argparse.ArgumentParser()
    SS.add_arguments(ap)
    assert ap.parse_args(["--calib-power", "walk_forward"]).calib_power == "walk_forward"
    assert "calib_power" in {s["name"] for s in tools.list_job_types()["sweep_settings"]}
    start = SS.Settings.from_dict({"calib_power": "walk_forward"}).to_json()
    html = templates.env.get_template("lab_sweep_form.html").render(
        jt=jobs.CATALOG["f1_sweep"], sel_job="f1_sweep", sweep_defaults=SS.Settings.from_dict().to_json(),
        sweep_start=start, sweep_source="", knobs={}, candidates=[], sel_candidate=0,
        sweep_groups=[(g, lab, [x for x in SS.SETTINGS if x.group == g]) for g, lab in SS.GROUPS],
        model_choices=jobs.MODEL_CHOICES, variant_switches=jobs.variant_switches(),
        exclusive_switches=jobs.EXCLUSIVE_SWITCHES, csrf=lambda: "")
    assert 'name="calib_power" value="walk_forward"' in html and 'type="number"' not in html.split('name="calib_power"')[1][:40]
    assert jobs.parse(jobs.CATALOG["f1_sweep"], {"year": "2026", "calib_power": "walk_forward"})["settings"] == \
        {"calib_power": "walk_forward"}
    _, parsed = tools._job_params("f1_sweep", {"year": "2026", "settings": {"calib_power": "walk_forward"}})
    assert parsed["settings"]["calib_power"] == "walk_forward"
