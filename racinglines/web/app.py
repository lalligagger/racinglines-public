"""
racinglines web app (FastAPI, server-rendered).

Three roles (see users.py): admin, maker, taker. Every route needs a signed-in
user (session cookie from /login, or HTTP Basic) and declares which roles may
use it; every form POST carries a CSRF token; every meaningful action is
written to activity_log. Run with `racinglines web`.
"""

import hashlib
import hmac
import math
import os
import secrets
import threading
import time
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[2]      # the repository

from racinglines.db import models as m  # noqa: E402
from racinglines.db.config import get_engine, get_session  # noqa: E402

from racinglines.db import reads as data  # noqa: E402
from racinglines.markets.polymarket import trade as polymarket

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Auth (users table, roles) + CSRF
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager  # noqa: E402

from racinglines.web import users as U  # noqa: E402

_SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(32)
CSRF_TOKEN = hmac.new(_SECRET.encode(), b"csrf", hashlib.sha256).hexdigest()

security = HTTPBasic(realm="racinglines", auto_error=False)
SESSION_COOKIE = "rl_session"
SESSION_HOURS = 12
PUBLIC_PATHS = ("/login", "/static", "/racinglines101")

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


def _session_value(user_id, expires, sid=""):
    """Signed cookie: user id, expiry, and a per-sign-in session id (a demo session's key, web/demo.py)."""
    body = f"{user_id}|{expires}|{sid}"
    sig = hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


def _session(cookie):
    """(user id, session id) from a valid, unexpired cookie, else (None, None). Accepts the older
    three-part cookie (no session id)."""
    try:
        parts = cookie.split("|")
        body, sig = "|".join(parts[:-1]), parts[-1]
        good = hmac.new(_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        if secrets.compare_digest(sig, good) and int(parts[1]) > time.time():
            return int(parts[0]), (parts[2] if len(parts) == 4 else None)
    except (AttributeError, ValueError, IndexError):
        pass
    return None, None


def _session_user_id(cookie):
    return _session(cookie)[0]


def _user_dict(u):
    return dict(id=u.id, username=u.username, role=u.role, display_name=u.display_name or u.username)


def authenticate(request: Request, creds: HTTPBasicCredentials | None = Depends(security)):
    """Signed session cookie (from /login) or HTTP Basic credentials (scripts / curl).
    The user and role are re-read from the database on every request, so
    deactivating a user or changing a role takes effect immediately."""
    if request.url.path.startswith(PUBLIC_PATHS):
        return None
    uid, sid = _session(request.cookies.get(SESSION_COOKIE))
    if uid is not None:
        with get_session() as s:
            u = U.get_user(s, user_id=uid)
            if u and u.active:
                request.state.user = dict(_user_dict(u), sid=sid)
                return request.state.user
    ip = client_ip(request)
    if creds:
        if _throttled(ip):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins; try again later")
        with get_session() as s:
            u = U.authenticate(s, creds.username, creds.password)
            if u:
                request.state.user = _user_dict(u)
                return request.state.user
        _record_failure(ip)
        U.log(get_engine(), None, "login_failed", request, username=creds.username, via="basic")
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": f"/login?next={request.url.path}"})
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                        headers={"WWW-Authenticate": 'Basic realm="racinglines"'})


def allow(*roles):
    """Route dependency: only these roles may use the route. Returns the user dict."""
    def dep(request: Request):
        u = getattr(request.state, "user", None)
        if not u or u["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This page is only for: {', '.join(roles)}.")
        return u
    return Depends(dep)


ANY = ("admin", "maker", "taker")


def check_csrf(csrf_token: str = Form(...)):
    if not secrets.compare_digest(csrf_token, CSRF_TOKEN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bad CSRF token")


def audit(request, action, **detail):
    U.log(get_engine(), getattr(request.state, "user", None), action, request, **detail)


@asynccontextmanager
async def lifespan(app):
    with get_session() as s:
        U.ensure_admin(s)
    threading.Thread(target=_warm_diagnostics, daemon=True).start()
    from racinglines.web import jobs
    jobs.start_worker()
    yield


def _warm_diagnostics():
    """Compute the event replays (and their sweeps) once at startup so /diag pages open fast."""
    from racinglines.web import diag
    try:
        with get_engine().connect() as c:
            for e in diag.event_summaries(c):
                diag.replay(c, e["run_id"], **diag.DEFAULT_KNOBS)
    except Exception as ex:  # noqa: BLE001  (a cold cache is only slower)
        print(f"diagnostics warm-up skipped: {ex}")


from racinglines.web import demo as _demo  # noqa: E402
app = FastAPI(title="racinglines", dependencies=[Depends(authenticate), Depends(_demo.guard)], docs_url=None, redoc_url=None,
              lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

MONEY_COLS = {"pnl", "spread_pnl", "markout_60m", "markout_5m", "model_edge", "worst_case", "cash", "taker_pnl"}


def fmt(value, col=""):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M") if (value.hour or value.minute) else value.strftime("%Y-%m-%d")
    if isinstance(value, float):
        if col.endswith("_prob") or col in ("model_prob", "edge", "quoted_share"):
            return f"{value:.1%}"
        if col in MONEY_COLS:
            return f"{value:+,.2f}"
        if col.endswith("time_s"):
            mins, secs = divmod(value, 60)
            return f"{int(mins)}:{secs:06.3f}" if mins else f"{secs:.3f}"
        if value.is_integer() and abs(value) < 1e6:
            return f"{int(value)}"
        return f"{value:.3f}" if abs(value) < 10 else f"{value:.1f}"
    return str(value)


templates.env.filters["fmt"] = fmt


def money(v, sign=False):
    """-302.97 -> '-$302.97'; sign=True adds '+' to positives."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    s = "-" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{s}${abs(v):,.2f}"


templates.env.filters["money"] = money
# Demo-only explanations (the demo accounts' story, the demo itself) render in `demo_context` bubbles
# (_macros.html) tagged data-tag="demo-context". RACINGLINES_DEMO_CONTEXT=0 hides them all; for real users,
# delete every `demo_context` call.
DEMO_CONTEXT = {"on": os.environ.get("RACINGLINES_DEMO_CONTEXT", "1") != "0"}
templates.env.globals["demo_context_on"] = lambda: DEMO_CONTEXT["on"]      # read at render time
templates.env.globals["csrf_token"] = CSRF_TOKEN


def _seen_since(user):
    """A demo session's "signals seen up to" time (web/demo.py overlay), else None (the database's seen_at)."""
    from racinglines.web import demo
    return demo.prefs(user["sid"]).get("signals_seen_at") if demo.is_demo(user) and user.get("sid") else None


def _signals_nav(user):
    """The Signals link for the nav (users with a strategy profile, and admins): unread signals, and the
    account's paper summary (profile, bankroll, P&L) for the banner on the home and trading pages."""
    if not user:
        return None
    try:
        with get_engine().connect() as c:
            r = c.execute(text("""SELECT prefs ? 'strategy_profile', prefs->'strategy_profile'->>'name',
                                         (prefs->'strategy_profile'->'bankroll'->>'start')::float,
                                         (SELECT count(*) FROM strategy_signals WHERE user_id = :u AND seen_at IS NULL
                                            AND status <> 'expired'
                                            AND (CAST(:since AS timestamptz) IS NULL OR created_at > CAST(:since AS timestamptz))),
                                         (SELECT sum(cash + yes_shares * coalesce(outcome::int, mark)
                                                 + no_shares * (1 - coalesce(outcome::int, mark)))
                                            FROM paper_positions WHERE user_id = :u)
                                  FROM users WHERE id = :u"""),
                          dict(u=user["id"], since=_seen_since(user))).first()
    except Exception:                                   # noqa: BLE001  the nav never breaks a page
        return None
    if r is None or not (r[0] or user["role"] == "admin"):
        return None
    pnl = float(r[4] or 0.0)
    return dict(unread=int(r[3] or 0), profile=r[1], start=r[2], pnl=pnl,
                balance=(r[2] + pnl) if r[2] else None, ret=(pnl / r[2]) if r[2] else None)


def render(request, name, **ctx):
    ctx.setdefault("trading", polymarket.TradingConfig.from_env())
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx.setdefault("signals_nav", _signals_nav(ctx["user"]))
    from racinglines.web import demo
    u = ctx["user"]
    ctx.setdefault("storage_ns", f"demo.{u.get('sid')}." if demo.is_demo(u) and u.get("sid") else "")
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
    # missing values -> None, so templates' "is not none" checks work (NaN would print "nan")
    return [{k: (None if not isinstance(v, (dict, list, str)) and pd.isna(v) else v) for k, v in r.items()}
            for r in df.to_dict("records")]


def conn():
    with get_engine().connect() as c:
        yield c


# ---------------------------------------------------------------------------
# Pages: predictions, runs, events, athletes
# ---------------------------------------------------------------------------

PRED_COLS = ["athlete", "nation", "win_prob", "podium_prob", "top10_prob", "make_final_prob", "exp_points"]
STAND_COLS = ["athlete", "current_points", "exp_points", "points_p10", "points_p90", "champion_prob",
              "top3_prob", "exp_rank"]


@app.get("/lab/runs/{run_id}", response_class=HTMLResponse, dependencies=[allow("admin", "maker")])
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


@app.post("/events", dependencies=[Depends(check_csrf), allow("admin")])
def create_event(request: Request, competition: str = Form(...), name: str = Form(...), start_date: str = Form(...),
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
        audit(request, "event_create", event_id=ev.id, name=name, start_date=start_date, venue=venue)
        return RedirectResponse(f"/events/{ev.id}", status_code=303)


@app.get("/events/by-key/{source_key}")
def event_by_key(source_key: str, c=Depends(conn)):
    """Stable link to an event by its source key (e.g. ChronoRace 20260925_mtb)."""
    ev = data.q(c, "SELECT id FROM events WHERE source_key = :k ORDER BY id DESC LIMIT 1", k=source_key)
    if not len(ev):
        raise HTTPException(404, f"no event {source_key}")
    return RedirectResponse(f"/events/{int(ev['id'].iloc[0])}", status_code=303)


@app.get("/racinglines101", response_class=HTMLResponse)
def racinglines101(request: Request):
    """Plain-language intro to makers, takers and the paper-trading demo (public, linked from the login page)."""
    return render(request, "racinglines101.html")


@app.get("/pitch", response_class=HTMLResponse)
def pitch():
    """The pitch deck (pitch.html at the repo root), behind the same login."""
    from fastapi.responses import FileResponse
    return FileResponse(ROOT / "pitch.html", media_type="text/html")


SITE = ROOT / "site"     # the built docs (mkdocs build -d site; the pre-push hook builds it)


@app.get("/docs")
def docs_root():
    return RedirectResponse("/docs/", status_code=307)


@app.get("/docs/{path:path}")
def docs(path: str):
    """The built docs (site/), behind the same login."""
    from fastapi.responses import FileResponse
    f = (SITE / path).resolve()
    if not f.is_relative_to(SITE.resolve()):
        raise HTTPException(404)
    if f.is_dir():
        f = f / "index.html"
    if not f.is_file():
        if not SITE.is_dir():
            raise HTTPException(404, "Docs not built: run python -m mkdocs build -d site")
        raise HTTPException(404)
    return FileResponse(f)


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
    if request.state.user["role"] == "taker":
        pred_groups = []  # model fair values are the makers' edge
    return render(request, "event.html", ev=ev, groups=groups, pred_groups=pred_groups)


@app.get("/athletes", response_class=HTMLResponse)
def athletes(request: Request, q: str | None = None, c=Depends(conn)):
    return render(request, "athletes.html", athletes=rows(data.athletes(c, q)), q=q or "")


@app.get("/athletes/{athlete_id}", response_class=HTMLResponse)
def athlete_detail(request: Request, athlete_id: int, c=Depends(conn)):
    a = data.athlete(c, athlete_id)
    if not a:
        raise HTTPException(404)
    preds = [] if request.state.user["role"] == "taker" else rows(data.athlete_predictions(c, athlete_id))
    return render(request, "athlete.html", a=a, results=rows(data.athlete_results(c, athlete_id)), preds=preds)


# ---------------------------------------------------------------------------
# Markets + orders
# ---------------------------------------------------------------------------

@app.get("/markets/linked", response_class=HTMLResponse, dependencies=[allow("admin")])
def markets(request: Request, c=Depends(conn)):
    links = rows(data.market_links(c))
    for link in links:
        link["model_prob"], _ = data.model_prob(c, link)
    return render(request, "markets.html", links=links)


@app.get("/markets/linked/lookup", response_class=HTMLResponse, dependencies=[allow("admin")])
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
                  predictions=data.PREDICTION_KINDS)


@app.post("/markets/linked", dependencies=[Depends(check_csrf), allow("admin")])
def create_link(request: Request, market_slug: str = Form(""), question: str = Form(...), condition_id: str = Form(""),
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
        audit(request, "polymarket_link", link_id=link.id, question=question, outcome=outcome, athlete_id=athlete_id,
              prediction=prediction)
        return RedirectResponse(f"/markets/linked/{link.id}", status_code=303)


@app.post("/markets/linked/{link_id}/toggle", dependencies=[Depends(check_csrf), allow("admin")])
def toggle_link(link_id: int):
    with get_session() as s:
        link = s.get(m.MarketLink, link_id)
        link.active = not link.active
        s.commit()
    return RedirectResponse("/markets/linked", status_code=303)


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


@app.get("/markets/linked/{link_id}", response_class=HTMLResponse, dependencies=[allow("admin")])
def market_detail(request: Request, link_id: int, c=Depends(conn)):
    link, prob, run_id, bk, book_error, suggestion = _link_context(c, link_id)
    past = data.orders(c)
    return render(request, "market.html", link=link, prob=prob, run_id=run_id, book=bk, book_error=book_error,
                  suggestion=suggestion, orders=rows(past[past["market_link_id"] == link_id]))


@app.post("/markets/linked/{link_id}/preview", response_class=HTMLResponse, dependencies=[Depends(check_csrf), allow("admin")])
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


@app.post("/markets/linked/{link_id}/order", dependencies=[Depends(check_csrf), allow("admin")])
def order_submit(request: Request, link_id: int, side: str = Form(...), price: float = Form(...), size: float = Form(...),
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
        audit(request, "polymarket_order", order_id=rec.id, link_id=link_id, side=side, price=price, size=size,
              status=rec.status, error=rec.error)
        return RedirectResponse(f"/orders?highlight={rec.id}", status_code=303)


def _jsonable(obj):
    import json
    return json.loads(json.dumps(obj, default=str))


@app.get("/orders", response_class=HTMLResponse, dependencies=[allow("admin")])
def orders(request: Request, highlight: int | None = None, c=Depends(conn)):
    cfg = polymarket.TradingConfig.from_env()
    live, live_error = [], None
    try:
        live = polymarket.open_orders(cfg)
    except Exception as e:
        live_error = str(e)
    return render(request, "orders.html", orders=rows(data.orders(c)), live=live, live_error=live_error,
                  highlight=highlight)


@app.post("/orders/{order_id}/cancel", dependencies=[Depends(check_csrf), allow("admin")])
def order_cancel(request: Request, order_id: int):
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
        audit(request, "polymarket_cancel", order_id=order_id, status=rec.status, error=rec.error)
    return RedirectResponse(f"/orders?highlight={order_id}", status_code=303)


# ---------------------------------------------------------------------------
# Private book: markets quoted by makers (admin = house), bets placed by takers
# ---------------------------------------------------------------------------

from racinglines.markets import private_book as house  # noqa: E402

MAX_STAKE = float(os.environ.get("MAX_STAKE", "100"))   # per-bet cap for taker bets (demo)


def _races_for_house(c):
    season = data.q(c, "SELECT count(*) AS n FROM house_markets WHERE race_id IS NULL AND status = 'open'")
    pseudo = [dict(race_id=0, venue="Season-long markets (championships, props)", start_date=None, category="",
                   status="open", markets=int(season["n"].iloc[0]))] if int(season["n"].iloc[0]) else []
    return pseudo + rows(data.q(c, """
        SELECT ra.id AS race_id, v.name AS venue, e.start_date, c.code AS category, e.status,
               (SELECT count(*) FROM house_markets hm WHERE hm.race_id = ra.id) AS markets
        FROM races ra JOIN events e ON e.id = ra.event_id JOIN categories c ON c.id = ra.category_id
        LEFT JOIN venues v ON v.id = e.venue_id
        WHERE e.status <> 'completed' OR EXISTS (SELECT 1 FROM house_markets hm WHERE hm.race_id = ra.id)
        ORDER BY e.start_date, c.code"""))


def _own_market(user, market_id):
    """Load a market; makers may only touch their own, admin any."""
    with get_session() as s:
        mk = s.get(m.HouseMarket, market_id)
        if mk is None:
            raise HTTPException(404)
        if user["role"] != "admin" and mk.maker_id != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your market.")
        return mk


@app.get("/book/quotes", response_class=HTMLResponse)
def house_book(request: Request, race_id: int | None = None, maker: str = "", msg: str = "", c=Depends(conn),
               user=allow("admin", "maker")):
    races = _races_for_house(c)
    if race_id is None and races:
        race_id = races[0]["race_id"]
    if user["role"] == "maker":
        maker_filter = user["id"]
    elif maker == "house":
        maker_filter = None
    elif maker:
        with get_session() as s:
            mu = U.get_user(s, username=maker)
            maker_filter = mu.id if mu else -1
    else:
        maker_filter = house.ALL
    bk = house.book(c, race_id, maker_id=maker_filter)
    totals = dict(markets=len(bk), open=int((bk["status"] == "open").sum()), bets=int(bk["bets"].sum()),
                  staked=float(bk["staked"].sum()), ev=float(bk["ev"].sum()), worst=float(bk["worst"].sum()),
                  settled=float(bk["settled_pnl"].dropna().sum())) if len(bk) else None
    groups = [(kind, rows(g)) for kind, g in bk.groupby("kind", sort=False)] if len(bk) else []
    makers = rows(data.q(c, "SELECT username FROM users WHERE role IN ('maker', 'admin') ORDER BY username"))
    return render(request, "house.html", races=races, race_id=race_id, groups=groups, totals=totals, msg=msg,
                  kinds=list(house.KINDS) + ["race_top10"], makers=makers, maker=maker)


@app.post("/book/quotes/generate", dependencies=[Depends(check_csrf)])
async def house_generate(request: Request, c=Depends(conn), user=allow("admin", "maker")):
    form = await request.form()
    race_id = int(form["race_id"])
    kinds = [k for k in form.getlist("kinds") if k in house.PROB_FIELD]
    top_n, spread = int(form.get("top_n", 15)), float(form.get("spread_pct", 6)) / 100
    try:
        with get_session() as s:
            created, repriced = house.generate(s, c, race_id, kinds, top_n, spread, maker_id=user["id"])
        msg = f"Created {created} markets, repriced {repriced}."
        audit(request, "markets_generate", race_id=race_id, kinds=kinds, top_n=top_n, spread=spread,
              created=created, repriced=repriced)
    except ValueError as e:
        msg = f"Error: {e}"
    nxt = form.get("next") or ""
    if nxt.startswith("/races/"):
        return RedirectResponse(f"{nxt}?msg={msg}#k-race_win", status_code=303)
    return RedirectResponse(f"/book/quotes?race_id={race_id}&msg={msg}", status_code=303)


@app.post("/book/quotes/settle-auto", dependencies=[Depends(check_csrf), allow("admin")])
def house_settle_auto(request: Request, race_id: int = Form(...), c=Depends(conn)):
    with get_session() as s:
        done = house.auto_settle(s, c, race_id)
    audit(request, "settle_auto", race_id=race_id, settled=[d[0] for d in done])
    msg = f"Auto-settled {len(done)} markets." if done else "Nothing to settle yet (Final not in the data)."
    return RedirectResponse(f"/book/quotes?race_id={race_id}&msg={msg}", status_code=303)


@app.get("/book/quotes/sheet", response_class=HTMLResponse, dependencies=[allow(*ANY)])
def house_sheet(request: Request, race_id: int, c=Depends(conn)):
    bk = house.book(c, race_id, status="open")
    with get_session() as s:
        venue, cat = house.race_label(s, race_id)
    groups = [(kind, rows(g.sort_values("fair_prob", ascending=False))) for kind, g in bk.groupby("kind", sort=False)]
    return render(request, "house_sheet.html", groups=groups, venue=venue, cat=cat,
                  now=pd.Timestamp.now(tz="America/Vancouver").strftime("%a %d %b %H:%M %Z"))


@app.get("/book/markets/{market_id}", response_class=HTMLResponse)
def house_market(request: Request, market_id: int, msg: str = "", c=Depends(conn), user=allow("admin", "maker")):
    _own_market(user, market_id)
    bk = house.book(c)
    mk = bk[bk["id"] == market_id]
    return render(request, "house_market.html", mk=rows(mk)[0], bets=rows(house.bets(c, market_id)), msg=msg)


@app.post("/book/markets/{market_id}/bet", dependencies=[Depends(check_csrf), allow("admin")])
def house_bet(request: Request, market_id: int, counterparty: str = Form(...), side: str = Form(...),
              stake: float = Form(...), price: str = Form(""), note: str = Form("")):
    """Admin records an offline bet for a counterparty without an account."""
    try:
        with get_session() as s:
            b = house.record_bet(s, market_id, counterparty, side, stake, float(price) if price else None, note)
        audit(request, "bet_record_offline", market_id=market_id, counterparty=counterparty, side=side,
              stake=stake, price=b.price, bet_id=b.id)
        msg = f"Recorded: {b.counterparty} {b.side} ${b.stake:.2f} at {b.price:.2f} (pays ${b.payout:.2f})."
    except ValueError as e:
        msg = f"Error: {e}"
    return RedirectResponse(f"/book/markets/{market_id}?msg={msg}", status_code=303)


@app.post("/book/markets/{market_id}/price", dependencies=[Depends(check_csrf)])
def house_price(request: Request, market_id: int, fair_pct: float = Form(...), spread_pct: float = Form(...),
                user=allow("admin", "maker")):
    _own_market(user, market_id)
    with get_session() as s:
        house.set_price(s, market_id, fair_pct / 100, spread_pct / 100)
    audit(request, "market_price", market_id=market_id, fair=fair_pct / 100, spread=spread_pct / 100)
    return RedirectResponse(f"/book/markets/{market_id}?msg=Repriced (manual fair value).", status_code=303)


@app.post("/book/markets/{market_id}/status", dependencies=[Depends(check_csrf)])
def house_status(request: Request, market_id: int, status_: str = Form(..., alias="status"),
                 user=allow("admin", "maker")):
    if status_ not in ("open", "closed"):
        raise HTTPException(400)
    _own_market(user, market_id)
    with get_session() as s:
        s.get(m.HouseMarket, market_id).status = status_
        s.commit()
    audit(request, "market_status", market_id=market_id, status=status_)
    return RedirectResponse(f"/book/markets/{market_id}", status_code=303)


@app.post("/book/markets/{market_id}/settle", dependencies=[Depends(check_csrf), allow("admin")])
def house_settle(request: Request, market_id: int, outcome: str = Form(...), note: str = Form(""),
                 confirm: str = Form("")):
    if confirm != "yes":
        raise HTTPException(400, "settlement not confirmed")
    value = {"yes": True, "no": False, "void": None}[outcome]
    with get_session() as s:
        house.settle(s, market_id, value, f"manual: {note}" if note else "manual")
    audit(request, "settle_manual", market_id=market_id, outcome=outcome, note=note)
    return RedirectResponse(f"/book/markets/{market_id}?msg=Settled {outcome.upper()}.", status_code=303)


# ---------------------------------------------------------------------------
# Takers: browse open markets from every maker, place bets, see own bets
# ---------------------------------------------------------------------------

def bet_markets(request: Request, msg: str = "", c=None):          # served at /markets for takers (views.board_page)
    """Every open Polymarket F1 market, with the account's strategy profile's current call on each (side,
    size, most to pay, heat), never our fair value or edge. Upcoming races first (listed or not yet), then
    season markets, then everything else. There is no maker here: takers trade on Polymarket."""
    from racinglines.pipelines import profiles as PF
    from racinglines.pipelines import weekend_sweep as WS
    user = request.state.user
    profile = PF.of_user(c, user["id"])
    if profile is None or profile["strategy"] not in WS.TAKER_MODES:
        try:
            profile = PF.load(c, "A")
        except ValueError:
            profile = None
    return render(request, "bet.html", msg=msg, profile=profile, **polymarket_calls(c, profile))


def polymarket_calls(c, profile, n_races=3):
    """Every open Polymarket F1 market with `profile`'s current call: a taker's side / size / limit / heat
    (signals.call) or a maker's quotes (signals.maker_call). -> dict(races (the next n, listed or not),
    season, other, synced, n_markets). Never exposes fair values."""
    from datetime import timedelta as _td

    from racinglines.markets import store as MS
    from racinglines.pipelines import signals as SG
    from racinglines.pipelines import weekend_sweep as WS
    maker = bool(profile and profile["strategy"] not in WS.TAKER_MODES)
    call = SG.maker_call if maker else SG.call
    links = data.q(c, """
        SELECT ml.*, a.display_name AS athlete, e.source_key AS event_key, e.start_date, e.status AS event_status,
               coalesce(ra.format->>'event_name', e.name) AS race_name
        FROM market_links ml LEFT JOIN athletes a ON a.id = ml.athlete_id
        LEFT JOIN races ra ON ra.id = ml.race_id LEFT JOIN events e ON e.id = ra.event_id
        WHERE ml.exchange = 'polymarket' AND NOT ml.closed
        ORDER BY ml.end_date NULLS LAST, ml.event_title, ml.last_price DESC NULLS LAST""")
    now = pd.Timestamp.now(tz="UTC")
    vol = {}
    if len(links):
        tr = MS.read(c, "trades", conditions=links["condition_id"].dropna().unique().tolist(),
                     start=now - _td(hours=24), end=now)
        if len(tr):
            vol = (tr["price"] * tr["size"]).groupby(tr["condition_id"]).sum().to_dict()
    runs, cache = {}, {}
    rows_ = []
    num = lambda v: None if v is None or pd.isna(v) else float(v)                # noqa: E731
    for link in links.to_dict("records"):
        link.update(last_bid=num(link["last_bid"]), last_ask=num(link["last_ask"]), volume=num(link["volume"]))
        if (link["last_bid"] or 0) <= 0 and (link["last_ask"] is None or link["last_ask"] >= 1):
            continue                                     # an empty book (e.g. a placeholder "Driver A"): not a bet
        kind = link["prediction"]
        ek = link["event_key"] if isinstance(link["event_key"], str) else None
        fair = None
        if profile and ek and kind.startswith("race_"):
            if ek not in runs:
                runs[ek] = SG.latest_run(c, profile, ek)
            if runs[ek]:
                fair = data.model_prob(c, link, cache, run_id=runs[ek])[0]
        mid = link["last_price"] if link["last_price"] is not None and not pd.isna(link["last_price"]) else None
        # 24 h volume from the recorded tape (race-weekend markets); None where no tape is recorded
        v24 = vol.get(link["condition_id"], 0.0) if kind.startswith("race_") else None
        cl = call(profile, kind, fair, mid, v24) if profile else dict(action=None, why="")
        subject = link["athlete"] or (link["params"].get("team") if isinstance(link["params"], dict) else None) \
            or link["group_title"] or link["outcome"]
        if kind == "race_h2h":
            subject = f"{link['outcome']} ({link['question'].split(': ')[-1]})"
        rows_.append(dict(link, subject=subject, mid=mid, call=cl, volume_24h=vol.get(link["condition_id"], 0.0),
                          heat_label=SG.HEAT_LABEL.get(cl.get("heat")) if cl.get("heat") else None))
    by_event = {}
    for r in rows_:
        by_event.setdefault(r["event_slug"], []).append(r)
    events = [dict(slug=k, title=v[0]["event_title"], end_date=v[0]["end_date"], event_key=v[0]["event_key"],
                   kind=v[0]["prediction"], rows=v, calls=sum(1 for r in v if r["call"].get("action")))
              for k, v in by_event.items()]
    sched = WS.schedule(now.year)
    upcoming = [w for _, w in sorted(sched.items()) if w["race_start"].tz_localize("UTC") > now][:n_races]
    try:
        from racinglines.models.position_sim.pricing import upcoming_schedule
        loc = dict(upcoming_schedule(now.year)[["round", "location"]].itertuples(index=False))
    except Exception:                                   # noqa: BLE001  (offline: names only)
        loc = {}
    races = []
    for w in upcoming:
        evs = [e for e in events if e["event_key"] == w["event_key"]]
        races.append(dict(name=w["name"], location=loc.get(int(w["event_key"].split("-")[1])), event_key=w["event_key"], start=w["race_start"], events=evs,
                          priced=bool(profile and SG.latest_run(c, profile, w["event_key"]))))
    shown = {e["slug"] for r in races for e in r["events"]}
    season = [e for e in events if e["slug"] not in shown and e["kind"] in
              ("champion", "constructors_champion", "season_wins_ge", "standings_h2h")]
    other = [e for e in events if e["slug"] not in shown and e not in season]
    synced = data.q(c, "SELECT max(synced_at) AS t FROM market_links WHERE exchange = 'polymarket'")["t"].iloc[0]
    return dict(races=races, season=season, other=other, synced=synced, n_markets=len(rows_), maker=maker)


@app.post("/book/markets/{market_id}/take", dependencies=[Depends(check_csrf)])
def place_bet(request: Request, market_id: int, side: str = Form(...), stake: float = Form(...),
              quoted: float = Form(...), user=allow("taker")):
    """Taker bets at the current quote. If the maker repriced since the page was
    loaded (quote changed), the bet is refused so the taker sees the new price."""
    race_id = None
    try:
        if side not in ("YES", "NO"):
            raise ValueError("side must be YES or NO")
        if not (0 < stake <= MAX_STAKE):
            raise ValueError(f"stake must be between $0 and ${MAX_STAKE:.0f}")
        with get_session() as s:
            mk = s.get(m.HouseMarket, market_id)
            if mk is None:
                raise ValueError("no such market")
            race_id = mk.race_id
            current = mk.yes_price if side == "YES" else mk.no_price
            if current is None or abs(current - quoted) > 1e-9:
                raise ValueError(f"the price moved (now {current}); check the new quote")
            b = house.record_bet(s, market_id, user["username"], side, stake, current, taker_id=user["id"])
        audit(request, "bet_place", market_id=market_id, side=side, stake=stake, price=b.price, bet_id=b.id,
              title=mk.title)
        msg = f"Bet placed: {side} ${stake:.2f} at {b.price:.2f} on \"{mk.title}\" (pays ${b.payout:.2f})."
    except ValueError as e:
        audit(request, "bet_rejected", market_id=market_id, side=side, stake=stake, reason=str(e))
        msg = f"Error: {e}"
    race_q = f"race_id={race_id}&" if race_id else ""
    return RedirectResponse(f"/markets?{race_q}msg={msg}", status_code=303)


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
    with get_session() as s:
        u = U.authenticate(s, username, password)
        user = _user_dict(u) if u else None
    if user is None:
        _record_failure(ip)
        U.log(get_engine(), None, "login_failed", request, username=username)
        return RedirectResponse(f"/login?next={next}&error=1", status_code=303)
    from racinglines.web import demo
    sid = demo.new_sid()                           # a fresh session: a demo account starts from its baseline
    U.log(get_engine(), user, "login", request, sid=sid, demo=demo.is_demo(user) or None)
    default = "/markets"
    target = next if next.startswith("/") and not next.startswith("//") and next != "/" else default
    resp = RedirectResponse(target, status_code=303)
    expires = int(time.time()) + SESSION_HOURS * 3600
    https = request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https"
    resp.set_cookie(SESSION_COOKIE, _session_value(user["id"], expires, sid), max_age=SESSION_HOURS * 3600,
                    httponly=True, samesite="lax", secure=https)
    return resp


@app.get("/logout")
def logout(request: Request):
    from racinglines.web import demo
    audit(request, "logout")
    sid = _session(request.cookies.get(SESSION_COOKIE))[1]
    if sid:
        demo.reset(sid)
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# Polymarket page (/pm, makers/admin): every listed event, our fair values, mirror into my book
# ---------------------------------------------------------------------------

@app.get("/markets/polymarket", response_class=HTMLResponse)
def pm_board(request: Request, event: str = "", show: str = "modeled", closed: int = 0, spread_pct: float = 4.0,
             msg: str = "", c=Depends(conn), user=allow("admin", "maker")):
    links = data.q(c, """
        SELECT ml.*, a.display_name AS athlete FROM market_links ml LEFT JOIN athletes a ON a.id = ml.athlete_id
        WHERE ml.exchange = 'polymarket' AND (CAST(:closed AS int) = 1 OR NOT ml.closed)
          AND (CAST(:ev AS text) IS NULL OR ml.event_slug = CAST(:ev AS text))
        ORDER BY ml.end_date NULLS LAST, ml.event_title, ml.last_price DESC NULLS LAST""", closed=closed, ev=event or None)
    mine = set(data.q(c, "SELECT market_link_id FROM house_markets WHERE maker_id = :u AND market_link_id IS NOT NULL",
                      u=user["id"])["market_link_id"].dropna().astype(int))
    from racinglines.markets import alerts
    fresh = alerts.new_links(c)
    cache, out = {}, []
    spread = spread_pct / 100
    for link in links.to_dict("records"):
        fair, _ = data.model_prob(c, link, cache)
        mid = link["last_price"] if link["last_price"] is not None and not pd.isna(link["last_price"]) else None
        tick = link["tick_size"] or 0.01
        link.update(fair=fair, edge=(fair - mid) if fair is not None and mid is not None else None,
                    q_bid=(math.floor(round((fair - spread / 2) / tick, 6)) * tick) if fair is not None else None,
                    q_ask=(math.ceil(round((fair + spread / 2) / tick, 6)) * tick) if fair is not None else None,
                    mirrored=int(link["id"]) in mine, new=link["token_id"] in fresh,
                    subject=link["athlete"] or (link["params"].get("team") if isinstance(link["params"], dict) else None)
                    or link["group_title"])
        if show == "modeled" and fair is None:
            continue
        out.append(link)
    events = []
    for slug, g in pd.DataFrame(out).groupby("event_slug", sort=False) if out else []:
        vol = g.drop_duplicates("market_slug")["volume"].fillna(0).sum()
        events.append(dict(slug=slug, title=g["event_title"].iloc[0], end_date=g["end_date"].iloc[0], volume=vol,
                           modeled=int(g["fair"].notna().sum()), new=int(g["new"].sum()), rows=rows(g.sort_values("last_price", ascending=False,
                                                                                         na_position="last"))))
    synced = data.q(c, "SELECT max(synced_at) AS t FROM market_links WHERE exchange = 'polymarket'")["t"].iloc[0]
    return render(request, "pm.html", events=events, show=show, closed=closed, spread_pct=spread_pct, msg=msg,
                  synced=synced, event=event)


@app.post("/markets/polymarket/mirror", dependencies=[Depends(check_csrf)])
def pm_mirror(request: Request, event_slug: str = Form(...), spread_pct: float = Form(4.0), c=Depends(conn),
              user=allow("admin", "maker")):
    with get_session() as s:
        created, repriced, skipped = house.mirror_event(s, c, event_slug, user["id"], spread_pct / 100)
    audit(request, "pm_mirror", event_slug=event_slug, spread=spread_pct / 100, created=created, repriced=repriced,
          skipped=skipped)
    msg = f"Mirrored into your book: {created} new, {repriced} repriced, {skipped} without a model price."
    return RedirectResponse(f"/markets/polymarket?spread_pct={spread_pct}&msg={msg}", status_code=303)


@app.post("/markets/polymarket/sync", dependencies=[Depends(check_csrf)])
def pm_sync(request: Request, c=Depends(conn), user=allow("admin", "maker")):
    from racinglines.markets import alerts
    with get_session() as s:
        stats, groups, _ = alerts.sync_and_alert(s, c, date.today().year)
    settled = []
    if user["role"] == "admin":
        with get_session() as s, get_engine().connect() as c2:
            settled = house.settle_from_exchange(s, c2)
    audit(request, "pm_sync", **stats, settled=settled)
    msg = (f"Synced {stats['events']} events / {stats['links']} outcomes ({stats['modeled']} priced by the model)."
           + (f" New: {', '.join(g['event_title'] for g in groups)}." if groups else "")
           + (f" Settled {len(settled)} mirrored markets from Polymarket." if settled else ""))
    return RedirectResponse(f"/markets/polymarket?msg={msg}", status_code=303)


# ---------------------------------------------------------------------------
# Single-event diagnostics (makers/admin): as-of prices vs Polymarket vs result
# ---------------------------------------------------------------------------

from racinglines.web import diag  # noqa: E402


@app.get("/lab/diagnostics/{run_id}", response_class=HTMLResponse, dependencies=[allow("admin", "maker")])
def diag_page(request: Request, run_id: int, msg: str = "", fill: str = "through", h: float = 0.02, size: float = 50,
              max_pos: float = 250, cap: float = 1000, skew: float = 1.0, disagree: float = 0.15, min_vol: float = 100,
              pull: int = 15, c=Depends(conn)):
    d = diag.load(c, run_id)
    if d is None:
        raise HTTPException(404)
    fill = fill if fill in ("touch", "through") else "through"
    mk = d["markets"]
    groups = [(k, rows(g.sort_values("fair", ascending=False, na_position="last")))
              for k, g in mk.groupby("kind", sort=False)] if len(mk) else []
    paper = mk[mk["paper_side"].notna()] if len(mk) and "paper_side" in mk else pd.DataFrame()
    knobs = dict(fill=fill, half_spread=min(max(h, 0.005), 0.2), size=min(max(size, 1), 5000),
                 max_pos=min(max(max_pos, 1), 50000), max_capital=min(max(cap, 10), 1e6), skew=min(max(skew, 0), 5),
                 max_disagree=None if disagree <= 0 else min(disagree, 1), min_volume_24h=max(min_vol, 0),
                 pull_min=min(max(pull, 0), 240))
    rp = diag.replay(c, run_id, **knobs)
    f = rp["fills"]
    top = f.reindex(f["pnl"].abs().sort_values(ascending=False).index).head(15) if len(f) else f
    bets = d["bets"]
    summary = dict(
        paper_n=len(paper), paper_staked=len(paper) * diag.PAPER_STAKE,
        paper_pnl=float(paper["paper_pnl"].fillna(0).sum()) if len(paper) else 0.0,
        taker_n=len(bets), taker_staked=float(bets["stake"].sum()) if len(bets) else 0.0,
        taker_pnl=float(bets["taker_pnl"].sum()) if len(bets) else 0.0)
    return render(request, "diag.html", d=d, groups=groups, scores=rows(d["scores"]), result=rows(d["result"]),
                  bets=rows(bets), paper=rows(paper), summary=summary, msg=msg,
                  coherence=d.get("coherence", {}), rp=rp, rp_stages=rows(rp["stages"]), rp_summary=rows(rp["summary"]),
                  rp_skips=rows(rp["skips"]), rp_sweep=rows(rp["sweep"]), rp_top=rows(top),
                  rp_positions=rows(rp["positions"]), fill=fill, h=h, runs=rows(diag.event_runs(c, run_id)),
                  consts=dict(paper_edge=diag.PAPER_EDGE, paper_stake=diag.PAPER_STAKE))


@app.post("/lab/diagnostics/{run_id}/example", dependencies=[Depends(check_csrf)])
def diag_example(request: Request, run_id: int, fill: str = Form("through"), c=Depends(conn),
                 user=allow("admin", "maker")):
    """Replay fills become bets by the Polymarket-takers system account (not the demo taker) on the demo
    'maker' account's markets."""
    with get_session() as s:
        maker, taker = U.get_user(s, username="maker"), U.ensure_replay_taker(s)
        if maker is None:
            raise HTTPException(400, "needs the demo 'maker' account")
        out = diag.create_example(s, c, run_id, maker.id, _user_dict(taker), fill=fill)
    audit(request, "diag_example", run_id=run_id, **out)
    return RedirectResponse(f"/lab/diagnostics/{run_id}?msg=Recorded {out['bets']} fills as Polymarket-taker bets on {out['markets']} markets",
                            status_code=303)


from racinglines.web import admin  # noqa: E402,F401  (registers /admin routes)
from racinglines.web import views  # noqa: E402,F401  (registers the board, race, season, book and lab pages)
from racinglines.web import legacy  # noqa: E402,F401  (old page URLs redirect to the current routes; register last)
