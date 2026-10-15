"""rank_logit: the one Plackett-Luce challenger (docs/f1-roadmap.md F1-6, decision log 2026-10-14). A `[sport]
challengers` entry (`racinglines backtest walk-forward <sport> --model rank_logit`); no sport's default price changes.

It is the results core (models/inputs/results.py) with another strength model: the same loading, events (with their
cutoffs and start lists), history, settlement and leakage rule (results on days strictly before the event), the same
retirement draw, and in place of the probit strength + normal noise a Davidson-Luce fit (rank_logit/likelihood.py)
on rankings, sampled by Gumbel-max. The two differ only in the strength model: with the same seed the retirement
draws are the same (the Gumbel noise is drawn as standard normals mapped through Phi, so the generator advances
exactly as the results core's does).

The schema says which round kinds become rankings and their default weights:

    [model.rank_logit.rankings]      # the first kind with a positive weight is the one priced (race; downhill: final)
    race = 1.0
    qual = 0.0                        # listed at 0 so `ranking_weights = "race=1,qual=1"` can turn it on

How it prices an event (every number from results on days strictly before the event):

1. Each past round of a kind with a positive weight is one ranking, weighted kind weight x 0.5 ** (age /
   half_life_days) (rankings below MIN_WEIGHT are left out). Its classified entrants ([results] classified of the
   schema: "status_ok" = status OK with a position, "placed" = any position) are the blocks in position order; the
   other starters (not DNS) are the tail, in every choice set and never chosen. `tie_on = "time_ms"` ties classified
   entrants with identical times; `top_k` keeps the first k blocks and moves the rest to the tail.
2. One MAP fit per event (L-BFGS): theta per athlete (N(0, sd_athlete^2)), with `team_effects` a team effect
   ([model] group; N(0, sd_team^2)), with `kind_sd > 0` an athlete x round-kind offset, the tie parameters (log
   delta ~ N(delta_prior_mean, delta_prior_sd^2)), with `cov` the Laplace covariance.
3. The field (the event's start list; an unseen athlete at the prior mean 0) is drawn by Gumbel-max from its
   log-worths for the priced kind (with `sd_scale`, plus a draw from the covariance per simulation), with the results
   core's retirement draw (retirements classified last). The schema's [model] sessions (race_pole: stage_rank["qual"])
   are drawn from the same fit at that kind (theta + its kind offset; with kind_sd = 0 the same strengths) when the
   kind has a result before the cutoff, on the results core's side generators. The best-lap order is not drawn.

Entries are single athletes: team entries (the likelihood's sum of member worths) are not used by any market yet.
"""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy.special import log_ndtr

from racinglines.models import outcomes as O
from racinglines.models.inputs import results as RES
from racinglines.models.inputs.results import ResultsCore, _day, _frame, _groups, _side_rng
from racinglines.models.rank_logit import likelihood as L
from racinglines.models.rank_logit.settings import settings_class
from racinglines.pipelines import sweep_settings as SS

MIN_WEIGHT = 1e-3          # a ranking weighing less than this (about ten half-lives old) is left out of the fit
PARAM_SEED = 7_501         # salt of the parameter-uncertainty generator (sd_scale)
CLASSIFIED = {
    "status_ok": lambda d: (d["status"] == "OK") & d["position"].notna(),
    "placed": lambda d: d["position"].notna(),
}


class RankLogit(ResultsCore):
    """The rank_logit challenger. Bound to a sport by `for_sport` (race_model.challenger does it); unbound it prices
    whatever frames `load(data=..., sides=..., kinds=...)` is given, with race rankings only."""

    sport = None
    name = "rank_logit"                    # model_runs.model
    rankings = {"race": 1.0}               # the schema's [model.rank_logit.rankings]
    target = "race"                        # the kind priced: the first with a positive weight
    classified = "status_ok"               # the schema's [results] classified
    Settings = settings_class(("race",))
    extra = None                           # {kind: frame}: ranking kinds beyond the target and the sessions

    @classmethod
    def for_sport(cls, sport):
        from racinglines import sports
        schema = sports.load(sport)
        m = schema.get("model", {})
        rl = m.get("rank_logit", {})
        where = f"sports/{sport}.toml [model.rank_logit.rankings]"
        rankings = {str(k): float(v) for k, v in (rl.get("rankings") or {}).items()}
        target = next((k for k, v in rankings.items() if v > 0), None)
        if target is None:
            raise ValueError(f"{where}: name the round kinds that become rankings, one with a positive weight")
        inputs = m.get("inputs") or []
        sessions = [k for k in (m.get("sessions") or []) if "qualifying" in inputs and k != target]
        cats = schema["competition"].get("categories") or {}
        cfg = dict(competition=schema["competition"]["code"],
                   source=m.get("source") or schema.get("replay", {}).get("source"),
                   group=m.get("group"), prior=None, kind=target, times=True,
                   race_key="category" if len(cats) > 1 else "event")
        if sessions:
            cfg["sessions"] = sessions
        return type(f"RankLogit[{sport}]", (cls,), dict(
            sport=sport, cfg=cfg, rankings=rankings, target=target,
            classified=schema.get("results", {}).get("classified", "status_ok"),
            Settings=settings_class(tuple(rankings), rl.get("defaults"), f"sports/{sport}.toml [model.rank_logit.defaults]")))

    # --- data ---------------------------------------------------------------------------------------
    def load(self, engine_url=None, data=None, sides=None, kinds=None):
        """The results core's frames (the priced kind's results, the [model] sessions in self.sides), plus every other
        kind of the rankings table in self.extra (with `data`: `kinds` gives them)."""
        out = super().load(engine_url, data=data, sides=sides)
        if data is not None:
            self.extra = {k: _frame(v) for k, v in (kinds or {}).items()}
            return out
        from racinglines.db.config import get_engine
        more = [k for k in self.rankings if k != self.target and k not in (self.sides or {})]
        params = dict(c=self.cfg["competition"], src=self.cfg["source"])
        with get_engine(engine_url).connect() as conn:
            self.extra = {k: self._load_kind(conn, params, k) for k in more}
        return out

    def _weights(self, settings):
        w = dict(self.rankings)
        w.update(SS.parse_map(settings["ranking_weights"]))
        return w

    def history(self, data, settings):
        """The results core's history (start lists, retirements, side classifications) and every past round of a
        kind with a positive weight as a ranking (weight = the kind's; decay is applied when pricing)."""
        frames = {self.target: data, **{k: f for k, f in (self.sides or {}).items() if k != (self.cfg or {}).get("best_lap")},
                  **(self.extra or {})}
        if settings["team_effects"] and ("team" not in data or not data["team"].notna().any()):
            raise ValueError("team_effects needs [model] group in the schema (a team per result)")
        team = (data.dropna(subset=["team"]).drop_duplicates(["race", "athlete_id"], keep="last")
                .set_index(["race", "athlete_id"])["team"] if settings["team_effects"] else None)
        rounds = []
        for kind, w in self._weights(settings).items():
            f = frames.get(kind)
            if w > 0 and f is not None and len(f):
                if team is not None and kind != self.target:     # other kinds: the entrant's team at that event's race
                    f = f.assign(team=team.reindex(pd.MultiIndex.from_frame(f[["race", "athlete_id"]])).to_numpy())
                rounds += self._rankings(f, kind, w, settings)
        rounds.sort(key=lambda r: r[0])
        return SimpleNamespace(base=super().history(data, settings), days=np.array([r[0] for r in rounds], np.int64),
                               rankings=[r[1] for r in rounds])

    def _rankings(self, f, kind, weight, settings):
        """[(day, Ranking)] of one kind's frame: classified rows in position order (ties by tie_on), the other
        starters in the tail, top_k applied."""
        tie_on, teams = settings["tie_on"], settings["team_effects"]
        if tie_on and tie_on not in f:
            raise ValueError(f"tie_on={tie_on!r}: the {kind} results have no {tie_on} column")
        d = f[f["status"] != "DNS"]
        d = d.assign(_cls=CLASSIFIED[self.classified](d).to_numpy())
        out = []
        for race, g in d.groupby("race", sort=False):
            g = g.sort_values("position", kind="stable")
            team = g["team"].to_numpy() if teams else [None] * len(g)       # a missing team: no team effect
            ent = [L.single(a, t if t is not None and pd.notna(t) else None) for a, t in zip(g["athlete_id"], team)]
            cls = g["_cls"].to_numpy()
            tv = g[tie_on].to_numpy(float) if tie_on else None
            blocks, tail, prev = [], [], None
            for i, e in enumerate(ent):
                if not cls[i]:
                    tail.append(e)
                    continue
                v = tv[i] if tv is not None else np.nan
                if blocks and not np.isnan(v) and v == prev:
                    blocks[-1].append(e)
                else:
                    blocks.append([e])
                prev = v
            if not blocks or len(ent) < 2:
                continue
            rk = L.truncate(L.Ranking(blocks, weight, race, tail, kind), settings["top_k"])
            out.append((_day(g["date"].iloc[0]), rk))
        return out

    # --- pricing ------------------------------------------------------------------------------------
    def price(self, hist, ev, settings, rng):
        """OutcomeSims from results on days before ev.cutoff; None when there are none."""
        b = hist.base
        cut = _day(ev.cutoff)
        n = int(np.searchsorted(b.t, cut, side="left"))
        if n == 0:
            return None
        t, a, fin = b.t[:n], b.a[:n], b.fin[:n]
        hl = settings["half_life_days"]
        w = 0.5 ** ((cut - t) / hl)
        field = list((ev.info or {}).get("field") or [])
        if not field:
            active = pd.Series(w).groupby(a).sum()
            field = sorted(int(x) for x in active.index[active >= 0.5])
            if not field:
                return None
        k = len(field)
        j = pd.Index(field).get_indexer(a)
        inf = j >= 0

        m = int(np.searchsorted(hist.days, cut, side="left"))
        decay = 0.5 ** ((cut - hist.days[:m]) / hl)
        rks = [replace(r, weight=r.weight * x) for r, x in zip(hist.rankings[:m], decay) if r.weight * x >= MIN_WEIGHT]
        if not rks:
            return None
        fit = L.fit(rks, team_effects=settings["team_effects"], sd_athlete=settings["sd_athlete"],
                    sd_team=settings["sd_team"], delta_prior=(settings["delta_prior_mean"], settings["delta_prior_sd"]),
                    max_tie=settings["max_tie"] or None, kind_sd=settings["kind_sd"], cov=settings["cov"])
        groups = _groups(b, n, j, inf, field, ev)
        team = [g if settings["team_effects"] and g is not None and not g.startswith("entrant:") else None
                for g in (groups or [None] * k)]
        entries = [L.single(x, tm) for x, tm in zip(field, team)]
        S = settings["sims"]

        lw = np.broadcast_to(fit.log_worths(entries, self.target), (S, k)).copy()
        if settings["sd_scale"] > 0:
            lw += settings["sd_scale"] * fit._entry_draws(entries, S, _side_rng(rng, PARAM_SEED), self.target)
        perf = lw - np.log(-log_ndtr(rng.standard_normal((S, k))))        # + Gumbel(0, 1): Phi(z) is uniform
        if settings["dnf"]:
            f = fin & inf
            Wf = np.bincount(j[f], weights=w[f], minlength=k)
            Wall = np.bincount(j[inf], weights=w[inf], minlength=k)
            dnf = rng.random((S, k)) < RES.dnf_rate(w, fin, Wall, Wf)
        else:
            dnf = np.zeros((S, k), bool)
        rank = np.argsort(np.argsort(-(perf - 1e3 * dnf), axis=1), axis=1) + 1

        stage_rank = {}
        best = (self.cfg or {}).get("best_lap")
        for i, (name, h) in enumerate(sorted((getattr(b, "sides", None) or {}).items())):
            if name == best or int(np.searchsorted(h.t, cut, side="left")) == 0:
                continue
            g = _side_rng(rng, RES.SIDE_SEED + i)
            sw = fit.log_worths(entries, name)[None, :] + g.gumbel(size=(S, k))
            stage_rank[name] = np.argsort(np.argsort(-sw, axis=1), axis=1) + 1
        return O.OutcomeSims(entrants=[int(x) for x in field], rank=rank, finished=~dnf, groups=groups,
                             stage_rank=stage_rank)
