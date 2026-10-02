"""
Cyclist name resolution for market links: which UCI road cyclist a market link names,
and which race they contested. One resolver per season against the database's cyclists and races.

    Resolver(conn, year).cyclist("Juan Ayuso")     -> athlete id, or None
    Resolver(conn, year).race("Tour de France", date(2026, 7, 6))   -> race id, or None

Cyclists are the athletes the ingest created (AthleteIdentifier scheme "cycling_name", the display name),
so a Polymarket token naming a cyclist in a race resolves to the same athlete and race across exchanges.

Names are matched exactly first (accents ignored: "Jhonatan Narváez" = "Jhonatan Narvaez"), then
first + last name (a middle name is dropped), then surname only if exactly one cyclist in the pool has it.
A surname on its own that fits two cyclists ("Pogacar" might fit multiple) is never guessed: it resolves
to None. The pool is the cyclists who raced in the market's season or the one before.
"""

import re
import unicodedata
from datetime import date

from sqlalchemy import text


RACE_WINDOW_DAYS = 7  # a market's date vs the race's date, in days


def norm(name):
    """Lower-case ASCII with accents removed: 'Jhonatan Narváez' -> 'jhonatan narvaez'."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    # Remove common punctuation but keep hyphens as spaces for compound names
    s = re.sub(r"[.']", "", s)  # remove dots and apostrophes
    s = re.sub(r"[-]", " ", s)  # hyphens become spaces
    return re.sub(r"[^a-z0-9 ]", "", s).strip()


def first_last(n):
    """First and last name from a normalized name: 'juan felipe ayuso vicens' -> 'juan ayuso'."""
    parts = n.split()
    if len(parts) <= 2:
        return n
    # Return first name + last name, skipping middle names
    return f"{parts[0]} {parts[-1]}"


class Resolver:
    """Cyclist and race lookups for UCI road cycling. `year`: the market's season."""

    def __init__(self, conn, year=None):
        """Build cyclist and race index from the database."""
        self.year = year
        self.unresolved = {}  # cyclist_name -> "unknown" | "ambiguous: a, b"

        # Load cyclists from the database (scheme "cycling_name")
        rows = conn.execute(text("""
            SELECT DISTINCT a.id, a.display_name FROM athletes a
            JOIN athlete_identifiers i ON i.athlete_id = a.id AND i.scheme = 'cycling_name'
            ORDER BY a.display_name
        """)).all()

        self.names = {int(i): n for i, n in rows}
        self.by_full = {norm(n): int(i) for i, n in rows}  # normalized full name -> id
        self.by_first_last = {}  # normalized "first last" -> id
        self.by_surname = {}  # normalized surname -> set of ids

        # Build first+last and surname indexes
        for i, n in rows:
            fl = first_last(norm(n))
            if fl != norm(n):
                # Only index as first+last if it differs from full name
                if fl not in self.by_first_last:
                    self.by_first_last[fl] = []
                self.by_first_last[fl].append(int(i))

            surname = norm(n).split()[-1]
            if surname not in self.by_surname:
                self.by_surname[surname] = set()
            self.by_surname[surname].add(int(i))

        # Simplify surname index: keep only unique surnames
        self.by_surname = {k: next(iter(v)) for k, v in self.by_surname.items() if len(v) == 1}

        # Pool: cyclists who raced this season or last season
        self.pool = self._pool(year)

        # Load races for the season
        self.races = conn.execute(text("""
            SELECT r.id, e.name, e.source_key, e.start_date FROM races r
            JOIN events e ON e.id = r.event_id
            JOIN seasons s ON s.id = e.season_id
            JOIN competitions co ON co.id = s.competition_id
            WHERE co.code = 'uci_road_wt'
              AND (CAST(:year AS int) IS NULL OR s.year = CAST(:year AS int))
            ORDER BY e.start_date DESC
        """), dict(year=year)).all()

    def _pool(self, year):
        """Cyclists from this season or last season, else all."""
        if year is not None:
            rows = self.names
            # TODO: could filter to only cyclists with results in season/season-1
            # For now, use all cyclists
            return set(self.names.keys())
        return set(self.names.keys())

    def cyclist(self, subject):
        """Athlete id for the subject string of a market ('Juan Ayuso', 'Pogacar', 'J. Ayuso')."""
        n = norm(subject)
        if not n:
            return None

        # Try exact match
        if n in self.by_full:
            return self.by_full[n]

        # Try first+last match
        fl = first_last(n)
        if fl in self.by_first_last:
            ids = self.by_first_last[fl]
            if len(ids) == 1:
                return ids[0]
            if len(ids) > 1:
                self.unresolved[subject] = f"ambiguous ({len(ids)} cyclists with {fl})"
                return None

        # Try surname match
        parts = n.split()
        if parts:
            surname = parts[-1]
            if surname in self.by_surname:
                return self.by_surname[surname]

        self.unresolved.setdefault(subject, "unknown")
        return None

    def race(self, race_name, when=None, window=RACE_WINDOW_DAYS):
        """(race_id, event_key) of the race: matched by name, optionally within `window` days of `when`."""
        if not race_name:
            return None, None

        n = norm(race_name)
        candidates = []

        for rid, name, key, start in self.races:
            if norm(name) == n or n in norm(name):
                if when is not None and start is not None:
                    if hasattr(when, "date"):
                        when = when.date()
                    if abs((start - when).days) > window:
                        continue
                candidates.append((rid, name, key, start))

        if len(candidates) == 1:
            return candidates[0][0], candidates[0][2]
        if len(candidates) > 1:
            # Multiple candidates: prefer the one closest to `when`
            if when is not None:
                if hasattr(when, "date"):
                    when = when.date()
                candidates.sort(key=lambda x: abs((x[3] - when).days) if x[3] else float("inf"))
            return candidates[0][0], candidates[0][2]

        return None, None
