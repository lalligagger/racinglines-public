"""Minimal Road Cycling backtest model scaffold.

This model uses finished race results stored in the standard schema from UCI-sourced
road cycling data. It is built to fit the generic backtest engine and to run against
the VM-loaded road cycling data, sized for safe extension to live market-making.
"""

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
    SS.Setting("uci_bias", "model", "UCI ranking prior weight", "float", 0.35, 0.0, 2.0),
]


def _last_races(frame, n):
    """The rows of the last `n` races in `frame` (by date), however many results each race holds."""
    dates = np.sort(frame["date"].unique())[-n:]
    return frame[frame["date"].isin(dates)]


def _field(ev):
    """The start list the replay passes in `ev.info["field"]` (pipelines/position_replay.py): price exactly these
    entrants, a newcomer at the model's no-form base. Empty (walk-forward, search): every entrant in the history,
    as before."""
    return list((ev.info or {}).get("field") or [])


class RoadCyclingSettings(SS.Settings):
    SPEC = SETTINGS
    BY = {s.name: s for s in SETTINGS}
    MODEL = [s.name for s in SETTINGS]
    ALIASES = {}

    def _validate(self):
        if self["recent_races"] < 1:
            raise ValueError("recent_races must be >= 1")
        if self["history_races"] < 0:
            raise ValueError("history_races must be >= 0")
        if self["uci_bias"] < 0:
            raise ValueError("uci_bias must be >= 0")

    def label(self):
        return ", ".join(f"{k}={v}" for k, v in self.changed().items()) or "baseline"


class RoadCyclingModel:
    """Minimal position simulator for road cycling: UCI ranking + recent form."""

    sport = "road_cycling"
    name = "road_cycling_results"
    Settings = RoadCyclingSettings

    @staticmethod
    def _keyed(frame):
        """(entrant column, frame keyed by it). The database frame carries `athlete_id`; a frame without ids
        (a fixture, a CSV) is keyed by `rider` name instead. Rows without a key are dropped."""
        ids = pd.to_numeric(frame.get("athlete_id", pd.Series(dtype="float64", index=frame.index)), errors="coerce")
        if ids.notna().any():
            out = frame[ids.notna()].copy()
            out["athlete_id"] = ids[ids.notna()].astype(int)
            return "athlete_id", out
        names = frame.get("rider", pd.Series(dtype="object", index=frame.index))
        out = frame[names.notna()].copy()
        out["rider"] = names[names.notna()].astype(str)
        return "rider", out

    @classmethod
    def _entrant_ids(cls, frame):
        key, keyed = cls._keyed(frame)
        return sorted(keyed[key].unique().tolist())

    def search_grid(self, data, seasons=None, settings_list=None, kinds=None, echo=False):
        """Evaluate a small grid of parameter settings and rank by mean log loss."""
        from racinglines.core import walk_forward as WF

        if settings_list is None:
            settings_list = [self.Settings.from_dict({}).to_json()]
        kinds = kinds or ["race_win", "race_podium", "race_top10"]
        rows = []
        for idx, raw in enumerate(settings_list, 1):
            settings = self.Settings.from_dict(raw)
            out = WF.run(self, data, settings, seasons=seasons, kinds=kinds, echo=lambda *args, **kwargs: None if not echo else print(*args, **kwargs))
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
            df = df.sort_values(["score"] + [k for k in kinds if k in df.columns], ascending=[True] + [True] * len([k for k in kinds if k in df.columns]), na_position="last")
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
                        a.display_name AS rider,
                        r.position,
                        COALESCE((r.extra->>'uci_points')::float, 0.0) AS uci_points,
                        r.status,
                        COALESCE((r.extra->>'points')::float, 0.0) AS points
                    FROM events ev
                    JOIN races ra ON ra.event_id = ev.id
                    JOIN rounds r2 ON r2.race_id = ra.id AND r2.kind = 'race'
                    JOIN results r ON r.round_id = r2.id
                    JOIN athletes a ON a.id = r.athlete_id
                    WHERE ev.source = 'uci_api'
                    ORDER BY ev.start_date, r.position NULLS LAST
                    """
                )
            ).all()

        if not rows:
            return pd.DataFrame(columns=["season", "event_id", "event_name", "race_key", "date", "athlete_id", "rider", "position", "uci_points", "status", "points"])

        df = pd.DataFrame(rows, columns=["season", "event_id", "event_name", "race_key", "date", "athlete_id", "rider", "position", "uci_points", "status", "points"])
        df["race"] = df["race_key"].fillna(df["event_name"])
        return df

    @staticmethod
    def data_through(data):
        return data["date"].max()

    def seasons(self, data, settings):
        return sorted(int(s) for s in data["season"].dropna().unique())

    @staticmethod
    def _race_ids(frame):
        """Every row's event id, "<season>::<race>"."""
        if "race" in frame.columns:
            return frame["season"].astype(str) + "::" + frame["race"].astype(str)
        return frame["season"].astype(str) + "::" + frame["race_key"].fillna(frame.get("event_name", frame["event_id"]))

    def events(self, data, settings, seasons=None):
        frame = data.assign(race=self._race_ids(data))
        d = frame.drop_duplicates("race").sort_values("date")
        if seasons:
            d = d[d["season"].isin(seasons)]
        out = []
        for row in d.itertuples():
            event_name = getattr(row, "event_name", None)
            out.append(Event(id=row.race, season=int(row.season), cutoff=row.date,
                             name=str(event_name or row.race)))
        return out

    def history(self, data, settings):
        return data

    def price(self, hist, ev, settings, rng):
        past = hist[hist["date"] < ev.cutoff].copy()
        if past.empty:
            return None

        key, past = self._keyed(past)
        entrants = _field(ev) or self._entrant_ids(past)
        if not entrants:
            return None

        past = past.sort_values("date")
        if settings["history_races"] > 0:
            past = _last_races(past, settings["history_races"])

        overall = float(past["position"].mean())
        uci_mean = float(past["uci_points"].mean()) if past["uci_points"].notna().any() else 0.0

        scores = []
        for athlete_id in entrants:
            rider_rows = past[past[key] == athlete_id].sort_values("date").tail(settings["recent_races"])
            if rider_rows.empty:
                base = overall
            else:
                w = np.exp(-np.linspace(max(float(settings["recency_decay"]), 0.1), 0.0, len(rider_rows)))
                recent_mean = float(np.average(rider_rows["position"].to_numpy(float), weights=w))
                uci_points = float(rider_rows["uci_points"].iloc[-1]) if rider_rows["uci_points"].notna().any() else uci_mean
                shrink = min(0.75, settings["shrink"] / max(settings["shrink"] + 5.0, 1.0))
                base = ((1.0 - shrink) * recent_mean) + (shrink * overall)
                uci_delta = uci_points - uci_mean
                base += settings["uci_bias"] * (uci_delta / max(abs(uci_delta), 1.0) if uci_delta != 0 else 0)
            scores.append(base)

        base = np.asarray(scores, dtype=float)
        noise = rng.normal(0.0, settings["noise"], (settings["sims"], len(entrants)))
        sim_scores = base[None, :] + noise
        rank = np.argsort(np.argsort(sim_scores, axis=1), axis=1) + 1
        return O.OutcomeSims(entrants=entrants, rank=rank, finished=np.ones_like(rank, bool))

    def results(self, data, ev):
        r = data[self._race_ids(data) == ev.id].copy()
        if r.empty:
            return pd.DataFrame(columns=["athlete_id", "position", "status", "qual_position", "team_id", "points"])
        key, r = self._keyed(r)
        r = r.sort_values("position")
        return pd.DataFrame(
            dict(
                athlete_id=r[key].to_numpy(),
                position=r["position"].to_numpy(float),
                status=r["status"].fillna("OK").to_numpy(),
                qual_position=np.nan,
                team_id=None,
                points=r["points"].fillna(0.0).to_numpy(float),
            )
        )
