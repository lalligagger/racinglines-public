"""The TUI's payload parsing and order-book walk (racinglines/tui)."""

from types import SimpleNamespace

import pytest

from racinglines.tui.backend import ToolError, parse_payload
from racinglines.tui.panes.trade import walk_book


def block(text):
    return SimpleNamespace(type="text", text=text)


def test_json_after_rendered_table():
    text = 'hint Start\n┌──┐\n│ {x} │\n└──┘{"a": {"b": [1, 2]}, "c": "x"}'
    assert parse_payload(SimpleNamespace(content=[block(text)], is_error=False)) == {"a": {"b": [1, 2]}, "c": "x"}


def test_plain_json_and_separate_blocks():
    r = SimpleNamespace(content=[block("table"), block('{"k": 1}')], is_error=False, structured_content=None)
    assert parse_payload(r) == {"k": 1}


def test_structured_content_wins_and_unwraps_result():
    r = SimpleNamespace(content=[block("x")], is_error=False, structured_content={"result": [1]})
    assert parse_payload(r) == [1]


def test_error_raises_server_text():
    with pytest.raises(ToolError, match="book too old"):
        parse_payload(SimpleNamespace(content=[block("book too old")], is_error=True))


def test_walk_book_buy_and_sell():
    book = {"yes_asks": [[0.95, 12], [0.5, 500]], "yes_bids": [[0.4, 5], [0.45, 3]]}
    assert walk_book(book, "yes", "buy", 10, 0.6) == {"shares": 10, "notional": 5.0, "avg": 0.5}
    sell = walk_book(book, "yes", "sell", 6, 0.4)
    assert sell["shares"] == 6 and abs(sell["notional"] - (3 * 0.45 + 3 * 0.4)) < 1e-9
    assert walk_book(book, "yes", "buy", 10, 0.3)["shares"] == 0
