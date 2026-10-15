"""rank_logit rule tests (docs/f1-roadmap.md F1-6, ground rules 4; decision log 2026-10-14): the leakage rule (results
on days strictly before the event, nothing else moves a price), synthetic recovery (ties, team effects, top_k), the
toy walk-forward of the default model and of rank_logit through `eval compare`, and the default-price pin. Synthetic
frames, no database. The likelihood port checks are tests/test_rank_logit.py.

No leak guard exists for this path to test: `LeakageError` / `assert_no_leak` (inputs/laps_pricing.py) belong to the
laps pricing core; the results core, and with it rank_logit, enforces the rule by slicing (`searchsorted(day, cutoff,
side="left")`), and the first test below is what holds it."""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from racinglines.core import walk_forward as WF
from racinglines.db import records as REC
from racinglines.markets import payoffs as P
from racinglines.models import race_model as RM
from racinglines.models.rank_logit import likelihood as L
from racinglines.pipelines import eval_compare as EC

# the toy sport of tests/test_rank_logit.py (its schema, frames and fixture): pytest puts tests/ on sys.path
from test_rank_logit import dl_sample, toy_frames, toy_pl  # noqa: F401,E402


def _centred(x):
    x = np.asarray(x, float)
    return x - x.mean()


# ---- 1. the leakage rule ----------------------------------------------------------------------------------------

def _with_the_future(race, qual, cut):
    """The same history plus the future: every race and qualifying result dated on or after `cut` has its finishers
    reversed (the favourite now comes last, the weakest first), and a whole extra season of results is added after."""
    def flip(df):
        df = df.copy()
        late = df["date"] >= cut
        for _, ix in df[late].groupby("race").groups.items():
            g = df.loc[ix].sort_values("position", na_position="last")
            df.loc[g.index, "athlete_id"] = g["athlete_id"].to_numpy()[::-1]
        return df

    def extend(df):
        later = df[df["date"] >= cut]
        return pd.concat([flip(df)] + [flip(later.assign(date=later["date"] + pd.Timedelta(days=400 + 10 * i),
                                                          race=later["race"] + f"-x{i}", season=2027)) for i in range(2)],
                         ignore_index=True)

    return extend(race), extend(qual)


@pytest.mark.parametrize("extras", [dict(), dict(tie_on="time_ms", top_k=5, team_effects=True, kind_sd=0.3,
                                                 ranking_weights="qual=0.5,race=1", cov=True, sd_scale=1.0)],
                         ids=["defaults", "every extension on"])
def test_results_dated_on_or_after_the_event_never_move_a_price(toy_pl, extras):
    _, cls, orig = toy_pl
    m = cls()
    race, qual = toy_frames()
    data = m.load()
    st = m.Settings.from_dict(dict(sims=300, seed=1, **extras))
    ev = m.events(data, st, [2026])[3]
    past_r, past_q = race[race["date"] < ev.cutoff], qual[qual["date"] < ev.cutoff]
    fut_r, fut_q = _with_the_future(race, qual, ev.cutoff)
    assert (fut_r["date"] >= ev.cutoff).sum() > (race["date"] >= ev.cutoff).sum() > 0      # there is a future to leak
    assert not fut_r.equals(race)

    def price(r, q):
        mm = cls()
        d = orig(mm, data=r, sides={"qual": q})
        return mm.price(mm.history(d, st), ev, st, np.random.default_rng(9))

    a, b = price(past_r, past_q), price(fut_r, fut_q)
    assert a is not None and a.entrants == b.entrants
    assert np.array_equal(a.rank, b.rank) and np.array_equal(a.finished, b.finished)
    assert np.array_equal(a.stage_rank["qual"], b.stage_rank["qual"])
    # and the reversed future is a real change: priced from after the reversal's first day, it is a different book
    later = [e for e in m.events(orig(cls(), data=fut_r, sides={"qual": fut_q}), st, [2026]) if e.cutoff > ev.cutoff]
    assert later, "no later event to show that the future data would have moved a price"
    mm = cls()
    d = orig(mm, data=fut_r, sides={"qual": fut_q})
    mp = mm.price(mm.history(d, st), later[-1], st, np.random.default_rng(9))
    m0 = cls()
    p0 = m0.price(m0.history(orig(m0, data=past_r, sides={"qual": past_q}), st), later[-1], st, np.random.default_rng(9))
    assert p0 is None or mp is None or not np.array_equal(p0.rank, mp.rank)


# ---- 2. synthetic recovery --------------------------------------------------------------------------------------

def _fit_theta(f, n):
    return _centred([f.theta[f._ath_ix[str(i)]] for i in range(n)])


@pytest.fixture(scope="module")
def tie_data():
    rng = np.random.default_rng(11)
    n = 12
    theta = _centred(rng.normal(0, 1, n))
    delta = np.array([1.0, 0.3])
    rks = [L.Ranking([[L.single(i) for i in b] for b in dl_sample(np.exp(theta), delta, rng)]) for _ in range(400)]
    return n, theta, rks


def test_ties_recover_the_strengths_and_the_tie_parameter(tie_data):
    n, theta, rks = tie_data
    assert sum(len(b) > 1 for r in rks for b in r.blocks) > 100                     # the data really has ties
    f = L.fit(rks, sd_athlete=10, delta_prior=(-2, 3))
    assert f.converged and len(f.delta) == 2
    assert np.corrcoef(_fit_theta(f, n), theta)[0, 1] > 0.95
    assert abs(f.delta[1] - 0.3) < 0.1


def test_with_tie_on_off_the_same_data_collapses_by_position_order(tie_data):
    n, theta, rks = tie_data
    flat = [L.Ranking([[e] for b in r.blocks for e in b]) for r in rks]            # ties broken by position order
    f = L.fit(flat, sd_athlete=10)
    assert f.converged and len(f.delta) == 1 and f.delta[0] == 1.0
    assert np.corrcoef(_fit_theta(f, n), theta)[0, 1] > 0.9


def test_team_effects_are_recovered_when_a_driver_changes_team():
    rng = np.random.default_rng(12)
    n_teams, per = 5, 2
    theta_d = rng.normal(0, 0.4, n_teams * per)
    phi = np.linspace(1, -1, n_teams)
    team_of = np.repeat(np.arange(n_teams), per)
    rks = []
    for r in range(300):
        tt = team_of.copy()
        if r % 3 == 0:                                       # a third of the rankings: one driver has swapped team
            tt[0], tt[-1] = tt[-1], tt[0]
        order = np.argsort(-(theta_d + phi[tt] + rng.gumbel(size=len(tt))))
        rks.append(L.Ranking([[L.single(f"d{i}", f"t{tt[i]}")] for i in order]))
    f = L.fit(rks, team_effects=True, sd_athlete=1, sd_team=1)
    est = _centred([f.phi[f._team_ix[f"t{k}"]] for k in range(n_teams)])
    assert np.abs(est - _centred(phi)).max() < 0.3


def test_top_k_keeps_the_order_of_the_places_it_counts():
    rng = np.random.default_rng(13)
    n = 10
    theta = np.linspace(2, -2, n)
    full = [L.Ranking([[L.single(i)] for i in np.argsort(-(theta + rng.gumbel(size=n)))]) for _ in range(300)]
    cut = [L.truncate(r, 3) for r in full]
    assert all(len(r.blocks) == 3 and len(r.tail) == n - 3 for r in cut)
    f = L.fit(cut)
    assert f.converged
    est = np.array([f.theta[f._ath_ix[str(i)]] for i in range(n)])
    rho = spearmanr(est[:4], theta[:4])[0]
    assert rho > 0.8 and list(np.argsort(-est)[:4]) == [0, 1, 2, 3]
    assert np.all(np.isfinite(est)) and L.fit(full).converged                       # the full fit runs on the same draws


# ---- 3. the toy walk-forward through eval compare ---------------------------------------------------------------

def test_toy_walk_forward_of_both_models_settles_through_eval_compare(toy_pl, monkeypatch, tmp_path):
    tmp, rl, orig = toy_pl
    monkeypatch.setenv(REC.ROOT_ENV, str(tmp / "records"))
    race, qual = toy_frames()
    own = RM.get("toy_pl")
    rlm = rl()
    models = {1: (own, own.load(data=race, sides={"qual": qual})), 2: (rlm, rlm.load())}
    n_events = 8
    sport = "toy_pl"
    seen = {}
    for run_id, (m, data) in models.items():
        out = WF.run(m, data, m.Settings.from_dict(dict(seed=3, sims=300)), seasons=[2026], echo=lambda s: None,
                     keep_sims=True)
        assert len(out["sims"]) == n_events
        frames_ = [s.to_records(run_id, sport, sport, ev.season, ev.id, ev.name, "pre_race", ev.cutoff)
                   for ev, s in out["sims"]]
        REC.write(run_id, REC.concat(frames_))
        seen[run_id] = set(REC.read(run_id)["kind"])
    both = seen[1] & seen[2]
    assert {"race_win", "race_podium"} <= both

    m2, data2 = models[2]
    evs = {str(e.id): e for e in m2.events(data2, m2.Settings.from_dict({}), None)}

    def results_for(_sport, event_id):                    # the official classification, as db_results marks it
        e = evs.get(event_id)
        return None if e is None else P.mark_sport(m2.results(data2, e), getattr(m2, "sport", None))

    res = EC.run(1, 2, out_dir=tmp / "eval", echo=lambda s: None, results_for=results_for)
    assert res["unsettled"] == 0 and res["counts"]["only_a"] == res["counts"]["only_b"] == 0
    s = res["summary"]
    assert set(s["kind"]) == both
    allrows = s[s["season"] == "all"]
    assert set(allrows["kind"]) == both and (allrows["n_events"] == n_events).all()
    assert (s[s["season"] == "2026"]["n_events"] == n_events).all()
    assert res["paired"]["y"].notna().all() and res["counts"]["paired"] == len(res["paired"]) > 0
    assert (tmp / "eval" / "compare.csv").exists()


# ---- 4. the default-price pin ("own golden") --------------------------------------------------------------------

# rank_logit with every setting at its default, seed 1, on toy_frames(seed=5), the fourth 2026 event, 1000 simulations:
# P(win) per athlete id. It changes only with a deliberate model change and its own decision-log line in
# docs/f1-roadmap.md (the existing goldens, tests/golden/, are not touched and UPDATE_GOLDEN is never set here).
PIN_WIN = {100: 0.135, 101: 0.184, 102: 0.112, 103: 0.094, 104: 0.116, 105: 0.091, 106: 0.057, 107: 0.046,
           108: 0.043, 109: 0.034, 110: 0.060, 111: 0.028}


def test_default_rank_logit_race_win_prices_are_pinned(toy_pl):
    _, cls, _ = toy_pl
    m = cls()
    data = m.load()
    st = m.Settings.from_dict(dict(sims=1000, seed=1))
    assert set(st.changed()) <= {"sims", "seed"}                                     # every model setting at its default
    ev = m.events(data, st, [2026])[3]
    sims = m.price(m.history(data, st), ev, st, np.random.default_rng(1))
    win = dict(zip(sims.entrants, (sims.rank == 1).mean(0)))
    assert {int(k): round(float(v), 6) for k, v in win.items()} == pytest.approx(PIN_WIN, abs=5e-7)


# ---- 5. one subject key for every writer (docs/todo.md "Prediction records, cross-engine pairing") ----------------

def test_the_default_model_rank_logit_and_a_run_times_style_writer_key_an_athlete_the_same(toy_pl):
    """The toy sport's default model, `--model rank_logit` and the run-times core's shape of simulations (entrants
    "ath:<id>", from_timed_runs) write the same (kind, subject, params) for the same athlete, so `eval compare`
    pairs them: the subject is "<id>" and a head-to-head's opponent_id the int, whatever the engine."""
    from racinglines.models import outcomes as O
    race, qual = toy_frames()
    own, rlm = RM.get("toy_pl"), toy_pl[1]()
    data_own, data_rl = own.load(data=race, sides={"qual": qual}), rlm.load()
    ev = own.events(data_own, own.Settings.from_dict({}), [2026])[2]
    keys = ["kind", "subject", "params"]
    frames_ = {}
    for name, m, data in (("default", own, data_own), ("rank_logit", rlm, data_rl)):
        st = m.Settings.from_dict(dict(seed=3, sims=200))
        e = next(e for e in m.events(data, st, [2026]) if e.id == ev.id)
        sims = m.price(m.history(data, st), e, st, np.random.default_rng(3))
        if name == "default":                                  # the run-times core: the same draws, rider_id entrants
            dh = O.from_timed_runs([f"ath:{a}" for a in sims.entrants],
                                   dict(final_rank=sims.rank, qual_rank=sims.rank, made_final=sims.finished, points=None))
            frames_["timed_runs"] = dh.to_records(3, "toy_pl", "timed_runs", 2026, e.id, e.name, "pre_race", e.cutoff,
                                                  kinds=["race_win", "race_h2h"])
        frames_[name] = sims.to_records(len(frames_) + 1, "toy_pl", name, 2026, e.id, e.name, "pre_race", e.cutoff,
                                        kinds=["race_win", "race_h2h"])
    want = frames_["default"][keys].sort_values(keys).reset_index(drop=True)
    for name, f in frames_.items():
        pd.testing.assert_frame_equal(f[keys].sort_values(keys).reset_index(drop=True), want, obj=name)
    assert set(want.query("kind == 'race_win'")["subject"]) == {str(100 + i) for i in range(12)}
    assert not want["subject"].str.startswith("ath:").any() and not want["params"].str.contains("ath:").any()
    for n, f in frames_.items():                              # and every pair of writers pairs completely
        c = EC.pair(frames_["default"], f)[1]
        assert c["paired"] == len(want) and c["only_a"] == c["only_b"] == 0, n
