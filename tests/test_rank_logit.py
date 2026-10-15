"""rank_logit port checks (docs/f1-roadmap.md F1-6, decision log 2026-10-14): the Davidson-Luce likelihood equals
brute-force subset enumeration, the analytic gradient passes check_grad (ties, tail, teams and kind offsets on), a
tail entry only lowers the likelihood, and top_k reproduces a hand-computed truncated likelihood. Ported from the
owner's pl_ext prototype test. The leakage, synthetic-recovery and walk-forward tests are a later task."""

import itertools

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import check_grad

from racinglines.models.rank_logit import likelihood as L


def dl_sample(alpha, delta, rng):
    """Brute-force Davidson-Luce sampler (small n)."""
    rem, blocks = list(range(len(alpha))), []
    while rem:
        subs, wts = [], []
        for t in range(1, min(len(delta), len(rem)) + 1):
            for S in itertools.combinations(rem, t):
                subs.append(S)
                wts.append(delta[t - 1] * np.prod(alpha[list(S)]) ** (1 / t))
        wts = np.array(wts)
        S = subs[rng.choice(len(subs), p=wts / wts.sum())]
        blocks.append(list(S))
        rem = [i for i in rem if i not in S]
    return blocks


def dl_loglik_brute(blocks, alpha, delta, tail=()):
    """log P(blocks) by enumerating every candidate subset of the remaining set (blocks still to come + the tail)."""
    rem, ll = [i for b in blocks for i in b] + list(tail), 0.0
    for b in blocks:
        den = sum(delta[t - 1] * np.prod(alpha[list(S)]) ** (1 / t)
                  for t in range(1, min(len(delta), len(rem)) + 1) for S in itertools.combinations(rem, t))
        ll += np.log(delta[len(b) - 1] * np.prod(alpha[b]) ** (1 / len(b)) / den)
        rem = [i for i in rem if i not in b]
    return ll


def _flat_prior_problem(rks, **kw):
    return L._Problem(rks, sd_athlete=1e9, sd_team=1e9, delta_prior=(0.0, 1e9), **kw)


def _ids(rk):
    return [[int(e[0][0]) for e in b] for b in rk.blocks], [int(e[0][0]) for e in rk.tail]


def test_likelihood_equals_brute_force_with_a_three_tie_and_a_tail():
    rng = np.random.default_rng(0)
    n = 7
    alpha, delta = np.exp(rng.normal(0, 1, n)), np.array([1.0, 0.4, 0.15])
    rks = [L.Ranking([[L.single(i) for i in b] for b in dl_sample(alpha, delta, rng)]) for _ in range(30)]
    rks.append(L.Ranking([[L.single(0), L.single(1), L.single(2)], [L.single(3)], [L.single(4)]]))     # D = 3
    rks.append(L.Ranking([[L.single(5)], [L.single(1), L.single(6)]], tail=[L.single(0), L.single(3)]))  # a tail
    p = _flat_prior_problem(rks)
    assert p.D == 3
    order = [int(a) for a in p.athletes]
    x = np.r_[np.log(alpha[order]), np.log(delta[1:])]
    brute = sum(dl_loglik_brute(*_ids(r)[:1], alpha, delta, _ids(r)[1]) for r in rks)
    assert -p.negll(x)[0] == pytest.approx(brute, rel=1e-9, abs=1e-9)


def test_gradient_passes_check_grad_with_every_extension_on():
    rng = np.random.default_rng(1)
    n = 8
    alpha, delta = np.exp(rng.normal(0, 1, n)), np.array([1.0, 0.3, 0.1])
    team = {i: f"t{i % 3}" for i in range(n)}
    rks = []
    for r in range(25):
        blocks = dl_sample(alpha, delta, rng)
        kind = "race" if r % 2 else "qual"
        rk = L.Ranking([[L.single(i, team[i]) for i in b] for b in blocks], weight=0.5 ** (r / 10), kind=kind)
        rks.append(L.truncate(rk, 3) if r % 3 == 0 else rk)
    # a two-member team entry
    rks.append(L.Ranking([[(("0", "t0"), ("1", "t1"))], [L.single(2, "t2")]], tail=[L.single(3, "t0")], kind="race"))
    p = L._Problem(rks, team_effects=True, kind_sd=0.5, max_tie=3)
    x = p.x0() + rng.normal(0, 0.3, len(p.x0()))
    err = check_grad(lambda z: p.negll(z)[0], lambda z: p.negll(z)[1], x)
    assert err < 1e-4 * max(1.0, np.abs(p.negll(x)[1]).max())


def test_plain_plackett_luce_gradient():
    rng = np.random.default_rng(2)
    alpha = np.exp(rng.normal(0, 1, 6))
    rks = [L.Ranking([[L.single(i)] for i in np.argsort(-(np.log(alpha) + rng.gumbel(size=6)))]) for _ in range(20)]
    p = L._Problem(rks)
    assert p.D == 1 and len(p.x0()) == 6
    x = rng.normal(0, 0.5, 6)
    assert check_grad(lambda z: p.negll(z)[0], lambda z: p.negll(z)[1], x) < 1e-5


def test_a_tail_entry_never_raises_the_likelihood():
    rng = np.random.default_rng(3)
    for _ in range(20):
        lw = rng.normal(0, 1.5, 5)
        base = L.Ranking([[L.single(0)], [L.single(1), L.single(2)], [L.single(3)]])
        tailed = L.Ranking(base.blocks, tail=[L.single(4)])
        x_base = np.r_[lw[:4], 0.0]                 # log delta_2 = 0
        x_tail = np.r_[lw, 0.0]
        lb = -_flat_prior_problem([base]).negll(x_base)[0]
        p = _flat_prior_problem([tailed])
        lt, g = p.negll(x_tail)
        assert -lt < lb
        assert -g[4] < 0                            # more worth for the tail entry only lowers it further


def test_top_k_reproduces_the_hand_computed_truncated_likelihood():
    w = np.array([2.0, 1.0, 0.5, 0.25])
    rk = L.Ranking([[L.single(i)] for i in range(4)])
    t = L.truncate(rk, 2)
    assert [len(b) for b in t.blocks] == [1, 1] and len(t.tail) == 2
    hand = np.log(w[0] / w.sum()) + np.log(w[1] / w[1:].sum())
    assert -_flat_prior_problem([t]).negll(np.log(w))[0] == pytest.approx(hand, rel=1e-12)
    assert L.truncate(rk, 0) is rk and L.truncate(rk, 4) is rk


def test_fit_recovers_order_and_win_probs_sum_to_one():
    rng = np.random.default_rng(4)
    theta = np.linspace(1.5, -1.5, 6)
    rks = [L.Ranking([[L.single(i)] for i in np.argsort(-(theta + rng.gumbel(size=6)))]) for _ in range(300)]
    f = L.fit(rks)
    est = np.array([f.theta[f._ath_ix[str(i)]] for i in range(6)])
    assert np.all(np.diff(est) < 0)
    sole, inblk = f.win_probs([L.single(i) for i in range(6)])
    assert sole.sum() == pytest.approx(1.0) and inblk == pytest.approx(sole)


# ---- the challenger through the walk-forward engine (synthetic; no database) -------------------------------------
from racinglines import sports  # noqa: E402
from racinglines.cli import backtest as BT  # noqa: E402
from racinglines.core import walk_forward as WF  # noqa: E402
from racinglines.models import race_model as RM  # noqa: E402

TOY = """
[sport]
code = "toy_pl"
name = "Toy PL"
result_kind = "position"
model_family = "toy"
display_order = 9
pricing_model = "racinglines.models.model_global:GlobalModel"
challengers = { rank_logit = "racinglines.models.rank_logit.model:RankLogit" }

[competition]
code = "toy_pl_cup"
name = "Toy PL Cup"

[model]
inputs = ["results", "qualifying"]
source = "toy"
group = "team"
sessions = ["qual"]

[model.rank_logit.rankings]
race = 1.0
qual = 0.0
"""


def toy_frames(seed=5, drivers=12):
    """Two seasons of eight races: Plackett-Luce finishing orders from fixed strengths, a retirement now and then
    (status DNF, no position), times with an occasional dead heat in qualifying."""
    rng = np.random.default_rng(seed)
    theta = np.linspace(1.5, -1.5, drivers)
    race, qual = [], []
    for season in (2025, 2026):
        for k in range(8):
            date = pd.Timestamp(f"{season}-03-01") + pd.Timedelta(weeks=3 * k)
            rid = f"{season}-{k + 1}"
            order = np.argsort(-(theta + rng.gumbel(size=drivers)))
            dnf = set(rng.choice(drivers, 1).tolist()) if k % 2 else set()
            pos = 0
            for i in order:
                ok = i not in dnf
                pos += ok
                race.append(dict(season=season, race=rid, name=f"Race {rid}", date=date, athlete_id=100 + i,
                                 position=pos if ok else np.nan, status="OK" if ok else "DNF", team=f"T{i // 2}",
                                 time_ms=6_000_000 + 1000 * pos if ok else np.nan))
            qorder = np.argsort(-(theta + rng.gumbel(size=drivers)))
            for p, i in enumerate(qorder, 1):
                qual.append(dict(season=season, race=rid, date=date, athlete_id=100 + i, position=p, status="OK",
                                 time_ms=90_000 + 100 * (p - (p == 2))))      # P1 and P2 share a time
    return pd.DataFrame(race), pd.DataFrame(qual)


@pytest.fixture
def toy_pl(tmp_path, monkeypatch):
    (tmp_path / "sports").mkdir()
    for f in sports.SCHEMAS.glob("*.toml"):
        (tmp_path / "sports" / f.name).write_text(f.read_text())
    (tmp_path / "sports" / "toy_pl.toml").write_text(TOY)
    monkeypatch.setattr(sports, "SCHEMAS", tmp_path / "sports")
    sports.load.cache_clear()
    race, qual = toy_frames()
    from racinglines.models.rank_logit.model import RankLogit
    orig = RankLogit.load               # every bound class (for_sport makes a new one) reads the synthetic frames
    monkeypatch.setattr(RankLogit, "load", lambda self, engine_url=None, **kw: orig(self, data=race, sides={"qual": qual}))
    yield tmp_path, RM.challenger("toy_pl", "rank_logit"), orig
    sports.load.cache_clear()


def test_every_challenger_schema_binds_rank_logit():
    for sport, target in (("f1", "race"), ("nascar", "race"), ("motogp", "race"), ("mtb_dh", "final")):
        cls = RM.challenger(sport, "rank_logit")
        assert cls.target == target and cls.name == "rank_logit"
        st = cls.Settings.from_dict({})
        assert (st["top_k"], st["tie_on"], st["team_effects"], st["kind_sd"], st["cov"]) == (0, "", False, 0.0, False)
    assert RM.challenger("mtb_dh", "rank_logit").cfg["race_key"] == "category"


def test_rank_logit_prices_and_scores_through_the_walk_forward_engine(toy_pl):
    _, cls, orig = toy_pl
    m = BT.pricing_model("toy_pl", "rank_logit")
    data = m.load()
    st = m.Settings.from_dict(dict(sims=400, seed=3))
    out = WF.run(m, data, st, seasons=[2026], echo=lambda s: None)
    ev = out["events"]
    assert len(ev) == 8 and {"race_win", "race_podium"} <= set(out["calibration"]["kind"])
    # race_pole comes from the qual side classification (stage_rank["qual"])
    assert "race_pole" in set(out["calibration"]["kind"])
    # the strongest athlete is priced the favourite once there is history
    hist = m.history(data, st)
    e = m.events(data, st, [2026])[-1]
    sims = m.price(hist, e, st, np.random.default_rng(0))
    win = (sims.rank == 1).mean(0)
    assert sims.entrants[int(np.argmax(win))] == 100
    # every extension switched on still prices
    st2 = m.Settings.from_dict(dict(sims=200, seed=3, tie_on="time_ms", top_k=5, team_effects=True, kind_sd=0.3,
                                    ranking_weights="qual=0.5,race=1", cov=True, sd_scale=1.0))
    s2 = m.price(m.history(data, st2), e, st2, np.random.default_rng(0))
    assert s2.rank.shape == (200, len(e.info["field"])) and "qual" in s2.stage_rank


def test_only_results_before_the_cutoff_are_read(toy_pl):
    _, cls, orig = toy_pl
    m = cls()
    data = m.load()
    st = m.Settings.from_dict(dict(sims=300, seed=1))
    e = m.events(data, st, [2026])[3]
    a = m.price(m.history(data, st), e, st, np.random.default_rng(9))
    cut = data[data["date"] < e.cutoff]
    m2 = cls()
    race, qual = toy_frames()
    data2 = orig(m2, data=cut, sides={"qual": qual[qual["date"] < e.cutoff]})
    b = m2.price(m2.history(data2, st), e, st, np.random.default_rng(9))
    assert np.array_equal(a.rank, b.rank) and np.array_equal(a.stage_rank["qual"], b.stage_rank["qual"])


def test_the_retirement_draw_is_the_results_cores(toy_pl):
    _, cls, orig = toy_pl
    from racinglines.models.model_global import GlobalModel
    g = GlobalModel.for_sport("toy_pl")()
    m = cls()
    data, gdata = m.load(), g.load(data=toy_frames()[0], sides={"qual": toy_frames()[1]})
    st, gst = m.Settings.from_dict(dict(sims=500)), g.Settings.from_dict(dict(sims=500))
    e = m.events(data, st, [2026])[2]
    a = m.price(m.history(data, st), e, st, np.random.default_rng(4))
    b = g.price(g.history(gdata, gst), e, gst, np.random.default_rng(4))
    assert a.entrants == b.entrants and np.array_equal(a.finished, b.finished) and (~a.finished).any()


def test_the_cli_runs_rank_logit(toy_pl, capsys):
    tmp, _, _ = toy_pl
    from racinglines.cli import main
    assert main(["backtest", "walk-forward", "toy_pl", "--model", "rank_logit", "--seasons", "2026", "--sims", "300",
                 "--top-k", "3", "--out-dir", str(tmp / "wf")]) == 0
    assert "Walk-forward toy_pl 2026 · sims=300, top_k=3" in capsys.readouterr().out
    assert (tmp / "wf" / "walk_forward_calibration.csv").exists()


def test_the_walk_forward_job_takes_a_challenger():
    """MCP run_job and the Lab share the walk_forward job type (racinglines/web/jobs.py)."""
    from racinglines.web import jobs as J
    jt = J.CATALOG["walk_forward"]
    p = J.parse(jt, dict(sport="nascar", model="rank_logit", venue="none", seasons="2025"))
    assert J._walk_forward_argv(p, "/tmp/wf.log")[-4:] == ["--model", "rank_logit", "--seasons", "2025"]
    with pytest.raises(ValueError, match="not a challenger of nascar"):
        J._walk_forward_argv(dict(p, model="timed_runs"), "/tmp/wf.log")
    assert "--model" not in J._walk_forward_argv(dict(p, model="own"), "/tmp/wf.log")
