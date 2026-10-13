"""Task-first commands (racinglines/cli/verbs.py): `racinglines <group> <command> SPORT` runs exactly what the
sport-first `racinglines SPORT <command>` runs, every sport command has a group, and the sport-first form still works."""

import importlib

import pytest

from racinglines import cli
from racinglines.cli import verbs as VB

pytestmark = pytest.mark.quick


@pytest.mark.parametrize("module", VB.MODULES)
def test_every_sport_command_has_a_group(module):
    cmds = VB.commands(module)
    assert cmds, module
    assert {c: VB.group_of(c, module) for c in cmds if VB.group_of(c, module) is None} == {}


def _record(monkeypatch, module):
    seen = []
    mod = importlib.import_module(f"racinglines.cli.{module}")
    monkeypatch.setattr(mod, "main", lambda argv=None: seen.append(list(argv)) or 0)
    return seen


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setenv("RACINGLINES_PROGRESS_SEC", "0")


def test_the_task_first_form_runs_the_sport_command(monkeypatch, quiet):
    parser = VB.parser_of("f1")               # read before main is replaced
    monkeypatch.setattr(VB, "parser_of", lambda m: parser)
    seen = _record(monkeypatch, "f1")
    assert cli.main(["model", "backtest", "f1", "--variant", "grid", "--save", "--db=postgresql://x"]) == 0
    assert seen == [["--variant", "grid", "--db=postgresql://x", "backtest", "--save"]]   # f1's own options first
    assert cli.main(["strategy", "replay", "f1", "--runs", "1,2", "--sweep"]) == 0
    assert seen[-1] == ["replay", "--runs", "1,2", "--sweep"]
    assert cli.main(["f1", "replay", "--runs", "1,2"]) == 0                              # the sport-first form
    assert seen[-1] == ["replay", "--runs", "1,2"]


def test_sport_codes_and_short_names(monkeypatch, quiet):
    seen = _record(monkeypatch, "cycling")
    monkeypatch.setattr(VB, "parser_of", lambda m: __import__("argparse").ArgumentParser())
    monkeypatch.setattr(VB, "commands", lambda m: {"events": ""} if m == "cycling" else {})
    assert cli.main(["data", "events", "road_cycling"]) == 0 and cli.main(["data", "events", "cycling"]) == 0
    assert seen == [["events"], ["events"]]


def test_wrong_group_missing_or_unknown_sport(capsys, quiet):
    assert cli.main(["model", "forecast"]) == 2
    assert "f1, mtb_dh, nascar, motogp" in capsys.readouterr().err
    assert cli.main(["model", "walk-forward", "cycling"]) == 2             # not offered for that sport
    assert cli.main(["data", "forecast", "f1"]) == 2                       # a model command, not data
    assert cli.main(["model", "nope", "f1"]) == 2


def test_group_help_lists_commands_and_sports(capsys, quiet):
    assert cli.main(["strategy", "-h"]) == 0
    out = capsys.readouterr().out
    assert "replay" in out and "f1 nascar motogp" in out and "season-replay" in out
    assert cli.main(["-h"]) == 0
    top = capsys.readouterr().out
    assert "model forecast f1" in top and "\n    f1 " not in top                # sports aren't top-level groups


@pytest.mark.parametrize("module", VB.MODULES)
def test_no_command_shares_an_option_with_its_sport(module):
    """Options of the sport's own parser are moved before the command; safe only while no command has one by that name."""
    import argparse
    p = VB.parser_of(module)
    own = {s for a in p._actions if not isinstance(a, argparse._SubParsersAction) for s in a.option_strings} - {"-h", "--help"}
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sub in a.choices.items():
                assert not own & {s for x in sub._actions for s in x.option_strings}, (module, name)



def test_a_command_in_another_group_names_it(capsys):
    assert VB.main("model", ["sweep", "f1"]) == 2
    assert "racinglines strategy sweep f1" in capsys.readouterr().err
    assert VB.main("model", ["sweep"]) == 2
    assert "racinglines strategy sweep SPORT" in capsys.readouterr().err


def test_usage_lines_use_the_new_form():
    p = VB.parser_of("f1")
    sub = next(a for a in p._actions if a.choices and "sweep" in (a.choices or {})).choices["sweep"]
    assert sub.format_usage().startswith("usage: racinglines strategy sweep f1")
