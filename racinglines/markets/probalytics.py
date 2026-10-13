"""Probalytics' tape as a backtest venue: the same interface as markets/venue_replay.py's Polymarket and Kalshi
classes (markets, view, price, quote, volume_24h, coherent, touch_depth, resolve), read from the Parquet files that
scripts/probes/probalytics_pull.py writes, so a sweep can be re-run on their books and fills and compared with ours.

Switched on for weekend_sweep's venues by RACINGLINES_TAPE_SOURCE=probalytics (off by default: nothing changes
unless it is set). Read from $RACINGLINES_DATA/probalytics/:

    stages/<event_key>_<VENUE>.parquet     the book as of each stage cutoff (the last snapshot at or before it)
    books/<YYYY-MM-DD>_F1_<VENUE>.parquet  every snapshot of a day, when pulled (preferred: the full timeline)
    fills/F1_<VENUE>_<YYYY-MM>.parquet     every fill

What differs from our own tape, on purpose:
- price() is the book's mid (best bid + best ask) / 2 where we read Polymarket's 5-minute price history; quote()
  is the book's touch on both venues' Kalshi path, as ours is from our 5-minute Kalshi snapshots.
- Their snapshots are written on change, not on a clock, so a snapshot stays the book until the next one: it is
  stale only after BOOK_STALE (48 hours, the stage files' lookback), not after venue_replay.STALE's 6 hours.
- volume_24h() sums price x size of their fills (both outcomes of a Polymarket condition, one Kalshi ticker).
Keys are exact: a Polymarket token is their outcome platform id, a Kalshi ticker their market platform id (YES book).
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from racinglines.markets.venue_replay import Kalshi, Polymarket

ENV = "RACINGLINES_TAPE_SOURCE"
BOOK_STALE = timedelta(hours=48)


def enabled():
    return os.environ.get(ENV, "").strip().lower() == "probalytics"


def root():
    from racinglines.paths import DATA
    return Path(os.environ.get("PROBALYTICS_DATA", DATA / "probalytics"))


def _days(a, b):
    d = a.normalize()
    while d <= b:
        yield d
        d += pd.Timedelta(days=1)


def _months(a, b):
    m = a.normalize().replace(day=1)
    while m <= b:
        yield m
        m = (m + pd.Timedelta(days=32)).replace(day=1)


def _read(paths, cols, filters):
    import pyarrow.parquet as pq
    parts = [pq.read_table(p, columns=cols, filters=filters).to_pandas() for p in paths if p.exists()]
    parts = [x for x in parts if len(x)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


def read_books(venue, event_key, start, end, keys, base=None):
    """One row per snapshot of the keys' books over [start - BOOK_STALE, end]: key, ts (naive UTC), bid, ask,
    bid_size, ask_size (at the touch). The day files when any were pulled for the window, else the stage file."""
    base = Path(base or root())
    code = venue.upper()
    key_col = "outcome_pid" if venue == "polymarket" else "market_platform_id"
    cols = list(dict.fromkeys([key_col, "outcome_pid", "timestamp", "bid_px", "bid_sz", "ask_px", "ask_sz"]))
    a = pd.Timestamp(start) - BOOK_STALE
    days = [base / "books" / f"{d:%Y-%m-%d}_F1_{code}.parquet" for d in _days(a, pd.Timestamp(end))]
    filt = [(key_col, "in", list(keys))]
    df = _read(days, cols, filt) if any(p.exists() for p in days) else pd.DataFrame()
    if not len(df):
        df = _read([base / "stages" / f"{event_key}_{code}.parquet"], cols, filt)
    if venue == "kalshi" and len(df):
        df = df[df["outcome_pid"] == "yes"]
    out = pd.DataFrame(dict(key=df[key_col].astype(str) if len(df) else [],
                            ts=pd.to_datetime(df["timestamp"], utc=True).dt.tz_localize(None) if len(df) else []))
    if len(df):
        def best(px, sz, pick):
            if px is None or not len(px):
                return np.nan, 0.0
            i = int(pick(np.asarray(px)))
            return float(px[i]), float(sz[i])
        b = [best(p, s, np.argmax) for p, s in zip(df["bid_px"], df["bid_sz"])]
        k = [best(p, s, np.argmin) for p, s in zip(df["ask_px"], df["ask_sz"])]
        out["bid"], out["bid_size"] = [x[0] for x in b], [x[1] for x in b]
        out["ask"], out["ask_size"] = [x[0] for x in k], [x[1] for x in k]
    return out.drop_duplicates(["key", "ts"], keep="last").sort_values(["key", "ts"]).reset_index(drop=True)


def read_fills(venue, start, end, keys, base=None):
    """key, ts (naive UTC), usd (price x size) of every fill of the keys (Polymarket condition ids or Kalshi
    tickers) over [start, end]."""
    base = Path(base or root())
    a, b = pd.Timestamp(start), pd.Timestamp(end)
    paths = [base / "fills" / f"F1_{venue.upper()}_{m:%Y-%m}.parquet" for m in _months(a, b)]
    df = _read(paths, ["market_platform_id", "timestamp", "price", "size"], [("market_platform_id", "in", list(keys))])
    ts = pd.to_datetime(df["timestamp"], utc=True).dt.tz_localize(None) if len(df) else pd.Series([], dtype="datetime64[ns]")
    out = pd.DataFrame(dict(key=df["market_platform_id"].astype(str) if len(df) else [], ts=ts,
                            usd=(df["price"] * df["size"]).astype(float) if len(df) else []))
    out = out[(out["ts"] >= a) & (out["ts"] <= b)]
    return out.sort_values(["key", "ts"]).reset_index(drop=True)


class _Tape:
    """The shared reads: books per key, fills per market."""

    book_stale = BOOK_STALE

    def _load(self, venue, event_key, links, start, end, book_key, fill_key, base=None):
        a, b = pd.Timestamp(start), pd.Timestamp(end)
        bk = read_books(venue, event_key, a, b, links[book_key].dropna().astype(str).unique(), base)
        fl = read_fills(venue, a - timedelta(hours=24), b, links[fill_key].dropna().astype(str).unique(), base)
        self.pb_books = {k: g for k, g in bk.groupby("key")}
        self.pb_fills = {k: g for k, g in fl.groupby("key")}

    def _book_at(self, key, t):
        g = self.pb_books.get(key)
        if g is None:
            return None
        ts = pd.DatetimeIndex(g["ts"])
        i = ts.searchsorted(pd.Timestamp(t), side="right") - 1
        if i < 0 or pd.Timestamp(t) - ts[i] > self.book_stale:
            return None
        return g.iloc[i]

    def _touch(self, key, t):
        r = self._book_at(key, t)
        if r is None or pd.isna(r["bid"]) or pd.isna(r["ask"]) or not 0 < r["bid"] <= r["ask"] < 1:
            return None
        return float(r["bid"]), float(r["ask"])

    def _vol(self, key, t):
        g = self.pb_fills.get(key)
        if g is None:
            return 0.0
        a, b = g["ts"].searchsorted(t - timedelta(hours=24)), g["ts"].searchsorted(t, side="right")
        return float(g["usd"].iloc[a:b].sum())

    def touch_depth(self, token, t, max_age=None):
        r = self._book_at(self._book_key(token), t)
        if r is None:
            return None
        return float(r.get("ask_size") or 0.0), float(r.get("bid_size") or 0.0)

    def load_books(self, conn, start, end):
        """The books came with the tape (touch_depth reads them)."""


class ProbalyticsPolymarket(_Tape, Polymarket):
    """Polymarket on Probalytics' tape: price = the book's mid, trades at it (as ours trade at the price history)."""

    def __init__(self, conn, links, start, end, group_target=None, coherence_tol=0.25, stale=None, event_key=None,
                 base=None):
        self.links, self.stale = links, stale
        self.group_target, self.coherence_tol = group_target or {}, coherence_tol
        self._load("polymarket", event_key, links, start, end, "token_id", "condition_id", base)

    def _book_key(self, token):
        return str(token)

    def price(self, token, t):
        q = self._touch(str(token), t)
        return None if q is None else (q[0] + q[1]) / 2

    def volume_24h(self, condition, t):
        return self._vol(str(condition), t)


class ProbalyticsKalshi(_Tape, Kalshi):
    """Kalshi on Probalytics' tape: the taker meets the book's touch; price = its mid."""

    def __init__(self, conn, links, start, end, group_target=None, coherence_tol=0.25, stale=None, event_key=None,
                 base=None):
        self.links, self.stale = links, stale
        self.group_target, self.coherence_tol = group_target or {}, coherence_tol
        self._load("kalshi", event_key, links, start, end, "token_id", "token_id", base)

    def _book_key(self, token):
        return str(token)

    def price(self, token, t):
        q = self._touch(str(token), t)
        return None if q is None else (q[0] + q[1]) / 2

    def quote(self, token, t):
        return self._touch(str(token), t)

    def volume_24h(self, ticker, t):
        return self._vol(str(ticker), t)


EXCHANGES = {"polymarket": ProbalyticsPolymarket, "kalshi": ProbalyticsKalshi}
