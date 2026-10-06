"""Fetch one IndyCar race page from Wikipedia's MediaWiki API as raw HTML."""

from __future__ import annotations

from pathlib import Path

import httpx

from racinglines import paths
from racinglines.sources import http

BASE = "https://en.wikipedia.org"
API_PATH = "/w/api.php"
OUT = paths.DATA / "raw" / "indycar"
USER_AGENT = "Mozilla/5.0 (compatible; racinglines-probe/1.0)"


def client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


def fetch(race_name: str, out_dir: Path | str = OUT, force: bool = False, c: httpx.Client | None = None) -> Path:
    """Download one race page and return the stored HTML path."""
    out_path = Path(out_dir) / f"{race_name}.html"
    if out_path.exists() and not force:
        return out_path
    own = c is None
    c = c if c is not None else client()
    try:
        r = http.get(c, API_PATH, params={
            "action": "parse",
            "page": race_name,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
        })
        r.raise_for_status()
        payload = r.json()
        html = ((payload or {}).get("parse") or {}).get("text")
        if not isinstance(html, str) or not html.strip():
            detail = ((payload or {}).get("error") or {}).get("info") or "missing parse.text"
            raise ValueError(f"Wikipedia parse API returned no HTML for {race_name}: {detail}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(html, encoding="utf-8")
        tmp.replace(out_path)
        return out_path
    finally:
        if own:
            c.close()
