"""
The alpha layout (owner, 2026-10-12 19:18-19:21Z): four tabs and nothing else.

    Markets   what is happening on the prediction markets now, and what the model says about the busiest prices
    Trade     fantasy trading on the recorded books (web/fantasy_routes.py /trade)
    History   every trade, F$ through the run, and the leaderboard (/history)
    Lab       the advanced tools: following a strategy, its performance, backtests, research (templates/_lab_nav.html)

"We will not include live events or private books at all for alpha version" (19:20Z), and the top bar's right side
keeps only the GitHub badge and the account links (19:21Z). Those pages are archived, not deleted: their routes and
templates stay, and with the alpha layout off (RACINGLINES_LAYOUT=classic, or fantasy off, as on production today)
the old bar comes back unchanged. With it on, live events and private books answer 404 except to admins, so they can
be revisited. docs/alpha-layout.md lists what is hidden and how to bring it back.
"""

import os

from fastapi import HTTPException

# what the alpha hides from everyone but admins (route prefixes); the old bar's Live, Books, Pitch and Docs links go too
HIDDEN_PREFIXES = ("/live", "/book")


def alpha():
    """True when the alpha layout is on: RACINGLINES_LAYOUT=alpha, or unset with the fantasy pages on (staging)."""
    v = os.environ.get("RACINGLINES_LAYOUT", "").strip().lower()
    if v:
        return v == "alpha"
    from racinglines.fantasy import ledger as FL
    return FL.on()


def hidden(path, user):
    """True when the alpha layout hides this page from this user."""
    under = any(path == p or path.startswith(p + "/") for p in HIDDEN_PREFIXES)     # /book/..., not /bookmarks
    return alpha() and not (user and user.get("role") == "admin") and under


def guard(request):
    """Route-level check for an archived page: 404 under the alpha layout unless the user is an admin."""
    if hidden(request.url.path, getattr(request.state, "user", None)):
        raise HTTPException(404)
