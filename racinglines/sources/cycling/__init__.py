"""
UCI road cycling results adapter for Wikipedia (primary, approved 2026-10-01) and First Cycling API
(future, terms under review). Races are recorded as tape-only (unmodeled) until a model is built (2027).

Supported sources:
  - wikipedia: Grand Tours (TdF, Giro, Vuelta), Monuments, UCI World Tour races
               Coverage: stage results, GC, KOM/jersey standings, rider details
               Data shape: HTML tables on race Wikipedia pages, parsed with BeautifulSoup
               History: back decades; current 2026 season available

  - firstcycling (future): ProCyclingStats backend, if access is cleared
               API: (terms under review 2026-10-01)
               Data: comprehensive race calendar, full results per event

The adapter follows the pattern of racinglines/sources/{nascar,motogp}/. Results are not yet
ingested into the database; this scaffold is the first step (schema and fetch patterns).

When a results pipeline is built, the links module will match Wikipedia/API race results to Kalshi
market links via event keys (race name, date, course).
"""
