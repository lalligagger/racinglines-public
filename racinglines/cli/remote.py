"""
`--remote` for `racinglines book`: run map / price / settle on the VM's hosted MCP server (docs/mcp.md, Hosted) instead
of a local database, so nobody has to rebuild the data or serve the app to try the commands. The book file is read
and validated here and sent as text to the MCP tools `map_book`, `price_book`, `settle_book`, which return the same
dict `--json` prints locally (racinglines/books/slips.py); `--rich` and plain text render it the same way.

Sign-in, the same OAuth flow Claude's connector uses (docs/mcp.md, Hosted): the first `--remote` opens racinglines.bet in
the browser for one Allow (after the normal login if needed) and keeps the login in ~/.config/racinglines/mcp-login.json
(mode 600): an access token it refreshes on its own, for 30 days of disuse. `racinglines book logout` forgets it.

    RACINGLINES_MCP_TOKEN   an account's rl_ token instead of the browser sign-in (scripts, machines with no browser)
    RACINGLINES_MCP_URL     the server (default https://mcp.racinglines.bet/mcp); --mcp-url overrides it.
"""

import asyncio
import json
import os
import socket
import sys
import threading
from pathlib import Path

DEFAULT_URL = "https://mcp.racinglines.bet/mcp"
TOOLS = {"map": "map_book", "price": "price_book", "settle": "settle_book"}
LOGIN_FILE = Path(os.environ.get("RACINGLINES_MCP_LOGIN", "~/.config/racinglines/mcp-login.json")).expanduser()
CALLBACK_WAIT_SEC = 300
WARNING = ("warning: racinglines.bet remote access is in testing (#aintcare mode). A review of venue and data-feed "
           "terms is pending, so data served here is for testing only.")
_warned = False


def warn():
    """The remote-access warning on stderr, once per command run, before anything the server returns (stdout stays
    clean for --json). Every remote path goes through call(), which calls this first."""
    global _warned
    if not _warned:
        print(WARNING, file=sys.stderr, flush=True)
        _warned = True


class RemoteError(RuntimeError):
    """The server refused or failed the call; the message says why."""


def url(override=None):
    return override or os.environ.get("RACINGLINES_MCP_URL") or DEFAULT_URL


def token():
    """An rl_ token from the environment, or None (then the browser sign-in is used)."""
    return os.environ.get("RACINGLINES_MCP_TOKEN", "").strip() or None


# --- browser sign-in -----------------------------------------------------------------------------------------------

def _load():
    try:
        return json.loads(LOGIN_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save(data):
    LOGIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOGIN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(LOGIN_FILE)


def logout(server=None):
    """Forget the stored login for `server` (all servers when None). True if there was one."""
    data = _load()
    if server is None:
        had = bool(data)
        data = {}
    else:
        had = data.pop(url(server), None) is not None
    if data:
        _save(data)
    elif LOGIN_FILE.exists():
        LOGIN_FILE.unlink()
    return had


class _Storage:
    """The SDK's TokenStorage, one entry per server URL in LOGIN_FILE."""

    def __init__(self, server):
        self.server = server

    def _get(self, key, model):
        v = _load().get(self.server, {}).get(key)
        return None if v is None else model.model_validate(v)

    def _set(self, key, value):
        data = _load()
        data.setdefault(self.server, {})[key] = value.model_dump(mode="json", exclude_none=True)
        _save(data)

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        return self._get("tokens", OAuthToken)

    async def set_tokens(self, tokens):
        self._set("tokens", tokens)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        return self._get("client", OAuthClientInformationFull)

    async def set_client_info(self, client_info):
        self._set("client", client_info)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _callback_port(server):
    """The loopback port the registered client redirects to: the stored client's, else a free one (a new client)."""
    client = _load().get(server, {}).get("client")
    if client:
        from urllib.parse import urlparse
        return urlparse(client["redirect_uris"][0]).port
    return _free_port()


def _listen(port):
    """Bind the sign-in callback server on 127.0.0.1:port. Bound before the browser opens, so a fast browser (or a
    test's) never finds the port closed; `_wait_for_callback` then serves it."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urlparse(self.path)
            if q.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            got.update({k: v[0] for k, v in parse_qs(q.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Signed in. You can close this tab." if "code" in got else "Sign-in was not completed."
            self.wfile.write(f"<p style='font-family:sans-serif'>racinglines: {msg}</p>".encode())

        def log_message(self, *args):
            pass

    try:
        httpd = HTTPServer(("127.0.0.1", port), Handler)
    except OSError as ex:
        raise RemoteError(f"can't listen on 127.0.0.1:{port} for the sign-in ({ex}); "
                          "run `racinglines book logout` and try again") from ex
    httpd.timeout = 1
    httpd.got = got
    return httpd


def _wait_for_callback(httpd):
    """Serve one GET /callback on the bound server and return its query parameters (code, state, or error)."""
    got = httpd.got
    with httpd:
        for _ in range(CALLBACK_WAIT_SEC):
            httpd.handle_request()
            if got:
                return got
    raise RemoteError(f"no sign-in within {CALLBACK_WAIT_SEC} s")


def oauth(server, open_browser=None):
    """The SDK's OAuth provider for `server`: stored tokens, refreshed as needed; a browser sign-in when there are
    none. `open_browser(url)` is for tests (default: the web browser, and the URL printed to stderr)."""
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata
    port = _callback_port(server)
    pending = {}

    async def redirect(auth_url):
        httpd = _listen(port)
        pending["t"] = threading.Thread(target=lambda: pending.update(r=_safe_wait(httpd)), daemon=True)
        pending["t"].start()
        print(f"Sign in to racinglines in your browser (this URL if it does not open):\n  {auth_url}", file=sys.stderr)
        if open_browser:
            await asyncio.to_thread(open_browser, auth_url)
        else:
            import webbrowser
            webbrowser.open(auth_url)

    async def callback():
        await asyncio.to_thread(pending["t"].join)
        r = pending.get("r")
        if isinstance(r, Exception):
            raise r
        if "code" not in r:
            raise RemoteError(f"sign-in refused: {r.get('error', 'no code returned')}")
        return AuthorizationCodeResult(code=r["code"], state=r.get("state"))

    meta = OAuthClientMetadata(client_name="racinglines CLI", redirect_uris=[f"http://127.0.0.1:{port}/callback"],
                               grant_types=["authorization_code", "refresh_token"], response_types=["code"],
                               token_endpoint_auth_method="none")
    return OAuthClientProvider(server_url=server, client_metadata=meta, storage=_Storage(server),
                               redirect_handler=redirect, callback_handler=callback)


def _safe_wait(httpd):
    try:
        return _wait_for_callback(httpd)
    except Exception as ex:  # noqa: BLE001  (handed to the callback handler, which raises it)
        return ex


def call(tool, arguments, server=None, tok=None, http_client=None, open_browser=None):
    """Call one tool on the hosted server and return its parsed JSON: with an rl_ token (`tok`, else
    RACINGLINES_MCP_TOKEN) when there is one, else the browser sign-in. `http_client` (an httpx2.AsyncClient) and
    `open_browser` are for tests."""
    warn()
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    statuses = []                                          # the SDK's errors drop the HTTP status: keep it here

    async def seen(response):
        if response.status_code >= 400:
            statuses.append(response.status_code)

    async def go():
        bearer = tok or token()
        client = http_client or (create_mcp_http_client(headers={"Authorization": f"Bearer {bearer}"}) if bearer
                                 else create_mcp_http_client(auth=oauth(url(server), open_browser)))
        client.event_hooks.setdefault("response", []).append(seen)
        async with client, streamable_http_client(url(server), http_client=client) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool, arguments)

    try:
        r = asyncio.run(go())
    except RemoteError:
        raise
    except Exception as ex:  # noqa: BLE001  (network, TLS, 401: one line the user can act on)
        raise RemoteError(f"{url(server)}: {_reason(ex, statuses)}") from ex
    text = r.content[0].text if r.content else ""
    if r.is_error:
        raise RemoteError(f"{tool}: {text}")
    return json.loads(text)


def _reason(ex, statuses=()):
    """One line the user can act on: the HTTP status the server answered, else the innermost message of an exception
    group (anyio wraps transport errors)."""
    if 401 in statuses:
        return ("401 Unauthorized: the token or login is wrong, revoked or for an account that may not use MCP "
                "(`racinglines book logout` forgets a stored login)")
    while isinstance(ex, BaseExceptionGroup) and ex.exceptions:
        ex = ex.exceptions[0]
    msg = str(ex).splitlines()[0] if str(ex) else type(ex).__name__
    return (f"HTTP {statuses[-1]}: " if statuses else "") + msg[:300]


def run(cmd, raw_book, server=None, runs=(), open_browser=None):
    """The command's result dict from the hosted server: what `racinglines book CMD --json` prints locally."""
    args = {"book": raw_book}
    if cmd == "price" and runs:
        args["run_ids"] = list(runs)
    return call(TOOLS[cmd], args, server, open_browser=open_browser)


# --- model commands as hosted jobs ---------------------------------------------------------------------------------
# `racinglines model backtest|forecast SPORT --remote`: the command's Lab job (racinglines/web/jobs.py CATALOG) queued
# on the hosted server with run_job and followed with get_job, its log printed as it arrives. The server runs the same
# CLI command in its own worker; the flags below are the ones the job takes (its knobs), the rest are local only.

JOBS = {("f1", "backtest"): "f1_backtest", ("f1", "forecast"): "f1_scenario",
        ("mtb_dh", "backtest"): "dh_backtest", ("mtb_dh", "forecast"): "dh_scenario"}
POLL_SEC = 1.0
TAIL = 200                                 # log lines per get_job poll (the tool returns up to 500)


def _job_parser(job):
    import argparse
    ap = argparse.ArgumentParser(prog=f"--remote ({job})", add_help=False)
    ap.add_argument("--sims", type=int)
    if job.startswith("f1_"):
        ap.add_argument("--half-life", dest="half_life", type=float)
    else:
        ap.add_argument("--half-life-days", dest="half_life", type=float)
        ap.add_argument("--junior-weight", dest="junior_weight", type=float)
    if job == "f1_backtest":
        ap.add_argument("--races", type=int)
        ap.add_argument("--track", choices=["both", "on", "off"])
    if job.endswith("_scenario"):
        ap.add_argument("--scenario", dest="label")
    if job == "f1_scenario":
        ap.add_argument("--no-track", dest="track", action="store_const", const="off")
    ap.add_argument("--save", action="store_true")              # implied: a hosted job always saves its run
    ap.add_argument("--db", nargs="?", const="")                 # mtb_dh's "read the database": the server's always
    return ap


def job_params(sport, command, argv):
    """(job type, params) for `model COMMAND SPORT argv --remote`. Raises RemoteError on a flag the job doesn't take."""
    job = JOBS.get((sport, command))
    if job is None:
        raise RemoteError(f"model {command} {sport} doesn't run on the hosted server (it runs: "
                          f"{', '.join(f'model {c} {s}' for s, c in JOBS)})")
    known, extra = _job_parser(job).parse_known_args([a for a in argv if a != "--remote"])
    if extra:
        raise RemoteError(f"{' '.join(extra)}: local only; on the hosted server model {command} {sport} takes "
                          + ", ".join(sorted(o for a in _job_parser(job)._actions for o in a.option_strings
                                             if o not in ("--save", "--db"))))
    params = {k: v for k, v in vars(known).items() if v is not None and k not in ("save", "db")}
    if job.endswith("_scenario"):
        params.setdefault("label", f"cli {command}")
    return job, params


def run_model(sport, command, argv, server=None, out=None, poll=POLL_SEC, sleep=None):
    """Queue the job, print its log as it arrives (stdout), and return 0 when it is done, 1 when it failed."""
    import time
    out = out or sys.stdout
    sleep = sleep or time.sleep
    job, params = job_params(sport, command, argv)
    q = call("run_job", dict(job_type=job, params=params), server)
    job_id = q["job_id"]
    print(f"queued {job} as job {job_id} on {url(server)} ({', '.join(f'{k}={v}' for k, v in q['params'].items())})",
          file=sys.stderr, flush=True)
    seen = 0
    from racinglines import progress as PG
    while True:
        j = call("get_job", dict(job_id=job_id, log_lines=TAIL), server)
        n, tail = j.get("log_lines", 0), j.get("log_tail") or []
        new = n - seen
        if new > len(tail):
            print(f"... ({new - len(tail)} log lines not shown; get_job({job_id}) on the server)", file=out, flush=True)
        for line in tail[len(tail) - min(max(new, 0), len(tail)):]:
            print(line, file=out, flush=True)
        seen = n
        PG.update(item=f"job {job_id} {j['status']}: {j.get('progress') or ''}"[:120])
        if j["status"] in ("done", "failed"):
            break
        sleep(poll)
    run = j.get("result_run_id")
    print(f"job {job_id} {j['status']}" + (f": model run {run} on the hosted server (get_model_run({run}))" if run else
                                           f" ({j.get('progress')})"), file=sys.stderr, flush=True)
    return 0 if j["status"] == "done" else 1
