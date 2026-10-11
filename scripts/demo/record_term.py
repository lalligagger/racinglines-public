"""
Record the public /term page: the demo pack's quickstart, run and replayed (racinglines/web/term/demos.toml,
docs/webapp.md, Pages: Quickstart replay).

    python scripts/demo/record_term.py --run    # run the quickstart's commands, save what they printed, render
    python scripts/demo/record_term.py          # re-render the saved output only (nothing runs)

The commands come from the pack's manifest (racinglines/demo/packs/<pack>/pack.toml, [[quickstart]]), the same list
docs/quickstart.md is built from (scripts/build_quickstart.py). --run snapshots that list into
racinglines/web/term/quickstart.json, then runs each command as a user would type it, in colour with Rich's animations
off (the final frame of each progress bar or live table), and saves what it printed (stdout and stderr, as a terminal
shows them) as racinglines/web/term/<id>.ansi. Absolute paths of this checkout, $HOME and the temp folder are cut, so
paths read relative to the repo. For a true first run, drop the demo store first (its database and data/demo/<pack>/).
Rendering turns each saved .ansi into racinglines/web/term/<id>.html, an HTML fragment the page includes as is.
"""

import argparse
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import MONOKAI
from rich.text import Text

ROOT = Path(__file__).resolve().parents[2]
TERM = ROOT / "racinglines" / "web" / "term"
WIDTH = 120     # terminal columns of a recording; the page scrolls sideways on a phone
FORMAT = '<pre class="term-out">{code}</pre>'
OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")    # OSC sequences (OSC-8 links): the page includes the HTML as is


def config():
    return tomllib.loads((TERM / "demos.toml").read_text())


def demos():
    """The recorded steps: [{id, title, command, about}], snapshotted from the pack's quickstart by --run."""
    f = TERM / "quickstart.json"
    return json.loads(f.read_text()) if f.is_file() else []


def quickstart(pack):
    """The pack's [[quickstart]] steps as the page lists them (needs the racinglines package with demo packs)."""
    from racinglines.demo import store
    found = store.find(pack)
    if found is None:
        sys.exit(f"no demo pack {pack!r} (racinglines/demo/packs/)")
    return [{"id": f"step-{i}", "title": s["title"], "command": s["run"], "about": s.get("about", ""),
             "record": s.get("record", True)} for i, s in enumerate(found.quickstart, 1)]


def render(d):
    """A demo's saved terminal output (ANSI) -> the HTML fragment (empty for a step with `record = false`)."""
    if not d.get("record", True):
        return ""
    console = Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor", file=io.StringIO())
    ansi = OSC.sub("", (TERM / f"{d['id']}.ansi").read_text())
    console.print(Text.from_ansi(ansi), soft_wrap=True)
    return console.export_html(theme=MONOKAI, inline_styles=True, code_format=FORMAT)


def run(d):
    """Execute the step's command and save what it printed."""
    argv = shlex.split(d["command"])
    argv = [sys.executable, "-m", *argv] if argv[0] == "racinglines" else argv
    env = dict(os.environ, COLUMNS=str(WIDTH), FORCE_COLOR="1", TTY_INTERACTIVE="0", PYTHONUNBUFFERED="1")
    try:
        out = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True, env=env).stdout
    except subprocess.CalledProcessError as e:
        sys.exit(f"{d['id']}: `{d['command']}` failed (exit {e.returncode}):\n{e.stdout}")
    roots = {str(ROOT), os.getcwd(), str(Path.home()), tempfile.gettempdir(),
             *filter(None, env.get("PYTHONPATH", "").split(os.pathsep))}
    for r in sorted(roots, key=len, reverse=True):
        out = out.replace(r.rstrip("/") + "/", "")
    (TERM / f"{d['id']}.ansi").write_text(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="re-run each command first")
    args = ap.parse_args(argv)
    if args.run:
        steps = quickstart(config().get("pack", "kart"))
        for old in TERM.glob("step-*.*"):
            old.unlink()
        (TERM / "quickstart.json").write_text(json.dumps(steps, indent=2) + "\n")
    for d in demos():
        if args.run and d.get("record", True):
            run(d)
            print(f"{d['id']}: ran `{d['command']}`; update `recorded` in demos.toml", flush=True)
        (TERM / f"{d['id']}.html").write_text(render(d))
        print(f"{d['id']}: rendered {TERM / (d['id'] + '.html')}", flush=True)


if __name__ == "__main__":
    main()
