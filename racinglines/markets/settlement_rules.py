"""
Settlement of a race that is cancelled or moved (docs/paper-trading.md, "Cancelled and relocated races"; roadmap U8).

A market kind says what pays when the race runs (markets/kinds.py). This module says what each venue pays when it
doesn't: one table per venue, applied on top of the result-based settlement everywhere paper positions settle
(the private book's settle_from_results, the weekend sweep's markets that the signal engine's paper positions are
built from, and the maker replay). Everything here is behind a switch that is OFF by default:

    RACINGLINES_CANCELLED_RACE_RULES=1        or  rules=True on the settlement call

so the settlement output without it is unchanged. With the switch off, a cancelled race simply never settles
(no classification) and a relocated race settles on its result, as before.

Race status
    cancelled   the race never ran (events.status = 'cancelled' in the database, RACE_STATUS below, or the
                env RACINGLINES_RACE_STATUS="f1:2026-22=cancelled,f1:2026-23=cancelled").
    relocated   the race ran at another circuit under the same name (2026 round 16: the Bahrain GP at Sepang,
                listed as "Bahrain Grand Prix in Malaysia"). Its markets settle on the race that was run: the
                result. RACE_STATUS records it so the rule (and the test) is explicit.
    None        a normal race.

What is fact and what is assumed (the owner should confirm the assumptions before relying on them):
    Polymarket, cancelled
        FACT (data/archive/markets/polymarket/links, the April 2026 Bahrain markets): when the race did not run
        on its scheduled date (12 Apr 2026), every named-driver / constructor market resolved NO and the
        "Other" market of each group ("Will any other driver win ...?") resolved YES: 174 named markets NO, 9
        "Other" markets YES, 23 not recorded. The markets for the rescheduled race (round 16, October) are new
        markets and settle on the race at Sepang.
        ASSUMED: binary markets (head-to-heads) have no "Other"; Polymarket's usual sports rule for an event that
        is not held is a 50/50 resolution, encoded as a 0.5 payout (`cancelled_binary`).
    Kalshi, cancelled
        The rule text Kalshi publishes per market (params.rules in the archive) names the race "originally
        scheduled for <date>" and says only what resolves YES ("If X finishes first ... then the market resolves
        to Yes"); the archive holds no Kalshi race market on a race that was cancelled, so what Kalshi did is not
        observable. ASSUMED: a condition that can never be met resolves NO for every contract, named or binary.
        Kalshi could instead void the market; change `cancelled` to VOID here if it does. Kalshi's own market on
        whether the race happens (KXF1OCCUR-26ADGP, "take place in Abu Dhabi before December 7, 2026") is a
        separate, unmodeled market and is not settled here.
    Private book, cancelled
        Our own rule: every bet is void, stakes returned (private_book.settle(outcome=None)).
    Any venue, relocated
        Markets on the race as run settle on its result. FACT for Polymarket round 16 (listed anew for Sepang);
        Kalshi's "originally scheduled for" wording points the same way; the private book's spec is the race.
"""

import os

VOID = "void"                      # refund at cost: every share settles at the price it was bought or sold at
ENV = "RACINGLINES_CANCELLED_RACE_RULES"
STATUS_ENV = "RACINGLINES_RACE_STATUS"
CANCELLED, RELOCATED = "cancelled", "relocated"

# What a YES share pays on a market of a race that did not run, per venue and market shape:
#   cancelled          a named outcome (a driver, a constructor) in a multi-outcome group: win, podium, pole, ...
#   cancelled_other    the group's "Other" / "any other driver" outcome (Polymarket only)
#   cancelled_binary   a two-sided market with no "Other": head-to-head
#   relocated          RESULT: settle on the race that was run
# Values: True (pays 1), False (pays 0), a float payout (0.5), VOID (refund at cost), RESULT.
RESULT = "result"
RULES = {
    "polymarket": dict(cancelled=False, cancelled_other=True, cancelled_binary=0.5, relocated=RESULT),
    "kalshi": dict(cancelled=False, cancelled_other=False, cancelled_binary=False, relocated=RESULT),
    "private": dict(cancelled=VOID, cancelled_other=VOID, cancelled_binary=VOID, relocated=RESULT),
}
ASSUMED = {("polymarket", "cancelled_binary"), ("kalshi", "cancelled"), ("kalshi", "cancelled_other"),
           ("kalshi", "cancelled_binary")}    # the entries above that are not backed by data in the repo

BINARY_KINDS = {"race_h2h"}
OTHER_NAMES = ("other", "any other", "another", "field")

# Races whose status isn't (or isn't only) in the database: (sport, event key) -> status.
RACE_STATUS = {
    ("f1", "2026-16"): RELOCATED,      # Bahrain GP run at Sepang, Malaysia ("Bahrain Grand Prix in Malaysia")
}


def enabled(rules=None):
    """The switch: `rules` when given (True / False), else the environment (off by default)."""
    if rules is not None:
        return bool(rules)
    return os.environ.get(ENV, "").lower() in ("1", "true", "yes")


def env_status():
    """{(sport, event_key): status} from RACINGLINES_RACE_STATUS ("f1:2026-22=cancelled,f1:2026-23=cancelled")."""
    out = {}
    for item in os.environ.get(STATUS_ENV, "").split(","):
        if "=" not in item:
            continue
        key, status = item.rsplit("=", 1)
        sport, _, event = key.strip().partition(":")
        status = status.strip().lower()
        if status in (CANCELLED, RELOCATED) and event:
            out[(sport.strip(), event.strip())] = status
    return out


def race_status(sport, event_key, db_status=None):
    """cancelled / relocated / None for a race: the database's events.status ('cancelled'), the env override,
    then RACE_STATUS."""
    if db_status and str(db_status).lower() == CANCELLED:
        return CANCELLED
    return env_status().get((sport, event_key)) or RACE_STATUS.get((sport, event_key))


def db_status(conn, race_id):
    """events.status of a race (None when the race isn't in the database)."""
    from sqlalchemy import text
    return conn.execute(text("SELECT e.status FROM races ra JOIN events e ON e.id = ra.event_id WHERE ra.id = :r"),
                        dict(r=race_id)).scalar()


def is_other(name):
    n = str(name or "").strip().lower()
    return n in OTHER_NAMES or n.startswith(OTHER_NAMES[1:])


def payout(venue, status, kind, outcome_name=None):
    """What a YES share of the market pays under the race's status: True / False / 0.5 / VOID, or RESULT when
    the race's result decides (a normal or relocated race). Unknown venues follow the private book's table."""
    if status is None:
        return RESULT
    table = RULES.get(venue, RULES["private"])
    if status == RELOCATED:
        return table["relocated"]
    if status != CANCELLED:
        raise ValueError(f"unknown race status {status!r}")
    if kind in BINARY_KINDS:
        return table["cancelled_binary"]
    return table["cancelled_other"] if is_other(outcome_name) else table["cancelled"]


def apply(venue, status, kind, outcome_name, result):
    """The settled outcome of a market: `result` (the result-based YES/NO, or None while undecided) unless the
    race's status says otherwise. Returns True / False / None / 0.5 / VOID."""
    p = payout(venue, status, kind, outcome_name)
    return result if p == RESULT else p


def value(outcome):
    """A settled outcome as the price of a YES share: 1.0 / 0.0 / 0.5; None for VOID or undecided."""
    if outcome is None or outcome == VOID:
        return None
    return float(outcome)


def settle_position(yes, no, cash, outcome):
    """A paper position's P&L at settlement: cash + shares at the payout; VOID refunds every share at cost, so
    the P&L is 0. None while undecided."""
    if outcome is None:
        return None
    if outcome == VOID:
        return 0.0
    y = float(outcome)
    return cash + yes * y + no * (1 - y)


def describe(venue, status, kind, outcome_name=None):
    """A settlement note: 'Polymarket rule for a cancelled race: named outcome pays 0 (assumed)'."""
    p = payout(venue, status, kind, outcome_name)
    if p == RESULT:
        return f"{status or 'normal'} race: settled on the result"
    shape = "cancelled_binary" if kind in BINARY_KINDS else ("cancelled_other" if is_other(outcome_name) else "cancelled")
    what = {True: "pays 1", False: "pays 0", VOID: "void, stakes returned"}.get(p, f"pays {p}")
    tag = " (assumed; confirm with the venue)" if (venue, shape) in ASSUMED else ""
    return f"{venue} rule for a {status} race: {shape.replace('cancelled_', '').replace('cancelled', 'named')} outcome {what}{tag}"
