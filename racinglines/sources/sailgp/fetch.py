"""
Download one SailGP championship page from Wikipedia and store the raw HTML at
data/raw/sailgp/<page_title>.html.

The source is the season article itself, for example:

    https://en.wikipedia.org/wiki/2024–25_SailGP_championship

Requests go through racinglines.sources.http so Wikipedia requests share the
repo-wide 1.0 second host pacing.
"""

from pathlib import Path
from urllib.parse import quote

import httpx

from racinglines import paths
from racinglines.sources import http

BASE = "https://en.wikipedia.org/wiki/"
OUT = paths.DATA / "raw" / "sailgp"
USER_AGENT = "Mozilla/5.0 (compatible; racinglines-probe/1.0)"


def page_path(page_title: str) -> Path:
    return OUT / f"{page_title}.html"


def page_url(page_title: str) -> str:
    return BASE + quote(page_title.replace(" ", "_"), safe="()'_,:-")


def fetch_page(page_title: str, force: bool = False, session: httpx.Client | None = None) -> Path:
    """Download `page_title` unless it is already on disk, and return the stored path."""
    path = page_path(page_title)
    if path.exists() and not force:
        return path
    own = session is None
    session = session or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
    try:
        resp = http.get(session, page_url(page_title))
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(resp.content)
        tmp.replace(path)
    finally:
        if own:
            session.close()
    return path
