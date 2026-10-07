"""The global results model: one sport-agnostic pricing model for any sport whose history is a table of
finishing positions (docs/backtest-core.md). It is the "simple / fuzzy-data" model: it needs no laps, no
sectors and no fixed schedule, so it prices a sport where entrants miss events, fields differ in size and
nobody races every round (road cycling), and it is the model every sport with price tapes can be backtested
with.

A sport points at it from its schema, and nothing here names a sport:

    [sport]
    pricing_model = "racinglines.models.model_global:GlobalModel"
    [model]                         # the data hooks (all optional but `source`, which [replay] also supplies)
    source = "motogp_api"           # events.source whose race results are the history
    group = "team"                  # results column / extra key naming the entrant's team (group prior)
    prior = "uci_points"            # results.extra key: a pre-race rating of the entrant (rating prior)
    [model.defaults]                # per-sport defaults for the Settings below (decision-log entries)
    noise = 0.7

How it prices a race (every number from results on days strictly before the event):

1. Each finish becomes a field-size-free strength z = -probit((position - 0.5) / starters), so 2nd of 150 and
   2nd of 5 are not the same evidence.
2. An entrant's strength is the recency-weighted mean of their z (weight 0.5 ** (age / half_life_days)),
   shrunk toward a prior by `prior_weight` pseudo-starts, so a rider with two starts is mostly the prior and
   one with thirty is mostly their results. The prior is 0 (the field average), plus the team's form
   (`group_weight`) and the entrant's rating rank in the field (`rating_weight`) where the schema names them.
3. The race is a draw of strength + noise, with extra spread for entrants with few starts (`uncertainty`),
   and a retirement draw from the entrant's shrunk DNF rate (`dnf`), retirements classified last.

The start list is `ev.info["field"]` (walk-forward builds it from the event's non-DNS rows; the replay passes the
race's results); without one, every entrant with a start in the last half-life is priced.
"""

from dataclasses import replace
from statistics import NormalDist
from types import SimpleNamespace

import numpy as np
import pandas as pd

from racinglines import sports
from racinglines.models import outcomes as O
from racinglines.models.race_model import Event
from racinglines.pipelines import sweep_settings as SS

SETTINGS = [
    SS.Setting("sims", "model", "Simulations per race", "int", 2000, 100, 100000),
    SS.Setting("half_life_days", "model", "Recency half-life (days)", "float", 240.0, 10, 3650,
               help="Age at which a finish counts half."),
    SS.Setting("prior_weight", "model", "Prior weight (pseudo-starts)", "float", 3.0, 0, 100,
               help="How many starts of evidence it takes to outweigh the prior."),
    SS.Setting("noise", "model", "Race-day noise (strength units)", "float", 0.8, 0.05, 3,
               help="Spread of one race around an entrant's strength; a finish's strength is ~N(0,1) across the field."),
    SS.Setting("uncertainty", "model", "Extra spread for few starts", "float", 0.5, 0, 3,
               help="Added variance tau^2 / (decayed starts + 1)."),
    SS.Setting("group_weight", "model", "Team-form prior weight", "float", 0.0, 0, 2,
               help="Needs [model] group in the schema. 0 = off."),
    SS.Setting("rating_weight", "model", "Rating prior weight", "float", 0.0, 0, 2,
               help="Needs [model] prior in the schema. 0 = off."),
    SS.Setting("dnf", "model", "Model retirements", "bool", True,
               help="Draw retirements from each entrant's shrunk DNF rate; off = everyone finishes."),
    SS.Setting("seed", "model", "Monte Carlo seed", "int", None, 0, 2**31 - 1),
]

MIN_FINISHERS = 4          # an event with fewer classified finishers is neither history nor priced
DNF_PRIOR_N = 5.0          # pseudo-starts shrinking an entrant's DNF rate toward the field's
REQUIRED = ("season", "race", "date", "athlete_id", "position", "status")
_N = NormalDist()


class GlobalSettings(SS.Settings):
    SPEC = SETTINGS
    BY = {s.name: s for s in SETTINGS}
    MODEL = [s.name for s in SETTINGS]
    ALIASES = {}

    def _validate(self):
        pass

    def label(self):
        return ", ".join(f"{k}={v}" for k, v in self.changed().items()) or "baseline"


def _settings_class(defaults):
    """GlobalSettings with a sport's [model.defaults] as the defaults (unknown names are an error)."""
    unknown = sorted(set(defaults) - set(GlobalSettings.BY))
    if unknown:
        raise ValueError(f"[model.defaults] names unknown settings {unknown}; choose from {sorted(GlobalSettings.BY)}")
    spec = [replace(s, default=defaults[s.name]) if s.name in defaults else s for s in SETTINGS]
    return type("GlobalSettings", (GlobalSettings,),
                dict(SPEC=spec, BY={s.name: s for s in spec}, MODEL=[s.name for s in spec]))


def _probit(q):
    return np.fromiter((_N.inv_cdf(float(x)) for x in np.ravel(q)), float, np.size(q)).reshape(np.shape(q))


def _day(ts):
    """A timestamp as whole days since 1970 (a date, a naive or an aware timestamp)."""
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return int(ts.normalize().value // 86_400_000_000_000)


def _frame(df):
    """The model's results frame: season, race (event key), date, athlete_id, position, status, and optionally
    name, team, prior, points. One row per entrant per race."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"results frame lacks {missing}")
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["athlete_id"] = d["athlete_id"].astype(int)
    d["position"] = pd.to_numeric(d["position"], errors="coerce")
    d["status"] = d["status"].fillna("OK").astype(str).str.upper()
    return d.sort_values(["date", "race", "position"], kind="stable").reset_index(drop=True)


def _strengths(d):
    """Per row of the non-DNS rows: z (NaN unless the row is a classified finish) and fin (that finish)."""
    d = d[d["status"] != "DNS"]
    starters = d.groupby("race")["athlete_id"].transform("size").to_numpy(float)
    fin = ((d["status"] == "OK") & d["position"].notna() & (d["position"] >= 1)).to_numpy()
    q = np.clip((d["position"].fillna(1).to_numpy(float) - 0.5) / starters, 1e-6, 1 - 1e-6)
    return d, np.where(fin, -_probit(q), np.nan), fin


def _groups(hist, n, j, inf, field, ev):
    """Per entrant of `field`: its team (the group the team markets name), from the event's entry list
    (`ev.info["groups"]`) or else the entrant's latest team in the history before the event; an entrant with neither
    is a group of its own. None when there are no teams at all. Draws nothing, so the prices are unchanged."""
    known = dict((ev.info or {}).get("groups") or {})
    if not known and hist.team is None:
        return None
    last = {}
    if hist.team is not None:
        team = hist.team[:n]
        has = inf & pd.notna(team)
        last = pd.Series(team[has], index=j[has]).groupby(level=0).last().to_dict()
    out = []
    for i, a in enumerate(field):
        g = known.get(int(a), last.get(i))
        out.append(str(g) if g is not None and pd.notna(g) else f"entrant:{int(a)}")
    return out


class GlobalModel:
    """The sport-agnostic results model. `for_sport(code)` (called by race_model.model_class) binds it to a
    sport's schema; unbound it prices whatever frame `load(data=...)` is given."""

    sport = None
    name = "global_results"                # model_runs.model
    Settings = GlobalSettings
    cfg = None                             # {competition, source, group, prior}: the schema's data hooks
    noise_unit = "strength"                # `noise` is in strength units, not finishing places

    @classmethod
    def for_sport(cls, sport):
        s = sports.load(sport)
        m = s.get("model", {})
        source = m.get("source") or s.get("replay", {}).get("source")
        if not source:
            raise ValueError(f"sports/{sport}.toml: GlobalModel needs [model] source (or [replay] source)")
        cfg = dict(competition=s["competition"]["code"], source=source, group=m.get("group"), prior=m.get("prior"))
        return type(f"GlobalModel[{sport}]", (cls,),
                    dict(sport=sport, cfg=cfg, Settings=_settings_class(dict(m.get("defaults", {})))))

    # --- data ---------------------------------------------------------------------------------------
    def load(self, engine_url=None, data=None):
        if data is not None:
            return _frame(data)
        if self.cfg is None:
            raise ValueError("an unbound GlobalModel needs data=; bind it with for_sport(code) to read the database")
        from sqlalchemy import text

        from racinglines.db.config import get_engine

        group, prior = self.cfg["group"], self.cfg["prior"]
        params = dict(c=self.cfg["competition"], src=self.cfg["source"])
        # the schema names a results column ("team") or a results.extra key, as a bound parameter
        gsel = "r.team AS team" if group == "team" else "r.extra->>:gk AS team" if group else "NULL AS team"
        psel = ("CASE WHEN r.extra->>:pk ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN (r.extra->>:pk)::float END AS prior"
                if prior else "NULL::float AS prior")
        if group and group != "team":
            params["gk"] = group
        if prior:
            params["pk"] = prior
        with get_engine(engine_url).connect() as conn:
            df = pd.read_sql(text(f"""
                SELECT s.year AS season, ev.id AS race, ev.name, ev.start_date::date AS date, r.athlete_id,
                       r.position, r.status, {gsel}, {psel}
                FROM results r JOIN rounds ro ON ro.id = r.round_id AND ro.kind = 'race'
                JOIN races ra ON ra.id = ro.race_id JOIN events ev ON ev.id = ra.event_id
                JOIN seasons s ON s.id = ev.season_id JOIN competitions co ON co.id = s.competition_id
                WHERE co.code = :c AND ev.source = :src AND r.athlete_id IS NOT NULL
                ORDER BY ev.start_date, ev.id, r.position NULLS LAST"""), conn, params=params)
        return _frame(df)

    @staticmethod
    def data_through(data):
        return data["date"].max()

    def seasons(self, data, settings):
        return sorted(int(s) for s in data["season"].dropna().unique())

    def events(self, data, settings, seasons=None):
        out = []
        for race, g in data.groupby("race", sort=False):
            started = g[g["status"] != "DNS"]
            if int(((started["status"] == "OK") & started["position"].notna()).sum()) < MIN_FINISHERS:
                continue
            season = int(g["season"].iloc[0])
            if seasons and season not in seasons:
                continue
            name = str(g["name"].iloc[0]) if "name" in g and pd.notna(g["name"].iloc[0]) else str(race)
            info = {"field": sorted(started["athlete_id"].unique().tolist())}
            if "team" in started and started["team"].notna().any():      # the entry list's teams (group markets)
                t = started.dropna(subset=["team"]).drop_duplicates("athlete_id", keep="last")
                info["groups"] = {int(a): str(x) for a, x in zip(t["athlete_id"], t["team"])}
            out.append(Event(id=race, season=season, cutoff=g["date"].iloc[0], name=name, info=info))
        return sorted(out, key=lambda e: (e.cutoff, str(e.id)))

    def history(self, data, settings):
        d, z, fin = _strengths(data[data["race"].isin(self._complete_races(data))])
        return SimpleNamespace(
            t=(d["date"].to_numpy("datetime64[D]").astype(np.int64)), a=d["athlete_id"].to_numpy(), z=z, fin=fin,
            team=d["team"].to_numpy() if "team" in d and d["team"].notna().any() else None,
            rating=d["prior"].to_numpy(float) if "prior" in d and d["prior"].notna().any() else None)

    @staticmethod
    def _complete_races(data):
        started = data[data["status"] != "DNS"]
        ok = ((started["status"] == "OK") & started["position"].notna()).groupby(started["race"]).sum()
        return ok.index[ok >= MIN_FINISHERS]

    # --- pricing ------------------------------------------------------------------------------------
    def price(self, hist, ev, settings, rng):
        """OutcomeSims from finishes on days before ev.cutoff; None when there are none."""
        cut = _day(ev.cutoff)
        n = int(np.searchsorted(hist.t, cut, side="left"))
        if n == 0:
            return None
        t, a, z, fin = hist.t[:n], hist.a[:n], hist.z[:n], hist.fin[:n]
        w = 0.5 ** ((cut - t) / settings["half_life_days"])
        field = list((ev.info or {}).get("field") or [])
        if not field:
            active = pd.Series(w).groupby(a).sum()
            field = sorted(int(x) for x in active.index[active >= 0.5])
            if not field:
                return None
        k = len(field)
        j = pd.Index(field).get_indexer(a)
        inf = j >= 0

        def acc(x, mask):
            return np.bincount(j[mask], weights=x[mask], minlength=k)
        f = fin & inf
        Wf, Wz, Wall = acc(w, f), acc(w * np.where(fin, z, 0.0), f), acc(w, inf)

        prior = np.zeros(k)
        if settings["group_weight"] > 0 and hist.team is not None:
            code, _ = pd.factorize(hist.team[:n])
            ok = fin & (code >= 0)
            tw = np.bincount(code[ok], weights=w[ok], minlength=code.max() + 1 if len(code) else 1)
            tz = np.bincount(code[ok], weights=(w * np.where(fin, z, 0.0))[ok], minlength=len(tw))
            team_mu = tz / (tw + max(settings["prior_weight"], 1e-9))
            last = pd.Series(code[inf & (code >= 0)], index=j[inf & (code >= 0)]).groupby(level=0).last()
            prior[last.index.to_numpy()] += settings["group_weight"] * team_mu[last.to_numpy()]
        if settings["rating_weight"] > 0 and hist.rating is not None:
            r = hist.rating[:n]
            has = inf & ~np.isnan(r)
            last = pd.Series(r[has], index=j[has]).groupby(level=0).last()
            if len(last) >= 3:
                rank = last.rank(method="average").to_numpy()
                prior[last.index.to_numpy()] += settings["rating_weight"] * _probit((rank - 0.5) / len(last))

        den = Wf + settings["prior_weight"]
        mu = np.divide(Wz + settings["prior_weight"] * prior, den, out=prior.copy(), where=den > 0)
        sd = np.sqrt(settings["noise"] ** 2 + settings["uncertainty"] ** 2 / (Wf + 1.0))
        perf = mu + sd * rng.standard_normal((settings["sims"], k))
        if settings["dnf"]:
            rbar = float(w[~fin].sum() / w.sum())
            p_dnf = (Wall - Wf + DNF_PRIOR_N * rbar) / (Wall + DNF_PRIOR_N)
            dnf = rng.random((settings["sims"], k)) < p_dnf
        else:
            dnf = np.zeros((settings["sims"], k), bool)
        rank = np.argsort(np.argsort(-(perf - 1e3 * dnf), axis=1), axis=1) + 1
        return O.OutcomeSims(entrants=[int(x) for x in field], rank=rank, finished=~dnf,
                             groups=_groups(hist, n, j, inf, field, ev))

    def results(self, data, ev):
        """The classification in markets/kinds.settle's shape; unclassified entrants follow the finishers."""
        r = data[data["race"] == ev.id]
        pos = r["position"].to_numpy(float)
        missing = np.isnan(pos)
        pos[missing] = (np.nanmax(pos) if (~missing).any() else 0) + 1 + np.arange(missing.sum())
        return pd.DataFrame(dict(
            athlete_id=r["athlete_id"].to_numpy(), position=pos, status=r["status"].to_numpy(),
            qual_position=np.nan, team_id=r["team"].to_numpy() if "team" in r else None,
            points=r["points"].fillna(0.0).to_numpy(float) if "points" in r else 0.0))
