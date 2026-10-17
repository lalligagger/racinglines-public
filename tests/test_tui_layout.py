"""Layout mode (racinglines/tui/layout.py): keys and drag resize a tab's splits; layouts save, update, cycle and
come back on the next start. Headless against tests/tui_fixtures.py."""
import asyncio
import json

import pytest

from racinglines.tui import layout
from racinglines.tui.app import RacinglinesApp
from racinglines.tui.widgets import DataGrid
from tui_fixtures import FakeBackend


@pytest.fixture
def store_file(tmp_path, monkeypatch):
    path = tmp_path / "tui-layouts.json"
    monkeypatch.setenv("RACINGLINES_TUI_LAYOUTS", str(path))
    return path


async def settle(pilot, n=3):
    for _ in range(n):
        await pilot.pause(0.05)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def width(app, wid):
    return str(app.query_one(f"#{wid}").styles.width)


def test_store_round_trip_and_default_is_read_only(store_file):
    store = layout.Store()
    assert store.names() == ["default"] and store.current == "default"
    with pytest.raises(ValueError):
        store.save("default", {"trade.h": 40})
    store.save("wide", {"trade.h": 140, "bogus": 3})  # clamped; unknown splits dropped on read
    again = layout.Store()
    assert again.current == "wide"
    assert again.get("wide") == {"trade.h": 90}
    store_file.write_text("not json")
    assert layout.Store().names() == ["default"]


def test_layout_mode_keys_resize_and_save(store_file):
    asyncio.run(_test_layout_mode_keys_resize_and_save(store_file))


async def _test_layout_mode_keys_resize_and_save(store_file):
    app = RacinglinesApp(FakeBackend())
    async with app.run_test(size=(160, 48)) as pilot:
        await settle(pilot)
        app.action_tab("trade")
        await settle(pilot)
        grid = app.query_one("#tr-markets", DataGrid)
        grid.focus()
        # Outside layout mode the arrows belong to the grid, and nothing is resized.
        await pilot.press("right")
        assert app.splits == {} and not app.screen.has_class("-layout")

        await pilot.press("ctrl+l")
        assert app.layout_mode and app.screen.has_class("-layout")
        assert app.query_one("#layout-bar").display
        start = layout.measure(app, layout.BY_NAME["trade.h"])
        await pilot.press("right", "right", "shift+left")
        assert app.splits["trade.h"] == start + 9
        assert width(app, "tr-left") == f"{start + 9}fr" and width(app, "tr-right") == f"{91 - start}fr"
        await pilot.press("down")
        assert "trade.v" in app.splits

        # s on the built-in default asks for a name.
        await pilot.press("s")
        await settle(pilot, 1)
        assert isinstance(app.screen, layout.NameScreen)
        await pilot.press(*"wide", "enter")
        await settle(pilot, 1)
        saved = json.loads(store_file.read_text())
        assert saved["current"] == "wide" and saved["layouts"]["wide"]["trade.h"] == start + 9
        assert not app.layout_dirty

        # Update the saved one in place.
        await pilot.press("left")
        await pilot.press("s")
        assert json.loads(store_file.read_text())["layouts"]["wide"]["trade.h"] == start + 4

        # x resets this tab's splits to the CSS; n cycles to default and back.
        await pilot.press("x")
        assert "trade.h" not in app.splits and app.query_one("#tr-left").styles.width.value == 2
        await pilot.press("n")
        assert app.layouts.current == "default" and app.splits == {}
        await pilot.press("n")
        assert app.layouts.current == "wide" and app.splits["trade.h"] == start + 4

        await pilot.press("escape")
        assert not app.layout_mode and not app.screen.has_class("-layout")
        await pilot.press("s")  # an ordinary key again
        assert app.layouts.get("wide")["trade.h"] == start + 4

    # The next start comes up in the saved layout.
    app2 = RacinglinesApp(FakeBackend())
    async with app2.run_test(size=(160, 48)) as pilot:
        await settle(pilot)
        assert app2.layouts.current == "wide"
        assert width(app2, "tr-left") == f"{start + 4}fr"


def test_drag_a_divider(store_file):
    asyncio.run(_test_drag_a_divider())


async def _test_drag_a_divider():
    app = RacinglinesApp(FakeBackend())
    async with app.run_test(size=(160, 48)) as pilot:
        await settle(pilot)
        app.action_tab("book")
        await settle(pilot)
        divider = next(d for d in app.query(layout.Divider) if d.split.name == "book.h")
        assert not divider.display  # hidden outside layout mode
        await pilot.press("ctrl+l")
        await settle(pilot, 1)
        assert divider.display
        body = app.query_one("#sb-body").content_region
        await pilot.mouse_down(divider)
        target = body.x + body.width // 4 - divider.region.x
        await pilot.hover(divider, offset=(target, 0))
        await pilot.mouse_up(divider)  # the divider has moved under the mouse
        assert 20 <= app.splits["book.h"] <= 30
        assert app.layout_dirty

        # A stacked split drags on the other axis.
        app.action_tab("trade")
        await settle(pilot)
        bar = next(d for d in app.query(layout.Divider) if d.split.name == "trade.v")
        top = app.query_one("#tr-top").region
        await pilot.mouse_down(bar)
        await pilot.hover(bar, offset=(0, top.y + 4 - bar.region.y))
        await pilot.mouse_up(bar)
        assert app.splits["trade.v"] < 40
