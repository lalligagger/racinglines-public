"""Minimal MotoGP backtest model scaffold.

This is intentionally conservative: it uses only finished race results already
stored in the standard schema, with no lap-by-lap or sector data. The model is
built to fit the generic backtest engine and to run against the VM-loaded
MotoGP data, while being small enough to extend safely.
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
]


class MotoGPSettings(SS.Settings):
    SPEC = SETTINGS
    BY = {s.name: s for s in SETTINGS}
    MODEL = [s.name for s in SETTINGS]
    ALIASES = {}

    def _validate(self):
        pass

    def label(self):
        return ", ".join(f"{k}={v}" for k, v in self.changed().items()) or "baseline"


class MotoGPRace:
    sport = "motogp"
    name = "motogp_results"
    Settings = MotoGPSettings

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
                        a.display_name AS rider,
                        r.position,
                        r.team,
                        r.status,
                        r.points
                    FROM events ev
                    JOIN races ra ON ra.event_id = ev.id
                    JOIN rounds r2 ON r2.race_id = ra.id
                    JOIN results r ON r.round_id = r2.id
                    JOIN athletes a ON a.id = r.athlete_id
                    WHERE ev.source = 'motogp_api'
                    ORDER BY ev.start_date, r.position NULLS LAST
                    """
                )
            ).all()

        if not rows:
            return pd.DataFrame(columns=["season", "event_id", "event_name", "race_key", "date", "rider", "position", "team", "status", "points"])

        df = pd.DataFrame(rows, columns=["season", "event_id", "event_name", "race_key", "date", "rider", "position", "team", "status", "points"])
        df["race"] = df["race_key"].fillna(df["event_name"])
        return df

    @staticmethod
    def data_through(data):
        return data["date"].max()

    def seasons(self, data, settings):
        return sorted(int(s) for s in data["season"].dropna().unique())

    def events(self, data, settings, seasons=None):
        d = data.drop_duplicates("race").sort_values("date")
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

        entrants = sorted(past["rider"].dropna().unique())
        if not entrants:
            return None

        recent = past.groupby("rider")["position"].agg(["mean", "count"]).reindex(entrants)
        recent["skill"] = recent["mean"].fillna(recent["mean"].median())
        skill = recent["skill"].to_numpy(dtype=float)

        base = np.asarray(skill, dtype=float)
        noise = rng.normal(0.0, settings["noise"], (settings["sims"], len(entrants)))
        scores = base[None, :] + noise
        rank = scores.argsort(axis=1).argsort(axis=1) + 1
        return O.OutcomeSims(entrants=entrants, rank=rank, finished=np.ones_like(rank, bool))

    def results(self, data, ev):
        r = data[data["race"] == ev.id].copy()
        if r.empty:
            return pd.DataFrame(columns=["athlete_id", "position", "status", "qual_position", "team_id", "points"])
        r = r.sort_values("position")
        return pd.DataFrame(
            dict(
                athlete_id=r["rider"].to_numpy(),
                position=r["position"].to_numpy(float),
                status=r["status"].fillna("OK").to_numpy(),
                qual_position=np.nan,
                team_id=None,
                points=r["points"].fillna(0.0).to_numpy(float),
            )
        )
