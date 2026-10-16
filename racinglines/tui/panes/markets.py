"""The market matrix: our fair value against every venue, with the gap drawn as a bar."""
from __future__ import annotations

from ..widgets import CButton, CInput, CSelect  # noqa: F401

import re
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Select

from .. import fmt
from ..widgets import DataGrid, KeyValues
from .base import Pane, call_tool

VENUE_MID = re.compile(r"^(.+)_mid$")


def venues_in(columns: list[str]) -> list[str]:
    return [m.group(1) for c in columns if (m := VENUE_MID.match(c))]


class MarketsView(Vertical):
    """Reusable matrix for one event / race, or a competition's season-long markets."""

    DEFAULT_CSS = """
    MarketsView { height: 1fr; }
    MarketsView #mv-grid { height: 1fr; }
    """

    def __init__(self, event_id: int | None = None, competition: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.event_id = event_id
        self.competition = competition
        self.race_id: int | None = None
        self.venues: list[str] = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="toolbar"):
            yield CInput(placeholder="Kinds, e.g. race_win,race_podium (blank = all)", id="mv-kinds")
            yield CSelect([("polymarket", "polymarket")], value="polymarket", allow_blank=False,
                         id="mv-venue", prompt="Gap against")
            yield CButton("Load", id="mv-load", variant="primary")
        yield KeyValues(id="mv-head")
        yield KeyValues(id="mv-fresh")
        yield DataGrid(id="mv-grid", cell=self._cell)

    def set_scope(self, event_id: int | None = None, competition: str | None = None) -> None:
        self.event_id, self.competition = event_id, competition
        self.load()

    def load(self, offset: int = 0) -> None:
        self.run_worker(self._load(offset), exclusive=True, group="markets", exit_on_error=False)

    async def _load(self, offset: int) -> None:
        if self.event_id is None and not self.competition:
            return
        grid = self.query_one("#mv-grid", DataGrid)
        kinds = self.query_one("#mv-kinds", Input).value.strip() or None
        payload = await call_tool(
            self, "list_markets", busy=grid, event_id=self.event_id,
            competition=None if self.event_id else self.competition, kinds=kinds, limit=100, offset=offset,
        )
        if not isinstance(payload, dict):
            return
        self.race_id = payload.get("race_id")
        head = [(k, payload.get(k)) for k in ("title", "competition", "season", "status", "race_start")
                if payload.get(k) is not None]
        pricing = payload.get("pricing") or {}
        if pricing.get("run_id"):
            head.append(("priced by run", f"#{pricing['run_id']} {pricing.get('source') or ''}".strip()))
        if pricing.get("cadence"):
            head.append(("cadence", pricing["cadence"]))
        self.query_one("#mv-head", KeyValues).show(head)
        fresh = (payload.get("freshness") or {}).get("venues") or []
        pairs = []
        for v in fresh:
            age = v.get("age_hours")
            status = fmt.stale(v.get("stale"), v.get("reason"))
            if age is not None and not v.get("stale"):
                status.append(f" {age:.1f}h", style=fmt.DIM)
            pairs.append((v.get("venue"), status))
        self.query_one("#mv-fresh", KeyValues).show(pairs, title="prices")

        table = fmt.first_table(payload, "outcomes")
        self.venues = venues_in(table.columns)
        venue_select = self.query_one("#mv-venue", Select)
        current = venue_select.value
        if self.venues:
            venue_select.set_options([(v, v) for v in self.venues])
            venue_select.value = current if current in self.venues else self.venues[0]
        cols = ["kind", "subject"]
        if any(r.get("detail") for r in table.rows):
            cols.append("detail")
        cols.append("fair")
        cols += [f"{v}_quote" for v in self.venues]
        cols += ["fair_vs_market", "gap"]
        if any(r.get("result") is not None for r in table.rows):
            cols.append("result")
        cols.append("volume")
        grid.load(table, columns=cols)

    def _primary(self) -> str:
        value = self.query_one("#mv-venue", Select).value
        return str(value) if isinstance(value, str) else (self.venues[0] if self.venues else "polymarket")

    def _cell(self, col: str, value: Any, row: dict) -> Any:
        venue = self._primary()
        if col.endswith("_quote"):
            v = col[: -len("_quote")]
            mid, bid, ask = row.get(f"{v}_mid"), row.get(f"{v}_bid"), row.get(f"{v}_ask")
            if mid is None and bid is None and ask is None:
                return Text("–", style=fmt.DIM)
            text = Text(f"{mid * 100:.1f}" if mid is not None else "–")
            b = f"{bid * 100:.0f}" if bid is not None else "–"
            a = f"{ask * 100:.0f}" if ask is not None else "–"
            text.append(f" {b}/{a}", style=fmt.DIM)
            if row.get(f"{v}_closed"):
                text.append(" closed", style=fmt.AMBER)
            return text
        if col == "fair_vs_market":
            return fmt.gap_bar(row.get(f"gap_{venue}"))
        if col == "gap":
            return fmt.signed_points(row[f"gap_{venue}"]) if row.get(f"gap_{venue}") is not None else Text("–", style=fmt.DIM)
        if col == "volume":
            vol = row.get(f"{venue}_volume")
            return fmt.cell("volume", float(vol)) if vol is not None else Text("–", style=fmt.DIM)
        if col == "fair":
            return fmt.pct(value)
        if col == "result":
            if value is None:
                return Text("–", style=fmt.DIM)
            won = value in (1, True, "won", "yes", 1.0)
            return Text("won" if won else "lost" if value in (0, False, "lost", "no", 0.0) else str(value),
                        style=fmt.GREEN if won else fmt.DIM)
        return fmt.cell(col, value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "mv-load":
            event.stop()
            self.load()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "mv-kinds":
            event.stop()
            self.load()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "mv-venue":
            event.stop()
            grid = self.query_one("#mv-grid", DataGrid)
            if grid.table.rows:
                grid.load(grid.table, columns=[str(c.key.value) for c in grid.columns.values()])

    def on_data_grid_page_request(self, event: DataGrid.PageRequest) -> None:
        event.stop()
        self.load(event.offset)

    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        event.stop()
        from ..modals import MarketScreen

        self.app.push_screen(MarketScreen(event.row, self.race_id, self._primary()))


class MarketsPane(Pane):
    """Pick an upcoming weekend or a season-long competition; the matrix fills below."""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="toolbar"):
            yield CSelect([], id="mk-scope", prompt="Event or competition", allow_blank=True)
            yield CInput(placeholder="or event id", id="mk-event-id", classes="narrow")
        yield MarketsView(id="mk-view")

    def refresh_data(self) -> None:
        self.run(self._load_scopes())

    async def _load_scopes(self) -> None:
        events = await self.call("list_events", status="scheduled", limit=40)
        rows = sorted(fmt.first_table(events, "events").rows, key=lambda r: str(r.get("start_date") or ""))
        options: list[tuple[str, str]] = []
        for r in rows:
            name = str(r.get("name") or r.get("title") or r.get("source_key"))
            options.append((f"{str(r.get('start_date') or '')[:10]}  {r.get('competition', '')}  {name[:48]}",
                            f"event:{r.get('id', r.get('event_id'))}"))
        for comp in self.rl.competitions():
            options.append((f"Season-long  {comp}", f"comp:{comp}"))
        select = self.query_one("#mk-scope", Select)
        select.set_options(options)
        if options and select.is_blank():
            select.value = options[0][1]

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "mk-scope" or not isinstance(event.value, str):
            return
        kind, _, ident = event.value.partition(":")
        view = self.query_one("#mk-view", MarketsView)
        if kind == "event":
            view.set_scope(event_id=int(ident))
        else:
            view.set_scope(competition=ident)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "mk-event-id" and event.value.strip().isdigit():
            self.query_one("#mk-view", MarketsView).set_scope(event_id=int(event.value.strip()))
