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
