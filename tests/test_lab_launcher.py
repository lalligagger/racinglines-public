"""The Lab launcher (no database): every sport with a pricing model, every exchange that lists it, and the job types
that run there; the walk-forward job's form and command line."""

import pytest

from racinglines.web import jobs


def _cells():
    venues, rows = jobs.launcher()
    return venues, {r["code"]: {v: None if c is None else [jt.code for jt in c] for v, c in r["cells"].items()} for r in rows}


def test_launcher_rows_and_columns_come_from_the_schemas():
    venues, cells = _cells()
    assert venues[0] is None and set(venues[1:]) == {"polymarket", "kalshi", "og"}
    assert list(cells) == jobs.modeled_sports() and {"f1", "nascar", "motogp", "mtb_dh"} <= set(cells)
    assert jobs.modeled_sports()[0] == "f1"                                       # schema display_order
    assert all("walk_forward" in cells[code][None] for code in cells)            # every sport runs model-only
    assert cells["mtb_dh"]["kalshi"] is None                                      # not listed there
    assert cells["motogp"]["og"] is None and cells["nascar"]["og"] == []          # OG.com lists NASCAR, no job yet
    assert {"walk_forward", "f1_sweep", "f1_season_strategy"} <= set(cells["f1"]["kalshi"])
    assert cells["f1"]["og"] == ["f1_season_strategy"]
    assert cells["nascar"]["kalshi"] == ["walk_forward"] and cells["motogp"]["polymarket"] == ["walk_forward"]


def test_walk_forward_form_to_command_line():
    jt = jobs.CATALOG["walk_forward"]
    p = jobs.parse(jt, {"sport": "nascar", "venue": "kalshi", "model": "global", "seasons": "2025, 2026"})
    assert p == {"sport": "nascar", "venue": "kalshi", "model": "global", "seasons": "2025 2026"}
    assert jt.argv(p, "/runs/jobs/job_7.csv") == ["-m", "racinglines", "backtest", "walk-forward", "nascar", "--save",
                                                  "--out-dir", "/runs/jobs/job_7", "--model", "global",
                                                  "--seasons", "2025", "2026", "--venue", "kalshi"]
    p = jobs.parse(jt, {})                                                        # defaults: F1, model only, every season
    assert jt.argv(p, "/x/job_1.csv")[3:] == ["walk-forward", "f1", "--save", "--out-dir", "/x/job_1"]
    assert jt.sport_of(p) == "f1" and jt.sport_of(dict(p, sport="motogp")) == "motogp"
    assert jobs.CATALOG["f1_sweep"].sport_of({}) == "f1"


@pytest.mark.parametrize("field,value", [("sport", "indycar"), ("sport", "x; rm"), ("venue", "og"),
                                         ("model", "best"), ("seasons", "last year"), ("seasons", "26")])
def test_walk_forward_knobs_rejected(field, value):
    with pytest.raises(ValueError):
        jobs.parse(jobs.CATALOG["walk_forward"], {field: value})


def test_season_strategy_takes_the_exchange():
    jt = jobs.CATALOG["f1_season_strategy"]
    assert jt.argv(jobs.parse(jt, {"venue": "og"}), "/x.csv")[-2:] == ["--venue", "og"]
    assert jt.argv(jobs.parse(jt, {}), "/x.csv")[-2:] == ["--venue", "polymarket"]


def test_saved_run_line_of_every_command_is_read():
    import re
    pat = re.compile(r"Saved (?:[\w-]+ )*run (\d+)")
    for line, run in (("Saved walk-forward run 12.", "12"), ("Saved sweep run 9 for job 3.", "9"), ("Saved run 4", "4")):
        assert pat.search(line).group(1) == run


def test_launcher_renders_links_that_preset_the_form():
    from racinglines.web.app import templates
    html = templates.env.get_template("lab_run.html").render(
        launch=jobs.launcher(), venue_name=jobs.venue_name, sports=[], knobs={}, sel_job="", events=[], sel_event="",
        sel_cutoff="", csrf_token="t")
    assert '<th class="l">OG.com</th>' in html and '<th class="l">Model only</th>' in html
    assert 'href="/lab?job=walk_forward&amp;sport=nascar&amp;venue=kalshi#run"' in html
    assert 'href="/lab?job=f1_season_strategy&amp;venue=og#run"' in html
    assert "no job yet" in html and "not listed" in html
