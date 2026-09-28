"""
Venues in a backtest (docs/backtest-core.md, step 4): where a strategy's orders would have met prices,
read only as of each moment. Every venue gives the same four things:

    markets()             the venue's markets on the event: key, kind, subject, athlete / params
    view(market, t)       what was public at t: price (None when stale or absent), 24 h volume, tradeable
    cost / fill           the venue's costs per share and how an order fills (the strategies apply them)
    resolve(market, res)  YES / NO / None from the official result (markets/kinds.py's settlement)

    Polymarket(conn, w, start, end)          the recorded price history and trade tape (the F1 sweep reads it)
    Kalshi(conn, links, start, end)          the same for Kalshi's markets (markets/kalshi/ writes the same tables),
                                             with Kalshi's taker fee; built on mocked data, read by nothing yet
    PrivateBook.from_run(run_dir)            a live run's private book: our quotes and the simulated crowd,
                                             replayed from the logged polls and seeds (exactly, by default,
                                             or under another quoting rule)

A venue reads nothing after t in view(), so strategies can't look ahead through it; settlement is a
separate call made after trading. Another exchange is one more class with these methods; the display side
of venues (links, names, the board) is markets/venues.py.
"""

import gzip
import json
import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from racinglines.core.stats import last_at
from racinglines.markets import crowd as C

STALE = timedelta(hours=6)           # a price older than this is no price


class Polymarket:
    """Recorded Polymarket data for one weekend: 5-minute prices per token, the trade tape for liquidity,
    and the multi-outcome coherence check (a group whose prices don't sum near its target isn't traded)."""

    code = "polymarket"

    def __init__(self, conn, links, start, end, group_target=None, coherence_tol=0.25, stale=STALE):
        from racinglines.markets import store as MS
        self.links = links
        self.stale = stale
        self.group_target = group_target or {}
        self.coherence_tol = coherence_tol
        a, b = pd.Timestamp(start).tz_localize("UTC"), pd.Timestamp(end).tz_localize("UTC")
        ph = MS.read(conn, "prices", tokens=links["token_id"].tolist(), start=a, end=b)[["token_id", "ts", "price"]]
        tr = MS.read(conn, "trades", conditions=links["condition_id"].tolist(), start=a - timedelta(hours=24), end=b)
        tr = tr.assign(usd=tr["price"] * tr["size"])[["condition_id", "ts", "usd"]]
        for df in (ph, tr):
            df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
        self.prices = {t: g for t, g in ph.groupby("token_id")}
        self.trades = {c: g for c, g in tr.groupby("condition_id")}

    def markets(self):
        return self.links.to_dict("records")

    def price(self, token, t):
        g = self.prices.get(token)
        return None if g is None else last_at(pd.DatetimeIndex(g["ts"]), g["price"].to_numpy(), t, self.stale)

    def volume_24h(self, condition, t):
        g = self.trades.get(condition)
        if g is None:
            return 0.0
        a, b = g["ts"].searchsorted(t - timedelta(hours=24)), g["ts"].searchsorted(t, side="right")
        return float(g["usd"].iloc[a:b].sum())

    def coherent(self, kind, t):
        """A multi-outcome group's prices at t sum to within tolerance of its target (stale books skipped);
        True for kinds that aren't groups."""
        if kind not in self.group_target:
            return True
        target = self.group_target[kind]
        ps = [self.price(tok, t) for tok in self.links.loc[self.links["prediction"] == kind, "token_id"]]
        ps = [p for p in ps if p is not None]
        return bool(ps) and abs(sum(ps) - target) <= self.coherence_tol * target

    def view(self, market, t, min_volume_24h):
        """(price, volume_24h, tradeable-by-the-venue): priced, strictly inside (0, 1) and liquid enough."""
        p = self.price(market["token_id"], t)
        v = self.volume_24h(market["condition_id"], t)
        return p, v, p is not None and 0 < p < 1 and v >= min_volume_24h

    @staticmethod
    def resolve(market, res):
        from racinglines.markets import private_book as house
        ath = None if pd.isna(market["athlete_id"]) else int(market["athlete_id"])
        return house.outcome_for(market["prediction"], ath, market["params"], res)


class Kalshi(Polymarket):
    """Recorded Kalshi data for one weekend: markets/kalshi/sync.py stores Kalshi's candlesticks, tape (contracts
    pay $1, so USD volume = price x contracts) and links (exchange 'kalshi', token = the market's YES contract) in
    the tables Polymarket uses, so reading them is the same. What differs is the fee: Kalshi charges takers
    ceil(TAKER_FEE x contracts x P x (1 - P)) in cents per order (Kalshi's published schedule for most markets;
    check the market's own before relying on it). Built and tested on mocked data only."""

    code = "kalshi"
    TAKER_FEE = 0.07

    @classmethod
    def taker_fee(cls, price, contracts):
        """Dollars for one taker order of `contracts` at `price` (rounded up to the cent)."""
        return math.ceil(round(cls.TAKER_FEE * contracts * price * (1 - price) * 100, 6)) / 100

    @staticmethod
    def links(conn, race_id, kinds):
        """The race's Kalshi links of these kinds, one per market (the YES contract)."""
        from sqlalchemy import text
        return pd.read_sql(text("""SELECT ml.*, a.display_name AS athlete FROM market_links ml
                                   LEFT JOIN athletes a ON a.id = ml.athlete_id
                                   WHERE ml.race_id = :r AND ml.prediction = ANY(:k) AND ml.exchange = 'kalshi'
                                   ORDER BY ml.id"""), conn, params=dict(r=race_id, k=list(kinds)))


# ---------------------------------------------------------------------------
# The private book: our quotes, the simulated crowd
# ---------------------------------------------------------------------------

def _snaps(run_dir):
    out = {}
    for f in sorted((run_dir / "snaps").glob("*.json.gz")):
        with gzip.open(f, "rt") as g:
            s = json.load(g)
        out[s.get("ts")] = s
    return out


def _read_jsonl(p):
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


class PrivateBook:
    """A live run's private book replayed as a backtest. Each poll is what the crowd saw and how it was
    drawn: the quotes, the logged seed, and the rate (downhill: one poll's hits, scaled by the poll interval
    and the late pace; F1: one window's batch). Replaying with the recorded quotes re-derives the live
    book exactly; `quoter` re-quotes every market from its fair value and the replayed inventory instead,
    to backtest another quoting rule against the same crowd draws."""

    code = "private"

    def __init__(self, polls, params, outcomes, fair):
        self.polls, self.params, self.outcomes, self.fair = polls, params, outcomes, fair

    @classmethod
    def from_run(cls, run_dir):
        run_dir = Path(run_dir)
        meta = json.loads((run_dir / "meta.json").read_text())
        latest = json.loads((run_dir / "latest.json").read_text())
        sport = latest.get("sport") or ("mtb_dh" if "slug" in meta else "f1")
        snaps = _snaps(run_dir)
        crowd = _read_jsonl(run_dir / "crowd.jsonl")
        if sport == "mtb_dh":
            return cls._downhill(meta, latest, snaps, crowd)
        return cls._windows(latest, snaps, crowd, run_dir)

    @classmethod
    def _downhill(cls, meta, latest, snaps, crowd):
        from racinglines.pipelines import live_dh as L
        p = meta["params"]
        params = C.Params(takers=p["CROWD"], p=p["CROWD_P"], budget=tuple(p["CROWD_BUDGET"]), bet=tuple(p["CROWD_BET"]),
                          min_bet=p["MIN_BET"], max_pos=p["MAX_POS"], seed=L.CROWD_SEED, late_cap=p["LATE_CAP"],
                          late_pace=p["LATE_PACE"])
        polls = []
        for e in crowd:
            s = snaps.get(e["ts"])
            if s is None:
                raise ValueError(f"no snapshot for the crowd poll at {e['ts']}")
            b = s.get("betting") or {}
            late = bool(b.get("late"))
            rate = (b.get("interval") or L.BASE_INTERVAL) / L.BASE_INTERVAL * (params.late_pace if late else 1.0)
            polls.append(dict(ts=e["ts"], seed=e["seed"], quotes=s["quotes"], late=late, late_at=b.get("late_at"),
                              done=bool(s.get("done")), mode="poll", intensity=rate))
        outcomes = {f"{o['bib']}:{o['market']}": o["yes"] for o in latest.get("outcomes") or []}
        fair = {C.mkey(q): q["fair"] for q in latest.get("quotes") or []}
        return cls(polls, params, outcomes, fair)

    @classmethod
    def _windows(cls, latest, snaps, crowd, run_dir):
        live = json.loads((run_dir / "meta.json").read_text()).get("settings") or {}
        params = C.Params.from_dict(dict(live.get("crowd") or {}, max_loss=(live.get("quoting") or {}).get("max_loss")))
        order = sorted(snaps)
        polls = []
        for e in crowd:
            start = e["window"][0]
            prev = [ts for ts in order if ts <= start]              # the quotes posted when the window opened
            quotes = [dict(key=m["key"], fair=m["fair"], bid=m.get("bid"), ask=m.get("ask"))
                      for m in (snaps[prev[-1]].get("markets") if prev else [])]
            polls.append(dict(ts=e["ts"], seed=e["seed"], quotes=quotes, late=bool(e.get("late")), done=False,
                              mode="window", window=e["window"]))
        outcomes = {o["key"]: o["yes"] for o in latest.get("outcomes") or []}
        fair = {m["key"]: m["fair"] for m in latest.get("markets") or []}
        return cls(polls, params, outcomes, fair)

    def replay(self, quoter=None):
        """The book after every poll. quoter(quote, inv) -> (bid, ask): None = the recorded quotes.
        Returns dict(book, fills, pnl) (P&L settled where the outcome is known, else marked to fair)."""
        p = self.params
        book = C.new_book(p)
        fills = []
        for e in self.polls:
            if e["late"] and not book.get("late"):
                C.open_late(book, p, e.get("late_at"))
            if e["done"]:
                continue
            quotes = e["quotes"]
            if quoter is not None:
                quotes = []
                for q in e["quotes"]:
                    bid, ask = quoter(q, book["markets"].get(C.mkey(q), {}).get("inv", 0.0))
                    quotes.append(dict(q, bid=bid, ask=ask))
            pot = "late_left" if book.get("late") else "left"
            rng = np.random.default_rng(e["seed"])
            if e["mode"] == "poll":
                f = C.fills(quotes, book, rng, p, intensity=e["intensity"], pot=pot)
            else:
                a, b = (pd.Timestamp(x).to_pydatetime() for x in e["window"])
                f = C.window(quotes, book, rng, p, a, b, pace=p.late_pace if e["late"] else 1.0, pot=pot)
            fills += [dict(x, poll=e["ts"]) for x in f]
        return dict(book=book, fills=fills, pnl=C.book_pnl(book, self.fair, self.outcomes))

    def resolve(self, key):
        return self.outcomes.get(key)


def spread_quoter(half_spread, max_pos=2500.0, skew=1.0, lo=0.01, hi=0.99):
    """A quoting rule for PrivateBook.replay: a fixed half-spread around the recorded fair, leaning against
    inventory (markets/quoting.py). Markets the live maker didn't quote stay unquoted."""
    from racinglines.markets import quoting as Q

    def quoter(q, inv):
        if q.get("bid") is None and q.get("ask") is None:
            return None, None
        f = q.get("fair")
        if f is None or math.isnan(f) or f <= lo or f >= hi:
            return None, None
        return Q.quote(f, half_spread, inv, max_pos, skew, tidy=False)
    return quoter
