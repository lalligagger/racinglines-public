"""Fetch one motorsport.com Le Mans / WEC result page as raw HTML.

The motorsport.com Le Mans landing page currently redirects to WEC result pages, so callers pass the event URL
they want (for example the generic Le Mans results URL, or one event-specific WEC result URL) and this module
stores the final HTML under data/raw/lemans/.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from racinglines import paths
from racinglines.sources import http

OUT = paths.raw("lemans", "motorsport")
USER_AGENT = "Mozilla/5.0 (compatible; racinglines-probe/1.0)"


def client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": USER_AGENT})


def _slug(text: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def _event_name(final_url: str, html: str) -> str:
    parts = [p for p in urlsplit(final_url).path.split("/") if p]
    if len(parts) >= 4 and parts[1] == "results":
        series, year, slug = parts[0], parts[2], parts[3]
        return _slug(f"{series}-{year}-{slug}")
    soup = BeautifulSoup(html, "lxml")
    heading = soup.find("h1")
    if heading:
        return _slug(heading.get_text(" ", strip=True))
    title = soup.title.get_text(" ", strip=True) if soup.title else "lemans-results"
    return _slug(title.split("|", 1)[0])


def fetch(event_url: str, out_dir: Path | str = OUT, force: bool = False, c: httpx.Client | None = None) -> Path:
    """Download one result page and return the stored HTML path."""
    own = c is None
    c = c if c is not None else client()
    try:
        r = http.get(c, event_url)
        r.raise_for_status()
        path = Path(out_dir) / f"{_event_name(str(r.url), r.text)}.html"
        if path.exists() and not force:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(r.content)
        tmp.replace(path)
        return path
    finally:
        if own:
            c.close()
