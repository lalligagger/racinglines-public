"""The TUI backend over a real MCP stdio session (tests/tui_stub_server.py), and a clear error for a bad command."""
import asyncio
import sys
from pathlib import Path

import pytest

from racinglines.tui.backend import ConnectionSettings, McpBackend, ToolError

STUB = Path(__file__).resolve().parent / "tui_stub_server.py"


def _record_errlogs(monkeypatch, tmp_path):
    """LOG_DIR in tmp_path, and every server.log handle the backend opens, so a test can see it closed."""
    from racinglines.tui import backend as mod

    monkeypatch.setattr(mod, "LOG_DIR", tmp_path)
    opened = []
    real = mod._open_errlog

    def spy():
        handle = real()
        opened.append(handle)
        return handle

    monkeypatch.setattr(mod, "_open_errlog", spy)
    return opened


def test_stdio_round_trip(monkeypatch, tmp_path):
    opened = _record_errlogs(monkeypatch, tmp_path)

    async def go():
        backend = McpBackend(ConnectionSettings(stdio_argv=[sys.executable, str(STUB)], timeout=20))
        await backend.start()
        try:
            assert backend.connected and backend.server_name == "racinglines-stub"
            bal = await backend.call("fantasy_balance")
            assert bal["total"] == 1000.0
            mk = await backend.call("list_markets", event_id=91, kinds=None, limit=5)
            assert mk["echo"] == {"event_id": 91, "kinds": None, "limit": 5}  # None args are dropped
            assert mk["outcomes"]["rows"][0]["subject"] == "Max Verstappen"
            with pytest.raises(ToolError, match="40 min old"):
                await backend.call("fantasy_order", market_link_id=1, side="yes", action="buy", shares=1,
                                   limit_price=0.5)
        finally:
            await backend.close()
        assert not backend.connected
        assert len(opened) == 1 and opened[0].closed  # close() leaves no server.log handle behind

    asyncio.run(go())


def test_bad_command_is_a_clear_error(tmp_path, monkeypatch):
    opened = _record_errlogs(monkeypatch, tmp_path)

    async def go():
        backend = McpBackend(ConnectionSettings(stdio_argv=["definitely-not-racinglines", "mcp"]))
        with pytest.raises(ConnectionError, match="server log"):
            await backend.start()
        await backend.close()

    asyncio.run(go())
    assert opened and all(h.closed for h in opened)  # a failed start closes the log too
