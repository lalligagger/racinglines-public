"""The Lab launcher (no database): schema-backed walk-forwards and strategy sweeps, plus their forms and commands."""

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
    assert cells["motogp"]["og"] is None and cells["nascar"]["og"] == ["nascar_sweep"]
    assert {"walk_forward", "f1_sweep", "f1_season_strategy"} <= set(cells["f1"]["kalshi"])
    assert cells["f1"]["og"] == ["f1_sweep", "f1_season_strategy"]                 # the sweep replays OG.com too
    assert {"walk_forward", "nascar_sweep"} <= set(cells["nascar"]["kalshi"])
    assert {"walk_forward", "motogp_sweep"} <= set(cells["motogp"]["polymarket"])


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


def test_nascar_strategy_sweep_uses_its_sport_settings_and_saved_cli():
    jt = jobs.CATALOG["nascar_sweep"]
    p = jobs.parse(jt, {"year": "2025", "venue": "kalshi", "min_edge": "0.07"})
    assert p["year"] == "2025" and p["settings"]["venue"] == "kalshi"
    assert p["settings"]["min_edge"] == 0.07 and jt.sport_of(p) == "nascar"
    argv = jt.argv(p, "/runs/jobs/job_7.csv")
    assert argv[:7] == ["-m", "racinglines", "nascar", "sweep", "--year", "2025", "--save"]
    assert argv[-2:] == ["--venue", "kalshi"] and "--min-edge" in argv


def test_mcp_sport_sweep_keeps_sport_specific_settings():
    from racinglines.mcp import tools
    _, parsed = tools._job_params("nascar_sweep", {
        "year": "2025", "settings": {"venue": "kalshi", "prior_weight": 4.0}})
    assert parsed["settings"]["prior_weight"] == 4.0
    assert parsed["settings"]["venue"] == "kalshi"
    catalog = tools.list_job_types()
    assert any(x["name"] == "prior_weight" for x in catalog["sport_sweep_settings"]["nascar"])


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
    assert "not listed" in html
    assert 'href="/lab?job=nascar_sweep&amp;venue=og#run"' in html


def test_non_f1_sweep_form_renders_sport_specific_settings():
    from racinglines.pipelines import season_sweep as SW
    from racinglines.pipelines import sweep_settings as SS
    from racinglines.web.app import templates

    jt = jobs.CATALOG["nascar_sweep"]
    cls = SW.settings_class("nascar")
    groups = [(g, dict(SS.GROUPS).get(g, g.title()), [x for x in cls.SPEC if x.group == g])
              for g in dict.fromkeys(x.group for x in cls.SPEC)]
    html = templates.env.get_template("lab_sport_sweep_form.html").render(
        jt=jt, sel_job=jt.code, sweep_form=dict(groups=groups, defaults=cls.from_dict().to_json(),
                                                start=cls.from_dict().to_json(), year="2025"), csrf_token="t")
    assert 'name="job" value="nascar_sweep"' in html
    assert 'name="year"' in html and 'name="prior_weight"' in html and 'name="venue"' in html
    assert "historical simulation, not a live strategy" in html
