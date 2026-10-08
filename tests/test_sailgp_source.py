from pathlib import Path

import pytest

from racinglines.sources.sailgp.parse import parse_file

pytestmark = pytest.mark.quick

FIXTURE = Path(__file__).parent / "fixtures" / "sailgp" / "2024-25_SailGP_championship.html"


def test_parse_sailgp_fixture_offline():
    rows = parse_file(FIXTURE)

    assert len(rows) == 144
    assert sorted({row["event_rnd"] for row in rows}) == list(range(1, 13))
    assert rows[:3] == [
        {
            "event_rnd": 1,
            "event_name": "Emirates Dubai Sail Grand Prix",
            "event_date": "November 23–24, 2024",
            "event_winner": "Black Foils",
            "team": "Black Foils",
            "position_in_event": 1,
            "race_by_race_results": {"1": 2, "2": 3, "3": 5, "4": 1, "5": 7, "F": 1},
            "status": "OK",
        },
        {
            "event_rnd": 1,
            "event_name": "Emirates Dubai Sail Grand Prix",
            "event_date": "November 23–24, 2024",
            "event_winner": "Black Foils",
            "team": "Emirates GBR",
            "position_in_event": 2,
            "race_by_race_results": {"1": 5, "2": 8, "3": 2, "4": 3, "5": 3, "F": 2},
            "status": "OK",
        },
        {
            "event_rnd": 1,
            "event_name": "Emirates Dubai Sail Grand Prix",
            "event_date": "November 23–24, 2024",
            "event_winner": "Black Foils",
            "team": "United States",
            "position_in_event": 3,
            "race_by_race_results": {"1": 1, "2": 7, "3": 7, "4": 6, "5": 2, "F": 3},
            "status": "OK",
        },
    ]
