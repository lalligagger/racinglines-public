"""Algorithm A/B/C study (racinglines/research/algo_abc): synthetic checks only, no database, no data files."""

import numpy as np
import pandas as pd
import pytest

from racinglines.research.algo_abc import algos as AL
from racinglines.research.algo_abc import data as D
from racinglines.research.algo_abc import evaluate as E


def _synthetic(n_races=60, n_ath=12, field=10, dnf=0.1, seed=0, sport="nascar", start="2023-01-01"):
    """A results frame from Plackett-Luce with known strengths (athlete k has log-strength 2 - 4k / n_ath)."""
    rng = np.random.default_rng(seed)
    theta = 2.0 - 4.0 * np.arange(n_ath) / n_ath
    rows = []
    for r in range(n_races):
        date = pd.Timestamp(start) + pd.Timedelta(days=14 * r)
        ent = rng.choice(n_ath, field, replace=False)
        order = ent[np.argsort(-(theta[ent] + rng.gumbel(size=field)))]
        out = rng.random(field) < dnf
        fin, tail = order[~out], order[out]
        for k, a in enumerate(fin):
            rows.append((sport, 1000 + r, date, 100 + a, k + 1, "OK", f"t{a % 3}"))
        for a in tail:
            rows.append((sport, 1000 + r, date, 100 + a, np.nan, "DNF", f"t{a % 3}"))
    return D.normalize(pd.DataFrame(rows, columns=D.COLUMNS)), theta


def test_pl_fit_gradient_matches_finite_differences():
    frame, _ = _synthetic(n_races=8, n_ath=6, field=5, dnf=0.2)
    races = D.races(frame)
    w = np.linspace(0.5, 1.0, len(races))
    captured = {}
    import racinglines.research.algo_abc.algos as mod
    real = mod.minimize

    def spy(f, x0, **kw):
        captured["f"] = f
        return real(f, x0, **kw)

    mod.minimize = spy
    try:
        ath, _ = AL.pl_fit(races, w, 1.5)
    finally:
        mod.minimize = real
    f = captured["f"]
    x = np.random.default_rng(3).normal(size=len(ath))
    _, g = f(x)
    h = 1e-6
    num = np.array([(f(x + h * e)[0] - f(x - h * e)[0]) / (2 * h) for e in np.eye(len(x))])
    assert np.allclose(g, num, atol=1e-5)


def test_pl_recovers_true_order():
    frame, theta = _synthetic(n_races=150, n_ath=8, field=8, dnf=0.0)
    races = D.races(frame)
    ath, th = AL.pl_fit(races, np.ones(len(races)), 5.0)
    true = theta[ath - 100]
    assert np.corrcoef(true, th)[0, 1] > 0.95
    assert th[0] == th.max()


@pytest.mark.parametrize("name", ["pl", "wl_pl", "wl_pl_c", "elo", "avg_finish", "uniform"])
def test_pred_is_coherent(name):
    frame, _ = _synthetic(n_races=20)
    races = D.races(frame)
    m = AL.ALL[name]({"sims": 4000})
    for r in races[:-1]:
        m.update(r)
    p = m.predict(races[-1], np.random.default_rng(0))
    n = len(races[-1]["ids"])
    assert p.win.shape == (n,) and p.h2h.shape == (n, n)
    assert abs(p.win.sum() - 1) < 1e-2
    assert abs(p.top3.sum() - min(3, n)) < 1e-2
    off = ~np.eye(n, dtype=bool)
    assert np.allclose((p.h2h + p.h2h.T)[off], 1.0, atol=1e-9)
    assert np.all((p.win <= p.top3 + 1e-9) & (p.top3 <= p.top10 + 1e-9))


def test_weng_lin_update_direction_and_shrink():
    """Winner gains, last loses, every sigma shrinks; equal priors give a symmetric update (sum of mu kept)."""
    m = AL.WengLinPL()
    race = dict(race_id=1, date=pd.Timestamp("2024-01-01"), ids=np.array([1, 2, 3, 4]), n_fin=4, team={})
    m.update(race)
    mu = np.array([m.mu[a] for a in (1, 2, 3, 4)])
    s2 = np.array([m.sig2[a] for a in (1, 2, 3, 4)])
    assert np.all(np.diff(mu) < 0)
    assert abs(mu.sum() - 4 * 25.0) < 1e-9
    assert np.all(s2 < (25.0 / 3) ** 2 + (25.0 / 300) ** 2)
    # C' prices those ratings on the update's own scale: softer than C's beta-scale pair probabilities
    rng = np.random.default_rng(0)
    nxt = dict(race, race_id=2, date=pd.Timestamp("2024-01-15"))
    m2 = AL.WengLinPLOwnScale()
    m2.mu, m2.sig2 = dict(m.mu), dict(m.sig2)
    pc = m.predict(nxt, rng)
    pc2 = m2.predict(nxt, rng)
    assert 0.5 < pc2.h2h[0, 3] < pc.h2h[0, 3]


def test_walk_has_no_leakage():
    """A scored race's prediction does not change when later races are removed from the input."""
    frame, _ = _synthetic(n_races=30)
    models = ["pl", "wl_pl", "elo", "avg_finish", "uniform"]
    full = E.walk(frame, "nascar", models, 2023, echo=lambda *_: None)
    cut_date = sorted(frame["date"].unique())[20]
    part = E.walk(frame[frame["date"] <= cut_date], "nascar", models, 2023, echo=lambda *_: None)
    key = ["race_id", "model", "metric"]
    merged = part.merge(full, on=key, suffixes=("_p", "_f"))
    assert len(merged) == len(part) > 0
    assert np.allclose(merged["sum_p"], merged["sum_f"])


def test_learners_beat_uniform_on_strong_signal():
    frame, _ = _synthetic(n_races=80, n_ath=12, field=10)
    rows = E.walk(frame, "nascar", ["pl", "wl_pl_c", "elo", "avg_finish", "uniform"], 2024, echo=lambda *_: None)
    h = rows[rows["metric"] == "h2h_ll"].groupby("model")[["sum", "count"]].sum()
    ll = h["sum"] / h["count"]
    for m in ("pl", "wl_pl_c", "elo", "avg_finish"):
        assert ll[m] < ll["uniform"] - 0.03, (m, ll.to_dict())


def test_summary_and_tables_are_reproducible():
    frame, _ = _synthetic(n_races=30)
    models = ["pl", "elo", "uniform"]
    rows = E.walk(frame, "nascar", models, 2023, echo=lambda *_: None)
    a = E.summarize(rows, n_boot=200, ref="pl")
    b = E.summarize(rows, n_boot=200, ref="pl")
    pd.testing.assert_frame_equal(a, b)
    assert set(a["metric"]) == set(E.METRICS)


def test_read_packed_roundtrip(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("7|2025-03-01|0|11.1 12.2 13d.1\n7|2025-03-01|1|14d.3\n")
    f = D.read_packed([p], "f1")
    r = D.races(f)[0]
    assert list(r["ids"]) == [11, 12, 13, 14] and r["n_fin"] == 2
    assert r["team"][14] == "f1:3"
