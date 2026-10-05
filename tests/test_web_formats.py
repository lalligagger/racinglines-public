"""The web app's one money format, one date format and the `kind` filter (presentation only)."""
import datetime as dt

import pandas as pd

from racinglines.web.app import fmt, kind, money, templates, when
from scripts.check_templates import template_env


def test_money():
    assert money(-302.97) == "-$302.97"
    assert money(12.3, True) == "+$12.30"
    assert money(-30, False, False) == "-$30"
    assert money(1234.5, False, False) == "$1,234"      # whole dollars when cents=False (rounded)
    assert money(0, True) == "$0.00"
    assert money(None) == "" and money(float("nan")) == ""


def test_fmt_money_columns():
    assert fmt(-4.0, "pnl") == "-$4.00"
    assert fmt(3.5, "staked") == "$3.50"
    assert fmt(12, "payout") == "$12.00"
    assert fmt(2.0, "ev") == "+$2.00"
    assert fmt(0.5, "other") == "0.500"


def test_fmt_dates():
    assert fmt(pd.Timestamp("2026-09-27 14:05")) == "2026-09-27 14:05 UTC"
    assert fmt(pd.Timestamp("2026-09-27")) == "2026-09-27"
    assert fmt(pd.Timestamp("2026-09-27 14:05", tz="America/Vancouver")) == "2026-09-27 21:05 UTC"
    assert fmt(dt.datetime(2026, 9, 27, 9, 30, tzinfo=dt.timezone.utc)) == "2026-09-27 09:30 UTC"
    assert fmt(dt.date(2026, 9, 27)) == "2026-09-27"
    assert fmt(pd.NaT) == ""
    assert when("2026-09-27T14:05:33") == "2026-09-27 14:05 UTC"


def test_kind():
    assert kind("race_win") == "win" and kind("race_pole") == "pole"
    assert kind("race_make_final") == "make final"
    assert kind(None) == ""


def test_template_checker_registers_app_date_filter():
    template = template_env().from_string("{{ value|when }}")
    assert template.render(value="2026-09-27T14:05:33") == when("2026-09-27T14:05:33")


def test_table_headers_and_empty():
    t = templates.env.from_string('{% from "_macros.html" import table %}{{ table(rows, cols) }}')
    out = t.render(rows=[{"markets_made": 1, "foo_bar": 2}], cols=["markets_made", "foo_bar"])
    assert "<th>Markets made</th>" in out and "<th>Foo bar</th>" in out
    assert "No rows yet." in t.render(rows=[], cols=["x"])
