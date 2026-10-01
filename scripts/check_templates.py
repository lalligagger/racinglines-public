#!/usr/bin/env python3
"""Check Jinja2 templates for syntax errors. Fails before push, not in production."""

import math
import sys
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError


def fmt(value, col=""):
    """Format a value for display in templates."""
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
    """-302.97 -> '-$302.97'; sign=True adds '+' to positives; cents=False keeps whole dollars ('-$303')."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    s = "-" if v < 0 else ("+" if sign and v > 0 else "")
    return f"{s}${abs(v):,.{2 if cents else 0}f}"


def kind(k):
    """'race_win' -> 'win', 'race_top10' -> 'top10', 'race_make_final' -> 'make final'."""
    if k is None:
        return ""
    k = str(k).removeprefix("race_")
    return ("DH " + k.removeprefix("dh_") if k.startswith("dh_") else k).replace("_", " ")


def check_templates():
    """Validate all HTML templates in racinglines/web/templates."""
    template_dir = Path("racinglines/web/templates")
    
    if not template_dir.exists():
        print(f"ERROR: {template_dir} not found")
        return 1
    
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    # Register the same filters the app uses
    env.filters["fmt"] = fmt
    env.filters["money"] = money
    env.filters["kind"] = kind
    
    html_files = sorted(template_dir.rglob("*.html"))
    failed = []
    
    for template_path in html_files:
        # Get relative POSIX path from template directory
        relative_path = template_path.relative_to(template_dir)
        template_name = relative_path.as_posix()
        
        try:
            env.get_template(template_name)
        except TemplateSyntaxError as e:
            failed.append((template_name, str(e)))
            print(f"FAIL {template_name}: {e}")
    
    # Print summary
    print(f"templates ok: {len(html_files)}")
    
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(check_templates())
