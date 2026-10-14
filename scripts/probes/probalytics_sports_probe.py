"""Read-only probe: which sports Probalytics covers, wide (owner, 2026-10-14: "complete our sport coverage ... go wide
and just ignore and report if nothing comes up"). Every sport we have considered plus a wide net, matched by title /
slug / Kalshi series ticker (Probalytics carries no category or tags: all 243M markets have category ''), parlays
left out. This is discovery, so text matching is fine here; an import would use exact keys, as the F1 pull does.

For each sport and venue: markets (all / active), created and closing range, the top Kalshi series or Polymarket
title patterns with a sample, then fills (count, first, last) and one day of order books (2026-10-12).

    # LOCAL (Mac)
    python scripts/probes/probalytics_sports_probe.py      # -> reports/handoffs/<date>-probalytics-sports-probe/

Credentials as scripts/probes/probalytics_pull.py (.env.probalytics); never printed.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.argv = sys.argv[:1] + ["fills"]                    # probalytics_pull parses nothing at import; keep argv harmless
import probalytics_pull as P                           # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "handoffs" / f"{datetime.now(timezone.utc):%Y-%m-%d}-probalytics-sports-probe"
BOOK_DAY = "2026-10-12"

# order matters: the first match wins (MotoGP before F1's "grand prix", IndyCar before NASCAR's "500")
SPORTS = [
    ("motogp", r"motogp|moto ?gp|\bmoto[23]\b|kxmotogp"),
    ("indycar", r"indycar|indy ?500|indianapolis 500|kxindy"),
    ("nascar", r"nascar|daytona 500|cup series|kxnascar"),
    ("formula_e", r"formula e\b|e-prix|kxformulae"),
    ("f1", r"formula ?1|\bf1\b|grand prix|kxf1"),
    ("le_mans_wec", r"le mans|\bwec\b|endurance championship|24 hours of|kxlemans"),
    ("rally_dakar", r"\brally\b|\bwrc\b|dakar"),
    ("road_cycling", r"tour de france|giro d|vuelta|cycling|paris-roubaix|milan-san ?remo|tour of flanders|\buci\b|kxtdf"),
    ("mtb_downhill", r"mountain bike|downhill|\bmtb\b"),
    ("sailing", r"sailgp|america'?s cup|sailing"),
    ("golf", r"\bgolf|\bpga\b|lpga|liv golf|ryder cup|masters tournament|the masters|open championship|kxpga|kxgolf"),
    ("horse_racing", r"kentucky derby|preakness|belmont stakes|horse rac|grand national|breeders'? cup|kxkentucky"),
    ("athletics", r"marathon|olympic|athletics|\b100m\b|ironman|triathlon"),
    ("tennis", r"tennis|wimbledon|roland garros|french open|us open tennis|australian open|\batp\b|\bwta\b|kxatp|kxwta"),
    ("nfl", r"\bnfl\b|super bowl|pro football|kxnfl|kxsb"),
    ("nba", r"\bnba\b|kxnba"),
    ("mlb", r"\bmlb\b|world series|kxmlb"),
    ("nhl", r"\bnhl\b|stanley cup|kxnhl"),
    ("soccer", r"premier league|champions league|world cup|la liga|serie a|bundesliga|\bmls\b|\bepl\b|kxepl|kxucl"),
    ("weather", r"temperature|highest temp|rain in|snowfall|hurricane|kxhigh|kxrain"),
    ("us_politics", r"president|election|senate|congress|governor|kxpres"),
]


def lit(s):
    """A ClickHouse string literal: backslashes and quotes escaped (a regex's \\b must reach re2 intact)."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def classify_sql():
    arms = ", ".join(f"match(lower(concat(title, ' ', slug, ' ', platform_id)), {lit(rx)}), {lit(name)}"
                     for name, rx in SPORTS)
    return f"multiIf({arms}, '')"


def q(name, sql):
    t = time.time()
    try:
        body = P.ch(sql)
    except Exception as e:                              # report and go on: "ignore and report if nothing comes up"
        P.log(f"{name}: FAILED {str(e)[:300]}")
        (OUT / f"{name}.error.txt").write_text(str(e))
        return []
    (OUT / f"{name}.json").write_bytes(body)
    rows = json.loads(body)["data"]
    P.log(f"{name}: {len(rows)} rows, {time.time() - t:.0f}s")
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cls = classify_sql()
    base = f"FROM markets WHERE market_type != 'PARLAY'"
    markets = q("q1_markets_by_sport", f"""
        SELECT sport, toString(platform) AS venue, count() AS markets, countIf(status = 'ACTIVE') AS active,
               min(created_at) AS first_created, max(created_at) AS last_created,
               min(closes_at) AS first_close, max(closes_at) AS last_close
        FROM (SELECT *, {cls} AS sport {base}) WHERE sport != ''
        GROUP BY sport, venue ORDER BY sport, venue""")
    series = q("q2_top_series", f"""
        SELECT sport, venue, grp, n, sample FROM (
          SELECT sport, toString(platform) AS venue,
                 if(platform = 'KALSHI', splitByChar('-', platform_id)[1],
                    arrayStringConcat(arraySlice(splitByChar(' ', title), 1, 4), ' ')) AS grp,
                 count() AS n, any(title) AS sample
          FROM (SELECT *, {cls} AS sport {base}) WHERE sport != ''
          GROUP BY sport, venue, grp ORDER BY n DESC LIMIT 6 BY sport, venue)
        ORDER BY sport, venue, n DESC""")
    # one pass each over fills and one day of books: the sport comes from a join on the classified markets
    m = f"(SELECT id, sport FROM (SELECT id, {cls} AS sport {base}) WHERE sport != '')"
    fills = q("q3_fills_by_sport", f"""
        SELECT m.sport AS sport, toString(f.platform) AS venue, count() AS fills, uniqExact(f.market_id) AS markets,
               min(f.timestamp) AS first_fill, max(f.timestamp) AS last_fill,
               round(sum(toFloat64(f.price) * toFloat64(f.size))) AS notional
        FROM fills AS f INNER JOIN {m} AS m ON f.market_id = m.id
        GROUP BY sport, venue ORDER BY sport, venue""")
    books = q(f"q4_books_by_sport_{BOOK_DAY}", f"""
        SELECT m.sport AS sport, toString(o.platform) AS venue, count() AS snapshots, uniqExact(o.market_id) AS markets
        FROM (SELECT market_id, platform FROM orderbook_snapshots
              WHERE timestamp >= '{BOOK_DAY} 00:00:00' AND timestamp < toDateTime('{BOOK_DAY} 00:00:00') + INTERVAL 1 DAY) AS o
        INNER JOIN {m} AS m ON o.market_id = m.id
        GROUP BY sport, venue ORDER BY sport, venue""")
    (OUT / "summary.json").write_text(json.dumps(dict(markets=markets, series=series, fills=fills, books=books,
                                                      sports=[n for n, _ in SPORTS], book_day=BOOK_DAY), default=str))
    P.log(f"done -> {OUT}")


if __name__ == "__main__":
    main()
