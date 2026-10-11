"""
Which sports a signed-in user sees ([sport] audience in sports/<code>.toml, racinglines/sports.py audience): an
"admin" sport is left out of every page for everyone but admins, and its pages answer 404. Only the web app reads it:
recording, pricing, settlement and the CLI carry on, and no data is deleted.

    hidden(user)            the sport codes this user doesn't see (none for an admin)
    hidden_comps(user)      their competition codes
    shown(user, code)       False when a sport or competition code is hidden from this user
    guard(user, code)       404 when it is (a race, event, season or run page of a hidden sport)
    guard_athlete(conn, user, athlete_id)   404 for an athlete who only raced (or was priced) in hidden sports
"""

from fastapi import HTTPException

from racinglines import sports as SP


def _admin(user):
    return isinstance(user, dict) and user.get("role") == "admin"


def hidden(user):
    return frozenset() if _admin(user) else SP.admin_only()


def hidden_comps(user):
    return frozenset() if _admin(user) else SP.admin_only_competitions()


def shown(user, code):
    return not code or (code not in hidden(user) and code not in hidden_comps(user))


def guard(user, code):
    if not shown(user, code):
        raise HTTPException(404)


def guard_athlete(conn, user, athlete_id):
    hide = hidden_comps(user)
    if not hide:
        return
    from racinglines.db import reads
    comps = reads.athlete_competitions(conn, athlete_id)
    if comps and comps <= hide:
        raise HTTPException(404)
