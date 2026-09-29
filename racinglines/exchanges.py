"""
Exchange schemas: an exchange as data (exchanges/<code>.toml), the way sports are (sports/<code>.toml).

A venue with a plain JSON API is described by one file: its host and endpoints, where each field lives in a
response, its price units and fee, and how its markets map onto our prediction kinds per sport. One generic driver
(racinglines/markets/exchange_driver.py) reads it, so a new exchange is a new file, not new code. Polymarket and
Kalshi predate this and keep their own packages; they can move onto schemas later.

    load("og")        the parsed schema
    CODES             every exchange with a schema
    enabled("og")     whether its switch (an env var, off by default) is on
    sports("og")      the sports it lists (sports/<code>.toml codes)
    dig(obj, path)    obj["a"]["b"][0] for "a.b.0", None when any step is missing
"""

import os
import tomllib
from functools import cache

from racinglines.paths import ROOT

SCHEMAS = ROOT / "exchanges"
CODES = tuple(sorted(p.stem for p in SCHEMAS.glob("*.toml")))


@cache
def load(code):
    return tomllib.loads((SCHEMAS / f"{code}.toml").read_text())


def enabled(code):
    """The exchange's switch env var (schema [exchange] switch) is 1 / true / yes. Off unless set."""
    return os.environ.get(load(code)["exchange"].get("switch", ""), "").lower() in ("1", "true", "yes")


def sports(code):
    return tuple(load(code).get("sports", {}))


def dig(obj, path):
    """A dotted path into nested dicts and lists: "a.b.0" -> obj["a"]["b"][0]; None when a step is missing."""
    for step in str(path).split("."):
        if isinstance(obj, dict):
            obj = obj.get(step)
        elif isinstance(obj, (list, tuple)) and step.lstrip("-").isdigit() and -len(obj) <= int(step) < len(obj):
            obj = obj[int(step)]
        else:
            return None
        if obj is None:
            return None
    return obj
