"""
racinglines admin web app (FastAPI, server-rendered).

Admin-only: every route requires HTTP Basic auth (ADMIN_USERNAME / ADMIN_PASSWORD),
and every form POST carries a CSRF token. Run with `python -m webapp`.
"""

import hashlib
import hmac
import math
import os
import secrets
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from racedb import models as m  # noqa: E402
from racedb.config import get_engine, get_session  # noqa: E402

from . import data, polymarket  # noqa: E402

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Auth + CSRF
# ---------------------------------------------------------------------------

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(16)
if not os.environ.get("ADMIN_PASSWORD"):
    print(f"ADMIN_PASSWORD not set; generated one for this run: {ADMIN_USERNAME} / {ADMIN_PASSWORD}", flush=True)
_SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(32)
CSRF_TOKEN = hmac.new(_SECRET.encode(), b"csrf", hashlib.sha256).hexdigest()

security = HTTPBasic(realm="racinglines admin", auto_error=False)
SESSION_COOKIE = "rl_session"
SESSION_HOURS = 12
PUBLIC_PATHS = ("/login", "/static")


# failed-login throttle: per client IP, MAX_FAILURES within FAILURE_WINDOW seconds -> 429
MAX_FAILURES = 8
FAILURE_WINDOW = 15 * 60
_failures: dict[str, list[float]] = {}


def client_ip(request):
    """Real client address; behind a Cloudflare tunnel every request comes from localhost."""
    return (request.headers.get("cf-connecting-ip")
            or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))


def _throttled(ip):
    now = time.time()
    _failures[ip] = [t for t in _failures.get(ip, []) if now - t < FAILURE_WINDOW]
    return len(_failures[ip]) >= MAX_FAILURES


def _record_failure(ip):
    _failures.setdefault(ip, []).append(time.time())


def _valid_password(username, password):
    ok_user = secrets.compare_digest(username.encode(), ADMIN_USERNAME.encode())
    ok_pass = secrets.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    return ok_user and ok_pass


def _session_value(username, expires):
    sig = hmac.new(_SECRET.encode(), f"{username}|{expires}".encode(), hashlib.sha256).hexdigest()
    return f"{username}|{expires}|{sig}"


def _session_user(cookie):
    try:
        username, expires, sig = cookie.split("|")
        good = hmac.new(_SECRET.encode(), f"{username}|{expires}".encode(), hashlib.sha256).hexdigest()
        if secrets.compare_digest(sig, good) and int(expires) > time.time():
            return username
    except (AttributeError, ValueError):
        pass
    return None


def require_admin(request: Request, creds: HTTPBasicCredentials | None = Depends(security)):
    """Signed session cookie (from /login) or HTTP Basic credentials (scripts / curl).
    Browsers without either are redirected to the login page."""
    if request.url.path.startswith(PUBLIC_PATHS):
        return None
    user = _session_user(request.cookies.get(SESSION_COOKIE))
    if user:
        return user
    ip = client_ip(request)
    if creds:
        if _throttled(ip):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins; try again later")
        if _valid_password(creds.username, creds.password):
            return creds.username
        _record_failure(ip)
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": f"/login?next={request.url.path}"})
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                        headers={"WWW-Authenticate": 'Basic realm="racinglines admin"'})


def check_csrf(csrf_token: str = Form(...)):
    if not secrets.compare_digest(csrf_token, CSRF_TOKEN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bad CSRF token")


app = FastAPI(title="racinglines admin", dependencies=[Depends(require_admin)], docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def fmt(value, col=""):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M") if (value.hour or value.minute) else value.strftime("%Y-%m-%d")
    if isinstance(value, float):
        if col.endswith("_prob") or col in ("model_prob", "edge"):
            return f"{value:.1%}"
        if col.endswith("time_s"):
            mins, secs = divmod(value, 60)
            return f"{int(mins)}:{secs:06.3f}" if mins else f"{secs:.3f}"
        if value.is_integer() and abs(value) < 1e6:
            return f"{int(value)}"
        return f"{value:.3f}" if abs(value) < 10 else f"{value:.1f}"
    return str(value)


templates.env.filters["fmt"] = fmt
templates.env.globals["csrf_token"] = CSRF_TOKEN


def render(request, name, **ctx):
    ctx.setdefault("trading", polymarket.TradingConfig.from_env())
    return templates.TemplateResponse(request, name, ctx)


def rows(df):
    """DataFrame -> list of dicts for templates. ID columns come back from pandas as
    floats when they have gaps (e.g. 45.0); turn them into ints / None so links work."""
    if df is None:
        return []
    df = df.copy()
    for col in df.columns:
        if (col == "id" or col.endswith("_id") or col == "run") and df[col].dtype.kind in "fiu":
            df[col] = pd.Series([None if pd.isna(v) else int(v) for v in df[col]], index=df.index, dtype=object)
    return df.to_dict("records")


def conn():
    with get_engine().connect() as c:
        yield c


# ---------------------------------------------------------------------------
# Pages: predictions, runs, events, athletes
# ---------------------------------------------------------------------------

PRED_COLS = ["athlete", "nation", "win_prob", "podium_prob", "top10_prob", "make_final_prob", "exp_points"]
STAND_COLS = ["athlete", "current_points", "exp_points", "points_p10", "points_p90", "champion_prob",
              "top3_prob", "exp_rank"]


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, c=Depends(conn)):
    blocks = []
    for run in rows(data.latest_forecasts(c)):
        targets = data.run_race_targets(c, run["id"])
        upcoming = [t for t in rows(targets) if not str(t["target"]).startswith("backtest:")]
        sections = [dict(t, table=rows(data.race_predictions(c, run["id"], t["target"], limit=15)))
                    for t in upcoming]
        blocks.append(dict(run=run, sections=sections,
                           standings=rows(data.standings_predictions(c, run["id"], limit=15))))
    return render(request, "dashboard.html", blocks=blocks, pred_cols=PRED_COLS, stand_cols=STAND_COLS)


@app.get("/runs", response_class=HTMLResponse)
def runs(request: Request, kind: str | None = None, c=Depends(conn)):
    return render(request, "runs.html", runs=rows(data.model_runs(c, kind)), kind=kind)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: int, c=Depends(conn)):
    run = data.model_run(c, run_id)
    if not run:
        raise HTTPException(404)
    metrics = {k: pd.DataFrame(v) if isinstance(v, list) else pd.DataFrame([v])
               for k, v in (run.get("metrics") or {}).items()}
    targets = rows(data.run_race_targets(c, run_id))
    preds = [dict(t, table=rows(data.race_predictions(c, run_id, t["target"]))) for t in targets]
    return render(request, "run.html", run=run, metrics={k: (list(v.columns), rows(v)) for k, v in metrics.items()},
                  preds=preds, standings=rows(data.standings_predictions(c, run_id)),
                  pred_cols=PRED_COLS + ["attend_prob", "actual_final_rank", "actual_points"], stand_cols=STAND_COLS)


@app.get("/events", response_class=HTMLResponse)
def events(request: Request, season: int | None = None, c=Depends(conn)):
    venues = data.q(c, "SELECT slug, name FROM venues ORDER BY name")
    comps = data.q(c, "SELECT code, name FROM competitions ORDER BY code")
    return render(request, "events.html", events=rows(data.events(c, season=season)), season=season,
                  venues=rows(venues), comps=rows(comps), today=date.today().isoformat())


@app.post("/events", dependencies=[Depends(check_csrf)])
def create_event(competition: str = Form(...), name: str = Form(...), start_date: str = Form(...),
                 venue: str = Form(...), series_round: str = Form("")):
    """Add a scheduled (future) event, so forecasts and market links can attach to it.
    When its results are ingested later, the ingest adopts this event."""
    with get_session() as s:
        comp = s.scalars(select(m.Competition).filter_by(code=competition)).one()
        d = date.fromisoformat(start_date)
        season = s.scalars(select(m.Season).filter_by(competition_id=comp.id, year=d.year)).first()
        if season is None:
            season = m.Season(competition_id=comp.id, year=d.year)
            s.add(season)
            s.flush()
        v = s.scalars(select(m.Venue).filter_by(slug=venue)).one()
        ev = m.Event(season_id=season.id, source="manual", source_key=f"manual-{d:%Y%m%d}-{venue}", name=name,
                     start_date=d, venue_id=v.id, series_round=int(series_round) if series_round else None,
                     status="scheduled")
        s.add(ev)
        s.commit()
        return RedirectResponse(f"/events/{ev.id}", status_code=303)


@app.get("/events/by-key/{source_key}")
def event_by_key(source_key: str, c=Depends(conn)):
    """Stable link to an event by its source key (e.g. ChronoRace 20260925_mtb)."""
    ev = data.q(c, "SELECT id FROM events WHERE source_key = :k ORDER BY id DESC LIMIT 1", k=source_key)
    if not len(ev):
        raise HTTPException(404, f"no event {source_key}")
    return RedirectResponse(f"/events/{int(ev['id'].iloc[0])}", status_code=303)


@app.get("/pitch", response_class=HTMLResponse)
def pitch():
    """The pitch deck (pitch.html at the repo root), behind the same login."""
    from fastapi.responses import FileResponse
    return FileResponse(ROOT / "pitch.html", media_type="text/html")


@app.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(request: Request, event_id: int, c=Depends(conn)):
    ev = data.event(c, event_id)
    if not ev:
        raise HTTPException(404)
    res = data.event_results(c, event_id)
    groups = [dict(category=cat, round=rnd, table=rows(g))
              for (cat, _, rnd), g in res.groupby(["category", "ordinal", "round"], sort=True)] if len(res) else []
    preds = data.event_predictions(c, event_id)
    pred_groups = [dict(run=int(run), kind=g["kind"].iloc[0], category=cat, table=rows(g.head(30)))
                   for (run, cat), g in preds.groupby(["run", "category"], sort=False)] if len(preds) else []
    return render(request, "event.html", ev=ev, groups=groups, pred_groups=pred_groups)


@app.get("/athletes", response_class=HTMLResponse)
def athletes(request: Request, q: str | None = None, c=Depends(conn)):
    return render(request, "athletes.html", athletes=rows(data.athletes(c, q)), q=q or "")


@app.get("/athletes/{athlete_id}", response_class=HTMLResponse)
def athlete_detail(request: Request, athlete_id: int, c=Depends(conn)):
    a = data.athlete(c, athlete_id)
    if not a:
        raise HTTPException(404)
    return render(request, "athlete.html", a=a, results=rows(data.athlete_results(c, athlete_id)),
                  preds=rows(data.athlete_predictions(c, athlete_id)))


# ---------------------------------------------------------------------------
# Markets + orders
# ---------------------------------------------------------------------------

@app.get("/markets", response_class=HTMLResponse)
def markets(request: Request, c=Depends(conn)):
    links = rows(data.market_links(c))
    for link in links:
        link["model_prob"], _ = data.model_prob(c, link)
    return render(request, "markets.html", links=links)


@app.get("/markets/lookup", response_class=HTMLResponse)
def market_lookup(request: Request, slug: str = "", query: str = "", c=Depends(conn)):
    found, results, error = [], [], None
    try:
        if slug:
            found = polymarket.lookup(slug)
        elif query:
            results = polymarket.search(query)
    except Exception as e:  # network / API errors are shown, not raised
        error = str(e)
    return render(request, "market_lookup.html", slug=slug, query=query, markets=found, results=results,
                  error=error, races=rows(data.upcoming_races(c)),
                  comps=rows(data.q(c, "SELECT id, code FROM competitions ORDER BY code")),
                  cats=rows(data.q(c, "SELECT id, competition_id, code FROM categories ORDER BY code")),
                  predictions=list(data.PREDICTION_COLUMNS))


@app.post("/markets", dependencies=[Depends(check_csrf)])
def create_link(market_slug: str = Form(""), question: str = Form(...), condition_id: str = Form(""),
                token_id: str = Form(...), outcome: str = Form(...), neg_risk: str = Form("false"),
                tick_size: float = Form(0.01), min_size: float = Form(5), athlete_id: int = Form(...),
                prediction: str = Form(...), race_id: str = Form(""), competition_id: int = Form(...),
                category_id: str = Form(""), invert: str = Form(""), note: str = Form("")):
    if prediction not in data.PREDICTION_COLUMNS:
        raise HTTPException(400, "unknown prediction kind")
    with get_session() as s:
        if s.get(m.Athlete, athlete_id) is None:
            raise HTTPException(400, f"no athlete with id {athlete_id}")
        link = m.MarketLink(
            market_slug=market_slug or None, question=question, condition_id=condition_id or None,
            token_id=token_id, outcome=outcome, neg_risk=neg_risk.lower() == "true", tick_size=tick_size,
            min_size=min_size, competition_id=competition_id, category_id=int(category_id) if category_id else None,
            athlete_id=athlete_id, race_id=int(race_id) if race_id else None, prediction=prediction,
            invert=bool(invert), note=note or None)
        s.add(link)
        s.commit()
        return RedirectResponse(f"/markets/{link.id}", status_code=303)


@app.post("/markets/{link_id}/toggle", dependencies=[Depends(check_csrf)])
def toggle_link(link_id: int):
    with get_session() as s:
        link = s.get(m.MarketLink, link_id)
        link.active = not link.active
        s.commit()
    return RedirectResponse("/markets", status_code=303)


def _link_context(c, link_id):
    links = data.market_links(c)
    link = links[links["id"] == link_id]
    if not len(link):
        raise HTTPException(404)
    link = link.iloc[0].to_dict()
    prob, run_id = data.model_prob(c, link)
    try:
        bk, book_error = polymarket.book(link["token_id"]), None
    except Exception as e:
        bk, book_error = None, str(e)
    suggestion = None
    if bk and prob is not None:
        tick = bk["tick_size"]
        buy = math.floor((prob - 2 * tick) / tick) * tick  # quote under fair value
        if bk["best_ask"] is not None:
            buy = min(buy, bk["best_ask"] - tick)
        sell = math.ceil((prob + 2 * tick) / tick) * tick
        if bk["best_bid"] is not None:
            sell = max(sell, bk["best_bid"] + tick)
        suggestion = dict(buy=round(buy, 4) if buy >= tick else None, sell=round(sell, 4) if sell <= 1 - tick else None)
    return link, prob, run_id, bk, book_error, suggestion


@app.get("/markets/{link_id}", response_class=HTMLResponse)
def market_detail(request: Request, link_id: int, c=Depends(conn)):
    link, prob, run_id, bk, book_error, suggestion = _link_context(c, link_id)
    past = data.orders(c)
    return render(request, "market.html", link=link, prob=prob, run_id=run_id, book=bk, book_error=book_error,
                  suggestion=suggestion, orders=rows(past[past["market_link_id"] == link_id]))


@app.post("/markets/{link_id}/preview", response_class=HTMLResponse, dependencies=[Depends(check_csrf)])
def order_preview(request: Request, link_id: int, side: str = Form(...), price: float = Form(...),
                  size: float = Form(...), c=Depends(conn)):
    link, prob, run_id, bk, book_error, _ = _link_context(c, link_id)
    cfg = polymarket.TradingConfig.from_env()
    error, notional = None, None
    if bk is None:
        error = f"could not load the order book: {book_error}"
    else:
        try:
            notional = polymarket.check_order(cfg, side, price, size, bk)
        except polymarket.OrderRejected as e:
            error = str(e)
    edge = None
    if prob is not None:
        edge = (prob - price) if side == "BUY" else (price - prob)
    return render(request, "order_preview.html", link=link, prob=prob, book=bk, side=side, price=price, size=size,
                  notional=notional, edge=edge, error=error, run_id=run_id)


@app.post("/markets/{link_id}/order", dependencies=[Depends(check_csrf)])
def order_submit(link_id: int, side: str = Form(...), price: float = Form(...), size: float = Form(...),
                 confirm: str = Form(""), c=Depends(conn)):
    if confirm != "yes":
        raise HTTPException(400, "order not confirmed")
    link, prob, run_id, bk, book_error, _ = _link_context(c, link_id)
    cfg = polymarket.TradingConfig.from_env()
    rec = m.Order(market_link_id=link_id, token_id=link["token_id"], side=side, price=price, size=size,
                  order_type="GTC", post_only=True, model_prob=prob, model_run_id=run_id,
                  best_bid=bk["best_bid"] if bk else None, best_ask=bk["best_ask"] if bk else None, status="error")
    try:
        if bk is None:
            raise polymarket.OrderRejected(f"could not load the order book: {book_error}")
        rec.status, rec.exchange_order_id, resp = polymarket.place_maker_order(cfg, link["token_id"], side, price,
                                                                                size, bk)
        rec.response = _jsonable(resp)
    except polymarket.OrderRejected as e:
        rec.status, rec.error = "rejected", str(e)
    except Exception as e:
        rec.status, rec.error = "error", f"{type(e).__name__}: {e}"
    with get_session() as s:
        s.add(rec)
        s.commit()
        return RedirectResponse(f"/orders?highlight={rec.id}", status_code=303)


def _jsonable(obj):
    import json
    return json.loads(json.dumps(obj, default=str))


@app.get("/orders", response_class=HTMLResponse)
def orders(request: Request, highlight: int | None = None, c=Depends(conn)):
    cfg = polymarket.TradingConfig.from_env()
    live, live_error = [], None
    try:
        live = polymarket.open_orders(cfg)
    except Exception as e:
        live_error = str(e)
    return render(request, "orders.html", orders=rows(data.orders(c)), live=live, live_error=live_error,
                  highlight=highlight)


@app.post("/orders/{order_id}/cancel", dependencies=[Depends(check_csrf)])
def order_cancel(order_id: int):
    cfg = polymarket.TradingConfig.from_env()
    with get_session() as s:
        rec = s.get(m.Order, order_id)
        if rec is None or not rec.exchange_order_id:
            raise HTTPException(400, "no exchange order to cancel")
        try:
            resp = polymarket.cancel(cfg, rec.exchange_order_id)
            rec.status, rec.response = "cancelled", _jsonable(dict(original=rec.response, cancel=resp))
        except Exception as e:
            rec.error = f"cancel failed: {e}"
        s.commit()
    return RedirectResponse(f"/orders?highlight={order_id}", status_code=303)


# ---------------------------------------------------------------------------
# House markets (private bets we quote ourselves)
# ---------------------------------------------------------------------------

from . import house  # noqa: E402


def _races_for_house(c):
    return rows(data.q(c, """
        SELECT ra.id AS race_id, v.name AS venue, e.start_date, c.code AS category, e.status,
               (SELECT count(*) FROM house_markets hm WHERE hm.race_id = ra.id) AS markets
        FROM races ra JOIN events e ON e.id = ra.event_id JOIN categories c ON c.id = ra.category_id
        LEFT JOIN venues v ON v.id = e.venue_id
        WHERE e.status <> 'completed' OR EXISTS (SELECT 1 FROM house_markets hm WHERE hm.race_id = ra.id)
        ORDER BY e.start_date DESC, c.code"""))


@app.get("/house", response_class=HTMLResponse)
def house_book(request: Request, race_id: int | None = None, msg: str = "", c=Depends(conn)):
    races = _races_for_house(c)
    if race_id is None and races:
        race_id = races[0]["race_id"]
    bk = house.book(c, race_id)
    totals = dict(markets=len(bk), open=int((bk["status"] == "open").sum()), bets=int(bk["bets"].sum()),
                  staked=float(bk["staked"].sum()), ev=float(bk["ev"].sum()), worst=float(bk["worst"].sum()),
                  settled=float(bk["settled_pnl"].dropna().sum())) if len(bk) else None
    groups = [(kind, rows(g)) for kind, g in bk.groupby("kind", sort=False)] if len(bk) else []
    return render(request, "house.html", races=races, race_id=race_id, groups=groups, totals=totals, msg=msg,
                  kinds=list(house.KINDS))


@app.post("/house/generate", dependencies=[Depends(check_csrf)])
async def house_generate(request: Request, c=Depends(conn)):
    form = await request.form()
    race_id = int(form["race_id"])
    kinds = [k for k in form.getlist("kinds") if k in house.KINDS]
    try:
        with get_session() as s:
            created, repriced = house.generate(s, c, race_id, kinds, int(form.get("top_n", 15)),
                                               float(form.get("spread_pct", 6)) / 100)
        msg = f"Created {created} markets, repriced {repriced}."
    except ValueError as e:
        msg = f"Error: {e}"
    return RedirectResponse(f"/house?race_id={race_id}&msg={msg}", status_code=303)


@app.post("/house/settle-auto", dependencies=[Depends(check_csrf)])
def house_settle_auto(race_id: int = Form(...), c=Depends(conn)):
    with get_session() as s:
        done = house.auto_settle(s, c, race_id)
    msg = f"Auto-settled {len(done)} markets." if done else "Nothing to settle yet (Final not in the data)."
    return RedirectResponse(f"/house?race_id={race_id}&msg={msg}", status_code=303)


@app.get("/house/sheet", response_class=HTMLResponse)
def house_sheet(request: Request, race_id: int, c=Depends(conn)):
    bk = house.book(c, race_id)
    bk = bk[bk["status"] == "open"]
    with get_session() as s:
        venue, cat = house.race_label(s, race_id)
    groups = [(kind, rows(g.sort_values("fair_prob", ascending=False))) for kind, g in bk.groupby("kind", sort=False)]
    return render(request, "house_sheet.html", groups=groups, venue=venue, cat=cat,
                  kind_titles={k: v.split(" the ")[0] if not k.startswith("rank") else v for k, v in house.KINDS.items()},
                  now=pd.Timestamp.now(tz="America/Vancouver").strftime("%a %d %b %H:%M %Z"))


@app.get("/house/{market_id}", response_class=HTMLResponse)
def house_market(request: Request, market_id: int, msg: str = "", c=Depends(conn)):
    bk = house.book(c)
    mk = bk[bk["id"] == market_id]
    if not len(mk):
        raise HTTPException(404)
    return render(request, "house_market.html", mk=rows(mk)[0], bets=rows(house.bets(c, market_id)), msg=msg)


@app.post("/house/{market_id}/bet", dependencies=[Depends(check_csrf)])
def house_bet(market_id: int, counterparty: str = Form(...), side: str = Form(...), stake: float = Form(...),
              price: str = Form(""), note: str = Form("")):
    try:
        with get_session() as s:
            b = house.record_bet(s, market_id, counterparty, side, stake, float(price) if price else None, note)
        msg = f"Recorded: {b.counterparty} {b.side} ${b.stake:.2f} at {b.price:.2f} (pays ${b.payout:.2f})."
    except ValueError as e:
        msg = f"Error: {e}"
    return RedirectResponse(f"/house/{market_id}?msg={msg}", status_code=303)


@app.post("/house/{market_id}/price", dependencies=[Depends(check_csrf)])
def house_price(market_id: int, fair_pct: float = Form(...), spread_pct: float = Form(...)):
    with get_session() as s:
        house.set_price(s, market_id, fair_pct / 100, spread_pct / 100)
    return RedirectResponse(f"/house/{market_id}?msg=Repriced (manual fair value).", status_code=303)


@app.post("/house/{market_id}/status", dependencies=[Depends(check_csrf)])
def house_status(market_id: int, status_: str = Form(..., alias="status")):
    if status_ not in ("open", "closed"):
        raise HTTPException(400)
    with get_session() as s:
        s.get(m.HouseMarket, market_id).status = status_
        s.commit()
    return RedirectResponse(f"/house/{market_id}", status_code=303)


@app.post("/house/{market_id}/settle", dependencies=[Depends(check_csrf)])
def house_settle(market_id: int, outcome: str = Form(...), note: str = Form(""), confirm: str = Form("")):
    if confirm != "yes":
        raise HTTPException(400, "settlement not confirmed")
    value = {"yes": True, "no": False, "void": None}[outcome]
    with get_session() as s:
        house.settle(s, market_id, value, f"manual: {note}" if note else "manual")
    return RedirectResponse(f"/house/{market_id}?msg=Settled {outcome.upper()}.", status_code=303)



# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = ""):
    return templates.TemplateResponse(request, "login.html", dict(next=next, error=error))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/")):
    ip = client_ip(request)
    if _throttled(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins; try again in 15 minutes")
    if not _valid_password(username, password):
        _record_failure(ip)
        return RedirectResponse(f"/login?next={next}&error=1", status_code=303)
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    resp = RedirectResponse(target, status_code=303)
    expires = int(time.time()) + SESSION_HOURS * 3600
    https = request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https"
    resp.set_cookie(SESSION_COOKIE, _session_value(username, expires), max_age=SESSION_HOURS * 3600,
                    httponly=True, samesite="lax", secure=https)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
