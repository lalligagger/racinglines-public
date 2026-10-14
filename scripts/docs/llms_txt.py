"""
llms_txt.py: an mkdocs hook (mkdocs.yml `hooks:`) that makes the docs readable by AI tools, per the llmstxt.org
convention, at build time:

    site/llms.txt        H1, a one-paragraph summary, a line naming the full text, then one "## <nav section>" per
                         nav section with "- [Title](url): description" per page (the description is the page's
                         first paragraph, shortened)
    site/llms-full.txt   every page's Markdown source in nav order, each under its title and URL, with captured
                         examples (--8<-- "examples/<id>.md") expanded
    site/<page>/index.md each page's Markdown source next to its HTML (/docs/<page>/index.md serves it raw)

Only pages in the nav go in, and never one under an excluded folder (extra.llms.exclude, default internal/: the
admin-only book). Page links point at the public GitHub source (extra.llms.source_url), since /docs needs a sign-in;
the web app serves /llms.txt and /llms-full.txt from site/ (racinglines/web/info_routes.py). Secrets-shaped text
(private keys, API tokens, key=value credentials) is replaced with [redacted] and the build logs a warning naming
the page. Top-level pages that sit outside any nav section are listed together under extra.llms.top_section.

Standard library and mkdocs only: no third-party plugin.
"""

import logging
import re
from pathlib import Path

log = logging.getLogger("mkdocs.hooks.llms_txt")

_nav = None

SECRETS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\brl_[A-Za-z0-9_-]{20,}"),                     # racinglines MCP tokens
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"),            # API keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),                # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),              # Slack tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                        # AWS access keys
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[=:]\s*[\"']?(?!\$|<|\{)[A-Za-z0-9/+_.=-]{20,}"),
]
SNIPPET = re.compile(r'^(?P<indent>[ \t]*)-{1,}8<-{1,}[ \t]+"(?P<path>[^"]+?)(?::(?P<section>[\w-]+))?"[ \t]*$', re.M)
COMMENT = re.compile(r"<!--.*?-->", re.S)


def _cfg(config):
    o = (config.get("extra") or {}).get("llms") or {}
    return dict(
        site_url=o.get("site_url", "https://racinglines.bet/docs/"),
        source_url=o.get("source_url", "https://github.com/lalligagger/racinglines-public/blob/main/docs/"),
        full_url=o.get("full_url", "https://racinglines.bet/llms-full.txt"),
        title=o.get("title", config.get("site_name")),
        summary=" ".join((o.get("summary") or config.get("site_description") or "").split()),
        top_section=o.get("top_section", "Overview"),
        exclude=tuple(o.get("exclude", ["internal/"])),
    )


def on_nav(nav, config, files, **kwargs):
    global _nav
    _nav = nav
    return nav


def _pages(items, section=None):
    """(section title or None, nav title, File) for every nav page in order; nested sections fold into their top
    section with their titles prefixed."""
    for it in items:
        if getattr(it, "is_section", False):
            for sec, title, f in _pages(it.children, it.title):
                yield (section or sec), (title if section is None else f"{it.title}: {title}"), f
        elif getattr(it, "is_page", False):
            yield section, it.title, it.file


def _snippet(path, section, docs_dir, depth=0):
    p = Path(docs_dir) / path
    if not p.is_file() or depth > 3:
        return None
    text = p.read_text(encoding="utf-8")
    if section:
        m = re.search(rf"--8<-- \[start:{re.escape(section)}\][^\n]*\n(.*?)\n[^\n]*--8<-- \[end:{re.escape(section)}\]",
                      text, re.S)
        if not m:
            return None
        text = m.group(1)
    return _expand(text, docs_dir, depth + 1)


def _expand(md, docs_dir, depth=0):
    def sub(m):
        body = _snippet(m.group("path"), m.group("section"), docs_dir, depth)
        if body is None:
            return m.group(0)
        body = COMMENT.sub("", body).strip("\n")
        return "\n".join(m.group("indent") + ln if ln else ln for ln in body.splitlines())
    return SNIPPET.sub(sub, md)


def _redact(text, where):
    for pat in SECRETS:
        text, n = pat.subn("[redacted]", text)
        if n:
            log.warning(f"llms_txt: {n} secret-shaped string(s) redacted in {where}")
    return text


def _description(md, limit=220):
    """The first prose paragraph after the H1: no headings, comments, code, admonitions, tables, lists or images."""
    md = COMMENT.sub("", md)
    md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)
    para, fence = [], False
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            continue
        if not s:
            if para:
                break
            continue
        if s.startswith(("#", "!!!", "???", "|", "- ", "* ", "<", "![", "=== ", "--8<--", ">")) or re.match(r"\d+\. ", s):
            if para:
                break
            continue
        para.append(s)
    text = " ".join(para)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\*\*|__|(?<!\w)[*_](?!\s)|(?<!\s)[*_](?!\w)", "", text)
    text = " ".join(text.split())
    if len(text) > limit:
        cut = text[:limit]
        stop = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(": "))
        text = cut[:stop + 1] if stop > limit // 2 else cut.rsplit(" ", 1)[0] + " …"
    return text


def on_post_build(config, **kwargs):
    if _nav is None:
        return
    c = _cfg(config)
    site, docs_dir = Path(config["site_dir"]), config["docs_dir"]
    pages = [(sec, title, f) for sec, title, f in _pages(_nav.items)
             if not any(f.src_uri.startswith(x) for x in c["exclude"])]

    groups, order = {}, []
    for sec, title, f in pages:
        key = sec or c["top_section"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((title, f))
    if c["top_section"] in order:                       # the loose top-level pages lead
        order.remove(c["top_section"])
        order.insert(0, c["top_section"])

    idx = [f"# {c['title']}", "", f"> {c['summary']}", "",
           f"The full text of every page below, in this order, is at {c['full_url']}. Each link is the page's "
           f"Markdown source on GitHub; the rendered site is {c['site_url']} (sign-in required).", ""]
    full = [f"# {c['title']}", "", f"> {c['summary']}", ""]
    for key in order:
        idx += [f"## {key}", ""]
        for title, f in groups[key]:
            src = Path(f.abs_src_path).read_text(encoding="utf-8")
            src = _redact(_expand(src, docs_dir), f.src_uri)
            url = c["source_url"] + f.src_uri
            desc = _description(src)
            idx.append(f"- [{title}]({url})" + (f": {desc}" if desc else ""))
            full += ["", "---", "", f"<!-- page: {title} · section: {key} · source: {url} · "
                                    f"site: {c['site_url']}{f.url} -->", "", src.strip(), ""]
            out = site / (f.dest_uri.rsplit("/", 1)[0] if "/" in f.dest_uri else "") / (
                "index.md" if f.dest_uri.endswith("index.html") else Path(f.dest_uri).with_suffix(".md").name)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(src, encoding="utf-8")
        idx.append("")
    (site / "llms.txt").write_text("\n".join(idx).rstrip() + "\n", encoding="utf-8")
    (site / "llms-full.txt").write_text("\n".join(full).rstrip() + "\n", encoding="utf-8")
    log.info(f"llms_txt: llms.txt, llms-full.txt and {len(pages)} page sources written ({len(order)} sections)")
