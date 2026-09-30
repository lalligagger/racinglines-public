"""
Account roles and access tiers, in one place.

    admin   everything, plus the activity log, user management and the database explorer
    pro     every maker and taker strategy, the private book, and the Lab (backtests, Edge Finder,
            diagnostics, replays)
    basic   a limited set of taker strategies (BASIC_PROFILES) on Markets / Strategy / Positions / Live;
            no fair values, no book, no Lab

`pro` and `basic` were called `maker` and `taker` until 2026-09-30. Rows written before then still carry the old
spelling (no migration in that change): `canonical()` maps them, every user dict the app builds goes through it,
and `db_roles()` spells both forms for SQL `role IN (...)` filters. A one-line migration
(`UPDATE users SET role = 'pro' WHERE role = 'maker'`, same for taker -> basic) retires the aliases; until it runs,
nothing here breaks on either spelling. Strategy names (`maker` / `update` / `hold` ... in candidates and sweeps)
are not roles and are untouched.
"""

ROLES = ("admin", "pro", "basic")
LEGACY = {"maker": "pro", "taker": "basic"}       # old role value -> current role
PRO = ("admin", "pro")                            # the tier that sees fair values, the book and the Lab
BASIC = ("basic",)
ANY = ROLES

# The strategy profiles a basic account may run (codes from pipelines/profiles.PROFILES). Pro and admin may run
# any candidate. Widen this list to give basic accounts more taker strategies; a maker strategy never belongs here.
BASIC_PROFILES = ("A",)


def canonical(role):
    """The current spelling of a stored role ('maker' -> 'pro', 'taker' -> 'basic'; anything else unchanged)."""
    return LEGACY.get(role, role)


def db_roles(*roles):
    """Every stored spelling of these roles, for SQL `role IN (...)`: db_roles('pro') -> ('pro', 'maker')."""
    out = []
    for r in roles:
        out.append(r)
        out.extend(old for old, new in LEGACY.items() if new == r)
    return tuple(out)


def is_pro(user):
    return canonical(user["role"]) in PRO


def is_basic(user):
    return canonical(user["role"]) == "basic"


def basic_profile_names():
    """The candidate names a basic account may be assigned (the profiles behind BASIC_PROFILES)."""
    from racinglines.pipelines import profiles as PF
    return tuple(PF.PROFILES[c]["name"] for c in BASIC_PROFILES if c in PF.PROFILES)


def allowed_profile(role, profile):
    """May an account with this role run this strategy profile (a dict from profiles.load, or None)?
    Admin and pro: any. Basic: only the taker profiles in BASIC_PROFILES, by candidate name."""
    if profile is None or canonical(role) in PRO:
        return True
    return profile.get("name") in basic_profile_names()
