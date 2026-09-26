#!/usr/bin/env python3
"""
build_readme.py — Fill README.md from tagged sections of the docs (docs/*.md).

The docs are the source of truth; README.md is partly generated from them.

Tag a section in any docs page. The markers are HTML comments (hidden by MkDocs
and GitHub), each on its own line; markers inside code blocks are ignored:

    <!-- readme: quickstart -->
    ...markdown...
    <!-- /readme -->

Pull it into README.md with an include block. Everything between the two
markers is replaced on every build, so edit the docs, not the README:

    <!-- include: quickstart -->
    <!-- /include -->

Include options (space-separated after the name):
    shift=N    demote headings by N levels (negative promotes), e.g.
               <!-- include: model-summary shift=1 -->

While copying, docs-only syntax is converted for GitHub:
  - relative links to other pages (todo.md#x) -> docs/todo.md#x
  - same-page anchors (#x)                    -> docs/<page>.md#x
  - MkDocs admonitions (!!! warning "Title")  -> blockquotes

Usage:
    python build_readme.py            # rewrite README.md
    python build_readme.py --check    # exit 1 if README.md is out of date (CI / pre-commit)
    python build_readme.py --list     # list tagged sections and where they're included
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
README = ROOT / "README.md"

OPEN_RE = re.compile(r"^\s*<!--\s*readme:\s*([\w-]+)\s*-->\s*$")
CLOSE_RE = re.compile(r"^\s*<!--\s*/readme\s*-->\s*$")
FENCE_PREFIXES = ("```", "~~~")
INCLUDE_RE = re.compile(
    r"(<!--\s*include:\s*([\w-]+)((?:\s+\w+=\S+)*)\s*-->)(.*?)(<!--\s*/include\s*-->)", re.S)
LINK_RE = re.compile(r"(\]\()([^)\s]+)(\))")
ADMONITION_RE = re.compile(r'^!!!\s+(\w+)(?:\s+"([^"]*)")?[ \t]*\n((?:(?:[ ]{4}.*)?\n)+)', re.M)
ICONS = {"warning": "⚠️", "danger": "⛔", "caution": "⚠️", "note": "ℹ️", "info": "ℹ️", "tip": "💡"}


def collect_sections():
    """{name: (page_path, markdown)} for every tagged section in docs/."""
    sections = {}
    for page in sorted(DOCS.rglob("*.md")):
        name, buf, in_code = None, [], False
        for line in page.read_text().split("\n"):
            is_fence = line.lstrip().startswith(FENCE_PREFIXES)
            if name is None:
                # markers inside code blocks are examples, not tags
                if is_fence:
                    in_code = not in_code
                elif not in_code and (m := OPEN_RE.match(line)):
                    name, buf = m.group(1), []
                continue
            if is_fence:
                in_code = not in_code
            if not in_code and CLOSE_RE.match(line):
                if name in sections:
                    raise SystemExit(f"Duplicate readme tag '{name}' in {page} and {sections[name][0]}")
                sections[name] = (page, "\n".join(buf) + "\n")
                name = None
                continue
            buf.append(line)
        if name is not None:
            raise SystemExit(f"Unclosed readme tag '{name}' in {page}")
    return sections


def rewrite_links(text, page):
    """Make docs-relative links work from the repo root (where README.md lives)."""
    page_rel = page.relative_to(ROOT).as_posix()

    def fix(m):
        target = m.group(2)
        if re.match(r"^[a-zA-Z][\w+.-]*:", target) or target.startswith("/"):
            return m.group(0)  # absolute URL or site-absolute path
        if target.startswith("#"):
            return f"{m.group(1)}{page_rel}{target}{m.group(3)}"
        path, _, anchor = target.partition("#")
        new = (page.parent / path).resolve().relative_to(ROOT).as_posix()
        return f"{m.group(1)}{new}{'#' + anchor if anchor else ''}{m.group(3)}"

    return LINK_RE.sub(fix, text)


def convert_admonitions(text):
    """'!!! warning "Title"' + 4-space-indented body -> a GitHub blockquote."""
    def fix(m):
        kind, title, body = m.group(1).lower(), m.group(2), m.group(3)
        lines = [line[4:] if line.startswith("    ") else line for line in body.rstrip("\n").split("\n")]
        head = " ".join(p for p in (ICONS.get(kind, ""), f"**{title or kind.capitalize()}**") if p)
        out = "\n".join([f"> {head}", ">"] + [f"> {line}".rstrip() for line in lines]) + "\n"
        return out + ("\n" if body.endswith("\n\n") else "")

    return ADMONITION_RE.sub(fix, text)


def shift_headings(text, n):
    if not n:
        return text
    out, in_code = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{1,6})(\s.*)$", line)
        if m:
            line = "#" * min(6, max(1, len(m.group(1)) + n)) + m.group(2)
        out.append(line)
    return "\n".join(out)


def build(readme_text, sections):
    missing = []

    def fill(m):
        name = m.group(2)
        opts = dict(opt.split("=", 1) for opt in m.group(3).split())
        if name not in sections:
            missing.append(name)
            return m.group(0)
        page, body = sections[name]
        body = convert_admonitions(rewrite_links(body, page))
        body = shift_headings(body, int(opts.get("shift", 0)))
        src = page.relative_to(ROOT).as_posix()
        return (f"{m.group(1)}\n<!-- generated from {src} by build_readme.py - edit it there -->\n\n"
                f"{body.strip()}\n\n{m.group(5)}")

    out = INCLUDE_RE.sub(fill, readme_text)
    if missing:
        raise SystemExit(f"README includes unknown section(s): {', '.join(missing)}. "
                         f"Known: {', '.join(sorted(sections))}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="Exit 1 if README.md is out of date; don't write.")
    ap.add_argument("--list", action="store_true", help="List tagged sections and exit.")
    args = ap.parse_args()

    sections = collect_sections()
    current = README.read_text()
    if args.list:
        used = {m.group(2) for m in INCLUDE_RE.finditer(current)}
        for name, (page, body) in sorted(sections.items()):
            flag = "included" if name in used else "not included"
            print(f"{name:<22} {page.relative_to(ROOT).as_posix():<22} {len(body.splitlines()):>3} lines  ({flag})")
        return

    new = build(current, sections)
    if args.check:
        if new != current:
            print("README.md is out of date; run: python build_readme.py", file=sys.stderr)
            sys.exit(1)
        print("README.md is up to date.")
        return
    if new != current:
        README.write_text(new)
        print("README.md updated.")
    else:
        print("README.md already up to date.")


if __name__ == "__main__":
    main()
