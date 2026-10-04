"""In-race win chart: live timing -> win probabilities (models/position_sim/inrace.py, pipelines/live_f1.inrace_points)."""

import json

from racinglines.models.position_sim import inrace as IR

PRIOR = {"A": 0.5, "B": 0.3, "C": 0.15, "D": 0.05}


def rows(order, laps, status=None):
    return [dict(name=n, pos=i + 1, laps=laps, status=(status or {}).get(n, "")) for i, n in enumerate(order)]


def test_start_follows_the_prior_and_the_flag_follows_the_leader():
    early, _ = IR.win_probs(rows("DCBA", 1), PRIOR, 56)
    assert early["A"] > early["D"]                      # one lap in: still mostly the pre-race order
    late, laps = IR.win_probs(rows("DCBA", 56), PRIOR, 56)
    assert laps == 56 and late["D"] == 1.0              # at the flag the leader has won
    assert abs(sum(early.values()) - 1) < 1e-9


def test_retired_drivers_get_zero_and_unusable_orders_give_none():
    p, _ = IR.win_probs(rows("ABCD", 30, {"A": "Retired"}), PRIOR, 56)
    assert p["A"] == 0.0 and abs(sum(p.values()) - 1) < 1e-9
    assert IR.win_probs(rows("AB", 10), PRIOR, 56)[0] is None
    assert IR.win_probs(rows("ABCD", 0), PRIOR, 56)[0] is None


def test_inrace_points_store_one_point_per_relay_write(tmp_path, monkeypatch):
    from racinglines.pipelines import live_f1 as F
    from racinglines.web import f1_live as FL
    relay = tmp_path / "2026-16.json"
    monkeypatch.setattr(FL, "relay_file", lambda y, r: relay)
    snap = dict(event_key="2026-16", markets=[dict(kind="race_win", subject=n, key=f"race_win:{i}", fair=p)
                                              for i, (n, p) in enumerate(PRIOR.items())])
    assert F.inrace_points("2026-16", snap) == []      # no relay file yet
    relay.write_text(json.dumps(dict(session="Race", drivers=rows("BACD", 10), laps=40)))
    pts = F.inrace_points("2026-16", snap)
    assert len(pts) == 1 and set(pts[0]["fair"]) == {f"race_win:{i}" for i in range(4)}
    assert len(F.inrace_points("2026-16", snap)) == 1   # the same relay write isn't stored twice
    relay.write_text(json.dumps(dict(session="Qualifying", drivers=rows("BACD", 10), laps=40)))
    assert len(F.inrace_points("2026-16", snap)) == 1   # only the race feeds the chart


def _race(tmp_path):
    """A 3-lap race of four drivers: B leads lap 1, A takes over, D retires after lap 1."""
    import pandas as pd
    laps = pd.DataFrame([
        dict(Driver=d, LapNumber=lap, Position=pos, LapStartTime=100.0 + 90 * (lap - 1) + off, Time=190.0 + 90 * (lap - 1) + off)
        for lap, order in ((1, "BACD"), (2, "ABC"), (3, "ABC")) for pos, d in enumerate(order, 1)
        for off in [0.5 * pos]])
    results = pd.DataFrame(dict(Abbreviation=list("ABCD"), FullName=list("ABCD"),
                                Status=["Finished", "Finished", "+1 Lap", "Retired"]))
    return laps, results


def test_the_running_order_comes_from_the_laps_with_a_wall_clock(tmp_path):
    import pandas as pd
    from racinglines.pipelines import live_f1 as F
    laps, results = _race(tmp_path)
    order = F.race_running_order(laps, results, pd.Timestamp("2026-10-04T07:00:00Z"))
    assert [len(rows) for _, rows in order] == [4, 4, 4]
    t1, rows1 = order[0]
    assert t1 == pd.Timestamp("2026-10-04T07:01:30.000Z")             # lap 1 ends 90.5 s - 0.5 s after it began
    assert [r["name"] for r in sorted(rows1, key=lambda r: r["pos"])] == list("BACD")
    _, rows3 = order[-1]
    assert next(r for r in rows3 if r["name"] == "D")["status"] == "Retired"
    assert IR.win_probs(rows3, PRIOR, 3)[0]["A"] == 1.0


def test_backfill_writes_one_point_per_lap_and_replay_shows_them_up_to_the_snapshot(tmp_path, monkeypatch):
    import pandas as pd
    from racinglines.pipelines import live as LV
    from racinglines.pipelines import live_f1 as F
    from racinglines.sources.fastf1 import fetch
    from racinglines.web import f1_live as FL
    laps, results = _race(tmp_path)
    raw = tmp_path / "raw" / "2026"
    raw.mkdir(parents=True)
    laps.to_parquet(raw / "16_R.laps.parquet")
    results.to_parquet(raw / "16_R.results.parquet")
    (raw / "16_R.meta.json").write_text(json.dumps(dict(session_date="2026-10-04 07:00:00", total_laps=3)))
    monkeypatch.setattr(fetch, "OUT", tmp_path / "raw")
    monkeypatch.setattr(FL, "relay_file", lambda y, r: tmp_path / f"{y}-{r:02d}.json")
    markets = [dict(kind="race_win", subject=n, key=f"race_win:{n}", fair=0.0) for n in PRIOR]
    snap = dict(event_key="2026-16", ts="2026-10-04T10:00:00+00:00", markets=markets)
    hist = [dict(ts="2026-10-04T06:30:00+00:00", fair={f"race_win:{n}": p for n, p in PRIOR.items()})]
    monkeypatch.setattr(LV, "find", lambda key: dict(run="2026-16", event_key=key))
    monkeypatch.setattr(LV, "load", lambda run: (snap, [], hist))
    assert F.backfill_inrace(2026, 16, echo=lambda m: None) == 3
    assert F.backfill_inrace(2026, 16, echo=lambda m: None) == 3          # rewrites, never appends twice
    assert len(F.inrace_points("2026-16", snap, replay=True)) == 3
    early = dict(snap, ts="2026-10-04T07:02:00+00:00")
    pts = F.inrace_points("2026-16", early, replay=True)
    assert len(pts) == 1 and pd.Timestamp(pts[0]["ts"]) <= pd.Timestamp(early["ts"])
