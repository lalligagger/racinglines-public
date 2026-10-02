"""
Match UCI road cycling Wikipedia results to Kalshi market links.

The link identity challenge:
  Kalshi markets for cycling are identified by their series tickers (KXCYCLING*, KXCYCLINGSTAGE, etc.)
  and condition_ids. Each market link has:
    - competition_id (UCI World Tour)
    - athlete_id (rider, for head-to-head markets)
    - token_id (Kalshi's YES/NO token)
    - prediction (race_win, race_podium, race_top5, stage_win, kc_leader, etc.)
    - params (stage number for stage markets, etc.)

  Wikipedia results have:
    - race name, date, year
    - rider name, team, UCI ID (if available)
    - finishing position, time gap
    - stage-by-stage results, KOM standings, jersey holders

  A market link is "identified" when we can confidently map a Wikipedia result to a Kalshi market:
    race_win market → rider finished 1st overall
    race_podium market → rider finished 1-3 overall
    stage_win market (stage=3) → rider won stage 3
    kc_leader market → rider wore the yellow jersey after stage N

TODO (implementation phased):
  - [ ] Build identity resolver: name+date → (athlete_id, prediction, race_outcome)
  - [ ] Handle name variations (accents, punctuation, team changes)
  - [ ] Stage-by-stage matching (date, riders, winners)
  - [ ] Jersey/KOM market matching (time-aware, as jerseys change daily)
  - [ ] Unidentified races: log for manual review
"""


def identify_link(
    link: dict,  # market_links row
    race_result: dict,  # Wikipedia race data
) -> bool:
    """
    Determine if a market link corresponds to a race result.
    
    TODO:
      - Match link.athlete_id to rider in race_result
      - Match link.prediction to race_result outcome (race_win, stage_win, etc.)
      - Return True if match confidence > threshold
    """
    pass
