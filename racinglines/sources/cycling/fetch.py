"""
Fetch UCI road cycling results from Wikipedia (https://www.wikipedia.org, CC-BY-SA 3.0).

Races are fetched by their Wikipedia URLs and parsed with BeautifulSoup. The pattern:
  https://en.wikipedia.org/wiki/<Year>_<Race_Name>

Examples:
  2026 Tour de France        https://en.wikipedia.org/wiki/2026_Tour_de_France
  2026 Giro d'Italia         https://en.wikipedia.org/wiki/2026_Giro_d%27Italia
  2026 Vuelta a España       https://en.wikipedia.org/wiki/2026_Vuelta_a_Espa%C3%B1a
  2026 Tour of Flanders      https://en.wikipedia.org/wiki/2026_Tour_of_Flanders
  2026 Paris–Roubaix         https://en.wikipedia.org/wiki/2026_Paris%E2%80%93Roubaix
  2026 Liège–Bastogne–Liège  https://en.wikipedia.org/wiki/2026_Li%C3%A8ge%E2%80%93Bastogne%E2%80%93Li%C3%A8ge
  2026 Giro di Lombardia     https://en.wikipedia.org/wiki/2026_Giro_di_Lombardia

The results are stored as parsed HTML tables in data/raw/cycling/wikipedia/<year>/<race_slug>/ 
by source fetch logic (patterns TBD after first race is tested).

Rate limiting: Use 2-second delays between requests to respect Wikipedia's rate limits.
User-Agent: Required (Wikipedia blocks requests without one).

TODO (once cleared for implementation):
  - [ ] Crawl Wikipedia race calendars for the year
  - [ ] Fetch each race's main page
  - [ ] Extract and normalize tables: GC, stages, KOMs, jerseys, results
  - [ ] Parse rider details (names, teams, countries)
  - [ ] Store in data/raw/cycling/wikipedia/ for ingest step
  - [ ] Document table structures in docstrings (for later ingest.py)
"""

import time
from typing import Optional
import requests
from bs4 import BeautifulSoup

WIKIPEDIA_BASE = "https://en.wikipedia.org/wiki"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch_race_page(race_slug: str, year: int) -> Optional[str]:
    """
    Fetch a race's Wikipedia page by slug and year.
    
    Args:
        race_slug: Wikipedia page title (e.g., "Tour_de_France", "Tour_of_Flanders")
        year: Race year (e.g., 2026)
    
    Returns:
        HTML content of the page, or None if not found / fetch failed
    """
    url = f"{WIKIPEDIA_BASE}/{year}_{race_slug}"
    headers = {"User-Agent": USER_AGENT}
    
    try:
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code == 200:
            return resp.text
        elif resp.status_code == 404:
            print(f"Race page not found: {url}")
            return None
        else:
            print(f"Fetch error ({resp.status_code}): {url}")
            return None
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        return None
    finally:
        time.sleep(2)  # Rate limit: 2 seconds between requests


def parse_tables(html: str) -> dict:
    """
    Parse all wikitable elements from a race page.
    
    Returns:
        dict with table names (detected from headers) and their rows
    """
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table', {'class': 'wikitable'})
    
    result = {}
    for i, table in enumerate(tables):
        # Try to find a meaningful header for this table
        headers = [th.text.strip() for th in table.find_all('th')[:5]]
        key = f"table_{i}"
        if headers:
            key = "_".join(headers[:2]).lower().replace(" ", "_")
        
        rows = []
        for tr in table.find_all('tr')[1:]:  # Skip header row
            row_data = [td.text.strip() for td in tr.find_all(['td', 'th'])]
            if row_data:
                rows.append(row_data)
        
        result[key] = {"headers": headers, "rows": rows}
    
    return result


# TODO: Define race catalog (annual, by sport/category)
GRAND_TOURS = {
    "Tour_de_France": "tdf",
    "Giro_d%27Italia": "giro",
    "Vuelta_a_Espa%C3%B1a": "vuelta",
}

MONUMENTS = {
    "Tour_of_Flanders": "ronda",
    "Paris%E2%80%93Roubaix": "roubaix",
    "Lie%CC%80ge%E2%80%93Bastogne%E2%80%93Lie%CC%80ge": "liege",
    "Tour_of_Lombardy": "lombardia",
    "Milan%E2%80%93San_Remo": "milan",
}
