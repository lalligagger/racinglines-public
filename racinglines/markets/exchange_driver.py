"""
The generic exchange driver: reads an exchange schema (exchanges/<code>.toml, racinglines/exchanges.py) and does what
markets/kalshi/{client,sync}.py do for Kalshi, for any venue with a plain JSON market-data API: sync its markets into
market_links (exchange = <code>), keep the quotes fresh, and store the tape, price history and order books in the
shared tables (market_trades, market_price_history, market_book_snapshots), archived per exchange like the others.

Nothing here knows a venue: hosts, endpoints, field paths, price units, fees and how a market is named come from
the schema. Read-only by construction: the driver only issues GETs of public market data, and there is no order code.

    Client(schema)                         GET an endpoint; paged / batched calls as the schema says
    sync(session, conn, code, sport)       events -> instruments -> market_links (+ quotes), one call
    fetch_trades / fetch_history / snapshot_books                      the tape, minute prices and books
    fair_report(conn, code, sport)         the model's fair price beside the exchange's quote, net of the fee

Prediction kinds come from the schema's per-sport rules (a regex on the market's contract name); the subject is
matched to a driver or team by the sport's resolver (F1: markets/polymarket/sync.Resolver). A sport listed without
`modeled = true` is tape-only: every link is `unmodeled`, under that sport's own competition.
"""

import re
from datetime import datetime, timezone

import httpx
import pandas as pd
from sqlalchemy import select, text

from racinglines import exchanges as EX
from racinglines.db import models as m
from racinglines.sources import http

# ----- values -----

def when(v, unit):
    """A time from the exchange's number (ms / ns / s since the epoch) or ISO string, as aware UTC; None if missing."""
    if v in (None, ""):
        return None
    if unit == "iso":
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    div = {"s": 1, "ms": 1e3, "ns": 1e9}[unit]
    return datetime.fromtimestamp(float(v) / div, tz=timezone.utc)


def utc(t):
    """A pandas Timestamp in UTC (a naive one is taken as UTC)."""
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def epoch(t, unit):
    """A time as the exchange's integer (the inverse of `when`)."""
    mult = {"s": 1, "ms": 1000, "ns": 1_000_000_000}[unit]
    return int(utc(t).timestamp() * mult)


def price(v):
    """A price as a probability: the schema's prices are dollars 0..1 as strings; None for missing or empty."""
    if v in (None, ""):
        return None
    return float(v)


def quote(bid, ask, last):
    """(bid, ask, mid): an empty side is None; mid = the middle when both sides quote, else the last price."""
    bid = None if not bid else bid
    ask = None if ask is None or ask >= 1.0 else ask
    mid = (bid + ask) / 2 if bid is not None and ask is not None else last
    return bid, ask, mid


# ----- the client -----

class Client:
    """Read-only client for one exchange schema. `transport` (an httpx transport) replaces the network in tests."""

    def __init__(self, code, host=None, transport=None):
        import os
        self.code, self.schema = code, EX.load(code)
        api = self.schema["api"]
        host = host or os.environ.get(api.get("host_env", ""), "") or api["host"]
        http.HOST_INTERVAL.setdefault(httpx.URL(host).host, 1 / api.get("max_per_second", 4))
        self.http = httpx.Client(base_url=host.rstrip("/") + api.get("prefix", ""), timeout=api.get("timeout", 20),
                                 transport=transport)

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def call(self, endpoint, **params):
        """The parsed response of a schema endpoint; raises on HTTP errors or the exchange's own error code."""
        ep, api = self.schema["endpoints"][endpoint], self.schema["api"]
        q = {**ep.get("params", {}), **{k: v for k, v in params.items() if v is not None}}
        r = http.get(self.http, ep["path"], params=q)
        r.raise_for_status()
        body = r.json()
        if EX.dig(body, api["ok_path"]) != api["ok_value"]:
            raise RuntimeError(f"{self.code} {endpoint}: {EX.dig(body, api.get('error_path', 'message')) or body}")
        return body

    def rows(self, endpoint, **params):
        body = self.call(endpoint, **params)
        return EX.dig(body, self.schema["endpoints"][endpoint]["data"]) or []

    def paged(self, endpoint, **params):
        """Every row of a cursor-paged endpoint."""
        ep, out, cursor = self.schema["endpoints"][endpoint], [], None
        while True:
            body = self.call(endpoint, **{ep["cursor_param"]: cursor}, **params)
            out += EX.dig(body, ep["data"]) or []
            cursor = EX.dig(body, ep["next"])
            if not cursor:
                return out

    def batched(self, endpoint, values, **params):
        """Every row of an endpoint that takes comma-separated ids, `batch_size` at a time (and paged, if it pages)."""
        ep, out = self.schema["endpoints"][endpoint], []
        values = list(values)
        for i in range(0, len(values), ep.get("batch_size", 25)):
            part = {ep["batch_param"]: ",".join(values[i:i + ep.get("batch_size", 25)]), **params}
            out += self.paged(endpoint, **part) if "cursor_param" in ep else self.rows(endpoint, **part)
        return out

    def book(self, instrument):
        return self.call("book", **{self.schema["endpoints"]["book"]["instrument_param"]: instrument})

    def window(self, endpoint, instrument, start, end=None):
        """A time-windowed endpoint (trades, history) for one instrument; the window is clipped to the schema's
        `window_days` (the exchange keeps about that much)."""
        ep = self.schema["endpoints"][endpoint]
        start = utc(start)
        start = max(start, pd.Timestamp.now("UTC") - pd.Timedelta(days=ep["window_days"]))
        p = {ep["instrument_param"]: instrument, ep["start_param"]: epoch(start, ep["start_unit"])}
        if ep.get("end_param"):
            p[ep["end_param"]] = epoch(utc(end) if end else pd.Timestamp.now("UTC"), ep["start_unit"])
        return self.rows(endpoint, **p)


# ----- discovery and links -----

def sport_cfg(schema, sport):
    if sport not in schema.get("sports", {}):
        raise ValueError(f"{schema['exchange']['code']} lists no {sport!r} (exchanges/{schema['exchange']['code']}.toml [sports.*])")
    return schema["sports"][sport]


def discover(client, sport):
    """(events, instruments) the exchange lists for `sport`: events whose symbol starts with one of the schema's
    prefixes, then their instruments. Settled or expired instruments have left the listing."""
    cfg, f = sport_cfg(client.schema, sport), client.schema["fields"]
    prefixes = tuple(cfg["event_prefixes"])
    events = [e for e in client.paged("events") if str(EX.dig(e, f["event"]["id"]) or "").startswith(prefixes)]
    ids = [EX.dig(e, f["event"]["id"]) for e in events]
    return events, client.batched("instruments", ids) if ids else []


def classify(schema, sport, contract):
    """(prediction kind, subject kind) for a market's contract name, from the sport's rules; else unmodeled."""
    cfg = sport_cfg(schema, sport)
    if not cfg.get("modeled"):
        return "unmodeled", None
    for rule in cfg.get("rules", []):
        if re.search(rule["contract"], contract or "", re.I):
            return rule["kind"], rule.get("subject")
    return "unmodeled", None


def link_rows(schema, sport, instruments, tickers, resolver=None):
    """market_links values (with token_id) for every instrument. tickers: {instrument: ticker row}, for the quotes.
    resolver: driver(name), team(name) -> id / team key, only for a modeled sport."""
    f, code = schema["fields"], schema["exchange"]["code"]
    fi, ft = f["instrument"], f["ticker"]
    rows = []
    for inst in instruments:
        tok = EX.dig(inst, fi["id"])
        subject = EX.dig(inst, fi["subject"]) or ""
        contract = EX.dig(inst, fi["contract"]) or EX.dig(inst, fi["event_title"]) or ""
        kind, who = classify(schema, sport, contract)
        athlete_id, params = None, {}
        if kind != "unmodeled":
            if who == "driver":
                athlete_id = resolver.driver(subject)
            elif who == "team":
                params["team"] = resolver.team(subject)
            if athlete_id is None and not params.get("team"):
                kind = "unmodeled"                       # a subject we can't match to our drivers or teams
        tk = tickers.get(tok) or {}
        bid, ask, mid = quote(price(EX.dig(tk, ft["bid"])), price(EX.dig(tk, ft["ask"])), price(EX.dig(tk, ft["last"])))
        vol = EX.dig(tk, ft["volume"])
        tick = price(EX.dig(inst, fi["tick"]))
        rows.append(dict(
            token_id=tok, exchange=code, market_slug=tok,
            question=contract or EX.dig(inst, fi["title"]) or tok, condition_id=EX.dig(inst, fi["event"]),
            outcome=subject or "Yes", neg_risk=False, tick_size=tick or 0.01, min_size=1.0,
            athlete_id=athlete_id, race_id=None, prediction=kind, invert=False,
            params={k: v for k, v in dict(params, **({"contract": contract} if contract else {})).items() if v is not None},
            event_slug=EX.dig(inst, fi["event"]), event_title=EX.dig(inst, fi["event_title"]) or contract,
            group_title=subject or None, last_bid=bid, last_ask=ask, last_price=mid,
            volume=float(vol) if vol not in (None, "") else None,
            end_date=when(EX.dig(inst, fi["expiry"]), fi.get("expiry_unit", "ms")),
            closed=EX.dig(inst, fi["tradable"]) is False, resolved_yes=None,
            active=EX.dig(inst, fi["tradable"]) is not False))
    return rows


def _tickers(client, ids):
    ft = client.schema["fields"]["ticker"]
    return {EX.dig(t, ft["instrument"]): t for t in client.batched("tickers", ids)}


def sync(session, conn, code, sport="f1", year=2026, client=None, resolver=None):
    """Upsert one market_links row per instrument the exchange lists for `sport`, with its current quote. Idempotent;
    links of instruments that have left the listing are marked closed. Returns stats."""
    from racinglines.markets.kalshi.sync import competition
    schema = EX.load(code)
    comp, cat = competition(session, sport)
    client = client or Client(code)
    events, instruments = discover(client, sport)
    ids = [EX.dig(i, schema["fields"]["instrument"]["id"]) for i in instruments]
    tickers = _tickers(client, ids) if ids else {}
    if resolver is None and sport_cfg(schema, sport).get("modeled"):
        from racinglines.markets.polymarket.sync import Resolver
        resolver = Resolver(conn, year)
    rows = link_rows(schema, sport, instruments, tickers, resolver)
    now = datetime.now(timezone.utc)
    stats = dict(events=len(events), links=0, modeled=0, unmatched=0, new=0, closed=0)
    for row in rows:
        tok = row.pop("token_id")
        values = dict(row, competition_id=comp.id, category_id=cat.id, synced_at=now)
        link = session.scalars(select(m.MarketLink).filter_by(exchange=code, token_id=tok)).first()
        if link is None:
            session.add(m.MarketLink(token_id=tok, first_seen_at=now, **values))
            stats["new"] += 1
        else:
            for k, v in values.items():
                setattr(link, k, v)
        stats["links"] += 1
        stats["modeled" if row["prediction"] != "unmodeled" else "unmatched"] += 1
    live, prefixes = set(ids), tuple(sport_cfg(schema, sport)["event_prefixes"])
    for link in session.scalars(select(m.MarketLink).filter_by(exchange=code, closed=False, competition_id=comp.id)):
        if link.token_id not in live and (link.condition_id or "").startswith(prefixes):      # left the listing
            link.closed, link.active = True, False
            stats["closed"] += 1
    session.commit()
    return stats


# ----- the tape, minute prices and books -----

def links_of(conn, code, sport=None, events=None, open_only=False):
    """(token, event) of the exchange's links, for a sport's competition or the given events."""
    where, params = ["l.exchange = :x"], dict(x=code)
    if events:
        where.append("l.condition_id = ANY(:e)")
        params["e"] = list(events)
    elif sport:
        from racinglines import sports
        where.append("co.code = :c")
        params["c"] = sports.load(sport)["competition"]["code"]
    else:
        raise ValueError("give events or a sport")
    if open_only:
        where.append("NOT l.closed")
    return conn.execute(text(f"""SELECT l.token_id, l.condition_id FROM market_links l
                                 LEFT JOIN competitions co ON co.id = l.competition_id
                                 WHERE {' AND '.join(where)} ORDER BY l.condition_id, l.token_id"""), params).all()


def trade_rows(schema, token, event, trades):
    """market_trades rows: the taker's side of the YES contract at the YES price, size in contracts."""
    ft, rows = schema["fields"]["trade"], []
    for t in trades:
        p = price(EX.dig(t, ft["price"]))
        ts = when(EX.dig(t, ft["ts"]), ft["ts_unit"])
        if p is None or ts is None:
            continue
        rows.append(dict(token_id=token, condition_id=event or token, outcome_index=0, ts=ts,
                         side="BUY" if str(EX.dig(t, ft["side"]) or "").lower() == "buy" else "SELL", price=p,
                         size=float(EX.dig(t, ft["size"]) or 0), tx_hash=str(EX.dig(t, ft["id"]))[:80], wallet=""))
    return rows


def fetch_trades(session, conn, code, sport=None, events=None, since=None, client=None):
    """Store every trade the exchange still serves for the markets. Idempotent. Returns trades stored."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    client = client or Client(code)
    since = since or pd.Timestamp("2000-01-01", tz="UTC")           # clipped to the schema's window
    n = 0
    for tok, ev in links_of(conn, code, sport, events):
        rows = trade_rows(client.schema, tok, ev, client.window("trades", tok, since))
        for i in range(0, len(rows), 1000):
            session.execute(pg_insert(m.MarketTrade).values(rows[i:i + 1000]).on_conflict_do_nothing(constraint="uq_market_trade"))
        n += len(rows)
    session.commit()
    return n


def history_rows(schema, token, points):
    """market_price_history rows from the exchange's minute quotes: the bid/ask mid, else the last price."""
    fh, rows = schema["fields"]["history"], []
    for p in points:
        _, _, mid = quote(price(EX.dig(p, fh["bid"])), price(EX.dig(p, fh["ask"])), price(EX.dig(p, fh["last"])))
        ts = when(EX.dig(p, fh["ts"]), fh["ts_unit"])
        if mid is not None and ts is not None:
            rows.append(dict(token_id=token, ts=ts, price=mid))
    return rows


def fetch_history(session, conn, code, start, end=None, sport=None, events=None, client=None):
    """Store the exchange's minute prices for the markets from `start` (clipped to what it keeps). Returns rows."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    client = client or Client(code)
    n = 0
    for tok, _ in links_of(conn, code, sport, events):
        rows = history_rows(client.schema, tok, client.window("history", tok, start, end))
        if rows:
            session.execute(pg_insert(m.MarketPriceHistory).values(rows).on_conflict_do_update(
                index_elements=["token_id", "ts"], set_={"price": pg_insert(m.MarketPriceHistory).excluded.price}))
        n += len(rows)
    session.commit()
    return n


def book_row(schema, token, body, depth=10):
    """A market_book_snapshots row from the exchange's book: levels [[price, quantity]] best first."""
    fb = schema["fields"]["book"]
    bids = sorted(((float(p), float(q)) for p, q in EX.dig(body, fb["bids"]) or []), reverse=True)
    asks = sorted((float(p), float(q)) for p, q in EX.dig(body, fb["asks"]) or [])
    ts = when(EX.dig(body, fb["ts"]), fb["ts_unit"]) or datetime.now(timezone.utc)
    return dict(token_id=token, ts=ts, best_bid=bids[0][0] if bids else None, best_ask=asks[0][0] if asks else None,
                bids=[list(x) for x in bids[:depth]], asks=[list(x) for x in asks[:depth]])


def snapshot_books(session, conn, code, sport=None, events=None, depth=10, client=None):
    """One order-book snapshot per open market. Returns snapshots stored."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    client = client or Client(code)
    rows = [book_row(client.schema, tok, client.book(tok), depth) for tok, _ in links_of(conn, code, sport, events, open_only=True)]
    if rows:
        session.execute(pg_insert(m.MarketBookSnapshot).values(rows).on_conflict_do_nothing())
        session.commit()
    return len(rows)


# ----- the fair-price indicator -----

def fair_report(conn, code, sport="f1"):
    """The model's fair price beside the exchange's quote, for every open market the model prices.

    edge_yes = fair - ask - fee (buy YES at the ask); edge_no = bid - fair - fee (buy NO at 1 - bid). The fee is the
    schema's taker fee per contract. `call` is the side with a positive edge after the fee, else "". A thin book
    (no bid, a 1-cent ask) shows the fair price and no call: a quote nobody will trade against is not an edge.
    Returns a DataFrame sorted by the larger edge."""
    from racinglines import sports
    from racinglines.db import reads as data
    from racinglines.markets import venues
    fee = EX.load(code)["exchange"].get("taker_fee_per_contract", 0.0)
    links = data.q(conn, """SELECT l.* FROM market_links l JOIN competitions co ON co.id = l.competition_id
                            WHERE l.exchange = :x AND co.code = :c AND NOT l.closed AND l.prediction <> 'unmodeled'
                            ORDER BY l.event_slug, l.token_id""", x=code, c=sports.load(sport)["competition"]["code"])
    cache, out = {}, []
    for link in links.to_dict("records"):
        fair, run = data.model_prob(conn, link, cache)
        if fair is None:
            continue
        bid, ask, mid = link["last_bid"], link["last_ask"], link["last_price"]
        bid = None if bid is None or pd.isna(bid) else float(bid)
        ask = None if ask is None or pd.isna(ask) else float(ask)
        e = venues.net_edge(fee, fair, bid, ask)                # the same arithmetic the app shows
        out.append(dict(event=link["event_title"], subject=link["group_title"], kind=link["prediction"], fair=fair,
                        bid=bid, ask=ask, mid=None if mid is None or pd.isna(mid) else float(mid), edge_yes=e["edge_yes"],
                        edge_no=e["edge_no"], call=e["call"], token=link["token_id"], run_id=run))
    df = pd.DataFrame(out)
    if len(df):
        df["best"] = df[["edge_yes", "edge_no"]].max(axis=1)
        df = df.sort_values("best", ascending=False, na_position="last").drop(columns="best").reset_index(drop=True)
    return df


def fair_text(df, code, fee):
    """The fair-price report as text."""
    if not len(df):
        return f"{code}: no open market the model prices (run `racinglines markets --exchange {code} sync` first)"
    L = [f"{EX.load(code)['exchange']['name']}: model fair price vs the quote (taker fee ${fee:.2f} per contract, unverified)",
         f"{'market':<34}{'fair':>7}{'bid':>7}{'ask':>7}{'edge YES':>10}{'edge NO':>9}  call"]
    for r in df.itertuples():
        f = lambda v: "   –  " if v is None or pd.isna(v) else f"{v:6.2f}"          # noqa: E731
        e = lambda v: "     –  " if v is None or pd.isna(v) else f"{v:+8.2f}"          # noqa: E731
        L.append(f"{(r.event or '')[:20] + ' · ' + str(r.subject)[:12]:<34}{r.fair:7.2f}{f(r.bid)}{f(r.ask)}{e(r.edge_yes)}{e(r.edge_no)}  {r.call}")
    return "\n".join(L)
