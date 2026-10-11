"""`racinglines book view` and `--rich` (racinglines/cli/rich_view.py) on a synthetic saved result: no database. Every
name, odds and price here is made up."""

import json

import pytest
from rich.console import Console

from racinglines.cli import book as CLI
from racinglines.cli import rich_view as V

pytestmark = pytest.mark.quick

LEG = {"leg": "1", "status": "mapped", "reason": None, "sport": "f1", "event_key": "2026-17", "race_id": 1,
       "kind": "race_win", "side": "yes", "athlete": "Ann Alpha", "opponent": None, "team": None, "threshold": None,
       "odds": None}
PRICE = {
    "book": {"venue": "book_x", "event": "2026-17", "sport": "f1", "captured_utc": "2026-10-07T09:00Z",
             "odds": "decimal", "currency": "USD"},
    "lines": [
        {"line": 1, "id": "win", "title": "Race Winner", "selection": "Ann Alpha", "kind": "race_win",
         "status": "mapped", "reason": None, "n_legs": 1, "races": [1], "decimal_odds": 3.0, "book_prob": 0.333333,
         "model_prob": 0.4, "market_prob": 0.32, "model_method": "single", "flags": [], "ev_model": 0.2,
         "ev_market": -0.04, "legs": [dict(LEG, book_prob=None, model_prob=0.4, market_prob=0.32,
                                           market_exchange="kalshi")]},
        {"line": 2, "id": "sgp", "title": "Combo", "selection": "Ann Alpha win + podium", "kind": "combo",
         "status": "mapped", "reason": None, "n_legs": 2, "races": [1], "decimal_odds": 2.6, "book_prob": 0.384615,
         "model_prob": 0.32, "market_prob": None, "model_method": "product",
         "flags": ["race 1: 2 legs on one race, correlated: EV approximate"], "ev_model": -0.168, "ev_market": None,
         "legs": [dict(LEG, leg="2.1", model_prob=0.4), dict(LEG, leg="2.2", kind="race_podium", model_prob=0.8)]},
    ],
    "unmapped": [],
    "assumptions": ["EV is per unit staked."],
    "blend": "none",
}


def _text(cmd, out):
    c = Console(record=True, width=160, color_system=None)
    V.render(cmd, out, console=c)
    return c.export_text()


def test_price_renders_lines_legs_flags_and_assumptions():
    t = _text("price", PRICE)
    assert "+20.0%" in t and "-4.0%" in t and "-16.8%" in t
    assert "└ 2.2" in t and "race_podium Ann Alpha" in t
    assert "correlated: EV approximate" in t and "assumptions" in t


def test_view_detects_the_command(tmp_path, capsys):
    assert CLI._kind(PRICE) == "price"
    settled = {k: v for k, v in PRICE.items() if k not in ("assumptions", "blend")}
    settled["lines"] = [dict(r, result="won", payout=3.0, profit=2.0,
                             legs=[dict(g, result="won") for g in r["legs"]]) for r in PRICE["lines"]]
    assert CLI._kind(settled) == "settle"
    assert CLI._kind({"book": PRICE["book"], "lines": [dict(PRICE["lines"][0], legs=[LEG])], "unmapped": []}) == "map"
    p = tmp_path / "settle.json"
    p.write_text(json.dumps(settled))
    assert CLI.main(["view", str(p)]) == 0
    assert "book settle" in capsys.readouterr().out


def test_view_refuses_a_bad_file(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json")
    assert CLI.main(["view", str(p)]) == 2
