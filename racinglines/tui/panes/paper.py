"""Paper trading: a strategy account's weekend-by-weekend record, its positions and its signals."""
from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Select, Sparkline, Static, TabbedContent, TabPane

from .. import fmt
from ..widgets import CInput, CSelect, DataGrid, KeyValues, PagedGrid
from .base import Pane

VENUES = [("Polymarket", "polymarket"), ("Kalshi", "kalshi"), ("Private book", "private"), ("All venues", "all")]
SIGNAL_STATUS = [(s, s) for s in ("new", "alerted", "expired", "filled_paper")]
SIGNAL_ACTION = [(a, a) for a in ("buy", "sell", "quote", "pull", "fill")]

RECORD_COLS = ["event_key", "event_name", "start_date", "sport", "profile", "strategy", "signals", "taken",
               "fills", "positions", "settled", "pnl", "venue"]
POSITION_COLS = ["event_key", "venue", "kind", "subject", "yes_shares", "no_shares", "cash", "mark", "bid", "ask",
                 "outcome", "quote_state", "pnl", "updated_at"]
SIGNAL_COLS = ["signal_ts", "event_key", "stage", "kind", "subject", "action", "side", "shares", "limit_price",
               "fair", "price", "edge", "target_cost", "status", "strategy"]


def position_totals(payload: Any) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    for t in (payload or {}).get("totals") or []:
        value = fmt.money(float(t.get("sum") or 0), signed=True)
        value.append(f"  {t.get('count', 0)} positions", style=fmt.DIM)
        pairs.append((t.get("venue"), value))
    return pairs or [("totals", "none")]


def signal_cell(col: str, value: Any, row: dict) -> Any:
    if col == "action" and isinstance(value, str):
        return Text(value, style=fmt.GREEN if value == "buy" else fmt.RED if value == "sell" else None)
    if col == "shares" and isinstance(value, (int, float)):
        return f"{value:,.1f}"
    return fmt.cell(col, value)


class PaperPane(Pane):
    DEFAULT_CSS = """
    PaperPane #pp-equity { height: 5; margin: 0 0 0 0; }
    PaperPane #pp-record-grid { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(classes="toolbar"):
            yield CSelect([], id="pp-user", prompt="Account", allow_blank=True)
            yield CSelect(VENUES, value="polymarket", allow_blank=False, id="pp-venue")
            yield CInput(placeholder="Sport", id="pp-sport", classes="narrow")
            yield CInput(placeholder="Event key", id="pp-event", classes="narrow")
        with TabbedContent(id="pp-tabs"):
            with TabPane("Track record", id="pp-record"):
                yield KeyValues(id="pp-record-sum")
                yield Static(id="pp-equity-caption", classes="muted")
                yield Sparkline([], id="pp-equity")
                yield DataGrid(id="pp-record-grid", columns=RECORD_COLS, empty="No weekends traded yet.")
            with TabPane("Positions", id="pp-positions"):
                yield PagedGrid("list_positions", keys=("positions",), columns=POSITION_COLS, limit=100,
                                summary=position_totals, empty="No paper positions.", id="pp-positions-grid")
            with TabPane("Signals", id="pp-signals"):
                with Horizontal(classes="toolbar"):
                    yield CSelect(SIGNAL_STATUS, id="pp-sig-status", prompt="Any status", allow_blank=True)
                    yield CSelect(SIGNAL_ACTION, id="pp-sig-action", prompt="Any action", allow_blank=True)
                yield PagedGrid("list_signals", columns=SIGNAL_COLS, cell=signal_cell, limit=100,
                                empty="No signals for this account.", id="pp-signals-grid")

    def refresh_data(self) -> None:
        self.run(self._load())

    def _val(self, sel_id: str) -> str | None:
        v = self.query_one(sel_id, Select).value
        return v if isinstance(v, str) else None

    async def _load(self) -> None:
        user_sel = self.query_one("#pp-user", Select)
        if not getattr(self, "_users_loaded", False):
            self._users_loaded = True
            await self.rl.overview_ready()
            users = self.rl.users()
            with self.prevent(Select.Changed):
                user_sel.set_options([(f"{u['username']}  {u.get('profile') or u.get('role') or ''}".strip(),
                                       u["username"]) for u in users])
                default = self.rl.settings_user or ("taker" if any(u["username"] == "taker" for u in users) else None)
                if default:
                    user_sel.value = default
        user = self._val("#pp-user")
        if not user:
            return
        venue = self._val("#pp-venue") or "polymarket"
        sport = self.query_one("#pp-sport", CInput).value.strip() or None
        event_key = self.query_one("#pp-event", CInput).value.strip() or None
        self.query_one("#pp-positions-grid", PagedGrid).set_args(
            user=user, venue=None if venue == "all" else venue, event_key=event_key)
        self.query_one("#pp-signals-grid", PagedGrid).set_args(
            user=user, event_key=event_key, status=self._val("#pp-sig-status"), action=self._val("#pp-sig-action"))
        await self._load_record(user, venue, sport)

    async def _load_record(self, user: str, venue: str, sport: str | None) -> None:
        grid = self.query_one("#pp-record-grid", DataGrid)
        payload = await self.call("track_record", busy=grid, user=user, venue=venue, sport=sport)
        if not isinstance(payload, dict):
            return
        table = fmt.first_table(payload, "rows")
        grid.load(table, columns=[c for c in RECORD_COLS if c in table.columns] or None)
        self.query_one("#pp-record-sum", KeyValues).show([
            ("weekends", payload.get("weekends")),
            ("weekends up", payload.get("up")),
            ("P&L", fmt.money(float(payload.get("pnl") or 0), signed=True)),
        ], title=f"{user} on {venue}")
        # Equity curve: cumulative P&L in weekend order.
        rows = sorted(table.rows, key=lambda r: str(r.get("start_date") or r.get("event_key") or ""))
        running, curve = 0.0, []
        for r in rows:
            running += float(r.get("pnl") or 0)
            curve.append(running)
        shown = f"{len(rows)} of {table.total} weekends" if table.total and table.total > len(rows) else f"{len(rows)} weekends"
        caption = Text(f"Cumulative P&L, {shown}", style=fmt.DIM)
        if curve:
            caption.append(f"   low {min(curve):+,.0f}   high {max(curve):+,.0f}   now ", style=fmt.DIM)
            caption.append_text(fmt.money(curve[-1], signed=True))
        self.query_one("#pp-equity-caption", Static).update(caption)
        self.query_one("#pp-equity", Sparkline).data = curve or [0]

    def on_select_changed(self, event: Select.Changed) -> None:
        self.refresh_data()

    def on_input_submitted(self, event: CInput.Submitted) -> None:
        self.refresh_data()

    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        event.stop()
        self.rl.open_ref(event.row)
