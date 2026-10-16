"""Home: what the database holds, what races are next, which forecasts are live."""
from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import Static

from .. import fmt
from ..widgets import DataGrid, KeyValues
from .base import Pane


class OverviewPane(Pane):
    DEFAULT_CSS = """
    OverviewPane #ov-grid { grid-size: 2; grid-gutter: 0 2; height: 1fr; }
    OverviewPane DataGrid { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield KeyValues(id="ov-counts")
        with Grid(id="ov-grid"):
            for key, title in (("upcoming", "Next races"), ("forecasts", "Live forecasts"),
                               ("seasons", "Seasons"), ("model_runs", "Model runs"),
                               ("market_links", "Linked markets"), ("venues", "Venues")):
                grid = DataGrid(id=f"ov-{key}")
                grid.border_title = title
                yield grid
        yield Static(id="ov-hint", classes="muted")

    def refresh_data(self) -> None:
        self.run(self._load())

    async def _load(self) -> None:
        payload = await self.call("overview", busy=self.query_one("#ov-grid"))
        if not isinstance(payload, dict):
            return
        self.rl.set_overview(payload)
        counts = payload.get("row_counts") or {}
        self.query_one("#ov-counts", KeyValues).show(
            [(k.replace("_", " "), f"{v:,}") for k, v in counts.items()], title=self.rl.backend.label)
        seasons = fmt.to_table(payload.get("seasons") or [])
        seasons.rows = sorted(seasons.rows, key=lambda r: (-(r.get("season") or 0), r.get("competition") or ""))
        tables: dict[str, Any] = {
            "upcoming": payload.get("upcoming"),
            "forecasts": [{"competition": f.get("competition"), "category": f.get("category_name"),
                           "run": f.get("id"), "data_through": f.get("data_through"),
                           "created_at": f.get("created_at")} for f in payload.get("forecasts") or []],
            "seasons": seasons,
            "model_runs": payload.get("model_runs"),
            "market_links": payload.get("market_links"),
            "venues": payload.get("venues"),
        }
        for key, data in tables.items():
            self.query_one(f"#ov-{key}", DataGrid).load(data if data is not None else [])

    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        event.stop()
        row = event.row
        if event.grid.id == "ov-forecasts" and row.get("run"):
            self.rl.open_ref({"run_id": row["run"]})
        elif event.grid.id == "ov-model_runs":
            self.rl.show_lab_runs(kind=row.get("kind"))
        else:
            self.rl.open_ref(row)
