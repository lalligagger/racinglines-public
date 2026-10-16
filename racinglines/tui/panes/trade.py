"""Trade with F$: the Trade page. Markets, the recorded book, IOC orders, positions, leaderboard."""
from __future__ import annotations

from ..widgets import CButton, CInput, CSelect  # noqa: F401

import uuid
from datetime import datetime, timezone
from typing import Any

from rich.console import Group
from rich.table import Table as RichTable
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Select, Static, Switch, TabbedContent, TabPane

from .. import fmt
from ..modals import ConfirmScreen, order_summary
from ..widgets import DataGrid, KeyValues
from .base import Pane, float_or_none, int_or_none

MARKET_COLS = ["exchange", "kind", "subject", "event", "start_date", "bid", "ask", "book_ts"]


def walk_book(book: dict, side: str, action: str, shares: int, limit: float) -> dict:
    """What an IOC order would fill against the recorded book, at most 10 levels."""
    if action == "buy":
        levels = sorted(book.get(f"{side}_asks") or [], key=lambda lv: lv[0])
        ok = (lambda p: p <= limit + 1e-9)
    else:
        levels = sorted(book.get(f"{side}_bids") or [], key=lambda lv: -lv[0])
        ok = (lambda p: p >= limit - 1e-9)
    left, filled, notional = shares, 0, 0.0
    for price, size in levels[:10]:
        if left <= 0 or not ok(price):
            break
        take = min(left, int(size))
        filled += take
        notional += take * price
        left -= take
    return {"shares": filled, "notional": notional, "avg": notional / filled if filled else 0.0}


def book_age_minutes(book: dict) -> float | None:
    ts = book.get("ts")
    if not ts:
        return None
    try:
        when = datetime.fromisoformat(str(ts).replace(" ", "T").replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() / 60


def ladder(book: dict, side: str) -> RichTable:
    bids = sorted(book.get(f"{side}_bids") or [], key=lambda lv: -lv[0])[:10]
    asks = sorted(book.get(f"{side}_asks") or [], key=lambda lv: lv[0])[:10]
    t = RichTable(box=None, padding=(0, 1), expand=True, show_edge=False)
    t.add_column("size", justify="right", style=fmt.DIM)
    t.add_column("bid", justify="right", style=fmt.GREEN)
    t.add_column("ask", justify="left", style=fmt.RED)
    t.add_column("size", justify="left", style=fmt.DIM)
    for i in range(max(len(bids), len(asks), 1)):
        b = bids[i] if i < len(bids) else None
        a = asks[i] if i < len(asks) else None
        t.add_row(f"{b[1]:,.0f}" if b else "", f"{b[0]:.2f}" if b else "",
                  f"{a[0]:.2f}" if a else "", f"{a[1]:,.0f}" if a else "")
    return t


class TradePane(Pane):
    DEFAULT_CSS = """
    TradePane #tr-top { height: 1fr; }
    TradePane #tr-left { width: 2fr; }
    TradePane #tr-right { width: 1fr; min-width: 46; padding: 0 0 0 1; }
    TradePane #tr-markets { height: 1fr; }
    TradePane #tr-book { height: 1fr; border: round $panel; padding: 0 1; }
    TradePane .form-row { height: auto; }
    TradePane .form-row > * { width: 1fr; }
    TradePane #tr-place { width: 100%; }
    TradePane #tr-tabs { height: 14; }
    TradePane #tr-tabs DataGrid { height: 1fr; }
    TradePane .switch-row { height: auto; }
    TradePane .switch-row Label { padding: 1 1 0 0; }
    TradePane #tr-est { height: auto; margin: 0 0 1 0; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.market: dict | None = None
        self.book: dict = {}
        self.max_stake = 100.0
        self.max_age_min = 15.0
        self.cash = 0.0

    def compose(self) -> ComposeResult:
        yield KeyValues(id="tr-balance")
        with Horizontal(id="tr-top"):
            with Vertical(id="tr-left"):
                yield CInput(placeholder="Search question, driver or event", id="tr-q")
                yield DataGrid(id="tr-markets", columns=MARKET_COLS)
            with Vertical(id="tr-right"):
                yield Static("Pick a market to see its book.", id="tr-book")
                with Horizontal(classes="form-row"):
                    yield CSelect([("YES", "yes"), ("NO", "no")], value="yes", allow_blank=False, id="tr-side")
                    yield CSelect([("Buy", "buy"), ("Sell", "sell")], value="buy", allow_blank=False, id="tr-action")
                with Horizontal(classes="form-row"):
                    yield CInput("10", placeholder="Shares", id="tr-shares", type="integer")
                    yield CInput(placeholder="Limit 0.01–0.99", id="tr-limit", type="number")
                yield Static(id="tr-est")
                yield CButton("Place order", id="tr-place", variant="primary", disabled=True)
        with TabbedContent(id="tr-tabs"):
            with TabPane("Positions", id="tr-pos-tab"):
                with Horizontal(classes="switch-row"):
                    yield Label("Open only")
                    yield Switch(value=True, id="tr-open-only")
                yield DataGrid(id="tr-positions")
            with TabPane("Orders", id="tr-orders-tab"):
                yield DataGrid(id="tr-orders")
            with TabPane("Leaderboard", id="tr-board-tab"):
                yield DataGrid(id="tr-board")

    def on_mount(self) -> None:
        self.query_one("#tr-markets").border_title = "Tradable markets"
        self.set_interval(20, self._auto_book)

    # ---------------------------------------------------------------- loading
    def refresh_data(self) -> None:
        self.run(self._load_all())

    async def _load_all(self) -> None:
        await self._load_balance()
        await self._load_markets(0)
        await self._load_account()

    async def _load_balance(self) -> None:
        bal = await self.call("fantasy_balance")
        if not isinstance(bal, dict):
            return
        self.cash = float(bal.get("cash") or 0)
        self.query_one("#tr-balance", KeyValues).show([
            ("total", fmt.money(bal.get("total") or 0, prefix="F$")),
            ("cash", fmt.money(self.cash, prefix="F$")),
            ("open at mark", fmt.money(float(bal.get("held") or 0))),
            ("open trades", bal.get("open")),
            ("hand P&L", fmt.money(float(bal.get("manual_pnl") or 0), signed=True)),
            ("strategy P&L", fmt.money(float(bal.get("strategy_pnl") or 0), signed=True)),
        ], title=f"@{bal.get('user', '?')}")

    async def _load_markets(self, offset: int) -> None:
        q = self.query_one("#tr-q", Input).value.strip() or None
        payload = await self.call("fantasy_markets", busy=self.query_one("#tr-markets"), q=q, limit=50, offset=offset)
        if isinstance(payload, dict):
            self.max_stake = float(payload.get("max_stake") or self.max_stake)
            self.max_age_min = float(payload.get("max_age_min") or self.max_age_min)
            self.query_one("#tr-markets", DataGrid).load(fmt.first_table(payload, "markets"))

    async def _load_account(self) -> None:
        open_only = self.query_one("#tr-open-only", Switch).value
        for grid_id, tool, args in (("tr-positions", "fantasy_positions", {"open_only": open_only}),
                                    ("tr-orders", "fantasy_orders", {}),
                                    ("tr-board", "fantasy_leaderboard", {})):
            grid = self.query_one(f"#{grid_id}", DataGrid)
            payload = await self.call(tool, busy=grid, limit=100, **args)
            if payload is not None:
                grid.load(fmt.first_table(payload, "positions", "orders", "leaderboard"))

    async def _load_book(self) -> None:
        if not self.market:
            return
        book = await self.call("fantasy_book", market_link_id=int(self.market["market_link_id"]))
        if isinstance(book, dict):
            self.book = book
            self._render_book()

    def _auto_book(self) -> None:
        if self.market and self.display and self.is_attached:
            self.run(self._load_book(), group="book")

    # ---------------------------------------------------------------- rendering
    def _side(self) -> str:
        return str(self.query_one("#tr-side", Select).value)

    def _action(self) -> str:
        return str(self.query_one("#tr-action", Select).value)

    def _render_book(self) -> None:
        m = self.market or {}
        side = self._side()
        title = Text(str(m.get("question") or m.get("subject") or ""), style="bold")
        meta = Text(f"{m.get('exchange', '')}  #{m.get('market_link_id')}  {side.upper()} book", style=fmt.DIM)
        age = book_age_minutes(self.book)
        if age is not None:
            meta.append(f"  {age:.0f} min old", style=fmt.AMBER if age > self.max_age_min else fmt.DIM)
        warn = Text()
        if age is not None and age > self.max_age_min:
            warn = Text(f"Orders are refused on a book older than {self.max_age_min:.0f} min.", style=fmt.AMBER)
        self.query_one("#tr-book", Static).update(Group(title, meta, warn, ladder(self.book, side)))
        self._estimate()

    def _suggest_limit(self) -> None:
        side, action = self._side(), self._action()
        levels = self.book.get(f"{side}_asks" if action == "buy" else f"{side}_bids") or []
        if levels:
            best = min(lv[0] for lv in levels) if action == "buy" else max(lv[0] for lv in levels)
            self.query_one("#tr-limit", Input).value = f"{best:.2f}"

    def _order_inputs(self) -> tuple[int | None, float | None]:
        return (int_or_none(self.query_one("#tr-shares", Input).value),
                float_or_none(self.query_one("#tr-limit", Input).value))

    def _estimate(self) -> dict | None:
        est_widget = self.query_one("#tr-est", Static)
        button = self.query_one("#tr-place", Button)
        shares, limit = self._order_inputs()
        problem = None
        if not self.market:
            problem = "Pick a market."
        elif not shares or shares <= 0:
            problem = "Shares must be a whole number above 0."
        elif limit is None or not 0.01 <= limit <= 0.99:
            problem = "Limit must be between 0.01 and 0.99."
        if problem:
            est_widget.update(Text(problem, style=fmt.DIM))
            button.disabled = True
            return None
        assert shares is not None and limit is not None
        age = book_age_minutes(self.book)
        if age is not None and age > self.max_age_min:
            est_widget.update(Text(f"The book is {age:.0f} min old; wait for a fresh one (r refreshes).",
                                   style=fmt.AMBER))
            button.disabled = True
            return None
        est = walk_book(self.book, self._side(), self._action(), shares, limit)
        line = Text()
        if est["shares"]:
            line.append(f"Fills ~{est['shares']} at avg {est['avg']:.3f} = F${est['notional']:,.2f}")
        else:
            line.append("Nothing in the book at that limit; the order would be cancelled.", style=fmt.AMBER)
        if self._action() == "buy":
            worst = shares * limit
            if worst > self.max_stake:
                line.append(f"\nOver the F${self.max_stake:,.0f} per-order cap.", style=fmt.RED)
            if est["notional"] > self.cash:
                line.append(f"\nMore than your F${self.cash:,.2f} cash.", style=fmt.RED)
        est_widget.update(line)
        button.disabled = False
        return est

    # ---------------------------------------------------------------- events
    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        if event.grid.id != "tr-markets":
            event.stop()
            self.rl.open_ref(event.row)
            return
        event.stop()
        self.market = event.row
        self.book = {}
        self.run(self._select_market(), group="book")

    async def _select_market(self) -> None:
        await self._load_book()
        self._suggest_limit()
        self._estimate()

    def on_data_grid_page_request(self, event: DataGrid.PageRequest) -> None:
        if event.grid.id == "tr-markets":
            self.run(self._load_markets(event.offset))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tr-q":
            self.run(self._load_markets(0))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in ("tr-shares", "tr-limit"):
            self._estimate()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("tr-side", "tr-action") and self.market:
            self._render_book()
            self._suggest_limit()
            self._estimate()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "tr-open-only":
            self.run(self._load_account(), group="account")

    def search(self, text: str) -> None:
        self.query_one("#tr-q", Input).value = text
        self.loaded = True
        self.run(self._load_all())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tr-place":
            est = self._estimate()
            shares, limit = self._order_inputs()
            if est is None or self.market is None or shares is None or limit is None:
                return
            side, action = self._side(), self._action()
            body = order_summary(self.market, side, action, shares, limit, est)

            def confirmed(ok: bool | None) -> None:
                if ok:
                    self.run(self._place(side, action, shares, limit), group="order")

            self.app.push_screen(ConfirmScreen("Place order?", body, f"{action.title()} {side.upper()}"), confirmed)

    async def _place(self, side: str, action: str, shares: int, limit: float) -> None:
        assert self.market is not None
        result = await self.call(
            "fantasy_order", busy=self.query_one("#tr-place"), market_link_id=int(self.market["market_link_id"]),
            side=side, action=action, shares=shares, limit_price=round(limit, 2),
            client_key=f"tui-{uuid.uuid4().hex[:16]}",
        )
        if result is None:
            return
        order = result.get("order", result) if isinstance(result, dict) else {}
        status = order.get("status") or ("refused" if order.get("reason") else "placed")
        filled = order.get("filled") or order.get("filled_shares") or order.get("shares_filled")
        parts = [f"{status}"]
        if filled is not None:
            parts.append(f"filled {filled}")
        if order.get("avg_price") is not None:
            parts.append(f"avg {float(order['avg_price']):.3f}")
        if order.get("fee") is not None:
            parts.append(f"fee {float(order['fee']):.2f}")
        if order.get("reason"):
            parts.append(str(order["reason"]))
        self.app.notify(", ".join(parts), title="Order", severity="error" if order.get("reason") else "information")
        await self._load_balance()
        await self._load_book()
        await self._load_account()
