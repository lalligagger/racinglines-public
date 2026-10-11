"""
Record the public /term page's CLI runs (racinglines/web/term/demos.toml, docs/webapp.md, Pages: Command line).

    python scripts/demo/record_term.py --run    # run each demo's `run` argv, save what it printed, render
    python scripts/demo/record_term.py          # re-render the saved output only (nothing runs)

--run executes each command as a user would type it, in colour with Rich's animations off (the final frame of each
progress bar or live table), and saves its stdout as racinglines/web/term/<id>.ansi. This checkout's absolute path is
cut from the output, so paths read relative to the repo. Rendering turns each saved .ansi into
racinglines/web/term/<id>.html, an HTML fragment the page includes as is.
"""

import argparse
import io
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import MONOKAI
from rich.text import Text

ROOT = Path(__file__).resolve().parents[2]
TERM = ROOT / "racinglines" / "web" / "term"
WIDTH = 120     # terminal columns of a recording; the page scrolls sideways on a phone
FORMAT = '<pre class="term-out">{code}</pre>'


def demos():
    return tomllib.loads((TERM / "demos.toml").read_text()).get("demo", [])


def render(d):
    """A demo's saved terminal output (ANSI) -> the HTML fragment."""
    console = Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor", file=io.StringIO())
    console.print(Text.from_ansi((TERM / f"{d['id']}.ansi").read_text()), soft_wrap=True)
    return console.export_html(theme=MONOKAI, inline_styles=True, code_format=FORMAT)


def run(d):
    """Execute the demo's command and save what it printed to stdout."""
    argv = [sys.executable, "-m", *d["run"]] if d["run"][0] == "racinglines" else d["run"]
    env = dict(os.environ, COLUMNS=str(WIDTH), FORCE_COLOR="1", TTY_INTERACTIVE="0", PYTHONUNBUFFERED="1")
    out = subprocess.run(argv, capture_output=True, text=True, check=True, env=env).stdout
    roots = {str(ROOT), os.getcwd(), *filter(None, env.get("PYTHONPATH", "").split(os.pathsep))}
    for r in sorted(roots, key=len, reverse=True):
        out = out.replace(r.rstrip("/") + "/", "")
    (TERM / f"{d['id']}.ansi").write_text(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="re-run each command first")
    args = ap.parse_args(argv)
    for d in demos():
        if args.run:
            run(d)
            print(f"{d['id']}: ran `{d['command']}`; update `recorded` in demos.toml", flush=True)
        (TERM / f"{d['id']}.html").write_text(render(d))
        print(f"{d['id']}: rendered {TERM / (d['id'] + '.html')}", flush=True)


if __name__ == "__main__":
    main()
