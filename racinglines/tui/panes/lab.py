"""The Lab: queue simulations from the server's own job catalog, follow jobs, and read results."""
from __future__ import annotations

from ..widgets import CButton, CInput, CSelect  # noqa: F401

import json
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (Button, Collapsible, Input, Label, Select, SelectionList, Static, TabbedContent,
                             TabPane, TextArea)

from .. import fmt
from ..modals import JobScreen, ModelRunScreen, PayloadScreen
from ..widgets import DataGrid, KeyValues, ObjectView, PagedGrid, rich_kv_table
from textual.widgets import Select as _Select
from .base import Pane, float_or_none, int_or_none

EDGE_COLS = ["strategy_label", "venue", "pnl", "roi", "volume", "weekends", "up", "avg", "best", "worst",
             "drawdown", "consistency", "fills", "markout", "run_id", "settings_key", "config"]
CAND_COLS = ["id", "name", "strategy_label", "year", "source", "why", "created_at"]
DIAG_COLS = ["event_key", "runs", "first_run", "last_run", "first_cutoff", "last_cutoff", "from_sweep"]
JOB_COLS = ["id", "kind", "sport", "status", "progress", "created_at", "finished_at", "result_run_id", "user", "params"]
RUN_COLS = ["id", "kind", "competition", "season", "category", "variant", "event_key", "cutoff", "created_at",
            "label", "predictions"]


def edge_summary(payload: Any) -> list[tuple[str, Any]]:
    p = payload if isinstance(payload, dict) else {}
    return [("year", p.get("year")), ("configurations", p.get("configurations")),
            ("venue", p.get("venue") or "all")]


RUN_KINDS = ["forecast", "scenario", "diagnostic", "backtest", "sweep", "season_strategy", "season_checkpoints",
             "season_asof", "walk_forward", "candidate", "combo"]
STRATEGIES = ["update", "hold", "last", "early", "maker", "maker_flat"]
REPLAY_KNOBS = [  # replay_maker's knobs and defaults, as the tool declares them
    ("exchange", "choice", "polymarket", ["polymarket", "kalshi"]),
    ("fill", "choice", "through", ["through", "touch", "queue"]),
    ("half_spread", "float", 0.02, None), ("size", "float", 50, None), ("max_pos", "float", 250, None),
    ("max_capital", "float", 1000, None), ("skew", "float", 1, None), ("max_disagree", "float", 0.15, None),
    ("min_volume_24h", "float", 100, None), ("pull_min", "float", 15, None), ("top", "int", 20, None),
]


# ------------------------------------------------------------------------- knob form

class KnobField(Horizontal):
    """One knob from list_job_types / sweep_settings, as the right input for its type."""

    DEFAULT_CSS = """
    KnobField { height: auto; margin: 0 0 1 0; }
    KnobField > Label { width: 22; padding: 0 1 0 0; color: $text-muted; }
    KnobField > .knob-input { width: 1fr; }
    KnobField > .knob-help { width: 2fr; padding: 0 0 0 2; color: $text-muted; }
    KnobField TextArea { height: 6; }
    KnobField SelectionList { height: auto; max-height: 8; }
    """

    def __init__(self, knob: dict, prefix: str) -> None:
        super().__init__()
        self.knob = knob
        self.name_ = knob["name"]
        self.kind = knob.get("type") or "text"
        self.default = knob.get("default")
        self.prefix = prefix

    def compose(self) -> ComposeResult:
        yield Label(self.name_.replace("_", " "))
        yield self._input()
        help_text = self.knob.get("help") or ""
        rng = ""
        if self.knob.get("min") is not None or self.knob.get("max") is not None:
            rng = f"{self.knob.get('min', '')}–{self.knob.get('max', '')}"
        yield Static(" ".join(x for x in (rng, help_text) if x), classes="knob-help")

    def _input(self) -> Widget:
        kind, default, choices = self.kind, self.default, self.knob.get("choices")
        if kind == "choice" and choices:
            opts = [(str(c), str(c)) for c in choices]
            if default is None:
                return CSelect(opts, prompt="(default)", allow_blank=True, classes="knob-input")
            return CSelect(opts, value=str(default), allow_blank=False, classes="knob-input")
        if kind == "bool":
            opts = [("yes", "yes"), ("no", "no")]
            return CSelect(opts, prompt=f"(default: {'yes' if default else 'no'})", allow_blank=True,
                          classes="knob-input")
        if kind == "multi" and choices:
            chosen = set(default or [])
            return SelectionList(*[(str(c), str(c), c in chosen) for c in choices], classes="knob-input")
        if kind in ("legs", "object"):
            return TextArea(json.dumps(default, indent=1) if default else "", classes="knob-input")
        placeholder = {"datetime": "YYYY-MM-DDTHH:MM (UTC)", "event": "e.g. 2026-15", "years": "e.g. 2024,2025",
                       "map": "kind=value, e.g. race_h2h=0.05"}.get(kind, "")
        if default not in (None, ""):
            placeholder = f"{default}" if not placeholder else f"{placeholder}   default {default}"
        return CInput(placeholder=placeholder or "(default)", classes="knob-input")

    def set_value(self, value: Any) -> None:
        """Fill the field from a saved configuration's value."""
        widget = self.query_one(".knob-input")
        if isinstance(widget, _Select):
            text = ("yes" if value else "no") if self.kind == "bool" else str(value)
            try:
                widget.value = text
            except Exception:  # noqa: BLE001 - not one of the choices: leave the default
                pass
        elif isinstance(widget, SelectionList):
            widget.deselect_all()
            for item in value if isinstance(value, list) else str(value).split(","):
                widget.select(str(item).strip())
        elif isinstance(widget, TextArea):
            widget.text = json.dumps(value, indent=1)
        else:
            if isinstance(value, dict):
                text = ",".join(f"{k}={v}" for k, v in value.items())
            elif isinstance(value, list):
                text = ",".join(map(str, value))
            else:
                text = "" if value is None else str(value)
            widget.value = text

    def value(self) -> tuple[bool, Any]:
        """(changed from the default?, value as the server expects it)."""
        widget = self.query_one(".knob-input")
        kind, default = self.kind, self.default
        if isinstance(widget, _Select):
            v = widget.value
            if not isinstance(v, str):
                return False, None
            if kind == "bool":
                return (v == "yes") != bool(default), v == "yes"
            return v != str(default), v
        if isinstance(widget, SelectionList):
            sel = list(widget.selected)
            return sorted(sel) != sorted(default or []), sel
        if isinstance(widget, TextArea):
            text = widget.text.strip()
            if not text:
                return False, None
            return True, json.loads(text)
        text = widget.value.strip()  # Input
        if not text:
            return False, None
        if kind == "int":
            return True, int(text)
        if kind == "float":
            return True, float(text)
        if kind == "map":
            out: dict[str, float] = {}
            for part in text.split(","):
                k, _, v = part.partition("=")
                if k.strip():
                    out[k.strip()] = float(v)
            return True, out
        if kind == "years":
            return True, text
        return True, text


class JobForm(VerticalScroll):
    DEFAULT_CSS = "JobForm { height: 1fr; } JobForm .what { padding: 0 0 1 0; } JobForm Collapsible { height: auto; }"

    def __init__(self, job: dict, sweep_settings: list[dict]) -> None:
        super().__init__()
        self.job = job
        self.sweep_settings = sweep_settings

    def compose(self) -> ComposeResult:
        what = Text(self.job.get("what") or "")
        if self.job.get("takes"):
            what.append(f"  Takes {self.job['takes']}.", style=fmt.DIM)
        yield Static(what, classes="what")
        for knob in self.job.get("knobs") or []:
            if knob.get("type") == "object" and knob["name"] == "settings":
                groups: dict[str, list[dict]] = {}
                for s in self.sweep_settings:
                    groups.setdefault(s.get("group") or "other", []).append(s)
                for group, settings in groups.items():
                    with Collapsible(title=f"Sweep settings: {group}", collapsed=group != "model"):
                        for s in settings:
                            yield KnobField(s, prefix="settings")
            else:
                yield KnobField(knob, prefix="")

    def params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        settings: dict[str, Any] = {}
        for field in self.query(KnobField):
            changed, value = field.value()
            if field.prefix == "settings":
                if changed and value is not None:
                    settings[field.name_] = value
            elif value is not None:
                params[field.name_] = value
        if settings:
            params["settings"] = settings
        return params


# ------------------------------------------------------------------------- edge finder detail

class EdgeConfigScreen(ModalScreen[str | None]):
    """One Edge Finder row: the strategy's season recap and the settings that differ from default."""

    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    EdgeConfigScreen { align: center middle; }
    EdgeConfigScreen > VerticalScroll { width: 92; height: 80%; padding: 1 2; border: round $secondary;
                                        background: $surface; }
    EdgeConfigScreen .actions { height: auto; padding: 1 0 0 0; }
    EdgeConfigScreen .actions > * { margin: 0 2 0 0; }
    EdgeConfigScreen .head { text-style: bold; }
    EdgeConfigScreen .section { padding: 1 0 0 0; }
    """

    def __init__(self, row: dict, settings: dict) -> None:
        super().__init__()
        self.row = row
        self.settings = settings

    def compose(self) -> ComposeResult:
        r = self.row
        with VerticalScroll():
            yield Static(f"{r.get('strategy_label') or r.get('strategy')} on {r.get('venue')}", classes="head")
            yield Static(Text(str(r.get("config") or ""), style=fmt.DIM))
            yield Static("Season", classes="section")
            yield Static(rich_kv_table([(k, r.get(k)) for k in (
                "pnl", "roi", "volume", "weekends", "up", "avg", "sd", "best", "worst", "drawdown", "consistency",
                "fills", "markout") if r.get(k) is not None]))
            yield Static("Settings changed from default", classes="section")
            yield Static(rich_kv_table([(k, fmt.setting_value(v)) for k, v in self.settings.items()])
                         if self.settings else Text("None: the defaults.", style=fmt.DIM))
            with Horizontal(classes="actions"):
                yield CButton("Queue a sweep with these settings", id="sweep", variant="primary")
                yield CButton(f"Open run #{r.get('run_id')}", id="run", disabled=not r.get("run_id"))
                yield CButton("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run" and self.row.get("run_id"):
            self.app.push_screen(ModelRunScreen(int(self.row["run_id"])))
        elif event.button.id == "sweep":
            self.dismiss("sweep")
        else:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


# ------------------------------------------------------------------------- pane

class LabPane(Pane):
    DEFAULT_CSS = """
    LabPane DataGrid { height: 1fr; }
    LabPane #lab-form-host { height: 1fr; }
    LabPane #lab-diag-side { width: 52; padding: 0 0 0 1; }
    LabPane #lab-diag-side Input { width: 1fr; }
    LabPane .replay-row { height: auto; margin: 0 0 1 0; }
    LabPane .replay-row > Label { width: 16; padding: 0 1 0 0; color: $text-muted; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.catalog: dict = {}

    def compose(self) -> ComposeResult:
        with TabbedContent(id="lab-tabs"):
            with TabPane("Jobs", id="lab-jobs"):
                with Horizontal(classes="toolbar"):
                    yield CSelect([(s, s) for s in ("queued", "running", "done", "failed")], id="lab-job-status",
                                 prompt="Any status", allow_blank=True)
                    yield Static("Refreshes every 5 s. Enter opens a job.", classes="muted hint")
                yield DataGrid(id="lab-jobs-grid", columns=JOB_COLS, empty="No jobs yet. Queue one under New job.")
            with TabPane("New job", id="lab-new"):
                with Horizontal(classes="toolbar"):
                    yield CSelect([], id="lab-job-type", prompt="Simulation", allow_blank=True)
                    yield CButton("Queue job", id="lab-queue", variant="primary", disabled=True)
                yield Vertical(id="lab-form-host")
            with TabPane("Edge Finder", id="lab-edge"):
                with Horizontal(classes="toolbar"):
                    yield CInput("2026", placeholder="Year", id="lab-edge-year", classes="narrow")
                    yield CSelect([(s, s) for s in STRATEGIES], id="lab-edge-strategy", prompt="All strategies",
                                 allow_blank=True)
                    yield CSelect([("polymarket", "polymarket"), ("kalshi", "kalshi")], id="lab-edge-venue",
                                 prompt="All venues", allow_blank=True)
                yield PagedGrid("edge_finder", keys=("rows",), columns=EDGE_COLS, limit=100,
                                summary=edge_summary, empty="No sweeps saved for this year.", id="lab-edge-grid")
            with TabPane("Candidates", id="lab-cand"):
                yield PagedGrid("list_candidates", columns=CAND_COLS, limit=100,
                                empty="No candidates saved.", id="lab-cand-grid")
            with TabPane("Diagnostics", id="lab-diag"):
                with Horizontal():
                    yield PagedGrid("list_diagnostics", columns=DIAG_COLS, limit=100,
                                    empty="No diagnostic runs.", id="lab-diag-grid")
                    with VerticalScroll(id="lab-diag-side"):
                        yield Static("Diagnostic run", classes="section")
                        with Horizontal(classes="toolbar"):
                            yield CInput(placeholder="Run id", id="lab-diag-run", type="integer")
                            yield CButton("Open", id="lab-diag-open")
                        yield Static("Replay a maker", classes="section")
                        for name, kind, default, choices in REPLAY_KNOBS:
                            with Horizontal(classes="replay-row"):
                                yield Label(name.replace("_", " "))
                                if choices:
                                    yield CSelect([(c, c) for c in choices], value=default, allow_blank=False,
                                                 id=f"rp-{name}")
                                else:
                                    yield CInput(str(default), id=f"rp-{name}", type="number")
                        with Horizontal(classes="replay-row"):
                            yield Label("with sweep")
                            yield CSelect([("no", "no"), ("yes", "yes")], value="no", allow_blank=False,
                                         id="rp-with_sweep")
                        yield CButton("Replay", id="lab-replay", variant="primary")
            with TabPane("Model runs", id="lab-runs"):
                with Horizontal(classes="toolbar"):
                    yield CSelect([(k, k) for k in RUN_KINDS], id="lab-run-kind", prompt="Any kind", allow_blank=True)
                    yield CSelect([], id="lab-run-comp", prompt="Any competition", allow_blank=True)
                    yield CInput(placeholder="Season", id="lab-run-season", classes="narrow")
                yield DataGrid(id="lab-runs-grid")

    def on_mount(self) -> None:
        self.set_interval(5, self._tick_jobs)

    def _tick_jobs(self) -> None:
        if self.loaded and self.query_one("#lab-tabs", TabbedContent).active == "lab-jobs" and self.app.screen is self.screen:
            self.run(self._load_jobs(quiet=True), group="jobs")

    def refresh_data(self) -> None:
        active = self.query_one("#lab-tabs", TabbedContent).active
        loader = {
            "lab-jobs": self._load_jobs, "lab-new": self._load_catalog, "lab-edge": self._load_edge,
            "lab-cand": self._load_candidates, "lab-diag": self._load_diagnostics, "lab-runs": self._load_runs,
        }.get(active or "lab-jobs", self._load_jobs)
        self.run(loader(), group=active or "jobs")

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content.id == "lab-tabs":
            event.stop()
            if self.loaded:
                self.refresh_data()

    def _switch(self, pane_id: str) -> None:
        from textual.widgets._tabbed_content import ContentTabs

        tabs = self.query_one("#lab-tabs", TabbedContent)
        tabs.query_one(ContentTabs).focus()
        tabs.active = pane_id

    def _sel(self, sel_id: str) -> str | None:
        v = self.query_one(sel_id, Select).value
        return v if isinstance(v, str) else None

    # ---------------------------------------------------------------- loaders
    async def _load_jobs(self, quiet: bool = False) -> None:
        grid = self.query_one("#lab-jobs-grid", DataGrid)
        payload = await self.call("list_jobs", busy=None if quiet else grid, status=self._sel("#lab-job-status"),
                                  limit=100)
        if payload is not None:
            row = grid.cursor_row
            grid.load(fmt.first_table(payload, "jobs"))
            if quiet and 0 <= row < grid.row_count:
                grid.move_cursor(row=row)

    async def _load_catalog(self) -> None:
        if self.catalog:
            return
        payload = await self.call("list_job_types", busy=self.query_one("#lab-form-host"))
        if not isinstance(payload, dict):
            return
        self.catalog = payload
        sel = self.query_one("#lab-job-type", Select)
        sel.set_options([(f"{j['label']}  ({j['sport']})", j["job_type"]) for j in payload.get("job_types", [])])

    async def _load_edge(self) -> None:
        self.query_one("#lab-edge-grid", PagedGrid).set_args(
            year=int_or_none(self.query_one("#lab-edge-year", CInput).value) or 2026,
            strategy=self._sel("#lab-edge-strategy"), venue=self._sel("#lab-edge-venue"))

    async def _load_candidates(self) -> None:
        self.query_one("#lab-cand-grid", PagedGrid).set_args()

    async def _load_diagnostics(self) -> None:
        self.query_one("#lab-diag-grid", PagedGrid).set_args()

    async def _load_runs(self, offset: int = 0) -> None:
        comp = self.query_one("#lab-run-comp", Select)
        if not getattr(self, "_comps_loaded", False):
            self._comps_loaded = True
            await self.rl.overview_ready()
            with self.prevent(Select.Changed):
                comp.set_options([(c, c) for c in self.rl.competitions()])
        grid = self.query_one("#lab-runs-grid", DataGrid)
        payload = await self.call("list_model_runs", busy=grid, kind=self._sel("#lab-run-kind"),
                                  competition=self._sel("#lab-run-comp"),
                                  season=int_or_none(self.query_one("#lab-run-season", Input).value),
                                  limit=50, offset=offset)
        if payload is not None:
            table = fmt.first_table(payload, "runs", "model_runs")
            grid.load(table, columns=[c for c in RUN_COLS if c in table.columns] or None)

    # ---------------------------------------------------------------- new job
    def _job(self, job_type: str) -> dict | None:
        return next((j for j in self.catalog.get("job_types", []) if j["job_type"] == job_type), None)

    async def _show_form(self, job_type: str) -> None:
        job = self._job(job_type)
        host = self.query_one("#lab-form-host", Vertical)
        await host.remove_children()
        if job is None:
            return
        sport = job.get("sport")
        settings = (self.catalog.get("sport_sweep_settings") or {}).get(sport) or self.catalog.get("sweep_settings") or []
        await host.mount(JobForm(job, settings))
        self.query_one("#lab-queue", Button).disabled = False

    async def _queue(self) -> None:
        job_type = self._sel("#lab-job-type")
        forms = list(self.query(JobForm))
        if not job_type or not forms:
            return
        try:
            params = forms[0].params()
        except (ValueError, json.JSONDecodeError) as exc:
            self.app.notify(f"Check the form: {exc}", severity="error")
            return
        payload = await self.call("run_job", busy=self.query_one("#lab-queue"), job_type=job_type, params=params or None)
        if payload is None:
            return
        job_id = payload.get("job_id") or payload.get("id") if isinstance(payload, dict) else None
        if job_id is None and isinstance(payload, dict):
            job_id = (payload.get("job") or {}).get("id")
        self.app.notify(f"Job #{job_id} queued." if job_id else "Job queued.", title=job_type)
        if job_id:
            self.app.push_screen(JobScreen(int(job_id)))
        self._switch("lab-jobs")

    # ---------------------------------------------------------------- events
    async def on_select_changed(self, event: Select.Changed) -> None:
        sid = event.select.id or ""
        if sid == "lab-job-type" and isinstance(event.value, str):
            await self._show_form(event.value)
        elif sid == "lab-job-status":
            self.run(self._load_jobs(), group="jobs")
        elif sid.startswith("lab-edge-"):
            self.run(self._load_edge(), group="edge")
        elif sid.startswith("lab-run-"):
            self.run(self._load_runs(), group="runs")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        iid = event.input.id or ""
        if iid == "lab-edge-year":
            self.run(self._load_edge(), group="edge")
        elif iid == "lab-run-season":
            self.run(self._load_runs(), group="runs")
        elif iid == "lab-diag-run":
            self._open_diagnostic()

    def _open_diagnostic(self) -> None:
        run_id = int_or_none(self.query_one("#lab-diag-run", Input).value)
        if run_id is None:
            self.app.notify("Enter a diagnostic run id.", severity="warning")
            return
        self.app.push_screen(PayloadScreen(f"Diagnostic run #{run_id}",
                                           lambda: self.rl.backend.call("get_diagnostic", run_id=run_id, top=50)))

    def _replay(self) -> None:
        run_id = int_or_none(self.query_one("#lab-diag-run", Input).value)
        if run_id is None:
            self.app.notify("Enter the diagnostic run id to replay.", severity="warning")
            return
        args: dict[str, Any] = {"run_id": run_id}
        for name, kind, default, choices in REPLAY_KNOBS:
            widget = self.query_one(f"#rp-{name}")
            if isinstance(widget, Select):
                args[name] = widget.value
            else:
                v = float_or_none(widget.value)  # type: ignore[attr-defined]
                args[name] = (int(v) if kind == "int" and v is not None else v) if v is not None else default
        args["with_sweep"] = self.query_one("#rp-with_sweep", Select).value == "yes"
        self.app.push_screen(PayloadScreen(f"Maker replay of run #{run_id} on {args['exchange']}",
                                           lambda: self.rl.backend.call("replay_maker", **args)))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "lab-queue":
            self.run(self._queue(), group="queue")
        elif bid == "lab-diag-open":
            self._open_diagnostic()
        elif bid == "lab-replay":
            self._replay()

    def on_data_grid_row_chosen(self, event: DataGrid.RowChosen) -> None:
        event.stop()
        row = event.row
        owner = event.grid.parent.id if event.grid.parent is not None else None
        if owner == "lab-edge-grid":
            payload = self.query_one("#lab-edge-grid", PagedGrid).payload or {}
            settings = (payload.get("changed_settings") or {}).get(row.get("settings_key")) or {}
            year = payload.get("year")

            def chosen(action: str | None) -> None:
                if action == "sweep":
                    self.run(self._prefill_sweep(settings, year, row.get("venue")), group="prefill")

            self.app.push_screen(EdgeConfigScreen(row, settings), chosen)
            return
        if owner == "lab-cand-grid" and row.get("id"):
            self.app.push_screen(ModelRunScreen(int(row["id"])))
            return
        if owner == "lab-diag-grid":
            if row.get("last_run"):
                self.query_one("#lab-diag-run", CInput).value = str(int(row["last_run"]))
                self.app.notify(f"Run #{int(row['last_run'])}: the latest of {row.get('runs')} diagnostics for "
                                f"{row.get('event_key')}. Open it or replay a maker on it.", timeout=5)
            return
        if event.grid.id == "lab-jobs-grid" and (row.get("id") or row.get("job_id")):
            self.app.push_screen(JobScreen(int(row.get("id") or row.get("job_id"))))
        elif event.grid.id == "lab-runs-grid" and (row.get("id") or row.get("run_id")):
            self.app.push_screen(ModelRunScreen(int(row.get("id") or row.get("run_id"))))
        else:
            self.rl.open_ref(row)

    def on_data_grid_page_request(self, event: DataGrid.PageRequest) -> None:
        if event.grid.id == "lab-runs-grid":
            self.run(self._load_runs(event.offset), group="runs")

    def on_object_view_row_chosen(self, event: ObjectView.RowChosen) -> None:
        self.rl.open_ref(event.row)

    async def _prefill_sweep(self, settings: dict, year: Any, venue: Any) -> None:
        """New job: an Edge Finder sweep filled in with a saved configuration's settings."""
        await self._load_catalog()
        job_type = "f1_sweep"
        self._switch("lab-new")
        select = self.query_one("#lab-job-type", CSelect)
        with self.prevent(_Select.Changed):
            select.value = job_type
        await self._show_form(job_type)
        filled = dict(settings)
        if venue and "venue" not in filled:
            filled["venue"] = venue
        fields = {(f.prefix, f.name_): f for f in self.query(KnobField)}
        if year is not None and ("", "year") in fields:
            fields[("", "year")].set_value(str(year))
        missing = []
        for name, value in filled.items():
            field = fields.get(("settings", name))
            if field is None:
                missing.append(name)
                continue
            field.set_value(value)
            collapsible = next((a for a in field.ancestors if isinstance(a, Collapsible)), None)
            if collapsible is not None:
                collapsible.collapsed = False
        note = f" ({', '.join(missing)} not in this form)" if missing else ""
        self.app.notify(f"Filled {len(filled) - len(missing)} settings from the configuration{note}. "
                        "Check them, then Queue job.", title="New sweep", timeout=8)

    def show_runs(self, kind: str | None) -> None:  # noqa: D401
        self.loaded = True
        self._switch("lab-runs")
        if kind in RUN_KINDS:
            self.query_one("#lab-run-kind", Select).value = kind
        self.run(self._load_runs(), group="runs")
