"""
One standard shape for markets, across sports, time and venues.

    event (a race, or a competition's season)
      └─ outcome   (kind, subject[, opponent / team / n])   e.g. race_win · George Russell
           ├─ our fair value      (live forecast, or the last as-of price for a past race)
           ├─ venue quotes         Polymarket · Kalshi (soon) · our private book
           └─ result               (once the race has run)

`event_matrix` and `season_matrix` return one row per outcome with a column group
per venue, so the board, the event page and the book all read the same thing.
Adding a venue = a VENUES entry + its rows in `market_links` (exchange = code).
"""

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from racinglines import sports
from racinglines.db import reads as data
from racinglines.markets import private_book as house


@dataclass(frozen=True)
class Venue:
    code: str
    name: str
    status: str          # live | soon
    kind: str            # exchange | private
    url: str = ""        # event URL pattern ({slug})


# RACINGLINES_KALSHI_VENUE=1 (off by default): Kalshi shows as a live venue (its synced links' quotes on the board
# and race pages), and the Positions page lists the maker's Kalshi replay (`f1 demo-history --venue kalshi`,
# paper_positions.venue = 'kalshi'), which is otherwise hidden. The Strategy page stays Polymarket's record.
KALSHI_VENUE = os.environ.get("RACINGLINES_KALSHI_VENUE", "") == "1"
VENUES = [
    Venue("polymarket", "Polymarket", "live", "exchange", "https://polymarket.com/event/{slug}"),
    Venue("kalshi", "Kalshi", "live" if KALSHI_VENUE else "soon", "exchange", "https://kalshi.com/markets/{slug}"),
    Venue("private", "Private book", "live", "private"),
]
EXCHANGES = [v for v in VENUES if v.kind == "exchange"]

KIND_LABEL = {"race_pole": "Pole position", "race_win": "Win", "race_podium": "Podium", "race_top10": "Top 10", "race_make_final": "Makes the Final",
              "race_h2h": "Head-to-head", "race_constructor_top": "Top-scoring constructor",
              "champion": "Champion", "constructors_champion": "Constructors' champion",
              "season_wins_ge": "Season wins", "standings_h2h": "Championship head-to-head",
              "rank_up": "Rank up", "rank_down": "Rank down", "standings_top3": "Championship top 3"}
_SCHEMAS = sorted(map(sports.load, sports.SPORT_CODES), key=lambda s: s["sport"]["display_order"])
STANDARD_KINDS = {s["competition"]["code"]: tuple(s["markets"]["standard_kinds"]) for s in _SCHEMAS}   # sports/*.toml
SPORT_NAME = {s["competition"]["code"]: s["competition"].get("display_name", s["sport"]["name"]) for s in _SCHEMAS}
SPORT_ORDER = {s["competition"]["code"]: s["sport"]["display_order"] for s in _SCHEMAS}


TEAM_NAME = {"red_bull": "Red Bull", "rb": "Racing Bulls", "aston_martin": "Aston Martin", "mclaren": "McLaren",
             "sauber": "Audi (Sauber)", "haas": "Haas", "alpine": "Alpine", "williams": "Williams",
             "ferrari": "Ferrari", "mercedes": "Mercedes", "cadillac": "Cadillac"}


def team_name(t):
    return TEAM_NAME.get(t, str(t).replace("_", " ").title()) if t else t


def _n(v):
    return None if v is None or pd.isna(v) else float(v)


def _i(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v) else int(v)


def key(kind, athlete_id, params):
    p = params if isinstance(params, dict) else {}
    return (kind, _i(athlete_id), p.get("team"), _i(p.get("opponent_id")), _i(p.get("n")))


def race_info(conn, race_id):
    df = data.q(conn, """
        SELECT ra.id AS race_id, ra.event_id, e.name, e.status, e.start_date, e.source_key, v.name AS venue,
               co.code AS competition, co.id AS competition_id, ra.category_id, c.code AS category, s.year AS season,
               ra.format->>'event_name' AS event_name,
               (SELECT min((ro.extra->>'session_date')::timestamp) FROM rounds ro
                 WHERE ro.race_id = ra.id AND ro.kind IN ('race', 'final')) AS race_start
        FROM races ra JOIN events e ON e.id = ra.event_id JOIN seasons s ON s.id = e.season_id
        JOIN competitions co ON co.id = s.competition_id JOIN categories c ON c.id = ra.category_id
        LEFT JOIN venues v ON v.id = e.venue_id WHERE ra.id = :r""", r=race_id)
    if not len(df):
        return None
    info = df.iloc[0].to_dict()
    info["sport"] = SPORT_NAME.get(info["competition"], info["competition"])
    info["title"] = f"{info['venue']} GP" if info["competition"] == "f1_wdc" else info["venue"]
    return info


def pricing_run(conn, info):
    """Which run our fair values come from: the live forecast for upcoming races; for
    a past race, the latest as-of price made before it started (diagnostic, else a
    forecast created before the start)."""
    if info["status"] != "completed":
        rid, _ = data.latest_forecast_run(conn, info["competition_id"], info["category_id"])
        has = rid and len(data.q(conn, "SELECT 1 FROM race_predictions WHERE model_run_id = :m AND race_id = :r LIMIT 1",
                                 m=rid, r=info["race_id"]))
        if has:
            return dict(run_id=rid, source="live forecast", as_of=None)
    start = info["race_start"] if info["race_start"] is not None and not pd.isna(info["race_start"]) else \
        pd.Timestamp(info["start_date"])
    df = data.q(conn, """
        SELECT mr.id, mr.kind, coalesce((mr.params->>'cutoff')::timestamp, mr.created_at::timestamp) AS as_of
        FROM model_runs mr WHERE mr.kind IN ('diagnostic', 'forecast')
          AND EXISTS (SELECT 1 FROM race_predictions rp WHERE rp.model_run_id = mr.id AND rp.race_id = :r)
          AND coalesce((mr.params->>'cutoff')::timestamp, mr.created_at::timestamp) < :s
        ORDER BY as_of DESC LIMIT 1""", r=info["race_id"], s=pd.Timestamp(start).to_pydatetime())
    if len(df):
        r = df.iloc[0]
        return dict(run_id=int(r["id"]), source="as-of " + r["kind"], as_of=r["as_of"])
    return dict(run_id=None, source="no pre-race price", as_of=None)


def _exchange_rows(conn, links, cache, run_id):
    """market_links rows -> per-outcome exchange quotes (one row per question for binary pairs)."""
    out = {}
    if not len(links):
        return out
    links = links.sort_values("id")
    seen = set()
    for link in links.to_dict("records"):
        # a Polymarket binary question has two tokens (keep one); a Kalshi condition_id is the whole event
        q = link["token_id"] if link["exchange"] == "kalshi" else link["condition_id"]
        if link["prediction"] in ("race_h2h", "standings_h2h") and q in seen:
            continue
        seen.add(q)
        k = key(link["prediction"], link["athlete_id"], link["params"])
        fair = data.model_prob(conn, link, cache, run_id=run_id)[0] if link["prediction"] != "unmodeled" else None
        out.setdefault(k, {})[link["exchange"]] = dict(
            bid=_n(link["last_bid"]), ask=_n(link["last_ask"]), mid=_n(link["last_price"]), volume=_n(link["volume"]),
            slug=link["event_slug"], token=link["token_id"], link_id=link["id"], closed=link["closed"],
            question=link["question"], outcome=link["outcome"], fair=fair)
    return out


def _subject_names(conn, ids):
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    df = data.q(conn, "SELECT id, display_name FROM athletes WHERE id = ANY(:i)", i=ids)
    return dict(zip(df["id"], df["display_name"]))


def _assemble(conn, base, exch, priv, names, results=None):
    keys = list(dict.fromkeys(list(base) + list(exch) + list(priv)))
    rows = []
    for k in keys:
        kind, ath, team, opp, n = k
        b, e, p = base.get(k, {}), exch.get(k, {}), priv.get(k)
        fair = b.get("fair")
        if fair is None:
            fair = next((q["fair"] for q in e.values() if q.get("fair") is not None), None)
        subject = names.get(ath) or team_name(team) or (e and next(iter(e.values()))["outcome"]) or "?"
        detail = ""
        if opp is not None:
            detail = f"ahead of {names.get(opp, '?')}"
        elif n is not None:
            detail = f"{n}+"
        row = dict(kind=kind, kind_label=KIND_LABEL.get(kind, kind), athlete_id=ath, team=team, opponent_id=opp,
                   subject=subject, detail=detail, fair=fair, venues=e, private=p,
                   result=results.get(k) if results else None)
        pm = e.get("polymarket") or {}
        row["pm_mid"] = pm.get("mid")
        row["gap"] = (fair - pm["mid"]) if fair is not None and pm.get("mid") is not None else None
        rows.append(row)
    df = pd.DataFrame(rows)
    if len(df):
        df["sort"] = df["fair"].fillna(df["pm_mid"]).fillna(-1)
        df = df.sort_values(["kind", "sort"], ascending=[True, False])
    return df


def _private_rows(conn, race_id, maker_id):
    bk = house.book(conn, race_id, maker_id=maker_id)
    out = {}
    for r in bk.to_dict("records"):
        if r["status"] == "void":
            continue
        k = key(r["kind"], r["athlete_id"], r["params"])
        cur = out.get(k)
        if cur is None or (cur["status"] != "open" and r["status"] == "open"):
            out[k] = dict(market_id=r["id"], yes=_n(r["yes_price"]), no=_n(r["no_price"]), status=r["status"], bets=int(r["bets"]),
                          staked=float(r["staked"]), worst=float(r["worst"]), ev=float(r["ev"]), maker=r["maker"],
                          settled_pnl=_n(r["settled_pnl"]))
    return out


def event_matrix(conn, race_id, maker_id=house.ALL):
    """(info, pricing, outcomes DataFrame) for one race."""
    info = race_info(conn, race_id)
    if info is None:
        return None, None, pd.DataFrame()
    pricing = pricing_run(conn, info)
    run_id = pricing["run_id"]
    base = {}
    if run_id:
        preds = data.q(conn, """SELECT athlete_id, win_prob, podium_prob, top10_prob, make_final_prob
                                FROM race_predictions WHERE model_run_id = :m AND race_id = :r""", m=run_id, r=race_id)
        for kind in STANDARD_KINDS.get(info["competition"], ("race_win", "race_podium")):
            col = house.PROB_FIELD[kind]
            for a, p in zip(preds["athlete_id"], preds[col]):
                if p is not None and not pd.isna(p):
                    base[key(kind, a, None)] = dict(fair=float(p))
    links = data.q(conn, "SELECT * FROM market_links WHERE race_id = :r AND prediction <> 'unmodeled'", r=race_id)
    exch = _exchange_rows(conn, links, {}, run_id)
    priv = _private_rows(conn, race_id, maker_id)
    results = None
    if info["status"] == "completed":
        # compare with the exchange as it was when we priced, not its resolved price
        at = pricing.get("as_of")
        toks = [q["token"] for e in exch.values() for q in e.values()]
        from racinglines.markets import store as MS
        then = MS.last_before(conn, toks, pd.Timestamp(at).tz_localize("UTC")) if at is not None and toks else {}
        for e in exch.values():
            for q in e.values():
                q["resolved_mid"] = q["mid"]
                q["mid"], q["bid"], q["ask"], q["at_as_of"] = _n(then.get(q["token"])), None, None, True
        res = house.race_outcomes(conn, race_id)
        results = {k: house.outcome_for(k[0], k[1], {"team": k[2], "opponent_id": k[3]}, res)
                   for k in set(base) | set(exch) | set(priv)}
    ids = {k[1] for k in list(base) + list(exch) + list(priv)} | {k[3] for k in list(exch) + list(priv)}
    return info, pricing, _assemble(conn, base, exch, priv, _subject_names(conn, ids), results)


def season_matrix(conn, competition, maker_id=house.ALL):
    """(info, pricing, outcomes) for a competition's season-long markets."""
    comp = data.q(conn, "SELECT id, name FROM competitions WHERE code = :c", c=competition)
    if not len(comp):
        return None, None, pd.DataFrame()
    comp_id = int(comp["id"].iloc[0])
    run_id, metrics = data.latest_forecast_run(conn, comp_id)
    base = {}
    if run_id:
        st = data.standings_predictions(conn, run_id)
        for a, p in zip(st["athlete_id"], st["champion_prob"]):
            if p is not None and not pd.isna(p):
                base[key("champion", a, None)] = dict(fair=float(p))
        for c in (metrics or {}).get("constructors", []):
            if not isinstance(c.get("team_key"), str):
                continue
            base[key("constructors_champion", None, {"team": c.get("team_key")})] = dict(fair=c.get("champion_prob"))
    links = data.q(conn, """SELECT * FROM market_links WHERE competition_id = :c AND race_id IS NULL
                            AND prediction <> 'unmodeled' AND NOT closed""", c=comp_id)
    exch = _exchange_rows(conn, links, {}, None)
    season_links = set(links["id"].astype(int)) if len(links) else set()
    bk = house.book(conn, 0, maker_id=maker_id)
    bk = bk[bk["market_link_id"].isin(season_links)] if len(bk) else bk
    priv = {}
    for r in bk.to_dict("records"):
        if r["status"] != "void":
            priv[key(r["kind"], r["athlete_id"], r["params"])] = dict(
                market_id=r["id"], yes=_n(r["yes_price"]), no=_n(r["no_price"]), status=r["status"], bets=int(r["bets"]),
                staked=float(r["staked"]), worst=float(r["worst"]), ev=float(r["ev"]), maker=r["maker"],
                settled_pnl=_n(r["settled_pnl"]))
    ids = {k[1] for k in list(base) + list(exch) + list(priv)} | {k[3] for k in list(exch) + list(priv)}
    info = dict(competition=competition, competition_id=comp_id, name=comp["name"].iloc[0],
                sport=SPORT_NAME.get(competition, competition), title=f"{comp['name'].iloc[0]}")
    return info, dict(run_id=run_id, source="live forecast", as_of=None), \
        _assemble(conn, base, exch, priv, _subject_names(conn, ids))


def venue_summary(outcomes):
    """Per venue: status, number of outcomes listed, volume."""
    out = []
    for v in VENUES:
        if v.kind == "private":
            n = int(outcomes["private"].notna().sum()) if len(outcomes) else 0
            out.append(dict(venue=v, listed=n, volume=None,
                            staked=float(sum(p["staked"] for p in outcomes["private"].dropna())) if n else 0.0))
            continue
        quotes = [q[v.code] for q in (outcomes["venues"] if len(outcomes) else []) if v.code in q]
        vol = {}
        for q in quotes:
            vol[q["question"]] = float(q["volume"]) if q["volume"] is not None and pd.notna(q["volume"]) else 0.0
        out.append(dict(venue=v, listed=len(quotes), volume=sum(vol.values()) if quotes else None,
                        slug=quotes[0]["slug"] if quotes else None))
    return out


def price_series(conn, tokens, start, end, points=120):
    """Exchange price history (stored minute/hourly prices plus recorded book mids)
    for a few tokens, resampled to ~`points` steps. -> {token: [(ts, price), ...]}"""
    if not tokens:
        return {}
    from racinglines.markets import store as MS
    px = MS.read(conn, "prices", tokens=list(tokens), start=start, end=end)[["token_id", "ts", "price"]]
    bk = MS.read(conn, "books", tokens=list(tokens), start=start, end=end)
    bk = bk.dropna(subset=["best_bid", "best_ask"]).assign(price=lambda d: (d["best_bid"] + d["best_ask"]) / 2)
    df = pd.concat([px, bk[["token_id", "ts", "price"]]], ignore_index=True)
    out = {}
    if not len(df):
        return out
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    step = max((pd.Timestamp(end) - pd.Timestamp(start)) / points, pd.Timedelta(minutes=1))
    for tok, g in df.groupby("token_id"):
        s = g.set_index("ts")["price"].sort_index().resample(step).last().ffill().dropna()
        out[tok] = list(zip(s.index, s.to_numpy(float)))
    return out
