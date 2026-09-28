"""The live core carries a new sport without changes: a synthetic third sport (tests/live_toy.py) with its own
[live] schema, launch spec and body partial, run through the registry, the CLI's step, the replay and the Live
tab. Everything synthetic; no network, no database."""

import pytest

from racinglines import paths, sports
from racinglines.pipelines import live as LV

pytestmark = pytest.mark.quick

SCHEMA = """
[sport]
code = "toy_sprint"
name = "Toy sprint"
result_kind = "time"
model_family = "none"
display_order = 9

[live]
adapter = "live_toy"
[live.poll]
mode = "interval"
interval_s = 10
stale_h = 1
[live.markets]
kinds = ["race_win"]
[live.quoting]
half_spread = 0.04
max_pos = 500.0
skew = 1.0
[live.crowd]
takers = 50
p = 0.05
seed = 7
"""

SPEC = """sport = "toy_sprint"
event = "toy-1"
title = "Toy sprint #1"
[feed]
seed = 3
[live.quoting]
half_spread = 0.05
"""

BODY = """<h1>{{ snap.sport }}</h1>{% for r in rows %}<p>{{ r.key }} {{ "%.2f"|format(r.fair) }} {{ r.bid }}/{{ r.ask }}</p>{% endfor %}<p>fills {{ fills }}</p>"""


@pytest.fixture
def toy(tmp_path, monkeypatch):
    (tmp_path / "sports").mkdir()
    for f in sports.SCHEMAS.glob("*.toml"):                 # the real sports too: the app reads them on import
        (tmp_path / "sports" / f.name).write_text(f.read_text())
    (tmp_path / "sports" / "toy_sprint.toml").write_text(SCHEMA)
    (tmp_path / "live" / "toy_sprint").mkdir(parents=True)
    (tmp_path / "live" / "toy_sprint" / "toy-1.toml").write_text(SPEC)
    monkeypatch.setattr(sports, "SCHEMAS", tmp_path / "sports")
    monkeypatch.setattr(LV, "SPECS", tmp_path / "live")
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    sports.load.cache_clear()
    LV.state.__dict__.pop("cache", None)
    yield tmp_path
    sports.load.cache_clear()


def test_a_third_sport_runs_through_the_core(toy, monkeypatch):
    from racinglines.cli import live as CL
    spec = LV.load_spec("toy_sprint/toy-1")
    assert spec["live"]["quoting"] == dict(half_spread=0.05, max_pos=500.0, skew=1.0)      # the spec over the schema
    ad = LV.adapter("toy_sprint")
    assert ad.__name__ == "live_toy"
    args = type("A", (), dict(no_fetch=True, unfreeze=False, no_sync=True, no_alert=True, now=None))()
    n = 0
    while CL._step(spec, args) is not None:                 # the CLI's step: locked, through the adapter
        n += 1
        assert n < 50
    assert n >= 10
    ev = LV.find("toy-1")
    assert ev["sport"] == "toy_sprint" and ev["title"] == "Toy sprint #1"
    assert LV.state("toy-1") == "replay"                     # over
    times = LV.snap_times("toy-1")
    assert len(times) == n
    book = __import__("json").loads((LV.folder("toy-1") / "book.json").read_text())
    rebuilt, _ = LV.book_at("toy-1")
    assert set(rebuilt) == set(book["markets"]) and all(
        abs(rebuilt[k]["inv"] - book["markets"][k]["inv"]) < 1e-9 for k in book["markets"])
    # the Live tab: the shared shell over the sport's own body partial
    from jinja2 import ChoiceLoader, DictLoader

    from racinglines.web.app import templates
    from racinglines.web.views import live_context
    monkeypatch.setattr(templates.env, "loader", ChoiceLoader([DictLoader({"live_toy_sprint.html": BODY}), templates.env.loader]))
    templates.env.cache = None
    ctx = live_context("toy-1", times[2], True, 0)
    assert ctx["sport"] == "toy_sprint" and ctx["mode"] == "replay" and ctx["t"] == times[2]
    html = templates.get_template("live.html").render(dict(ctx, request=None, user=None, trading=None, live_nav=None,
                                                           signals_nav=None))
    assert "<h1>toy_sprint</h1>" in html and "race_win:Ada" in html and 'id="rp-slider"' in html
    assert "/live?event=toy-1&t=" in html                   # the replay bar keeps the event
    # the report: any sport's run folder
    from racinglines.pipelines import live_report as R
    files = R.write(spec)
    md = files["md"].read_text()
    assert "# Toy sprint #1: event report" in md and "## Fair-price scorecard" in md and "Settled" in md
    sc = R.scorecard(LV.load("toy-1")[2], R.outcomes_of(LV.load("toy-1")[0]))
    assert sc and sc[-1]["brier"] < 1e-9 and {r["kind"] for r in sc} == {"race_win"}   # certain at the end: perfect
    assert "<svg" in files["html"].read_text() and files["pnl.svg"].exists()
