"""Parse one saved IndyCar Wikipedia race page into row dicts."""

from __future__ import annotations

from datetime import datetime
from io import StringIO
from pathlib import Path
import re

import pandas as pd
from bs4 import BeautifulSoup

DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2},\s*\d{4})")

COLUMN_ALIASES = {
    "pos": "position",
    "pos.": "position",
    "position": "position",
    "driver": "competitor",
    "no.": "no",
    "no": "no",
    "team": "team",
    "engine": "engine",
    "laps": "laps",
    "time/retired": "time_retired",
    "pit stops": "pit_stops",
    "pitstops": "pit_stops",
    "grid": "grid",
    "laps led": "laps_led",
    "pts.": "points",
    "pts": "points",
    "points": "points",
}

TABLE_COLUMNS = (
    "position",
    "competitor",
    "status",
    "no",
    "team",
    "engine",
    "laps",
    "time_retired",
    "pit_stops",
    "grid",
    "laps_led",
    "points",
)


def _normalize(text) -> str:
    return " ".join(str(text).replace("\xa0", " ").split()).strip()


def _normalize_col(col) -> str:
    return _normalize(col).lower()


def _int(value) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = _normalize(value)
    if not text or text == "-":
        return None
    digits = re.sub(r"[^\d-]", "", text)
    if digits in {"", "-"}:
        return None
    return int(digits)


def _text(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = _normalize(value)
    return text or None


def _date(soup: BeautifulSoup) -> str | None:
    for text in soup.stripped_strings:
        match = DATE_RE.search(text)
        if match:
            return datetime.strptime(match.group(1).replace("  ", " "), "%B %d, %Y").date().isoformat()
    return None


def _table_score(cols: list[str]) -> tuple[int, int]:
    mapped = {_normalize_col(COLUMN_ALIASES.get(c, c)) for c in cols}
    score = 0
    if "position" in mapped:
        score += 2
    if "competitor" in mapped:
        score += 4
    if "points" in mapped:
        score += 3
    if "time_retired" in mapped:
        score += 3
    score += sum(1 for c in ("no", "team", "engine", "laps", "pit_stops", "grid", "laps_led") if c in mapped)
    return score, len(mapped)


def _map_columns(df: pd.DataFrame) -> pd.DataFrame:
    renames = {}
    for col in df.columns:
        key = _normalize_col(col)
        if key in COLUMN_ALIASES:
            renames[col] = COLUMN_ALIASES[key]
    return df.rename(columns=renames)


def _result_table(soup: BeautifulSoup) -> pd.DataFrame:
    best = None
    for table in soup.find_all("table"):
        try:
            df = pd.read_html(StringIO(str(table)))[0]
        except ValueError:
            continue
        df = _map_columns(df)
        score = _table_score([str(c) for c in df.columns])
        if "position" not in df.columns or "competitor" not in df.columns or "points" not in df.columns:
            continue
        if best is None or score > best[0]:
            best = (score, df)
    if best is None:
        raise ValueError("IndyCar result table not found")
    return best[1]


def _status(time_retired: str | None) -> str:
    if not time_retired:
        return "OK"
    upper = time_retired.upper()
    if upper in {"DNF", "DNS", "DSQ"}:
        return upper
    if re.fullmatch(r"\d+:\d{2}:\d{2}(?:\.\d+)?", time_retired) or re.fullmatch(r"\d+:\d{2}(?:\.\d+)?", time_retired):
        return "OK"
    return time_retired


def parse_html(html: str, event: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    date = _date(soup)
    df = _result_table(soup)
    rows = []
    for _, row in df.iterrows():
        position = _int(row.get("position"))
        competitor = _text(row.get("competitor"))
        if position is None or not competitor:
            continue
        time_retired = _text(row.get("time_retired"))
        rows.append({
            "event": event,
            "date": date,
            "position": position,
            "competitor": competitor,
            "status": _status(time_retired),
            "no": _int(row.get("no")),
            "team": _text(row.get("team")),
            "engine": _text(row.get("engine")),
            "laps": _int(row.get("laps")),
            "time_retired": time_retired,
            "pit_stops": _int(row.get("pit_stops")),
            "grid": _int(row.get("grid")),
            "laps_led": _int(row.get("laps_led")),
            "points": _int(row.get("points")),
        })
    return rows


def parse_file(path: str | Path) -> list[dict]:
    file_path = Path(path)
    return parse_html(file_path.read_text(encoding="utf-8"), event=file_path.stem)
