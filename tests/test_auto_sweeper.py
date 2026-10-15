"""Pure replay tests. No database, real child, Jev call, or system temporary folder."""

import json
import importlib.util
import shutil
import signal
import subprocess
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from racinglines.pipelines.sweep_settings import Settings
from racinglines.research import auto_sweeper as A


@pytest.fixture
def workspace(monkeypatch):
    root = Path.cwd() / (".auto-sweeper-test-" + uuid.uuid4().hex)
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr(A.paths, "ROOT", root)
    try:
        yield root
    finally:
        monkeypatch.chdir(root.parent)
        shutil.rmtree(root)


@pytest.fixture
def rig(workspace):
    backup = workspace / "backup.sql"
    backup.write_text("synthetic stand-in; no database was accessed")
    store = {}
    launches = []
    calls = []
    next_id = 0

    def add(job, pnl=None):
        nonlocal next_id
        next_id += 1
        st = Settings.from_dict(job["settings"])
        gain = 600 if st["min_edge"] != Settings.from_dict()["min_edge"] else 0
        values = pnl if pnl is not None else [100 + gain, 100 + gain, 100 + gain]
        row = dict(year=job["year"], settings=st.to_json(), run_id=next_id,
                   metrics={"weekends": [dict(round=i + 1, event=f"event-{i}", update_pnl=v)
                                         for i, v in enumerate(values)]})
        store[job["id"]] = row
        return row

    def execute(job, log, echo):
        launches.append(job["id"])
        add(job)

    def choose(evidence, options, model):
        calls.append(dict(evidence=evidence, options=options, model=model))
        return {"choice": options[0], "probabilities": {options[0]: 1.0}, "confidence": 1.0}

    def run(cfg=None, **kwargs):
        return A.run(cfg or A.Config([{"min_edge": .11}]), workspace / "state.json",
                     execute=True, backup=backup, loader=lambda: list(store.values()),
                     executor=SimpleNamespace(run=execute), chooser=choose, echo=lambda *a: None, **kwargs)

    return SimpleNamespace(root=workspace, backup=backup, store=store, launches=launches, calls=calls,
                           add=add, execute=execute, choose=choose, run=run)


def read(rig):
    return json.loads((rig.root / "state.json").read_text())


def test_dry_run_is_pure_even_with_opt_in_parameters(workspace):
    spy = Mock(side_effect=AssertionError("dry-run performed a side effect"))
    state = A.run(A.Config([{"min_edge": .11}]), workspace / "missing" / "state.json",
                  budget=20, jev_budget=20, loader=spy, chooser=spy, executor=spy)
    assert state["dry_run"] and state["sweep_budget"] == state["jev_budget"] == 0
    assert list(workspace.iterdir()) == []
    spy.assert_not_called()


def test_deterministic_plan_order_and_exact_seed_identity():
    a, b = {"min_edge": .11, "seed": 1}, {"min_edge": .12, "seed": 2}
    assert A.plan(A.Config([a, b])) == A.plan(A.Config([b, a]))
    jobs = A.plan(A.Config([a, b]))["jobs"]
    assert len(jobs) == 16
    assert {j["id"] for j in jobs} == {A.job_id(j["year"], j["settings"]) for j in jobs}
    assert A.job_id(2026, a) != A.job_id(2026, dict(a, seed=2))
    assert A.job_id(2026, a) != A.job_id(2026, dict(a, sims=16000))


@pytest.mark.parametrize("pool,kwargs", [
    ([], {}), ([{}] * 255, {}), ([{}, {}], {}), ([{}, {"sims": 5000}], {}),
    ([{"venue": "kalshi"}], {}), ([{}], {"confirm_sims": 4000}),
    ([{}], {"margin": float("nan")}), ([{}], {"stop_after": -1}),
    ([{}], {"strategy": "not-a-strategy"}), ([{}], {"target": 2024}),
    (["private user data"], {}),
])
def test_invalid_bounded_config(pool, kwargs):
    with pytest.raises(ValueError):
        A.plan(A.Config(pool, **kwargs))


def test_finite_choice_cap_and_no_truncation():
    pool = [{"min_edge": .005 + .001 * i} for i in range(254)]
    assert A.plan(A.Config(pool))["candidates"] == 254
    with pytest.raises(ValueError, match="254"):
        A.plan(A.Config(pool + [{"min_edge": .3}]))


def test_defaults_zero_budgets_never_choose_or_launch(rig):
    state = rig.run()
    assert state["attempts"] == state["choices"] == []
    assert rig.launches == rig.calls == []


def test_separate_zero_jev_budget(rig):
    state = rig.run(budget=20)
    assert not state["choices"] and not rig.launches


def test_execution_requires_nonempty_existing_backup(workspace):
    spy = Mock()
    with pytest.raises(ValueError, match="backup"):
        A.run(A.Config([{}]), workspace / "state.json", execute=True, loader=spy)
    assert list(workspace.iterdir()) == []
    spy.assert_not_called()


def test_full_replay_counts_years_baselines_confirmations_and_writes_reports(rig):
    state = rig.run(budget=8, jev_budget=1)
    assert len(state["attempts"]) == len(rig.launches) == 8
    assert len(state["choices"]) == len(rig.calls) == 1
    assert len(state["evaluations"]) == 1 and state["stopped"] == "pool exhausted"
    assert all(a["status"] == "done" for a in state["attempts"])
    score = next(iter(state["evaluations"].values()))
    assert score["score"] == 1800
    assert score["verdict"] == "robust" and score["confirmed"] == "yes"
    assert score["shape"] == "steady"
    for name in ("leaderboard.csv", "leaderboard.md", "search-report/report.md",
                 "search-report/stats.csv", "search-report/ranking.csv"):
        assert (rig.root / name).is_file()


def test_pre_stored_exact_keys_not_repeated(rig):
    cfg = A.Config([{"min_edge": .11}])
    required = A.requirements(cfg.pool[0], cfg.document())
    for job in required[:5]:
        rig.add(job)
    state = rig.run(cfg, budget=3, jev_budget=1)
    assert len(state["evaluations"]) == 1
    assert rig.launches == [j["id"] for j in required[5:]]
    assert len(state["attempts"]) == 3


def test_all_results_pre_stored_need_no_jev_or_budget(rig):
    cfg = A.Config([{"min_edge": .11}])
    for job in A.requirements(cfg.pool[0], cfg.document()):
        rig.add(job)
    state = rig.run(cfg)
    assert len(state["evaluations"]) == 1
    assert not rig.launches and not rig.calls


def test_resume_partial_pair_has_no_new_selection_and_budget_is_cumulative(rig):
    first = rig.run(budget=3, jev_budget=1)
    assert first["active"] and not first["evaluations"] and first["misses"] == 0
    assert len(rig.calls) == 1 and len(rig.launches) == 3
    again = rig.run()
    assert again["attempts"] == first["attempts"]
    with pytest.raises(ValueError, match="increase_budget"):
        rig.run(budget=8)
    state = rig.run(budget=8, increase_budget=True)
    assert len(rig.launches) == len(set(rig.launches)) == 8
    assert len(rig.calls) == 1 and len(state["attempts"]) == 8
    assert len(state["evaluations"]) == 1
    with pytest.raises(ValueError):
        rig.run(budget=7, increase_budget=True)


def test_commit_before_checkpoint_recovers_without_retry_or_selection(rig):
    cfg = A.Config([{"min_edge": .11}])
    first = rig.run(cfg, budget=1, jev_budget=1)
    doc = read(rig)
    doc["attempts"][0].pop("run_id")
    doc["attempts"][0]["status"] = "launched"
    (rig.root / "state.json").write_text(json.dumps(doc))
    second = rig.run(cfg, budget=8, increase_budget=True)
    assert len(second["attempts"]) == 8
    assert len(rig.calls) == 1
    assert len(rig.launches) == len(set(rig.launches)) == 8
    assert second["attempts"][0]["run_id"] == first["attempts"][0]["run_id"]


def test_failed_attempt_stops_checkpoints_and_explicit_retry_costs_another(rig, monkeypatch):
    original = rig.execute
    failing = Mock(side_effect=RuntimeError("synthetic child failure"))
    monkeypatch.setattr(A, "LocalExecutor", lambda: SimpleNamespace(run=failing))
    with pytest.raises(RuntimeError, match="synthetic"):
        A.run(A.Config([{"min_edge": .11}]), rig.root / "state.json", execute=True,
              backup=rig.backup, budget=9, jev_budget=1, loader=lambda: list(rig.store.values()),
              chooser=rig.choose, echo=lambda *a: None)
    failed = read(rig)
    assert failed["attempts"][0]["status"] == "failed"
    assert failed["failure"] and failed["active"]
    with pytest.raises(RuntimeError, match="retry_failed"):
        rig.run()
    state = rig.run(retry_failed=True)
    assert len(state["attempts"]) == 9 and len(rig.launches) == 8
    assert len(rig.calls) == 1 and len(state["evaluations"]) == 1
    assert original


def test_crashed_launched_attempt_conservatively_counts_budget(rig):
    cfg = A.Config([{"min_edge": .11}])
    rig.run(cfg, budget=1, jev_budget=1)
    doc = read(rig)
    job = doc["attempts"][0]
    del rig.store[job["id"]]
    doc["pins"].pop(job["id"])
    job.pop("run_id")
    job["status"] = "launched"
    (rig.root / "state.json").write_text(json.dumps(doc))
    with pytest.raises(RuntimeError, match="retry_failed"):
        rig.run(cfg)
    state = rig.run(cfg, retry_failed=True)
    assert len(state["attempts"]) == 1 and state["active"]
    assert len(rig.launches) == 1  # Exhausted attempt was not refunded.


def test_interruption_checkpoint_and_resume(rig, monkeypatch):
    fake = Mock(side_effect=KeyboardInterrupt("synthetic SIGTERM"))
    monkeypatch.setattr(A, "LocalExecutor", lambda: SimpleNamespace(run=fake))
    with pytest.raises(KeyboardInterrupt):
        A.run(A.Config([{"min_edge": .11}]), rig.root / "state.json", execute=True,
              backup=rig.backup, budget=9, jev_budget=1, loader=lambda: [], chooser=rig.choose,
              echo=lambda *a: None)
    doc = read(rig)
    assert doc["attempts"][0]["status"] == "interrupted"
    assert doc["active"] and doc["failure"].startswith("KeyboardInterrupt")
    assert rig.run(retry_failed=True)["stopped"] == "pool exhausted"
    assert len(rig.calls) == 1


@pytest.mark.parametrize("timeout", [False, True])
def test_executor_terminates_only_owned_child_and_reaps(workspace, monkeypatch, timeout):
    child = Mock()
    child.poll.return_value = None
    waits = [KeyboardInterrupt(), subprocess.TimeoutExpired("owned-child", 10), 0] if timeout else [KeyboardInterrupt(), 0]
    child.wait.side_effect = waits
    popen = Mock(return_value=child)
    monkeypatch.setattr(A.subprocess, "Popen", popen)
    monkeypatch.setattr(A, "local_database", lambda: "postgresql://localhost/synthetic")
    old = signal.getsignal(signal.SIGTERM)
    with pytest.raises(KeyboardInterrupt):
        A.LocalExecutor().run(dict(id="test", year=2026, settings={}), workspace / "child.log", lambda *a: None)
    child.terminate.assert_called_once_with()
    assert child.wait.call_count == (3 if timeout else 2)
    assert child.kill.call_count == int(timeout)
    assert signal.getsignal(signal.SIGTERM) == old
    argv = popen.call_args.args[0]
    assert "--no-fetch" in argv and "--save" in argv and "f1" in argv


def test_sweep_argv_reuses_settings_and_never_has_trading_flags():
    st = Settings.from_dict({"min_edge": .11, "seed": 4, "sims": 8000, "variant": "gridq"})
    argv = A.sweep_argv(dict(year=2025, settings=st.to_json()))
    assert argv[-len(st.argv()):] == st.argv()
    assert argv[argv.index("--variant") + 1] == "gridq"
    assert not any("trading" in a or "profile" in a or "remote" in a for a in argv)


def test_stop_rule_only_fires_after_complete_scored_evaluations(rig):
    cfg = A.Config([{"min_edge": .11}, {"min_edge": .12}], stop_after=1, margin=1.0)
    state = rig.run(cfg, budget=2, jev_budget=2)
    assert not state["evaluations"] and state["misses"] == 0 and state["stopped"] is None
    state = rig.run(cfg, budget=10, increase_budget=True)
    assert len(state["evaluations"]) == 1 and state["misses"] == 0
    state = rig.run(cfg, budget=16, increase_budget=True)
    assert len(state["evaluations"]) == 2 and state["misses"] == 1
    assert state["stopped"] == "no improvement"


def test_jev_stop_is_cached_before_any_execution(rig):
    chooser = Mock(return_value={"choice": A.STOP})
    state = A.run(A.Config([{}]), rig.root / "state.json", execute=True, backup=rig.backup,
                  budget=20, jev_budget=1, loader=lambda: [], chooser=chooser,
                  executor=Mock(side_effect=AssertionError("should not execute")), echo=lambda *a: None)
    assert state["stopped"] == "Jev STOP" and not state["attempts"]
    assert read(rig)["choices"][0]["answer"]["choice"] == A.STOP
    assert state["choices"][0]["options"][-1] == A.STOP


def test_invalid_jev_choice_is_explicit_failure_and_spends_call(rig):
    with pytest.raises(ValueError, match="out-of-pool"):
        A.run(A.Config([{}]), rig.root / "state.json", execute=True, backup=rig.backup,
              budget=20, jev_budget=1, loader=lambda: [], chooser=lambda *a: {"choice": "made-up"},
              executor=SimpleNamespace(run=rig.execute),
              echo=lambda *a: None)
    doc = read(rig)
    assert len(doc["choices"]) == 1 and doc["choices"][0]["status"] == "failed"
    assert not doc["attempts"]
    with pytest.raises(RuntimeError, match="retry_failed"):
        rig.run(A.Config([{}]))


def test_jev_error_no_silent_fallback_or_new_call_without_retry(rig):
    with pytest.raises(RuntimeError, match="synthetic API error"):
        A.run(A.Config([{}]), rig.root / "state.json", execute=True, backup=rig.backup,
              budget=20, jev_budget=1, loader=lambda: [],
              executor=SimpleNamespace(run=rig.execute),
              chooser=Mock(side_effect=RuntimeError("synthetic API error")), echo=lambda *a: None)
    state = rig.run(A.Config([{}]), retry_failed=True)
    assert len(state["choices"]) == 1 and not state["attempts"]
    assert len(rig.calls) == 0


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(version=500),
    lambda s: s.update(best=float("nan")),
    lambda s: s.update(attempts={}),
    lambda s: s.update(active="unknown"),
    lambda s: s.update(budget=-1),
    lambda s: s.update(evaluations=[]),
    lambda s: s.pop("choices"),
])
def test_corrupt_state_rejected_before_loader_or_execution(rig, mutation):
    rig.run()
    doc = read(rig)
    mutation(doc)
    (rig.root / "state.json").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="journal"):
        rig.run()
    assert not rig.launches and not rig.calls


@pytest.mark.parametrize("change", [
    {"pool": [{"min_edge": .12}]}, {"margin": 2.0}, {"model": "different"},
    {"stop_after": 2}, {"strategy": "hold"}, {"confirm_sims": 20000},
])
def test_incompatible_warm_start_is_rejected(rig, change):
    rig.run()
    args = dict(pool=[{"min_edge": .11}])
    args.update(change)
    with pytest.raises(ValueError, match="incompatible"):
        rig.run(A.Config(**args))


def test_process_lock_excludes_same_and_different_journals(rig):
    path = rig.root / "data" / "runs"
    path.mkdir(parents=True)
    with A._lock(path / "auto-sweeper"):
        with pytest.raises(RuntimeError, match="another controller"):
            rig.run(budget=8, jev_budget=1)
    assert not rig.launches and not rig.calls


def test_atomically_cached_choice_precedes_executor(rig):
    def execute(job, log, echo):
        doc = read(rig)
        assert doc["choices"][0]["status"] == "done"
        assert doc["active"] == doc["choices"][0]["answer"]["choice"]
        assert doc["attempts"][-1]["status"] == "launched"
        assert not list(rig.root.glob("*.pending"))
        rig.add(job)

    state = A.run(A.Config([{"min_edge": .11}]), rig.root / "state.json", execute=True,
                  backup=rig.backup, budget=8, jev_budget=1, loader=lambda: list(rig.store.values()),
                  chooser=rig.choose, executor=SimpleNamespace(run=execute), echo=lambda *a: None)
    assert len(state["evaluations"]) == 1


def test_reconcile_again_immediately_before_launch(rig):
    cfg = A.Config([{"min_edge": .11}])
    count = 0
    first_job = A.requirements(cfg.pool[0], cfg.document())[0]

    def loader():
        nonlocal count
        count += 1
        if count == 4:
            rig.add(first_job)
        return list(rig.store.values())

    state = A.run(cfg, rig.root / "state.json", execute=True, backup=rig.backup,
                  budget=7, jev_budget=1, loader=loader, chooser=rig.choose,
                  executor=SimpleNamespace(run=rig.execute), echo=lambda *a: None)
    assert first_job["id"] not in rig.launches
    assert len(state["evaluations"]) == 1 and len(state["attempts"]) == 7


def test_search_report_objective_is_gain_not_raw_pnl(rig):
    cfg = A.Config([{"min_edge": .11}])
    document = cfg.document()
    for job in A.requirements(cfg.pool[0], document):
        st = Settings.from_dict(job["settings"])
        is_candidate = st["min_edge"] == .11
        # Candidate loses money in heldout but improves that losing baseline.
        pnl = [200, 200, 200] if job["year"] == 2026 else [-100, -100, -100]
        if not is_candidate:
            pnl = [v - 200 for v in pnl]
        rig.add(job, pnl=pnl)
    state = rig.run(cfg)
    result = next(iter(state["evaluations"].values()))
    assert result["score"] == 600  # gain + min(0, heldout gain); not raw 600-300.
    assert result["vs_base_2025"] == 600
    assert result["loses_money_in"] == "2025" and result["shape"] == "mixed"


def test_noisy_improvement_does_not_claim_robust(rig):
    cfg = A.Config([{"min_edge": .11}])
    for job in A.requirements(cfg.pool[0], cfg.document()):
        candidate = Settings.from_dict(job["settings"])["min_edge"] == .11
        rig.add(job, pnl=[101 if candidate else 100] * 3)
    result = next(iter(rig.run(cfg)["evaluations"].values()))
    assert result["score"] == 3 and result["verdict"] == "not better"
    assert result["confirmed"] == ""


def test_confirmation_failed_evidence_not_claimed_successful(rig):
    cfg = A.Config([{"min_edge": .11}])
    for job in A.requirements(cfg.pool[0], cfg.document()):
        st = Settings.from_dict(job["settings"])
        candidate = st["min_edge"] == .11
        pnl = [100 if not candidate else (1000 if st["sims"] == 4000 else -100)] * 3
        rig.add(job, pnl=pnl)
    result = next(iter(rig.run(cfg)["evaluations"].values()))
    assert result["verdict"] == "robust" and result["confirmed"] == "no"


def test_signal_handlers_restore_after_run(rig):
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    rig.run()
    assert {s: signal.getsignal(s) for s in before} == before


def test_commit_then_child_error_is_recovered_without_retry(rig):
    def commit_then_error(job, log, echo):
        rig.add(job)
        raise RuntimeError("committed before child error")

    cfg = A.Config([{"min_edge": .11}])
    with pytest.raises(RuntimeError, match="committed"):
        A.run(cfg, rig.root / "state.json", execute=True, backup=rig.backup,
              budget=8, jev_budget=1, loader=lambda: list(rig.store.values()), chooser=rig.choose,
              executor=SimpleNamespace(run=commit_then_error), echo=lambda *a: None)
    assert read(rig)["failure_job"] in rig.store
    state = rig.run(cfg)
    assert len(state["evaluations"]) == 1 and len(state["attempts"]) == 8
    assert len(rig.launches) == 7 and len(rig.calls) == 1


def test_distinct_seeds_have_distinct_scores_not_report_average(rig):
    cfg = A.Config([{"min_edge": .11, "seed": 1}, {"min_edge": .11, "seed": 2}])
    for settings in cfg.pool:
        for job in A.requirements(settings, cfg.document()):
            st = Settings.from_dict(job["settings"])
            pnl = 100
            if st["min_edge"] == .11:
                pnl += 200 if st["seed"] == 1 else 400
            rig.add(job, pnl=[pnl] * 3)
    state = rig.run(cfg)
    assert state["evaluations"][Settings.from_dict(cfg.pool[0]).key]["score"] == 600
    assert state["evaluations"][Settings.from_dict(cfg.pool[1]).key]["score"] == 1200
    assert not rig.launches and not rig.calls


def test_small_improvement_updates_best_without_resetting_streak(rig):
    cfg = A.Config([{"min_edge": .11}, {"min_edge": .12}], margin=100)
    for i, settings in enumerate(cfg.document()["pool"]):
        for job in A.requirements(settings, cfg.document()):
            st = Settings.from_dict(job["settings"])
            candidate = st["min_edge"] != Settings.from_dict()["min_edge"]
            rig.add(job, pnl=[100 + (200 + i * 10 if candidate else 0)] * 3)
    state = rig.run(cfg)
    assert state["best"] == 630 and state["misses"] == 1


def test_deferred_termination_during_popen_still_reaps_owned_child(workspace, monkeypatch):
    child = Mock()
    child.poll.return_value = None
    child.wait.return_value = 0

    def popen(*a, **kw):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return child

    monkeypatch.setattr(A.subprocess, "Popen", popen)
    monkeypatch.setattr(A, "local_database", lambda: "postgresql://localhost/synthetic")
    with pytest.raises(KeyboardInterrupt):
        A.LocalExecutor().run(dict(id="test", year=2026, settings={}), workspace / "owned.log", lambda *a: None)
    child.terminate.assert_called_once_with()
    child.wait.assert_called_once_with(timeout=10)


def test_typed_jev_choice_uses_one_request_no_retry(monkeypatch):
    import sys
    from racinglines.research import jev_gate

    client = Mock()
    client.system_one.return_value = SimpleNamespace(
        choices={"next": SimpleNamespace(choice="exact-key", probabilities={"exact-key": 1}, confidence=.9)})
    monkeypatch.setattr(jev_gate, "make_client", lambda: client)
    monkeypatch.setitem(sys.modules, "typesafe_sdk", SimpleNamespace(
        RetryPolicy=lambda **kw: kw))
    result = A.ask_jev({"candidates": []}, ["exact-key", A.STOP], "stand-in")
    assert result["choice"] == "exact-key"
    kw = client.system_one.call_args.kwargs
    assert kw["retry"]["max_retries"] == 0
    assert kw["questions"]["next"]["type"] == "choice"
    assert list(kw["questions"]["next"]["criteria"]) == ["exact-key", A.STOP]
    client.system_one.assert_called_once()


@pytest.mark.parametrize("url", [
    "postgresql://user:secret@example.com/database",
    "sqlite:///somewhere", "postgresql://host.docker.internal/database",
])
def test_local_database_refuses_remote_sources(monkeypatch, url):
    from racinglines.cli import config
    monkeypatch.setattr(config, "load", lambda: {})
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError, match="local PostgreSQL"):
        A.local_database()


def test_local_database_refuses_demo_store(monkeypatch):
    monkeypatch.setenv("RACINGLINES_DEMO", "synthetic")
    with pytest.raises(ValueError, match="demo"):
        A.local_database()


def test_standalone_script_dry_run(workspace, capsys):
    path = Path(A.__file__).resolve().parents[2] / "scripts/research/auto_sweeper.py"
    spec = importlib.util.spec_from_file_location("auto_sweeper_script", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    pool = workspace / "pool.json"
    pool.write_text(json.dumps([{"min_edge": .11}]))
    assert script.main([str(pool), "--dry-run", "--journal", str(workspace / "unused" / "state.json")]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["dry_run"] and data["max_new_sweeps"] == 8
    assert sorted(p.name for p in workspace.iterdir()) == ["pool.json"]


@pytest.mark.parametrize("field,value", [
    ("stop_after", True), ("stop_after", 1.5), ("confirm_sims", True),
    ("confirm_sims", 16000.5), ("confirm_sims", 10**10),
])
def test_confirmation_and_stop_types_rejected_before_side_effects(workspace, field, value):
    with pytest.raises(ValueError):
        A.run(A.Config([{}], **{field: value}), workspace / "state.json")
    assert not list(workspace.iterdir())


def mock_sql_runs(monkeypatch, rows):
    from racinglines.db import config
    conn = Mock()
    conn.begin.return_value = nullcontext()
    conn.execute.return_value.mappings.return_value.all.return_value = rows
    engine = Mock()
    engine.connect.return_value = nullcontext(conn)
    monkeypatch.setattr(config, "get_engine", lambda *a: engine)
    monkeypatch.setattr(A, "local_database", lambda: "postgresql://localhost/synthetic")
    return conn


def test_legacy_exact_saved_run_loader_prevents_repeat(rig, monkeypatch):
    cfg = A.Config([{"min_edge": .11}])
    job = A.requirements(cfg.pool[0], cfg.document())[0]
    saved = rig.add(job)
    params = dict(Settings.from_dict(job["settings"]), year=job["year"],
                  settings_key=Settings.from_dict(job["settings"]).key)
    # No sport, no nested settings: a legitimate older F1 row.
    conn = mock_sql_runs(monkeypatch, [
        dict(id=saved["run_id"], params=params, metrics=saved["metrics"]),
        dict(id=999, params=dict(year=2026, settings_key="irrelevant-future-key"), metrics=None),
    ])
    loaded = A.load_runs({job["id"]})
    assert len(loaded) == 1 and A.job_id(loaded[0]["year"], loaded[0]["settings"]) == job["id"]
    sql = str(conn.execute.call_args_list[-1].args[0])
    assert "coalesce(params->>'sport', 'f1') = 'f1'" in sql
    assert str(conn.execute.call_args_list[0].args[0]) == "SET TRANSACTION READ ONLY"
    state = rig.run(cfg, budget=7, jev_budget=1)
    assert job["id"] not in rig.launches and len(state["evaluations"]) == 1


@pytest.mark.parametrize("mutation", [
    lambda w: w[0].pop("update_pnl"),
    lambda w: w[0].update(update_pnl=None),
    lambda w: w[0].update(update_pnl=float("nan")),
    lambda w: w[0].update(update_pnl=float("inf")),
    lambda w: w[0].update(update_pnl="600"),
    lambda w: w[1].update(round=w[0]["round"]),
    lambda w: w[0].pop("event"),
    lambda w: w[0].update(event=""),
    lambda w: w[1].update(event=w[0]["event"]),
    lambda w: w[0].update(round=1.5),
    lambda w: w[0].update(event="different-event"),
    lambda w: w.pop(),
])
def test_malformed_evidence_blocks_scoring_not_success_shaped_zeros(rig, mutation):
    cfg = A.Config([{"min_edge": .11}])
    for job in A.requirements(cfg.pool[0], cfg.document()):
        rig.add(job)
    candidate = A.job_id(2026, cfg.pool[0])
    mutation(rig.store[candidate]["metrics"]["weekends"])
    with pytest.raises(ValueError, match="run"):
        rig.run(cfg)
    assert not read(rig)["evaluations"]


def test_global_lock_cannot_be_escaped_by_other_cwd(rig, monkeypatch):
    lock = rig.root / "data/runs/auto-sweeper"
    lock.parent.mkdir(parents=True)
    elsewhere = rig.root / "elsewhere"
    elsewhere.mkdir()
    with A._lock(lock):
        monkeypatch.chdir(elsewhere)
        with pytest.raises(RuntimeError, match="another controller"):
            rig.run(budget=8, jev_budget=1)
    assert not (elsewhere / "data").exists()


def test_partial_historical_baselines_are_supplied_to_jev(rig):
    cfg = A.Config([{"min_edge": .11}])
    job = A.requirements(cfg.pool[0], cfg.document())[0]
    rig.add(job)
    rig.run(cfg, budget=1, jev_budget=1)
    evidence = rig.calls[0]["evidence"]
    assert evidence["stored"][0]["id"] == job["id"]
    assert evidence["stored"][0]["baseline"] is True
    assert evidence["stored"][0]["pnl"] == 300
    assert evidence["stored"][0]["gain"] == 0
    assert evidence["noise"]["policy"] == "fixed-search-report-defaults-v1"


def test_saved_live_pid_blocks_restart_without_killing(rig, monkeypatch):
    rig.run(budget=1, jev_budget=1)
    state = read(rig)
    state["attempts"][0].update(pid=12345, reaped=False, status="launched")
    (rig.root / "state.json").write_text(json.dumps(state))
    kill = Mock()
    monkeypatch.setattr(A.os, "kill", kill)
    with pytest.raises(RuntimeError, match="may still be alive"):
        rig.run(retry_failed=True)
    kill.assert_called_once_with(12345, 0)
    assert len(rig.launches) == 1


@pytest.mark.parametrize("replace", [False, True])
def test_pre_stored_run_pin_disappearance_or_replacement_blocks_resume(rig, replace):
    cfg = A.Config([{"min_edge": .11}])
    job = A.requirements(cfg.pool[0], cfg.document())[0]
    rig.add(job)
    rig.run(cfg)
    assert read(rig)["pins"][job["id"]] == 1
    if replace:
        rig.add(job)
    else:
        rig.store.clear()
    with pytest.raises(RuntimeError, match="disappeared or was replaced"):
        rig.run(cfg, retry_failed=True)
    assert not rig.launches


def test_database_identity_ignores_credentials_but_binds_host_port_database(monkeypatch):
    monkeypatch.setattr(A, "local_database", lambda: "postgresql://u:secret@localhost:5432/db")
    one = A.database_identity()
    monkeypatch.setattr(A, "local_database", lambda: "postgresql://other:another@localhost/db")
    assert A.database_identity() == one and "secret" not in one
    monkeypatch.setattr(A, "local_database", lambda: "postgresql://u:secret@localhost/different")
    assert A.database_identity() != one


def test_database_context_mismatch_rejected_before_loader(rig):
    rig.run()
    doc = read(rig)
    doc["database_identity"] = "f" * 64
    (rig.root / "state.json").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="database identity"):
        rig.run()
    assert not rig.launches


def test_partial_existing_identity_blocks_but_full_counterpart_can_be_used(rig, monkeypatch):
    cfg = A.Config([{"min_edge": .11}])
    job = A.requirements(cfg.pool[0], cfg.document())[0]
    st = Settings.from_dict(job["settings"])
    params = dict(year=job["year"], settings=st.to_json(), settings_key=st.key, rounds="1,2")
    row = dict(id=1, params=params, metrics={"weekends": []})
    conn = mock_sql_runs(monkeypatch, [row])
    with pytest.raises(ValueError, match="partial sweep blocks"):
        A.load_runs({job["id"]})
    sql = str(conn.execute.call_args_list[-1].args[0])
    assert "params->>'rounds'" not in sql
    assert A.load_runs({"2026:unrelated"}) == []
    full = rig.add(job)
    full_row = dict(id=2, params=dict(params, rounds=None), metrics=full["metrics"])
    mock_sql_runs(monkeypatch, [row, full_row])
    assert A.load_runs({job["id"]})[0]["run_id"] == 2


def test_executor_checkpoints_pid_before_wait_and_inherits_root_lock(workspace, monkeypatch):
    child = Mock(pid=1234)
    child.wait.return_value = 0
    popen = Mock(return_value=child)
    monkeypatch.setattr(A.subprocess, "Popen", popen)
    monkeypatch.setattr(A, "local_database", lambda: "postgresql://localhost/synthetic")
    executor = A.LocalExecutor()
    executor.lock_fd = 123
    seen = []

    def started(pid):
        assert not child.wait.called
        seen.append(pid)

    executor.run(dict(id="test", year=2026, settings={}), workspace / "owned.log", lambda *a: None, started)
    assert seen == [1234]
    assert popen.call_args.kwargs["cwd"] == workspace
    assert popen.call_args.kwargs["pass_fds"] == (123,)


def test_leaderboard_exposes_settings_both_windows_and_noise(rig):
    rig.run(budget=8, jev_budget=1)
    text = (rig.root / "leaderboard.md").read_text()
    for term in ("min_edge=0.11", "gain target / heldout", "P&L target / heldout", "noise",
                 "loses money in", "pinned", "descriptive", "1800"):
        assert term in text


def test_replicate_noise_cannot_change_cached_controller_floor(rig):
    cfg = A.Config([{"min_edge": .11, "seed": i} for i in (1, 2, 3)])
    for settings in cfg.pool:
        for job in A.requirements(settings, cfg.document()):
            st = Settings.from_dict(job["settings"])
            value = 100 + (st["seed"] * 10000 if st["min_edge"] == .11 else 0)
            rig.add(job, pnl=[value] * 3)
    state = rig.run(cfg)
    assert {r["noise_floor"] for r in state["evaluations"].values()} == {150.0}
    assert {r["noise_floor"] for r in rig.run(cfg)["evaluations"].values()} == {150.0}


def test_noise_defaults_are_pinned_in_resume_configuration(rig, monkeypatch):
    from racinglines.pipelines import search_report

    rig.run()
    assert read(rig)["config"]["noise"]["taker"] == 150.0
    monkeypatch.setitem(search_report.DEFAULTS, "noise", dict(taker=999.0, maker=350.0, model=25.0))
    with pytest.raises(ValueError, match="incompatible journal configuration"):
        rig.run()
