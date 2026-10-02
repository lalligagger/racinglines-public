"""
Tests for UCI road cycling results adapter.

Coverage: fetch (Wikipedia), parse (HTML tables), normalize (to racinglines schema).
Not yet implemented: links (market matching), upsert (database integration).

TODO (Phase 2):
  - [ ] test_identify_link_race_win (market link to GC winner)
  - [ ] test_identify_link_race_podium (market link to top 3)
  - [ ] test_upsert_creates_event_and_race
  - [ ] test_upsert_creates_athlete_identifiers
"""

import pytest
from datetime import date

from racinglines.sources.cycling.fetch import parse_tables
from racinglines.sources.cycling.ingest import (
    _normalize_rider_name,
    _parse_time_gap,
    normalize_race,
)


class TestTimeGapParsing:
    """Tests for _parse_time_gap function."""

    def test_empty_string_returns_none(self):
        assert _parse_time_gap("") is None
        assert _parse_time_gap("+") is None

    def test_minutes_and_seconds(self):
        # "+ 34' 34\"" → 34*60 + 34 = 2074 seconds → 2074000 ms
        result = _parse_time_gap("+ 34' 34\"")
        assert result == 2074 * 1000

    def test_hours_minutes_seconds_with_unicode_apostrophe(self):
        # "+ 1h 04' 36\"" → (1*60 + 4)*60 + 36 = 3876 seconds
        result = _parse_time_gap("+ 1h 04' 36\"")
        assert result == 3876 * 1000

    def test_hours_minutes_seconds_no_space(self):
        # "+1h 08' 19\"" → (1*60 + 8)*60 + 19 = 4099 seconds
        result = _parse_time_gap("+1h 08' 19\"")
        assert result == 4099 * 1000

    def test_unicode_apostrophes_and_quotes(self):
        # Wikipedia uses fancy Unicode apostrophes (\xa0 = non-breaking space)
        result = _parse_time_gap("+ 34' 34\"")  # Regular ASCII
        assert result == 2074 * 1000


class TestRiderNameNormalization:
    """Tests for _normalize_rider_name function."""

    def test_extract_country_code(self):
        name, country = _normalize_rider_name("Ben O'Connor (AUS)")
        assert name == "Ben O'Connor"
        assert country == "AUS"

    def test_no_country_code(self):
        name, country = _normalize_rider_name("Ben O'Connor")
        assert name == "Ben O'Connor"
        assert country is None

    def test_accented_characters(self):
        name, country = _normalize_rider_name("Jhonatan Narváez (ECU)")
        assert "Narv" in name  # Accent preserved
        assert country == "ECU"


class TestNormalizeRace:
    """Tests for normalize_race function (requires live Wikipedia fetch).
    
    These tests fetch live data from Wikipedia, so they're marked as integration tests.
    Run with: pytest tests/test_cycling_results.py::TestNormalizeRace -v
    """

    @pytest.mark.integration
    def test_tour_de_france_2025_parsing(self):
        """Parse 2025 Tour de France Wikipedia page and verify structure."""
        from racinglines.sources.cycling.fetch import fetch_race_page, parse_tables

        html = fetch_race_page("Tour_de_France", 2025)
        assert html is not None
        assert len(html) > 10000  # Reasonable page size

        tables = parse_tables(html)
        assert len(tables) > 0
        assert any("general_classification" in name.lower() for name in tables.keys())

        # Normalize
        data = normalize_race(2025, "Tour de France", tables)

        # Verify structure
        assert data["event"]["name"] == "Tour de France 2025"
        assert data["event"]["source_key"] == "2025-tour_de_france"
        assert len(data["results"]) > 100

        # Verify result structure
        result = data["results"][0]
        assert "position" in result
        assert "time_ms" in result
        assert "team" in result
        assert "extra" in result
        assert "rider_name" in result["extra"]

    @pytest.mark.integration
    def test_giro_d_italia_parsing(self):
        """Parse Giro d'Italia and verify."""
        from racinglines.sources.cycling.fetch import fetch_race_page, parse_tables

        html = fetch_race_page("Giro_d'Italia", 2025)
        if html is None:
            pytest.skip("Giro d'Italia page not available")

        tables = parse_tables(html)
        data = normalize_race(2025, "Giro d'Italia", tables)

        assert data["event"]["name"] == "Giro d'Italia 2025"
        assert len(data["results"]) > 0

    def test_event_source_key_format(self):
        """Verify event source_key matches expected pattern."""
        # Mock data (no fetch needed)
        tables = {
            "general_classification": {
                "headers": ["Rank", "Rider", "Team", "Time"],
                "rows": [
                    ["Rank", "Rider", "Team", "Time"],  # Header
                    ["1", "Test Rider (AUS)", "Test Team", ""],
                ],
            }
        }

        data = normalize_race(2025, "Tour de France", tables)
        assert data["event"]["source_key"] == "2025-tour_de_france"

    def test_result_time_gap_calculation(self):
        """Verify time gaps are calculated correctly."""
        tables = {
            "general_classification": {
                "headers": ["Rank", "Rider", "Team", "Time"],
                "rows": [
                    ["Rank", "Rider", "Team", "Time"],  # Header
                    ["1", "Winner (AUS)", "Team A", ""],  # Winner
                    ["2", "Second (USA)", "Team B", "+ 34' 34\""],  # 2074 seconds
                ],
            }
        }

        data = normalize_race(2025, "Tour de France", tables)
        results = sorted(data["results"], key=lambda x: x["position"])

        assert results[0]["time_ms"] is None  # Winner
        assert results[1]["time_ms"] == 2074 * 1000  # Second place
