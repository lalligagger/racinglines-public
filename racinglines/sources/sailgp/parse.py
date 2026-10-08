"""
Parse one saved SailGP Wikipedia championship page into tidy per-team event results.

The page carries one season-level events table plus one standings table for each
round. The standings tables list the team's overall event position and its race-
by-race placings within that round.
"""

from io import StringIO
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

ROUND_RE = re.compile(r"Round\s+(\d+):\s*(.+)")


def _normalize(text) -> str:
    return " ".join(str(text).replace("\xa0", " ").split()).strip()


def _normalize_key(text) -> str:
    return _normalize(text).lower()


def _event_name(title: str) -> str:
    name = _normalize(title)
    for sep in (" presented by ", " | "):
        if sep in name:
            name = name.split(sep, 1)[0]
    return name


def _parse_html_table(table_html: str) -> pd.DataFrame:
    return pd.read_html(StringIO(table_html))[0]


def _is_events_table(df: pd.DataFrame) -> bool:
    cols = [_normalize_key(c) for c in df.columns]
    return cols[:5] == ["rnd", "host", "title", "dates", "winning team"]


def _is_round_standings_table(df: pd.DataFrame) -> bool:
    cols = [_normalize_key(c) for c in df.columns]
    if len(cols) < 3 or cols[0] != "pos" or cols[1] != "team":
        return False
    return any(c.isdigit() for c in cols[2:])


def _round_heading(table) -> str | None:
    headings = [_normalize(h.get_text(" ", strip=True)) for h in table.find_all_previous(["h2", "h3", "h4"], limit=3)]
    if not headings:
        return None
    if ROUND_RE.match(headings[0]):
        return headings[0]
    if headings[0] in {"Results", "Penalties"} and len(headings) > 1 and ROUND_RE.match(headings[1]):
        return headings[1]
    return None


def _event_meta(events_df: pd.DataFrame) -> dict[int, dict]:
    out = {}
    for _, row in events_df.iterrows():
        try:
            rnd = int(row["Rnd"])
        except (TypeError, ValueError):
            continue
        out[rnd] = {
            "event_rnd": rnd,
            "event_name": _event_name(row["Title"]),
            "event_date": _normalize(row["Dates"]),
            "event_winner": _normalize(row["Winning team"]),
        }
    return out


def _cell_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, str):
        s = _normalize(value)
        if not s:
            return None
        if s.isdigit():
            return int(s)
        try:
            f = float(s)
        except ValueError:
            return s
        return int(f) if f.is_integer() else f
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def parse_html(html: str) -> list[dict]:
    """Per-team event results from one saved season page."""
    all_tables = pd.read_html(StringIO(html))
    events_df = next((df for df in all_tables if _is_events_table(df)), None)
    if events_df is None:
        raise ValueError("events table not found")
    events = _event_meta(events_df)
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for table in soup.select("table.wikitable"):
        df = _parse_html_table(str(table))
        if not _is_round_standings_table(df):
            continue
        heading = _round_heading(table)
        if not heading:
            continue
        match = ROUND_RE.match(heading)
        if not match:
            continue
        rnd = int(match.group(1))
        meta = events.get(rnd)
        if meta is None:
            continue
        race_cols = [str(c) for c in df.columns[2:]]
        for _, row in df.iterrows():
            team = _normalize(row["Team"])
            pos = _cell_value(row["Pos"])
            if not team or team.startswith("Citation:") or pos is None:
                continue
            result = {
                **meta,
                "team": team,
                "position_in_event": pos,
                "race_by_race_results": {col: _cell_value(row[col]) for col in race_cols},
                "status": "OK",
            }
            rows.append(result)
    return rows


def parse_file(path: str | Path) -> list[dict]:
    return parse_html(Path(path).read_text())
