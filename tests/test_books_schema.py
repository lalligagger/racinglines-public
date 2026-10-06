"""The sportsbook schemas (racinglines/books/schema.py): every draft example under docs/sportsbook/schemas loads, and
a bad kind, odds value or time fails naming its field."""

import copy

import pytest

from racinglines.books import schema as S

pytestmark = pytest.mark.quick

EXAMPLES = sorted(p for p in S.EXAMPLES.glob("*.toml") if p.name != "kinds-vocabulary.toml")


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_every_draft_example_loads(path):
    d = S.load(path)
    assert any(t in d for t in ("event", "venue", "book"))


def test_the_examples_cover_all_three_schemas():
    kinds = {next(t for t in S.VALIDATORS if t in S.load(p)) for p in EXAMPLES}
    assert kinds == {"event", "venue", "book"}


@pytest.fixture
def book():
    return S.load(next(p for p in EXAMPLES if p.name.startswith("books-book_a")))


def test_unmapped_lines_are_listed(book):
    assert [ln["title"] for ln in S.unmapped(book)] == ["Fastest Team Pit Stop"]


def test_bad_kind_names_the_field(book):
    d = copy.deepcopy(book)
    d["lines"][0]["market"] = {"kind": "race_teleport", "driver": "x"}
    with pytest.raises(S.BookError) as ex:
        S.validate_book(d)
    assert any("lines[0].market.kind" in p and "race_teleport" in p for p in ex.value.problems)


def test_bad_odds_name_the_field(book):
    d = copy.deepcopy(book)
    d["lines"][1]["odds"] = 0.8
    with pytest.raises(S.BookError) as ex:
        S.validate_book(d)
    assert any(p.startswith("lines[1].odds") for p in ex.value.problems)


def test_american_odds_need_a_hundred():
    assert S.check_odds(-150, "american") is None
    assert S.check_odds(50, "american")
    assert S.check_odds(2.5, "decimal") is None
    assert S.check_odds(1.0, "decimal")


def test_every_presentation_checks_and_converts():
    good = dict(decimal=1.85, american=-118, fractional="7/4", cents=37, dollars=0.37, prob=0.37)
    bad = dict(decimal=0.9, american=-50, fractional="7/0", cents=100, dollars=1.0, prob=0)
    assert set(good) == set(S.ODDS_FORMATS)
    for fmt in S.ODDS_FORMATS:
        assert S.check_odds(good[fmt], fmt) is None
        assert S.check_odds(bad[fmt], fmt)
        with pytest.raises(ValueError):
            S.to_prob(bad[fmt], fmt)
    assert S.to_prob(1.85, "decimal") == pytest.approx(1 / 1.85)
    assert S.to_prob(-118, "american") == pytest.approx(118 / 218)
    assert S.to_prob(150, "american") == pytest.approx(100 / 250)
    assert S.to_prob("7/4", "fractional") == pytest.approx(4 / 11)
    assert S.to_prob(37, "cents") == pytest.approx(0.37) == S.to_prob(0.37, "dollars") == S.to_prob(0.37, "prob")


def test_present_round_trips_through_each_venue():
    for p in (0.05, 0.37, 0.5, 0.63, 0.95):
        for fmt in S.ODDS_FORMATS:
            q = S.present(p, fmt)
            assert S.check_odds(q, fmt) is None, (p, fmt, q)
            assert S.to_prob(q, fmt) == pytest.approx(p, abs=0.011), (p, fmt, q)
    assert S.present(0.37, "american") == 170 and S.present(0.63, "american") == -170
    assert S.present(0.5, "american") == -100 and S.present(0.37, "fractional") == "17/10"
    assert S.present(0.37, "cents") == 37 and S.present(0.37, "decimal") == 2.7
    with pytest.raises(ValueError):
        S.present(1.0, "cents")


def test_a_kind_that_names_a_team_must_carry_one(book):
    d = copy.deepcopy(book)
    d["lines"][2]["market"] = {"kind": "race_constructor_top"}
    with pytest.raises(S.BookError) as ex:
        S.validate_book(d)
    assert any("names a team" in p for p in ex.value.problems)


def test_event_time_must_be_utc_or_unknown():
    ev = S.load(next(p for p in EXAMPLES if p.name.startswith("events-")))
    d = copy.deepcopy(ev)
    d["sessions"]["race"] = "2026-10-11 12:00"
    with pytest.raises(S.BookError) as ex:
        S.validate_event(d)
    assert any(p.startswith("sessions.race") for p in ex.value.problems)


def test_venue_rules_must_compile():
    v = S.load(next(p for p in EXAMPLES if p.name.startswith("venues-")))
    d = copy.deepcopy(v)
    d["rules"][0]["title"] = "("
    with pytest.raises(S.BookError) as ex:
        S.validate_venue(d)
    assert any("rules[0].title" in p for p in ex.value.problems)
