"""
Helpers for the overnight VM run's replay half (docs/overnight-vm-run.md). Read-only.

    python scripts/vm/replay_grid.py spikes nascar [kalshi]
        Share of the sport's stored exchange prices that sit more than 15 points off their 5-point rolling median:
        the test that ruled out Kalshi's F1 taker replay (1.67% on Kalshi F1 against 0.06% on Polymarket,
        data/runs/search/taker-resweep/REPORT.md section 3). Prints the share and a verdict line.

    python scripts/vm/replay_grid.py rank data/runs/replay-grid/nascar [--top 3] [--venue kalshi]
        Reads every <run>/<venue>/summary.json under the folder (runs named <year>-e<edge>-v<volume>[-s<sims>]),
        writes grid-<venue>.md (grid.md for kalshi) next to them, one row per setting with each season's update P&L after fees, ranked by the
        worse season, and prints the top settings as "edge volume" lines for the 16k re-run.
"""

import json
import re
import sys
from pathlib import Path

SPIKE_PTS, WINDOW = 0.15, 5
F1_KALSHI, F1_POLYMARKET = 0.0167, 0.0006


def spikes(sport, exchange="kalshi"):
    import pandas as pd
    from sqlalchemy import text
    from racinglines import sports
    from racinglines.db.config import get_engine
    comp = sports.load(sport)["competition"]["code"]
    q = text("""SELECT h.token_id, h.ts, h.price FROM market_price_history h
                JOIN market_links ml ON ml.token_id = h.token_id
                JOIN competitions co ON co.id = ml.competition_id
                WHERE co.code = :c AND ml.exchange = :x ORDER BY h.token_id, h.ts""")
    with get_engine().connect() as c:
        df = pd.read_sql(q, c, params=dict(c=comp, x=exchange))
    if df.empty:
        print(f"spikes {sport} {exchange}: no stored prices")
        return 1
    med = df.groupby("token_id")["price"].transform(lambda s: s.rolling(WINDOW, center=True, min_periods=3).median())
    share = float(((df["price"] - med).abs() > SPIKE_PTS).mean())
    half = float(((df["price"] - 0.5).abs() < 1e-9).mean())
    verdict = ("CLEAN (Polymarket-like): taker P&L can be read" if share < 5 * F1_POLYMARKET else
               "SPIKY (Kalshi-F1-like): taker P&L is indicative only, fills need bid/ask" if share >= F1_KALSHI / 2 else
               "IN BETWEEN: read taker P&L with the per-race table, not the total")
    print(f"spikes {sport} {exchange}: {len(df):,} price points on {df['token_id'].nunique():,} markets, "
          f"{share:.2%} more than {SPIKE_PTS * 100:.0f} points off the rolling median "
          f"(F1 Kalshi {F1_KALSHI:.2%}, F1 Polymarket {F1_POLYMARKET:.2%}); {half:.2%} at exactly 0.50 "
          f"(an empty book's midpoint if high): {verdict}")
    return 0


NAME = re.compile(r"^(?P<year>\d{4})-e(?P<edge>[\d.]+)-v(?P<vol>[\d.]+)(?:-s(?P<sims>\d+))?$")


def rank(folder, top=3, venue="kalshi"):
    folder = Path(folder)
    rows = {}
    for f in sorted(folder.glob(f"*/{venue}/summary.json")):
        m = NAME.match(f.parent.parent.name)
        if not m:
            continue
        t = json.loads(f.read_text())["totals"].get("update") or {}
        key = (float(m["edge"]), float(m["vol"]), int(m["sims"] or 0))
        rows.setdefault(key, {})[int(m["year"])] = t
    if not rows:
        print(f"rank: no summaries under {folder}")
        return 1
    years = sorted({y for r in rows.values() for y in r}, reverse=True)
    def worse(r):
        return min((r[y].get("net", 0.0) for y in years if y in r), default=float("-inf")) if all(y in r for y in years) else float("-inf")
    order = sorted(rows, key=lambda k: worse(rows[k]), reverse=True)
    lines = ["| min edge | 24 h volume floor | sims | " + " | ".join(f"{y} net (races up)" for y in years) + " | worse season |",
             "|---:|---:|---:|" + "---:|" * len(years) + "---:|"]
    for k in order:
        r = rows[k]
        cells = [f"{r[y]['net']:+,.0f} ({r[y]['races_up']}/{r[y]['races']})" if y in r else "not run" for y in years]
        lines.append(f"| {k[0]:g} | ${k[1]:,.0f} | {k[2] or 'default'} | " + " | ".join(cells) + f" | {worse(r):+,.0f} |")
    (folder / ("grid.md" if venue == "kalshi" else f"grid-{venue}.md")).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    for k in [k for k in order if k[2] == 0][:top]:
        print(f"TOP {k[0]:g} {k[1]:g}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["spikes"] and len(a) >= 2:
        sys.exit(spikes(a[1], a[2] if len(a) > 2 else "kalshi"))
    if a[:1] == ["rank"] and len(a) >= 2:
        sys.exit(rank(a[1], int(a[a.index("--top") + 1]) if "--top" in a else 3,
                      a[a.index("--venue") + 1] if "--venue" in a else "kalshi"))
    sys.exit(__doc__)
