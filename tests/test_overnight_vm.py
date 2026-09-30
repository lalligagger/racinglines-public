"""The overnight VM run's helpers (scripts/vm/, docs/overnight-vm-run.md): its queue loads, the 16k promotion
keeps only tradeable Polymarket combos and is idempotent, and the replay grid ranks by the worse season."""

import importlib.util
import json
from pathlib import Path

import pytest

from racinglines.pipelines import search as S
from racinglines.pipelines import sweep_settings as SS

pytestmark = pytest.mark.quick

ROOT = Path(__file__).resolve().parents[1]


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "vm" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_queue_loads_polymarket_only_with_golden_first():
    cfg, jobs, _ = S.load(ROOT / "sweeps" / "overnight-vm.toml")
    assert cfg["name"] == "overnight-vm" and cfg["hours"] <= 3.0
    assert len(jobs) == 106
    assert all(j.get("venue", "polymarket") == "polymarket" for j in jobs)
    assert all((SS.Settings.from_dict(j["settings"])["min_volume_24h"] or 0) >= 25 for j in jobs)
    first = [j for j in jobs if "baseline" not in j.get("note", "")][0]
    assert first["note"].startswith("golden")


CANDS = """
[[candidate]]
id = "early-x"
year = 2026
strategy = "early"
variant = "gbm"
min_edge = 0.1
min_volume_24h = 0.0

[[candidate]]
id = "update-k"
year = 2026
strategy = "update"
venue = "kalshi"
variant = "gbm"

[[candidate]]
id = "update-y"
year = 2026
strategy = "update"
variant = "gridq+pretrain"
min_edge = 0.12

[[candidate]]
id = "early-y"
year = 2026
strategy = "early"
variant = "gridq+pretrain"
min_edge = 0.12
"""


def test_promote_keeps_tradeable_distinct_and_is_idempotent(tmp_path):
    P = _mod("promote_16k")
    q = tmp_path / "q.toml"
    q.write_text('[search]\nname = "t"\n\n[[job]]\nyear = 2026\nvariant = "gbm"\n')
    c = tmp_path / "c.toml"
    c.write_text(CANDS)
    for _ in range(2):
        P.main([str(q), "--candidates", str(c), "--top", "5"])
    text = q.read_text()
    assert text.count(P.MARK) == 1
    _, jobs, _ = S.load(q)
    deep = [SS.Settings.from_dict(j["settings"]) for j in jobs if SS.Settings.from_dict(j["settings"])["sims"] == 16000]
    # profile A, the baseline and the one tradeable Polymarket combo, for 2 seasons each
    assert len(deep) == 6
    assert {s["variant"] for s in deep} == {"gridq+pretrain+reset", "baseline", "gridq+pretrain"}
    assert "early-x" not in text and "update-k" not in text


def test_replay_grid_ranks_by_worse_season(tmp_path, capsys):
    G = _mod("replay_grid")
    def put(name, net, up=5, races=10):
        d = tmp_path / name / "kalshi"
        d.mkdir(parents=True)
        (d / "summary.json").write_text(json.dumps(dict(totals=dict(update=dict(net=net, races_up=up, races=races)))))
    put("2026-e0.05-v50", 900); put("2025-e0.05-v50", -100)
    put("2026-e0.10-v200", 300); put("2025-e0.10-v200", 200)
    put("2026-e0.10-v200-s16000", 250); put("2025-e0.10-v200-s16000", 150)
    assert G.rank(tmp_path, top=1) == 0
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1] == "TOP 0.1 200"
    assert (tmp_path / "grid.md").exists()



def test_story_gate_stops_on_a_different_pick_or_no_evidence():
    G = _mod("story_gate")
    ok = [dict(label="Before", chosen="update · baseline", candidates=0),
          dict(label="After r8", chosen=G.EXPECTED, candidates=16),
          dict(label="After r16", chosen=G.EXPECTED, candidates=32),
          dict(label="Before 2026", chosen=G.EXPECTED, candidates=32)]
    assert G.check(ok) == []
    assert G.check(ok[:3] + [dict(ok[3], chosen="early · gbm · min_edge=0.15")])
    assert G.check(ok[:3] + [dict(ok[3], candidates=0)])


def test_progress_counts_jobs_and_eta(tmp_path, monkeypatch):
    P = _mod("progress")
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "data" / "runs" / "search" / "overnight-vm"
    d.mkdir(parents=True)
    state = {f"j{i}": dict(status="done", settings={"variant": "baseline"}) for i in range(10)}
    state["x"] = dict(status="failed", settings={"variant": "baseline"})
    state["deep"] = dict(status="done", settings={"variant": "baseline", "sims": 16000})
    (d / "state.json").write_text(json.dumps(state))
    # no queue file here: the total falls back to what the state holds
    line = P.counts("F1 broad sweep (4k)", start=0, now=600)
    assert line.startswith(" · 10 of 11 jobs done, 1 failed")
    assert P.counts("F1 top 10 at 16k", start=0, now=60) == " · 1 of 1 jobs done"
    assert P.counts("nascar: replay saves", start=0) == ""


def test_progress_reads_the_replay_race_counters_from_the_log(tmp_path):
    P = _mod("progress")
    log = tmp_path / "run.log"
    log.write_text("== 12:59:00Z nascar: links, tape, replay\n"
                   "pull kalshi 1/200 2016-01 Daytona: 40 markets, 10 trades, 20 prices\n"
                   "2026-09-30T13:00Z [all, 5 min in, 0 failed] step 3: nascar Kalshi tape pull\n"
                   "pull kalshi 50/200 2019-10 Dover: 40 markets, 10 trades, 20 prices\n")
    assert P.activity(log, step_start=0, now=600) == " · kalshi tape race 50 of 200, about 30 min left"
    log.write_text(log.read_text() + "Pulled kalshi: 200 races, 2000 trades, 4000 prices\n\n"
                   "progress nascar kalshi: 36 races, 400 markets of kinds win\n"
                   "progress 12 2026-12 Kansas: 12 markets, 10 priced, 3 tradeable\n")
    assert P.activity(log) == " · kalshi replay race 12 of 36"
    log.write_text(log.read_text() + "Wrote data/runs/replay/x\n== 14:00:00Z nascar: replay saves\n")
    assert P.activity(log) == ""


def test_replay_grid_rank_handles_a_season_with_no_races(tmp_path):
    G = _mod("replay_grid")
    for name, totals in (("2026-e0.1-v50", {"update": dict(net=12.0, races_up=2, races=3)}), ("2025-e0.1-v50", {})):
        d = tmp_path / name / "kalshi"
        d.mkdir(parents=True)
        (d / "summary.json").write_text(json.dumps(dict(totals=totals)))
    assert G.rank(tmp_path, top=1) == 0
    assert "no races with markets" in (tmp_path / "grid.md").read_text()
