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


def _wait_for_callback(port):
    """Serve one GET /callback on 127.0.0.1:port and return its query parameters (code, state, or error)."""
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
        pending["t"] = threading.Thread(target=lambda: pending.update(r=_safe_wait(port)), daemon=True)
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


def _safe_wait(port):
    try:
        return _wait_for_callback(port)
    except Exception as ex:  # noqa: BLE001  (handed to the callback handler, which raises it)
        return ex


def call(tool, arguments, server=None, tok=None, http_client=None, open_browser=None):
    """Call one tool on the hosted server and return its parsed JSON: with an rl_ token (`tok`, else
    RACINGLINES_MCP_TOKEN) when there is one, else the browser sign-in. `http_client` (an httpx2.AsyncClient) and
    `open_browser` are for tests."""
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
