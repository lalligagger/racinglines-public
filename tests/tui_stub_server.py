"""A stdio MCP server for the TUI transport test that answers like `racinglines mcp`: a drawn table, then the JSON.
Run as a script (tests/test_tui_transport.py starts it)."""
import json
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tui_fixtures import BALANCE, MARKETS  # noqa: E402

server = MCPServer("racinglines-stub")


def render(payload: dict) -> str:
    return "┌──────┐\n│ table │\n└──────┘" + json.dumps(payload)


@server.tool()
def fantasy_balance(user: str | None = None) -> str:
    return render(BALANCE)


@server.tool()
def list_markets(event_id: int | None = None, kinds: str | None = None, limit: int = 50, offset: int = 0) -> str:
    return render({**MARKETS, "echo": {"event_id": event_id, "kinds": kinds, "limit": limit}})


@server.tool()
def fantasy_order(market_link_id: int, side: str, action: str, shares: int, limit_price: float) -> str:
    raise ToolError("book is 40 min old; orders are refused past 15 minutes")


if __name__ == "__main__":
    server.run("stdio")
