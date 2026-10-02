"""
Ingest UCI road cycling results from Wikipedia (parsed by racinglines/sources/cycling/fetch.py)
into the racinglines database.

Data model (once [results] pipeline is built):
  event          one race (Tour de France 2026, Giro d'Italia 2026, etc.)
  race           event x category (GC / stages / KOM / jersey winners)
  rounds         not applicable for cycle races (no qualifying/practice sessions)
  results        one per rider: finishing position, time/gap, stage details, KOM/jersey points
  laps           not applicable (cycling doesn't use lap-based scoring)

Rider matching:
  Riders are matched on AthleteIdentifier(scheme="cycling_uci", value=<uci_id>) when available,
  or by name + team (fallback). UCI IDs are stable across teams and seasons; team affiliations
  are source data only and are not join keys.

Source data quirks (to document after first live run):
  TBD - to be updated after first Wikipedia race is ingested

Idempotent like F1 / NASCAR ingests: a race is rebuilt only when its source files change.
Only Grand Tours and Monuments are wired to competitions initially; other races can be added as needed.

TODO (implementation phased):
  [ ] Implement normalize_race() — parse Wikipedia tables into racinglines schema
  [ ] Implement _upsert() calls — insert/update events, races, results
  [ ] Add tests in tests/test_cycling_results.py
  [ ] Document source quirks in tests/fixtures/market/cycling_README.txt
"""

import hashlib
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy import delete, insert, select

from racinglines.db import models as m
from racinglines.db.ingest import _upsert, ensure_competition, resolve_venue


SPORT = "road_cycling"
SOURCE = "wikipedia"
SCHEME = "cycling_uci"
PARSER = "wikipedia_cycling"

# Map competition codes to Wikipedia race types
RACES = {
    # Grand Tours
    "uci_road_wt": {
        "tdf": {"name": "Tour de France", "category": "stage_race"},
        "giro": {"name": "Giro d'Italia", "category": "stage_race"},
        "vuelta": {"name": "Vuelta a España", "category": "stage_race"},
    },
}


def normalize_race(
    event_data: Dict,
    tables_parsed: Dict,
) -> Tuple[m.Event, List[m.Race], List[m.Result]]:
    """
    Normalize a Wikipedia race page into racinglines schema.
    
    Args:
        event_data: Race metadata (name, date, year, etc.)
        tables_parsed: Parsed HTML tables from Wikipedia page
    
    Returns:
        (Event, list of Races, list of Results)
    
    TODO:
      - Parse tables["general_classification"] → GC results
      - Parse tables["stages"] → stage results
      - Parse tables["mountain_classification"] → KOM standings
      - Parse tables["points_classification"] → jersey standings
      - Extract rider IDs and match to UCI database (when available)
    """
    pass


def ingest_race(year: int, race_key: str, html_content: str, tables: Dict):
    """
    Ingest a single race into the database.
    
    TODO:
      - Build event/race/result objects
      - Upsert via _upsert() (idempotent)
      - Record source file hash for change detection
    """
    pass
