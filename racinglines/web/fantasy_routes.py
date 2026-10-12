"""
The fantasy pages (owner, 2026-10-12 08:40Z, staging only): an account's F$ ("1k balance they can see"), trading by
hand ("first-cut manual trading") next to following a strategy, and the leaderboard.

    /fantasy               your F$: the total, cash, open trades, the followed strategy, recent orders
    /fantasy/trade         the tradable F1 markets with their recorded best prices; ?link=<id> opens one market's
                           book and the order form
    POST /fantasy/orders   one IOC paper order (fantasy/exchange.place), then back to the market with the result
    /leaderboard           every registered account ranked by total F$

All of it is off unless fantasy/ledger.on() (RACINGLINES_FANTASY=1, or staging with the switch unset): 404 otherwise.
Before `racinglines users setup` has created the trading tables the pages say so and nothing is written. F$ only:
nothing here reaches an exchange (fantasy/exchange.py). Split out of web/app.py, which imports this module.
"""

import uuid
from urllib.parse import quote

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from racinglines.fantasy import exchange as FX
from racinglines.fantasy import ledger as FL
from racinglines.web import demo
from racinglines.web.app import ANY, allow, app, audit, check_csrf, get_engine, render

HIDDEN = ("polymarket-takers",)          # the system account (web/accounts.RESERVED); demo accounts are added at call time


def _gate():
    if not FL.on():
        raise HTTPException(404)


def _ready():
    from racinglines.web import accounts as ACC
    with get_engine().connect() as c:
        return ACC.ready(c) and FL.ready(c)


def _books():
    return FX.books_engine(get_engine())


@app.get("/fantasy", response_class=HTMLResponse, dependencies=[allow(*ANY)])
def fantasy_home(request: Request, msg: str = ""):
    _gate()
    me = request.state.user
    if not _ready():
        return render(request, "fantasy.html", ready=False, msg=msg)
    from racinglines.pipelines import profiles as PF
    eng = get_engine()
    with eng.connect() as c:
        q = FX.quotes(_books(), FL.open_tokens(c, me["id"]))
        s = FL.summary(c, me["id"], quotes=q)
        pos = FL.positions(c, me["id"], open_only=True, quotes=q)
        recent = FL.orders(c, me["id"], limit=15)
        profile = PF.of_user(c, me["id"])
        board = FL.leaderboard(c, hide=(*HIDDEN, *demo.DEMO_USERS), quotes=FX.quotes(_books(), FL.open_tokens(c)))
    rank = next((r["rank"] for r in board if r["username"] == me["username"]), None)
    return render(request, "fantasy.html", ready=True, s=s, positions=pos, orders=recent, profile=profile, rank=rank,
                  players=len(board), msg=msg, is_demo_user=demo.is_demo(me), reasons=FX.TEXT)


def _markets(c, search=""):
    """The links a player may trade now, newest events first: F1, Kalshi and Polymarket, open and unresolved, in the
    tradable kinds. Closing times are checked when an order is placed. -> [dict]"""
    kinds = sorted({k for ks in FX.tradable().values() for k in ks})
    rs = c.execute(text("""
        SELECT ml.id, ml.exchange, ml.token_id, ml.prediction AS kind, ml.question, ml.group_title, ml.outcome,
               ml.event_title, ml.last_bid, ml.last_ask, e.start_date
        FROM market_links ml JOIN competitions co ON co.id = ml.competition_id JOIN sports sp ON sp.id = co.sport_id
        LEFT JOIN races ra ON ra.id = ml.race_id LEFT JOIN events e ON e.id = ra.event_id
        WHERE sp.code = :sport AND ml.exchange = ANY(:x) AND ml.prediction = ANY(:k) AND ml.active AND NOT ml.closed
          AND ml.resolved_yes IS NULL AND (e.start_date IS NULL OR e.start_date >= current_date - 1)
          AND (:q = '' OR ml.question ILIKE :like OR ml.group_title ILIKE :like OR ml.event_title ILIKE :like)
        ORDER BY e.start_date NULLS LAST, ml.event_title, ml.exchange, ml.prediction, ml.group_title, ml.id"""),
        dict(sport=FX.SPORT, x=list(FX.EXCHANGES), k=kinds, q=search, like=f"%{search}%")).mappings().all()
    return [dict(r) for r in rs]


@app.get("/fantasy/trade", response_class=HTMLResponse, dependencies=[allow(*ANY)])
def fantasy_trade(request: Request, link: int = 0, q: str = "", msg: str = "", action: str = "buy", side: str = "yes"):
    _gate()
    me = request.state.user
    if not _ready():
        return render(request, "fantasy_trade.html", ready=False, msg=msg)
    eng = get_engine()
    q = q.strip()[:60]
    with eng.connect() as c:
        markets = _markets(c, q)
        quotes = FX.quotes(_books(), [m["token_id"] for m in markets])
        for m in markets:
            b, a, ts = quotes.get(m["token_id"], (None, None, None))
            m.update(bid=b, ask=a, quoted=ts)
        markets = [m for m in markets if m["quoted"] is not None]          # recorded in the last day
        sel = book = pos = None
        if link:
            sel = c.execute(text("""SELECT id, exchange, token_id, prediction AS kind, question, group_title, outcome,
                                           event_title FROM market_links WHERE id = :i"""), dict(i=link)).mappings().first()
            if sel is not None:
                sel = dict(sel)
                book = FX.latest_book(_books(), sel["token_id"])
                if book:
                    nb, na = FX.yes_to_no(book["bids"], book["asks"])
                    book.update(no_bids=nb, no_asks=na)
                held = [p for p in FL.positions(c, me["id"], open_only=True) if p["market_link_id"] == sel["id"]]
                pos = held[0] if held else None
        cash = FL.cash(c, me["id"])
    events = []
    for m in markets:
        if not events or events[-1]["title"] != (m["event_title"] or "Season"):
            events.append(dict(title=m["event_title"] or "Season", start=m["start_date"], markets=[]))
        events[-1]["markets"].append(m)
    return render(request, "fantasy_trade.html", ready=True, events=events, n=len(markets), sel=sel, book=book,
                  pos=pos, cash=cash, q=q, msg=msg, action=action if action in ("buy", "sell") else "buy",
                  side=side if side in ("yes", "no") else "yes", client_key=uuid.uuid4().hex, max_stake=FX.MAX_STAKE,
                  max_age=FX.MAX_AGE_MIN, is_demo_user=demo.is_demo(me))


@app.post("/fantasy/orders", dependencies=[Depends(check_csrf), allow(*ANY)])
def fantasy_order(request: Request, market_link_id: str = Form(""), side: str = Form(""), action: str = Form(""),
                  shares: str = Form(""), limit_price: str = Form(""), client_key: str = Form("")):
    _gate()
    me = request.state.user
    back = f"/fantasy/trade?link={market_link_id}" if market_link_id.isdigit() else "/fantasy/trade"
    if not _ready():
        msg = "Error: fantasy trading isn't set up yet."
    elif not FX.rate_ok(me["id"]):
        audit(request, "fantasy_order_rejected", reason="rate_limited", link=market_link_id)
        msg = "Error: " + FX.TEXT["rate_limited"]
    else:
        r = FX.place(get_engine(), me, market_link_id, side, action, shares, limit_price, client_key=client_key,
                     demo=demo.is_demo(me))
        if not r["ok"]:
            msg = "Error: " + r["message"]
        else:
            got = sum(s for _, s in r["fills"])
            avg = sum(p * s for p, s in r["fills"]) / got
            msg = (f"{'Bought' if action == 'buy' else 'Sold'} {got:g} {side.upper()} at an average of {avg:.2f}"
                   + (f", fee F${r['fee']:.2f}" if r["fee"] else "")
                   + (" (part of your order: the rest wasn't on the book at your limit)" if r["status"] == "partial" else "")
                   + (" (already placed)" if r.get("repeat") else "") + ".")
    sep = "&" if "?" in back else "?"
    return RedirectResponse(f"{back}{sep}msg={quote(msg)}", status_code=303)


@app.get("/leaderboard", response_class=HTMLResponse, dependencies=[allow(*ANY)])
def leaderboard_page(request: Request):
    _gate()
    if not _ready():
        return render(request, "leaderboard.html", ready=False, rows=[])
    with get_engine().connect() as c:
        rows = FL.leaderboard(c, hide=(*HIDDEN, *demo.DEMO_USERS), quotes=FX.quotes(_books(), FL.open_tokens(c)))
    return render(request, "leaderboard.html", ready=True, rows=rows)
