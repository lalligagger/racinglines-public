"""
Record the public /term page's CLI runs (racinglines/web/term/demos.toml, docs/webapp.md, Pages: Command line).

    python scripts/demo/record_term.py --run    # run each demo's `run` argv with --json, save its result, render
    python scripts/demo/record_term.py          # re-render the saved results only (no database, no network)

Rendering uses the CLI's own Rich renderer (racinglines/cli/rich_view.py) into racinglines/web/term/<id>.html, an HTML
fragment the page includes as is. --run needs whatever the command needs (the hosted server's token for --demo).
"""

import argparse
import io
import json
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import MONOKAI

from racinglines.cli import rich_view

TERM = Path(__file__).resolve().parents[2] / "racinglines" / "web" / "term"
WIDTH = 120     # terminal columns of a recording; the page scrolls sideways on a phone
FORMAT = '<pre class="term-out">{code}</pre>'


def demos():
    return tomllib.loads((TERM / "demos.toml").read_text())["demo"]


def render(d):
    """A demo's saved result rendered by rich_view -> the HTML fragment."""
    out = json.loads((TERM / d["result"]).read_text())
    console = Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor", file=io.StringIO())
    rich_view.render(d["render"], out, console=console)
    return console.export_html(theme=MONOKAI, inline_styles=True, code_format=FORMAT)


def run(d):
    """Execute the demo's command with --json and save what it prints as its result."""
    p = subprocess.run([sys.executable, "-m", *d["run"], "--json"] if d["run"][0] == "racinglines" else [*d["run"], "--json"],
                       capture_output=True, text=True, check=True)
    json.loads(p.stdout)                                    # refuse to save anything but a result
    (TERM / d["result"]).write_text(p.stdout)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="re-run each command first (needs its database or token)")
    args = ap.parse_args(argv)
    for d in demos():
        if args.run:
            print(f"{d['id']}: ran at {run(d)}; update `recorded` in demos.toml", flush=True)
        (TERM / f"{d['id']}.html").write_text(render(d))
        print(f"{d['id']}: rendered {TERM / (d['id'] + '.html')}", flush=True)


if __name__ == "__main__":
    main()
