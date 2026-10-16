"""Turning tool payloads into rows and Rich cells, with the app's colour language.

Colour carries meaning and nothing else, borrowed from a timing screen:
  green  = in our favour (model above market, profit)
  red    = against us (model below market, loss)
  purple = the best on the board (top probability, rank 1)
  amber  = stale or needs attention
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from rich.text import Text

GREEN = "#3fcf73"
RED = "#ff5f57"
PURPLE = "#b48cff"
AMBER = "#f0b429"
DIM = "#7d8590"

PROB_COLS = re.compile(
    r"(^|_)(prob|fair|mid|bid|ask|price|implied|model|market|vwap|last|p_yes|yes|no)$|_prob$|^fair_|_fair$"
)
SIGNED_POINTS = re.compile(r"(^|_)(gap|edge|lift|diff|disagree)($|_)")
MONEY = re.compile(r"(^|_)(pnl|p&l|profit|payout|cost|cash|total|worth|value|fees?|stake|volume|ev|balance|grant)($|_)")
IDS = re.compile(r"(^|_)id$|_ids?$|^season$|^year$|^round$|token")


# Knob names whose values are settings, never data to colour (see list_job_types sweep_settings).
SETTING_NAMES = {"stake_per_edge", "cost", "thin_edge_mult", "bankroll", "kelly", "half_spread", "size", "skew",
                 "info_skew", "widen", "coherence_tol", "taker_fee", "half_life", "half_life_days", "ridge_team",
                 "ridge_slope", "driver_prior_n", "finish_rho_scale", "reset_weight", "noise", "uncertainty"}


def plain(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def setting_value(value: Any) -> Text | str:
    """A configuration value as written: lists joined, maps as k=v, nothing coloured."""
    if value is None:
        return Text("default", style=DIM)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(map(str, value))
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return plain(value)


@dataclass
class Table:
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int | None = None
    offset: int = 0
    next_offset: int | None = None
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def is_table(value: Any) -> bool:
    if isinstance(value, dict) and "rows" in value and isinstance(value["rows"], list):
        return True
    return isinstance(value, list) and bool(value) and all(isinstance(r, dict) for r in value)


def to_table(value: Any) -> Table:
    """{"columns","rows",...} or [dict, ...] -> Table. Anything else -> empty Table."""
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        rows = value["rows"]
        cols = list(value.get("columns") or [])
        if rows and not isinstance(rows[0], dict):  # rows as lists
            rows = [dict(zip(cols, r)) for r in rows]
        if not cols:
            cols = _union_keys(rows)
        return Table(
            cols, rows, value.get("total"), value.get("offset") or 0, value.get("next_offset"),
            value.get("note") or "",
            {k: v for k, v in value.items() if k not in {"columns", "rows", "total", "offset", "limit",
                                                       "truncated", "next_offset", "note"}},
        )
    if isinstance(value, list) and all(isinstance(r, dict) for r in value):
        return Table(_union_keys(value), value, len(value))
    return Table([], [])


def _union_keys(rows: Iterable[dict]) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows:
        for key in row:
            seen.setdefault(key, None)
    return list(seen)


def first_table(payload: Any, *keys: str) -> Table:
    """The first table found under any of `keys` (dotted paths allowed), else in the payload."""
    for key in keys:
        node = dig(payload, key)
        if is_table(node):
            return to_table(node)
    if is_table(payload):
        return to_table(payload)
    if isinstance(payload, dict):
        for value in payload.values():
            if is_table(value):
                return to_table(value)
    return Table([], [])


def dig(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def label(col: str) -> str:
    return col.replace("_", " ")


def cell(col: str, value: Any) -> Text | str:
    """One value -> a Rich cell, formatted by what its column means."""
    c = col.lower()
    if value is None or value == "":
        return Text("–", style=DIM)
    if isinstance(value, bool):
        return Text("yes" if value else "no", style=None if value else DIM)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if IDS.search(c):
            return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
        if c.startswith(("min_", "max_")) or c in SETTING_NAMES:
            return plain(value)  # a threshold or knob, not a measured edge/price/amount
        if c in ("time_s", "time") or c.endswith("_time_s"):
            return race_time(float(value))
        if c == "roi":
            return Text(f"{value * 100:+.0f}%", style=GREEN if value > 0 else RED if value < 0 else DIM)
        if c == "position" and isinstance(value, float) and value.is_integer():
            return Text(f"{int(value)}", style=PURPLE if value == 1 else None)
        if SIGNED_POINTS.search(c):
            return signed_points(value)
        if MONEY.search(c) and isinstance(value, float):
            return money(value, signed=bool(re.search(r"pnl|profit|p&l|ev", c)))
        if PROB_COLS.search(c) and isinstance(value, float) and 0 <= value <= 1:
            return Text(f"{value * 100:.1f}%")
        if isinstance(value, float):
            return Text(f"{value:,.4g}" if abs(value) < 1e6 else f"{value:,.0f}")
        return str(value)
    if c == "status" and isinstance(value, str):
        style = {"done": GREEN, "failed": RED, "running": PURPLE, "queued": AMBER, "DNF": AMBER,
                 "DNS": DIM, "DSQ": RED, "alerted": PURPLE, "expired": DIM, "filled_paper": GREEN}.get(value)
        return Text(value, style=style) if style else value
    if isinstance(value, (dict, list)):
        text = json.dumps(value, separators=(",", ":"), default=str)
        return Text(text if len(text) <= 48 else text[:47] + "…", style=DIM)
    text = str(value)
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text):
        return text[:16].replace("T", " ")
    return text if len(text) <= 64 else text[:63] + "…"


def race_time(seconds: float) -> str:
    """6120.785 -> 1:42:00.785; 91.373 -> 1:31.373."""
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}:{minutes:02d}:{sec:06.3f}" if hours else f"{minutes}:{sec:06.3f}"


def signed_points(value: float) -> Text:
    """A probability gap in percentage points, green when it favours us."""
    pts = value * 100
    style = GREEN if pts > 0.05 else RED if pts < -0.05 else DIM
    return Text(f"{pts:+.1f}", style=style)


def money(value: float, signed: bool = False, prefix: str = "") -> Text:
    if signed:
        style = GREEN if value > 0.005 else RED if value < -0.005 else DIM
        return Text(f"{prefix}{value:+,.2f}", style=style)
    return Text(f"{prefix}{value:,.2f}")


def pct(value: Any, digits: int = 1) -> Text:
    if value is None:
        return Text("–", style=DIM)
    return Text(f"{float(value) * 100:.{digits}f}%")


def prob_bar(value: Any, width: int = 12, best: bool = False) -> Text:
    """A horizontal bar for a probability, eighth-block resolution."""
    if value is None:
        return Text("–", style=DIM)
    v = max(0.0, min(1.0, float(value)))
    eighths = round(v * width * 8)
    full, rem = divmod(eighths, 8)
    bar = "█" * full + ("" if rem == 0 else " ▏▎▍▌▋▊▉"[rem])
    text = Text(bar.ljust(width), style=PURPLE if best else "#8fa3bf")
    text.append(f" {v * 100:5.1f}%", style="bold" if best else "")
    return text


def gap_bar(gap: Any, half: int = 7, scale: float = 0.25) -> Text:
    """Fair minus market as a diverging bar around a centre line.

    Left and red: the market prices it higher than we do. Right and green: we price it higher.
    Full width is `scale` (25 points).
    """
    if gap is None:
        return Text(" " * half + "┆" + " " * half, style=DIM)
    g = max(-scale, min(scale, float(gap)))
    n = round(abs(g) / scale * half)
    left = ("█" * n).rjust(half) if g < 0 else " " * half
    right = ("█" * n).ljust(half) if g > 0 else " " * half
    text = Text()
    text.append(left, style=RED)
    text.append("┆", style=DIM)
    text.append(right, style=GREEN)
    return text


def stale(flag: Any, reason: str | None = None) -> Text:
    if flag:
        return Text(f"stale{': ' + reason if reason else ''}", style=AMBER)
    return Text("fresh", style=GREEN)
