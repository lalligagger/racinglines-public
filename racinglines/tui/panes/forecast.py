"""Live fair prices: the next races' top probabilities and the championship."""
from __future__ import annotations

from ..widgets import CButton, CInput, CSelect  # noqa: F401

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Select, Static

from .. import fmt
from ..widgets import DataGrid, KeyValues
from .base import Pane, int_or_none

RACE_COLS = ["athlete", "win_prob", "podium_prob", "top10_prob", "make_final_prob", "exp_points"]
STANDING_COLS = ["athlete", "current_points", "exp_points", "p10_p90", "champion_prob", "top3_prob", "exp_rank"]


class ForecastPane(Pane):
    DEFAULT_CSS = """
    ForecastPane #fc-body { height: 1fr; }
    ForecastPane #fc-race, ForecastPane #fc-standings { width: 1fr; height: 1fr; }
    ForecastPane DataGrid { height: 1fr; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.forecasts: list[dict] = []
        self._comps_loaded = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="toolbar"):
            yield CSelect([], id="fc-comp", prompt="Competition", allow_blank=True)
            yield CSelect([], id="fc-cat", prompt="Category", allow_blank=True)
            yield CInput("10", placeholder="Top", id="fc-top", classes="narrow")
        yield KeyValues(id="fc-run")
        with Horizontal(id="fc-body"):
            with Vertical(id="fc-race"):
                yield CSelect([], id="fc-target", prompt="Race", allow_blank=True)
                yield DataGrid(id="fc-race-grid", columns=RACE_COLS, cell=self._cell)
            with Vertical(id="fc-standings"):
                yield Static("Championship", classes="section")
                yield DataGrid(id="fc-standings-grid", columns=STANDING_COLS, cell=self._cell)
        yield Static(id="fc-sources", classes="muted")

    def on_mount(self) -> None:
        self.query_one("#fc-race-grid").border_title = "Next race"

    def refresh_data(self) -> None:
        self.run(self._load())

    async def _load(self) -> None:
        comp_select = self.query_one("#fc-comp", Select)
        if not self._comps_loaded:
            self._comps_loaded = True
            await self.rl.overview_ready()
            comps = [f.get("competition") for f in (self.rl.overview or {}).get("forecasts", [])]
            comps = list(dict.fromkeys(c for c in comps if c)) or self.rl.competitions()
            comp_select.set_options([(c, c) for c in comps])
            if comps:
                with self.prevent(Select.Changed):
                    comp_select.value = "f1_wdc" if "f1_wdc" in comps else comps[0]
        comp = comp_select.value if isinstance(comp_select.value, str) else None
        cat_value = self.query_one("#fc-cat", Select).value
        payload = await self.call(
            "get_forecast", busy=self.query_one("#fc-body"), competition=comp,
            category=cat_value if isinstance(cat_value, str) else None,
            top=int_or_none(self.query_one("#fc-top", Input).value) or 10,
        )
        if not isinstance(payload, dict):
            return
        self.forecasts = payload.get("forecasts") or []
        cats = [(f["run"].get("category_name") or f["run"].get("category"), f["run"].get("category"))
                for f in self.forecasts if f.get("run")]
        cat_select = self.query_one("#fc-cat", Select)
        if cats and not isinstance(cat_value, str):
            with self.prevent(Select.Changed):
                cat_select.set_options(cats)
        self._show(0)

    def _show(self, index: int) -> None:
        if not self.forecasts:
            self.query_one("#fc-run", KeyValues).show([("forecast", "none for this competition")])
            return
        fc = self.forecasts[min(index, len(self.forecasts) - 1)]
        run = fc.get("run") or {}
        self.query_one("#fc-run", KeyValues).show(
            [("run", f"#{run.get('id')}"), ("data through", run.get("data_through")),
             ("as of", fmt.cell("created_at", run.get("created_at"))), ("season", run.get("season")),
             ("code", run.get("code_version"))],
            title=run.get("competition_name") or run.get("competition"))
        races = fc.get("next_races") or []
        target = self.query_one("#fc-target", Select)
        with self.prevent(Select.Changed):
            target.set_options([(f"{str(r.get('start_date'))[:10]}  {r.get('event')}", str(i))
                                for i, r in enumerate(races)])
            if races:
                target.value = "0"
        self._show_race(races[0] if races else None)
        self.query_one("#fc-standings-grid", DataGrid).load(fc.get("standings") or [])
        sources = (fc.get("sources") or {}).get("text") or ""
        self.query_one("#fc-sources", Static).update(sources)

    def _show_race(self, race: dict | None) -> None:
        grid = self.query_one("#fc-race-grid", DataGrid)
        grid.border_title = (race or {}).get("event") or "Next race"
        rows = (race or {}).get("top") or []
        cols = [c for c in RACE_COLS if any(r.get(c) is not None for r in rows)] or RACE_COLS
        grid.load(rows, columns=cols)

    def _cell(self, col: str, value: Any, row: dict) -> Any:
        if col == "p10_p90":
            lo, hi = row.get("points_p10"), row.get("points_p90")
            return f"{lo:.0f}–{hi:.0f}" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else "–"
        if col.endswith("_prob"):
            grid_rows = [r for r in (self.query_one("#fc-race-grid", DataGrid).table.rows
                                     + self.query_one("#fc-standings-grid", DataGrid).table.rows)
                         if col in r]
            best = value is not None and value == max((r.get(col) or 0) for r in grid_rows)
            return fmt.prob_bar(value, width=6, best=best)
        if col in ("exp_points", "current_points", "points_p10", "points_p90", "exp_rank"):
            return f"{value:,.1f}" if isinstance(value, (int, float)) else fmt.cell(col, value)
        return fmt.cell(col, value)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "fc-comp":
            self.query_one("#fc-cat", Select).clear()
            self.refresh_data()
        elif event.select.id == "fc-cat":
            self.refresh_data()
        elif event.select.id == "fc-target" and isinstance(event.value, str) and self.forecasts:
            races = self.forecasts[0].get("next_races") or []
            i = int(event.value)
            self._show_race(races[i] if i < len(races) else None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "fc-top":
            self.refresh_data()

    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        event.stop()
        self.rl.open_ref(event.row)
