"""Plackett-Luce challenger (engine roadmap E7; docs/novig-and-model-bakeoff.md): a ranking-likelihood model on
the same finishing-position history as the global model (racinglines/models/model_global.py), so the two differ
only in the algorithm.

How it prices a race (every number from results on days strictly before the event):

1. Each past race's classified finishing order is one Plackett-Luce observation, weighted by recency
   (0.5 ** (age / half_life_days)). Retirements and unclassified entrants are left out of the order.
2. Strengths gamma are the weighted maximum-likelihood fit by Hunter's (2004) MM algorithm, regularised by
   `prior_weight` pseudo-comparisons per entrant against an average entrant (gamma = 1), half won and half lost,
   so an entrant with few results stays near the field average and one never seen is exactly average.
3. The race is a Plackett-Luce draw (Gumbel-max: log gamma + Gumbel noise per simulation), with the global
   model's retirement draw (`dnf`), retirements classified last.

`noise`, `uncertainty`, `group_weight` and `rating_weight` are not used: Plackett-Luce has its own fixed noise
(the Gumbel), and this first version has no team or rating prior.
"""

import numpy as np
import pandas as pd

from racinglines.models import outcomes as O
from racinglines.models.model_global import DNF_PRIOR_N, GlobalModel, _day

MM_ITERS = 200
MM_TOL = 1e-6
MIN_WEIGHT = 1e-3          # races older than this weight are dropped from the fit (about 10 half-lives)


def fit_pl(orders, weights, n, prior, iters=MM_ITERS, tol=MM_TOL):
    """Weighted Plackett-Luce strengths for entrants 0..n-1 by Hunter's MM algorithm.

    orders: list of int arrays, each a race's classified finishers, best first. weights: one weight per race.
    prior: pseudo-comparisons per entrant against a fixed average entrant (gamma = 1), half won.
    Returns gamma (mean 1 over entrants with evidence is not enforced; the prior anchors the scale)."""
    wins = np.full(n, prior / 2.0)
    for o, w in zip(orders, weights):
        wins[o[:-1]] += w                          # every place but last is a "win" of one choice stage
    g = np.ones(n)
    for _ in range(iters):
        den = prior / (g + 1.0)
        for o, w in zip(orders, weights):
            tail = np.cumsum(g[o][::-1])[::-1]     # sum of strengths still in the choice set at each stage
            inv = w / tail[:-1]                    # the last stage has one choice and no information
            den[o] += np.concatenate([np.cumsum(inv), [inv.sum()]])
        new = wins / den
        if np.max(np.abs(np.log(new) - np.log(g))) < tol:
            g = new
            break
        g = new
    return g


class PlackettLuceModel(GlobalModel):
    """Plackett-Luce on finishing orders; data, events and settlement are the global model's."""

    name = "plackett_luce"

    def price(self, hist, ev, settings, rng):
        cut = _day(ev.cutoff)
        n = int(np.searchsorted(hist.t, cut, side="left"))
        if n == 0:
            return None
        t, a, fin, race = hist.t[:n], hist.a[:n], hist.fin[:n], hist.race[:n]
        pos = hist.position[:n]
        w = 0.5 ** ((cut - t) / settings["half_life_days"])
        field = list((ev.info or {}).get("field") or [])
        if not field:
            active = pd.Series(w).groupby(a).sum()
            field = sorted(int(x) for x in active.index[active >= 0.5])
            if not field:
                return None
        keep = fin & (w >= MIN_WEIGHT)
        ids = pd.Index(sorted(set(a[keep].tolist()) | set(field)))
        df = pd.DataFrame(dict(race=race[keep], i=ids.get_indexer(a[keep]), pos=pos[keep], w=w[keep]))
        orders, weights = [], []
        for _, g in df.sort_values(["race", "pos"]).groupby("race", sort=False):
            if len(g) >= 2:
                orders.append(g["i"].to_numpy())
                weights.append(float(g["w"].iloc[0]))
        gamma = fit_pl(orders, weights, len(ids), settings["prior_weight"])
        k = len(field)
        lg = np.log(gamma[ids.get_indexer(field)])
        perf = lg + rng.gumbel(size=(settings["sims"], k))
        if settings["dnf"]:
            j = pd.Index(field).get_indexer(a)
            inf = j >= 0
            Wall = np.bincount(j[inf], weights=w[inf], minlength=k)
            Wf = np.bincount(j[inf & fin], weights=w[inf & fin], minlength=k)
            rbar = float(w[~fin].sum() / w.sum())
            p_dnf = (Wall - Wf + DNF_PRIOR_N * rbar) / (Wall + DNF_PRIOR_N)
            dnf = rng.random((settings["sims"], k)) < p_dnf
        else:
            dnf = np.zeros((settings["sims"], k), bool)
        rank = np.argsort(np.argsort(-(perf - 1e3 * dnf), axis=1), axis=1) + 1
        return O.OutcomeSims(entrants=[int(x) for x in field], rank=rank, finished=~dnf)

    def history(self, data, settings):
        h = super().history(data, settings)
        d = data[data["race"].isin(self._complete_races(data))]
        d = d[d["status"] != "DNS"]                 # the same rows, in the same order, as the global history
        h.race = d["race"].to_numpy()
        h.position = d["position"].to_numpy(float)
        return h
