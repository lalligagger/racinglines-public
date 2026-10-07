"""The contenders. Every one sees the same input: the finishing orders of races on dates strictly before the race it
prices (data.races), and the start list of that race. Every one returns a `Pred`: per entrant P(win), P(top 3),
P(top 10) and the matrix P(i finishes ahead of j).

    A        `repo_form`   the repo's results-only form model, called as is: models/nascar_model.py
                           NascarCupRaceChallenger.price (the same code as MotoGPRaceChallenger.price), defaults
    G        `global`      the repo's global results model, called as is: models/model_global.py GlobalModel, defaults
    B        `pl`          Plackett-Luce, MAP log-strengths with recency weights and a Gaussian shrinkage prior
    C        `wl_pl`       Weng-Lin Bayesian online rating, Plackett-Luce variant (openskill's default model),
                           TrueSkill-style mu / sigma per athlete, updated race by race
    C'       `wl_pl_c`     C's ratings priced on the scale its own update assumes (see WengLinPLOwnScale)
    C2       `elo`         pairwise Elo over every pair of a finishing order, updated race by race
    control  `uniform`     learns nothing
    control  `avg_finish`  rank by average finishing percentile over the last starts, as Plackett-Luce strengths

Every setting is a priori (DEFAULTS); none was tuned on the scored seasons.
"""

import dataclasses

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import ndtr

DEFAULTS = {
    "sims": 20000,              # draws for the sampled markets (top 3 / top 10) of B, C, C2, avg_finish
    "repo_sims": 2000,          # A and G: the repo models' own default simulation count
    "pl_half_life_days": 365.0,  # B: a race a year old counts half
    "pl_window_days": 1095.0,   # B: races older than three half-lives (weight < 1/8) are dropped
    "pl_prior_sd": 1.5,         # B: log-strength ~ N(0, 1.5^2): a 1-in-20 favourite (log 19 = 2.9) is ~2 sd
    "wl_mu": 25.0, "wl_sigma": 25.0 / 3, "wl_beta": 25.0 / 6, "wl_tau": 25.0 / 300, "wl_kappa": 1e-4,  # C: openskill
    "elo_k": 32.0, "elo_init": 1500.0,   # C2: K per race, split over the n-1 opponents
    "avg_last": 6,              # avg_finish: last starts averaged (the repo form model's recent_races)
    "avg_temp": 3.0,            # avg_finish: log-strength = -3 x average percentile (best vs worst ~ e^3)
}


@dataclasses.dataclass
class Pred:
    ids: np.ndarray
    win: np.ndarray
    top3: np.ndarray
    top10: np.ndarray
    h2h: np.ndarray            # h2h[i, j] = P(i ahead of j)


def _ord_positions(race):
    """Finishing order as positions: finishers 1..F, every non-finisher F+1 (the repo's --own-fill convention)."""
    n, f = len(race["ids"]), race["n_fin"]
    return np.concatenate([np.arange(1, f + 1), np.full(n - f, f + 1)]).astype(float)


def from_ranks(ids, rank, finished=None):
    """Pred from simulated classifications (n_sims, n): rank 1 = winner; a draw that did not finish never counts
    for win / top n and is behind every finisher."""
    if finished is None:
        finished = np.ones_like(rank, bool)
    r = np.where(finished, rank, rank + 10_000)
    h = np.empty((len(ids), len(ids)))
    for i in range(len(ids)):
        h[i] = (r[:, [i]] < r).mean(0)
    np.fill_diagonal(h, 0.5)
    return Pred(np.asarray(ids), ((r == 1)).mean(0), (r <= 3).mean(0), (r <= 10).mean(0), h)


def from_strengths(ids, theta, rng, sims):
    """Pred from Plackett-Luce log-strengths: win and head-to-head exact (softmax; logistic of the difference),
    top 3 / top 10 sampled with the Gumbel trick."""
    theta = np.asarray(theta, float)
    p = np.exp(theta - theta.max())
    win = p / p.sum()
    h = 1.0 / (1.0 + np.exp(-(theta[:, None] - theta[None, :])))
    perf = theta[None, :] + rng.gumbel(size=(sims, len(theta)))
    rank = (-perf).argsort(1).argsort(1) + 1
    return Pred(np.asarray(ids), win, (rank <= 3).mean(0), (rank <= 10).mean(0), h)


def from_gaussian(ids, mu, sd, rng, sims):
    """Pred from Gaussian performances N(mu, sd^2): head-to-head exact (normal CDF), the rest sampled."""
    mu, sd = np.asarray(mu, float), np.asarray(sd, float)
    h = ndtr((mu[:, None] - mu[None, :]) / np.sqrt(sd[:, None] ** 2 + sd[None, :] ** 2))
    np.fill_diagonal(h, 0.5)
    perf = mu[None, :] + sd[None, :] * rng.standard_normal((sims, len(mu)))
    rank = (-perf).argsort(1).argsort(1) + 1
    return Pred(np.asarray(ids), (rank == 1).mean(0), (rank <= 3).mean(0), (rank <= 10).mean(0), h)


class Model:
    """predict(race, rng) prices a race from what update() has seen; update(race) adds a finished race. The
    walk-forward (evaluate.walk) prices every race of a date before it updates with any of them."""
    name = ""
    online = False

    def __init__(self, s=None):
        self.s = {**DEFAULTS, **(s or {})}
        self.past = []

    def update(self, race):
        self.past.append(race)

    def predict(self, race, rng):
        raise NotImplementedError


class Uniform(Model):
    name = "uniform"

    def predict(self, race, rng):
        n = len(race["ids"])
        h = np.full((n, n), 0.5)
        return Pred(race["ids"], np.full(n, 1 / n), np.full(n, min(3, n) / n), np.full(n, min(10, n) / n), h)


class AvgFinish(Model):
    """Control: mean finishing percentile ((position - 0.5) / starters, non-finishers at F+1) over each athlete's last
    `avg_last` starts; a newcomer is 0.5. Ranked, then turned into probabilities as Plackett-Luce strengths
    -avg_temp x percentile (its head-to-head accuracy depends on the ranking only)."""
    name = "avg_finish"

    def __init__(self, s=None):
        super().__init__(s)
        self.hist = {}

    def update(self, race):
        pct = (_ord_positions(race) - 0.5) / len(race["ids"])
        for a, q in zip(race["ids"], pct):
            self.hist.setdefault(int(a), []).append(q)

    def predict(self, race, rng):
        k = self.s["avg_last"]
        avg = np.array([np.mean(self.hist[a][-k:]) if a in self.hist else 0.5 for a in map(int, race["ids"])])
        return from_strengths(race["ids"], -self.s["avg_temp"] * avg, rng, self.s["sims"])


class RepoForm(Model):
    """A: the repo's NASCAR / MotoGP results-only form model, its price() called on the study's results frame with
    the race's start list as ev.info["field"] (as the replay does). Positions it reads: finishers 1..F, non-finishers
    F+1 (scripts/validate_global_model.py --own-fill)."""
    name = "repo_form"

    def __init__(self, s=None):
        super().__init__(s)
        from racinglines.models.nascar_model import NascarCupRaceChallenger
        self.model = NascarCupRaceChallenger()
        self.settings = self.model.Settings.from_dict({"sims": self.s["repo_sims"]})
        self.rows = []

    def update(self, race):
        for a, p in zip(race["ids"], _ord_positions(race)):
            self.rows.append((race["date"], int(a), p, race["team"].get(int(a), "")))
        self._frame = None

    def predict(self, race, rng):
        from racinglines.models.race_model import Event
        if getattr(self, "_frame", None) is None:
            self._frame = pd.DataFrame(self.rows, columns=["date", "athlete_id", "position", "team"])
        ev = Event(id=race["race_id"], season=race["date"].year, cutoff=race["date"],
                   info={"field": [int(a) for a in race["ids"]]})
        sims = self.model.price(self._frame, ev, self.settings, rng)
        return from_ranks(sims.entrants, sims.rank, sims.finished)


class GlobalRepo(Model):
    """G: the repo's global results model (models/model_global.py), unbound, its own defaults (no sport sets
    [model.defaults]), fed the same frame (status OK / DNF, finishers' positions 1..F) and the race's start list."""
    name = "global"

    def __init__(self, s=None):
        super().__init__(s)
        from racinglines.models.model_global import GlobalModel
        self.model = GlobalModel()
        self.settings = self.model.Settings.from_dict({"sims": self.s["repo_sims"]})
        self.rows = []

    def update(self, race):
        for k, a in enumerate(race["ids"]):
            fin = k < race["n_fin"]
            self.rows.append((race["date"].year, race["race_id"], race["date"], int(a),
                              float(k + 1) if fin else np.nan, "OK" if fin else "DNF"))
        self._hist = None

    def predict(self, race, rng):
        from racinglines.models.race_model import Event
        if getattr(self, "_hist", None) is None:
            d = self.model.load(data=pd.DataFrame(self.rows, columns=["season", "race", "date", "athlete_id",
                                                                      "position", "status"]))
            self._hist = self.model.history(d, self.settings)
        ev = Event(id=race["race_id"], season=race["date"].year, cutoff=race["date"],
                   info={"field": [int(a) for a in race["ids"]]})
        sims = self.model.price(self._hist, ev, self.settings, rng)
        if sims is None:
            return Uniform(self.s).predict(race, rng)
        order = pd.Index(sims.entrants).get_indexer([int(a) for a in race["ids"]])
        return from_ranks(race["ids"], sims.rank[:, order], sims.finished[:, order])


def pl_fit(races, weights, prior_sd, init=None):
    """MAP Plackett-Luce log-strengths: maximize sum_r w_r log PL(order_r) - |theta|^2 / (2 prior_sd^2), where a
    race's likelihood chooses its finishers one by one from everyone still in it (non-finishers are never chosen:
    an unordered tail). L-BFGS with the analytic gradient. Returns (athlete ids, theta)."""
    ath = np.unique(np.concatenate([r["ids"] for r in races]))
    m = max(len(r["ids"]) for r in races)
    idx = np.full((len(races), m), -1)
    for k, r in enumerate(races):
        idx[k, :len(r["ids"])] = np.searchsorted(ath, r["ids"])
    valid = idx >= 0
    nfin = np.array([r["n_fin"] for r in races])
    stage = (np.arange(m)[None, :] < nfin[:, None]) & valid
    w = np.asarray(weights, float)[:, None]
    safe = np.where(valid, idx, 0)
    var = prior_sd ** 2

    def f(theta):
        t = theta[safe]
        e = np.where(valid, np.exp(t), 0.0)
        s = np.cumsum(e[:, ::-1], axis=1)[:, ::-1]                # s[r, k] = sum of e over positions >= k
        s = np.where(valid, s, 1.0)
        ll = (w * stage * (t - np.log(s))).sum()
        c = np.cumsum(np.where(stage, 1.0 / s, 0.0), axis=1)        # sum over stages <= k of 1/S
        g = w * (stage.astype(float) - e * c)
        grad = np.bincount(safe[valid], weights=g[valid], minlength=len(ath))
        return -ll + (theta ** 2).sum() / (2 * var), -grad + theta / var

    x0 = np.zeros(len(ath)) if init is None else np.array([init.get(int(a), 0.0) for a in ath])
    res = minimize(f, x0, jac=True, method="L-BFGS-B", bounds=[(-12, 12)] * len(ath),
                   options=dict(maxiter=500, gtol=1e-6))
    return ath, res.x


class PlackettLuce(Model):
    """B: refit before every race on the races of the last pl_window_days, each weighted 0.5 ** (age /
    pl_half_life_days); an athlete never seen in the window is at the prior mean 0."""
    name = "pl"

    def __init__(self, s=None):
        super().__init__(s)
        self.last = {}

    def predict(self, race, rng):
        t = race["date"]
        win = [r for r in self.past if 0 < (t - r["date"]).days <= self.s["pl_window_days"]]
        theta = {}
        if win:
            age = np.array([(t - r["date"]).days for r in win], float)
            ath, th = pl_fit(win, 0.5 ** (age / self.s["pl_half_life_days"]), self.s["pl_prior_sd"], self.last)
            theta = dict(zip(ath.tolist(), th.tolist()))
            self.last = theta
        return from_strengths(race["ids"], [theta.get(int(a), 0.0) for a in race["ids"]], rng, self.s["sims"])


class WengLinPL(Model):
    """C: Weng & Lin (2011) Bayesian approximation, Plackett-Luce model (Algorithm 4; openskill.py's default),
    one-player teams. Finishers ranked 1..F, non-finishers tied at F+1. Before each race every entrant's sigma^2
    grows by tau^2. Prediction: performance ~ N(mu, sigma^2 + beta^2)."""
    name = "wl_pl"
    online = True

    def __init__(self, s=None):
        super().__init__(s)
        self.mu, self.sig2 = {}, {}

    def _get(self, ids):
        mu = np.array([self.mu.get(int(a), self.s["wl_mu"]) for a in ids])
        s2 = np.array([self.sig2.get(int(a), self.s["wl_sigma"] ** 2) for a in ids])
        return mu, s2

    def predict(self, race, rng):
        mu, s2 = self._get(race["ids"])
        s2 = s2 + self.s["wl_tau"] ** 2
        return from_gaussian(race["ids"], mu, np.sqrt(s2 + self.s["wl_beta"] ** 2), rng, self.s["sims"])

    def update(self, race):
        ids = race["ids"]
        mu, s2 = self._get(ids)
        s2 = s2 + self.s["wl_tau"] ** 2
        beta2 = self.s["wl_beta"] ** 2
        rank = _ord_positions(race)
        c = np.sqrt((s2 + beta2).sum())
        e = np.exp((mu - mu.max()) / c)                        # a common factor cancels in e_i / C_q
        cq = np.array([e[rank >= rq].sum() for rq in rank])    # C_q: everyone ranked at or behind q
        aq = np.array([(rank == rq).sum() for rq in rank])     # A_q: ties with q
        p = e[:, None] / cq[None, :]                           # p[i, q] = e_i / C_q
        at_or_ahead = rank[None, :] <= rank[:, None]           # q ranked at or ahead of i
        eye = np.eye(len(ids))
        omega = (s2 / c) * ((eye - p) / aq[None, :] * at_or_ahead).sum(1)
        gamma = np.sqrt(s2) / c
        delta = gamma * (s2 / c ** 2) * ((p * (1 - p)) / aq[None, :] * at_or_ahead).sum(1)
        mu = mu + omega
        s2 = s2 * np.maximum(1 - delta, self.s["wl_kappa"])
        for a, m_, v in zip(ids, mu, s2):
            self.mu[int(a)], self.sig2[int(a)] = float(m_), float(v)


class WengLinPLOwnScale(WengLinPL):
    """C': the same ratings as C, priced with the Plackett-Luce likelihood its own update assumes: strengths mu / c,
    c = sqrt(sum over the field of sigma^2 + tau^2 + beta^2). openskill's predict_win (used by C) scores a pair on
    the beta scale instead, which in a field of n is about sqrt(n / 2) times sharper than the update's own scale."""
    name = "wl_pl_c"

    def predict(self, race, rng):
        mu, s2 = self._get(race["ids"])
        c = np.sqrt((s2 + self.s["wl_tau"] ** 2 + self.s["wl_beta"] ** 2).sum())
        return from_strengths(race["ids"], mu / c, rng, self.s["sims"])


class Elo(Model):
    """C2: every pair of a finishing order is a game (the one ahead wins; two non-finishers: no game), each pair's
    update K / (n - 1), so one race moves a rating by at most K. P(i ahead of j) = 1 / (1 + 10^((Rj - Ri) / 400)),
    i.e. Plackett-Luce strengths R ln(10) / 400 for the whole order."""
    name = "elo"
    online = True

    def __init__(self, s=None):
        super().__init__(s)
        self.r = {}

    def _get(self, ids):
        return np.array([self.r.get(int(a), self.s["elo_init"]) for a in ids])

    def predict(self, race, rng):
        return from_strengths(race["ids"], self._get(race["ids"]) * np.log(10) / 400, rng, self.s["sims"])

    def update(self, race):
        ids, n, f = race["ids"], len(race["ids"]), race["n_fin"]
        if n < 2:
            return
        r = self._get(ids)
        e = 1.0 / (1.0 + 10 ** ((r[None, :] - r[:, None]) / 400))      # e[i, j] = expected score of i vs j
        pos = np.arange(n)
        score = np.where(pos[:, None] < pos[None, :], 1.0, 0.0)        # i ahead of j in the array order
        dnf = pos >= f
        game = ~(dnf[:, None] & dnf[None, :]) & ~np.eye(n, dtype=bool)
        r = r + self.s["elo_k"] / (n - 1) * ((score - e) * game).sum(1)
        for a, v in zip(ids, r):
            self.r[int(a)] = float(v)


ALL = {m.name: m for m in (RepoForm, GlobalRepo, PlackettLuce, WengLinPL, WengLinPLOwnScale, Elo, Uniform, AvgFinish)}
LABEL = {"repo_form": "A repo form", "global": "G repo global", "pl": "B Plackett-Luce", "wl_pl": "C Weng-Lin PL", "wl_pl_c": "C' Weng-Lin PL, own scale",
         "elo": "C2 Elo pairs", "uniform": "uniform", "avg_finish": "avg finish"}
