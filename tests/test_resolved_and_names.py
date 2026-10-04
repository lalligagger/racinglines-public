"""One display name per event (sports/<sport>.toml [names]) and resolved races kept on the Markets board."""

import json

import pandas as pd

from racinglines import sports as SP
from racinglines.markets import venues as V
from racinglines.web import board as B


def test_the_malaysia_round_has_one_name():
    assert SP.event_title("f1_wdc", "2026-16", "Sakhir GP") == "Malaysia GP"
    assert SP.event_title("f1_wdc", "2026-15", "Baku GP") == "Baku GP"
    assert SP.event_title("f1_wdc", None, "Bristol") == "Bristol"
    assert SP.event_title("no_such_comp", "2026-16", "x") == "x"


def test_race_title_uses_the_name_table_then_the_venue():
    assert V.race_title("f1_wdc", "2026-16", "Sakhir", "Bahrain Grand Prix") == "Malaysia GP"
    assert V.race_title("f1_wdc", "2026-17", "Marina Bay", "Singapore Grand Prix") == "Marina Bay GP"
    assert V.race_title("mtb_dh", "20260927", "Whistler", "Crankworx") == "Whistler"


def _card(rid, status):
    return dict(info=dict(race_id=rid, status=status), top=[], new=0)


def test_recently_resolved_cards_come_first_and_next_skips_them(monkeypatch):
    monkeypatch.setattr(B, "recently_resolved", lambda conn, comp: pd.DataFrame(dict(race_id=[16])))
    monkeypatch.setattr(B, "_resolved_card", lambda conn, rid, maker: dict(_card(rid, "completed"), winner="Norris"))
    cards = B._with_resolved(None, 1, None, [_card(16, "completed"), _card(17, "scheduled"), _card(18, "scheduled")])
    assert [c["info"]["race_id"] for c in cards] == [16, 17, 18]          # race 16 once, as the resolved card
    assert cards[0]["winner"] == "Norris" and [c["next"] for c in cards] == [False, True, False]


def test_nothing_resolved_leaves_the_upcoming_cards(monkeypatch):
    monkeypatch.setattr(B, "recently_resolved", lambda conn, comp: pd.DataFrame(dict(race_id=[])))
    cards = B._with_resolved(None, 1, None, [_card(17, "in_progress"), _card(18, "scheduled")])
    assert [c["next"] for c in cards] == [False, True]


def test_the_live_tab_uses_the_same_name(tmp_path, monkeypatch):
    from racinglines.pipelines import live as LV
    run = tmp_path / "2026-16"
    run.mkdir()
    (run / "meta.json").write_text(json.dumps(dict(sport="f1", event_key="2026-16", title="Bahrain GP in Malaysia (T1 only)")))
    (run / "latest.json").write_text("{}")
    monkeypatch.setattr(LV, "base", lambda: tmp_path)
    assert [e["title"] for e in LV.events()] == ["Malaysia GP"]
