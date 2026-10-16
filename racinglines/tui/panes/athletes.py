"""Drivers and riders: search by name, open one for results and prediction history."""
from __future__ import annotations

from ..widgets import CButton, CInput, CSelect  # noqa: F401

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input

from .. import fmt
from ..widgets import DataGrid
from .base import Pane


class AthletesPane(Pane):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="toolbar"):
            yield CInput(placeholder="Search drivers and riders by name", id="at-q")
        yield DataGrid(id="at-grid")

    def refresh_data(self) -> None:
        self.run(self._load(self.query_one("#at-q", Input).value.strip() or None))

    async def _load(self, q: str | None) -> None:
        payload = await self.call("search_athletes", busy=self.query_one("#at-grid"), q=q, limit=100)
        if payload is not None:
            self.query_one("#at-grid", DataGrid).load(fmt.first_table(payload, "athletes"))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "at-q" and (len(event.value) >= 3 or not event.value):
            self.refresh_data()

    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        event.stop()
        self.rl.open_ref({"athlete_id": event.row.get("id") or event.row.get("athlete_id")})
