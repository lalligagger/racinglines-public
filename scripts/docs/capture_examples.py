#!/usr/bin/env python3
"""
capture_examples.py: run the docs' example commands for real and save each command with its exact output, so a page
shows what the command prints instead of a hand-typed copy (docs/examples/<id>.md, embedded with pymdownx.snippets).

The manifest is scripts/docs/examples.toml:

    [setup]                         # optional
    fresh_demo = ["kart"]           # drop these packs' demo stores first (database racinglines_demo_<pack> and
                                    # data/demo/<pack>), so the first --demo example shows the build and every run
                                    # number is the same on every capture; --keep-demo skips it

    [defaults]                      # optional, applied to every entry
    env = { NO_COLOR = "1" }        # extra environment (merged over os.environ, then the entry's env)
    timeout = 900                   # seconds

    [[example]]
    id = "db-stats-demo"            # -> docs/examples/db-stats-demo.md
    command = "racinglines db stats --demo"   # split with shlex and run without a shell
    env = { COLUMNS = "100" }       # optional
    cwd = "."                       # optional, relative to the repo root (the default)
    timeout = 300                   # optional
    head = 40                       # optional: keep only the first N lines of output ...
    tail = 10                       # optional: ... and/or the last N; the file states how many lines were cut
    lang = "text"                   # optional: the output block's highlight language (default text)

Each file is the command in a ```bash block titled "Command" and stdout+stderr (interleaved as a terminal shows them)
in a block titled "Output", between snippet section markers, so a page can embed the pair or either half:

    --8<-- "examples/db-stats-demo.md"            the command block, then the output block
    --8<-- "examples/db-stats-demo.md:command"    only the command
    --8<-- "examples/db-stats-demo.md:output"     only the output

The output is byte-for-byte what the command printed, with four stated exceptions: trailing spaces on each line and
blank lines before and after the output are dropped (Rich pads its tables to the terminal width), any ANSI escape codes are removed (the defaults ask for none:
NO_COLOR=1), and a `head`/`tail` cut is replaced by one "… N lines cut …" line. A command that exits non-zero or times
out writes nothing (its old file, if any, stays) and is reported; the script then exits 1.

A comment at the top of each file records when it was captured, the git commit (+dirty when the tree had changes), the
elapsed time and the exit code. Progress: one line per command as it starts and ends, and a heartbeat every minute
while one runs (owner rule: long jobs print progress at least every 5 minutes).

    python scripts/docs/capture_examples.py                 # every example
    python scripts/docs/capture_examples.py db-stats-demo   # only these ids
    python scripts/docs/capture_examples.py --list
    python scripts/docs/capture_examples.py --keep-demo book-price-demo   # one example on the existing demo store
"""

import argparse
import datetime as dt
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts" / "docs" / "examples.toml"
OUT = ROOT / "docs" / "examples"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)")
HEARTBEAT_SEC = 60


def log(msg):
    print(f"[capture {dt.datetime.now(dt.timezone.utc):%H:%M:%S}] {msg}", flush=True)


def git_commit():
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def fence(text):
    """A backtick fence longer than any backtick run in the text."""
    runs = [len(m) for m in re.findall(r"`+", text)]
    return "`" * max(3, max(runs, default=0) + 1)


def trim(lines, head, tail):
    """(kept lines, number cut): the first `head` and last `tail` lines with one marker between, when that cuts any."""
    n = len(lines)
    head, tail = head or 0, tail or 0
    if not (head or tail) or n <= head + tail:
        return lines, 0
    cut = n - head - tail
    what = " and ".join(s for s in (head and f"first {head}", tail and f"last {tail}") if s)
    marker = f"… {cut} lines cut (showing the {what} of {n}) …"
    return lines[:head] + [marker] + (lines[n - tail:] if tail else []), cut


def render(ex, output, meta):
    lines = [ln.rstrip() for ln in output.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    kept, cut = trim(lines, ex.get("head"), ex.get("tail"))
    body = "\n".join(kept)
    cmd = ex["command"]
    fc, fo = fence(cmd), fence(body)
    note = f" {cut} of {len(lines)} output lines cut (head={ex.get('head') or 0}, tail={ex.get('tail') or 0})." if cut else ""
    header = (f"<!-- Captured by scripts/docs/capture_examples.py (id {ex['id']}, scripts/docs/examples.toml) on "
              f"{meta['when']}, commit {meta['commit']}, {meta['elapsed']:.1f} s, exit {meta['rc']}. "
              f"Output as printed: trailing spaces dropped, {meta['ansi']} ANSI escape codes removed.{note} "
              f"Do not edit: re-run the script. -->")
    return (f"{header}\n\n"
            f"<!-- --8<-- [start:command] -->\n"
            f'{fc}bash title="Command"\n{cmd}\n{fc}\n'
            f"<!-- --8<-- [end:command] -->\n\n"
            f"<!-- --8<-- [start:output] -->\n"
            f'{fo}{ex.get("lang", "text")} title="Output"\n{body}\n{fo}\n'
            f"<!-- --8<-- [end:output] -->\n")


def run_one(ex, defaults, i, n):
    env = dict(os.environ)
    env.update({k: str(v) for k, v in defaults.get("env", {}).items()})
    env.update({k: str(v) for k, v in ex.get("env", {}).items()})
    cwd = ROOT / ex.get("cwd", ".")
    timeout = ex.get("timeout", defaults.get("timeout", 900))
    log(f"{i}/{n} {ex['id']}: $ {ex['command']}")
    t0 = time.monotonic()
    done = threading.Event()

    def beat():
        while not done.wait(HEARTBEAT_SEC):
            log(f"{i}/{n} {ex['id']}: still running, {(time.monotonic() - t0) / 60:.0f} min elapsed "
                f"(timeout {timeout // 60} min)")

    threading.Thread(target=beat, daemon=True).start()
    try:
        p = subprocess.run(shlex.split(ex["command"]), cwd=cwd, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout)
        rc, raw = p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        rc, raw = f"timeout after {timeout} s", e.stdout or b""
    except OSError as e:
        rc, raw = f"could not start: {e}", b""
    finally:
        done.set()
    elapsed = time.monotonic() - t0
    text = raw.decode("utf-8", errors="replace")
    if rc != 0:
        last = "\n".join(text.strip().splitlines()[-8:])
        log(f"{i}/{n} {ex['id']}: FAILED ({rc}, {elapsed:.1f} s); nothing written. Last lines:\n{last}")
        return False
    ansi = len(ANSI.findall(text))
    text = ANSI.sub("", text)
    meta = dict(when=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), commit=git_commit(),
                elapsed=elapsed, rc=rc, ansi=ansi)
    out = OUT / f"{ex['id']}.md"
    out.write_text(render(ex, text, meta), encoding="utf-8")
    log(f"{i}/{n} {ex['id']}: ok, {elapsed:.1f} s, {len(text.splitlines())} lines -> {out.relative_to(ROOT)}")
    return True


def fresh_demo(pack, env):
    """Drop one pack's demo store: its database (only a name with "demo" in it) and its data folder (only a path
    with "demo" in it). The next --demo command rebuilds it from the pack, as a first-time reader sees it."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    if not re.fullmatch(r"[a-z0-9_]+", pack):
        sys.exit(f"fresh_demo: bad pack name {pack!r}")
    base = env.get("DATABASE_URL") or "postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines"
    name = env.get("RACINGLINES_DEMO_DATABASE_URL") and make_url(env["RACINGLINES_DEMO_DATABASE_URL"]).database \
        or f"racinglines_demo_{pack}"
    if "demo" not in name:
        sys.exit(f"fresh_demo: refusing to drop database {name!r} (no 'demo' in its name)")
    eng = create_engine(make_url(base).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    eng.dispose()
    data = Path(env.get("RACINGLINES_DEMO_DATA") or ROOT / "data" / "demo" / pack).resolve()
    if data.exists():
        if "demo" not in data.as_posix().lower():
            sys.exit(f"fresh_demo: refusing to remove {data} (no 'demo' in its path)")
        import shutil
        shutil.rmtree(data)
    log(f"fresh demo store: dropped database {name} and {data}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="only these example ids (default: all)")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--list", action="store_true", help="list the examples and exit")
    ap.add_argument("--keep-demo", action="store_true", help="reuse the demo stores instead of [setup] fresh_demo")
    a = ap.parse_args()
    m = tomllib.loads(a.manifest.read_text(encoding="utf-8"))
    defaults, examples = m.get("defaults", {}), m.get("example", [])
    ids = [e["id"] for e in examples]
    dupes = {x for x in ids if ids.count(x) > 1}
    if dupes:
        sys.exit(f"duplicate ids in {a.manifest}: {sorted(dupes)}")
    if a.list:
        for e in examples:
            print(f"{e['id']:<28} {e['command']}")
        return 0
    unknown = set(a.ids) - set(ids)
    if unknown:
        sys.exit(f"unknown ids: {sorted(unknown)}")
    todo = [e for e in examples if not a.ids or e["id"] in a.ids]
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    if not a.keep_demo:
        env = dict(os.environ, **{k: str(v) for k, v in defaults.get("env", {}).items()})
        for pack in m.get("setup", {}).get("fresh_demo", []):
            fresh_demo(pack, env)
    failed = [e["id"] for i, e in enumerate(todo, 1) if not run_one(e, defaults, i, len(todo))]
    log(f"done: {len(todo) - len(failed)} of {len(todo)} captured in {(time.monotonic() - t0) / 60:.1f} min"
        + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
