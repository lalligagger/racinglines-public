"""
Record the public /term page: the demo pack's quickstart, run and replayed (racinglines/web/term/demos.toml,
docs/webapp.md, Pages: Quickstart replay).

    python scripts/demo/record_term.py --run    # run the quickstart's commands, save what they printed, render
    python scripts/demo/record_term.py          # re-render the saved output only (nothing runs)
    python scripts/demo/record_term.py --run --part f1-singapore --out DIR   # record one extra part (on the VM)

The commands come from the pack's manifest (racinglines/demo/packs/<pack>/pack.toml, [[quickstart]]), the same list
docs/quickstart.md is built from (scripts/build_quickstart.py). --run snapshots that list into
racinglines/web/term/quickstart.json, then runs each command as a user would type it, in colour with Rich's animations
off (the final frame of each progress bar or live table), and saves what it printed (stdout and stderr, as a terminal
shows them) as racinglines/web/term/<id>.ansi. Absolute paths of this checkout, $HOME and the temp folder are cut, so
paths read relative to the repo. For a true first run, drop the demo store first (its database and data/demo/<pack>/).
--run needs a configured database (DATABASE_URL, e.g. a local Postgres): the commands run with no terminal, so a
first-run prompt can't ask. Nothing saved changes unless every command succeeds.
A part's step may set `group` and `optional = true`: when an optional step fails, it and every later step of its group
are left out of the recording (e.g. a replay that makes no trades on one exchange) instead of failing the run.
Extra parts (demos.toml `parts`) are steps files next to it, racinglines/web/term/<part>.toml, with [[steps]] like the
pack's [[quickstart]]; they follow the pack's steps on the page. `--run --part NAME` records one of them instead of the
pack: its steps run one after another in one fresh folder (so a file one step writes is there for the next) and save
<part>.json and <part>-<n>.ansi. With --out the recording goes to that folder instead of the checkout (the VM's
checkout is never edited: scripts/vm/record_term_f1.sh); copy those files into racinglines/web/term/ and render.
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
    f = TERM / "demos.toml"
    return tomllib.loads(f.read_text()) if f.is_file() else {}


def demos():
    """The recorded steps: [{id, title, command, about}], snapshotted from the pack's quickstart (and each extra part's
    steps file) by --run."""
    out = []
    for name in ["quickstart", *config().get("parts", [])]:
        f = TERM / f"{name}.json"
        out += json.loads(f.read_text()) if f.is_file() else []
    return out


def quickstart(pack):
    """The pack's [[quickstart]] steps as the page lists them (needs the racinglines package with demo packs)."""
    from racinglines.demo import store
    found = store.find(pack)
    if found is None:
        sys.exit(f"no demo pack {pack!r} (racinglines/demo/packs/)")
    return [{"id": f"step-{i}", "title": s["title"], "command": s["run"], "about": s.get("about", ""),
             "record": s.get("record", True),
             **({"section": s["section"]} if s.get("section") else {})}      # the page's part headings
            for i, s in enumerate(found.quickstart, 1)]


def part(name):
    """An extra part's [[steps]] (racinglines/web/term/<name>.toml), as quickstart() lists the pack's."""
    if name not in config().get("parts", []):
        sys.exit(f"no part {name!r} in demos.toml `parts`")
    steps = tomllib.loads((TERM / f"{name}.toml").read_text())["steps"]
    return [{"id": f"{name}-{i}", "title": s["title"], "command": s["run"], "about": s.get("about", ""),
             "record": s.get("record", True), **({"section": s["section"]} if s.get("section") else {}),
             **{k: s[k] for k in ("group", "optional") if k in s}}
            for i, s in enumerate(steps, 1)]


def render(d):
    """A demo's saved terminal output (ANSI) -> the HTML fragment (empty for a step with `record = false`)."""
    if not d.get("record", True):
        return ""
    console = Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor", file=io.StringIO())
    ansi = OSC.sub("", (TERM / f"{d['id']}.ansi").read_text())
    console.print(Text.from_ansi(ansi), soft_wrap=True)
    return console.export_html(theme=MONOKAI, inline_styles=True, code_format=FORMAT)


class Skipped(Exception):
    """An `optional` step failed: it and the rest of its `group` are left out of the recording."""


def run(d, cwd=None):
    """Execute the step's command (in `cwd`, default here) and return what it printed."""
    argv = shlex.split(d["command"])
    argv = [sys.executable, "-m", *argv] if argv[0] == "racinglines" else argv
    env = dict(os.environ, COLUMNS=str(WIDTH), FORCE_COLOR="1", TTY_INTERACTIVE="0", PYTHONUNBUFFERED="1",
               RACINGLINES_PROGRESS_SEC="0")    # no heartbeat lines in a recording (the VM script beats instead)
    try:
        out = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True, env=env,
                             cwd=cwd).stdout
    except subprocess.CalledProcessError as e:
        if d.get("optional"):
            print(f"{d['id']}: optional step failed (exit {e.returncode}), left out with the rest of group "
                  f"{d.get('group')!r}:\n{e.stdout}", flush=True)
            raise Skipped(d.get("group")) from None
        hint = "" if os.environ.get("DATABASE_URL") else "\n(DATABASE_URL is not set: the recorder needs a configured database)"
        sys.exit(f"{d['id']}: `{d['command']}` failed (exit {e.returncode}); nothing saved changed:\n{e.stdout}{hint}")
    roots = {str(ROOT), os.getcwd(), *([str(cwd)] if cwd else []), str(Path.home()), tempfile.gettempdir(),
             *filter(None, env.get("PYTHONPATH", "").split(os.pathsep))}
    for r in sorted(roots, key=len, reverse=True):
        out = out.replace(r.rstrip("/") + "/", "")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="re-run each command first")
    ap.add_argument("--part", default=None, help="with --run: record this extra part (demos.toml `parts`), not the pack")
    ap.add_argument("--out", default=None, help="with --run: save the recording in this folder, not the checkout "
                                                "(nothing is rendered)")
    args = ap.parse_args(argv)
    if (args.part or args.out) and not args.run:
        sys.exit("--part and --out go with --run")
    if args.run:
        name = args.part or "quickstart"
        steps = part(args.part) if args.part else quickstart(config().get("pack", "kart"))
        dest = Path(args.out) if args.out else TERM
        dest.mkdir(parents=True, exist_ok=True)
        work = tempfile.mkdtemp(prefix="term-") if args.part else None     # one folder for the whole part
        outs, dropped = {}, set()
        for d in steps:     # run them all first: a failure leaves the saved recording as it was
            if not d.get("record", True):                   # shown, never run: no .ansi, an empty fragment
                continue
            if d.get("group") is not None and d["group"] in dropped:
                continue
            try:
                outs[d["id"]] = run(d, cwd=work)
            except Skipped as e:
                dropped.add(e.args[0])
                continue
            print(f"{d['id']}: ran `{d['command']}`", flush=True)
        steps = [d for d in steps if d.get("group") is None or d["group"] not in dropped]
        if not steps:
            sys.exit("every step was left out (optional groups that failed): nothing saved changed")
        for old in dest.glob(f"{args.part}-*.*" if args.part else "step-*.*"):
            old.unlink()
        for k, out in outs.items():
            (dest / f"{k}.ansi").write_text(out)
        (dest / f"{name}.json").write_text(json.dumps(steps, indent=2) + "\n")
        print(f"all steps ran; saved in {dest}" + ("" if args.out else "; update `recorded` in demos.toml"), flush=True)
        if args.out:
            return
    for d in demos():
        (TERM / f"{d['id']}.html").write_text(render(d))
        print(f"{d['id']}: rendered {TERM / (d['id'] + '.html')}", flush=True)


if __name__ == "__main__":
    main()
