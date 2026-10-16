from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.widget import Widget

from ..backend import ToolError

if TYPE_CHECKING:
    from ..app import RacinglinesApp


class Pane(Vertical):
    """One tab of the app. Loads lazily the first time it is shown; r refreshes it."""

    DEFAULT_CSS = "Pane { height: 1fr; }"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.loaded = False

    @property
    def rl(self) -> "RacinglinesApp":
        return self.app  # type: ignore[return-value]

    def ensure_loaded(self) -> None:
        if not self.loaded:
            self.loaded = True
            self.refresh_data()

    def refresh_data(self) -> None:  # override
        pass

    async def call(self, tool: str, busy: Widget | None = None, **args: Any) -> Any:
        return await call_tool(self, tool, busy=busy, **args)

    def run(self, coro: Any, group: str = "load") -> None:
        self.run_worker(coro, exclusive=True, group=f"{self.id}-{group}", exit_on_error=False)


async def call_tool(widget: Widget, tool: str, busy: Widget | None = None, **args: Any) -> Any:
    """Call a tool, showing a spinner on `busy`; failures become a notification and None."""
    app = widget.app
    if busy is not None:
        busy.loading = True
    try:
        return await app.backend.call(tool, **args)  # type: ignore[attr-defined]
    except ToolError as exc:
        app.notify(str(exc), title=tool, severity="error", timeout=8)
    except (ConnectionError, OSError) as exc:
        app.notify(f"{exc}", title="Not connected", severity="error", timeout=8)
    except TimeoutError:
        app.notify("The server took too long to answer.", title=tool, severity="warning")
    except Exception as exc:  # noqa: BLE001
        app.notify(f"{exc.__class__.__name__}: {exc}", title=tool, severity="error", timeout=8)
    finally:
        if busy is not None:
            busy.loading = False
    return None


def int_or_none(text: str | None) -> int | None:
    text = (text or "").strip()
    try:
        return int(text) if text else None
    except ValueError:
        return None


def float_or_none(text: str | None) -> float | None:
    text = (text or "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None
