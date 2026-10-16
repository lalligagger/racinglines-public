"""The TUI's connection: one MCP session to the hosted server (sign-in is `--remote`'s, racinglines/cli/remote.py:
RACINGLINES_MCP_TOKEN or the stored browser login) or to `racinglines mcp` over stdio on this machine.

Every tool answers with a drawn table and the same data as JSON, the last block; `parse_payload` takes the JSON so
the screens work on rows, never on rendered text.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

LOG_DIR = Path(os.environ.get("RACINGLINES_TUI_LOG_DIR", "~/.cache/racinglines/tui")).expanduser()


class ToolError(RuntimeError):
    """The server refused or failed a tool call; the message is the server's own."""


class Backend(Protocol):
    label: str

    async def start(self) -> None: ...
    async def call(self, tool: str, **args: Any) -> Any: ...
    async def close(self) -> None: ...


# --------------------------------------------------------------------------- parsing

_decoder = json.JSONDecoder()


def _json_tail(text: str) -> Any:
    """The JSON value that ends `text` (tools print a table, then the JSON)."""
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except ValueError:
        pass
    end = len(stripped)
    # The outermost JSON value starts at the earliest '{' or '[' that decodes to the end.
    for i, ch in enumerate(stripped):
        if ch not in "{[":
            continue
        try:
            value, stop = _decoder.raw_decode(stripped, i)
        except ValueError:
            continue
        if stop == end:
            return value
    return None


def parse_payload(result: Any) -> Any:
    """CallToolResult -> the tool's JSON payload (dict or list)."""
    is_error = getattr(result, "is_error", None)
    if is_error is None:
        is_error = getattr(result, "isError", False)
    content = getattr(result, "content", None) or []
    texts = [getattr(block, "text", "") for block in content if getattr(block, "type", "") == "text"]

    if is_error:
        raise ToolError("\n".join(t for t in texts if t).strip() or "The server returned an error.")

    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if structured is not None:
        # FastMCP/MCPServer wrap non-object returns as {"result": ...}.
        if isinstance(structured, dict) and set(structured) == {"result"}:
            structured = structured["result"]
        if isinstance(structured, str):  # a rendered string: its JSON tail is the payload
            value = _json_tail(structured)
            if value is not None:
                return value
        else:
            return structured

    for text in reversed(texts):  # a separate JSON block, when the server sends one
        value = _json_tail(text)
        if value is not None:
            return value
    joined = "".join(texts)
    value = _json_tail(joined)
    if value is not None:
        return value
    return {"text": joined}


# --------------------------------------------------------------------------- transport


@dataclass
class ConnectionSettings:
    """Hosted (`url`, with `token` or the stored browser login) or local (`stdio_argv`, `racinglines mcp`)."""

    url: str | None = None
    token: str | None = None
    stdio_argv: list[str] | None = None
    timeout: float = 90.0
    statuses: list[int] = field(default_factory=list)   # HTTP statuses >= 400 seen: the SDK's errors drop them

    @property
    def label(self) -> str:
        argv = self.stdio_argv
        if argv:
            if "mcp" in argv:  # `python -m racinglines mcp [--db ...]`: show it the way it is typed
                return "local: " + " ".join(["racinglines", *argv[argv.index("mcp"):]])
            return "local: " + " ".join(argv)
        return self.url or "not configured"


def local_argv(db: str | None = None, no_jobs: bool = False) -> list[str]:
    """`racinglines mcp` with this interpreter, so the TUI and the server share one environment."""
    argv = [sys.executable, "-m", "racinglines", "mcp"]
    if db:
        argv += ["--db", db]
    if no_jobs:
        argv.append("--no-jobs")
    return argv


@contextlib.asynccontextmanager
async def _http_transport(settings: ConnectionSettings):
    """Streamable HTTP with the same client remote.py builds: a bearer token, else the stored OAuth login."""
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    from racinglines.cli import remote

    async def seen(response):
        if response.status_code >= 400:
            settings.statuses.append(response.status_code)

    client = (create_mcp_http_client(headers={"Authorization": f"Bearer {settings.token}"}) if settings.token
              else create_mcp_http_client(auth=remote.oauth(remote.url(settings.url))))
    client.event_hooks.setdefault("response", []).append(seen)
    async with client, streamable_http_client(remote.url(settings.url), http_client=client) as streams:
        yield streams


def _open_errlog():
    """The file the stdio server's stderr goes to: it must never reach the terminal, the TUI owns it. The caller
    closes it."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return open(LOG_DIR / "server.log", "a", encoding="utf-8")  # noqa: SIM115


def _stdio_transport(argv: list[str], errlog):
    from mcp.client.stdio import StdioServerParameters, stdio_client

    env = {**os.environ, "RACINGLINES_PROGRESS_SEC": "0"}
    return stdio_client(StdioServerParameters(command=argv[0], args=argv[1:], env=env), errlog=errlog)


class McpBackend:
    """Holds one MCP session in a background task; any task may call tools on it."""

    def __init__(self, settings: ConnectionSettings) -> None:
        self.settings = settings
        self.label = settings.label
        self.server_name: str | None = None
        self._session: Any = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._error: BaseException | None = None
        self._task: asyncio.Task | None = None
        self._errlog: Any = None

    @property
    def connected(self) -> bool:
        return self._session is not None

    @property
    def error(self) -> BaseException | None:
        return self._error

    async def start(self) -> None:
        if not (self.settings.url or self.settings.stdio_argv):
            raise ConnectionError("No server: `racinglines tui` (hosted) or `racinglines tui --local`.")
        self._ready.clear()
        self._stop.clear()
        self._error = None
        self._task = asyncio.create_task(self._run(), name="racinglines-mcp")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=30)
        except asyncio.TimeoutError as exc:
            raise ConnectionError(f"No answer from {self.label} within 30 s.") from exc
        if self._error is not None:
            raise ConnectionError(self.describe(self._error)) from self._error

    async def _run(self) -> None:
        from mcp import ClientSession

        self.settings.statuses.clear()
        try:
            if self.settings.stdio_argv:
                self._errlog = _open_errlog()
                transport = _stdio_transport(self.settings.stdio_argv, self._errlog)
            else:
                transport = _http_transport(self.settings)
            async with transport as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
                    self.server_name = getattr(info, "name", None)
                    self._session = session
                    self._ready.set()
                    await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - surfaced to the UI
            if not isinstance(exc, asyncio.CancelledError):
                self._error = exc
        finally:
            self._session = None
            self._close_errlog()  # after the child is gone, on a clean close and on a failed start alike
            self._ready.set()

    def _close_errlog(self) -> None:
        errlog, self._errlog = self._errlog, None
        if errlog is not None:
            with contextlib.suppress(OSError):
                errlog.close()

    async def call(self, tool: str, **args: Any) -> Any:
        await self._ready.wait()
        session = self._session
        if session is None:
            raise ConnectionError(self.describe(self._error) if self._error else "Not connected. Press ctrl+r to reconnect.")
        clean = {k: v for k, v in args.items() if v is not None and v != ""}
        result = await asyncio.wait_for(session.call_tool(tool, clean), timeout=self.settings.timeout)
        return parse_payload(result)

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(self._task, timeout=5)
        self._task = None
        self._close_errlog()  # a task that outlived the wait is cancelled above; its handle goes either way

    def describe(self, exc: BaseException) -> str:
        """One line the user can act on: remote.py's wording (HTTP status, 401 advice), the stdio server's log path."""
        from racinglines.cli import remote

        text = remote._reason(exc, self.settings.statuses)  # noqa: SLF001 - the CLI's own message, kept identical
        if self.settings.stdio_argv:
            text += f" (server log: {LOG_DIR / 'server.log'})"
        return text
