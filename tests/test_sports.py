"""Sport schemas (sports/*.toml): every schema has the sections the code reads, and the
modules that take their values from a schema agree with it."""

import pytest

from racinglines import exchanges, sports

pytestmark = pytest.mark.quick

REQUIRED = {"sport": ["code", "name", "result_kind", "model_family", "display_order"],
            "league": ["code", "name", "organizer"],
            "competition": ["code", "name", "categories"],
            "markets": ["venues", "standard_kinds"]}


@pytest.mark.parametrize("code", sports.SPORT_CODES)
def test_schema_has_required_keys(code):
    s = sports.load(code)
    assert s["sport"]["code"] == code
    for section, keys in REQUIRED.items():
        missing = [k for k in keys if k not in s.get(section, {})]
        assert not missing, f"sports/{code}.toml [{section}] is missing {missing}"
    for cat, spec in s["competition"]["categories"].items():
        assert len(spec) == 3, f"{code} category {cat}: expected [name, gender, age_group]"


def test_modules_read_the_schemas():
    from racinglines.db import registry
    from racinglines.markets import venues
    from racinglines.models import timed_runs
    from racinglines.models.position_sim import model
    f1, dh = sports.load("f1"), sports.load("mtb_dh")
    assert set(registry.SPORTS) == set(sports.SPORT_CODES)
    assert model.RACE_POINTS == f1["points"]["race"]
    assert model.SESSION_MINUTES["race"] == f1["sessions"]["minutes"]["race"]
    assert timed_runs.FINAL_POINTS == dh["points"]["final"]
    assert venues.STANDARD_KINDS["uci_dhi_wc"] == tuple(dh["markets"]["standard_kinds"])
    known = {v.code for v in venues.VENUES} | set(exchanges.CODES)   # schema venues show only with their switch on
    for code in sports.SPORT_CODES:
        assert set(sports.load(code)["markets"]["venues"]) <= known


def test_schema_supports_generic_fallback_data():
    policy = sports.fallback_rule("nascar")
    assert policy == "official_then_public_summary_fallback"

    fallbacks = sports.fallbacks("nascar")
    assert len(fallbacks) == 1
    assert fallbacks[0]["source"] == "wikipedia"
    assert fallbacks[0]["quality"] == "summary_only"
    assert fallbacks[0]["scope"] == "race_summary"
