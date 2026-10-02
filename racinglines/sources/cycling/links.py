"""
Which UCI road cyclist, race and prediction kind a Polymarket/Kalshi market link is about:
one pass over the market links to set athlete_id, race_id, and params (kind, season).

    Linker(conn).identify(link)     what a link (a market_links row dict) is about
    Linker(conn).fill(rows)         the same, written into each row's athlete_id / race_id / params
    
A market link is identified when:
  - athlete_id: the rider (cyclist name from Polymarket market outcome)
  - race_id: the UCI race (race name from market question/event title)
  - params.kind: the prediction (race_win, race_podium, race_top10, etc.)
  - params.season: the market's year
"""

import json
import re
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import text

from racinglines.sources.cycling import identity as ID
from racinglines.sources.cycling.identity import norm

# Polymarket/Kalshi wording -> (prediction_kind, subject_type)
# Example: "Will Juan Ayuso win the Tour de France?" -> ("race_win", "rider")
KINDS = {
    "winner": ("race_win", "rider"),
    "win": ("race_win", "rider"),
    "champion": ("race_win", "rider"),
    "podium": ("race_podium", "rider"),
    "top 3": ("race_podium", "rider"),
    "top 5": ("race_top5", "rider"),
    "top 10": ("race_top10", "rider"),
    "king of the mountains": ("race_kom", "rider"),
    "kom": ("race_kom", "rider"),
    "best young rider": ("race_best_young", "rider"),
    "points classification": ("race_points", "rider"),
    "stage winner": ("race_stage_win", "rider"),
}

RACE_KINDS = {k for k, _ in KINDS.values() if k.startswith("race_")}


def classify_polymarket(event_title, question, outcome):
    """
    Classify a Polymarket cycling market by title/question/outcome.
    Returns (kind, race_name, rider_name) or (None, None, None) if unclassifiable.
    
    Examples:
      ("Tour de France 2026: Winner", "Will Juan Ayuso win...", "Juan Ayuso") 
        -> ("race_win", "Tour de France", "Juan Ayuso")
      ("Il Lombardia 2026: Winner", "Will X win...", "Remco Evenepoel")
        -> ("race_win", "Il Lombardia", "Remco Evenepoel")
    """
    title = str(event_title or "").strip()
    question = str(question or "").strip()
    outcome = str(outcome or "").strip()

    # Extract race name from title: "Tour de France 2026: Winner" -> "Tour de France"
    race_match = re.search(r"^(.+?)\s+(?:20\d{2})?:?\s*(winner|champion|podium|top|stage)", title, re.I)
    race_name = race_match.group(1).strip() if race_match else None

    # Determine kind from title/question wording
    kind = None
    for pattern, (k, _) in KINDS.items():
        if re.search(pattern, title + " " + question, re.I):
            kind = k
            break

    # Outcome is typically the rider name (the "Yes" option or outcome label)
    rider_name = outcome if outcome and outcome != "Yes" else None

    return kind, race_name, rider_name


class Found:
    """What one market link is about (following NASCAR pattern)."""

    def __init__(self):
        self.kind = self.year = self.athlete_id = self.race_id = None
        self.problems = []

    def params(self):
        """The keys this adds to the link's params (only those known)."""
        want = {"kind": self.kind, "season": self.year}
        return {k: v for k, v in want.items() if v is not None}


def outcome_key(link):
    """One real-world outcome: (kind, athlete, race). None until fully identified."""
    p = link.get("params") or {}
    if not (p.get("kind") and link.get("athlete_id") and link.get("race_id")):
        return None
    return (p["kind"], link["athlete_id"], link["race_id"])


class Linker:
    """Identifies cycling market links against the database's cyclists and races."""

    def __init__(self, conn):
        self.conn = conn
        self._by_year = {}
        self.counts = Counter()
        self.unresolved = defaultdict(Counter)

    def resolver(self, year):
        """Get or create a Resolver for the given year."""
        if year not in self._by_year:
            self._by_year[year] = ID.Resolver(self.conn, year)
        return self._by_year[year]

    def has_data(self):
        """Check if there's any cyclist data in the database."""
        return bool(self.resolver(None).names)

    def identify(self, link):
        """Determine what a market link is about: (athlete_id, race_id, kind, season)."""
        found = Found()

        # Extract year from end_date or event_slug
        end_date = link.get("end_date")
        if end_date and isinstance(end_date, str):
            try:
                dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                found.year = dt.year
            except (ValueError, AttributeError):
                pass
        if not found.year:
            # Try to extract from event_slug
            m = re.search(r"20\d{2}", str(link.get("event_slug", "")))
            if m:
                found.year = int(m.group(0))

        found.year = found.year or 2026  # default to 2026

        resolver = self.resolver(found.year)

        # Classify the market
        event_title = link.get("event_title", "")
        question = link.get("question", "")
        outcome = link.get("outcome", "")
        group_title = link.get("group_title", "")

        kind, race_name, rider_name = classify_polymarket(event_title, question, group_title or outcome)
        if not kind:
            found.problems.append("classification failed")
            return found

        found.kind = kind

        # Resolve race
        if race_name:
            race_id, event_key = resolver.race(race_name, end_date)
            if race_id:
                found.race_id = race_id
            else:
                found.problems.append(f"race not found: {race_name}")

        # Resolve cyclist
        if rider_name:
            athlete_id = resolver.cyclist(rider_name)
            if athlete_id:
                found.athlete_id = athlete_id
            else:
                found.problems.append(f"cyclist not found: {rider_name}")
                self.unresolved["cyclist"][rider_name] += 1

        return found

    def fill(self, rows):
        """Identify each market link and fill in athlete_id, race_id, and params."""
        for row in rows:
            found = self.identify(row)
            row["athlete_id"] = found.athlete_id
            row["race_id"] = found.race_id
            params = row.get("params") or {}
            if isinstance(params, str):
                params = json.loads(params)
            params.update(found.params())
            row["params"] = params
            self.counts[f"problems_{len(found.problems)}"] += 1
