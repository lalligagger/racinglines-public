"""The compact source note (racinglines/attribution.py, owner 2026-10-13): every sport schema names its results feed(s),
the helper builds one line from schema data, the `source_note` macro renders it, and MCP answers carry `sources`."""

from pathlib import Path

import pandas as pd
import pytest
from jinja2 import Environment, FileSystemLoader

from racinglines import attribution as A
from racinglines import sports

pytestmark = pytest.mark.quick
TEMPLATES = Path(__file__).resolve().parents[1] / "racinglines" / "web" / "templates"


def test_every_sport_schema_has_a_sources_table():
    for code in sports.SPORT_CODES:
        src = sports.load(code).get("sources")
        assert src is not None, f"sports/{code}.toml has no [sources]"
        results = src["results"]
        if results == "unknown":
            continue
        assert results and all(r["name"] and r["url"].startswith("https://") for r in results), code


def test_results_sources_by_sport_or_competition_code():
    by_sport = A.results_sources("f1")
    assert by_sport and by_sport == A.results_sources(sports.load("f1")["competition"]["code"])
    assert A.results_sources("nope") == () and A.results_sources(None) == ()


def test_note_names_feed_venues_and_run():
    n = A.note("road_cycling", ["kalshi", "Polymarket", "private", "some-sportsbook"], run={"id": 12,
               "created_at": pd.Timestamp("2026-10-12T14:05", tz="UTC")})
    assert [r["name"] for r in n["results"]] == ["ProCyclingStats"]
    assert n["prices"] == ["Kalshi", "Polymarket"]                    # our private book and unknown venues are not named
    assert n["fair"] == "racinglines model (run #12, as of 2026-10-12 14:05 UTC)"
    assert n["text"] == ("Sources: results: ProCyclingStats · prices: Kalshi, Polymarket · "
                         "fair values: racinglines model (run #12, as of 2026-10-12 14:05 UTC)")
    assert A.note(None, None)["text"] == ""
    book = A.note("f1", ["og"], sportsbook=True)
    assert book["prices"] == ["OG.com", A.SPORTSBOOK] and book["fair"] is None


def test_source_note_macro_renders_one_line():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    env.globals["sources_note"] = A.note
    tpl = env.from_string('{% from "_macros.html" import source_note %}{{ source_note("nascar", ["kalshi"], 7) }}')
    out = tpl.render().strip()
    assert out.startswith('<p class="legend source-note">Sources: results: <a href="https://cf.nascar.com/"')
    assert "prices: Kalshi" in out and "fair values: racinglines model (run #7)" in out and "\n" not in out
    # without the global (a bare test environment), the macro renders nothing rather than failing
    bare = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    assert bare.from_string('{% from "_macros.html" import source_note %}{{ source_note("f1") }}').render().strip() == ""


def test_an_mcp_answer_carries_sources(monkeypatch):
    from racinglines.mcp import tools as T
    df = pd.DataFrame(dict(id=[1], season=[2026], name=["Singapore Grand Prix"], competition=["f1_wdc"], status=["completed"]))
    monkeypatch.setattr(T.data, "events", lambda conn, competition=None, season=None: df)
    monkeypatch.setattr(T, "_drop_hidden", lambda conn, rows, **cols: rows)
    monkeypatch.setattr(T, "_sport_filter", lambda conn, sport=None, competition=None: competition)
    out = T.list_events(None, competition="f1_wdc")
    assert out["sources"]["results"] == list(A.results_sources("f1"))
    assert out["sources"]["text"].startswith("Sources: results: ")
