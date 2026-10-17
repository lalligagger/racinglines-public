"""Layout mode: resize a tab's splits with the keys or by dragging a divider, then save the sizes as a named layout.

A split is two neighbouring containers in one pane (SPLITS). A layout maps a split's name to the first side's share
in percent; a split it leaves out keeps the pane's own CSS sizes. The built-in "default" layout is {} and can't be
overwritten. Saved layouts and the one last used live in ~/.config/racinglines/tui-layouts.json
(RACINGLINES_TUI_LAYOUTS overrides the path)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label

if TYPE_CHECKING:
    from .app import RacinglinesApp

DEFAULT = "default"
MIN_PCT, MAX_PCT = 10, 90


@dataclass(frozen=True)
class Split:
    name: str
    tab: str
    first: str
    second: str
    axis: str  # "h": side by side (widths), "v": stacked (heights)


SPLITS: tuple[Split, ...] = (
    Split("trade.h", "trade", "tr-left", "tr-right", "h"),
    Split("trade.v", "trade", "tr-top", "tr-tabs", "v"),
    Split("lab.diag", "lab", "lab-diag-grid", "lab-diag-side", "h"),
    Split("book.h", "book", "sb-editor", "sb-result", "h"),
)
BY_NAME = {s.name: s for s in SPLITS}


def path() -> Path:
    return Path(os.environ.get("RACINGLINES_TUI_LAYOUTS", "~/.config/racinglines/tui-layouts.json")).expanduser()


def clamp(pct: float) -> int:
    return int(max(MIN_PCT, min(MAX_PCT, round(pct))))


class Store:
    """The saved layouts and which one is current."""

    def __init__(self, file: Path | None = None) -> None:
        self.file = file or path()
        self.layouts: dict[str, dict[str, int]] = {}
        self.current = DEFAULT
        try:
            data = json.loads(self.file.read_text())
        except (OSError, ValueError):
            data = {}
        for name, splits in (data.get("layouts") or {}).items():
            if name != DEFAULT and isinstance(splits, dict):
                self.layouts[name] = {k: clamp(v) for k, v in splits.items()
                                      if k in BY_NAME and isinstance(v, (int, float))}
        if data.get("current") in self.layouts:
            self.current = data["current"]

    def names(self) -> list[str]:
        return [DEFAULT, *sorted(self.layouts)]

    def get(self, name: str) -> dict[str, int]:
        return dict(self.layouts.get(name, {}))

    def save(self, name: str, splits: dict[str, int]) -> None:
        if name == DEFAULT:
            raise ValueError("the default layout can't be overwritten; save it under a new name")
        self.layouts[name] = dict(splits)
        self.current = name
        self.write()

    def use(self, name: str) -> None:
        self.current = name if name in self.layouts else DEFAULT
        self.write()

    def write(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"current": self.current, "layouts": self.layouts}, indent=2, sort_keys=True))
        tmp.replace(self.file)


def _sides(app: "RacinglinesApp", split: Split) -> tuple[Widget, Widget] | None:
    try:
        return app.query_one(f"#{split.first}"), app.query_one(f"#{split.second}")
    except NoMatches:
        return None


def apply(app: "RacinglinesApp", splits: dict[str, int]) -> None:
    """Size every split: from `splits` where it names one, else back to the pane's CSS."""
    for split in SPLITS:
        sides = _sides(app, split)
        if sides is None:
            continue
        pct = splits.get(split.name)
        attr = "width" if split.axis == "h" else "height"
        for widget, share in zip(sides, (pct, None if pct is None else 100 - pct)):
            setattr(widget.styles, attr, None if share is None else f"{share}fr")


def measure(app: "RacinglinesApp", split: Split) -> int | None:
    """The first side's share as laid out now, in percent."""
    sides = _sides(app, split)
    if sides is None:
        return None
    a, b = (s.outer_size.width if split.axis == "h" else s.outer_size.height for s in sides)
    return clamp(100 * a / (a + b)) if a + b else None


class Divider(Widget):
    """A one-cell bar between a split's two sides; shown in layout mode, dragged to resize."""

    DEFAULT_CSS = """
    Divider { display: none; background: $secondary 40%; }
    Divider.-h { width: 1; height: 1fr; }
    Divider.-v { height: 1; width: 1fr; }
    Divider:hover, Divider.-dragging { background: $secondary; }
    """

    def __init__(self, split: str, **kwargs) -> None:
        self.split = BY_NAME[split]
        super().__init__(classes=f"-{self.split.axis}", **kwargs)
        self._dragging = False

    def render(self) -> str:
        return ""

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.add_class("-dragging")
        self.capture_mouse()
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            self.remove_class("-dragging")
            self.release_mouse()
            event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging or self.parent is None:
            return
        region = self.parent.content_region
        if self.split.axis == "h":
            pct = 100 * (event.screen_x - region.x) / max(region.width, 1)
        else:
            sides = _sides(self.app, self.split)  # stacked: measure from the first side's top, not the pane's
            top = sides[0].region.y if sides else region.y
            span = (sides[0].outer_size.height + sides[1].outer_size.height) if sides else region.height
            pct = 100 * (event.screen_y - top) / max(span, 1)
        self.app.set_split(self.split.name, pct)  # type: ignore[attr-defined]
        event.stop()


class LayoutBar(Horizontal):
    """The banner shown in layout mode: the layout's name, whether it changed, and the keys."""

    DEFAULT_CSS = """
    LayoutBar { display: none; height: 1; background: $secondary 30%; padding: 0 1; }
    LayoutBar Label { width: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label(id="layout-label")

    def show(self, name: str, dirty: bool, splits: list[str]) -> None:
        mark = " (changed)" if dirty else ""
        here = ", ".join(splits) if splits else "nothing to resize on this tab"
        self.query_one("#layout-label", Label).update(
            f"LAYOUT {name}{mark} · {here} · ←→ ↑↓ or drag a bar to resize · esc done")


class NameScreen(ModalScreen[str | None]):
    """Ask for a new layout's name."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    NameScreen { align: center middle; }
    NameScreen > Vertical { width: 56; height: auto; padding: 1 2; border: round $secondary; background: $surface; }
    NameScreen Horizontal { height: auto; padding: 1 0 0 0; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Save layout as")
            yield Input(placeholder="name, e.g. wide-book", id="layout-name")
            yield Label("", id="layout-name-error", classes="muted")
            with Horizontal():
                yield Button("Save", id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def _submit(self) -> None:
        name = self.query_one(Input).value.strip()
        error = ("Give it a name." if not name else
                 f"'{DEFAULT}' is built in; pick another name." if name == DEFAULT else "")
        if error:
            self.query_one("#layout-name-error", Label).update(error)
            return
        self.dismiss(name)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self._submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
