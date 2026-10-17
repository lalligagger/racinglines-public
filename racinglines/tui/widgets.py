"""Shared widgets: a paged data grid, a generic payload viewer, and a key/value strip."""
from __future__ import annotations

from typing import Any, Callable

from rich.console import Group
from rich.pretty import Pretty
from rich.table import Table as RichTable
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import DataTable, Static

from . import fmt

CellFn = Callable[[str, Any, dict], Any]


class DataGrid(DataTable):
    """A DataTable that loads tool payloads, keeps each row's dict, and pages with [ and ]."""

    BINDINGS = [
        Binding("]", "page(1)", "Next page", show=False),
        Binding("[", "page(-1)", "Prev page", show=False),
        Binding("enter", "open_row", "Open", show=False),
    ]

    class PageRequest(Message):
        def __init__(self, grid: "DataGrid", offset: int) -> None:
            super().__init__()
            self.grid = grid
            self.offset = offset

    class RowChosen(Message):
        """Enter or click on a row: carries the row's own dict."""

        def __init__(self, grid: "DataGrid", row: dict) -> None:
            super().__init__()
            self.grid = grid
            self.row = row

    def __init__(self, *, columns: list[str] | None = None, cell: CellFn | None = None,
                 page_size: int = 50, empty: str = "Nothing here yet.", **kwargs: Any) -> None:
        super().__init__(cursor_type="row", zebra_stripes=True, cursor_foreground_priority="renderable", **kwargs)
        self.fixed_columns_spec = columns
        self.cell_fn = cell
        self.page_size = page_size
        self.empty_text = empty
        self.table: fmt.Table = fmt.Table([], [])

    def load(self, data: Any, columns: list[str] | None = None) -> fmt.Table:
        table = data if isinstance(data, fmt.Table) else fmt.to_table(data)
        self.table = table
        cols = columns or self.fixed_columns_spec or table.columns
        self.clear(columns=True)
        if not table.rows:
            self.add_column("", key="_empty")
            self.add_row(Text(table.note or self.empty_text, style=fmt.DIM), key="_empty")
            self.border_subtitle = ""
            return table
        for col in cols:
            self.add_column(fmt.label(col), key=col)
        for i, row in enumerate(table.rows):
            cells = [
                self.cell_fn(col, row.get(col), row) if self.cell_fn else fmt.cell(col, row.get(col))
                for col in cols
            ]
            self.add_row(*cells, key=str(i))
        self.border_subtitle = self.paging_text()
        return table

    def paging_text(self) -> str:
        t = self.table
        n = len(t.rows)
        if t.total is None and (t.next_offset is not None or t.offset):
            more = "  ] for more" if t.next_offset is not None else ""
            return f"{t.offset + 1}–{t.offset + n}{more}{'  [ back' if t.offset else ''}"
        if t.total is None or (t.total == n and t.offset == 0):
            return f"{n} rows"
        start = t.offset + 1 if n else 0
        hint = "  [ ] to page" if (t.next_offset is not None or t.offset) else ""
        return f"{start}–{t.offset + n} of {t.total}{hint}"

    def current_row(self) -> dict | None:
        if not self.table.rows or self.cursor_row < 0 or self.cursor_row >= len(self.table.rows):
            return None
        key = self.coordinate_to_cell_key((self.cursor_row, 0)).row_key.value
        return self.table.rows[int(key)] if key is not None and key.isdigit() else None

    def action_page(self, direction: int) -> None:
        t = self.table
        if direction > 0 and t.next_offset is not None:
            self.post_message(self.PageRequest(self, t.next_offset))
        elif direction < 0 and t.offset > 0:
            self.post_message(self.PageRequest(self, max(0, t.offset - self.page_size)))

    def action_open_row(self) -> None:
        row = self.current_row()
        if row is not None:
            self.post_message(self.RowChosen(self, row))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table is not self:
            return
        event.stop()
        key = event.row_key.value
        if key is not None and key.isdigit() and int(key) < len(self.table.rows):
            self.post_message(self.RowChosen(self, self.table.rows[int(key)]))


class KeyValues(Static):
    """A one-or-two line strip of label/value pairs."""

    def show(self, pairs: list[tuple[str, Any]], title: str | None = None) -> None:
        text = Text()
        if title:
            text.append(title, style="bold")
            text.append("   ")
        for i, (key, value) in enumerate(pairs):
            if i:
                text.append("   ")
            text.append(f"{key} ", style=fmt.DIM)
            text.append_text(value if isinstance(value, Text) else Text(str(value) if value is not None else "–"))
        self.update(text)


class ObjectView(VerticalScroll):
    """Any tool payload, laid out: scalars as a strip, every table as a grid, nested dicts by path.

    The tools' shapes vary and grow; this keeps every screen working with whatever comes back.
    """

    class RowChosen(Message):
        def __init__(self, view: "ObjectView", path: str, row: dict) -> None:
            super().__init__()
            self.view = view
            self.path = path
            self.row = row

    DEFAULT_CSS = """
    ObjectView { height: 1fr; }
    ObjectView .ov-title { color: $text-muted; margin: 1 0 0 0; }
    ObjectView .ov-scalars { margin: 0 0 0 0; }
    ObjectView DataGrid { height: auto; max-height: 24; }
    ObjectView .ov-pretty { margin: 0 0 1 0; }
    """

    def __init__(self, payload: Any = None, *, max_depth: int = 3, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.payload = payload
        self.max_depth = max_depth
        self._grids: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        if self.payload is not None:
            yield from self._build(self.payload)

    async def show(self, payload: Any) -> None:
        self.payload = payload
        await self.remove_children()
        await self.mount_all(list(self._build(payload)))

    def _build(self, payload: Any) -> list:
        widgets: list = []
        self._grids = {}
        if payload is None:
            return [Static(Text("Nothing here yet.", style=fmt.DIM))]
        if fmt.is_table(payload):
            widgets += self._table_widgets("", payload)
            return widgets
        if not isinstance(payload, dict):
            return [Static(Pretty(payload), classes="ov-pretty")]
        self._walk(payload, "", 0, widgets)
        if not widgets:
            widgets.append(Static(Text("Empty.", style=fmt.DIM)))
        return widgets

    def _walk(self, obj: dict, path: str, depth: int, out: list) -> None:
        scalars: list[tuple[str, Any]] = []
        nested: list[tuple[str, Any]] = []
        for key, value in obj.items():
            if key in {"hint", "sources"} and depth == 0:
                continue
            if fmt.is_table(value) or isinstance(value, dict):
                nested.append((key, value))
            elif isinstance(value, list):
                if value and all(isinstance(v, (str, int, float)) for v in value):
                    scalars.append((key, ", ".join(map(str, value))))
                elif value:
                    nested.append((key, value))
            else:
                scalars.append((key, fmt.cell(key, value)))
        if scalars:
            strip = KeyValues(classes="ov-scalars")
            strip.show(scalars, title=path or None)
            out.append(strip)
        for key, value in nested:
            sub = f"{path}.{key}" if path else key
            if fmt.is_table(value):
                out += self._table_widgets(sub, value)
            elif isinstance(value, dict) and depth < self.max_depth:
                self._walk(value, sub, depth + 1, out)
            else:
                out.append(Static(Text(sub, style="bold"), classes="ov-title"))
                out.append(Static(Pretty(value, max_length=20, max_depth=3), classes="ov-pretty"))
        if isinstance(obj.get("sources"), dict) and depth == 0 and obj["sources"].get("text"):
            out.append(Static(Text(obj["sources"]["text"], style=fmt.DIM), classes="ov-title"))

    def _table_widgets(self, path: str, value: Any) -> list:
        table = fmt.to_table(value)
        grid = DataGrid()
        grid.border_title = path or None
        self._grids[str(id(grid))] = path
        grid.load(table)
        out: list = []
        if path:
            out.append(Static(Text(path, style="bold"), classes="ov-title"))
        if table.note:
            out.append(Static(Text(table.note, style=fmt.DIM)))
        out.append(grid)
        return out

    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        event.stop()
        self.post_message(self.RowChosen(self, self._grids.get(str(id(event.grid)), ""), event.row))


def rich_kv_table(pairs: list[tuple[str, Any]]) -> RichTable:
    table = RichTable.grid(padding=(0, 2))
    table.add_column(style=fmt.DIM)
    table.add_column()
    for key, value in pairs:
        table.add_row(fmt.label(key), value if isinstance(value, Text) else fmt.cell(key, value))
    return table


def row_detail(row: dict) -> Group:
    return Group(rich_kv_table(list(row.items())))


# Compact controls: one line each, so filter bars don't eat the screen.
from textual.widgets import Button as _Button, Input as _Input, Select as _Select  # noqa: E402


class CInput(_Input):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("compact", True)
        super().__init__(*args, **kwargs)


class CSelect(_Select):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("compact", True)
        super().__init__(*args, **kwargs)


class CButton(_Button):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("compact", True)
        super().__init__(*args, **kwargs)


class PagedGrid(Vertical):
    """A DataGrid bound to one list tool: set its args, it loads and pages through the server."""

    DEFAULT_CSS = "PagedGrid { height: 1fr; } PagedGrid > DataGrid { height: 1fr; }"

    def __init__(self, tool: str, *, keys: tuple[str, ...] = (), columns: list[str] | None = None,
                 cell: CellFn | None = None, limit: int = 100, empty: str = "Nothing here yet.",
                 summary: Callable[[Any], list[tuple[str, Any]]] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.tool = tool
        self.keys = keys
        self.columns = columns
        self.limit = limit
        self.summary = summary
        self.args: dict[str, Any] = {}
        self.payload: Any = None
        self._grid = DataGrid(cell=cell, page_size=limit, empty=empty)

    def compose(self) -> ComposeResult:
        if self.summary is not None:
            yield KeyValues()
        yield self._grid

    @property
    def grid(self) -> DataGrid:
        return self._grid

    def set_args(self, **args: Any) -> None:
        self.args = args
        self.load(0)

    def load(self, offset: int = 0, quiet: bool = False) -> None:
        self.run_worker(self._load(offset, quiet), exclusive=True, group="paged", exit_on_error=False)

    async def _load(self, offset: int, quiet: bool) -> None:
        from .panes.base import call_tool

        payload = await call_tool(self, self.tool, busy=None if quiet else self._grid,
                                  limit=self.limit, offset=offset, **self.args)
        if payload is None:
            return
        self.payload = payload
        row = self._grid.cursor_row
        table = fmt.first_table(payload, *self.keys)
        cols = [c for c in self.columns if c in table.columns] if self.columns and table.columns else None
        self._grid.load(table, columns=cols or None)
        if quiet and 0 <= row < self._grid.row_count:
            self._grid.move_cursor(row=row)
        if self.summary is not None:
            self.query_one(KeyValues).show(self.summary(payload))

    def on_data_grid_page_request(self, event: DataGrid.PageRequest) -> None:
        event.stop()
        self.load(event.offset)
