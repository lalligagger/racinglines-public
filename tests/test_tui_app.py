"""The TUI headless against tests/tui_fixtures.py: every tab, every drill-down, orders, the Lab's forms.
TUI_SHOTS=<dir> saves an SVG screenshot of each screen there."""
import asyncio
import os

import pytest

from racinglines.tui.app import TABS, RacinglinesApp
from racinglines.tui.modals import JobScreen, MarketScreen, ModelRunScreen, PayloadScreen
from racinglines.tui.panes.events import EventScreen
from racinglines.tui.widgets import DataGrid
from tui_fixtures import FakeBackend

SHOTS = os.environ.get("TUI_SHOTS")


def shot(app, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        app.save_screenshot(f"{SHOTS}/{name}")


async def settle(pilot, n=3):
    for _ in range(n):
        await pilot.pause(0.05)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def test_every_tab_loads_and_drills():
    asyncio.run(_test_every_tab_loads_and_drills())


async def _test_every_tab_loads_and_drills():
    backend = FakeBackend()
    app = RacinglinesApp(backend)
    async with app.run_test(size=(160, 48)) as pilot:
        await settle(pilot)
        assert app.overview is not None
        for key, _, _ in TABS:
            app.action_tab(key)
            await settle(pilot)
            shot(app, "{key}.svg")
        tools = {t for t, _ in backend.calls}
        for needed in ("overview", "get_forecast", "list_markets", "list_events", "search_athletes",
                       "fantasy_balance", "fantasy_markets", "fantasy_positions", "track_record",
                       "list_positions", "list_signals", "list_jobs", "list_live_events", "data_changes"):
            assert needed in tools, needed

        # Markets: open an outcome -> history sparkline
        app.action_tab("markets")
        await settle(pilot)
        grid = app.query_one("#mv-grid", DataGrid)
        assert len(grid.table.rows) == 2
        grid.focus()
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, MarketScreen)
        shot(app, "market-detail.svg")
        await pilot.press("escape")

        # Events -> event screen with markets tab
        app.action_tab("events")
        await settle(pilot)
        app.query_one("#ev-grid", DataGrid).focus()
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, EventScreen)
        shot(app, "event.svg")
        await pilot.press("escape")

        # Trade: pick market, estimate, confirm order
        app.action_tab("trade")
        await settle(pilot)
        app.query_one("#tr-markets", DataGrid).focus()
        await pilot.press("enter")
        await settle(pilot)
        pane = app.query_one("#pane-trade")
        assert pane.book.get("market_link_id") == 40423
        assert app.query_one("#tr-limit").value == "0.50"
        shot(app, "trade-selected.svg")
        app.query_one("#tr-place").press()
        await settle(pilot)
        shot(app, "trade-confirm.svg")
        await pilot.press("y")
        await settle(pilot)
        orders = [a for t, a in backend.calls if t == "fantasy_order"]
        assert orders and orders[0]["shares"] == 10 and orders[0]["limit_price"] == 0.5
        assert orders[0]["side"] == "yes" and orders[0]["action"] == "buy" and orders[0]["client_key"]

        # Lab: new job form -> queue -> job screen
        app.action_tab("lab")
        await settle(pilot)
        from textual.widgets import TabbedContent
        app.query_one("#lab-tabs", TabbedContent).active = "lab-new"
        await settle(pilot)
        app.query_one("#lab-job-type").value = "f1_sweep"
        await settle(pilot)
        shot(app, "lab-form.svg")
        app.query_one("#lab-queue").press()
        await settle(pilot)
        run_job = [a for t, a in backend.calls if t == "run_job"]
        assert run_job and run_job[0]["job_type"] == "f1_sweep"
        assert run_job[0].get("params", {}).get("year") == "2026"
        assert "settings" not in run_job[0].get("params", {})  # untouched settings stay default
        assert isinstance(app.screen, JobScreen)
        await settle(pilot)
        shot(app, "job.svg")
        # The real sample job failed: no run to open, and its log tail is shown with the CLI command.
        assert app.screen.query_one("#open-run").disabled
        log_text = "\n".join(str(line.text) for line in app.screen.query_one("#job-log").lines)
        assert "last 2 of 28 lines" in log_text and "conflicting option string" in log_text
        assert "racinglines backtest walk-forward" in str(app.screen.query_one("#job-cmd").render())
        await pilot.press("escape")

        # Forecast athlete -> athlete payload
        app.action_tab("forecast")
        await settle(pilot)
        app.query_one("#fc-race-grid", DataGrid).focus()
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, PayloadScreen)
        await pilot.press("escape")

        # Data: SQL
        app.action_tab("data")
        await settle(pilot)
        app.query_one("#dt-tabs", TabbedContent).active = "dt-sql"
        await settle(pilot)
        app.query_one("#dt-sql-run").press()
        await settle(pilot)
        assert any(t == "sql" for t, _ in backend.calls)
        shot(app, "sql.svg")


def test_stale_book_blocks_orders():
    asyncio.run(_test_stale_book_blocks_orders())


async def _test_stale_book_blocks_orders():
    app = RacinglinesApp(FakeBackend(book_age_min=40))
    async with app.run_test(size=(160, 48)) as pilot:
        await settle(pilot)
        app.action_tab("trade")
        await settle(pilot)
        app.query_one("#tr-markets", DataGrid).focus()
        await pilot.press("enter")
        await settle(pilot)
        assert app.query_one("#tr-place").disabled
        assert "min old" in str(app.query_one("#tr-est").render())


def test_sweep_settings_only_send_changes():
    asyncio.run(_test_sweep_settings_only_send_changes())


async def _test_sweep_settings_only_send_changes():
    backend = FakeBackend()
    app = RacinglinesApp(backend)
    async with app.run_test(size=(160, 48)) as pilot:
        await settle(pilot)
        app.show_lab_runs(None)
        await settle(pilot)
        lab = app.query_one("#pane-lab")
        lab._switch("lab-new")
        await settle(pilot)
        app.query_one("#lab-job-type").value = "f1_sweep"
        await settle(pilot)
        from racinglines.tui.panes.lab import JobForm, KnobField
        fields = {f.name_: f for f in app.query(KnobField)}
        fields["sims"].query_one(".knob-input").value = "8000"
        fields["min_edge_by_kind"].query_one(".knob-input").value = "race_win=0.07"
        fields["taker_stages"].query_one(".knob-input").deselect("after FP1")
        params = app.query_one(JobForm).params()
        assert params["settings"] == {"sims": 8000, "min_edge_by_kind": {"race_win": 0.07},
                                      "taker_stages": ["pre-weekend"]}
        assert params["year"] == "2026"



def test_real_shapes_navigate_and_page():
    asyncio.run(_test_real_shapes_navigate_and_page())


async def _test_real_shapes_navigate_and_page():
    from textual.widgets import TabbedContent
    from racinglines.tui.panes.lab import EdgeConfigScreen, KnobField
    from racinglines.tui.widgets import PagedGrid

    backend = FakeBackend()
    app = RacinglinesApp(backend)
    async with app.run_test(size=(160, 48)) as pilot:
        await settle(pilot)

        # Paper: paged positions/signals, totals strip, equity curve from cumulative P&L
        app.action_tab("paper")
        await settle(pilot)
        assert app.query_one("#pp-equity").data == [-22.33, -22.33 + 333.69]
        signals = app.query_one("#pp-signals-grid", PagedGrid)
        signals.grid.action_page(1)
        await settle(pilot)
        sig_calls = [a for t, a in backend.calls if t == "list_signals"]
        assert sig_calls[-1]["offset"] == 100 and sig_calls[-1]["user"] == "taker"
        shot(app, "paper.svg")

        # Track-record rows open their event by event_key
        app.query_one("#pp-record-grid", DataGrid).focus()
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, EventScreen) and app.screen.source_key == "2025-01"
        await pilot.press("escape")

        # Lab: diagnostics row fills the run box with last_run
        lab = app.query_one("#pane-lab")
        app.action_tab("lab")
        await settle(pilot)
        lab._switch("lab-diag")
        await settle(pilot)
        app.query_one("#lab-diag-grid", PagedGrid).grid.focus()
        await pilot.press("enter")
        await settle(pilot)
        assert app.query_one("#lab-diag-run").value == "9956"

        # Candidates open their own model run
        lab._switch("lab-cand")
        await settle(pilot)
        app.query_one("#lab-cand-grid", PagedGrid).grid.focus()
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, ModelRunScreen) and app.screen.run_id == 9951
        # metric keys became buttons; one opens its path
        keys = [b.name for b in app.screen.query(".metric-key")]
        assert keys == ["metrics.scores", "metrics.totals", "metrics.weekends"]
        app.screen.query_one(".metric-key").press()
        await settle(pilot)
        assert [a.get("path") for t, a in backend.calls if t == "get_model_run"][-1] == "metrics.scores"
        await pilot.press("escape")

        # Edge Finder: row -> config screen -> prefilled sweep form
        lab._switch("lab-edge")
        await settle(pilot)
        app.query_one("#lab-edge-grid", PagedGrid).grid.focus()
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, EdgeConfigScreen)
        shot(app, "edge-config.svg")
        app.screen.query_one("#sweep").press()
        await settle(pilot)
        assert app.query_one("#lab-tabs", TabbedContent).active == "lab-new"
        from racinglines.tui.panes.lab import JobForm
        params = app.query_one(JobForm).params()
        assert params["settings"]["taker_stages"] == ["after FP1", "after FP2"]
        assert params["settings"]["sims"] == 16000 and params["settings"]["min_edge"] == 0.1
        assert params["settings"]["variant"] == "gridq+pretrain+reset" and params["settings"]["venue"] == "kalshi"
        assert params["year"] == "2026"
        shot(app, "edge-prefill.svg")

        # Data: change-log row opens the run named in its detail; SQL pages without a total
        app.action_tab("data")
        await settle(pilot)
        app.query_one("#dt-changes-grid", PagedGrid).grid.focus()
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, ModelRunScreen) and app.screen.run_id == 10011
        await pilot.press("escape")

        # Trade: an empty order book of orders shows an empty state, not a blank box
        app.action_tab("trade")
        await settle(pilot)
        orders = app.query_one("#tr-orders", DataGrid)
        assert orders.row_count == 1 and not orders.table.rows


def test_paging_text_without_total():
    from racinglines.tui import fmt
    from racinglines.tui.widgets import DataGrid
    grid = DataGrid()
    grid.table = fmt.to_table({"columns": ["id"], "rows": [{"id": 1}, {"id": 2}], "total": None,
                               "offset": 0, "next_offset": 2})
    assert "] for more" in grid.paging_text()
