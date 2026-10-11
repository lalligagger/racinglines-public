"""Nothing in the repo calls the old sport-first CLI form (`racinglines f1 forecast`, `$R nascar sweep`, a
`["-m", "racinglines", "f1", ...]` argv): code, VM and cloud scripts, systemd units, sweeps, sport schemas, templates
and docs all use `racinglines data|model|strategy <command> SPORT`. The old form is an alias with a notice for one
version only (owner, 2026-10-11: one command set for users and every background job by end of week). History logs
and dated reports keep the commands as they were run."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = re.compile(r"^(docs/history\.md|docs/data-changes(\.md|/)|reports/|racinglines/cli/(__init__|verbs)\.py"
                  r"|tests/test_cli_verbs\.py|tests/test_no_old_cli_forms\.py)")
TEXT = re.compile(r"(\.(md|py|sh|toml|html|service|timer|ya?ml|txt|js)$|^scripts/)")
SPORT = r"(f1|mtb_dh|nascar|motogp|cycling)"
# racinglines | $R | ${RL} | "racinglines", then a sport, optional sport options, then a command word
OLD = re.compile(r"(\bracinglines\b|\$\{?RL?\}?)\"?,?\s+\"?" + SPORT + r"\"?,?"
                 r"(\s+\"?--(db|variant|half-life)\"?,?\s+\S+)*\s+\"?([a-z][a-z-]+)\b")


def _files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if TEXT.search(f) and not SKIP.match(f)]


def test_no_caller_uses_the_sport_first_form():
    from racinglines.cli import verbs
    cmds = {m: set(verbs.commands(m)) for m in verbs.MODULES}
    hits = []
    for f in _files():
        p = ROOT / f
        if not p.is_file():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in OLD.finditer(line):
                if m.group(5) in cmds[m.group(2)]:
                    hits.append(f"{f}:{n}: {line.strip()[:120]}")
    assert not hits, "old sport-first CLI form (now racinglines data|model|strategy <command> SPORT):\n" + "\n".join(hits)
