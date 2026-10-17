"""Sportsbook: paste a book's lines as TOML, map them, price them against model and market, settle."""
from __future__ import annotations

from ..widgets import CButton, CInput, CSelect  # noqa: F401

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, TextArea

from ..layout import Divider
from ..widgets import ObjectView
from .base import Pane

TEMPLATE = '''# A sportsbook's lines (format: docs/sportsbook/slips.md). Edit, then Map, Price or Settle.
[book]
venue = "my-book"
event = "2026-18"
sport = "f1"
odds = "decimal"

[[lines]]
kind = "race_win"
driver = "Max Verstappen"
odds = 6.5

[[lines]]
kind = "race_podium"
driver = "Charles Leclerc"
odds = 2.9

[[lines]]
kind = "race_h2h"
driver = "George Russell"
opponent = "Kimi Antonelli"
odds = 1.95
'''


class SportsbookPane(Pane):
    DEFAULT_CSS = """
    SportsbookPane #sb-body { height: 1fr; }
    SportsbookPane #sb-editor { width: 2fr; }
    SportsbookPane #sb-result { width: 3fr; padding: 0 0 0 1; }
    SportsbookPane TextArea { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(classes="toolbar"):
            yield CButton("Map lines", id="sb-map")
            yield CButton("Price", id="sb-price", variant="primary")
            yield CButton("Settle", id="sb-settle")
            yield CInput(placeholder="Pin model runs, e.g. 9929,10010", id="sb-runs")
            yield CButton("Market kinds", id="sb-kinds")
        with Horizontal(id="sb-body"):
            with Vertical(id="sb-editor"):
                yield TextArea(TEMPLATE, id="sb-text", show_line_numbers=True, soft_wrap=False)
            yield Divider("book.h")
            yield ObjectView(id="sb-result")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        book = self.query_one("#sb-text", TextArea).text
        bid = event.button.id
        if bid == "sb-kinds":
            self.run(self._show("list_kinds"))
        elif bid == "sb-map":
            self.run(self._show("map_book", book=book))
        elif bid == "sb-settle":
            self.run(self._show("settle_book", book=book))
        elif bid == "sb-price":
            runs = [int(x) for x in self.query_one("#sb-runs", Input).value.replace(" ", "").split(",") if x.isdigit()]
            self.run(self._show("price_book", book=book, run_ids=runs or None))

    async def _show(self, tool: str, **args) -> None:
        view = self.query_one("#sb-result", ObjectView)
        payload = await self.call(tool, busy=view, **args)
        if payload is not None:
            await view.show(payload)

    def on_object_view_row_chosen(self, event: ObjectView.RowChosen) -> None:
        self.rl.open_ref(event.row)
