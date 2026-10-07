"""
The pricing-model contract (docs/backtest-core.md): what a sport's model gives the shared backtest
engine (racinglines/core/walk_forward.py), the search and, later, the venues.

    m = race_model.get("mtb_dh")
    st = m.Settings.from_dict({...})              # the model's own settings (keys, labels, flags)
    data = m.load(engine_url)                     # everything the model reads, once
    for ev in m.events(data, st, seasons):        # what to price, in time order, with its cutoff
        hist = m.history(data, st)                # (once) what the model learns from
        sims = m.price(hist, ev, st, rng)         # OutcomeSims from data strictly before ev.cutoff
        res = m.results(data, ev)                 # the official result, in markets/kinds.settle's shape

`price` must only read data from before `ev.cutoff`; `results` is read only after pricing, to settle.
Adding a sport means one class with these methods (plus `sports/<code>.toml`): no engine changes.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from racinglines.core import stages as STG
from racinglines.models import outcomes as O

STAGE = STG.spec("mtb_dh")["pre_label"]          # downhill events are priced once, before they start


@dataclass(frozen=True)
class Event:
    id: object                  # the sport's own event id
    season: int
    cutoff: object              # price with data strictly before this
    name: str = ""
    info: dict = field(default_factory=dict, compare=False)   # model-specific (e.g. the start list, format)


class TimedRuns:
    """Downhill (models/timed_runs): one event per race weekend, priced from every run before it with
    its actual start list and format, as walk_forward_season does."""

    sport = "mtb_dh"
    name = "timed_runs"                  # model_runs.model

    from racinglines.models.timed_runs.settings import DHSettings as Settings

    def load(self, engine_url=None, competition="uci_dhi_wc", data=None):
        """The tidy runs frame (database, or `data`: a frame already loaded)."""
        from racinglines.models.timed_runs import RUN_WEIGHTS
        if data is None:
            from racinglines.db.config import get_engine
            from racinglines.db.queries import load_tidy
            data = load_tidy(get_engine(engine_url), competition=competition, with_splits=False)
        return data[data["round"].isin(RUN_WEIGHTS)]

    @staticmethod
    def data_through(data):
        return data["event_date"].max()

    def seasons(self, data, settings, min_events=3):
        """Seasons of the category with min_events or more completed events (as `mtb_dh backtest`)."""
        from racinglines.models.timed_runs import completed_events, select_target
        years = data.loc[data["category"] == settings["category"], "event_date"].astype(str).str[:4]
        out = []
        for y in sorted(years.unique()):
            t = select_target(data, y, settings["category"])
            if len(completed_events(t)) >= min_events:
                out.append(int(y))
        return out

    def events(self, data, settings, seasons=None):
        from racinglines.models.timed_runs import completed_events, event_format, event_order, select_target
        from racinglines.models.timed_runs.season import _event_date
        cat = settings["category"]
        out = []
        for season in seasons or self.seasons(data, settings):
            target = select_target(data, season, cat)
            target = target[target["event_id"].isin(completed_events(target))]
            for e in event_order(target):
                fmt = event_format(target, e)
                cutoff = _event_date(target, e)
                out.append(Event(id=e, season=int(season), cutoff=cutoff,
                                 name=str(target.loc[target["event_id"] == e, "venue"].iloc[0]) if "venue" in target else str(e),
                                 info=dict(format=fmt, target=target, stage=STAGE)))
        return out

    def history(self, data, settings):
        return data

    def price(self, hist, ev, settings, rng):
        """None when the event can't be priced (nothing to learn from yet, or no final results)."""
        from racinglines.models.timed_runs import event_starters, fit_season_model, simulate_weekend
        from racinglines.models.timed_runs.season import _training_rows
        target, fmt = ev.info["target"], ev.info["format"]
        kw = settings.fit_kw()
        train = _training_rows(hist, target, ev.cutoff, kw.pop("train_scope"))
        if not (train["category"] == settings["category"]).any():
            return None
        if not fmt.get("to_final", fmt.get("q1_to_final")):
            return None
        model = fit_season_model(train, category=settings["category"], **kw)
        field = event_starters(target, ev.id)
        with settings.applied():
            sim = simulate_weekend(model, field, n_sims=settings["sims"], rng=rng, fmt=fmt)
        return O.from_timed_runs(field, sim)

    def results(self, data, ev):
        """Final classification (position = final rank, status OK when ranked in the Final), the points
        qualifier's rank, points and who reached the Final."""
        from racinglines.models.timed_runs import actual_event_points
        target = ev.info["target"]
        pts = actual_event_points(target)
        pts = pts[pts["event_id"] == ev.id]
        made = set(target.loc[(target["event_id"] == ev.id) & (target["round"] == "final"), "rider_id"])
        ids = sorted(set(pts["rider_id"]) | made)
        p = pts.set_index("rider_id").reindex(ids)
        return pd.DataFrame(dict(athlete_id=ids, position=p["final_rank"].to_numpy(),
                                 status=np.where(p["final_rank"].notna(), "OK", "DNF"),
                                 qual_position=p["qual_rank"].to_numpy(), team_id=None,
                                 points=p["points"].fillna(0.0).to_numpy(),
                                 reached_final=[r in made for r in ids]))


class PositionSim:
    """F1 (models/position_sim): one event per race, priced as of one minute before the start (qualifying
    known), as the pricing backtest's pre-race mode. The season sweep prices every stage through the
    same price_race; stages from the schema are step 5 of docs/backtest-core.md."""

    sport = "f1"
    name = "f1_sector_sim"

    from racinglines.pipelines.sweep_settings import Settings

    def load(self, engine_url=None, data=None):
        from racinglines.models.position_sim import pricing as run
        if data is None:
            from racinglines.db.config import get_engine
            data = run.Measurements.load(get_engine(engine_url))
        return data

    @staticmethod
    def data_through(data):
        return data.drivers["r_ts"].max()

    def seasons(self, data, settings):
        return sorted(int(y) for y in data.drivers["year"].dropna().unique())

    def events(self, data, settings, seasons=None):
        from racinglines.models.position_sim import pricing as run
        d = data.drivers.drop_duplicates("event_id").sort_values("r_ts")
        if seasons:
            d = d[d["year"].isin(seasons)]
        return [Event(id=r.event_id, season=int(r.year), cutoff=r.r_ts - run.ONE_MIN, name=str(r.venue))
                for r in d.itertuples()]

    def history(self, data, settings):
        from types import SimpleNamespace

        from racinglines.models.position_sim import pricing as run
        with settings.applied():
            return SimpleNamespace(meas=data, hist=run.history(data, settings["track_features"]))

    def price(self, hist, ev, settings, rng):
        from racinglines.models.position_sim import pricing as run
        with settings.applied():
            _, ex = run.price_race(hist.meas, hist.hist, ev.cutoff, ev.id, n_sims=settings["sims"], rng=rng,
                                   use_track=settings["track_features"])
        return O.from_position_sim(ex["entrants"], ex["sim"])

    def results(self, data, ev):
        from racinglines.models.position_sim import practice as PR
        o = data.drivers[data.drivers["event_id"] == ev.id]
        q = data.res[(data.res["event_id"] == ev.id) & (data.res["round"] == "qual")].set_index("athlete_id")["position"]
        out = pd.DataFrame(dict(athlete_id=o["athlete_id"].to_numpy(), position=o["position"].to_numpy(float),
                                status=o["status"].to_numpy(), qual_position=o["athlete_id"].map(q).to_numpy(float),
                                team_id=o["team_key"].to_numpy() if "team_key" in o else None,
                                points=o["points"].to_numpy(float) if "points" in o else 0.0))
        # each practice session's order of best laps (fp1_position, ...: the race_fp<n>_fastest kinds), where stored
        return PR.with_positions(out, PR.classification(data.practice, ev.id))


MODELS = {"mtb_dh": TimedRuns, "f1": PositionSim}


def bind(cls, sport):
    """A sport-agnostic model class (models/model_global) is bound to the sport's schema by its `for_sport`;
    a sport's own model class is returned as it is."""
    return cls.for_sport(sport) if hasattr(cls, "for_sport") else cls


def model_class(sport):
    """The sport's pricing model: [sport] pricing_model in sports/<code>.toml ("module:Class"), so a new
    sport needs its schema and its wrapper and nothing here; the built-in ones otherwise."""
    from importlib import import_module

    from racinglines import sports
    try:
        ref = sports.load(sport)["sport"].get("pricing_model")
    except FileNotFoundError:
        ref = None
    if ref:
        mod, _, cls = ref.partition(":")
        return bind(getattr(import_module(mod), cls), sport)
    if sport not in MODELS:
        raise ValueError(f"no pricing model for sport {sport!r}: set [sport] pricing_model in sports/{sport}.toml")
    return MODELS[sport]


def challengers(sport):
    """{name: "module:Class"}: the sport's challenger models ([sport] challengers in sports/<code>.toml), earlier or
    alternative pricing models kept runnable beside [sport] pricing_model (`backtest walk-forward --model NAME`)."""
    from racinglines import sports
    try:
        return dict(sports.load(sport)["sport"].get("challengers") or {})
    except FileNotFoundError:
        return {}


def challenger(sport, name):
    """The challenger model class `name` of `sport`, bound to the sport's schema as the pricing model is."""
    from importlib import import_module
    refs = challengers(sport)
    if name not in refs:
        raise ValueError(f"sports/{sport}.toml [sport] challengers has no {name!r}; choose from {sorted(refs)}")
    mod, _, cls = refs[name].partition(":")
    return bind(getattr(import_module(mod), cls), sport)


def get(sport):
    return model_class(sport)()
