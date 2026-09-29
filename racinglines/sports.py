"""
Sport schemas: what differs between sports, as data (sports/<code>.toml).

Existing modules keep their own constant names (registry.COMPETITIONS,
position_sim.model.SESSION_MINUTES, timed_runs.model.FINAL_POINTS, ...) and take
the values from here, so a new sport starts with a new schema file.

    load("f1")                  the parsed schema
    SPORT_CODES                 every sport with a schema, in display order
    by_competition("f1_wdc")    the schema whose competition has that code
    modeled(code)               False for a tape-only sport ([sport] model_family = "none": no model, no
                                pipeline; its exchange markets are only recorded, docs/todo.md U9)
    kalshi_series(code)         the Kalshi series prefixes a sport's [markets.kalshi] names, () if none
"""

import tomllib
from functools import cache

from racinglines.paths import ROOT

SCHEMAS = ROOT / "sports"
SPORT_CODES = ("mtb_dh", "f1", "nascar", "motogp", "indycar")   # registry / seeding order (keeps database ids stable)


@cache
def load(code):
    return tomllib.loads((SCHEMAS / f"{code}.toml").read_text())


def by_competition(competition):
    return next(s for s in map(load, SPORT_CODES) if s["competition"]["code"] == competition)


def modeled(code):
    """Whether the sport has a model ([sport] model_family other than "none")."""
    return load(code)["sport"].get("model_family", "none") != "none"


def kalshi_series(code):
    """The Kalshi series ticker prefixes a sport's schema names ([markets.kalshi] series), as a tuple."""
    return tuple(load(code).get("markets", {}).get("kalshi", {}).get("series", ()))


def int_keys(d):
    """TOML keys are strings; {"2021": x} -> {2021: x}."""
    return {int(k): v for k, v in d.items()}
