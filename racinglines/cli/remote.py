"""
`--demo` for `racinglines book`: run map / price / settle on the VM's hosted MCP server (docs/mcp.md, Hosted) instead
of a local database, so nobody has to rebuild the data or serve the app to try the commands. The book file is read
and validated here and sent as text to the MCP tools `map_book`, `price_book`, `settle_book`, which return the same
dict `--json` prints locally (racinglines/books/slips.py); `--rich` and plain text render it the same way.

    RACINGLINES_MCP_TOKEN   an account's rl_ token (web app: Settings > Connect Claude (MCP) > Get a token). Required.
    RACINGLINES_MCP_URL     the server (default https://mcp.racinglines.bet/mcp); --mcp-url overrides it.
"""

import asyncio
import json
import os

DEFAULT_URL = "https://mcp.racinglines.bet/mcp"
TOOLS = {"map": "map_book", "price": "price_book", "settle": "settle_book"}


class RemoteError(RuntimeError):
    """The server refused or failed the call; the message says why."""


def url(override=None):
    return override or os.environ.get("RACINGLINES_MCP_URL") or DEFAULT_URL


def token():
    tok = os.environ.get("RACINGLINES_MCP_TOKEN", "").strip()
    if not tok:
        raise RemoteError("--demo needs RACINGLINES_MCP_TOKEN, an account's rl_ token from the web app "
                          "(Settings > Connect Claude (MCP) > Get a token)")
    return tok


def call(tool, arguments, server=None, tok=None, http_client=None):
    """Call one tool on the hosted server and return its parsed JSON. `http_client` (an httpx2.AsyncClient) is for
    tests; by default one is made with the bearer token."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    statuses = []                                          # the SDK's errors drop the HTTP status: keep it here

    async def seen(response):
        if response.status_code >= 400:
            statuses.append(response.status_code)

    async def go():
        client = http_client or create_mcp_http_client(headers={"Authorization": f"Bearer {tok or token()}"})
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
        return "401 Unauthorized: the token is wrong, revoked or for an account that may not use MCP"
    while isinstance(ex, BaseExceptionGroup) and ex.exceptions:
        ex = ex.exceptions[0]
    msg = str(ex).splitlines()[0] if str(ex) else type(ex).__name__
    return (f"HTTP {statuses[-1]}: " if statuses else "") + msg[:300]


def run(cmd, raw_book, server=None, runs=()):
    """The command's result dict from the hosted server: what `racinglines book CMD --json` prints locally."""
    args = {"book": raw_book}
    if cmd == "price" and runs:
        args["run_ids"] = list(runs)
    return call(TOOLS[cmd], args, server)
