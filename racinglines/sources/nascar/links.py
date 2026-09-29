"""
Which NASCAR driver, race and contract an exchange's market is about: one pass over the market links of every
exchange, so the same real-world outcome gets the same athlete, race and kind whichever venue listed it.

    Linker(conn).identify(link)     what a link (a market_links row, or the dict a sync is about to store) is about
    Linker(conn).fill(rows)         the same, written into the rows' athlete_id / race_id / params (never raises)
    relink(session, conn, ...)      the pass over the links already in the database (`racinglines nascar link`)

What is filled, and what is not:

* `athlete_id`: the driver, through identity.Resolver, for a Cup contract on one driver; for a head-to-head the one that
  finishes ahead on "yes", with `params.opponent_id` the other (both resolve or neither is set).
* `race_id`: the Cup race, for a contract on one race. The race is found by its NAME within the market's season:
  every exchange writes the race's name somewhere (Kalshi's rules text, Polymarket's question), sponsors and
  all, and it is matched as a whole phrase against the season's Cup schedule. A name two races share ("Cook Out
  400" at Martinsville and again at Richmond in 2026) is settled by the date the listing gives (Kalshi's rules
  say "originally scheduled for Oct 4, 2026"; Polymarket's slug ends in the date), else by the close time, else
  left alone. A date on its own is never enough: the O'Reilly race is the day before the Cup race at the same
  track, so a date fits the wrong series. The one exception is a listing that says "Cup Series" outright.
* `params.kind`: what the contract is (race_win, race_top10, champion, ...), from the Kalshi series ticker or
  the wording of the question. `prediction` is NOT touched: every NASCAR link stays `unmodeled` until there is a
  model, so nothing on the board, in the calendar or in the strategies changes. `kind` is what a later step
  promotes.
* `params.nascar_series`: "cup", "xfinity" or "trucks", when the listing says so or a Cup race matched. Trucks
  and O'Reilly (Auto Parts / Xfinity) links are TAGGED, not dropped: they keep their competition and their
  tapes, and get no driver or race (the results adapter files Cup only).
* `params.season`: the market's year.

The identity of one outcome across venues is `outcome_key`: (kind, athlete, race or season). Two links with the
same key are the same bet, and see the same model.

Nothing here overwrites an athlete or race that is already set with nothing: a failed match leaves the link as
it was and says why (`Found.problems`).
"""

import json
import re
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import text

from racinglines.sources.nascar import identity as ID
from racinglines.sources.nascar.identity import norm

# Kalshi series ticker -> (kind, who the contract is on, series class when the ticker settles it).
# From the 19 KXNASCAR* series listed on 2026-09-29 (tests/fixtures/market/kalshi_nascar_events.json). A ticker with no
# sample event there (CUPCHAMP, RACEOLD, TOPMANU) is mapped from its series title only; the pass's report shows
# any shape that still does not resolve.
KALSHI = {
    "KXNASCARRACE": ("race_win", "driver", None),                # Cup and O'Reilly races both: told apart by the text
    "KXNASCARRACEOLD": ("race_win", "driver", None),
    "KXNASCARTOP3": ("race_podium", "driver", None),
    "KXNASCARTOP5": ("race_top5", "driver", None),
    "KXNASCARTOP10": ("race_top10", "driver", None),
    "KXNASCARTOP20": ("race_top20", "driver", None),
    "KXNASCARPOLE": ("race_pole", "driver", None),
    "KXNASCARFASTLAP": ("race_fastest_lap", "driver", None),
    "KXNASCARBIGGESTMOVER": ("race_biggest_mover", "driver", None),
    "KXNASCARH2H": ("race_h2h", "matchup", None),                # two drivers a market: athlete = the one that finishes ahead on yes
    "KXNASCARTOPTEAM": ("race_team_win", "team", None),
    "KXNASCARTOPMANU": ("race_manufacturer_win", "manufacturer", None),
    "KXNASCARCUPSERIES": ("champion", "driver", "cup"),
    "KXNASCARCUPCHAMP": ("champion", "driver", "cup"),
    "KXNASCARCUPSEASON": ("regular_season_champion", "driver", "cup"),
    "KXNASCARCHALLENGE": ("in_season_challenge", "driver", "cup"),
    "KXNASCARAUTOPARTSSERIES": ("champion", "driver", "xfinity"),
    "KXNASCARTRUCKSERIES": ("champion", "driver", "trucks"),
}
RACE_KINDS = {k for k, w, _ in KALSHI.values() if k.startswith("race_")}
SEASON_KINDS = {"champion", "regular_season_champion", "in_season_challenge"}
# The wording of a question on the exchanges that have no ticker family (Polymarket, OG.com), in order. Only the two
# shapes seen on real listings; anything else gets no kind, and shows in the report as one.
TEXT_KINDS = (
    (re.compile(r"\bchampion(ship)?\b"), "champion", "driver"),
    (re.compile(r"\bwins?\b|\bwinner\b"), "race_win", "driver"),
)
# Wording that makes a 'win' or 'champion' something else (the pole, a stage, a matchup, the regular-season title): no kind.
NOT_THAT = re.compile(r"\b(pole|fastest|stage|lap|top \d+|podium|finish(es)?|ahead|beat|versus|vs|matchup|head to head|"
                      r"regular season|playoffs?|round of \d+|in season|challenge)\b")
# What a listing says about the series, most specific first ("Xfinity 500" is a Cup race sponsored by Xfinity, so the
# word alone means nothing: it takes "Xfinity Series").
CLASS_HINTS = (
    (re.compile(r"\btruck series\b|^truck series\b"), "trucks"),
    (re.compile(r"\bxfinity series\b|\bauto parts series\b|^auto parts\b"), "xfinity"),
    (re.compile(r"\bcup series\b"), "cup"),
)
# A head-to-head market names both drivers: Kalshi's question "Will Todd Gilliland beat Chase Elliott at the Window World 450 Main
# Race originally scheduled for July 19, 2026?" (yes = the first finishes ahead), its yes side "Todd Gilliland beats Chase Elliott".
PAIR = (re.compile(r"^Will (.+?) (?:finish ahead of|beat) (.+?) (?:at|in) "), re.compile(r"^(.+?) beats (.+)$"))
DATE = re.compile(r"scheduled for ([A-Z][a-z]{2,8})\.? (\d{1,2}), (\d{4})")
SLUG_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})$")
YEAR = re.compile(r"(?<!\d)(20[12]\d)(?!\d)")
TAIL = re.compile(r"\b(?:presented|powered|available|sponsored)\s+(?:by|at)\b.*$")
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
SAME_NAME_DAYS = 3             # a name two races share: the listing's date (or close time) must be within this of one
RESCHEDULE_DAYS = 14           # a race that moved further than this from the listing's date is not trusted
NOT_A_DRIVER = {"", "yes", "no"}


class Found:
    """What one link is about. `problems` lists why a part is missing (a report, not an error)."""

    def __init__(self):
        self.kind = self.series = self.year = self.athlete_id = self.opponent_id = self.race_id = self.race = self.subject = None
        self.problems = []

    def params(self):
        """The keys this adds to the link's params (only those known)."""
        want = {"kind": self.kind, "nascar_series": self.series, "season": self.year, "opponent_id": self.opponent_id}
        return {k: v for k, v in want.items() if v is not None}


def outcome_key(link):
    """One real-world outcome across exchanges: (kind, athlete, "race" | "season", race id or year, opponent id or None). None
    until the link has the kind, the driver and the race (or season); a head-to-head also needs its opponent."""
    p = link.get("params") or {}
    race = p.get("kind") in RACE_KINDS
    where = link.get("race_id") if race else p.get("season")
    if not (p.get("kind") and link.get("athlete_id") and where) or (p["kind"] == "race_h2h" and not p.get("opponent_id")):
        return None
    return (p["kind"], link["athlete_id"], "race" if race else "season", where, p.get("opponent_id"))


def _pair(link):
    """(first driver, second driver) named by a head-to-head market, or None."""
    for field in ("question", "group_title", "outcome"):
        for rx in PAIR:
            m = rx.search(str(link.get(field) or "").strip())
            if m:
                return m.group(1).strip(), m.group(2).strip()
    return None


def _phrases(name):
    """The ways a venue may write a race's name: whole, and without the sponsor tail ('presented by Jiffy Lube')."""
    n = norm(name)
    cut = TAIL.sub("", n).strip()
    return [n] + ([cut] if cut != n and len(cut.split()) >= 2 else [])


def _text_of(link):
    p = link.get("params") or {}
    return " ".join(str(x) for x in (link.get("question"), link.get("event_title"), p.get("rules")) if x)


def _day(raw, link):
    """The race day a listing states: 'originally scheduled for Oct 4, 2026' (Kalshi) or a slug ending in the date."""
    m = DATE.search(raw)
    if m and m.group(1)[:3].lower() in MONTHS:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        except ValueError:
            return None
    m = SLUG_DATE.search(str(link.get("event_slug") or ""))
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _ticker_year(code):
    """The season in a Kalshi event ticker's code: SOUP26 -> 2026, FOCH100326 (MMDDYY) -> 2026, WINW26TOGICHEL -> 2026."""
    code = str(code or "").split("-", 1)[-1]
    m = re.fullmatch(r"[A-Z]+\d{4}(\d{2})", code) or re.search(r"(?<!\d)(\d{2})(?!\d)", code)
    return 2000 + int(m.group(1)) if m else None


def _year(raw, link, day):
    if day:
        return day.year
    m = YEAR.search(raw) or YEAR.search(str(link.get("event_slug") or ""))          # OG.com's symbol ends in the year
    if m:
        return int(m.group(1))
    y = _ticker_year(link.get("event_slug") or link.get("condition_id")) if link.get("exchange") == "kalshi" else None
    if y:
        return y
    end = link.get("end_date")
    return end.year if end is not None else None


def _kind(link, words):
    """(kind, who, series class, sure): from the Kalshi ticker family when there is one (sure), else from the wording
    of the question (a 'win' wording alone is not sure: it is a race contract only once a race is found)."""
    p = link.get("params") or {}
    if link.get("exchange") == "kalshi":
        fam = p.get("series") or str(link.get("event_slug") or link.get("condition_id") or "").split("-", 1)[0]
        if fam in KALSHI:
            return (*KALSHI[fam], True)
    for rx, kind, who in TEXT_KINDS:
        if rx.search(words):
            if NOT_THAT.search(words):
                break
            return kind, who, None, kind == "champion"
    return None, "driver", None, True


class Linker:
    """Identifies market links against the database's NASCAR drivers and Cup races. One Resolver per season is built
    on first use (a link is matched against its own season's drivers and races)."""

    def __init__(self, conn):
        self.conn, self._by_year, self._names = conn, {}, {}
        self.counts = Counter()                             # what fill() has done, summed over its calls
        self.unresolved = defaultdict(Counter)              # reason -> subject strings (drivers) / listing titles (races)

    def resolver(self, year):
        if year not in self._by_year:
            self._by_year[year] = ID.Resolver(self.conn, year)
        return self._by_year[year]

    def has_data(self):
        return bool(self.resolver(None).names)

    def _season(self, year):
        """[(race id, event name, start, [(phrase length, compiled phrase)])] of the season's Cup events."""
        if year not in self._names:
            self._names[year] = [
                (rid, name, start, [(len(p), re.compile(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])")) for p in _phrases(name)])
                for rid, name, start, _ in self.resolver(year).events if start is not None and start.year == year]
        return self._names[year]

    def race_named(self, words, year, day=None, near=None):
        """(race id, event name, None), or (None, None, why): the Cup race of season `year` whose name (as a whole
        phrase) is in `words`. `day`: the date the listing states; `near`: the market's close time, a weaker hint."""
        found = []
        for rid, name, start, phrases in self._season(year):
            hit = max((n for n, rx in phrases if rx.search(words)), default=0)
            if hit:
                found.append((hit, rid, name, start))
        if not found:
            return None, None, "no race of that season named"
        top = max(f[0] for f in found)
        found = [f for f in found if f[0] == top]                   # the longest name wins ("Daytona 500" over "Daytona")
        by = day or (near.date() if hasattr(near, "date") else near)
        if len(found) > 1:
            close = [f for f in found if by and abs((f[3] - by).days) <= SAME_NAME_DAYS]
            if len(close) != 1:
                return None, None, f"{len(found)} races share the name {found[0][2].strip()!r} and the date does not pick one"
            found = close
        _, rid, name, start = found[0]
        if day and abs((start - day).days) > RESCHEDULE_DAYS:
            return None, None, f"{name.strip()!r} is {abs((start - day).days)} days from the listing's date {day}"
        return rid, name, None

    def identify(self, link):
        f = Found()
        raw = _text_of(link)
        words = norm(raw)
        kind, who, cls, sure = _kind(link, words)
        cls = cls or next((c for rx, c in CLASS_HINTS if rx.search(words)), None)
        day = _day(raw, link)
        f.kind, f.series, f.year = kind, cls, _year(raw, link, day)
        if f.year is None:
            f.problems.append("no season found in the listing")
            return f
        if cls in ("xfinity", "trucks"):
            return f                                                 # tagged; no driver or race: we hold no results for the series
        contract = sure
        if kind in RACE_KINDS:
            rid, name, why = self.race_named(words, f.year, day, link.get("end_date"))
            if rid is None and cls == "cup" and day is not None:      # the listing says Cup outright: its date is enough
                rid, name = self.resolver(f.year).race(day, window=1)
            named = rid is not None or not why.startswith("no race")   # some race's name is in the text, even if it is not one race
            if named:
                f.series = f.series or "cup"                         # a Cup race's name is in the text: the listing is Cup
            if rid is not None:
                f.race_id, f.race = rid, name
            elif sure or named:
                f.problems.append(f"race: {why}")
                self.unresolved["race: " + re.sub(r"'[^']*'", "'...'", why)][(link.get("event_title") or "")[:60]] += 1
            contract = sure or named
            if not contract:
                f.kind = None                                        # 'win' wording and no race named: not a race contract
        if f.series == "cup" and f.kind and contract and who == "matchup":
            pair = _pair(link)
            if pair:
                R = self.resolver(f.year)
                a, b = R.driver(pair[0]), R.driver(pair[1])
                if a is not None and b is not None and a != b:
                    f.athlete_id, f.opponent_id = a, b               # both, or neither: half a matchup is no key
                else:
                    for name, got in zip(pair, (a, b)):
                        if got is None:
                            f.problems.append(f"driver: {R.unresolved.get(name, 'unknown')}")
                            self.unresolved["driver: " + R.unresolved.get(name, "unknown").split(":")[0]][name] += 1
            else:
                f.problems.append("matchup: the two drivers are not in the question")
        if f.series == "cup" and f.kind and contract and who == "driver":
            subject = link.get("group_title") if norm(link.get("group_title")) not in NOT_A_DRIVER else link.get("outcome")
            f.subject = subject
            if norm(subject) not in NOT_A_DRIVER:
                R = self.resolver(f.year)
                f.athlete_id = R.driver(subject)
                if f.athlete_id is None:
                    why = R.unresolved.get(subject, "unknown")
                    f.problems.append(f"driver: {why}")
                    self.unresolved["driver: " + why.split(":")[0]][subject] += 1
        return f

    def fill(self, rows):
        """Write what is known into freshly built link rows (a sync's values): athlete_id, race_id and params. Never
        raises: a bad row keeps the sync going and stays as it was. Returns the counts."""
        n = Counter()
        for row in rows:
            n["links"] += 1
            try:
                f = self.identify(row)
            except Exception as e:                                     # a recorder must not stop for an identity bug
                n["errors"] += 1
                n["last_error"] = f"{type(e).__name__}: {e}"
                continue
            self.apply(row, f)
            n["athletes"] += f.athlete_id is not None
            n["races"] += f.race_id is not None
        self.counts.update({k: v for k, v in n.items() if k != "last_error"})
        if "last_error" in n:
            self.counts["last_error"] = n["last_error"]
        return dict(n)

    @staticmethod
    def apply(row, f):
        if f.athlete_id is not None:
            row["athlete_id"] = f.athlete_id
        if f.race_id is not None:
            row["race_id"] = f.race_id
        add = f.params()
        if add:
            row["params"] = dict(row.get("params") or {}, **add)


LINK_COLUMNS = ("id", "exchange", "token_id", "event_slug", "condition_id", "question", "event_title", "outcome", "group_title",
                "end_date", "params", "athlete_id", "race_id")


def relink(session, conn, exchange=None, apply=False, undo_path=None, echo=print):
    """Identify every NASCAR link in the database. Dry run by default: nothing is written and the report says what
    would change. With `apply`: athlete_id, race_id and params of the changed links are updated in one transaction
    (the caller commits), and the previous values of every changed link are written to `undo_path` first, so the pass
    can be undone link by link (`undo`) without restoring a dump and losing the tapes recorded since.
    Returns the report (a dict)."""
    from racinglines.db import models as m
    where, args = "co.code = 'nascar_cup'", {}
    if exchange:
        where += " AND l.exchange = :x"
        args["x"] = exchange
    rows = [dict(zip(LINK_COLUMNS, r)) for r in conn.execute(text(
        f"SELECT {', '.join('l.' + c for c in LINK_COLUMNS)} FROM market_links l JOIN competitions co ON co.id = l.competition_id "
        f"WHERE {where} ORDER BY l.id"), args).all()]
    L = Linker(conn)
    if not L.has_data():
        echo("no NASCAR drivers in the database yet (racinglines nascar fetch, then ingest): only kinds and series are filled")
    shapes = defaultdict(Counter)
    keys = defaultdict(set)
    changes = []
    for row in rows:
        f = L.identify(row)
        fam = (row["params"] or {}).get("series") or str(row["event_slug"] or "").split("-", 1)[0]
        shape = shapes[(row["exchange"], fam if row["exchange"] == "kalshi" else "", f.series or "?", f.kind or "-")]
        shape["links"] += 1
        shape["athlete"] += f.athlete_id is not None
        shape["race"] += f.race_id is not None
        new = dict(row)
        L.apply(new, f)
        if new["athlete_id"] != row["athlete_id"] or new["race_id"] != row["race_id"] or new["params"] != row["params"]:
            changes.append((row, new))
        k = outcome_key(new)
        if k:
            keys[k].add(row["exchange"])
    report = dict(links=len(rows), changed=len(changes), shapes={"|".join(k): dict(v) for k, v in sorted(shapes.items())},
                  unresolved={r: c.most_common(12) for r, c in L.unresolved.items()},
                  across_venues=sum(1 for v in keys.values() if len(v) > 1), outcomes=len(keys))
    if apply and changes:
        if undo_path is None:
            raise ValueError("apply needs an undo file")
        undo_path.parent.mkdir(parents=True, exist_ok=True)
        undo_path.write_text(json.dumps([dict(id=o["id"], athlete_id=o["athlete_id"], race_id=o["race_id"], params=o["params"])
                                         for o, _ in changes], default=str))
        for old, new in changes:
            link = session.get(m.MarketLink, old["id"])
            link.athlete_id, link.race_id, link.params = new["athlete_id"], new["race_id"], new["params"]
        report["undo"] = str(undo_path)
    return report


def undo(session, path):
    """Put back the athlete_id, race_id and params `relink --apply` replaced (the file it wrote). Returns links restored."""
    from racinglines.db import models as m
    old = json.loads(open(path).read())
    for o in old:
        link = session.get(m.MarketLink, o["id"])
        link.athlete_id, link.race_id, link.params = o["athlete_id"], o["race_id"], o["params"]
    return len(old)


def format_report(r):
    """The dry-run text: totals, then one line per shape (exchange, Kalshi series, series, kind: links / with a driver /
    with a race), then what did not resolve."""
    out = [f"{r['links']:,} NASCAR links; {r['changed']:,} would change; {r['outcomes']:,} outcomes fully identified, "
           f"{r['across_venues']:,} of them on more than one venue"]
    out.append(f"  {'exchange':11} {'kalshi series':24} {'class':8} {'kind':22} {'links':>7} {'driver':>7} {'race':>7}")
    for k, v in r["shapes"].items():
        ex, fam, cls, kind = k.split("|")
        out.append(f"  {ex:11} {fam:24} {cls:8} {kind:22} {v['links']:>7,} {v['athlete']:>7,} {v['race']:>7,}")
    for reason, items in r["unresolved"].items():
        out.append(f"  {reason}: " + "; ".join(f"{s!r} x{n}" for s, n in items))
    return "\n".join(out)
