"""Road cycling book model (racinglines/models/cycling.py) and the PCS row builder, on synthetic data."""

import numpy as np
import pandas as pd
import pytest

from racinglines.models import cycling as C
from racinglines.sources import pcs

pytestmark = pytest.mark.quick


def _results(kind, n_races=60, field=60, seed=1):
    rng = np.random.default_rng(seed)
    names = ["POGACAR Tadej", "EVENEPOEL Remco", "PIDCOCK Thomas"] + [f"RIDER Number{i}" for i in range(120)]
    skill = rng.normal(0, 1, len(names))
    skill[:3] += [3.0, 2.0, 1.0]
    rows = []
    for i, d in enumerate(pd.date_range("2022-01-10", periods=n_races, freq="14D")):
        k = np.r_[0, 1, 2, rng.choice(np.arange(3, len(names)), field - 3, replace=False)]
        perf = skill[k] + rng.normal(0, 0.5, field)
        for p, j in enumerate(np.argsort(-perf)):
            dnf = rng.random() < 0.05
            rows.append(dict(race=f"race{i}", kind="gc" if kind == "road" and i % 6 == 0 else "oneday",
                             date=d.date().isoformat(), race_class="1.UWT" if i % 2 else "1.Pro",
                             distance_km=30.0 if kind == "itt" else 200.0, vert_m=300 if i % 2 else 50,
                             profile_score=100, profile_icon="p3" if i % 2 else "p1", rider=names[k[j]],
                             rider_url=f"rider/{k[j]}", position=None if dnf else p + 1,
                             gap_s=None if dnf else 4.0 * p, winner_time_s=2400.0,
                             status="DNF" if dnf else "OK", source_url=""))
    return pd.DataFrame(rows)


def _event(kind):
    return {"id": "test", "event": {"kind": kind, "name": "t", "date": "2026-01-01", "terrain": "hilly",
                                    "distance_km": 30.0, "vert_m": 300},
            "settings": dict(C.model_block(kind)["defaults"]),
            "book": {"futures": {"Pogacar": 2.0, "Pidcock": 10.0},
                     "matchups": [{"a": "Evenepoel", "a_odds": 2.5, "b": "Pidcock", "b_odds": 1.5}]},
            "names": {"Pogacar": "tadej pogacar", "Evenepoel": "remco evenepoel", "Pidcock": "pidcock"}}


def test_schema_blocks_and_event_files_load():
    for kind in ("itt", "road"):
        b = C.model_block(kind)
        assert set(b["grid"]) <= set(b["defaults"])
        assert {"min_field", "categories"} <= set(b["backtest"])
    for e in C.list_events():
        ev = C.load_event(e)
        missing = set(C.labels(ev)) - set(ev["names"])
        assert not missing, f"{e}: no [names] entry for {missing}"


@pytest.mark.parametrize("kind", ["itt", "road"])
def test_price_ranks_the_strongest_rider_first(kind):
    res = _results(kind)
    raw = C.to_raw(res, kind, C.model_block(kind)["rules"])
    ev = _event(kind)
    start = res.drop_duplicates("rider_url").head(40)[["rider", "rider_url"]]
    ids, bad = C.book_ids(ev, start, res)
    assert not bad
    fut, mu, _ = C.price(ev, raw, start, ids, ev["settings"], sims=4000)
    p = fut.set_index("rider")["win_p"]
    assert p["Pogacar"] > p["Pidcock"]
    assert mu.iloc[0]["a_p"] > 0.5                       # Evenepoel beats Pidcock more often than not
    b = C.stakes(fut, mu, bankroll=400, kelly=0.25)
    assert (b["edge"] > 0).all() and (b["stake"] >= 0).all()


def test_road_pseudo_times_follow_finishing_order():
    raw = C.to_raw(_results("road", n_races=3), "road", C.model_block("road")["rules"])
    ok = raw[raw["status"] == "OK"].sort_values(["event_id", "rank_at_split"])
    for _, g in ok.groupby("event_id"):
        assert g["cum_time_s"].is_monotonic_increasing
    assert set(raw["category"]) <= {"ME", "MF", "WH", "WF", "GC"}


def test_backtest_scores_months_walk_forward():
    res = _results("road", n_races=50, field=70)
    raw = C.to_raw(res, "road", C.model_block("road")["rules"])
    s = dict(C.model_block("road")["defaults"])
    bt = C.backtest(raw, "road", [s, {**s, "noise_scale": 1.5}], since="2022-06-01", n_sims=300)
    assert len(bt) and set(bt["noise_scale"]) == {1.0, 1.5}
    summ = C.summarize(bt, list(s))
    assert len(summ) == 2 and summ["win_ll"].notna().all()


def test_book_names_need_one_match():
    res = _results("road", n_races=2)
    ev = _event("road")
    ev["names"]["Pidcock"] = "rider"                    # matches every "RIDER NumberN"
    ids, bad = C.book_ids(ev, res.head(0)[["rider", "rider_url"]], res)
    assert "Pidcock" not in ids and any(b.startswith("Pidcock") for b in bad)


def test_pcs_rows_read_times_and_gaps():
    table = [dict(rider_name="A", rider_url="rider/a", rank=1, status="DF", time="0:27:12"),
             dict(rider_name="B", rider_url="rider/b", rank=2, status="DF", time="0:00:15"),
             dict(rider_name="C", rider_url="rider/c", rank=3, status="DF", time="0:27:40"),
             dict(rider_name="D", rider_url="rider/d", rank=None, status="DNF", time="")]
    rows = pcs.stage_rows(table, dict(date="2025-09-21"), "r", "oneday", "u")
    assert [r["gap_s"] for r in rows[:3]] == [0, 15, 28]
    assert rows[0]["winner_time_s"] == 1632
    assert [r["status"] for r in rows] == ["OK", "OK", "OK", "DNF"] and rows[3]["position"] is None
