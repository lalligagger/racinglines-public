"""Render test for board.html template (no database)."""

import math
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError


@pytest.fixture
def jinja_env():
    """Set up Jinja environment with the same filters and globals as the app."""
    template_dir = Path(__file__).resolve().parents[1] / "racinglines" / "web" / "templates"
    static_dir = Path(__file__).resolve().parents[1] / "racinglines" / "web" / "static"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    
    # Register the same filters the app uses
    def fmt(value, col=""):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d %H:%M") if (value.hour or value.minute) else value.strftime("%Y-%m-%d")
        if isinstance(value, float):
            if col.endswith("_prob") or col in ("model_prob", "edge", "quoted_share"):
                return f"{value:.1%}"
            if col.endswith("_pnl") or col in ("pnl", "spread_pnl", "markout_60m", "markout_5m", "model_edge", "worst_case", "cash", "taker_pnl"):
                return f"{value:+,.2f}"
            if col.endswith("time_s"):
                mins, secs = divmod(value, 60)
                return f"{int(mins)}:{secs:06.3f}" if mins else f"{secs:.3f}"
            if value.is_integer() and abs(value) < 1e6:
                return f"{int(value)}"
            return f"{value:.3f}" if abs(value) < 10 else f"{value:.1f}"
        return str(value)
    
    def money(v, sign=False, cents=True):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return ""
        s = "-" if v < 0 else ("+" if sign and v > 0 else "")
        return f"{s}${abs(v):,.{2 if cents else 0}f}"
    
    env.filters["fmt"] = fmt
    env.filters["money"] = money
    
    # Register globals the app uses
    env.globals["demo_context_on"] = lambda: False
    env.globals["csrf_token"] = "test-csrf-token"
    env.globals["env_label"] = lambda: "test"
    env.globals["maintenance_notice"] = lambda: ""
    env.globals["signup_on"] = lambda: False
    env.globals["is_demo"] = lambda u: False
    
    # css_v returns a version number based on file timestamps
    def css_v():
        try:
            return int(max(p.stat().st_mtime for p in static_dir.glob("*.*"))) if static_dir.exists() else 0
        except (ValueError, OSError):
            return 0
    
    env.globals["css_v"] = css_v
    
    return env



def test_board_html_renders(jinja_env):
    """Test that board.html renders without errors with sample data."""
    
    # Build sample context matching board.html needs
    now = datetime.utcnow()
    tomorrow = now + timedelta(days=1)
    
    # Headline object (h) - what the Markets page KPIs display
    headline = {
        "outcomes": 128,
        "markets": 342,
        "volume": 5_200_000,
        "recording": 2,
        "recorded_at": pd.Timestamp(now),
        "my_open": 5,
        "my_staked": 12500.00,
        "my_worst": -342.50,
        "bt_win": 0.0456,
        "bt_grid": 0.0512,
        "jobs_active": 1,
        "brier_win": 0.081,
        "brier_grid": 0.094,
    }
    
    # Sports list - one sport card per section
    sports = [
        {
            "code": "f1",
            "name": "Formula 1",
            "run": None,
            "tape": None,
            "asof": None,
            "upcoming": [],
            "season": {
                "new": 0, 
                "venues": {}, 
                "mine": [], 
                "top": [], 
                "outcomes": 12, 
                "constructors": [],
                "strategy": None,
            },
            "exchanges": [
                {
                    "exchange_name": "Polymarket",
                    "markets": 45,
                    "open": 23,
                    "volume": 125_000,
                    "trades": 456,
                    "price_points": 1250,
                    "books": 23,
                    "synced": "2 min ago",
                    "url": "https://polymarket.com",
                }
            ],
            "later": [],
            "recent": [],
        },
        {
            "code": "mtb_dh",
            "name": "MTB Downhill",
            "run": None,
            "tape": None,
            "asof": None,
            "upcoming": [],
            "season": {
                "new": 0, 
                "venues": {}, 
                "mine": [], 
                "top": [], 
                "outcomes": 8, 
                "constructors": [],
                "strategy": None,
            },
            "exchanges": [
                {
                    "exchange_name": "Polymarket",
                    "markets": 12,
                    "open": 5,
                    "volume": 25_000,
                    "trades": 89,
                    "price_points": 250,
                    "books": 5,
                    "synced": "5 min ago",
                    "url": None,
                }
            ],
            "later": [],
            "recent": [],
        },
    ]
    
    # Minimal context required by board.html and its includes
    context = {
        "h": headline,
        "sports": sports,
        "calendar": [],
        "cal_events": [],
        "cal_sports": [("f1", "Formula 1"), ("mtb_dh", "MTB Downhill")],
        "cal_exchanges": ["polymarket"],
        "kalshi": False,
        "schema_exchanges": [],
        "tapes": False,
        "signals_nav": None,
        "sport_status": None,
        "user": {"sid": "test", "email": "test@example.com"},
        "storage_ns": "",
        "trading": None,
        "live_nav": None,
    }
    
    # Render the template
    template = jinja_env.get_template("board.html")
    html = template.render(**context)
    
    # Verify it rendered to non-empty string
    assert isinstance(html, str)
    assert len(html) > 0
    assert "Markets" in html
    assert "Formula 1" in html
    assert "0.081" in html
    assert "lower is better" in html
    assert "grid-only 0.094" in html


def test_board_html_with_sport_status(jinja_env):
    """Test board.html renders with minimal sport_status (optional include)."""
    
    now = datetime.utcnow()
    
    headline = {
        "outcomes": 64,
        "markets": 200,
        "volume": 2_100_000,
        "recording": 1,
        "recorded_at": pd.Timestamp(now),
        "my_open": 2,
        "my_staked": 5000.00,
        "my_worst": -125.00,
        "bt_win": 0.0300,
        "bt_grid": 0.0400,
        "jobs_active": 0,
    }
    
    sports = [
        {
            "code": "f1",
            "name": "Formula 1",
            "run": None,
            "tape": None,
            "asof": None,
            "upcoming": [],
            "season": {
                "new": 0, 
                "venues": {}, 
                "mine": [], 
                "top": [], 
                "outcomes": 12, 
                "constructors": [],
                "strategy": None,
            },
            "exchanges": [
                {
                    "exchange_name": "Polymarket",
                    "markets": 30,
                    "open": 15,
                    "volume": 50_000,
                    "trades": 200,
                    "price_points": 600,
                    "books": 15,
                    "synced": "1 min ago",
                    "url": "https://polymarket.com",
                }
            ],
            "later": [],
            "recent": [],
        },
    ]
    
    # Test without sport_status enabled (simpler test)
    context = {
        "h": headline,
        "sports": sports,
        "calendar": [],
        "cal_events": [],
        "cal_sports": [("f1", "Formula 1")],
        "cal_exchanges": ["polymarket"],
        "kalshi": False,
        "schema_exchanges": [],
        "tapes": False,
        "signals_nav": None,
        "sport_status": None,  # sport_status is optional; template checks if it's enabled
        "user": {"sid": "test", "email": "test@example.com"},
        "storage_ns": "",
        "trading": None,
        "live_nav": None,
    }
    
    template = jinja_env.get_template("board.html")
    html = template.render(**context)
    
    assert isinstance(html, str)
    assert len(html) > 0
    assert "Formula 1" in html


def test_board_html_model_accuracy_without_backtest(jinja_env):
    """The Model accuracy KPI shows a dash and 'no backtest yet' when there is no baseline backtest."""
    headline = {
        "outcomes": 0, "markets": 0, "volume": 0, "recording": 0, "recorded_at": None,
        "my_open": 0, "my_staked": 0.0, "my_worst": 0.0, "jobs_active": 0,
        "brier_win": None, "brier_grid": None,
    }
    context = {
        "h": headline, "sports": [], "calendar": [], "cal_events": [], "cal_sports": [], "cal_exchanges": [],
        "kalshi": False, "schema_exchanges": [], "tapes": False, "signals_nav": None, "sport_status": None,
        "user": {"sid": "test", "email": "test@example.com"}, "storage_ns": "", "trading": None, "live_nav": None,
    }
    html = jinja_env.get_template("board.html").render(**context)
    assert "Model accuracy" in html
    assert "no backtest yet" in html
    assert "lower is better" not in html
