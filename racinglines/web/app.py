"""
racinglines web app (FastAPI, server-rendered).

Three roles (see roles.py): admin, pro, basic (`maker` / `taker` rows read as pro / basic). Every route needs
a signed-in user (session cookie from /login, or HTTP Basic) and declares which roles may use it (allow(*PRO)
for the maker tools and the Lab); every form POST carries a CSRF token; every meaningful action is
written to activity_log. Run with `racinglines web`.
"""

from types import SimpleNamespace
import contextvars
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from urllib.parse import quote
from datetime import date, datetime, timezone
from numbers import Real
from pathlib import Path

logger = logging.getLogger(__name__)

import pandas as pd
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[2]      # the repository

from racinglines.db import models as m  # noqa: E402
from racinglines.db.config import get_engine, get_session  # noqa: E402

from racinglines.db import reads as data  # noqa: E402
from racinglines import exchanges, sports  # noqa: E402
from racinglines.markets.polymarket import trade as polymarket

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Auth (users table, roles) + CSRF
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager  # noqa: E402

from racinglines.web import users as U  # noqa: E402
from racinglines.web import roles as R  # noqa: E402

_SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(32)
CSRF_TOKEN = hmac.new(_SECRET.encode(), b"csrf", hashlib.sha256).hexdigest()

security = HTTPBasic(realm="racinglines", auto_error=False)
SESSION_COOKIE = "rl_session"
SESSION_HOURS = 12
PUBLIC_PATHS = ("/login", "/static", "/racinglines101", "/signup", "/forgot", "/pitch")

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
    return dict(id=u.id, username=u.username, role=R.canonical(u.role), display_name=u.display_name or u.username)


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
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": "/login?next=" + quote(
                                request.url.path + (f"?{request.url.query}" if request.url.query else ""), safe="/")})
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                        headers={"WWW-Authenticate": 'Basic realm="racinglines"'})


def allow(*roles):
    """Route dependency: only these roles may use the route. Returns the user dict."""
    def dep(request: Request):
        u = getattr(request.state, "user", None)
        if not u or R.canonical(u["role"]) not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This page is only for: {', '.join(roles)}.")
        return u
    return Depends(dep)


ANY, PRO = R.ANY, R.PRO


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
app.mount("/media", StaticFiles(directory=HERE / "media"), name="media")
templates = Jinja2Templates(directory=HERE / "templates")


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

MONEY_COLS = {"pnl", "spread_pnl", "markout_60m", "markout_5m", "model_edge", "worst_case", "cash", "taker_pnl",
              "staked", "stake", "payout", "ev", "pnl_if_yes", "pnl_if_no", "cost", "proceeds", "notional", "settled_pnl",
              "paper_pnl", "replay_pnl", "kalshi_pnl", "worst"}
SIGNED_MONEY_COLS = {"pnl", "spread_pnl", "markout_60m", "markout_5m", "model_edge", "taker_pnl", "pnl_if_yes",
                     "pnl_if_no", "ev", "settled_pnl", "paper_pnl", "replay_pnl", "kalshi_pnl"}   # P&L-like: shown with a sign


def money(v, sign=False, cents=True):
    """-302.97 -> '-$302.97'; sign=True adds '+' to positives; cents=False keeps whole dollars ('-$303')."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    s = "-" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{s}${abs(v):,.{2 if cents else 0}f}"


def _when(value):
    """One date format: 'YYYY-MM-DD HH:MM UTC', or 'YYYY-MM-DD' when there is no time part (tz-aware values go to UTC)."""
    if isinstance(value, pd.Timestamp) and pd.isna(value):
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%d %H:%M UTC") if (value.hour or value.minute) else value.strftime("%Y-%m-%d")
    return value.strftime("%Y-%m-%d")                                     # a plain date


def fmt(value, col=""):
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT:
        return ""
    if isinstance(value, (datetime, date)):                                # pd.Timestamp is a datetime
        return _when(value)
    if col in MONEY_COLS and isinstance(value, Real) and not isinstance(value, bool):
        return money(value, sign=col in SIGNED_MONEY_COLS)
    if isinstance(value, float):
        if col.endswith("_prob") or col in ("model_prob", "edge", "quoted_share"):
            return f"{value:.1%}"
        if col.endswith("time_s"):
            mins, secs = divmod(value, 60)
            return f"{int(mins)}:{secs:06.3f}" if mins else f"{secs:.3f}"
        if value.is_integer() and abs(value) < 1e6:
            return f"{int(value)}"
        return f"{value:.3f}" if abs(value) < 10 else f"{value:.1f}"
    return str(value)


templates.env.filters["fmt"] = fmt
templates.env.filters["money"] = money


def kind(k):
    """'race_win' -> 'win', 'race_top10' -> 'top10', 'race_make_final' -> 'make final'."""
    if k is None:
        return ""
    k = str(k).removeprefix("race_")
    return ("DH " + k.removeprefix("dh_") if k.startswith("dh_") else k).replace("_", " ")


templates.env.filters["kind"] = kind


def when(v):
    """fmt for an ISO string ('2026-09-27T14:05:00'; no zone means UTC)."""
    if not v:
        return ""
    t = pd.Timestamp(v)
    return fmt(t.tz_localize("UTC") if t.tzinfo is None else t)


templates.env.filters["when"] = when
# Short column headers for the `table` macro; a key not listed gets `_` -> space and a capital first letter.
LABELS = {"markets_made": "Markets made", "bets_against": "Bets against", "bets_placed": "Bets placed", "staked": "Staked",
          "last_seen": "Last seen", "created_at": "Created", "pnl": "P&L", "pnl_if_yes": "P&L if yes", "pnl_if_no": "P&L if no",
          "ev": "EV", "id": "ID", "fair_prob": "Fair", "yes_price": "Yes", "no_price": "No",
          "win_prob": "Win", "podium_prob": "Podium", "top10_prob": "Top 10", "make_final_prob": "Makes final",
          "exp_points": "Exp. points", "actual_final_pos": "Final pos.", "time_s": "Time", "start_date": "Date",
          "series_round": "Round", "source_key": "Source", "last_race": "Last race", "brier_model": "Brier (model)",
          "brier_polymarket": "Brier (Polymarket)", "logloss_model": "Log loss (model)",
          "logloss_polymarket": "Log loss (Polymarket)", "run_id": "Run", "spread_pnl": "Spread P&L",
          "markout_60m": "Markout 60m", "model_edge": "Model edge", "worst_case": "Worst case", "quoted_share": "Quoted",
          "half_spread": "Half spread", "max_disagree": "Max disagree", "market_steps": "Market steps",
          "taker_pnl": "Taker P&L", "model_prob": "Model prob", "best_bid": "Best bid", "best_ask": "Best ask",
          "exchange_order_id": "Exchange order", "ts": "Time", "qty": "Qty", "mid": "Mid", "fair": "Fair"}
templates.env.globals["LABELS"] = LABELS
# Demo-only explanations (the demo accounts' story, the demo itself) render in `demo_context` bubbles
# (_macros.html) tagged data-tag="demo-context". RACINGLINES_DEMO_CONTEXT=0 hides them all; for real users,
# delete every `demo_context` call.
DEMO_CONTEXT = {"on": os.environ.get("RACINGLINES_DEMO_CONTEXT", "1") != "0"}
_RENDER_USER = contextvars.ContextVar("render_user", default=None)   # set by render(): imported macros don't see the page's `user`
templates.env.globals["demo_context_on"] = lambda: DEMO_CONTEXT["on"] and _demo.is_demo(_RENDER_USER.get())   # read at render time; demo accounts only
templates.env.globals["csrf_token"] = CSRF_TOKEN
# RACINGLINES_ENV=staging (set only in /etc/racinglines-staging.env on the VM): every response carries
# X-Racinglines-Env so a deploy's smoke check can tell the staging instance from production, and the top bar shows
# the label. Unset (production, local): no header, no label, nothing changes.
ENV_LABEL = os.environ.get("RACINGLINES_ENV", "").strip()
templates.env.globals["env_label"] = lambda: ENV_LABEL
if ENV_LABEL:
    @app.middleware("http")
    async def _env_header(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Racinglines-Env"] = ENV_LABEL
        return response
# Maintenance popup on the sign-in page and every app page, dismissed with "ok" once per browser session
# (_site_notice.html). Set to "" to turn it off.
MAINTENANCE_NOTICE = "We are working on things! You may experience downtime or dead links until we finish."
templates.env.globals["maintenance_notice"] = lambda: MAINTENANCE_NOTICE   # read at render time
templates.env.globals["signup_on"] = lambda: signup_on()                    # RACINGLINES_SIGNUP=1: beta sign-up
templates.env.globals["is_demo"] = lambda u: _demo.is_demo(u)
# the stylesheet's and scripts' URLs carry the newest static file's mtime, so a change is a new URL: no stale copy from the browser or
# Cloudflare's edge cache (read at render time)
templates.env.globals["css_v"] = lambda: int(max(p.stat().st_mtime for p in (HERE / "static").glob("*.*")))


def _seen_since(user):
    """A demo session's "signals seen up to" time (web/demo.py overlay), else None (the database's seen_at)."""
    from racinglines.web import demo
    return demo.prefs(user["sid"]).get("signals_seen_at") if demo.is_demo(user) and user.get("sid") else None


def _signals_nav(user):
    """The Signals link for the nav (users with a strategy profile, and admins): unread signals, and the
    account's paper summary (profile, bankroll, P&L) for the banner on the home and trading pages."""
    if not user:
        return None
    from racinglines.pipelines import sport_paper as SP        # RACINGLINES_SPORT_PAPER=1: NASCAR / MotoGP demo rows count
    try:
        with get_engine().connect() as c:
            r = c.execute(text("""SELECT prefs ? 'strategy_profile', prefs->'strategy_profile'->>'name',
                                         (prefs->'strategy_profile'->'bankroll'->>'start')::float,
                                         (SELECT count(*) FROM strategy_signals WHERE user_id = :u AND seen_at IS NULL
                                            AND status <> 'expired'
                                            AND (CAST(:since AS timestamptz) IS NULL OR created_at > CAST(:since AS timestamptz))),
                                         (SELECT sum(cash + yes_shares * coalesce(outcome::int, mark)
                                                 + no_shares * (1 - coalesce(outcome::int, mark)))
                                            FROM paper_positions WHERE user_id = :u AND (venue = 'polymarket'
                                                 OR (:sp AND event_key IN (""" + SP.SPORT_KEYS + """)))),
                                         (SELECT sum(cash + yes_shares * coalesce(outcome::int, mark)
                                                 + no_shares * (1 - coalesce(outcome::int, mark)))
                                            FROM paper_positions WHERE user_id = :u AND venue = 'private')
                                  FROM users WHERE id = :u"""),
                          dict(u=user["id"], since=_seen_since(user), sp=SP.enabled())).first()
    except Exception:                                   # noqa: BLE001  the nav never breaks a page
        return None
    if r is None or not (r[0] or user["role"] == "admin"):
        return None
    pnl = float(r[4] or 0.0)
    return dict(unread=int(r[3] or 0), profile=r[1], start=r[2], pnl=pnl, private=None if r[5] is None else float(r[5]),
                balance=(r[2] + pnl) if r[2] else None, ret=(pnl / r[2]) if r[2] else None)


def render(request, name, **ctx):
    ctx.setdefault("trading", polymarket.TradingConfig.from_env())
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx.setdefault("signals_nav", _signals_nav(ctx["user"]))
    ctx.setdefault("schema_exchanges", V.SCHEMA_EXCHANGES)      # venues defined as schemas whose switch is on (none by default)
    ctx.setdefault("tapes", V.TAPES)                            # RACINGLINES_TAPES=1: the tape-only sports' market data
    try:                                               # a live event (pipelines/live.py): the Live tab, green while
        from racinglines.pipelines.live import state      # it runs, grey once it is over (a replay)
        ctx.setdefault("live_nav", state() if ctx["user"] else None)
    except Exception:                                  # noqa: BLE001
        ctx.setdefault("live_nav", False)
    from racinglines.web import demo
    u = ctx["user"]
    _RENDER_USER.set(u)
    ctx.setdefault("storage_ns", f"demo.{u.get('sid')}." if demo.is_demo(u) and u.get("sid") else "")
    return templates.TemplateResponse(request, name, ctx)


# Browser requests (Accept: text/html) get a readable error page for 403 / 404 / 422 / 429; JSON and API clients keep
# FastAPI's JSON error. A throttled sign-in goes back to the form with a sentence instead.
ERROR_TEXT = {403: "You don't have access to this page.", 404: "That page doesn't exist, or it has moved.",
              422: "Something in that link or form wasn't valid.", 429: "Too many attempts. Wait a few minutes and try again."}


def _wants_html(request):
    return "text/html" in request.headers.get("accept", "") and not request.url.path.startswith("/api/")


def _error_page(request, code):
    user = getattr(request.state, "user", None)
    try:
        resp = render(request, "error.html", code=code, message=ERROR_TEXT[code], home="/markets" if user else "/login")
        resp.status_code = code
        return resp
    except Exception:                                  # noqa: BLE001  never let the error page itself fail
        return None


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 429 and request.method == "POST" and request.url.path == "/login" and _wants_html(request):
        return RedirectResponse("/login?error=throttled", status_code=303)
    if exc.status_code in ERROR_TEXT and _wants_html(request):
        resp = _error_page(request, exc.status_code)
        if resp is not None:
            return resp
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    if _wants_html(request):
        resp = _error_page(request, 422)
        if resp is not None:
            return resp
    return await request_validation_exception_handler(request, exc)


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


@app.get("/lab/runs/{run_id}", response_class=HTMLResponse, dependencies=[allow(*PRO)])
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


@app.get("/events/by-key/{source_key}")
def event_by_key(source_key: str, c=Depends(conn)):
    """Stable link to an event by its source key (e.g. ChronoRace 20260925_mtb)."""
    ev = data.q(c, "SELECT id FROM events WHERE source_key = :k ORDER BY id DESC LIMIT 1", k=source_key)
    if not len(ev):
        raise HTTPException(404, f"no event {source_key}")
    return RedirectResponse(f"/events/{int(ev['id'].iloc[0])}", status_code=303)


@app.get("/racinglines101", response_class=HTMLResponse)
def racinglines101(request: Request):
    """Plain-language intro to makers, takers (the pro and basic tiers) and the paper-trading demo (public, linked from the login page)."""
    return render(request, "racinglines101.html")


@app.get("/pitch", response_class=HTMLResponse)
def pitch():
    """The pitch deck (pitch.html at the repo root), public like /login and /signup."""
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
    if R.is_basic(request.state.user):
        pred_groups = []  # model fair values are the makers' edge
    return render(request, "event.html", ev=ev, groups=groups, pred_groups=pred_groups)


@app.get("/athletes/{athlete_id}", response_class=HTMLResponse)
def athlete_detail(request: Request, athlete_id: int, c=Depends(conn)):
    a = data.athlete(c, athlete_id)
    if not a:
        raise HTTPException(404)
    preds = [] if R.is_basic(request.state.user) else rows(data.athlete_predictions(c, athlete_id))
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
# Private book: markets quoted by pro accounts (admin = house), bets placed by basic accounts
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
               user=allow(*PRO)):
    races = _races_for_house(c)
    if race_id is None and races:
        race_id = races[0]["race_id"]
    if user["role"] == "pro":
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
    makers = rows(data.q(c, "SELECT username FROM users WHERE role IN ('pro', 'maker', 'admin') ORDER BY username"))
    return render(request, "house.html", races=races, race_id=race_id, groups=groups, totals=totals, msg=msg,
                  kinds=list(house.KINDS) + ["race_top10"], makers=makers, maker=maker)


@app.post("/book/quotes/generate", dependencies=[Depends(check_csrf)])
async def house_generate(request: Request, c=Depends(conn), user=allow(*PRO)):
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
                  now=pd.Timestamp.now(tz="America/Vancouver").strftime("%a %d %b %H:%M"))


@app.get("/book/markets/{market_id}", response_class=HTMLResponse)
def house_market(request: Request, market_id: int, msg: str = "", c=Depends(conn), user=allow(*PRO)):
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
                user=allow(*PRO)):
    _own_market(user, market_id)
    with get_session() as s:
        house.set_price(s, market_id, fair_pct / 100, spread_pct / 100)
    audit(request, "market_price", market_id=market_id, fair=fair_pct / 100, spread=spread_pct / 100)
    return RedirectResponse(f"/book/markets/{market_id}?msg=Repriced (manual fair value).", status_code=303)


@app.post("/book/markets/{market_id}/status", dependencies=[Depends(check_csrf)])
def house_status(request: Request, market_id: int, status_: str = Form(..., alias="status"),
                 user=allow(*PRO)):
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
    view = R.basic_view_profile(profile) if R.is_basic(user) else profile       # basic: "Your picks", no strategy name
    from racinglines.web import sport_status as SS                  # RACINGLINES_SPORT_STATUS=1: every sport's status
    return render(request, "bet.html", msg=msg, profile=view, **polymarket_calls(c, profile),
                  sport_status=SS.status(c) if SS.enabled() else None, show_paper=False)


def polymarket_calls(c, profile, n_races=3, exchange="polymarket"):
    """Every open Polymarket F1 market (or Kalshi's, `exchange="kalshi"`) with `profile`'s current call: a taker's
    side / size / limit / heat (signals.call) or a maker's quotes (signals.maker_call). -> dict(races (the next n,
    listed or not), season, other, synced, n_markets). Never exposes fair values."""
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
        WHERE ml.exchange = :x AND NOT ml.closed
        ORDER BY ml.end_date NULLS LAST, ml.event_title, ml.last_price DESC NULLS LAST""", x=exchange)
    now = pd.Timestamp.now(tz="UTC")
    vol = {}
    # 24 h volume per market: by condition on Polymarket; on Kalshi a condition is the whole event, so by ticker
    vkey = "token_id" if exchange == "kalshi" else "condition_id"
    if len(links):
        tr = MS.read(c, "trades", **{"tokens" if exchange == "kalshi" else "conditions": links[vkey].dropna().unique().tolist()},
                     start=now - _td(hours=24), end=now, root=MS.root_for(exchange))
        if len(tr):
            vol = (tr["price"] * tr["size"]).groupby(tr[vkey]).sum().to_dict()
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
        v24 = vol.get(link[vkey], 0.0) if kind.startswith("race_") else None
        cl = call(profile, kind, fair, mid, v24) if profile else dict(action=None, why="")
        subject = link["athlete"] or (link["params"].get("team") if isinstance(link["params"], dict) else None) \
            or link["group_title"] or link["outcome"]
        if kind == "race_h2h":
            subject = f"{link['outcome']} ({link['question'].split(': ')[-1]})"
        rows_.append(dict(link, subject=subject, mid=mid, call=cl, volume_24h=vol.get(link[vkey], 0.0),
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
    synced = data.q(c, "SELECT max(synced_at) AS t FROM market_links WHERE exchange = :x", x=exchange)["t"].iloc[0]
    from racinglines.web import board as B
    recorders = B.recorder_status(c, [exchange]) if exchange != "polymarket" else None    # the Kalshi / schema recorders
    return dict(races=races, season=season, other=other, synced=synced, n_markets=len(rows_), maker=maker, exchange=exchange)


@app.post("/book/markets/{market_id}/take", dependencies=[Depends(check_csrf)])
def place_bet(request: Request, market_id: int, side: str = Form(...), stake: float = Form(...),
              quoted: float = Form(...), user=allow(*R.BASIC)):
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
    dest = f"/races/{race_id}" if race_id and not R.is_basic(user) else "/markets"
    return RedirectResponse(f"{dest}?msg={msg}", status_code=303)


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = ""):
    return templates.TemplateResponse(request, "login.html", dict(next=next, error=error))


def _safe_next(nxt):
    """The post-login target: a same-site relative path only (one leading slash, no scheme, host, backslash or
    control characters), else /markets."""
    if (not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt or any(ord(ch) < 32 or ord(ch) == 127 for ch in nxt)):
        return "/markets"
    return nxt


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
        return RedirectResponse(f"/login?next={quote(_safe_next(next), safe='/')}&error=1", status_code=303)
    target = _safe_next(next) if next != "/" else "/markets"
    return _start_session(request, user, target)


def _start_session(request, user, target):
    """Sign `user` in: a fresh session cookie, logged, then a redirect to `target`."""
    from racinglines.web import demo
    sid = demo.new_sid()                           # a fresh session: a demo account starts from its baseline
    U.log(get_engine(), user, "login", request, sid=sid, demo=demo.is_demo(user) or None)
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
# User settings: email, exchange preferences, sports subscriptions
# ---------------------------------------------------------------------------

def _prefs(user_id):
    with get_session() as s:
        return dict(s.query(m.User).filter_by(id=user_id).first().prefs or {})


def _mcp_context(user):
    from racinglines.mcp import auth as mcp_auth, oauth
    prefs = _prefs(user["id"])
    return dict(mcp_url=oauth.MCP_URL, mcp_issued_at=(prefs.get("mcp") or {}).get("issued_at"),
                mcp_clients=(prefs.get("mcp_oauth") or {}).get("clients") or {},
                mcp_allowed=user["role"] in mcp_auth.ROLES, mcp_roles=", ".join(mcp_auth.ROLES))


@app.get("/settings", response_class=HTMLResponse, dependencies=[allow(*ANY)])
def settings_page(request: Request):
    """User settings: email, exchange preferences, sports subscriptions, MCP token. Demo users cannot access."""
    user = request.state.user
    if _demo.is_demo(user):
        raise HTTPException(404)
    prefs = _prefs(user["id"])
    return templates.TemplateResponse(request, "settings.html", dict(
        email=prefs.get("email", ""),
        exchange=prefs.get("exchange", "polymarket"),
        sports=prefs.get("sports", ["f1"]),
        **_mcp_context(user),
    ))


@app.post("/settings", dependencies=[Depends(check_csrf), allow(*ANY)])
def update_settings(request: Request, email: str = Form(""), exchange: str = Form("polymarket"),
                   sports: list[str] = Form(None)):
    """Update user settings: email, exchange preferences, sports subscriptions."""
    user = request.state.user
    if _demo.is_demo(user):
        raise HTTPException(404)
    sports = sports or []
    email = email.strip()
    if email and not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        return templates.TemplateResponse(request, "settings.html", dict(
            email=email, exchange=exchange, sports=sports, error="Invalid email address", **_mcp_context(user),
        ), status_code=400)
    with get_session() as s:     # merge: the session user carries no prefs, and prefs also hold the MCP token and seen-at marks
        u = s.query(m.User).filter_by(id=user["id"]).first()
        u.prefs = {**(u.prefs or {}), "email": email, "exchange": exchange, "sports": sports or ["f1"]}
        s.commit()
    audit(request, "update_settings", email=bool(email), exchange=exchange, sports=sports)
    return templates.TemplateResponse(request, "settings.html", dict(
        email=email, exchange=exchange, sports=sports, success="Settings saved", **_mcp_context(user),
    ))


# ---------------------------------------------------------------------------
# MCP token from the Settings page: the same token `racinglines mcp token <account>` issues (racinglines/mcp/auth.py),
# one per account, shown once; the hosted MCP server accepts it at once.
# ---------------------------------------------------------------------------

@app.post("/api/settings/token/generate", dependencies=[Depends(check_csrf), allow(*ANY)])
def generate_mcp_token(request: Request):
    from racinglines.mcp import auth as mcp_auth
    user = request.state.user
    if _demo.is_demo(user):
        raise HTTPException(403, "Demo accounts cannot get an MCP token")
    try:
        token = mcp_auth.new_token(get_engine(), user["username"])
    except ValueError as ex:
        raise HTTPException(403, str(ex)) from ex
    audit(request, "generate_mcp_token")
    from racinglines.mcp import oauth
    return {"token": token, "url": oauth.MCP_URL}


@app.post("/api/settings/token/revoke", dependencies=[Depends(check_csrf), allow(*ANY)])
def revoke_mcp_token(request: Request):
    from racinglines.mcp import auth as mcp_auth
    user = request.state.user
    if _demo.is_demo(user):
        raise HTTPException(403, "Demo accounts have no MCP token")
    if not mcp_auth.revoke(get_engine(), user["username"]):
        raise HTTPException(404, "No MCP token to revoke")
    audit(request, "revoke_mcp_token")
    return {"status": "revoked"}


@app.post("/api/settings/mcp/disconnect", dependencies=[Depends(check_csrf), allow(*ANY)])
def disconnect_mcp(request: Request):
    from racinglines.mcp import oauth
    user = request.state.user
    if _demo.is_demo(user):
        raise HTTPException(403, "Demo accounts have no MCP sign-ins")
    oauth.disconnect(get_engine(), user["id"])
    audit(request, "mcp_disconnect")
    return {"status": "disconnected"}


# ---------------------------------------------------------------------------
# MCP sign-in (racinglines/mcp/oauth.py): the MCP server's /authorize sends the browser here with a signed request;
# a signed-in account allowed MCP access presses Allow and goes back to the client with a code.
# ---------------------------------------------------------------------------

@app.get("/mcp/authorize", response_class=HTMLResponse, dependencies=[allow(*ANY)])
def mcp_authorize_page(request: Request, req: str = ""):
    from racinglines.mcp import oauth
    user = request.state.user
    info = oauth.request_info(req)
    allowed = not _demo.is_demo(user) and oauth.account(get_engine(), user_id=user["id"]) is not None
    resp = render(request, "mcp_authorize.html", req=req, info=info, allowed=allowed, roles=", ".join(oauth.auth.ROLES))
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"                       # an Allow button must not be clickable inside another site
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    return resp


@app.post("/mcp/authorize", dependencies=[Depends(check_csrf), allow(*ANY)])
def mcp_authorize(request: Request, req: str = Form(...), decision: str = Form(...)):
    from racinglines.mcp import oauth
    user = request.state.user
    if decision != "allow":
        url = oauth.deny_url(req)
    elif _demo.is_demo(user) or oauth.account(get_engine(), user_id=user["id"]) is None:
        raise HTTPException(403, "This account may not use the MCP server")
    else:
        url = oauth.approve(req, user)
        audit(request, "mcp_authorize", client=(oauth.request_info(req) or {}).get("client"))
    if url is None:
        raise HTTPException(400, "This sign-in request expired: start again from your MCP client")
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------------------
# Beta sign-up (/signup, RACINGLINES_SIGNUP=1, off by default; web/accounts.py): username and password, as pro. One
# transaction creates the account (scrypt hash) and its 1,000 fantasy-bucks grant, then signs the person in.
# Until `racinglines users setup` has made the ledger, the page says sign-up isn't open yet.
# ---------------------------------------------------------------------------

SIGNUP_ROLE = "pro"                         # every beta sign-up starts as pro (owner, 2026-10-01); tiers later
SIGNUP_MAX_PER_IP = 10                      # sign-up attempts per client IP per hour (successful or not)
_signup_hits: dict[str, list[float]] = {}


def signup_on() -> bool:
    return os.environ.get("RACINGLINES_SIGNUP", "0") == "1"


def _signup_ready() -> bool:
    from racinglines.web import accounts as ACC
    try:
        with get_engine().connect() as c:
            return bool(ACC.ready(c))
    except Exception:                               # noqa: BLE001  no database: fail soft, sign-up closed
        return False


def _signup_page(request, form=None, error="", status_code=200):
    from racinglines.web import accounts as ACC
    return templates.TemplateResponse(request, "signup.html", dict(form=form or {}, error=error,
                                      ready=_signup_ready(), grant=ACC.SIGNUP_GRANT,
                                      pw_min=ACC.PASSWORD_MIN), status_code=status_code)


SUPPORT_EMAIL = "hello@racinglines.bet"      # password resets are requested here; we store no user emails


@app.get("/forgot", response_class=HTMLResponse)
def forgot_password(request: Request):
    """Forgot your password: we hold no email address, so the page writes a reset request to SUPPORT_EMAIL for the
    person to send; an admin resets it at /admin/users and replies with a one-time password."""
    if not signup_on():
        raise HTTPException(404)
    return templates.TemplateResponse(request, "forgot.html", dict(support=SUPPORT_EMAIL))


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if not signup_on():
        raise HTTPException(404)
    return _signup_page(request)


@app.post("/signup", response_class=HTMLResponse)
def signup(request: Request, username: str = Form(""), password: str = Form(""), confirm: str = Form(""),
           adult: str = Form(""), website: str = Form("")):
    from racinglines.web import accounts as ACC
    if not signup_on():
        raise HTTPException(404)
    if website:                                     # honeypot: people never see this field, bots fill it
        raise HTTPException(400)
    ip = client_ip(request)
    now = time.time()
    hits = [t for t in _signup_hits.get(ip, []) if now - t < 3600]
    if len(hits) >= SIGNUP_MAX_PER_IP:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many sign-up attempts; try again in an hour")
    _signup_hits[ip] = hits + [now]
    if not _signup_ready():
        return _signup_page(request, status_code=503)
    username = username.strip().lower()
    tier = SIGNUP_ROLE
    form = dict(username=username[:30])
    with get_engine().begin() as c:
        error = (ACC.check_username(c, username) or ACC.check_password(password, confirm, username)
                 or ("Please confirm you're 18 or older." if not adult else ""))
        if error:
            return _signup_page(request, form, error, status_code=400)
        uid = c.execute(text("""INSERT INTO users (username, display_name, role, password_hash, active)
                                VALUES (:u, :u, :r, :h, true) RETURNING id"""),
                        dict(u=username, r=tier, h=U.hash_password(password))).scalar()
        ACC.grant(c, uid)
    # One taker strategy per new account, round-robin over PF.TAKER_TOP by user id, so the paper records cover every
    # strategy evenly and each account's record maps to exactly one (strategy diversity, owner 2026-10-06; replaces
    # "start on A", 2026-10-01). No bankroll, no history, so Strategy and Positions start empty. A failure here
    # leaves the account fine, just unassigned (an admin can assign one).
    try:
        from racinglines.pipelines import profiles as PF
        with get_engine().begin() as c:
            cands = PF.ensure_candidates(c)
            code = PF.TAKER_TOP[uid % len(PF.TAKER_TOP)]
            PF.assign(c, uid, PF.load(c, cands[code]))
    except Exception as ex:                         # noqa: BLE001
        print(f"signup: no starting profile for user {uid}: {ex}", flush=True)
    with get_session() as s:
        user = _user_dict(U.get_user(s, user_id=uid))
    U.log(get_engine(), user, "signup", request, grant=ACC.SIGNUP_GRANT)
    return _start_session(request, user, "/markets")


# ---------------------------------------------------------------------------
# Polymarket page (/pm, makers/admin): every listed event, our fair values, mirror into my book
# ---------------------------------------------------------------------------

@app.get("/markets/polymarket", response_class=HTMLResponse)
def pm_board(request: Request, event: str = "", show: str = "modeled", closed: int = 0, spread_pct: float = 4.0,
             msg: str = "", sport: str = "", c=Depends(conn), user=allow(*PRO)):
    return _exchange_board(request, c, user, "polymarket", event, show, closed, spread_pct, msg, sport)


def _exchange_board(request, c, user, exchange, event, show, closed, spread_pct, msg, sport=""):
    """Every listed event of one exchange (market_links.exchange), our fair values and a quote at ± spread/2.
    `sport`: a competition code (market_links.competition_id, exact match, no text/fuzzy matching) to narrow the
    list to one sport, e.g. from a Markets page "N new" link."""
    links = data.q(c, """
        SELECT ml.*, a.display_name AS athlete FROM market_links ml LEFT JOIN athletes a ON a.id = ml.athlete_id
        LEFT JOIN competitions co ON co.id = ml.competition_id
        WHERE ml.exchange = :x AND (CAST(:closed AS int) = 1 OR NOT ml.closed)
          AND (CAST(:ev AS text) IS NULL OR ml.event_slug = CAST(:ev AS text))
          AND (CAST(:sport AS text) IS NULL OR co.code = CAST(:sport AS text))
        ORDER BY ml.end_date NULLS LAST, ml.event_title, ml.last_price DESC NULLS LAST""", closed=closed, ev=event or None,
                   sport=sport or None, x=exchange)
    mine = set(data.q(c, "SELECT market_link_id FROM house_markets WHERE maker_id = :u AND market_link_id IS NOT NULL",
                      u=user["id"])["market_link_id"].dropna().astype(int))
    from racinglines.markets import alerts
    fresh = alerts.new_links(c)
    cache, out = {}, []
    spread = spread_pct / 100
    schema = exchange in exchanges.CODES                  # a schema venue: the edge is net of its taker fee, per side
    fee = V.schema_fee(exchange) if schema else 0.0
    for link in links.to_dict("records"):
        fair, _ = data.model_prob(c, link, cache)
        mid = link["last_price"] if link["last_price"] is not None and not pd.isna(link["last_price"]) else None
        tick = link["tick_size"] or 0.01
        if schema:
            bid = None if link["last_bid"] is None or pd.isna(link["last_bid"]) else float(link["last_bid"])
            ask = None if link["last_ask"] is None or pd.isna(link["last_ask"]) else float(link["last_ask"])
            link.update(V.net_edge(fee, fair, bid, ask) if fair is not None else dict(edge_yes=None, edge_no=None, best=None, call=""))
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
    synced = data.q(c, "SELECT max(synced_at) AS t FROM market_links WHERE exchange = :x", x=exchange)["t"].iloc[0]
    from racinglines.web import board as B
    recorders = B.recorder_status(c, [exchange]) if exchange != "polymarket" else None    # the Kalshi / schema recorders
    ctx = dict(events=events, show=show, closed=closed, spread_pct=spread_pct, msg=msg, synced=synced, event=event,
               sport=sport, sport_name=V.SPORT_NAME.get(sport, sport) if sport else "", recorders=recorders)
    if schema:
        venue = next(v for v in V.SCHEMA_EXCHANGES if v.code == exchange)
        return render(request, "exchange.html", mode="schema", venue=venue, fee=fee, **ctx,
                      sports=[V.SPORT_NAME.get(sports.load(x)["competition"]["code"], x) for x in exchanges.sports(exchange)])
    if exchange == "kalshi":
        return render(request, "exchange.html", mode="kalshi", venue=next(v for v in V.EXCHANGES if v.code == "kalshi"), **ctx)
    return render(request, "exchange.html", mode="pm", venue=SimpleNamespace(name="Polymarket", code="polymarket", url=""), **ctx)


@app.post("/markets/polymarket/mirror", dependencies=[Depends(check_csrf)])
def pm_mirror(request: Request, event_slug: str = Form(...), spread_pct: float = Form(4.0), c=Depends(conn),
              user=allow(*PRO)):
    with get_session() as s:
        created, repriced, skipped = house.mirror_event(s, c, event_slug, user["id"], spread_pct / 100)
    audit(request, "pm_mirror", event_slug=event_slug, spread=spread_pct / 100, created=created, repriced=repriced,
          skipped=skipped)
    msg = f"Mirrored into your book: {created} new, {repriced} repriced, {skipped} without a model price."
    return RedirectResponse(f"/markets/polymarket?spread_pct={spread_pct}&msg={msg}", status_code=303)


@app.post("/markets/polymarket/sync", dependencies=[Depends(check_csrf)])
def pm_sync(request: Request, c=Depends(conn), user=allow(*PRO)):
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


# Kalshi (RACINGLINES_KALSHI_VENUE=1, off by default): the same list and mirror as Polymarket's, read-only on Kalshi
from racinglines.markets import venues as V  # noqa: E402


def _kalshi_on():
    if not V.KALSHI_VENUE:
        raise HTTPException(404)


@app.get("/markets/kalshi", response_class=HTMLResponse, dependencies=[Depends(_kalshi_on)])
def kalshi_board(request: Request, event: str = "", show: str = "modeled", closed: int = 0, spread_pct: float = 4.0,
                 msg: str = "", sport: str = "", c=Depends(conn), user=allow(*PRO)):
    return _exchange_board(request, c, user, "kalshi", event, show, closed, spread_pct, msg, sport)


@app.post("/markets/kalshi/mirror", dependencies=[Depends(_kalshi_on), Depends(check_csrf)])
def kalshi_mirror(request: Request, event_slug: str = Form(...), spread_pct: float = Form(4.0), c=Depends(conn),
                  user=allow(*PRO)):
    with get_session() as s:
        created, repriced, skipped = house.mirror_event(s, c, event_slug, user["id"], spread_pct / 100)
    audit(request, "kalshi_mirror", event_slug=event_slug, spread=spread_pct / 100, created=created, repriced=repriced,
          skipped=skipped)
    msg = f"Mirrored into your book: {created} new, {repriced} repriced, {skipped} without a model price."
    return RedirectResponse(f"/markets/kalshi?spread_pct={spread_pct}&msg={msg}", status_code=303)


@app.post("/markets/kalshi/sync", dependencies=[Depends(_kalshi_on), Depends(check_csrf)])
def kalshi_sync(request: Request, c=Depends(conn), user=allow(*PRO)):
    from racinglines.markets.kalshi import sync as KS
    try:
        with get_session() as s:
            stats = KS.sync(s, c, date.today().year)
        msg = f"Synced {stats['events']} events / {stats['links']} outcomes ({stats['modeled']} priced by the model)."
    except Exception as e:  # noqa: BLE001  (Kalshi unreachable from this machine)
        stats, msg = None, f"Error: couldn't reach Kalshi ({type(e).__name__})."
    audit(request, "kalshi_sync", stats=str(stats))
    return RedirectResponse(f"/markets/kalshi?msg={msg}", status_code=303)


# Exchanges defined as schemas (exchanges/<code>.toml, e.g. OG.com at /markets/og): each with its own switch
# (RACINGLINES_OG_VENUE=1, off by default). The same list and mirror as Kalshi's, read-only, plus the fair-price
# indicator net of the fee (`racinglines markets --exchange <code> fair`). One route per schema code, registered at
# import (no wildcard, so /markets/linked, /markets/tapes and the legacy /markets/{id} redirect keep their paths);
# with every switch off each is a 404 and nothing else changes.
def _schema_routes(code):
    def on():
        if not exchanges.enabled(code):
            raise HTTPException(404)

    @app.get(f"/markets/{code}", response_class=HTMLResponse, dependencies=[Depends(on)], name=f"{code}_board")
    def board(request: Request, event: str = "", show: str = "modeled", closed: int = 0, spread_pct: float = 4.0,
              msg: str = "", sport: str = "", c=Depends(conn), user=allow(*PRO)):
        return _exchange_board(request, c, user, code, event, show, closed, spread_pct, msg, sport)

    @app.post(f"/markets/{code}/mirror", dependencies=[Depends(on), Depends(check_csrf)], name=f"{code}_mirror")
    def mirror(request: Request, event_slug: str = Form(...), spread_pct: float = Form(4.0), c=Depends(conn),
               user=allow(*PRO)):
        with get_session() as s:
            created, repriced, skipped = house.mirror_event(s, c, event_slug, user["id"], spread_pct / 100)
        audit(request, f"{code}_mirror", event_slug=event_slug, spread=spread_pct / 100, created=created, repriced=repriced,
              skipped=skipped)
        msg = f"Mirrored into your book: {created} new, {repriced} repriced, {skipped} without a model price."
        return RedirectResponse(f"/markets/{code}?spread_pct={spread_pct}&msg={msg}", status_code=303)

    @app.post(f"/markets/{code}/sync", dependencies=[Depends(on), Depends(check_csrf)], name=f"{code}_sync")
    def sync(request: Request, c=Depends(conn), user=allow(*PRO)):
        """Every sport the schema lists (exchanges/<code>.toml [sports.*]), the way the CLI syncs one at a time."""
        from racinglines.markets import exchange_driver as D
        stats, parts = {}, []
        try:
            with get_session() as s:
                for sport in exchanges.sports(code):
                    stats[sport] = D.sync(s, c, code, sport, date.today().year)
                    parts.append(f"{sport}: {stats[sport].get('links', 0)} markets ({stats[sport].get('modeled', 0)} priced by the model)")
            msg = "Synced " + "; ".join(parts) + "."
        except Exception as e:  # noqa: BLE001  (the exchange unreachable from this machine)
            stats, msg = None, f"Error: couldn't reach {code} ({type(e).__name__})."
        audit(request, f"{code}_sync", stats=str(stats))
        return RedirectResponse(f"/markets/{code}?msg={msg}", status_code=303)


for _code in exchanges.CODES:
    _schema_routes(_code)


# Tapes (RACINGLINES_TAPES=1, off by default): the tape-only sports' markets as market data, no model and no P&L
def _tapes_on():
    if not V.TAPES:
        raise HTTPException(404)


@app.get("/markets/tapes", response_class=HTMLResponse, dependencies=[Depends(_tapes_on)])
def tapes_page(request: Request, c=Depends(conn), user=allow(*PRO)):
    return render(request, "tapes.html", blocks=V.tape_summary(c), sports=[s["competition"].get("display_name", s["sport"]["name"])
                                                                            for s in V.tape_sports()])


# ---------------------------------------------------------------------------
# Single-event diagnostics (makers/admin): as-of prices vs Polymarket vs result
# ---------------------------------------------------------------------------

from racinglines.web import diag  # noqa: E402


@app.get("/lab/diagnostics/{run_id}", response_class=HTMLResponse, dependencies=[allow(*PRO)])
def diag_page(request: Request, run_id: int, msg: str = "", fill: str = "through", h: float = 0.02, size: float = 50,
              max_pos: float = 250, cap: float = 1000, skew: float = 1.0, disagree: float = 0.15, min_vol: float = 100,
              pull: int = 15, venue: str = "", c=Depends(conn)):
    d = diag.load(c, run_id)
    venue = "kalshi" if venue == "kalshi" and V.KALSHI_VENUE else ""      # the maker replay on Kalshi's tape
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
    rp = diag.replay(c, run_id, **knobs, **(dict(exchange=venue) if venue else {}))
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
                  consts=dict(paper_edge=diag.PAPER_EDGE, paper_stake=diag.PAPER_STAKE), venue=venue, kalshi=V.KALSHI_VENUE)


@app.post("/lab/diagnostics/{run_id}/example", dependencies=[Depends(check_csrf)])
def diag_example(request: Request, run_id: int, fill: str = Form("through"), c=Depends(conn),
                 user=allow(*PRO)):
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


async def _f1_live_ws(websocket):
    """Live F1 timing for one viewer (web/f1_live.py). A plain Starlette route: the app's dependencies (HTTP Basic,
    the demo guard) can't run on a websocket, so the session cookie is checked here."""
    from starlette.concurrency import run_in_threadpool

    from racinglines.web import f1_live

    def who():
        uid = _session_user_id(websocket.cookies.get(SESSION_COOKIE))
        if uid is None:
            return None
        with get_session() as s:
            u = U.get_user(s, user_id=uid)
            return _user_dict(u) if u and u.active else None

    await f1_live.serve(websocket, await run_in_threadpool(who))


from starlette.routing import WebSocketRoute  # noqa: E402

app.router.routes.append(WebSocketRoute("/ws/f1/live", _f1_live_ws))


# FastF1 live stream (WebSocket support; staging's stream page, web/f1_ws.py)
from fastapi import WebSocket, WebSocketDisconnect
from racinglines.web.f1_ws import live_stream_manager, FastF1LiveClient

@app.get("/live/f1/stream", response_class=HTMLResponse)
def live_f1(request: Request, year: int = 2026, round_num: int = None, c=Depends(conn), user=allow(*ANY)):
    """FastF1 live stream page with market pricing (Whistler Live demo replica).

    Shows real-time F1 timing from FastF1 alongside live Polymarket prices.
    Auto-detects current F1 event.
    """
    # Find the current/upcoming F1 race (auto-detect if round_num not specified)
    try:
        if round_num:
            # Use specified round
            races = data.q(c, """
                SELECT ra.id, ra.event_id, e.season_id, e.start_date, e.name, s.competition_id
                FROM races ra
                JOIN events e ON e.id = ra.event_id
                JOIN seasons s ON s.id = e.season_id
                WHERE s.year = :year AND e.round = :round
                LIMIT 1
            """, year=year, round=round_num)
        else:
            # Auto-detect: first look for ongoing, then upcoming, then most recent
            races = data.q(c, """
                SELECT ra.id, ra.event_id, e.round, e.season_id, e.start_date, e.name, e.status, s.competition_id
                FROM races ra
                JOIN events e ON e.id = ra.event_id
                JOIN seasons s ON s.id = e.season_id
                WHERE s.year = :year
                ORDER BY CASE
                    WHEN e.status = 'ongoing' THEN 0
                    WHEN e.status = 'upcoming' THEN 1
                    WHEN e.status = 'completed' THEN 2
                END ASC,
                e.start_date DESC
                LIMIT 1
            """, year=year)
            if races:
                round_num = races[0].get("round")  # Extract round number from event

        race_id = races[0]["id"] if races else None
        event_name = races[0].get("name", f"Round {round_num}") if races else None
    except Exception as e:
        logger.error(f"Error finding F1 race: {e}")
        race_id = None
        event_name = None
        round_num = 21

    return render(request, "live_f1_stream.html", year=year, round_num=round_num, race_id=race_id, event_name=event_name)

@app.get("/api/f1/markets/{race_id}")
def f1_markets(race_id: int, c=Depends(conn), user=allow(*ANY)):
    """Fetch market data for an F1 race (race winner odds)."""
    try:
        from racinglines.markets.venues import event_matrix
        info, pricing, df = event_matrix(c, race_id)

        # Filter to race winner markets
        winners = df[df["kind"] == "race_win"].copy()

        # Get athlete names
        athlete_ids = winners["athlete_id"].unique() if len(winners) > 0 else []
        athletes = {}
        if len(athlete_ids) > 0:
            names = data.q(c,
                f"SELECT id, display_name FROM athletes WHERE id IN ({','.join('?' * len(athlete_ids))})",
                *athlete_ids)
            athletes = {row["id"]: row["display_name"] for _, row in names.iterrows()}

        markets = []
        for _, row in winners.iterrows():
            athlete_name = athletes.get(row.get("athlete_id"), f"#{row.get('athlete_id', '?')}")
            fair_val = float(row["fair"]) if row["fair"] is not None and pd.notna(row["fair"]) else None
            pm_bid = float(row.get("pm_bid", None)) if row.get("pm_bid") is not None and pd.notna(row.get("pm_bid")) else None
            pm_ask = float(row.get("pm_ask", None)) if row.get("pm_ask") is not None and pd.notna(row.get("pm_ask")) else None

            markets.append({
                "subject": athlete_name,
                "fair": fair_val,
                "bid": pm_bid,
                "ask": pm_ask,
            })

        return {"markets": sorted(markets, key=lambda m: m["fair"] or 0, reverse=True), "source": pricing.get("source", "model")}
    except Exception as e:
        logger.error(f"Error fetching F1 markets: {e}")
        return {"markets": [], "error": str(e)}

@app.websocket("/ws/f1/live/{session_id}")
async def websocket_f1_live(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for F1 live timing updates."""
    await websocket.accept()
    await live_stream_manager.add_client(session_id, websocket)

    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "start":
                # Start live updates for this session
                year = msg.get("year")
                round_num = msg.get("round")
                session_name = msg.get("session")  # "FP1", "FP2", "FP3", "SQ", "SS", "Q", "R"

                if year and round_num and session_name:
                    try:
                        fastf1_session = await FastF1LiveClient.get_session(year, round_num, session_name)
                        if fastf1_session is None:
                            await websocket.send_json({
                                "type": "error",
                                "data": {"error": f"F1 session {year} R{round_num} {session_name} not found"}
                            })
                        else:
                            await live_stream_manager.start_live_updates(session_id, fastf1_session, update_interval=5)
                    except Exception as e:
                        logger.error(f"Error loading F1 session {year} R{round_num} {session_name}: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "data": {"error": f"Failed to load session: {str(e)[:100]}"}
                        })
    except WebSocketDisconnect:
        await live_stream_manager.remove_client(session_id)
    except Exception as e:
        logger.error(f"WebSocket error for {session_id}: {e}")
        await live_stream_manager.remove_client(session_id)


from racinglines.web import admin  # noqa: E402,F401  (registers /admin routes)
from racinglines.web import views  # noqa: E402,F401  (registers the board, race, season, book and lab pages)
from racinglines.web import api  # noqa: E402,F401  (the read-only JSON API; off unless RACINGLINES_JSON_API=1)
from racinglines.web import legacy  # noqa: E402,F401  (old page URLs redirect to the current routes; register last)
