"""Board cards: an outcome the model doesn't price can't top a card or print "nan%", and a near-certain
probability doesn't read as a settled 100% / 0%."""

import pandas as pd


def test_pct_marks_the_extremes_and_blanks_nan():
    from racinglines.web.app import templates
    pct = templates.env.from_string('{% from "_macros.html" import pct %}{{ pct(p) }}|{{ pct(p, 1) }}')
    assert pct.render(p=0.9966) == "&gt;99%|99.7%"
    assert pct.render(p=0.0027) == "&lt;1%|0.3%"
    assert pct.render(p=0.0001) == "&lt;1%|&lt;0.1%"
    assert pct.render(p=1.0) == "100%|100.0%" and pct.render(p=0.0) == "0%|0.0%"
    assert pct.render(p=0.142) == "14%|14.2%"
    assert pct.render(p=float("nan")) == "–|–" and pct.render(p=None) == "–|–"


def test_unpriced_outcome_sorts_after_priced_and_reads_as_none():
    from racinglines.markets import venues as V
    from racinglines.web import board as B
    base = {("race_win", 1, None, None, None): dict(fair=0.14), ("race_win", 2, None, None, None): dict(fair=0.13)}
    exch = {("race_win", 3, None, None, None): {"polymarket": dict(mid=0.25, outcome="Yes", fair=None)}}
    df = V._assemble(None, base, exch, {}, {1: "A", 2: "B", 3: "Unpriced"})
    top = B._top(df, "race_win")
    assert [o["subject"] for o in top] == ["A", "B", "Unpriced"]
    assert top[2]["fair"] is None and top[2]["pm_mid"] == 0.25
    assert isinstance(df, pd.DataFrame)


def test_bar_draws_nothing_for_nan():
    from racinglines.web.app import templates
    bar = templates.env.from_string('{% from "_macros.html" import bar %}{{ bar(f, m) }}')
    html = bar.render(f=float("nan"), m=0.015)
    assert "nan" not in html and 'class="f"' not in html and 'data-venue="polymarket"' in html
