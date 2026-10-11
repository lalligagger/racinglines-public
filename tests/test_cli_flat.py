"""Flat commands (racinglines/cli/flat.py): `racinglines <command> --sport SPORT` runs exactly what the sport-first
`racinglines SPORT <command>` runs; every sport command is listed; the sport-first form still works."""

import argparse
import importlib

import pytest

from racinglines import cli
from racinglines.cli import flat as FL

pytestmark = pytest.mark.quick


@pytest.mark.parametrize("module", FL.MODULES)
def test_every_sport_command_is_listed(module):
    cmds = FL.commands(module)
    listed = {FL.RENAMED.get(c, c) for c in FL.COMMANDS}
    assert cmds and set(cmds) - listed == set()


def test_flat_names_never_shadow_a_group():
    assert set(FL.COMMANDS) & set(cli.GROUPS) <= {"backtest"}    # `backtest` is shared, see BACKTEST_CORE


@pytest.mark.parametrize("module", FL.MODULES)
def test_no_command_shares_an_option_with_its_sport(module):
    """The sport parser's own options are moved before the command; safe only while no command has one by that name."""
    p = FL.parser_of(module)
    own = {s for a in p._actions if not isinstance(a, argparse._SubParsersAction) for s in a.option_strings} - {"-h", "--help"}
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sub in a.choices.items():
                assert not own & {s for x in sub._actions for s in x.option_strings}, (module, name)


@pytest.fixture
def record(monkeypatch):
    """Replace the sport modules' main() with a recorder (their parsers are read first)."""
    monkeypatch.setenv("RACINGLINES_PROGRESS_SEC", "0")
    monkeypatch.delenv("RACINGLINES_SPORT", raising=False)
    parsers = {m: FL.parser_of(m) for m in FL.MODULES}
    cmds = {m: FL.commands(m) for m in FL.MODULES}
    monkeypatch.setattr(FL, "parser_of", parsers.__getitem__)
    monkeypatch.setattr(FL, "commands", cmds.__getitem__)
    seen = []
    for m in FL.MODULES:
        mod = importlib.import_module(f"racinglines.cli.{m}")
        monkeypatch.setattr(mod, "main", lambda argv=None, m=m: seen.append((m, list(argv))) or 0)
    return seen


def test_the_flat_form_runs_the_sport_command(record, monkeypatch):
    assert cli.main(["backtest", "--sport", "f1", "--variant", "grid", "--save", "--db=postgresql://x"]) == 0
    assert record[-1] == ("f1", ["--variant", "grid", "--db=postgresql://x", "backtest", "--save"])
    assert cli.main(["replay", "--runs", "1,2", "--sport=nascar"]) == 0
    assert record[-1] == ("nascar", ["replay", "--runs", "1,2"])
    assert cli.main(["download", "--year", "2026"]) == 0                 # one sport offers it: no --sport needed
    assert record[-1] == ("mtb_dh", ["download", "--year", "2026"])
    assert cli.main(["follow", "--sport", "mtb_dh", "x.toml"]) == 0      # renamed: the downhill `live`
    assert record[-1] == ("mtb_dh", ["live", "x.toml"])
    assert cli.main(["events", "--sport", "road_cycling"]) == 0          # the schema's code works too
    assert record[-1] == ("cycling", ["events"])
    monkeypatch.setenv("RACINGLINES_SPORT", "motogp")
    assert cli.main(["forecast", "--save"]) == 0
    assert record[-1] == ("motogp", ["forecast", "--save"])
    assert cli.main(["f1", "replay", "--runs", "1,2"]) == 0               # the sport-first form
    assert record[-1] == ("f1", ["replay", "--runs", "1,2"])


def test_the_backtest_core_keeps_its_group(record, monkeypatch):
    seen = []
    monkeypatch.setattr(importlib.import_module("racinglines.cli.backtest"), "main", lambda argv=None: seen.append(argv) or 0)
    assert cli.main(["backtest", "coverage", "--seasons", "2026"]) == 0
    assert seen == [["coverage", "--seasons", "2026"]] and not record


def test_missing_or_wrong_sport(record, capsys):
    assert cli.main(["forecast"]) == 2
    assert "f1, mtb_dh, nascar, motogp" in capsys.readouterr().err
    assert cli.main(["forecast", "--sport", "cycling"]) == 2
    assert "not offered for cycling" in capsys.readouterr().err
    assert not record


def test_help_lists_commands_with_their_sports(capsys):
    assert cli.main(["-h"]) == 0
    out = capsys.readouterr().out
    assert "    replay " in out and "f1 nascar motogp" in out and "\n    f1 " not in out
