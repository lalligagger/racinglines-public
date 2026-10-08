"""Minimal NASCAR Cup model scaffold.

This is intentionally conservative: it only uses finish positions already stored in
our standard schema from the NASCAR public results feeds. It is a model-contract
starter for the next sport after the tape-only stack, and it is shaped to plug
into the same walk-forward / search flow as the F1 and MotoGP backtests.
"""

import hashlib

import numpy as np
import pandas as pd

from racinglines.models import outcomes as O
from racinglines.models.race_model import Event
from racinglines.pipelines import sweep_settings as SS

SETTINGS = [
    SS.Setting("sims", "model", "Simulations per race", "int", 2000, 100, 100000),
    SS.Setting("shrink", "model", "Form shrinkage (races)", "float", 3.0, 0, 100),
    SS.Setting("noise", "model", "Race-day noise (places)", "float", 2.0, 0.1, 20),
    SS.Setting("seed", "model", "Monte Carlo seed", "int", None, 0, 2**31 - 1),
    SS.Setting("history_races", "model", "Historical results kept as the prior", "int", 0, 0, 500),
    SS.Setting("recent_races", "model", "Recent results used for form", "int", 6, 1, 30),
    SS.Setting("recency_decay", "model", "Recent-form decay (races)", "float", 2.5, 0.1, 25),
    SS.Setting("team_bias", "model", "Team-form prior weight", "float", 0.35, 0.0, 2.0),
]


def _last_races(frame, n):
    """The rows of the last `n` races in `frame` (by date), however many results each race holds."""
    dates = np.sort(frame["date"].unique())[-n:]
    return frame[frame["date"].isin(dates)]


def _team_form(past, settings):
    """{team: recency-weighted mean finishing position over the team's last `recent_races` races} (each race's
    mean over the team's entries, the latest race weighted 1 and the oldest e^-recency_decay)."""
    out = {}
    for team, rows in past.groupby("team", dropna=False):
        per_race = rows.groupby("date")["position"].mean().sort_index().tail(settings["recent_races"])
        if per_race.empty:
            continue
        w = np.exp(-np.linspace(max(float(settings["recency_decay"]), 0.1), 0.0, len(per_race)))
        out[team] = float(np.average(per_race.to_numpy(float), weights=w))
    return out


def _field(ev):
    """The start list in `ev.info["field"]`: the replay passes the race's entrants (pipelines/position_replay.py) and
    `events` the event's own entry list (its rows that started), so exactly these entrants are priced, a newcomer at
    the model's no-form base. Empty (an Event built by hand): every entrant in the history."""
    return list((ev.info or {}).get("field") or [])


def _started(rows):
    """The rows of an event's entry list that started the race: every row but a DNS (did not start)."""
    status = rows["status"] if "status" in rows else pd.Series("OK", index=rows.index)
    return rows[status.fillna("OK").astype(str).str.upper() != "DNS"]


class NascarCupSettings(SS.Settings):
    SPEC = SETTINGS
    BY = {s.name: s for s in SETTINGS}
    MODEL = [s.name for s in SETTINGS]
    ALIASES = {}

    def _validate(self):
        if self["recent_races"] < 1:
            raise ValueError("recent_races must be >= 1")
        if self["history_races"] < 0:
            raise ValueError("history_races must be >= 0")
        if self["team_bias"] < 0:
            raise ValueError("team_bias must be >= 0")

    def label(self):
        return ", ".join(f"{k}={v}" for k, v in self.changed().items()) or "baseline"


class NascarCupRace:
    sport = "nascar"
    name = "nascar_results"
    Settings = NascarCupSettings
    noise_unit = "places"          # `noise` is in finishing places (the season forecast's estimate_noise is too)

    @staticmethod
    def _driver_key(name):
        text = str(name).strip()
        if not text:
            return 0
        return int(hashlib.md5(text.encode("utf-8")).hexdigest()[:12], 16) % (2**31 - 1)

    @classmethod
    def _with_athlete_ids(cls, frame):
        resolved = frame.copy()
        if "athlete_id" not in resolved.columns and "driver" in resolved.columns:
            mapping = {name: cls._driver_key(name) for name in sorted(resolved["driver"].dropna().astype(str).unique())}
            resolved["athlete_id"] = resolved["driver"].map(mapping)
        return resolved

    @classmethod
    def _entrant_ids(cls, frame):
        resolved = cls._with_athlete_ids(frame)
        ids = pd.to_numeric(resolved.get("athlete_id", pd.Series(dtype="float64")), errors="coerce")
        if ids.notna().any():
            return sorted(ids.dropna().astype(int).unique().tolist())
        names = resolved.get("driver", pd.Series(dtype="object"))
        return sorted(names.dropna().astype(str).unique().tolist())

    def search_grid(self, data, seasons=None, settings_list=None, kinds=None, echo=False):
        from racinglines.core import walk_forward as WF

        if settings_list is None:
            settings_list = [self.Settings.from_dict({}).to_json()]
        kinds = kinds or ["race_win", "race_podium", "race_h2h"]
        rows = []
        for idx, raw in enumerate(settings_list, 1):
            settings = self.Settings.from_dict(raw)
            out = WF.run(self, data, settings, seasons=seasons, kinds=kinds,
                         echo=lambda *args, **kwargs: None if not echo else print(*args, **kwargs))
            cal = out["calibration"].query("season == 'all'").set_index("kind")
            vals = []
            entry = {"candidate": idx, **dict(raw)}
            for kind in kinds:
                if kind in cal.index:
                    val = float(cal.loc[kind, "logloss"])
                    entry[kind] = val
                    vals.append(val)
            entry["score"] = float(np.mean(vals)) if vals else np.nan
            rows.append(entry)
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values(["score"] + [k for k in kinds if k in df.columns],
                                ascending=[True] + [True] * len([k for k in kinds if k in df.columns]),
                                na_position="last")
            df = df.reset_index(drop=True)
        return df

    @staticmethod
    def load(engine_url=None, data=None):
        if data is not None:
            return data.copy()

        from racinglines.db.config import get_engine
        from sqlalchemy import text

        engine = get_engine(engine_url)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        EXTRACT(YEAR FROM ev.start_date)::int AS season,
                        ev.id AS event_id,
                        ev.name AS event_name,
                        ev.source_key AS race_key,
                        ev.start_date::date AS date,
                        a.id AS athlete_id,
                        a.display_name AS driver,
                        r.position,
                        r.team,
                        r.status,
                        COALESCE((r.extra->>'points')::float, 0.0) AS points
                    FROM events ev
                    JOIN races ra ON ra.event_id = ev.id
                    JOIN rounds r2 ON r2.race_id = ra.id AND r2.kind = 'race'
                    JOIN results r ON r.round_id = r2.id
                    JOIN athletes a ON a.id = r.athlete_id
                    WHERE ev.source = 'nascar_cf'
                    ORDER BY ev.start_date, r.position NULLS LAST
                    """
                )
            ).all()

        if not rows:
            return pd.DataFrame(columns=["season", "event_id", "event_name", "race_key", "date", "athlete_id", "driver",
                                         "position", "team", "status", "points"])

        df = pd.DataFrame(rows, columns=["season", "event_id", "event_name", "race_key", "date", "athlete_id", "driver",
                                          "position", "team", "status", "points"])
        # NASCAR event names repeat across seasons (e.g. Daytona), so keep the season in the event key to
        # avoid mixing one event's drivers with the next season's same-named race.
        df["race"] = df["season"].astype(str) + "::" + df["race_key"].fillna(df["event_name"]).astype(str)
        return df

    @staticmethod
    def data_through(data):
        return data["date"].max()

    @staticmethod
    def _event_race_key(frame):
        if "race" in frame.columns:
            base = frame["race"].fillna("").astype(str)
            season = frame["season"].fillna("").astype(str)
            out = []
            for s, r in zip(season.tolist(), base.tolist()):
                text = str(r)
                if not text:
                    out.append("")
                elif str(s) and text.startswith(f"{s}::"):
                    out.append(text)
                elif str(s):
                    out.append(f"{s}::{text}")
                else:
                    out.append(text)
            return pd.Series(out, index=frame.index)
        return frame["season"].astype(str) + "::" + frame["race_key"].fillna(frame.get("event_name", frame["event_id"]))

    def seasons(self, data, settings):
        return sorted(int(s) for s in data["season"].dropna().unique())

    def events(self, data, settings, seasons=None):
        frame = data.copy()
        frame["race"] = self._event_race_key(frame)
        d = frame.drop_duplicates("race").sort_values("date")
        if seasons:
            d = d[d["season"].isin(seasons)]
        entries = _started(frame).groupby("race")
        out = []
        for row in d.itertuples():
            event_name = getattr(row, "event_name", None)
            field = self._entrant_ids(entries.get_group(row.race)) if row.race in entries.groups else []
            out.append(Event(id=row.race, season=int(row.season), cutoff=row.date,
                             name=str(event_name or row.race), info={"field": field}))
        return out

    def history(self, data, settings):
        return data

    def price(self, hist, ev, settings, rng):
        past = self._with_athlete_ids(hist[hist["date"] < ev.cutoff].copy())
        if past.empty:
            entrants = _field(ev) or self._entrant_ids(hist)
            if not entrants:
                return None
            base = np.zeros(len(entrants), dtype=float)
            noise = rng.normal(0.0, settings["noise"], (settings["sims"], len(entrants)))
            sim_scores = base[None, :] + noise
            rank = np.argsort(np.argsort(sim_scores, axis=1), axis=1) + 1
            return O.OutcomeSims(entrants=entrants, rank=rank, finished=np.ones_like(rank, bool))

        past = past.sort_values("date")
        if settings["history_races"] > 0:
            past = _last_races(past, settings["history_races"])

        entrants = _field(ev) or self._entrant_ids(past)
        if not entrants:
            return None

        overall = float(past["position"].mean())
        team_form = _team_form(past, settings)

        scores = []
        for athlete_id in entrants:
            driver_rows = past[past["athlete_id"] == athlete_id].sort_values("date").tail(settings["recent_races"])
            if driver_rows.empty:
                base = overall
            else:
                w = np.exp(-np.linspace(max(float(settings["recency_decay"]), 0.1), 0.0, len(driver_rows)))
                recent_mean = float(np.average(driver_rows["position"].to_numpy(float), weights=w))
                team = driver_rows["team"].iloc[-1]
                team_mean = team_form.get(team, overall)
                shrink = min(0.75, settings["shrink"] / max(settings["shrink"] + 5.0, 1.0))
                base = ((1.0 - shrink) * recent_mean) + (shrink * overall)
                base += settings["team_bias"] * (team_mean - overall)
            scores.append(base)

        base = np.asarray(scores, dtype=float)
        noise = rng.normal(0.0, settings["noise"], (settings["sims"], len(entrants)))
        sim_scores = base[None, :] + noise
        rank = np.argsort(np.argsort(sim_scores, axis=1), axis=1) + 1
        return O.OutcomeSims(entrants=entrants, rank=rank, finished=np.ones_like(rank, bool))

    def results(self, data, ev):
        frame = self._with_athlete_ids(data.copy())
        frame["race"] = self._event_race_key(frame)
        r = frame[frame["race"] == ev.id].copy()
        if r.empty:
            return pd.DataFrame(columns=["athlete_id", "position", "status", "qual_position", "team_id", "points"])
        r = r[pd.notna(r["athlete_id"])].sort_values(["position", "points"], na_position="last")
        r = r.drop_duplicates(subset=["athlete_id"], keep="last")
        return pd.DataFrame(
            dict(
                athlete_id=pd.to_numeric(r["athlete_id"], errors="coerce").astype(int).to_numpy(),
                position=r["position"].to_numpy(float),
                status=r["status"].fillna("OK").to_numpy(),
                qual_position=np.nan,
                team_id=None,
                points=r["points"].fillna(0.0).to_numpy(float),
            )
        )


class NascarCupRaceChallenger(NascarCupRace):
    """A more F1-like NASCAR backtest: recency-weighted driver form with a team prior."""

    name = "nascar_recent_form"
    Settings = NascarCupSettings

    def price(self, hist, ev, settings, rng):
        past = self._with_athlete_ids(hist[hist["date"] < ev.cutoff].copy())
        if past.empty:
            entrants = _field(ev) or self._entrant_ids(hist)
            if not entrants:
                return None
            base = np.zeros(len(entrants), dtype=float)
            noise = rng.normal(0.0, settings["noise"], (settings["sims"], len(entrants)))
            sim_scores = base[None, :] + noise
            rank = np.argsort(np.argsort(sim_scores, axis=1), axis=1) + 1
            return O.OutcomeSims(entrants=entrants, rank=rank, finished=np.ones_like(rank, bool))

        past = past.sort_values("date")
        if settings["history_races"] > 0:
            past = _last_races(past, settings["history_races"])

        entrants = _field(ev) or self._entrant_ids(past)
        if not entrants:
            return None

        overall = float(past["position"].mean())
        team_form = _team_form(past, settings)

        scores = []
        for athlete_id in entrants:
            driver_rows = past[past["athlete_id"] == athlete_id].sort_values("date").tail(settings["recent_races"])
            if driver_rows.empty:
                base = overall
            else:
                w = np.exp(-np.linspace(max(float(settings["recency_decay"]), 0.1), 0.0, len(driver_rows)))
                recent_mean = float(np.average(driver_rows["position"].to_numpy(float), weights=w))
                team = driver_rows["team"].iloc[-1]
                team_mean = team_form.get(team, overall)
                shrink = min(0.75, settings["shrink"] / max(settings["shrink"] + 5.0, 1.0))
                base = ((1.0 - shrink) * recent_mean) + (shrink * overall)
                base += settings["team_bias"] * (team_mean - overall)
            scores.append(base)

        base = np.asarray(scores, dtype=float)
        noise = rng.normal(0.0, settings["noise"], (settings["sims"], len(entrants)))
        sim_scores = base[None, :] + noise
        rank = np.argsort(np.argsort(sim_scores, axis=1), axis=1) + 1
        return O.OutcomeSims(entrants=entrants, rank=rank, finished=np.ones_like(rank, bool))
