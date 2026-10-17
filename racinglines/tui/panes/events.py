"""Race weekends: browse by sport, season and status; open one for results, predictions, markets."""
from __future__ import annotations

from ..widgets import CButton, CInput, CSelect  # noqa: F401

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Input, Select, Static, TabbedContent, TabPane

from .. import fmt
from ..widgets import DataGrid, KeyValues, ObjectView
from .base import Pane, call_tool, int_or_none
from .markets import MarketsView

EVENT_COLS = ["id", "source_key", "competition", "season", "name", "start_date", "status", "venue", "races"]


class EventsPane(Pane):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="toolbar"):
            yield CSelect([], id="ev-comp", prompt="All competitions", allow_blank=True)
            yield CInput(placeholder="Season", id="ev-season", classes="narrow")
            yield CSelect([("Completed", "completed"), ("Scheduled", "scheduled")], id="ev-status",
                         prompt="Any status", allow_blank=True)
            yield CInput(placeholder="Open by key, e.g. 2026-15", id="ev-key")
        yield DataGrid(id="ev-grid")

    def refresh_data(self, offset: int = 0) -> None:
        self.run(self._load(offset))

    async def _load(self, offset: int) -> None:
        comp = self.query_one("#ev-comp", Select)
        if not getattr(self, "_comps_loaded", False):
            self._comps_loaded = True
            await self.rl.overview_ready()
            with self.prevent(Select.Changed):
                comp.set_options([(c, c) for c in self.rl.competitions()])
        status = self.query_one("#ev-status", Select).value
        payload = await self.call(
            "list_events", busy=self.query_one("#ev-grid"),
            competition=comp.value if isinstance(comp.value, str) else None,
            season=int_or_none(self.query_one("#ev-season", Input).value),
            status=status if isinstance(status, str) else None, limit=50, offset=offset,
        )
        if payload is not None:
            table = fmt.first_table(payload, "events")
            cols = [c for c in EVENT_COLS if c in table.columns] or table.columns
            self.query_one("#ev-grid", DataGrid).load(table, columns=cols)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("ev-comp", "ev-status"):
            self.refresh_data()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ev-season":
            self.refresh_data()
        elif event.input.id == "ev-key" and event.value.strip():
            self.app.push_screen(EventScreen(source_key=event.value.strip()))

    def on_data_grid_page_request(self, event: DataGrid.PageRequest) -> None:
        self.refresh_data(event.offset)

    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        event.stop()
        row = event.row
        self.app.push_screen(EventScreen(event_id=row.get("id") or row.get("event_id"),
                                         source_key=row.get("source_key")))


class EventScreen(Screen):
    """One race weekend: classification, every stored prediction, and its market matrix."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]
    DEFAULT_CSS = """
    EventScreen { padding: 0 1; }
    EventScreen #es-title { text-style: bold; padding: 1 0 0 0; }
    EventScreen TabbedContent { height: 1fr; }
    """

    def __init__(self, event_id: int | None = None, source_key: str | None = None) -> None:
        super().__init__()
        self.event_id = int(event_id) if event_id is not None else None
        self.source_key = source_key
        self.event: dict = {}
        self._predictions_loaded = False

    def compose(self) -> ComposeResult:
        yield Static("Loading event…", id="es-title")
        yield KeyValues(id="es-head")
        with TabbedContent(id="es-tabs"):
            with TabPane("Races & results", id="es-results"):
                yield ObjectView(id="es-results-view")
            with TabPane("Predictions", id="es-predictions"):
                yield ObjectView(id="es-predictions-view")
            with TabPane("Markets", id="es-markets"):
                yield MarketsView(id="es-markets-view")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load(), exit_on_error=False)

    def _ident(self) -> dict[str, Any]:
        return {"event_id": self.event_id} if self.event_id is not None else {"source_key": self.source_key}

    async def _load(self) -> None:
        view = self.query_one("#es-results-view", ObjectView)
        payload = await call_tool(self, "get_event", busy=view, include="results", **self._ident())
        if not isinstance(payload, dict):
            self.query_one("#es-title", Static).update("Event not found.")
            return
        event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
        self.event = event
        self.event_id = event.get("id") or event.get("event_id") or self.event_id
        self.query_one("#es-title", Static).update(str(event.get("name") or event.get("title") or "Event"))
        self.query_one("#es-head", KeyValues).show(
            [(k.replace("_", " "), event.get(k)) for k in ("id", "source_key", "competition", "season", "start_date",
                                                           "status", "venue") if event.get(k) is not None])
        await view.show({k: v for k, v in payload.items() if k != "event"} if "event" in payload else payload)
        if self.event_id is not None:
            self.query_one("#es-markets-view", MarketsView).set_scope(event_id=int(self.event_id))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "es-predictions" and not self._predictions_loaded:
            self._predictions_loaded = True
            self.run_worker(self._load_predictions(), exit_on_error=False)

    async def _load_predictions(self) -> None:
        view = self.query_one("#es-predictions-view", ObjectView)
        payload = await call_tool(self, "get_event", busy=view, include="predictions", **self._ident())
        if isinstance(payload, dict):
            await view.show({k: v for k, v in payload.items() if k in ("predictions", "races") or "pred" in k}
                            or payload)

    def on_object_view_row_chosen(self, event: ObjectView.RowChosen) -> None:
        self.app.open_ref(event.row)  # type: ignore[attr-defined]
