"""Pure planner and no-side-effects CLI contract."""

import copy
import json

import pytest

from racinglines.pipelines import search as S
from racinglines.pipelines import search_plan as P
from racinglines.pipelines.sweep_settings import Settings

pytestmark = pytest.mark.quick


def key(settings):
    return Settings.from_dict(settings).key


def test_new_candidates_deduplicates_normalized_keys_in_input_order():
    candidates = [{"min_edge": 0.08}, {}, {"min_edge": "0.08"}, {"min_edge": 0.09}, {"min_edge": 0.05}]
    before = copy.deepcopy(candidates)
    stored = {key({})}
    result = P.new_candidates(candidates, stored)
    assert [s["min_edge"] for s in result] == [0.08, 0.09]
    assert result == P.new_candidates(candidates, reversed(sorted(stored)))
    assert candidates == before and stored == {key({})}


def test_candidate_key_matches_search_candidate_import_path(tmp_path):
    path = tmp_path / "queue.toml"
    path.write_text('[[candidate]]\nvariant = "gridq"\nhalf_spread = 0.03\n')
    _, _, (candidate,) = S.load(path)
    planned = P.plan([candidate["settings"]], set(), budget=1)["candidates"][0]
    assert planned["settings_key"] == candidate["settings_key"] == key(candidate["settings"])
    assert P.plan([candidate["settings"]], {candidate["settings_key"]}, budget=1)["candidates"] == []


def test_run_identity_keeps_simulations_seed_and_venue_but_normalizes_aliases():
    candidates = [{}, {"n_sims": 4000}, {"sims": 8000}, {"seed": 1}, {"venue": "kalshi"}]
    result = P.new_candidates(candidates, set())
    assert len(result) == 4
    assert [key(s) for s in result] == [key(candidates[i]) for i in (0, 2, 3, 4)]
    with pytest.raises(ValueError, match="unknown settings"):
        P.new_candidates([{"data_key": "season-fingerprint"}], set())


@pytest.mark.parametrize("budget, count", [(0, 0), (1, 1), (2, 2), (10, 3)])
def test_budget_counts_only_unique_new_settings(budget, count):
    candidates = [{}, {"min_edge": 0.08}, {"min_edge": 0.08}, {"min_edge": 0.09}, {"min_edge": 0.1}]
    out = P.plan(candidates, {key({})}, budget=budget)
    assert out["new_count"] == 3 and out["selected_count"] == count
    assert [c["settings"]["min_edge"] for c in out["candidates"]] == [0.08, 0.09, 0.1][:count]
    assert out == P.plan(candidates, {key({})}, budget=budget)


def history(scores):
    return [dict(settings_key=f"done-{i}", score=s) for i, s in enumerate(scores)]


def test_stop_latches_at_k_misses_and_does_not_consume_pending_scores():
    completed = history([12, 12.5, 12.5, 100])
    out = P.plan([{}], {h["settings_key"] for h in completed}, budget=3, history=completed,
                 best_score=10, margin=1, stop_after=2)
    assert out["stopped"] and out["reason"] == "stop_rule" and out["candidates"] == []
    assert out["consecutive_misses"] == 2 and out["best_score"] == 12.5


def test_margin_boundary_is_a_miss_and_improvement_resets_streak():
    completed = history([11, 13, 13])
    out = P.plan([{}, {"min_edge": 0.08}], {h["settings_key"] for h in completed}, budget=3,
                 history=completed, best_score=10, margin=1, stop_after=2)
    assert not out["stopped"] and out["consecutive_misses"] == 1 and out["best_score"] == 13
    assert out["selected_count"] == 2


def test_stop_off_and_empty_history_do_not_block():
    completed = history([0, 0])
    assert P.plan([{}], {h["settings_key"] for h in completed}, budget=1, history=completed,
                  best_score=10)["selected_count"] == 1
    assert P.plan([{}], set(), budget=1, best_score=10, stop_after=1)["selected_count"] == 1
    assert P.plan([], set())["reason"] == "exhausted"


@pytest.mark.parametrize("kwargs, message", [
    ({"budget": -1}, "budget"), ({"budget": True}, "budget"), ({"budget": 1.5}, "budget"),
    ({"stop_after": -1}, "stop_after"), ({"stop_after": 1}, "best_score"),
    ({"margin": -1}, "margin"), ({"margin": float("nan")}, "finite"),
    ({"best_score": float("inf")}, "finite"), ({"best_score": True}, "finite"),
    ({"history": [{"settings_key": "absent", "score": 1}]}, "stored_keys"),
    ({"history": [{"settings_key": "done", "score": float("nan")}]}, "finite"),
    ({"history": [{"settings_key": "done", "score": 1}] * 2}, "duplicate"),
    ({"history": [{"score": 1}]}, "settings_key"),
])
def test_invalid_controls_and_history_are_explicit_errors(kwargs, message):
    with pytest.raises(ValueError, match=message):
        P.plan([{}], {"done"}, **kwargs)


def test_invalid_settings_are_not_hidden_by_zero_budget():
    with pytest.raises(ValueError, match="unknown settings"):
        P.plan([{"typo": 1}], set())


@pytest.mark.parametrize("dry_run", [False, True])
def test_task_first_cli_only_prints_and_writes_nothing(tmp_path, monkeypatch, capsys, dry_run):
    from racinglines.cli import verbs
    from racinglines.db import config

    def forbidden(*args, **kwargs):
        pytest.fail("planner attempted database access or sweep execution")

    monkeypatch.setattr(config, "get_engine", forbidden)
    monkeypatch.setattr(config, "get_session", forbidden)
    monkeypatch.setattr(S, "run", forbidden)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(dict(year=2026, stored_keys=[key({})], candidates=[{}, {"min_edge": 0.08}])))
    monkeypatch.chdir(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    verbs.main("strategy", ["search-plan", "f1", str(path), "--budget", "1"] + (["--dry-run"] if dry_run else []))
    out = json.loads(capsys.readouterr().out)
    assert out["year"] == 2026 and out["dry_run"] == dry_run and out["execution_enabled"] is False
    assert out["selected_count"] == 1 and out["candidates"][0]["settings_key"] == key({"min_edge": 0.08})
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_cli_default_budget_and_invalid_input(tmp_path, capsys):
    from racinglines.cli import f1

    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(dict(year=2025, stored_keys=[], candidates=[{}])))
    f1.main(["search-plan", str(path)])
    assert json.loads(capsys.readouterr().out)["candidates"] == []
    with pytest.raises(SystemExit) as error:
        f1.main(["search-plan", str(path), "--budget", "-1"])
    assert error.value.code == 2 and "budget" in capsys.readouterr().err
    path.write_text('{"year": 2026, "stored_keys": [], "candidates": "wrong"}')
    with pytest.raises(SystemExit):
        f1.main(["search-plan", str(path)])
    assert "candidates must be a list" in capsys.readouterr().err


def test_cli_passes_completed_history_and_stop_controls(tmp_path, capsys):
    from racinglines.cli import f1

    path = tmp_path / "snapshot.json"
    completed = history([11, 11])
    data = dict(year=2026, stored_keys=[h["settings_key"] for h in completed],
                candidates=[{}], history=completed)
    path.write_text(json.dumps(data))
    f1.main(["search-plan", str(path), "--budget", "5", "--stop-after", "2",
             "--best-score", "10", "--margin", "1", "--dry-run"])
    out = json.loads(capsys.readouterr().out)
    assert out["stopped"] and out["reason"] == "stop_rule" and out["selected_count"] == 0
    assert out["best_score"] == 11 and out["consecutive_misses"] == 2
    assert json.loads(path.read_text()) == data


def test_top_level_cli_cannot_build_demo_store(tmp_path, monkeypatch, capsys):
    from racinglines import cli
    from racinglines.cli import source

    def forbidden(*args, **kwargs):
        pytest.fail("pure planner attempted source selection or a demo database build")

    monkeypatch.setattr(source, "take_demo", forbidden)
    monkeypatch.setattr(source, "use_demo", forbidden)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(dict(year=2026, stored_keys=[], candidates=[{}])))
    cli.main(["strategy", "search-plan", "f1", str(path), "--dry-run"])
    assert json.loads(capsys.readouterr().out)["selected_count"] == 0
    with pytest.raises(SystemExit) as error:
        cli.main(["strategy", "search-plan", "f1", str(path), "--dry-run", "--demo"])
    assert error.value.code == 2 and "unrecognized arguments: --demo" in capsys.readouterr().err
    assert cli.main(["strategy", "search-plan", "--demo", "f1", str(path), "--dry-run"]) == 2


@pytest.mark.parametrize("data, message", [
    ([], "object"), ({"year": "2026"}, "year"),
    ({"year": 2026, "stored_keys": [None], "candidates": []}, "non-empty strings"),
    ({"year": 2026, "stored_keys": [], "candidates": [1]}, "objects"),
    ({"year": 2026, "stored_keys": [], "candidates": [], "history": {}}, "history must be a list"),
    ({"year": 2026, "stored_keys": [], "candidates": [], "typo": 1}, "object"),
])
def test_snapshot_schema_errors_are_explicit(tmp_path, data, message):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        P.print_plan(path)
