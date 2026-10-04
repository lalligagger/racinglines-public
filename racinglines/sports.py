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
    polymarket_tags(code)       the Gamma tag_slug values a sport's [markets.polymarket] names, () if none
    identity(code)              the package under racinglines/sources/ whose links module says which driver and race a
                                market is about ([identity] resolver in the schema), None if the sport has none
    frames(code)                the L1 input frames a sport's [data] frames names, () if the block is absent
                                (racinglines/frames, docs/frames.md)
"""

import tomllib
from functools import cache

from racinglines.paths import ROOT

SCHEMAS = ROOT / "sports"
SPORT_CODES = ("mtb_dh", "f1", "nascar", "motogp", "indycar", "road_cycling", "le_mans", "sailgp")   # registry / seeding order (keeps database ids stable)


@cache
def load(code):
    return tomllib.loads((SCHEMAS / f"{code}.toml").read_text())


def by_competition(competition):
    return next(s for s in map(load, SPORT_CODES) if s["competition"]["code"] == competition)


def event_title(competition, event_key, default):
    """An event's one display name: its schema's [names] entry for the key, else `default`."""
    try:
        names = by_competition(competition).get("names", {})
    except StopIteration:
        return default
    return names.get(str(event_key), default)


def modeled(code):
    """Whether the sport has a model ([sport] model_family other than "none")."""
    return load(code)["sport"].get("model_family", "none") != "none"


def kalshi_series(code):
    """The Kalshi series ticker prefixes a sport's schema names ([markets.kalshi] series), as a tuple."""
    return tuple(load(code).get("markets", {}).get("kalshi", {}).get("series", ()))


def polymarket_tags(code):
    """The Polymarket Gamma tag_slug values a sport's schema names ([markets.polymarket] tags), as a tuple."""
    return tuple(load(code).get("markets", {}).get("polymarket", {}).get("tags", ()))


def identity(code):
    """The name of the sport's market-identity resolver ([identity] resolver), or None."""
    return load(code).get("identity", {}).get("resolver")


def frames(code):
    """The L1 input frames a sport's schema says it provides ([data] frames), as a tuple; () if there is no block."""
    return tuple(load(code).get("data", {}).get("frames", ()))


def fallback_rule(code):
    """The source-quality rule a sport declares for missing or partial result data.

    Default is strict: official data is required; a fallback source is allowed only when the schema says so.
    """
    return load(code).get("results", {}).get("fallback_rule", "official_only")


def fallbacks(code):
    """Fallback sources declared in the sport schema, if any.

    Each entry is a generic dict: {source, quality, scope, notes, ...}. The schema may also define a
    `fallback_rule` describing the policy for when the fallback is acceptable.
    """
    entries = load(code).get("results", {}).get("fallbacks", ())
    if not entries:
        return ()
    if isinstance(entries, dict):
        entries = entries.get("sources", tuple(entries.values()))
    return tuple(entries)


def live_frames(code):
    """The frames whose source dates each row as it happens ([data] live), as a tuple; () if none. Every other
    session-keyed frame is published a whole session at a time, once the session has ended."""
    return tuple(load(code).get("data", {}).get("live", ()))


def int_keys(d):
    """TOML keys are strings; {"2021": x} -> {2021: x}."""
    return {int(k): v for k, v in d.items()}
