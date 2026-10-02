"""
Sync Polymarket cycling markets into market_links and map each outcome to the
prediction that prices it.

    "Tour de France 2026: Winner"     race_win         athlete, race
    "Il Lombardia 2026: Podium"       race_podium      athlete, race
    "Tour de France 2026: Top 10"     race_top10       athlete, race
    (other predictions mapped similarly)

Prices come from the Gamma API (bestBid / bestAsk / lastTradePrice / outcomePrices).
Idempotent: links are keyed by token id and updated in place.

Cycling is a tape-only sport (no pricing model yet), so all links are `unmodeled`
until a model is built. The identity pass (sources/cycling/links.py) fills athlete_id
and race_id.
"""

import json
import re
import unicodedata
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, text

from racinglines import sports
from racinglines.db import models as m
from racinglines.markets import identity
from racinglines.sources import http

GAMMA = "https://gamma-api.polymarket.com"
TAGS = ("cycling",)  # Polymarket's Gamma API tag for cycling markets


def _norm(s):
    """Normalize text for comparison: lowercase ASCII, no punctuation."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s).strip()


def _f(v):
    """Convert value to float, or None."""
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def competition(session, sport="cycling"):
    """(Competition, its first Category) for cycling, as the tape-only sync files links under."""
    schema = sports.load(sport)
    comp = session.scalars(select(m.Competition).filter_by(code=schema["competition"]["code"])).one()
    cat_code = next(iter(schema["competition"]["categories"]))
    return comp, session.scalars(select(m.Category).filter_by(competition_id=comp.id, code=cat_code)).one()


def _events(tags=TAGS):
    """Active cycling events from the given Gamma tags."""
    out = {}
    with httpx.Client(base_url=GAMMA, timeout=30) as c:
        for tag in tags:
            for e in http.get(c, "/events", params={"tag_slug": tag, "active": "true", "closed": "false",
                                                    "limit": 200}).json():
                out[e["slug"]] = e
    return out


def sync(session, conn, year=2026, include_closed=False, new=None, sport="cycling", tags=None):
    """
    Fetch every active cycling event and upsert one market_links row per outcome token.
    Tokens seen for the first time get first_seen_at and, if `new` is a list, are appended to it.

    Cycling is tape-only: every link is filed `unmodeled` under the cycling competition.
    The identity pass (sources/cycling/links.py) fills athlete_id and race_id on cycling links.
    
    Args:
        session: SQLAlchemy session
        conn: Database connection
        year: Market season (for filtering)
        include_closed: Whether to include closed markets from the given year
        new: Optional list to append newly seen tokens to
        sport: Sport name, default "cycling"
        tags: Override Gamma tag slugs (default: ("cycling",))
    """
    tags = tuple(tags or sports.polymarket_tags(sport) or TAGS)
    comp, cat = competition(session, sport)
    events = _events(tags)

    now = datetime.now(timezone.utc)
    stats = dict(events=0, links=0, new=0)

    # Tape-only sports use the identity linker to fill athlete_id/race_id
    who = identity.linker(sport, conn)

    for slug, ev in events.items():
        stats["events"] += 1
        for mk in ev.get("markets", []):
            if not mk.get("clobTokenIds"):
                continue

            outcomes = json.loads(mk.get("outcomes") or "[]")
            tokens = json.loads(mk.get("clobTokenIds") or "[]")
            prices = [_f(p) for p in json.loads(mk.get("outcomePrices") or "[]")]
            bid, ask = _f(mk.get("bestBid")), _f(mk.get("bestAsk"))
            end = datetime.fromisoformat(mk["endDate"].replace("Z", "+00:00")) if mk.get("endDate") else None
            closed = bool(mk.get("closed"))

            # For tape-only sports, we upsert the first outcome token only (like F1's unmodeled markets)
            # The identity pass later fills in athlete_id and race_id
            tokens_to_upsert = [(0, outcomes[0] if outcomes else "Yes")]

            t_bid, t_ask = (bid, ask) if bid is not None else (None, None)
            mid = (t_bid + t_ask) / 2 if t_bid is not None and t_ask is not None else (prices[0] if prices else None)
            resolved = None
            if closed and len(prices) > 0 and prices[0] in (0.0, 1.0):
                resolved = prices[0] == 1.0

            values = dict(
                exchange="polymarket", market_slug=mk.get("slug"), question=mk.get("question") or ev.get("title"),
                condition_id=mk.get("conditionId"), outcome=str(outcomes[0] if outcomes else "Yes"),
                neg_risk=bool(mk.get("negRisk") or ev.get("negRisk")),
                tick_size=_f(mk.get("orderPriceMinTickSize")) or 0.01,
                min_size=_f(mk.get("orderMinSize")) or 5,
                competition_id=comp.id, category_id=cat.id,
                athlete_id=None, race_id=None,  # filled by identity linker
                prediction="unmodeled",  # all cycling links are unmodeled until a model is built
                params=None,  # will be filled by identity linker
                invert=False,
                event_slug=slug, event_title=ev.get("title"),
                group_title=outcomes[0] if outcomes else str(outcomes[0] if outcomes else ""),
                last_bid=t_bid, last_ask=t_ask, last_price=mid,
                volume=_f(mk.get("volume")),
                end_date=end, closed=closed, resolved_yes=resolved,
                synced_at=now, active=not closed
            )

            # Let the identity linker fill in athlete_id, race_id, and params
            if who:
                who.fill([values])

            # Upsert the market link by token_id
            if len(tokens) > 0:
                token_id = tokens[0]
                link = session.scalars(select(m.MarketLink).filter_by(token_id=token_id)).first()
                if link is None:
                    session.add(m.MarketLink(token_id=token_id, first_seen_at=now, **values))
                    stats["new"] += 1
                    if new is not None:
                        new.append(dict(values, token_id=token_id))
                else:
                    for k, v in values.items():
                        setattr(link, k, v)
                stats["links"] += 1

    if who:
        stats["identity"] = dict(who.counts)

    session.commit()
    return stats
