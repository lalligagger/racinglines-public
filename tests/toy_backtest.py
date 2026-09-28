"""A synthetic third sport for the backtest core's tests (tests/test_backtest_toy.py): a toy running race.
Its data source generates seasons of results from a seed, and its pricing model is a shrunk average of past
finishing positions plus noise. It is the whole of what a new sport adds to backtest: this module (data
source + model wrapper, named in its schema as [sport] pricing_model) and the schema. The engine, the market
kinds, calibration, the search queue and the search report are used as they are."""

import numpy as np
import pandas as pd

from racinglines.models import outcomes as O
from racinglines.models.race_model import Event
from racinglines.pipelines import sweep_settings as SS

RUNNERS = 12

SETTINGS = [
    SS.Setting("sims", "model", "Simulations per race", "int", 2000, 100, 100000),
    SS.Setting("shrink", "model", "Form shrinkage (races)", "float", 3.0, 0, 50),
    SS.Setting("noise", "model", "Race-day noise (places)", "float", 2.5, 0.1, 20),
    SS.Setting("seed", "model", "Monte Carlo seed", "int", None, 0, 2**31 - 1),
]


class ToySettings(SS.Settings):
    SPEC = SETTINGS
    BY = {s.name: s for s in SETTINGS}
    MODEL = [s.name for s in SETTINGS]
    ALIASES = {}

    def _validate(self):
        pass

    def label(self):
        return ", ".join(f"{k}={v}" for k, v in self.changed().items()) or "baseline"


class ToyRace:
    sport = "toy_race"
    name = "toy_race"
    Settings = ToySettings

    def load(self, engine_url=None, seed=11):
        """Three seasons of six races: each runner's true pace drifts a little per race; results add noise."""
        rng = np.random.default_rng(seed)
        pace = rng.normal(0, 1.5, RUNNERS)
        rows = []
        for season in (2024, 2025, 2026):
            for k in range(6):
                pace = pace + rng.normal(0, 0.2, RUNNERS)
                t = pace + rng.normal(0, 1.0, RUNNERS)
                pos = t.argsort().argsort() + 1
                date = pd.Timestamp(f"{season}-04-01") + pd.Timedelta(weeks=3 * k)
                rows += [dict(season=season, race=f"{season}-{k + 1}", date=date, runner=f"r{i:02d}", position=int(p))
                         for i, p in enumerate(pos)]
        return pd.DataFrame(rows)

    @staticmethod
    def data_through(data):
        return data["date"].max()

    def seasons(self, data, settings):
        return sorted(int(s) for s in data["season"].unique() if s > data["season"].min())   # the first is history

    def events(self, data, settings, seasons=None):
        d = data.drop_duplicates("race").sort_values("date")
        d = d[d["season"].isin(seasons or self.seasons(data, settings))]
        return [Event(id=r.race, season=int(r.season), cutoff=r.date, name=r.race) for r in d.itertuples()]

    def history(self, data, settings):
        return data

    def price(self, hist, ev, settings, rng):
        past = hist[hist["date"] < ev.cutoff]
        field = sorted(hist.loc[hist["race"] == ev.id, "runner"])
        mid = (RUNNERS + 1) / 2
        g = past.groupby("runner")["position"].agg(["sum", "count"])
        form = ((mid * g["count"] - g["sum"]) / (g["count"] + settings["shrink"])).reindex(field).fillna(0.0).to_numpy()
        t = -form + rng.normal(0, settings["noise"], (settings["sims"], len(field)))
        rank = t.argsort(axis=1).argsort(axis=1) + 1.0
        return O.OutcomeSims(entrants=field, rank=rank, finished=np.ones_like(rank, bool))

    def results(self, data, ev):
        r = data[data["race"] == ev.id]
        return pd.DataFrame(dict(athlete_id=r["runner"].to_numpy(), position=r["position"].to_numpy(float),
                                 status="OK", qual_position=np.nan, team_id=None, points=0.0))
