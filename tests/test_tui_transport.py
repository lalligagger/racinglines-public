"""The TUI backend over a real MCP stdio session (tests/tui_stub_server.py), and a clear error for a bad command."""
import asyncio
import sys
from pathlib import Path

import pytest

from racinglines.tui.backend import ConnectionSettings, McpBackend, ToolError

STUB = Path(__file__).resolve().parent / "tui_stub_server.py"


def test_stdio_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr("racinglines.tui.backend.LOG_DIR", tmp_path)

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

    asyncio.run(go())


def test_bad_command_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr("racinglines.tui.backend.LOG_DIR", tmp_path)

    async def go():
        backend = McpBackend(ConnectionSettings(stdio_argv=["definitely-not-racinglines", "mcp"]))
        with pytest.raises(ConnectionError, match="server log"):
            await backend.start()

    asyncio.run(go())
