"""Rich output by default (racinglines/cli/tty.py): forced colour off a terminal, NO_COLOR and journald without escape
codes, --plain / RACINGLINES_PLAIN for the plain text, progress lines kept plain off a terminal."""

import io

import pytest


@pytest.fixture
def env(monkeypatch):
    for k in ("RACINGLINES_PLAIN", "NO_COLOR", "FORCE_COLOR", "JOURNAL_STREAM", "TTY_INTERACTIVE"):
        monkeypatch.setenv(k, "")
        monkeypatch.delenv(k)
    return monkeypatch


def _out(con, markup="[bold green]+1.00[/] 📊"):
    buf = io.StringIO()
    con.file = buf
    con.print(markup)
    return buf.getvalue()


def test_colour_by_default_and_the_off_switches(env):
    from racinglines.cli import source, tty
    assert "\x1b[" in _out(tty.console())                          # piped (pytest's stdout): still coloured
    env.setenv("NO_COLOR", "1")
    assert _out(tty.console()) == "+1.00 📊\n"                     # layout and emojis, no escape codes
    env.delenv("NO_COLOR")
    env.setenv("JOURNAL_STREAM", "8:123")                          # a systemd unit's output: no "[blob data]"
    assert _out(tty.console()) == "+1.00 📊\n"
    env.setenv("FORCE_COLOR", "1")
    assert "\x1b[" in _out(tty.console())
    assert source.apply(["db", "stats", "--plain"]) == ["db", "stats"]
    assert tty.plain() and tty.console() is None
    source.reset()


def test_progress_off_a_terminal_prints_plain_progress_lines(env, capsys):
    from racinglines.cli import tty
    con = tty.console()
    with tty.Progress(con, every=10) as pr:
        pr.new("📊 backtest")
        for i in range(1, 24):
            pr.echo(f"progress {i}/23 race {i}")
        pr.echo("a note")
    lines = capsys.readouterr().out.splitlines()
    assert [x for x in lines if x.startswith("progress ")] == ["progress 10/23 race 10", "progress 20/23 race 20",
                                                               "progress 23/23 race 23"]
    assert any("backtest" in x for x in lines) and "a note" in lines
