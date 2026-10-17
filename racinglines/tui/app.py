"""The TUI: the web app's tabs (Home, Forecast, Markets, Events, Athletes, Trade, Paper, Lab, Sportsbook, Live, Data)
over one MCP session. `racinglines tui` builds the backend (racinglines/cli/tui.py)."""
from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.theme import Theme
from textual.widgets import Footer, Header, TabbedContent, TabPane
from textual.widgets._tabbed_content import ContentTabs

from .backend import Backend
from .modals import JobScreen, ModelRunScreen, PayloadScreen
from .panes.athletes import AthletesPane
from .panes.base import Pane
from .panes.data import DataPane
from .panes.events import EventScreen, EventsPane
from .panes.forecast import ForecastPane
from .panes.lab import LabPane
from .panes.live import LivePane
from .panes.markets import MarketsPane
from .panes.overview import OverviewPane
from .panes.paper import PaperPane
from .panes.sportsbook import SportsbookPane
from .panes.trade import TradePane

# Pit-wall asphalt with timing-screen signals; see fmt.py for what each colour means.
PITWALL = Theme(
    name="pitwall",
    primary="#8fa3bf",
    secondary="#b48cff",
    accent="#b48cff",
    warning="#f0b429",
    error="#ff5f57",
    success="#3fcf73",
    foreground="#e4e2dd",
    background="#191c21",
    surface="#21252b",
    panel="#2c313a",
    dark=True,
)

TABS: list[tuple[str, str, type[Pane]]] = [
    ("home", "Home", OverviewPane),
    ("forecast", "Forecast", ForecastPane),
    ("markets", "Markets", MarketsPane),
    ("events", "Events", EventsPane),
    ("athletes", "Athletes", AthletesPane),
    ("trade", "Trade", TradePane),
    ("paper", "Paper", PaperPane),
    ("lab", "Lab", LabPane),
    ("book", "Sportsbook", SportsbookPane),
    ("live", "Live", LivePane),
    ("data", "Data", DataPane),
]


class RacinglinesApp(App):
    TITLE = "racinglines"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("ctrl+r", "reconnect", "Reconnect"),
        Binding("question_mark", "help", "Keys"),
        *[Binding(str((i + 1) % 10), f"tab('{key}')", label, show=False) for i, (key, label, _) in enumerate(TABS[:10])],
    ]

    def __init__(self, backend: Backend, user: str | None = None, remote_warning: str | None = None) -> None:
        super().__init__()
        self.backend = backend
        self.remote_warning = remote_warning
        self.settings_user = user
        self.overview: dict | None = None
        self._overview_event = asyncio.Event()

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs"):
            for key, label, pane_cls in TABS:
                with TabPane(label, id=f"tab-{key}"):
                    yield pane_cls(id=f"pane-{key}")
        yield Footer()

    async def on_mount(self) -> None:
        self.register_theme(PITWALL)
        self.theme = "pitwall"
        self.sub_title = f"connecting to {self.backend.label}…"
        self.run_worker(self._connect(), exclusive=True, group="connect", exit_on_error=False)

    async def _connect(self) -> bool:
        """Start the backend; False (after telling the user) when it could not."""
        try:
            await self.backend.start()
        except Exception as exc:  # noqa: BLE001
            self.sub_title = "disconnected"
            self.notify(f"{exc}\nctrl+r tries again.", title="Can't reach racinglines", severity="error", timeout=15)
            return False
        name = getattr(self.backend, "server_name", None)
        self.sub_title = f"{name or 'connected'}  {self.backend.label}"
        if self.remote_warning:  # cli/remote.py's warning: the hosted data is for testing only
            self.notify(self.remote_warning.removeprefix("warning: "), title="Remote access", severity="warning",
                        timeout=20)
        self.query_one("#pane-home", Pane).ensure_loaded()
        # Other panes depend on the overview's competitions and users.
        if not self.query_one("#pane-home", Pane).loaded:
            self.query_one("#pane-home", Pane).ensure_loaded()
        self._active_pane().ensure_loaded()
        return True

    async def on_unmount(self) -> None:
        await self.backend.close()

    # ------------------------------------------------------------------ shared state
    def set_overview(self, payload: dict) -> None:
        self.overview = payload
        self._overview_event.set()

    async def overview_ready(self, timeout: float = 30) -> None:
        if self.overview is None:
            pane = self.query_one("#pane-home", Pane)
            pane.ensure_loaded()
            try:
                await asyncio.wait_for(self._overview_event.wait(), timeout)
            except asyncio.TimeoutError:
                pass

    def competitions(self) -> list[str]:
        return sorted(((self.overview or {}).get("sports") or {}).keys())

    def sports(self) -> list[str]:
        return sorted(set(((self.overview or {}).get("sports") or {}).values()))

    def users(self) -> list[dict]:
        return list((self.overview or {}).get("users") or [])

    # ------------------------------------------------------------------ navigation
    def _active_pane(self) -> Pane:
        active = self.query_one("#tabs", TabbedContent).active or "tab-home"
        return self.query_one(f"#pane-{active.removeprefix('tab-')}", Pane)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content.id == "tabs" and event.pane.id:
            pane = self.query_one(f"#pane-{event.pane.id.removeprefix('tab-')}", Pane)
            if getattr(self.backend, "connected", True):
                pane.ensure_loaded()

    def action_tab(self, key: str) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        # Focus left inside the old tab would pull it straight back to the front.
        tabs.query_one(ContentTabs).focus()
        tabs.active = f"tab-{key}"

    def action_refresh(self) -> None:
        if self.screen is self.screen_stack[0]:
            pane = self._active_pane()
            pane.loaded = True
            pane.refresh_data()

    def action_reconnect(self) -> None:
        async def go() -> None:
            await self.backend.close()
            if await self._connect():
                self._active_pane().refresh_data()

        self.run_worker(go(), exclusive=True, group="connect", exit_on_error=False)

    def action_help(self) -> None:
        keys = "  ".join(f"{(i + 1) % 10} {label}" for i, (_, label, _) in enumerate(TABS[:10]))
        self.notify(
            f"{keys}\nr refresh   ctrl+r reconnect   enter open row   [ ] page   esc back   ctrl+p commands",
            title="Keys", timeout=12,
        )

    def open_ref(self, row: dict[str, Any]) -> None:
        """Open whatever a row points at, using the field names the server actually sends.

        jobs: job_id; runs: run_id, result_run_id, last_run, run (an int), detail.run, or the id of
        a model-run row; events: event_id, or event_key / source_key (e.g. 2026-17, 20261002_mtb);
        athletes: athlete_id.
        """
        run = _first_int(row, "result_run_id", "run_id", "last_run")
        if run is None and isinstance(row.get("run"), (int, float)) and not row.get("athlete_id"):
            run = int(row["run"])
        if run is None and isinstance(row.get("detail"), dict):
            run = _first_int(row["detail"], "run", "run_id")
        if run is None and row.get("kind") in _RUN_KINDS and isinstance(row.get("id"), int) and "model" in row:
            run = int(row["id"])
        if row.get("job_id"):
            self.push_screen(JobScreen(int(row["job_id"])))
        elif row.get("athlete_id") and not row.get("run"):
            aid = int(row["athlete_id"])
            name = row.get("athlete") or row.get("subject") or f"Athlete #{aid}"
            self.push_screen(PayloadScreen(
                str(name), lambda: self.backend.call("get_athlete", athlete_id=aid, include="results,predictions")))
        elif run is not None:
            self.push_screen(ModelRunScreen(run))
        elif row.get("event_id"):
            self.push_screen(EventScreen(event_id=int(row["event_id"])))
        elif row.get("event_key") or (row.get("source_key") and row.get("competition")):
            self.push_screen(EventScreen(source_key=str(row.get("event_key") or row["source_key"])))
        elif row.get("athlete_id"):
            self.open_ref({k: v for k, v in row.items() if k != "run"})
        elif row:
            self.push_screen(PayloadScreen("Row", _const(row)))

    def trade_search(self, text: str) -> None:
        self.action_tab("trade")
        self.query_one("#pane-trade", TradePane).search(text)

    def show_lab_runs(self, kind: str | None) -> None:
        self.action_tab("lab")
        self.query_one("#pane-lab", LabPane).show_runs(kind)


_RUN_KINDS = {"forecast", "scenario", "diagnostic", "backtest", "sweep", "season_strategy", "season_checkpoints",
              "season_asof", "walk_forward", "candidate", "combo"}


def _first_int(row: dict, *keys: str) -> int | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def _const(value: Any):
    async def load() -> Any:
        return value
    return load
