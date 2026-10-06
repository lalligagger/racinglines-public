from conftest import FIX

from racinglines.sources.lemans import parse


FIXTURE = FIX / "lemans" / "wec-2026-fuji-665449.html"


def test_parse_fixture_reads_fuji_race_results_offline():
    rows = parse.parse_file(FIXTURE)
    assert len(rows) >= 3
    assert rows[:3] == [
        {
            "event": "2026 WEC Fuji",
            "date": "2026-09-27",
            "position": 1,
            "team": "Toyota Racing",
            "car_no": 8,
            "drivers": "S. Buemi, B. Hartley, R. Hirakawa",
            "car_model": "Toyota GR010 - Hybrid",
            "laps": 203,
            "time": "6:01'01.299",
            "interval": "",
            "pit_stops": 6,
            "retirement_reason": "",
            "points": 25,
            "status": "OK",
        },
        {
            "event": "2026 WEC Fuji",
            "date": "2026-09-27",
            "position": 2,
            "team": "Alpine Endurance Team",
            "car_no": 36,
            "drivers": "J. Gounon, V. Martins",
            "car_model": "Alpine A424",
            "laps": 203,
            "time": "6:01'01.890",
            "interval": "0.591",
            "pit_stops": 6,
            "retirement_reason": "",
            "points": 18,
            "status": "OK",
        },
        {
            "event": "2026 WEC Fuji",
            "date": "2026-09-27",
            "position": 3,
            "team": "BMW M Team WRT",
            "car_no": 15,
            "drivers": "K. Magnussen, R. Marciello, D. Vanthoor",
            "car_model": "BMW M Hybrid V8",
            "laps": 203,
            "time": "6:01'07.714",
            "interval": "5.824",
            "pit_stops": 6,
            "retirement_reason": "",
            "points": 15,
            "status": "OK",
        },
    ]
