"""Parse motorsport.com Le Mans / WEC result tables from saved HTML."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

SIMPLE_DATE_RE = re.compile(r"([A-Z][a-z]{2} \d{1,2}, \d{4})(?:\s+to\s+([A-Z][a-z]{2} \d{1,2}, \d{4}))?")
TIME_RE = re.compile(r"\b\d+:\d{2}'\d{2}\.\d+\b|\b\d{1,2}'\d{2}\.\d+\b|\b\d{1,2}:\d{2}\.\d+\b")


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _event(soup: BeautifulSoup) -> str:
    heading = soup.find("h1")
    if heading:
        return _text(heading)
    if soup.title:
        return soup.title.get_text(" ", strip=True).split("|", 1)[0].strip()
    return "Unknown event"


def _date(soup: BeautifulSoup) -> str | None:
    for text in soup.stripped_strings:
        match = SIMPLE_DATE_RE.search(text)
        if not match:
            continue
        chosen = match.group(2) or match.group(1)
        return datetime.strptime(chosen, "%b %d, %Y").date().isoformat()
    return None


def _team(td) -> str:
    return _text(td.select_one(".info > .name")) or _text(td.select_one(".name")) or _text(td)


def _drivers(td) -> str:
    names = [_text(node) for node in td.select(".name-short")]
    if not names:
        names = [_text(node) for node in td.select(".name")]
    seen = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return ", ".join(seen) if seen else _text(td)


def _time(td) -> str:
    raw = _text(td)
    matches = TIME_RE.findall(raw)
    return matches[-1] if matches else raw


def _int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _status(retirement_reason: str) -> str:
    reason = retirement_reason.strip()
    if not reason:
        return "OK"
    upper = reason.upper()
    if upper == "RETIREMENT":
        return "DNF"
    return upper if upper in {"DNF", "DNS", "DSQ"} else reason


def parse_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="ms-table--result")
    if table is None:
        raise ValueError("motorsport result table not found")
    event = _event(soup)
    date = _date(soup)
    rows = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 11:
            continue
        retirement_reason = _text(cells[9])
        rows.append({
            "event": event,
            "date": date,
            "position": _int(_text(cells[0])),
            "team": _team(cells[1]),
            "car_no": _int(_text(cells[2])),
            "drivers": _drivers(cells[3]),
            "car_model": _text(cells[4]),
            "laps": _int(_text(cells[5])),
            "time": _time(cells[6]),
            "interval": _text(cells[7]),
            "pit_stops": _int(_text(cells[8])),
            "retirement_reason": retirement_reason,
            "points": _int(_text(cells[10])),
            "status": _status(retirement_reason),
        })
    return rows


def parse_file(path: str | Path) -> list[dict]:
    return parse_html(Path(path).read_text(encoding="utf-8"))
