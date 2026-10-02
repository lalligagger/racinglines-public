"""
Match UCI road cycling Wikipedia results to Kalshi market links.

The link identity challenge:
  Kalshi markets for cycling are identified by their series tickers (KXCYCLING*, etc.)
  and condition_ids. Each market link has:
    - competition_id (UCI World Tour)
    - athlete_id (rider, for head-to-head or outcome markets)
    - race_id (the specific race, e.g., 2025 Tour de France)
    - prediction (race_win, race_podium, race_top10, etc.)
    - params (additional context, e.g. {"stage": 3} for stage markets)

  Wikipedia results have:
    - race name, date, year
    - rider name, team, country
    - finishing position, time gap
    - (future: stage-by-stage results, KOM standings, jersey holders)

  A market link is "identified" when we map the Wikipedia result to a Kalshi market:
    race_win market → rider finished 1st overall
    race_podium market → rider finished 1-3 overall
    race_top10 market → rider finished 1-10 overall

This module is Phase 2: actual matching logic. Phase 1 (fetch/ingest) is complete.

TODO (implementation):
  - [ ] Rider name matching (exact, fuzzy, UCI ID when available)
  - [ ] Prediction matching (race_win, race_podium, race_top10, stage_win, etc.)
  - [ ] Handle multiple markets for same rider (e.g., both race_win and race_podium)
  - [ ] Log unidentified races for manual review
"""

from typing import Dict, List, Optional, Tuple


def normalize_rider_name(name: str) -> str:
    """
    Normalize rider names for matching: lowercase, remove accents, etc.
    
    Examples:
      "Ben O'Connor" → "ben oconnor"
      "Jhonatan Narváez" → "jhonatan narvaez"
    """
    import unicodedata
    # Remove accents
    name = ''.join(c for c in unicodedata.normalize('NFD', name)
                   if unicodedata.category(c) != 'Mn')
    # Lowercase and remove punctuation
    name = name.lower().replace("'", "").replace("-", " ")
    # Collapse multiple spaces
    name = ' '.join(name.split())
    return name


def identify_link(
    link_dict: dict,  # market_links row (as dict with all columns)
    results_dict: dict,  # normalize_race() output
) -> bool:
    """
    Determine if a market link corresponds to any race result.
    
    Args:
        link_dict: Market link row with keys (prediction, athlete_id, race_id, params, ...)
        results_dict: Output from normalize_race() with keys (event, race, rounds, results)
    
    Returns:
        True if the link is identified and linked to a result. False otherwise.
    
    TODO:
      - Resolve athlete_id to rider name via database lookup
      - Match prediction type to result (race_win, race_podium, etc.)
      - Handle stage markets (params["stage"])
      - Handle jersey/KOM markets (params["jersey"], etc.)
    """
    # TODO: This is a stub for Phase 2.
    # Full implementation requires database access (athlete name lookup, etc.)
    # and decision on how to record identified links (update race_id? store separately?)
    return False
