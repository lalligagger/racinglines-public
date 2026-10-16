"""Pop-over screens: payload viewer, confirmation, job follower, market detail, model run."""
from __future__ import annotations

from .widgets import CButton, CInput, CSelect  # noqa: F401

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, Sparkline, Static

from . import fmt
from .panes.base import call_tool
from .widgets import KeyValues, ObjectView, rich_kv_table

Loader = Callable[[], Awaitable[Any]]


class Dialog(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss_none", "Close")]
    DEFAULT_CSS = """
    Dialog { align: center middle; }
    Dialog > #dialog {
        width: 92%; height: 88%; padding: 0 1;
        border: round $primary; background: $surface;
    }
    Dialog #dialog-title { text-style: bold; padding: 0 0 1 0; }
    Dialog .dialog-actions { height: auto; padding: 1 0 0 0; }
    Dialog .dialog-actions Button { margin: 0 1 0 0; }
    """

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class PayloadScreen(Dialog):
    """Shows whatever a tool returns; rows that name an athlete, event, run or job open them."""

    BINDINGS = [Binding("r", "reload", "Reload")]

    def __init__(self, title: str, loader: Loader) -> None:
        super().__init__()
        self.title_text = title
        self.loader = loader

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.title_text, id="dialog-title")
            yield ObjectView(id="payload")

    def on_mount(self) -> None:
        self.action_reload()

    def action_reload(self) -> None:
        self.run_worker(self._load(), exclusive=True, exit_on_error=False)

    async def _load(self) -> None:
        view = self.query_one("#payload", ObjectView)
        view.loading = True
        try:
            payload = await self.loader()
        except Exception as exc:  # noqa: BLE001
            self.app.notify(str(exc), severity="error")
            payload = None
        finally:
            view.loading = False
        await view.show(payload)

    def on_object_view_row_chosen(self, event: ObjectView.RowChosen) -> None:
        self.app.open_ref(event.row)  # type: ignore[attr-defined]


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("y", "confirm", "Confirm", show=False)]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical { width: 64; height: auto; padding: 1 2; border: round $warning; background: $surface; }
    ConfirmScreen Horizontal { height: auto; padding: 1 0 0 0; }
    ConfirmScreen Button { margin: 0 1 0 0; }
    """

    def __init__(self, title: str, body: Any, confirm_label: str) -> None:
        super().__init__()
        self.title_text = title
        self.body = body
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(Text(self.title_text, style="bold"))
            yield Static(self.body)
            with Horizontal():
                yield CButton(self.confirm_label, id="ok", variant="warning")
                yield CButton("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)


class JobScreen(Dialog):
    """Follows one Lab job until it finishes; opens the model run it saved."""

    def __init__(self, job_id: int) -> None:
        super().__init__()
        self.job_id = job_id
        self.job: dict = {}
        self._last_tail: list = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"Job #{self.job_id}", id="dialog-title")
            yield KeyValues(id="job-status")
            yield Static("", id="job-cmd")
            yield RichLog(id="job-log", wrap=True, markup=False, highlight=False)
            with Horizontal(classes="dialog-actions"):
                yield CButton("Cancel job", id="cancel-job", variant="error")
                yield CButton("Open model run", id="open-run", variant="primary", disabled=True)
                yield CButton("Close", id="close")

    def on_mount(self) -> None:
        self.run_worker(self.poll(), exclusive=True, exit_on_error=False)
        self.set_interval(3, self._tick)

    def _tick(self) -> None:
        if self.job.get("status") in (None, "queued", "running"):
            self.run_worker(self.poll(), exclusive=True, exit_on_error=False)

    async def poll(self) -> None:
        payload = await call_tool(self, "get_job", job_id=self.job_id, log_lines=200)
        if not isinstance(payload, dict):
            return
        job = payload.get("job", payload)
        self.job = job
        status = str(job.get("status", "?"))
        style = {"done": fmt.GREEN, "failed": fmt.RED, "running": fmt.PURPLE}.get(status, fmt.AMBER)
        pairs: list[tuple[str, Any]] = [("status", Text(status, style=f"bold {style}"))]
        for key in ("kind", "sport", "progress", "created_at", "started_at", "finished_at", "result_run_id"):
            if job.get(key) not in (None, ""):
                pairs.append((key.replace("_", " "), fmt.cell(key, job[key])))
        self.query_one("#job-status", KeyValues).show(pairs)
        if job.get("argv"):
            cmd = " ".join(str(a) for a in job["argv"]).replace("-m racinglines", "racinglines", 1)
            self.query_one("#job-cmd", Static).update(Text(f"$ {cmd}", style=fmt.DIM))
        # get_job sends the newest lines as log_tail; log_lines is how many the log holds.
        tail = job.get("log_tail") or payload.get("log_tail") or []
        if isinstance(tail, str):
            tail = tail.splitlines()
        total = job.get("log_lines")
        log = self.query_one("#job-log", RichLog)
        if tail != self._last_tail:
            log.clear()
            if isinstance(total, int) and total > len(tail):
                log.write(Text(f"… last {len(tail)} of {total} lines", style=fmt.DIM))
            for line in tail:
                log.write(Text(str(line), style=fmt.RED if status == "failed" and "Error" in str(line) else ""))
            self._last_tail = list(tail)
        self.query_one("#cancel-job", Button).disabled = status != "queued"
        self.query_one("#open-run", Button).disabled = not job.get("result_run_id")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "cancel-job":
            result = await call_tool(self, "cancel_job", job_id=self.job_id)
            if result is not None:
                self.app.notify(f"Job #{self.job_id} cancelled.")
                await self.poll()
        elif event.button.id == "open-run" and self.job.get("result_run_id"):
            self.app.push_screen(ModelRunScreen(int(self.job["result_run_id"])))


class ModelRunScreen(Dialog):
    """One model run, with a path box to drill into large metrics (e.g. metrics.weekends.3)."""

    def __init__(self, run_id: int) -> None:
        super().__init__()
        self.run_id = run_id

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"Model run #{self.run_id}", id="dialog-title")
            with Horizontal(classes="toolbar"):
                yield CInput(placeholder="Path, e.g. metrics.weekends or params.settings", id="run-path")
                yield CButton("Open path", id="open-path")
                yield CButton("Predictions", id="predictions")
                yield CButton("Diagnostic", id="diagnostic")
            yield Horizontal(id="run-keys", classes="toolbar")
            yield ObjectView(id="run-view")

    def on_mount(self) -> None:
        self.load(None)

    def load(self, path: str | None) -> None:
        self.run_worker(self._load("get_model_run", run_id=self.run_id, path=path), exclusive=True,
                        exit_on_error=False)

    async def _load(self, tool: str, **args: Any) -> None:
        view = self.query_one("#run-view", ObjectView)
        payload = await call_tool(self, tool, busy=view, **args)
        if payload is None:
            return
        if tool == "get_model_run" and not args.get("path") and isinstance(payload, dict):
            await self._show_metric_keys(payload)
        await view.show(payload)

    async def _show_metric_keys(self, payload: dict) -> None:
        """Large metrics come back as a key map with sizes: one button per part."""
        metrics = payload.get("metrics")
        keys = metrics.get("keys") if isinstance(metrics, dict) else None
        bar = self.query_one("#run-keys", Horizontal)
        await bar.remove_children()
        if not isinstance(keys, dict):
            return
        buttons = [Static(Text("metrics", style=fmt.DIM))]
        for key, size in keys.items():
            size_text = f" {size / 1000:.0f}k" if isinstance(size, (int, float)) and size >= 1000 else ""
            buttons.append(CButton(f"{key}{size_text}", name=f"metrics.{key}", classes="metric-key"))
        await bar.mount_all(buttons)
        payload["metrics"] = {k: v for k, v in metrics.items() if k not in ("keys", "_size", "note")} or None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.load(event.value.strip() or None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("metric-key") and event.button.name:
            self.query_one("#run-path", Input).value = event.button.name
            self.load(event.button.name)
        elif event.button.id == "open-path":
            self.load(self.query_one("#run-path", Input).value.strip() or None)
        elif event.button.id == "predictions":
            self.run_worker(self._load("get_predictions", run_id=self.run_id), exclusive=True, exit_on_error=False)
        elif event.button.id == "diagnostic":
            self.run_worker(self._load("get_diagnostic", run_id=self.run_id), exclusive=True, exit_on_error=False)

    def on_object_view_row_chosen(self, event: ObjectView.RowChosen) -> None:
        row = event.row
        if row.get("run_id") == self.run_id or row.get("run") == self.run_id:
            row = {k: v for k, v in row.items() if k not in ("run_id", "run")}
        self.app.open_ref(row)  # type: ignore[attr-defined]


VALUE_COLS = ("price", "last", "close", "mid", "p", "vwap", "yes", "bid", "ask")


def history_values(payload: Any) -> tuple[list[float], str]:
    """The price series from get_market_history, and a caption for it."""
    table = fmt.first_table(payload, "rows")
    if not table.rows:
        return [], (payload.get("note") if isinstance(payload, dict) else "") or "No stored prices in that window."
    numeric = [c for c in table.columns
               if any(isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool) for r in table.rows)]
    col = next((c for c in VALUE_COLS if c in numeric), None) or next(
        (c for c in numeric if not fmt.IDS.search(c) and "count" not in c), None)
    if col is None:
        return [], "No price column in the history."
    token_col = next((c for c in ("token", "token_id") if c in table.columns), None)
    rows = table.rows
    if token_col:  # one market only: the first token's series
        first = rows[0].get(token_col)
        rows = [r for r in rows if r.get(token_col) == first]
    values = [float(r[col]) for r in rows if isinstance(r.get(col), (int, float))]
    ts_col = next((c for c in table.columns if c in ("ts", "time", "bucket", "timestamp")), None)
    span = ""
    if ts_col and rows:
        span = f"  {str(rows[0].get(ts_col))[:16]} → {str(rows[-1].get(ts_col))[:16]}"
    return values, f"{col}, {len(values)} points{span}"


class MarketScreen(Dialog):
    """One outcome of the market matrix: every venue's numbers and the price history."""

    def __init__(self, row: dict, race_id: int | None, venue: str = "polymarket") -> None:
        super().__init__()
        self.row = row
        self.race_id = race_id
        self.venue = venue

    def compose(self) -> ComposeResult:
        subject = self.row.get("subject") or "?"
        kind = self.row.get("kind") or ""
        with Vertical(id="dialog"):
            yield Static(f"{subject}   {kind}", id="dialog-title")
            yield Static(rich_kv_table([(k, v) for k, v in self.row.items() if not k.endswith("_token")]))
            yield Static("", id="spark-caption", classes="muted")
            yield Sparkline([], id="spark")
            with Horizontal(classes="dialog-actions"):
                yield CButton(f"Search Trade for {self.row.get('subject') or 'this'}", id="trade", variant="primary")
                yield CButton("Athlete", id="athlete", disabled=not self.row.get("athlete_id"))
                yield CButton("Close", id="close")

    def on_mount(self) -> None:
        self.run_worker(self.load_history(), exit_on_error=False)

    async def load_history(self) -> None:
        token = self.row.get(f"{self.venue}_token")
        args: dict[str, Any] = {"series": "prices", "resample": "1h", "limit": 200}
        if token:
            args["tokens"] = str(token)
        elif self.row.get("athlete_id"):  # an exact key only: the server's `subject` is an ILIKE match
            args.update(race_id=self.race_id, kind=self.row.get("kind"), athlete_id=self.row["athlete_id"],
                        exchange=self.row.get("exchange"))
        else:
            self.query_one("#spark-caption", Static).update(
                Text("no exact key for this outcome (no token, no athlete_id): no history shown.", style=fmt.DIM))
            return
        if self.row.get("result") is None:  # upcoming: the last week, not the week before the race
            now = datetime.now(timezone.utc)
            args.update(start=(now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M"), end=now.strftime("%Y-%m-%dT%H:%M"))
        payload = await call_tool(self, "get_market_history", busy=self.query_one("#spark"), **args)
        values, caption = history_values(payload) if payload is not None else ([], "History unavailable.")
        fair = self.row.get("fair")
        extra = f"   our fair {fair * 100:.1f}%" if isinstance(fair, (int, float)) else ""
        last = f"   last {values[-1] * 100:.1f}%" if values else ""
        self.query_one("#spark-caption", Static).update(Text(f"{self.venue} {caption}{last}{extra}", style=fmt.DIM))
        self.query_one("#spark", Sparkline).data = values

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.dismiss(None)
        elif event.button.id == "trade":
            self.dismiss(None)
            self.app.trade_search(str(self.row.get("subject") or ""))  # type: ignore[attr-defined]
        elif event.button.id == "athlete":
            self.app.open_ref({"athlete_id": self.row["athlete_id"]})  # type: ignore[attr-defined]


def order_summary(market: dict, side: str, action: str, shares: int, limit: float, est: dict) -> Group:
    pairs: list[tuple[str, Any]] = [
        ("market", market.get("question") or market.get("subject")),
        ("venue", market.get("exchange")),
        ("order", Text(f"{action} {shares} {side.upper()} at ≤ {limit:.2f}" if action == "buy"
                       else f"{action} {shares} {side.upper()} at ≥ {limit:.2f}", style="bold")),
        ("expected fill", f"{est['shares']} shares, avg {est['avg']:.3f}" if est["shares"] else "none at that limit"),
        ("expected F$", fmt.money(est["notional"])),
    ]
    return Group(rich_kv_table(pairs), Text(
        "\nImmediate-or-cancel against the latest recorded book; the rest is cancelled. "
        "Paper F$ only — nothing reaches an exchange.", style=fmt.DIM))
