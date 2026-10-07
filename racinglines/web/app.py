"""
racinglines web app (FastAPI, server-rendered).

Three roles (see roles.py): admin, pro, basic (`maker` / `taker` rows read as pro / basic). Every route needs
a signed-in user (session cookie from /login, or HTTP Basic) and declares which roles may use it (allow(*PRO)
for the maker tools and the Lab); every form POST carries a CSRF token; every meaningful action is
written to activity_log. Run with `racinglines web`.
"""

import contextvars
import hashlib
import hmac
import json  # noqa: F401  (staging's F1 stream routes)
import logging
import os
import re
import secrets
import threading
import time
from urllib.parse import quote
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
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]      # the repository

from racinglines.db import models as m  # noqa: E402
from racinglines.db.config import get_engine, get_session  # noqa: E402

from racinglines.db import reads as data  # noqa: E402,F401  (route modules import it from here)
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

from racinglines.web.formats import (LABELS, MONEY_COLS, SIGNED_MONEY_COLS, fmt, kind, money,  # noqa: E402,F401
                                     when)

templates.env.filters.update(fmt=fmt, money=money, kind=kind, when=when)
templates.env.globals["LABELS"] = LABELS              # short column headers for the `table` macro
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


SITE = ROOT / "site"     # the built docs (mkdocs build -d site; the pre-push hook builds it); served by web/info_routes.py


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


# Kalshi (RACINGLINES_KALSHI_VENUE=1, off by default) and the schema venues: their switches, read by render()
from racinglines.markets import venues as V  # noqa: E402


# Route groups split out of this file; each imports the shared helpers above and registers its routes.
from racinglines.web import info_routes  # noqa: E402,F401  (runs, events, athletes, docs, intro, pitch)
from racinglines.web import order_routes  # noqa: E402,F401  (linked markets and Polymarket orders, admin)
from racinglines.web import book_routes  # noqa: E402,F401  (the private book and the taker's calls)
from racinglines.web import exchange_routes  # noqa: E402,F401  (exchange boards and tapes)
from racinglines.web import diag_routes  # noqa: E402,F401  (single-event diagnostics)
from racinglines.web.book_routes import bet_markets, polymarket_calls  # noqa: E402,F401  (used by views.py)


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


from racinglines.web import admin  # noqa: E402,F401  (registers /admin routes)
from racinglines.web import views  # noqa: E402,F401  (registers the board, race, season, book and lab pages)
from racinglines.web import api  # noqa: E402,F401  (the read-only JSON API; off unless RACINGLINES_JSON_API=1)
from racinglines.web import legacy  # noqa: E402,F401  (old page URLs redirect to the current routes; register last)
