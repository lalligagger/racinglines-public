"""
Ingest UCI road cycling results from Wikipedia (parsed by racinglines/sources/cycling/fetch.py)
into the racinglines database.

Data model:
  event          one race (Tour de France 2025, Giro d'Italia 2025, etc.)
  race           event x category (UCI World Tour Grand Tour)
  rounds         Stage 1, Stage 2, ..., Stage N, General Classification, Mountains, Points
  results        one per rider per round: finishing position, time/gap

Rider matching:
  Riders are matched on AthleteIdentifier(scheme="cycling_name", value=<normalized_name>) 
  (UCI IDs are not yet on Wikipedia tables; future enhancement).

Idempotent like F1 / NASCAR ingests: a race is rebuilt only when its source files change.

Races currently supported (Grand Tours; Monuments + UCI WT races TBD):
  - Tour de France (21 stages)
  - Giro d'Italia (21 stages)
  - Vuelta a España (21 stages)
"""

import hashlib
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import delete, insert, select

from racinglines.db import models as m
from racinglines.db.ingest import _upsert, ensure_competition, resolve_venue


SPORT = "road_cycling"
SOURCE = "wikipedia"
SCHEME = "cycling_name"
PARSER = "wikipedia_cycling"

# Map race name patterns to competition codes
RACE_CATALOG = {
    "tour_de_france": "uci_road_wt",
    "giro_d_italia": "uci_road_wt",
    "vuelta_a_españa": "uci_road_wt",
}


def _parse_time_gap(gap_str: str) -> Optional[int]:
    """
    Parse time gap strings like "+ 34' 34\"", "+1h 04' 36\"", or "00:00:00" to milliseconds.
    Returns None if gap is 0 or empty (winner).
    """
    if not gap_str or gap_str.strip() == "" or gap_str.strip() == "+":
        return None
    
    gap_str = gap_str.strip()
    
    # Format: "+1h 04' 36\"" (hours, minutes, seconds with fancy Unicode apostrophes)
    if "h" in gap_str:
        try:
            # Normalize Unicode apostrophes and quotes
            gap_str = gap_str.replace("\xa0", " ").replace("'", "'").replace(""", '"').replace(""", '"')
            parts = gap_str.replace("+", "").replace("h", ":").replace("'", ":").replace('"', "").strip().split(":")
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) >= 2:
                if len(parts) == 3:
                    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                else:
                    h, m, s = int(parts[0]), int(parts[1]), 0
                return ((h * 60 + m) * 60 + s) * 1000
        except (ValueError, IndexError):
            pass
    
    # Format: "+ 34' 34\"" (minutes and seconds)
    if "'" in gap_str or "'" in gap_str:  # Handle both ASCII and Unicode apostrophes
        try:
            gap_str = gap_str.replace("\xa0", " ").replace("'", "'").replace(""", '"').replace(""", '"')
            parts = gap_str.replace("+", "").replace("'", ":").replace('"', "").strip().split(":")
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) == 2:
                mins, secs = int(parts[0]), int(parts[1])
                return (mins * 60 + secs) * 1000
        except (ValueError, IndexError):
            pass
    
    # Format: "00:00:00" (hours:minutes:seconds)
    if ":" in gap_str:
        try:
            parts = [int(p) for p in gap_str.split(":") if p.strip()]
            if len(parts) == 3:
                h, m, s = parts
                return ((h * 60 + m) * 60 + s) * 1000
            elif len(parts) == 2:
                m, s = parts
                return (m * 60 + s) * 1000
        except ValueError:
            pass
    
    return None


def _normalize_rider_name(name_str: str) -> Tuple[str, Optional[str]]:
    """
    Parse 'Rider Name (COUNTRY)' or 'Rider Name' into (name, country_code).
    Returns (normalized_name, country_code).
    """
    if "(" in name_str and ")" in name_str:
        name, country = name_str.rsplit("(", 1)
        country = country.rstrip(")").strip()
        return name.strip(), country if len(country) == 3 else None
    return name_str.strip(), None


def normalize_race(
    year: int,
    race_name: str,
    tables_parsed: Dict,
    event_date: Optional[date] = None,
) -> Dict:
    """
    Normalize a Wikipedia race page into racinglines schema (as plain dicts).
    
    Returns:
        dict with keys: event, race, rounds, results (each as dicts, ready for upsert)
    
    Following the pattern from racinglines/sources/nascar/ingest.py parse_race().
    """
    # Find GC table
    gc_table = None
    gc_table_name = None
    for name, data in tables_parsed.items():
        if "general_classification" in name.lower():
            gc_table = data
            gc_table_name = name
            break
    
    if not gc_table:
        raise ValueError(f"No general classification table found in {tables_parsed.keys()}")
    
    # Determine competition and race identity
    race_key = race_name.lower().replace(" ", "_")
    competition_code = RACE_CATALOG.get(race_key, "uci_road_wt")  # default to UCI WT
    source_key = f"{year}-{race_key}"
    
    # Build Event dict
    event = {
        "source": SOURCE,
        "source_key": source_key,
        "name": f"{race_name} {year}",
        "start_date": event_date or date(year, 1, 1),  # placeholder if unknown
        "status": "completed",
    }
    
    # Build Race dict
    race = {
        "format": {"kind": "stage_race", "stages": 21} if "tour" in race_key else None,
    }
    
    # Build Rounds dict (one GC round for now; stages TBD for Phase 2)
    gc_round = {
        "kind": "gc",
        "ordinal": 0,
        "name": "General Classification",
        "extra": None,
    }
    rounds = [gc_round]
    
    # Parse General Classification results
    results = []
    
    # Skip header row if present (row 0 might be duplicate headers)
    start_idx = 1 if gc_table["rows"] and gc_table["rows"][0][1] == "Rank" else 0
    
    for row in gc_table["rows"][start_idx:]:
        if not row or len(row) < 3:
            continue
        
        try:
            position = int(row[0])
        except (ValueError, IndexError):
            continue
        
        rider_name_raw = row[1] if len(row) > 1 else ""
        rider_name, country = _normalize_rider_name(rider_name_raw)
        team = row[2] if len(row) > 2 else None
        time_gap_str = row[3] if len(row) > 3 else ""
        
        time_gap_ms = _parse_time_gap(time_gap_str) if position > 1 else None
        
        # Build Result dict
        result = {
            "round_ordinal": 0,  # GC round
            "position": position,
            "status": "OK",
            "time_ms": time_gap_ms,
            "bib": None,
            "team": team,
            "nation": country,
            "extra": {
                "rider_name": rider_name,
                "source_table": gc_table_name,
            },
        }
        results.append(result)
    
    return {
        "event": event,
        "race": race,
        "rounds": rounds,
        "results": results,
    }
