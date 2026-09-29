"""
L1 canonical input frames: the shape a sport's data takes before any model reads it (docs/frames.md,
docs/engine-roadmap.md "L1: Canonical input frames").

Each frame is declared once, here, as plain dataclasses: its columns (a dtype family and whether nulls are allowed),
its key columns (unique and never null) and its `available_at` column, when the row became knowable (naive UTC,
non-null on every row, so an as-of view can filter on it).

    SCHEMAS["classifications"]          the declaration (a FrameSchema)
    FRAMES                              every declared frame name, in display order
    validate("classifications", df)     df itself, or FrameError listing every problem found

`validate` checks that the declared columns are present, their dtype families, that non-nullable columns have no
nulls, that `available_at` is set on every row and that the key is unique. Extra columns are allowed (a sport may
carry more than the engine reads). An empty frame passes when its columns are present.

Dtype families (what pandas holds, not an exact dtype, so a nullable int or a string dtype passes too):
    id        int or str (an event id is an int for F1, a string for downhill)
    int       integers
    number    int or float (a float column with NaN for "no value")
    str       str (None / NaN for a missing value)
    bool      booleans
    datetime  datetime64, naive UTC (the convention of position_sim and core/stages)
    object    anything (a list or a dict per row)

`market_links` and `market_quotes` (the exchange half of L1) are declared in a later task.
"""

from dataclasses import dataclass

import pandas as pd
from pandas.api import types as T

FAMILIES = ("id", "int", "number", "str", "bool", "datetime", "object")


class FrameError(ValueError):
    """A frame that doesn't match its declaration (or a frame request that can't be met). `problems` lists each one."""

    def __init__(self, message, problems=()):
        super().__init__(message)
        self.problems = list(problems)


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str                  # one of FAMILIES
    nullable: bool = False
    doc: str = ""


@dataclass(frozen=True)
class FrameSchema:
    name: str
    key: tuple                  # column names that identify a row: unique together, never null
    columns: tuple              # Column, in display order
    available_at: str = "available_at"
    doc: str = ""

    def __post_init__(self):
        names = [c.name for c in self.columns]
        by = {c.name: c for c in self.columns}
        problems = []
        if len(set(names)) != len(names):
            problems.append("duplicate column names")
        problems += [f"unknown dtype {c.dtype!r} on {c.name!r}" for c in self.columns if c.dtype not in FAMILIES]
        problems += [f"key column {k!r} is not a column" for k in self.key if k not in by]
        problems += [f"key column {k!r} is nullable" for k in self.key if k in by and by[k].nullable]
        a = by.get(self.available_at)
        if a is None:
            problems.append(f"available_at column {self.available_at!r} is not a column")
        elif a.dtype != "datetime" or a.nullable:
            problems.append(f"available_at column {self.available_at!r} must be a non-nullable datetime")
        if self.available_at in self.key:
            problems.append("available_at can't be part of the key")
        if problems:
            raise ValueError(f"frame schema {self.name!r}: " + "; ".join(problems))

    @property
    def column_names(self):
        return tuple(c.name for c in self.columns)


def _c(name, dtype, nullable=False, doc=""):
    return Column(name, dtype, nullable, doc)


_AVAILABLE = _c("available_at", "datetime", doc="when the row became knowable (naive UTC)")

_SCHEMAS = [
    FrameSchema(
        "entrants", key=("event_id", "race_id", "athlete_id"),
        doc="Who is entered in each race of an event: identity and team, never results.",
        columns=(_c("event_id", "id"), _c("race_id", "id"), _c("athlete_id", "int"), _c("name", "str"),
                 _c("team_id", "str", True, "the sport's own team key, when it has one"),
                 _c("team", "str", True, "team name as the source spells it"),
                 _c("bib", "str", True, "start number"), _AVAILABLE)),
    FrameSchema(
        "sessions", key=("event_id", "session"),
        doc="The sessions (F1) or rounds (downhill) each event ran, in the sport's own vocabulary "
            "([sessions] / [rounds] in sports/<code>.toml).",
        columns=(_c("event_id", "id"), _c("session", "str"), _c("start", "datetime"), _c("end", "datetime"),
                 _AVAILABLE)),
    FrameSchema(
        "classifications", key=("event_id", "session", "athlete_id"),
        doc="One row per athlete per session: where they finished and how.",
        columns=(_c("event_id", "id"), _c("session", "str"), _c("athlete_id", "int"),
                 _c("position", "number", True, "classified position, null when the session has none"),
                 _c("status", "str", doc="OK, DNF, DNS ..."),
                 _c("time_ms", "number", True), _c("gap_ms", "number", True, "time_ms minus the P1 row's time_ms"),
                 _c("grid", "number", True), _c("points", "number", True), _AVAILABLE)),
    FrameSchema(
        "laps", key=("event_id", "session", "athlete_id", "lap"),
        doc="One row per lap, for sports whose feed has laps (optional).",
        columns=(_c("event_id", "id"), _c("session", "str"), _c("athlete_id", "int"), _c("lap", "int"),
                 _c("time_ms", "number", True), _c("sector_ms", "object", True, "list of sector times"),
                 _c("pit", "bool", doc="an in-lap or an out-lap"), _c("track_status", "str", True), _AVAILABLE)),
    FrameSchema(
        "conditions", key=("event_id", "session"),
        doc="Weather and track state per session (optional).",
        columns=(_c("event_id", "id"), _c("session", "str"),
                 _c("rain_share", "number", True, "share of the session it rained, 0 to 1"),
                 _c("track_temp", "number", True, "mean track temperature, C"), _AVAILABLE)),
    FrameSchema(
        "venue_features", key=("event_id",),
        doc="What the event's venue looks like to a model (optional). The sport defines the keys of `features`.",
        columns=(_c("event_id", "id"), _c("venue", "str", True), _c("features", "object", doc="{name: value}"),
                 _AVAILABLE)),
    FrameSchema(
        "official_results", key=("event_id", "athlete_id"),
        doc="The settled result of each event. The engine reads it only after pricing, to settle (what "
            "`results()` does today).",
        columns=(_c("event_id", "id"), _c("athlete_id", "int"),
                 _c("position", "number", True, "final position, null if not classified"),
                 _c("status", "str"), _c("points", "number", True),
                 _c("rounds_reached", "object", True, "the race rounds the athlete started, in running order; "
                                                      "null for a sport without elimination rounds"),
                 _AVAILABLE)),
]

SCHEMAS = {s.name: s for s in _SCHEMAS}
FRAMES = tuple(SCHEMAS)


def schema(name):
    try:
        return SCHEMAS[name]
    except KeyError:
        raise FrameError(f"unknown frame {name!r}; the declared frames are {list(FRAMES)}") from None


def _is_text(d, nonnull):
    return (d == object or T.is_string_dtype(d)) and all(isinstance(v, str) for v in nonnull)


def _dtype_problem(col, s):
    """Why series `s` isn't in `col`'s dtype family, or None."""
    d, f = s.dtype, col.dtype
    if f == "object":
        return None
    if f == "int":
        ok = T.is_integer_dtype(d)
    elif f == "number":
        ok = T.is_numeric_dtype(d) and not T.is_bool_dtype(d)
    elif f == "bool":
        ok = T.is_bool_dtype(d)
    elif f == "datetime":
        if T.is_datetime64_any_dtype(d) and getattr(d, "tz", None) is not None:
            return "is timezone-aware; frames use naive UTC"
        ok = T.is_datetime64_dtype(d)
    elif f == "str":
        ok = _is_text(d, s.dropna())
    else:   # id
        ok = T.is_integer_dtype(d) or _is_text(d, s.dropna())
    return None if ok else f"has dtype {d}, expected {f}"


def validate(name, df):
    """Check `df` against the declaration of frame `name`; returns `df`, or raises FrameError listing every problem."""
    sc = schema(name)
    if not isinstance(df, pd.DataFrame):
        raise FrameError(f"frame {name!r}: expected a DataFrame, got {type(df).__name__}")
    problems = []
    missing = [c.name for c in sc.columns if c.name not in df.columns]
    if missing:
        problems.append(f"missing columns {missing}")
    if len(df):
        for col in sc.columns:
            if col.name not in df.columns:
                continue
            s = df[col.name]
            why = _dtype_problem(col, s)
            if why:
                problems.append(f"column {col.name!r} {why}")
            n_null = int(s.isna().sum())
            if n_null and col.name == sc.available_at:
                problems.append(f"{n_null} of {len(df)} rows have no {sc.available_at} (a row that can't be "
                                f"dated can't be leak-checked)")
            elif n_null and not col.nullable:
                problems.append(f"column {col.name!r} has {n_null} nulls but isn't nullable")
        if all(k in df.columns for k in sc.key):
            dup = df.duplicated(list(sc.key), keep=False)
            if dup.any():
                eg = df.loc[dup, list(sc.key)].drop_duplicates().head(3).to_dict("records")
                problems.append(f"{int(df.duplicated(list(sc.key)).sum())} rows repeat a key {list(sc.key)}, e.g. {eg}")
    if problems:
        raise FrameError(f"frame {name!r} doesn't match its declaration: " + "; ".join(problems), problems)
    return df
