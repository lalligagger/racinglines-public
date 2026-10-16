"""Data: the change log, the schema, a read-only SQL console, and `racinglines data pull`."""
from __future__ import annotations

from ..widgets import CButton, CInput, CSelect  # noqa: F401

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input, RichLog, Select, Static, TabbedContent, TabPane, TextArea

from .. import fmt
from ..cli import run_cli
from ..widgets import DataGrid, ObjectView, PagedGrid
from .base import Pane


class SqlEditor(TextArea):
    BINDINGS = [Binding("ctrl+j", "run_query", "Run query", show=True)]

    class Run(Message):
        pass

    def action_run_query(self) -> None:
        self.post_message(self.Run())


class DataPane(Pane):
    DEFAULT_CSS = """
    DataPane DataGrid { height: 1fr; }
    DataPane #dt-schema-list { width: 2fr; }
    DataPane #dt-schema-cols { width: 1fr; padding: 0 0 0 1; }
    DataPane #dt-sql-text { height: 9; }
    DataPane #dt-pull-log { height: 1fr; border: round $panel; }
    """

    def compose(self) -> ComposeResult:
        with TabbedContent(id="dt-tabs"):
            with TabPane("Changes", id="dt-changes"):
                with Horizontal(classes="toolbar"):
                    yield CSelect([], id="dt-sport", prompt="All sports", allow_blank=True)
                yield PagedGrid("data_changes", columns=["at", "sport", "kind", "summary", "by", "detail"],
                                limit=100, empty="No changes logged.", id="dt-changes-grid")
            with TabPane("Schema", id="dt-schema"):
                with Horizontal():
                    yield DataGrid(id="dt-schema-list")
                    yield ObjectView(id="dt-schema-cols")
            with TabPane("SQL", id="dt-sql"):
                yield SqlEditor("SELECT id, competition, season, name, start_date\nFROM events\n"
                                "ORDER BY start_date DESC", id="dt-sql-text", language="sql"
                                if "sql" in TextArea().available_languages else None, show_line_numbers=True)
                with Horizontal(classes="toolbar"):
                    yield CButton("Run query", id="dt-sql-run", variant="primary")
                    yield Static("Read only, 10 s limit. ctrl+j runs. users and orders are not readable.",
                                 classes="muted hint")
                yield DataGrid(id="dt-sql-grid", page_size=200)
            with TabPane("Pull", id="dt-pull"):
                with Horizontal(classes="toolbar"):
                    yield CSelect([], id="dt-pull-sport", prompt="Sport", allow_blank=True)
                    yield CInput(placeholder="Since: last, or YYYY-MM-DD (blank = everything)", id="dt-pull-since")
                    yield CSelect([("With exchange history", "all"), ("Race data and runs only", "no-markets")],
                                  value="all", allow_blank=False, id="dt-pull-what")
                with Horizontal(classes="toolbar"):
                    yield CButton("Pull into the local database", id="dt-pull-cli", variant="primary")
                    yield Static(Text("Runs racinglines data pull SPORT. A first pull wants a fresh database "
                                      "(racinglines db init).", style=fmt.DIM), classes="muted hint")
                yield RichLog(id="dt-pull-log", wrap=True, markup=False)

    def refresh_data(self) -> None:
        active = self.query_one("#dt-tabs", TabbedContent).active
        if active == "dt-schema":
            self.run(self._load_schema())
        elif active == "dt-sql":
            self.run(self._run_sql(0))
        elif active == "dt-pull":
            self.run(self._fill_sports())
        else:
            self.run(self._load_changes())

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content.id == "dt-tabs":
            event.stop()
            if self.loaded and event.pane.id != "dt-sql":
                self.refresh_data()

    async def _fill_sports(self) -> None:
        await self.rl.overview_ready()
        sports = self.rl.sports()
        for sel_id in ("#dt-sport", "#dt-pull-sport"):
            sel = self.query_one(sel_id, Select)
            if not getattr(sel, "_rl_filled", False):
                sel._rl_filled = True  # type: ignore[attr-defined]
                with self.prevent(Select.Changed):
                    sel.set_options([(s, s) for s in sports])

    async def _load_changes(self) -> None:
        await self._fill_sports()
        sport = self.query_one("#dt-sport", Select).value
        self.query_one("#dt-changes-grid", PagedGrid).set_args(sport=sport if isinstance(sport, str) else None)

    async def _load_schema(self) -> None:
        grid = self.query_one("#dt-schema-list", DataGrid)
        if grid.table.rows:
            return
        payload = await self.call("describe_schema", busy=grid)
        if payload is not None:
            table = fmt.first_table(payload, "tables")
            grid.load(table, columns=[c for c in ("table", "name", "what", "rows") if c in table.columns] or None)

    async def _run_sql(self, offset: int) -> None:
        query = self.query_one("#dt-sql-text", TextArea).text.strip()
        if not query:
            return
        grid = self.query_one("#dt-sql-grid", DataGrid)
        payload = await self.call("sql", busy=grid, query=query, limit=200, offset=offset)
        if payload is not None:
            grid.load(fmt.first_table(payload, "rows", "result"))

    async def _pull(self) -> None:
        log = self.query_one("#dt-pull-log", RichLog)
        sport = self.query_one("#dt-pull-sport", Select).value
        if not isinstance(sport, str):
            self.app.notify("Pick a sport to pull.", severity="warning")
            return
        since = self.query_one("#dt-pull-since", CInput).value.strip() or None
        args = ["data", "pull", sport] + (["--since", since] if since else [])
        if self.query_one("#dt-pull-what", Select).value == "no-markets":
            args.append("--no-markets")
        button = self.query_one("#dt-pull-cli", CButton)
        button.disabled = True
        log.write(f"$ racinglines {' '.join(args)}")
        try:
            code = await run_cli(args, log.write)
            log.write(f"exit {code}")
            if code:
                self.app.notify(f"racinglines data pull {sport} exited {code}; the log says why.", title="Pull",
                                severity="error")
        except OSError as exc:
            log.write(f"failed: {exc}")
            self.app.notify(str(exc), title="Pull", severity="error")
        finally:
            button.disabled = False

    def on_sql_editor_run(self, event: SqlEditor.Run) -> None:
        self.run(self._run_sql(0), group="sql")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "dt-sport":
            self.run(self._load_changes())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "dt-sql-run":
            self.run(self._run_sql(0), group="sql")
        elif bid == "dt-pull-cli":
            self.run(self._pull(), group="pull")

    def on_data_grid_page_request(self, event: DataGrid.PageRequest) -> None:
        if event.grid.id == "dt-sql-grid":
            self.run(self._run_sql(event.offset), group="sql")

    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        event.stop()
        if event.grid.id == "dt-schema-list":
            name = event.row.get("table") or event.row.get("name")
            if name:
                self.run(self._show_table(str(name)), group="schema")
        else:
            self.rl.open_ref(event.row)

    async def _show_table(self, name: str) -> None:
        view = self.query_one("#dt-schema-cols", ObjectView)
        payload = await self.call("describe_schema", busy=view, table=name)
        if payload is not None:
            await view.show(payload)
