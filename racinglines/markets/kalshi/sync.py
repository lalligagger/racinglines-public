"""
Sync Kalshi's F1 markets into market_links (exchange = 'kalshi'), map each to the model prediction that
prices it, and store its tape, price history and order books in the same tables as Polymarket's. Nothing runs
unless called (`racinglines markets --exchange kalshi ...`); built and tested on mocked responses only, since
the cloud network policy blocks Kalshi's API. F1 roadmap, F1-9.

One link per Kalshi market: its YES contract (token_id = the market ticker, condition_id = the event ticker;
NO is the mirror image). Titles are classified like Polymarket's (the wording below is a guess from Kalshi's
usual phrasing and must be checked against the live listing):

    "... <GP> ... winner" / "Who will win ... <GP>"      race_win          yes_sub_title = the driver
    "... podium ... <GP>"                                race_podium
    "... pole ... <GP>"                                  race_pole
    "Will A finish ahead of B ... <GP>"                  race_h2h          params.opponent_id
    "... constructor ... <GP>"                           race_constructor_top   yes_sub_title = the team
    "... fastest lap ... <GP>"                           race_fastest_lap
    "... safety car / red flag / rain ... <GP>"          race_safety_car / race_red_flag / race_rain
    "... Drivers' Champion(ship)"                        champion
    "... Constructors' Champion(ship)"                   constructors_champion
    anything else                                        unmodeled (listed with prices, no model price)

Each link keeps Kalshi's resolution rules (params.rules, from rules_primary) so markets on two venues are only
compared when their rules agree (F1-9), and its series ticker (params.series, for the price history).
"""

import re
from datetime import datetime, timezone

from sqlalchemy import select, text

from racinglines.db import models as m
from racinglines.markets.kalshi import client as K

SERIES = ()          # Kalshi series tickers to sync; empty: every Sports series whose title looks like F1
F1_WORDS = re.compile(r"\b(formula\s*1|formula one|f1|grand prix)\b", re.I)
CLOSED = {"closed", "settled", "finalized", "determined"}
STOP = {"who", "will", "win", "the", "a", "an", "at", "in", "of", "formula", "one", "which", "driver", "drivers"}
PROP = [(r"fastest lap", "race_fastest_lap"), (r"safety car", "race_safety_car"), (r"red[- ]flag", "race_red_flag"),
        (r"\brain", "race_rain")]


def gp_name(t):
    """The Grand Prix a title names ("Who will win the Singapore Grand Prix?" -> "Singapore Grand Prix"), or None."""
    for mm in re.finditer(r"((?:[A-Z][A-Za-z\.'-]*\s+)+)Grand Prix", t or ""):
        words = [w for w in mm.group(1).split() if w.lower() not in STOP]
        if words:
            return " ".join(words) + " Grand Prix"
    return None


def classify(event_title, market_title=""):
    """(prediction kind, Grand Prix name or None) for a Kalshi market."""
    t = f"{event_title or ''} {market_title or ''}"
    gp = gp_name(event_title) or gp_name(market_title)
    low = t.lower()
    if re.search(r"constructors'? champion", low):
        return "constructors_champion", None
    if re.search(r"drivers'? champion", low) or (re.search(r"\bchampion(ship)?\b", low) and not gp):
        return "champion", None
    if not gp:
        return "unmodeled", None
    for pat, kind in PROP:
        if re.search(pat, low):
            return kind, gp
    if re.search(r"finish ahead of|head[- ]to[- ]head|\bvs\.?\b", low):
        return "race_h2h", gp
    if "constructor" in low:
        return "race_constructor_top", gp
    if "podium" in low:
        return "race_podium", gp
    if "pole" in low:
        return "race_pole", gp
    if re.search(r"\bwin(ner)?\b", low):
        return "race_win", gp
    return "unmodeled", gp


def _time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _quote(mk):
    """(bid, ask, mid) of the YES contract; an empty side (0 bid / 1.00 ask) is None."""
    bid, ask = K.price(mk, "yes_bid"), K.price(mk, "yes_ask")
    bid = None if not bid else bid
    ask = None if ask is None or ask >= 1.0 else ask
    last = K.price(mk, "last_price")
    mid = (bid + ask) / 2 if bid is not None and ask is not None else (last or None)
    return bid, ask, mid


def link_rows(events, resolver):
    """market_links values (with token_id) for every market of `events` (Kalshi /events with nested markets).
    resolver: driver(name), team(name), race(gp, end_date) -> (race_id, event key), as polymarket.sync.Resolver."""
    rows = []
    for ev in events:
        for mk in ev.get("markets") or []:
            kind, gp = classify(ev.get("title"), mk.get("title"))
            sub = mk.get("yes_sub_title") or mk.get("subtitle") or ""
            end = _time(mk.get("close_time") or mk.get("expiration_time"))
            race_id, race_key = resolver.race(gp, end) if gp else (None, None)
            athlete_id, params = None, None
            if kind == "race_h2h":
                mm = re.search(r"Will (.+?) finish ahead of (.+?)(?: at| in|\?|$)", mk.get("title") or "")
                a, b = (resolver.driver(mm.group(1)), resolver.driver(mm.group(2))) if mm else (None, None)
                athlete_id, params = a, {"opponent_id": b}
            elif kind in ("race_constructor_top", "constructors_champion"):
                params = {"team": resolver.team(sub)}
            elif kind in ("race_win", "race_podium", "race_pole", "race_fastest_lap", "champion"):
                athlete_id = resolver.driver(sub)
            matched = kind == "unmodeled" or (
                (athlete_id is not None or (params or {}).get("team") or kind in ("race_safety_car", "race_red_flag", "race_rain"))
                and (params is None or all(v is not None for v in params.values()))
                and (not kind.startswith("race_") or race_id is not None))
            params = dict(params or {}, **({"event_key": race_key} if race_key else {}),
                          series=ev.get("series_ticker"), rules=mk.get("rules_primary") or None)
            bid, ask, mid = _quote(mk)
            status = (mk.get("status") or "").lower()
            result = (mk.get("result") or "").lower()
            tick = mk.get("tick_size")
            rows.append(dict(
                token_id=mk["ticker"], exchange="kalshi", market_slug=mk["ticker"],
                question=mk.get("title") or ev.get("title") or mk["ticker"], condition_id=mk.get("event_ticker") or ev.get("event_ticker"),
                outcome=sub or "Yes", neg_risk=bool(ev.get("mutually_exclusive")),
                tick_size=(float(tick) / 100 if tick else 0.01), min_size=1.0,
                athlete_id=athlete_id, race_id=race_id, prediction=kind if matched else "unmodeled",
                params={k: v for k, v in params.items() if v is not None}, invert=False,
                event_slug=ev.get("event_ticker"), event_title=ev.get("title"), group_title=sub or mk.get("title"),
                last_bid=bid, last_ask=ask, last_price=mid, volume=float(mk["volume"]) if mk.get("volume") is not None else None,
                end_date=end, closed=status in CLOSED, resolved_yes={"yes": True, "no": False}.get(result),
                active=status not in CLOSED))
    return rows


def f1_series(kc):
    """The series tickers to sync: SERIES, or every Sports series whose title looks like F1."""
    if SERIES:
        return list(SERIES)
    return [s["ticker"] for s in kc.series(category="Sports") if F1_WORDS.search(s.get("title") or "")]


def sync(session, conn, year=2026, include_closed=False, kc=None):
    """Upsert one market_links row per Kalshi F1 market (open ones; with include_closed, settled ones too).
    kc: a kalshi Client (default: a new one on the network)."""
    from racinglines.markets.polymarket.sync import Resolver
    comp = session.scalars(select(m.Competition).filter_by(code="f1_wdc")).one()
    cat = session.scalars(select(m.Category).filter_by(competition_id=comp.id, code="DRV")).one()
    kc = kc or K.Client()
    now = datetime.now(timezone.utc)
    events = []
    for s in f1_series(kc):
        events += kc.events(series_ticker=s, status="open")
        if include_closed:
            events += kc.events(series_ticker=s, status="settled")
    events = list({e["event_ticker"]: e for e in events}.values())      # an event can come back under both statuses
    stats = dict(events=len(events), links=0, modeled=0, unmatched=0, new=0)
    for row in link_rows(events, Resolver(conn, year)):
        tok = row.pop("token_id")
        values = dict(row, competition_id=comp.id, category_id=cat.id, synced_at=now)
        link = session.scalars(select(m.MarketLink).filter_by(exchange="kalshi", token_id=tok)).first()
        if link is None:
            session.add(m.MarketLink(token_id=tok, first_seen_at=now, **values))
            stats["new"] += 1
        else:
            for k, v in values.items():
                setattr(link, k, v)
        stats["links"] += 1
        stats["modeled" if row["prediction"] != "unmodeled" else "unmatched"] += 1
    session.commit()
    return stats


def trade_rows(ticker, event_ticker, trades):
    """market_trades rows for Kalshi trades: the taker's side of the YES contract (taker bought YES = BUY,
    bought NO = SELL YES), at the YES price; size in contracts."""
    rows = []
    for t in trades:
        yes = K.price(t, "yes_price")
        if yes is None:
            continue
        rows.append(dict(token_id=ticker, condition_id=event_ticker or ticker, outcome_index=0, ts=_time(t["created_time"]),
                         side="BUY" if (t.get("taker_side") or "").lower() == "yes" else "SELL", price=yes,
                         size=float(t.get("count_fp") or t.get("count") or 0), tx_hash=str(t["trade_id"])[:80],
                         wallet=""))            # no wallets on Kalshi; "" (not NULL) keeps uq_market_trade deduplicating
    return rows


def _tickers(conn, event_tickers, open_only=False):
    return conn.execute(text("""SELECT token_id, condition_id, params->>'series' FROM market_links
                                WHERE exchange = 'kalshi' AND condition_id = ANY(:e) AND (NOT :o OR NOT closed)"""),
                        dict(e=list(event_tickers), o=open_only)).all()


def fetch_trades(session, conn, event_tickers, since=None, kc=None):
    """Store every trade on the markets of the given Kalshi events. Idempotent. Returns trades stored."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    kc = kc or K.Client()
    n = 0
    for tok, ev, _ in _tickers(conn, event_tickers):
        rows = trade_rows(tok, ev, kc.trades(tok, min_ts=int(since.timestamp()) if since else None))
        for i in range(0, len(rows), 1000):
            session.execute(pg_insert(m.MarketTrade).values(rows[i:i + 1000]).on_conflict_do_nothing(constraint="uq_market_trade"))
        n += len(rows)
    session.commit()
    return n


def history_rows(ticker, candles):
    """market_price_history rows from Kalshi candlesticks: the close of the YES price, else the bid/ask mid."""
    rows = []
    for c in candles:
        p = K.price(c.get("price") or {}, "close")
        if p is None:
            b, a = K.price(c.get("yes_bid") or {}, "close"), K.price(c.get("yes_ask") or {}, "close")
            p = (b + a) / 2 if b is not None and a is not None else None
        if p is not None:
            rows.append(dict(token_id=ticker, ts=datetime.fromtimestamp(int(c["end_period_ts"]), tz=timezone.utc), price=p))
    return rows


def fetch_history(session, conn, event_tickers, start, end, period=60, kc=None):
    """Store price history (candlesticks, `period` minutes: 1, 60 or 1440) for the given Kalshi events."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    kc = kc or K.Client()
    n = 0
    for tok, _, series in _tickers(conn, event_tickers):
        rows = history_rows(tok, kc.candlesticks(series, tok, start.timestamp(), end.timestamp(), period))
        if rows:
            session.execute(pg_insert(m.MarketPriceHistory).values(rows).on_conflict_do_update(
                index_elements=["token_id", "ts"], set_={"price": pg_insert(m.MarketPriceHistory).excluded.price}))
        n += len(rows)
    session.commit()
    return n


def book_row(ticker, ob, ts, depth=10):
    """A market_book_snapshots row from Kalshi's order book (YES bids and NO bids; a NO bid at p is a YES ask
    at 1 - p). Levels [[price, contracts]], best first."""
    def levels(side):
        d = ob.get(f"{side}_dollars")
        if d:
            return [(float(p), float(q)) for p, q in d]
        return [(float(p) / 100, float(q)) for p, q in ob.get(side) or []]
    bids = sorted(levels("yes"), reverse=True)
    asks = sorted((round(1 - p, 4), q) for p, q in levels("no"))
    return dict(token_id=ticker, ts=ts, best_bid=bids[0][0] if bids else None, best_ask=asks[0][0] if asks else None,
                bids=[list(x) for x in bids[:depth]], asks=[list(x) for x in asks[:depth]])


def snapshot_books(session, conn, event_tickers, depth=10, kc=None):
    """One order-book snapshot for every open market of the given Kalshi events. Returns snapshots stored."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    kc = kc or K.Client()
    now = datetime.now(timezone.utc)
    rows = [book_row(tok, kc.orderbook(tok, depth), now, depth) for tok, _, _ in _tickers(conn, event_tickers, open_only=True)]
    if rows:
        session.execute(pg_insert(m.MarketBookSnapshot).values(rows).on_conflict_do_nothing())
        session.commit()
    return len(rows)
