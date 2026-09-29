"""
Who and which race a NASCAR market is about: one resolver for the sport, whichever exchange listed the market.

    Resolver(conn, year).driver("Ricky Stenhouse Jr.")          -> athlete id, or None
    Resolver(conn, year).race(date(2026, 11, 8), "Homestead")   -> race id, or None

Drivers are the athletes the results adapter created (AthleteIdentifier scheme "nascar", NASCAR's own driver id),
so a Kalshi ticker, a Polymarket token and an OG.com instrument naming the same driver in the same race resolve to
the same athlete and race and therefore share one outcome key (markets/venues.key). Nothing here reads a
venue's format: each venue hands over a subject string and a date.

Names are matched exactly first (accents, case, punctuation and generational suffixes ignored: "Daniel Suárez" =
"Daniel Suarez", "A.J. Allmendinger" = "AJ Allmendinger", "Ricky Stenhouse Jr." = "Ricky Stenhouse"), then on
first + last name (a middle name is dropped: "John Hunter Nemechek" = "John Nemechek"), then a known nickname,
then a short first name with a surname only one driver in the pool has ("Chris Buescher" = "Christopher Buescher",
never "Kyle Busch" for "Kurt Busch"), then a surname on its own if exactly one driver has it. A name that fits two drivers ("Busch") is
never guessed: it resolves to None and `unresolved` says why, so a naming rule can be added on purpose.
The pool is the drivers who raced in the market's season or the one before (else everyone): "Kyle Busch" in
2026 is the 2026 driver even if a namesake raced once in 2015, and a market listed before the first race of a
season still finds last year's field.
"""

import re
import unicodedata

from sqlalchemy import text

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
# names that are one person and share no first name (a nickname): the feed has used both over the years.
# Extend when the audit lists an unresolved subject; ordinary short forms (Chris/Christopher) are handled by the matcher.
ALIAS_GROUPS = [{"bubba wallace", "darrell wallace", "darrell bubba wallace"}]
RACE_WINDOW_DAYS = 1                     # a market's date vs the race's date, in days


def norm(name):
    """Lower-case ASCII with punctuation removed: 'A.J. Allmendinger' -> 'aj allmendinger'."""
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'`]", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def strip_suffix(n):
    parts = [p for p in n.split(" ") if p]
    while len(parts) > 1 and parts[-1] in SUFFIXES:
        parts.pop()
    return " ".join(parts)


def first_last(n):
    parts = strip_suffix(n).split(" ")
    return f"{parts[0]} {parts[-1]}" if len(parts) > 2 else " ".join(parts)


def _short_form(a, b):
    """Two first names that can be one person: equal, or one begins the other ('chris' / 'christopher')."""
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


class Resolver:
    """Driver and race lookups for the NASCAR Cup competition. `year`: the market's season; the pool of drivers is
    those with a race result that season or the one before, else every NASCAR driver in the database."""

    def __init__(self, conn, year=None, competition="nascar_cup"):
        self.competition, self.year = competition, year
        self.unresolved = {}                                  # subject string -> "unknown" | "ambiguous: a, b"
        rows = conn.execute(text("""
            SELECT a.id, a.display_name, i.value FROM athletes a
            JOIN athlete_identifiers i ON i.athlete_id = a.id AND i.scheme = 'nascar'"""), {}).all()
        self.names = {int(i): n for i, n, _ in rows}
        self.driver_ids = {int(i): int(v) for i, _, v in rows}
        seasons = {int(i): set() for i, *_ in rows}
        for i, y in conn.execute(text("""
                SELECT DISTINCT r.athlete_id, s.year FROM results r JOIN rounds ro ON ro.id = r.round_id AND ro.kind = 'race'
                JOIN races ra ON ra.id = ro.race_id JOIN events e ON e.id = ra.event_id
                JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
                WHERE co.code = :c"""), dict(c=competition)).all():
            seasons.setdefault(int(i), set()).add(int(y))
        self.seasons = seasons
        self.pool = self._pool(year)
        self._index = self._build(self.pool)
        self.events = conn.execute(text("""
            SELECT ra.id, e.name, e.start_date, e.status FROM races ra JOIN events e ON e.id = ra.event_id
            JOIN seasons s ON s.id = e.season_id JOIN competitions co ON co.id = s.competition_id
            WHERE co.code = :c AND e.source = 'nascar_cf' ORDER BY e.start_date"""), dict(c=competition)).all()

    def _pool(self, year):
        if year is not None:
            ids = {i for i, ys in self.seasons.items() if ys & {year, year - 1}}
            if ids:
                return ids
        return set(self.names)

    def _build(self, pool):
        """{key kind: {normalized key: set of athlete ids}} over the pool."""
        idx = {"full": {}, "plain": {}, "firstlast": {}, "surname": {}}
        for i in pool:
            n = norm(self.names[i])
            plain = strip_suffix(n)
            for kind, key in (("full", n), ("plain", plain), ("firstlast", first_last(n)), ("surname", plain.split(" ")[-1])):
                idx[kind].setdefault(key, set()).add(i)
        return idx

    def _one(self, kind, key, subject):
        ids = self._index[kind].get(key, set())
        if len(ids) == 1:
            return next(iter(ids))
        if len(ids) > 1:
            self.unresolved[subject] = "ambiguous: " + ", ".join(sorted(self.names[i] for i in ids))
        return None

    def driver(self, subject):
        """Athlete id for the subject string of a market ('Kyle Larson', 'Larson', 'Ricky Stenhouse Jr.')."""
        n = strip_suffix(norm(subject))
        if not n:
            return None
        names = [n] + [a for g in ALIAS_GROUPS if n in g for a in sorted(g) if a != n]
        for cand in names:
            for kind, key in (("full", norm(subject) if cand == n else cand), ("plain", cand), ("firstlast", first_last(cand))):
                got = self._one(kind, key, subject)
                if got is not None:
                    return got
                if subject in self.unresolved:
                    return None
        parts = n.split(" ")
        if len(parts) >= 2:
            same = self._index["surname"].get(parts[-1], set())
            fits = {i for i in same if _short_form(parts[0], strip_suffix(norm(self.names[i])).split(" ")[0])}
            if len(fits) == 1:
                return next(iter(fits))
            if len(fits) > 1:
                self.unresolved[subject] = "ambiguous: " + ", ".join(sorted(self.names[i] for i in fits))
                return None
        else:
            got = self._one("surname", n, subject)
            if got is not None:
                return got
            if subject in self.unresolved:
                return None
        self.unresolved.setdefault(subject, "unknown")
        return None

    def driver_id(self, athlete_id):
        """NASCAR's own driver id for an athlete (the join key back to the feeds)."""
        return self.driver_ids.get(athlete_id)

    def race(self, when, name=None, window=RACE_WINDOW_DAYS):
        """(race id, event name) of the race held within `window` days of `when` (a date). More than one candidate
        (an exhibition the same week): the one whose name shares a word with `name`; still more than one: None."""
        if when is None:
            return None, None
        if hasattr(when, "date"):
            when = when.date()
        near = [(rid, ev) for rid, ev, start, _ in self.events if start is not None and abs((start - when).days) <= window]
        if len(near) > 1 and name:
            words = set(norm(name).split()) - {"the", "race", "nascar", "cup", "series", "of", "at", "in", "a", "winner"}
            best = [(rid, ev) for rid, ev in near if words & set(norm(ev).split())]
            near = best or near
        return near[0] if len(near) == 1 else (None, None)

    def race_window(self, start, end):
        """Races held from `start` to `end` (dates), e.g. for a champion market that spans the season."""
        return [(rid, ev, s) for rid, ev, s, _ in self.events if start <= s <= end]
