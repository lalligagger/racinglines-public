#!/usr/bin/env python3
"""
build_quickstart.py — Render the demo packs' quickstart steps into docs/quickstart.md, from each pack's manifest
(racinglines/demo/packs/<name>/pack.toml, [[quickstart]]). The manifest is the source of truth: the doc's generated
block, and the command list the web app's /term replay records (scripts/demo/record_term.py reads
racinglines/web/term/demos.toml), both come from it, so a new pack gets its quickstart for free.

A generated block in the doc, replaced on every build:

    <!-- quickstart: kart -->
    <!-- /quickstart -->

Usage:
    python3 scripts/build_quickstart.py              # rewrite docs/quickstart.md's blocks
    python3 scripts/build_quickstart.py --check      # exit 1 if a block is out of date (tests/test_demo_store.py)
    python3 scripts/build_quickstart.py --commands kart   # the pack's commands, one per line (for demos.toml)
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DOC = ROOT / "docs" / "quickstart.md"
BLOCK = re.compile(r"(<!--\s*quickstart:\s*([\w-]+)\s*-->\n)(.*?)(<!--\s*/quickstart\s*-->)", re.S)


def render(pack):
    """The Markdown of one pack's quickstart: a numbered step per [[quickstart]] entry, each with its command."""
    out = []
    for i, step in enumerate(pack.quickstart, 1):
        out += [f"**{i}. {step['title']}.** {step.get('about', '')}".rstrip(), "",
                "```", "# LOCAL (Mac), or any machine with Postgres", step["run"], "```", ""]
    return "\n".join(out)


def build(text):
    from racinglines.demo import store

    def sub(m):
        pack = store.find(m.group(2))
        if pack is None:
            raise SystemExit(f"{DOC.name}: no demo pack {m.group(2)!r}")
        return m.group(1) + "\n" + render(pack) + m.group(4)
    return BLOCK.sub(sub, text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--commands", metavar="PACK")
    args = ap.parse_args(argv)
    if args.commands:
        from racinglines.demo import store
        print("\n".join(s["run"] for s in store.find(args.commands).quickstart))
        return 0
    old = DOC.read_text()
    new = build(old)
    if args.check:
        if new != old:
            print(f"{DOC.relative_to(ROOT)} is out of date: python3 scripts/build_quickstart.py", file=sys.stderr)
            return 1
        return 0
    DOC.write_text(new)
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
