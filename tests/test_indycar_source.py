from pathlib import Path

from racinglines.sources.indycar.parse import parse_file

FIX = Path(__file__).parent / "fixtures" / "indycar"


def test_parse_indy500_fixture():
    rows = parse_file(FIX / "2025_Indianapolis_500.html")
    assert rows[:3] == [
        {
            "event": "2025_Indianapolis_500",
            "date": "2025-05-25",
            "position": 1,
            "competitor": "Álex Palou",
            "status": "OK",
            "no": 10,
            "team": "Chip Ganassi Racing",
            "engine": "Honda",
            "laps": 200,
            "time_retired": None,
            "pit_stops": 5,
            "grid": 6,
            "laps_led": None,
            "points": 58,
        },
        {
            "event": "2025_Indianapolis_500",
            "date": "2025-05-25",
            "position": 2,
            "competitor": "David Malukas",
            "status": "OK",
            "no": 4,
            "team": "A. J. Foyt Racing",
            "engine": "Chevrolet",
            "laps": 200,
            "time_retired": None,
            "pit_stops": 5,
            "grid": 7,
            "laps_led": None,
            "points": 47,
        },
        {
            "event": "2025_Indianapolis_500",
            "date": "2025-05-25",
            "position": 3,
            "competitor": "Pato O'Ward",
            "status": "OK",
            "no": 5,
            "team": "Arrow McLaren",
            "engine": "Chevrolet",
            "laps": 200,
            "time_retired": None,
            "pit_stops": 5,
            "grid": 3,
            "laps_led": None,
            "points": 46,
        },
    ]


def test_parse_st_petersburg_fixture():
    rows = parse_file(FIX / "2025_Firestone_Grand_Prix_of_St._Petersburg.html")
    assert rows[:3] == [
        {
            "event": "2025_Firestone_Grand_Prix_of_St._Petersburg",
            "date": "2025-03-02",
            "position": 1,
            "competitor": "Álex Palou",
            "status": "OK",
            "no": 10,
            "team": "Chip Ganassi Racing",
            "engine": "Honda",
            "laps": 100,
            "time_retired": "01:51:08.5118",
            "pit_stops": 3,
            "grid": 8,
            "laps_led": 26,
            "points": 51,
        },
        {
            "event": "2025_Firestone_Grand_Prix_of_St._Petersburg",
            "date": "2025-03-02",
            "position": 2,
            "competitor": "Scott Dixon",
            "status": "OK",
            "no": 9,
            "team": "Chip Ganassi Racing",
            "engine": "Honda",
            "laps": 100,
            "time_retired": "01:51:11.3787",
            "pit_stops": 3,
            "grid": 6,
            "laps_led": 5,
            "points": 41,
        },
        {
            "event": "2025_Firestone_Grand_Prix_of_St._Petersburg",
            "date": "2025-03-02",
            "position": 3,
            "competitor": "Josef Newgarden",
            "status": "OK",
            "no": 2,
            "team": "Team Penske",
            "engine": "Chevrolet",
            "laps": 100,
            "time_retired": "01:51:14.7162",
            "pit_stops": 3,
            "grid": 10,
            "laps_led": 2,
            "points": 36,
        },
    ]
