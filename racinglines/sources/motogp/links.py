"""
Which rider and race a MotoGP market is about, for the taker replay (racinglines/pipelines/position_replay.py).

    Linker(conn).identify(link)     -> dict(kind, athlete_id, race_id, opponent_id, problems)

Read-only: nothing here writes to the database, and the sport's schema names no [identity] resolver, so the syncs
keep filing MotoGP links `unmodeled` exactly as before. The replay identifies each link in memory when it runs.

* kind: from the Kalshi series ticker (KXMOTOGPRACE = the Grand Prix winner; the championship and team series are
  not race contracts and get no kind), else from the wording ("win" + "Grand Prix"/"GP", never a sprint, a pole or
  the title). Only the race winner is known from the listings seen so far (docs/data-changes.md, 2026-09-29: 289 of
  MotoGP's 322 Kalshi markets are KXMOTOGPRACE).
* athlete_id: the rider named on the yes side, matched with the NASCAR resolver's name rules against the riders the
  results adapter created (AthleteIdentifier scheme "motogp").
* race_id: the MotoGP-class race of the event whose Sunday falls within RACE_WINDOW_DAYS before the market's close
  (an event is filed by its first day, date_start, so its race is RACE_DAY_OFFSET days later); two candidates (never
  seen: MotoGP runs one Grand Prix a weekend) are told apart by a shared word in the name, else none is picked.
"""

import re
from datetime import timedelta

from racinglines.sources.nascar.identity import Resolver, norm

KALSHI = {"KXMOTOGPRACE": "race_win"}           # series ticker -> kind; others (KXMOTOGP, KXMOTOGPTEAMS) are not races
NOT_RACE_WIN = re.compile(r"\b(sprint|pole|qualif\w*|champion\w*|title|constructor|team|fastest lap|podium|moto2|moto3)\b")
RACE_WIN = re.compile(r"\bwins?\b|\bwinner\b")
GP = re.compile(r"\bgrand prix\b|\bgp\b|\bmotogp\b")
RACE_DAY_OFFSET = 2                             # Friday first day -> Sunday race
RACE_WINDOW_DAYS = 6                            # a race's Sunday up to this many days before the market's close
NOT_A_RIDER = {"", "yes", "no"}


def _series(link):
    p = link.get("params") or {}
    return p.get("series") or str(link.get("event_slug") or "").split("-", 1)[0].upper()


def kind_of(link):
    """(kind or None) of one link: its Kalshi series when it has one, else the listing's wording."""
    if link.get("exchange") == "kalshi":
        return KALSHI.get(_series(link))
    words = norm(" ".join(str(link.get(k) or "") for k in ("event_title", "question")))
    if RACE_WIN.search(words) and GP.search(words) and not NOT_RACE_WIN.search(words):
        return "race_win"
    return None


class Linker:
    """One Resolver per season, built on first use (a link is matched against its own season's riders and races)."""

    def __init__(self, conn):
        self.conn, self._by_year = conn, {}

    def resolver(self, year):
        if year not in self._by_year:
            self._by_year[year] = Resolver(self.conn, year, competition="motogp_wc", scheme="motogp", source="motogp_api")
        return self._by_year[year]

    def race(self, year, close, name=None):
        """race id of the Grand Prix whose Sunday is 0..RACE_WINDOW_DAYS days before `close` (a date), or None."""
        near = [(rid, ev) for rid, ev, start, _ in self.resolver(year).events if start is not None
                and 0 <= (close - (start + timedelta(days=RACE_DAY_OFFSET))).days <= RACE_WINDOW_DAYS]
        if len(near) > 1 and name:
            words = set(norm(name).split()) - {"the", "grand", "prix", "gp", "motogp", "of", "de", "winner", "race", "will", "win"}
            near = [(rid, ev) for rid, ev in near if words & set(norm(ev).split())] or near
        return near[0][0] if len(near) == 1 else None

    def identify(self, link):
        out = dict(kind=kind_of(link), athlete_id=None, race_id=None, opponent_id=None, problems=[])
        close = link.get("end_date")
        if out["kind"] is None or close is None:
            if out["kind"] is not None:
                out["problems"].append("no close date")
            return out
        close = close.date() if hasattr(close, "date") else close
        out["race_id"] = self.race(close.year, close, link.get("event_title") or link.get("question"))
        if out["race_id"] is None:
            out["problems"].append("race: none, or more than one, in the window")
        subject = link.get("group_title") if norm(link.get("group_title")) not in NOT_A_RIDER else link.get("outcome")
        if norm(subject) not in NOT_A_RIDER:
            R = self.resolver(close.year)
            out["athlete_id"] = R.driver(subject)
            if out["athlete_id"] is None:
                out["problems"].append(f"rider: {R.unresolved.get(subject, 'unknown')}")
        return out
