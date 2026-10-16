"""The private book's live events: settled maker P&L against the crowd, and whether one is live now."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from .. import fmt

from ..widgets import ObjectView
from .base import Pane


class LivePane(Pane):
    def compose(self) -> ComposeResult:
        yield Static(id="lv-state")
        yield ObjectView(id="lv-view")

    def on_mount(self) -> None:
        self.set_interval(30, self._tick)

    def _tick(self) -> None:
        if self.loaded and self.display:
            self.refresh_data()

    def refresh_data(self) -> None:
        self.run(self._load())

    async def _load(self) -> None:
        view = self.query_one("#lv-view", ObjectView)
        payload = await self.call("list_live_events", busy=view if not view.children else None, limit=100)
        if isinstance(payload, dict):
            state = str(payload.get("state") or "?")
            badge = Text(f"{'Live now' if state == 'live' else state.title()}",
                         style=f"bold {fmt.PURPLE}" if state == "live" else fmt.DIM)
            self.query_one("#lv-state", Static).update(badge)
            await view.show({k: v for k, v in payload.items() if k != "state"})

    def on_object_view_row_chosen(self, event: ObjectView.RowChosen) -> None:
        self.rl.open_ref(event.row)
