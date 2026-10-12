"""Nothing in the repo calls the old sport-first CLI form: code, VM and cloud scripts, systemd units, sweeps, sport
schemas, templates and docs all use `racinglines data|model|strategy <command> SPORT`. The old form is an alias with a
notice for one version only (owner, 2026-10-11: one command set for users and every background job by end of week).
History logs and dated reports keep the commands as they were run.

Caught: `racinglines f1 forecast`, `racinglines nascar|motogp replay`, `racinglines f1 --variant X sweep`,
`racinglines <sport> forecast`, `$R nascar fetch`, `$R "$S" replay`, `${RACINGLINES} $sport forecast`, and argv lists such as
`["-m", "racinglines", sport, "sweep"]` or `["racinglines", "f1", "--half-life", hl, "backtest"]`."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKIP = re.compile(r"^(docs/history\.md|docs/data-changes(\.md|/)|reports/|racinglines/cli/(__init__|verbs)\.py"
                  r"|tests/test_cli_verbs\.py|tests/test_no_old_cli_forms\.py)")
TEXT = re.compile(r"(\.(md|py|sh|toml|html|service|timer|ya?ml|txt|js)$|^scripts/)")
SPORTS = r"(?:f1|mtb_dh|nascar|motogp|cycling|road_cycling)"
SPORT_OPTS = r"(?:db|variant|half-life)"
Q = r"[\"']?"
# shell and prose: racinglines | $R | ${RL} | $RACINGLINES, a sport (a name, `a|b`, or a shell variable), the
# sport's own options, then a word
SHELL = re.compile(r"(?:\bracinglines\b|\$\{?(?:R|RL|RACINGLINES)\}?)\s+" + Q
                   + r"(?P<sport>" + SPORTS + r"(?:\|" + SPORTS + r")*|\$\{?\w+\}?|<sport>|<SPORT>)" + Q
                   + r"(?:\s+--" + SPORT_OPTS + r"(?:=\S+|\s+\S+))*\s+(?P<cmd>[a-z][a-z-]+)\b")
# argv lists: "racinglines", then a sport (a quoted name or a variable), the sport's options, then a quoted word
ARGV = re.compile(r"[\"']racinglines[\"']\s*,\s*(?P<sport>[\"']" + SPORTS + r"[\"']|[a-z_][\w.\[\]\"']*)\s*,"
                  r"(?:\s*[\"']--" + SPORT_OPTS + r"[\"']\s*,\s*[^,\]]+,)*\s*[\"'](?P<cmd>[a-z][a-z-]+)[\"']")


def _commands():
    from racinglines.cli import verbs
    return set().union(*(verbs.commands(m) for m in verbs.MODULES)), set(verbs.GROUPS)


def old_forms(text):
    """(line number, line) of each old sport-first call in text."""
    cmds, groups = _commands()
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for rx in (SHELL, ARGV):
            for m in rx.finditer(line):
                sport = m["sport"].strip("\"'")
                if m["cmd"] in cmds and sport not in groups:
                    out.append((n, line.strip()))
                    break
            else:
                continue
            break
    return out


def _files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if TEXT.search(f) and not SKIP.match(f)]


@pytest.mark.parametrize("line", [
    "racinglines f1 forecast --save",
    "racinglines nascar|motogp replay",
    "racinglines f1 --variant gridq sweep --year 2026",
    "nice $R nascar fetch --years 2026",
    'nice $R "$S" replay --years 2026',
    "${RACINGLINES} $sport forecast --save",
    "$RACINGLINES nascar forecast",
    "undo with `racinglines <sport> demo-history --reset`",
    'py = [sys.executable, "-m", "racinglines", sport, "sweep"]',
    'a = ["racinglines", "f1", "--half-life", str(hl), "backtest"]',
    "argv = ['-m', 'racinglines', j['sport'], 'replay']",
])
def test_old_forms_are_caught(line):
    assert old_forms(line)


@pytest.mark.parametrize("line", [
    "racinglines model forecast f1 --save",
    "racinglines strategy replay nascar|motogp",
    'nice $R strategy replay "$S" --years 2026',
    'py = [sys.executable, "-m", "racinglines", "strategy", "sweep", sport]',
    "racinglines book price --demo",
    "racinglines live run --demo",
    "racinglines is the package; racinglines the replay",
])
def test_new_forms_pass(line):
    assert not old_forms(line)


def test_no_caller_uses_the_sport_first_form():
    hits = []
    for f in _files():
        p = ROOT / f
        if p.is_file():
            hits += [f"{f}:{n}: {line[:120]}" for n, line in old_forms(p.read_text(encoding="utf-8", errors="replace"))]
    assert not hits, "old sport-first CLI form (now racinglines data|model|strategy <command> SPORT):\n" + "\n".join(hits)
