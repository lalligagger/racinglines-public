"""The rank_logit likelihood: Davidson-Luce over rankings of blocks of entries (docs/f1-roadmap.md F1-6, decision log
2026-10-14). Ported from the owner's `pl_ext.py` prototype; plain Plackett-Luce is the special case (every block one
entry, no tail, no teams, no kind offsets).

A ranking is an ordered list of blocks (a block of t entries is a t-way tie) plus a tail: entries present in every
stage's choice set but never chosen (non-classified entrants, and with `truncate(ranking, k)` every entry after the
k-th block). At each stage the next block S is chosen from the remaining set R (the unchosen blocks and the tail) with
probability

    delta_|S| * (prod_{i in S} alpha_i)^(1/|S|)  /  sum_{t=1..D} delta_t * e_t(alpha^(1/t) over R)

with delta_1 = 1 and e_t the elementary symmetric polynomial, so the denominator is exact in O(n * D) without
enumerating subsets; D is the largest tie in the data (or `max_tie`).

An entry is a tuple of members (athlete, team); its worth is the SUM of its members' worths (team entries, the
hyper2 model; by Luce's choice axiom ranking teams by their best-placed member is exactly this model). A member's
log-worth is theta[athlete] + phi[team] (team_effects) + eta[athlete, kind] (kind_sd > 0: an athlete x round-kind
offset, the ranking's `kind`), each with a normal prior: N(0, sd_athlete^2), N(0, sd_team^2), N(0, kind_sd^2); log
delta_t ~ N(delta_prior). MAP by L-BFGS with the analytic gradient; `cov=True` adds the Laplace covariance (numerical
Hessian of the gradient). The pricing model (rank_logit/model.py) builds single-member entries only; team entries are
supported here as ported (and tested by the prototype's checks), not yet used by any market.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from scipy.optimize import minimize

Member = tuple  # (athlete_id, team_key or None)
Entry = tuple   # one competitor: a tuple of Members (1 member, or a team)


def single(athlete, team=None) -> Entry:
    """An entry with one member (the usual case)."""
    return ((str(athlete), None if team is None else str(team)),)


@dataclass
class Ranking:
    """Ordered blocks of entries (a block with > 1 entry is a tie), then the unordered tail (in every stage's choice
    set, never chosen). Entries absent from both are not in the ranking at all (partial ranking)."""
    blocks: list
    weight: float = 1.0
    key: object = None
    tail: list = field(default_factory=list)
    kind: object = None          # the round kind (for kind offsets); None = no offset

    def size(self):
        return sum(len(b) for b in self.blocks) + len(self.tail)


def truncate(ranking: Ranking, k: int) -> Ranking:
    """top_k: only the first k blocks are chosen; every entry after them joins the tail (k <= 0: unchanged)."""
    if k <= 0 or len(ranking.blocks) <= k:
        return ranking
    rest = [e for b in ranking.blocks[k:] for e in b]
    return Ranking(ranking.blocks[:k], ranking.weight, ranking.key, rest + list(ranking.tail), ranking.kind)


# ----------------------------------------------------------------------------------------------------------------
# Compiled, padded tensors: R rankings x S stages x N entries x Mm members
# ----------------------------------------------------------------------------------------------------------------
class _Data:
    def __init__(self, rankings: Sequence[Ranking], ath_ix: dict, team_ix: dict, kind_ix: dict | None = None):
        R = len(rankings)
        N = max(r.size() for r in rankings)
        S = max(len(r.blocks) for r in rankings)
        Mm = max(len(e) for r in rankings for e in [*(e for b in r.blocks for e in b), *r.tail])
        self.ath = np.zeros((R, N, Mm), int)
        self.team = np.full((R, N, Mm), -1, int)
        self.mmask = np.zeros((R, N, Mm), bool)
        self.emask = np.zeros((R, N), bool)
        self.kind = np.zeros(R, int)
        block = np.full((R, N), -1, int)
        nblocks = np.zeros(R, int)
        for r, rk in enumerate(rankings):
            i = 0
            nb = len(rk.blocks)
            for j, b in [*((j, b) for j, b in enumerate(rk.blocks)), (nb, rk.tail)]:   # the tail: block nb, never chosen
                for e in b:
                    for m, (a, t) in enumerate(e):
                        self.ath[r, i, m] = ath_ix[a]
                        if t is not None and team_ix:
                            self.team[r, i, m] = team_ix[t]
                        self.mmask[r, i, m] = True
                    self.emask[r, i] = True
                    block[r, i] = j
                    i += 1
            nblocks[r] = nb
            if kind_ix:
                self.kind[r] = kind_ix[rk.kind]
        j = np.arange(S)
        self.svalid = j[None, :] < nblocks[:, None]                                      # (R,S)
        self.A = (self.emask[:, None, :] & (block[:, None, :] >= j[None, :, None])
                  & self.svalid[:, :, None])                                              # remaining set (R,S,N)
        self.B = (block[:, None, :] == j[None, :, None]) & self.svalid[:, :, None]        # chosen block
        self.s = self.B.sum(-1)                                                           # block sizes
        self.cnt = self.A.sum(-1)
        self.w = np.array([rk.weight for rk in rankings], float)
        self.D = int(self.s.max())


def _esym(Y, t):
    """Power sums -> elementary symmetric polys e_0..e_t over the last axis (Newton's identities)."""
    p = [None] + [(Y ** k).sum(-1) for k in range(1, t + 1)]
    e = [np.ones(Y.shape[:-1])]
    for k in range(1, t + 1):
        acc = 0.0
        for i in range(1, k + 1):
            acc = acc + (-1) ** (i - 1) * e[k - i] * p[i]
        e.append(acc / k)
    return e


def _stage_terms(logw, A, delta, cnt):
    """log-scale shift M, the Davidson-Luce denominator Z (scaled by exp(-M)), dZ/dlogw, and each e_t term."""
    L = np.where(A, logw[..., None, :], -np.inf)
    M = L.max(-1)
    M = np.where(np.isfinite(M), M, 0.0)
    Z = np.zeros(A.shape[:-1])
    dZ = np.zeros(A.shape)
    et_all = []
    for t in range(1, len(delta) + 1):
        Y = np.where(A, np.exp((logw[..., None, :] - M[..., None]) / t), 0.0)
        e = _esym(Y, t)
        ok = cnt >= t
        et = np.where(ok, np.maximum(e[t], 0.0), 0.0)
        de = sum((-Y) ** m * e[t - 1 - m][..., None] for m in range(t))
        de = np.where(ok[..., None] & A, de, 0.0)
        Z += delta[t - 1] * et
        dZ += delta[t - 1] * de * Y / t
        et_all.append(et)
    return M, Z, dZ, et_all


class _Problem:
    """The MAP objective of a set of rankings: `negll(x)` -> (-log posterior, gradient). Parameters, in order:
    theta (athletes), phi (teams), eta (athletes x kinds, row-major; only with kind_sd > 0), log delta_2..D."""

    def __init__(self, rankings, *, team_effects=False, sd_athlete=1.5, sd_team=0.75, delta_prior=(-2.0, 2.0),
                 max_tie=None, kind_sd=0.0):
        rankings = [r for r in rankings if r.blocks and r.size() >= 2]
        if not rankings:
            raise ValueError("no ranking with a chosen block and two or more entries")
        ents = [e for r in rankings for e in [*(e for b in r.blocks for e in b), *r.tail]]
        self.athletes = sorted({a for e in ents for a, _ in e})
        self.teams = sorted({t for e in ents for _, t in e if t is not None}) if team_effects else []
        self.kinds = sorted({r.kind for r in rankings}, key=str) if kind_sd > 0 else []
        self.ath_ix = {a: i for i, a in enumerate(self.athletes)}
        self.team_ix = {t: i for i, t in enumerate(self.teams)}
        self.kind_ix = {k: i for i, k in enumerate(self.kinds)}
        self.rankings = rankings
        self.d = _Data(rankings, self.ath_ix, self.team_ix, self.kind_ix)
        self.D = self.d.D if not max_tie else max(self.d.D, int(max_tie))
        self.nA, self.nT, self.nK = len(self.athletes), len(self.teams), len(self.kinds)
        self.nE = self.nA * self.nK
        self.sd_athlete, self.sd_team, self.kind_sd = sd_athlete, sd_team, kind_sd
        self.delta_prior = tuple(delta_prior)

    def x0(self):
        return np.concatenate([np.zeros(self.nA + self.nT + self.nE), np.full(self.D - 1, self.delta_prior[0])])

    def split(self, x):
        a, t, e = self.nA, self.nA + self.nT, self.nA + self.nT + self.nE
        return x[:a], x[a:t], x[t:e].reshape(self.nA, self.nK), x[e:]

    def negll(self, x):
        d, nA, nT, nK, D = self.d, self.nA, self.nT, self.nK, self.D
        theta, phi, eta, ldel = self.split(x)
        delta = np.concatenate([[1.0], np.exp(ldel)])
        lam = theta[d.ath]
        if nT:
            lam = lam + np.where(d.team >= 0, phi[np.maximum(d.team, 0)], 0.0)
        if nK:
            lam = lam + eta[d.ath, d.kind[:, None, None]]
        lam = np.where(d.mmask, lam, -np.inf)
        logw = np.logaddexp.reduce(lam, axis=-1)
        logw = np.where(d.emask, logw, 0.0)
        soft = np.where(d.mmask, np.exp(lam - logw[..., None]), 0.0)

        M, Z, dZ, et = _stage_terms(logw, d.A, delta, d.cnt)
        sv = d.svalid
        s = np.maximum(d.s, 1)
        Zs = np.where(sv, Z, 1.0)
        num = np.log(delta[s - 1]) + (d.B * logw[:, None, :]).sum(-1) / s
        den = M + np.log(Zs)
        ll = (d.w * np.where(sv, num - den, 0.0).sum(-1)).sum()

        wv = d.w[:, None] * sv                                                   # (R,S)
        G = (wv[..., None] * (d.B / s[..., None] - dZ / Zs[..., None])).sum(1)  # (R,N)
        Gm = G[..., None] * soft
        mm = d.mmask
        gth = np.bincount(d.ath[mm], weights=Gm[mm], minlength=nA)
        gph = np.zeros(nT)
        if nT:
            tm = mm & (d.team >= 0)
            gph = np.bincount(d.team[tm], weights=Gm[tm], minlength=nT)
        geta = np.zeros(nA * nK)
        if nK:
            flat = d.ath * nK + d.kind[:, None, None]
            geta = np.bincount(flat[mm], weights=Gm[mm], minlength=nA * nK)
        gdl = np.array([(wv * ((d.s == t) - delta[t - 1] * et[t - 1] / Zs)).sum() for t in range(2, D + 1)])

        mu_d, sd_d = self.delta_prior
        ll += (-0.5 * (theta ** 2).sum() / self.sd_athlete ** 2
               - 0.5 * (phi ** 2).sum() / self.sd_team ** 2
               - 0.5 * ((ldel - mu_d) ** 2).sum() / sd_d ** 2)
        gth = gth - theta / self.sd_athlete ** 2
        gph = gph - phi / self.sd_team ** 2
        if nK:
            ll += -0.5 * (eta ** 2).sum() / self.kind_sd ** 2
            geta = geta - eta.ravel() / self.kind_sd ** 2
        gdl = gdl - (ldel - mu_d) / sd_d ** 2
        return -ll, -np.concatenate([gth, gph, geta, gdl])


@dataclass
class PLFit:
    athletes: list
    teams: list
    kinds: list
    theta: np.ndarray            # athlete log-worths
    phi: np.ndarray              # team log-worth effects (empty if none)
    eta: np.ndarray              # athlete x kind offsets (nA, nK; nK = 0 without kind offsets)
    delta: np.ndarray            # delta_1..delta_D (delta_1 = 1)
    loglik: float                # the log posterior at the optimum
    n_rankings: int
    converged: bool
    _ath_ix: dict = field(repr=False, default_factory=dict)
    _team_ix: dict = field(repr=False, default_factory=dict)
    _kind_ix: dict = field(repr=False, default_factory=dict)
    _cov: np.ndarray | None = field(repr=False, default=None)

    # -- worths ------------------------------------------------------------------------------------------------
    def _member_ix(self, athlete, team=None, kind=None):
        """(log-worth, parameter indices) of a member; an unseen athlete, team or kind is at the prior mean 0."""
        nA, nT, nK = len(self.theta), len(self.phi), len(self.kinds)
        th, ix = 0.0, []
        a = self._ath_ix.get(str(athlete))
        if a is not None:
            th += self.theta[a]
            ix.append(a)
        if team is not None and self._team_ix:
            k = self._team_ix.get(str(team))
            if k is not None:
                th += self.phi[k]
                ix.append(nA + k)
        if kind is not None and nK and a is not None and kind in self._kind_ix:
            k = self._kind_ix[kind]
            th += self.eta[a, k]
            ix.append(nA + nT + a * nK + k)
        return float(th), ix

    def member_log_worth(self, athlete, team=None, kind=None) -> float:
        return self._member_ix(athlete, team, kind)[0]

    def entry_log_worth(self, entry: Entry, kind=None) -> float:
        return float(np.logaddexp.reduce([self.member_log_worth(a, t, kind) for a, t in entry]))

    def log_worths(self, entries, kind=None):
        return np.array([self.entry_log_worth(e, kind) for e in entries])

    def table(self):
        """Athlete log-worths, centred, best first."""
        th = self.theta - self.theta.mean()
        o = np.argsort(-th)
        return [(self.athletes[i], round(float(th[i]), 4)) for i in o]

    # -- prediction --------------------------------------------------------------------------------------------
    def win_probs(self, entries: Sequence[Entry], kind=None):
        """Exact first-block probabilities under Davidson-Luce: (sole_win, in_first_block) aligned with `entries`."""
        logw = self.log_worths(entries, kind)
        A = np.ones((1, 1, len(entries)), bool)
        M, Z, _, _ = _stage_terms(logw[None], A, self.delta, A.sum(-1))
        M, Z = M[0, 0], Z[0, 0]
        sole = np.exp(logw - M) / Z
        inblk = np.zeros(len(entries))
        for t in range(1, len(self.delta) + 1):
            Y = np.exp((logw - M) / t)
            e = _esym(Y, t)
            de = sum((-Y) ** m * e[t - 1 - m] for m in range(t))
            inblk += self.delta[t - 1] * Y * de / Z
        return sole, inblk

    def simulate(self, entries: Sequence[Entry], n_sims=10_000, rng=None, sd_scale=0.0, kind=None):
        """Full finishing orders by Gumbel-max (no ties: negligible for win / podium / top-n markets). sd_scale > 0
        adds parameter uncertainty from the Laplace covariance (fit(..., cov=True)). Positions (n_sims, n), 1 = first."""
        rng = np.random.default_rng(rng)
        lw = np.broadcast_to(self.log_worths(entries, kind), (n_sims, len(entries))).copy()
        if sd_scale > 0:
            lw += sd_scale * self._entry_draws(entries, n_sims, rng, kind)
        g = lw + rng.gumbel(size=lw.shape)
        order = np.argsort(-g, axis=1)
        pos = np.empty_like(order)
        np.put_along_axis(pos, order, np.arange(1, len(entries) + 1)[None, :], axis=1)
        return pos

    def market_probs(self, entries, tops=(1, 3, 10), **kw):
        pos = self.simulate(entries, **kw)
        return {k: (pos <= k).mean(0) for k in tops}

    def _entry_draws(self, entries, n, rng, kind=None):
        """(n, entries) draws of each entry's log-worth minus its MAP value, from the Laplace covariance."""
        if self._cov is None:
            raise ValueError("fit with cov=True to use sd_scale")
        nP = len(self.theta) + len(self.phi) + self.eta.size
        z = rng.multivariate_normal(np.zeros(nP), self._cov[:nP, :nP], size=n, method="eigh")
        out = np.zeros((n, len(entries)))
        for j, e in enumerate(entries):
            lm = []
            for a, t in e:
                v, ix = self._member_ix(a, t, kind)
                lm.append(v + (z[:, ix].sum(1) if ix else np.zeros(n)))
            out[:, j] = np.logaddexp.reduce(np.array(lm), axis=0) - self.entry_log_worth(e, kind)
        return out


def fit(rankings: Sequence[Ranking], *, team_effects=False, sd_athlete=1.5, sd_team=0.75, delta_prior=(-2.0, 2.0),
        max_tie=None, kind_sd=0.0, cov=False, maxiter=2000) -> PLFit:
    """MAP fit by L-BFGS with the analytic gradient (rankings with no chosen block or fewer than two entries are
    dropped). max_tie: D at least this (default / 0: the largest tie in the data). cov: also the Laplace covariance."""
    p = _Problem(rankings, team_effects=team_effects, sd_athlete=sd_athlete, sd_team=sd_team,
                 delta_prior=delta_prior, max_tie=max_tie, kind_sd=kind_sd)
    res = minimize(p.negll, p.x0(), jac=True, method="L-BFGS-B", options={"maxiter": maxiter, "gtol": 1e-7})
    x = res.x
    C = None
    if cov:
        H = _num_hessian(lambda z: p.negll(z)[1], x)
        C = np.linalg.inv((H + H.T) / 2)
    theta, phi, eta, ldel = p.split(x)
    return PLFit(p.athletes, p.teams, p.kinds, theta.copy(), phi.copy(), eta.copy(),
                 np.concatenate([[1.0], np.exp(ldel)]), -float(res.fun), len(p.rankings), bool(res.success),
                 p.ath_ix, p.team_ix, p.kind_ix, C)


def _num_hessian(grad, x, h=1e-5):
    n = len(x)
    H = np.empty((n, n))
    for i in range(n):
        e = np.zeros(n)
        e[i] = h
        H[:, i] = (grad(x + e) - grad(x - e)) / (2 * h)
    return H
