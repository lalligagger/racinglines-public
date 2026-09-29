"""
Downhill frames (L1, docs/frames.md), built from the tidy runs frame `TimedRuns.load` returns. Read-only views over
what the model already holds: no database query, and nothing about how the model loads or prices changes. Only the
FINISH rows are used (one per rider per round; a frame loaded with splits also has S1, S2 ... rows).

    entrants          one row per (event, rider), everyone with a row in the event, DNS riders included
    sessions          one row per (event, round), in the rounds' own names ([rounds] in sports/mtb_dh.toml)
    classifications   one row per (event, round, rider): rank, status and time of each run; gap_ms is to the round's
                      fastest run; no grid or points at round level (the source has neither)
    official_results  one row per rider of every completed event (the model's own `completed_events`: the final has
                      results): the Final's rank, the event's points, and the race rounds the rider started

`event_id` already names the category ("20260821_mtb_ME"), so an event is one category's race weekend.
`official_results` reuses the model's own `actual_event_points`, with the rules `TimedRuns.results` applies: position =
the Final rank, status OK when ranked in the Final and DNF otherwise, points 0 when none. `rounds_reached` lists the
race rounds (`[rounds] race`) in which the rider has a row (a start-list entry, so a DNS in the Final still
reached it, as `results()`' `reached_final` counts it), in running order (`[rounds] order`).

`available_at` (naive UTC): the tidy frame carries an event *date*, not session times, and mtb_dh.toml has no session
minutes. So every row of an event is knowable from the end of that date (the next midnight), and a session's `start`
and `end` are the bounds of that day, not its own times. The model's own rule, `_training_rows`, uses an event's
rows for a later event whose date is strictly after it (`event_date < cutoff`); the frame is at most one day
stricter (an event the day before another isn't visible to it), never looser. Assumption to review in E2.
Entrants and official_results use the same date: the model reads the actual start list of the event it prices
(`event_starters`), before that date, so E2 has to carry that read over as an exception ("identities, never results").

Not built: `laps` (downhill has splits instead), `conditions` (the frame's track_condition is a constant
"unknown"), `venue_features` (no venue history in the frame).
"""

import numpy as np
import pandas as pd

from racinglines import sports
from racinglines.frames._util import gap_to_leader, shape
from racinglines.frames.schema import SCHEMAS
from racinglines.models.timed_runs import actual_event_points, completed_events

DAY = pd.Timedelta(days=1)
ROUNDS = sports.load("mtb_dh")["rounds"]           # sports/mtb_dh.toml [rounds]


def _runs(data):
    """The FINISH rows, with the start and the end of the day of their event."""
    d = data[data["sector_id"] == "FINISH"] if "sector_id" in data else data
    day = pd.to_datetime(d["event_date"])
    return d.assign(_start=day, _end=day + DAY)


def _text(s):
    """A str (or None) per value: start numbers can arrive as numbers."""
    return s.map(lambda v: v if pd.isna(v) else str(v)).astype(object)


def entrants(data):
    d = _runs(data)
    g = d.groupby(["event_id", "athlete_id"], as_index=False).agg(
        race_id=("race_id", "first"), name=("rider_name", "first"), team=("team", "first"), bib=("bib", "first"),
        available_at=("_end", "min"))
    g["team_id"] = None                                # the tidy frame has team names only
    g["bib"] = _text(g["bib"])
    return shape("entrants", g)


def sessions(data):
    g = _runs(data).groupby(["event_id", "round"], as_index=False).agg(start=("_start", "min"), end=("_end", "min"))
    g = g.rename(columns={"round": "session"})
    g["available_at"] = g["end"]
    return shape("sessions", g)


def classifications(data):
    d = _runs(data)
    c = pd.DataFrame({
        "event_id": d["event_id"], "session": d["round"], "athlete_id": d["athlete_id"],
        "position": d["rank_at_split"].astype(float), "status": d["status"],
        "time_ms": np.rint(d["cum_time_s"].astype(float) * 1000),
        "grid": np.nan, "points": np.nan, "available_at": d["_end"]})
    c["gap_ms"] = gap_to_leader(c)
    return shape("classifications", c)


def official_results(data):
    d = _runs(data)
    done = d[d["event_id"].isin(completed_events(d))]
    if done.empty:
        return shape("official_results", pd.DataFrame(columns=SCHEMAS["official_results"].column_names))
    pts = actual_event_points(done)
    made = done.loc[done["round"] == "final", ["event_id", "rider_id"]]
    out = pd.concat([pts[["event_id", "rider_id"]], made]).drop_duplicates().merge(
        pts[["event_id", "rider_id", "final_rank", "points"]], on=["event_id", "rider_id"], how="left")
    out["athlete_id"] = out["rider_id"].map(done.drop_duplicates("rider_id").set_index("rider_id")["athlete_id"])
    out["position"] = out["final_rank"].astype(float)
    out["status"] = np.where(out["final_rank"].notna(), "OK", "DNF")
    out["points"] = out["points"].fillna(0.0)
    out["available_at"] = out["event_id"].map(done.groupby("event_id")["_end"].max())
    listed = done[done["round"].isin(ROUNDS["race"])]
    reached = (listed.assign(_order=listed["round"].map(ROUNDS["order"])).sort_values("_order", kind="stable")
               .groupby(["event_id", "rider_id"])["round"].agg(tuple).rename("rounds_reached"))
    out = out.join(reached, on=["event_id", "rider_id"])
    out["rounds_reached"] = [t if isinstance(t, tuple) else () for t in out["rounds_reached"]]
    return shape("official_results", out)


BUILDERS = {"entrants": entrants, "sessions": sessions, "classifications": classifications,
            "official_results": official_results}
