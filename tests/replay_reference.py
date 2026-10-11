"""The maker replay as it was before the speed rewrite (staging 295eec4), kept verbatim as the reference that
tests/test_replay_parity.py compares the current maker_replay.replay against. Not used by the app."""

from dataclasses import replace

import numpy as np
import pandas as pd

from racinglines.markets.strategies.maker_replay import (Params, PublicView, _after_queue, _join_queue, _positions,
                                                         _score_fills, venue_fee)


def _worst_case(cash, inv):
    """Worst-case P&L of one market's position: YES resolves 0 or 1."""
    return min(cash, cash + inv)


def _used(cash, inv):
    return -sum(min(0.0, _worst_case(cash[c], inv[c])) for c in cash)


def _cap(q, sgn, price, cash, inv, cond, p):
    """Largest fill <= q that keeps the event's worst-case loss within max_capital
    (a fill that reduces risk is never cut)."""
    def used_after(x):
        c, i = dict(cash), dict(inv)
        c[cond] -= sgn * x * price
        i[cond] += sgn * x
        return _used(c, i)
    if q <= 0 or used_after(q) <= p.max_capital + 1e-9 or used_after(q) <= _used(cash, inv):
        return max(q, 0.0)
    lo, hi = 0.0, q
    for _ in range(30):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if used_after(mid) <= p.max_capital else (lo, mid)
    return lo


def quote(fair, view: PublicView, inv, p: Params, capital_used=0.0):
    """(bid, ask, reason). bid/ask are None when that side isn't quoted; reason says why
    nothing is quoted. Uses only `fair`, our own state and the public view."""
    mid = view.mid()
    if fair is None or np.isnan(fair):
        return None, None, "no fair"
    if mid is None:
        return None, None, "no market price"
    if not (p.price_band[0] <= mid <= p.price_band[1]):
        return None, None, "outside price band"
    if view.volume() < p.min_volume_24h:
        return None, None, "thin"
    if p.max_disagree is not None and abs(fair - mid) > p.max_disagree:
        return None, None, "disagree"
    shift = -p.skew * p.half_spread * inv / p.max_pos
    bid = np.floor(round((fair - p.half_spread + shift) / p.tick, 6)) * p.tick
    ask = np.ceil(round((fair + p.half_spread + shift) / p.tick, 6)) * p.tick
    # post-only: never cross the market
    bid = min(bid, np.ceil(round(mid / p.tick, 6)) * p.tick - p.tick)
    ask = max(ask, np.floor(round(mid / p.tick, 6)) * p.tick + p.tick)
    bid = None if bid < p.tick else round(bid, 4)
    ask = None if ask > 1 - p.tick else round(ask, 4)
    # limits: only the side that reduces risk once a limit is reached
    at_cap = capital_used >= p.max_capital
    if bid is not None and (inv >= p.max_pos or (at_cap and inv >= 0)):
        bid = None
    if ask is not None and (inv <= -p.max_pos or (at_cap and inv <= 0)):
        ask = None
    return bid, ask, None if (bid is not None or ask is not None) else "limit"


def replay(data, p: Params = Params()):
    """data = dict(markets=[Market], stages=[dict(run_id, start, end)]) with times in
    int64 ns. Returns dict(fills, quotes, positions)."""
    step = int(p.step_min * 60e9)
    pull = int(p.pull_min * 60e9)
    cash = {m.cond: 0.0 for m in data["markets"]}
    inv = {m.cond: 0.0 for m in data["markets"]}
    fills, quotes = [], []
    by_kind = p.half_spread_by_kind or {}
    queue = {}                     # fill="queue": (cond, side) -> [price, size ahead of us]
    booked = [0, 0]                # fill="queue": quoted sides with a usable book, all quoted sides
    for st in data["stages"]:
        t, end = st["start"], st["end"] - (pull if st.get("session_end", True) else 0)
        while t < end:
            t_next = min(t + step, end)
            used = _used(cash, inv)
            pt = p
            if p.info_skew and st.get("session_end", True):     # skew harder as the next session approaches
                pt = replace(p, skew=p.skew * (1 + p.info_skew * np.exp(-(st["end"] - t) / (p.info_tau_h * 3600e9))))
            for mk in data["markets"]:
                fair = mk.fairs.get(st["run_id"])
                view = PublicView(mk, t)
                pk = replace(pt, half_spread=by_kind[mk.kind]) if mk.kind in by_kind else pt
                bid, ask, why = quote(fair, view, inv[mk.cond], pk, used)
                quotes.append((t, mk.cond, st["run_id"], bid, ask, why))
                if bid is None and ask is None:
                    continue
                if p.fill == "queue":
                    for side, px_q in (("bid", bid), ("ask", ask)):
                        _join_queue(queue, mk, t, side, px_q, p, booked)
                # trades strictly after the quote was placed, up to the next requote
                a = np.searchsorted(mk.tr_ts, t, side="right")
                b = np.searchsorted(mk.tr_ts, t_next, side="right")
                left_bid = left_ask = p.size
                for k in range(a, b):
                    px, sz, buy = mk.tr_px[k], mk.tr_sz[k], mk.tr_buy[k]
                    if p.fill == "queue":
                        side, px_q = ("ask", ask) if buy else ("bid", bid)
                        sz = _after_queue(queue.get((mk.cond, side)), px, sz, px_q, buy)
                        if sz <= 0:
                            continue
                    if not buy and bid is not None and left_bid > 0 and (px <= bid if p.fill in ("touch", "queue") else px < bid):
                        q = _cap(min(sz, left_bid, p.max_pos - inv[mk.cond]), +1, bid, cash, inv, mk.cond, p)
                        if q > 0:
                            left_bid -= q
                            inv[mk.cond] += q
                            cash[mk.cond] -= q * bid
                            if p.maker_fee:
                                cash[mk.cond] -= venue_fee(p.maker_fee, bid, q)
                            fills.append((int(mk.tr_ts[k]), mk.cond, st["run_id"], "buy", bid, q, fair))
                    elif buy and ask is not None and left_ask > 0 and (px >= ask if p.fill in ("touch", "queue") else px > ask):
                        q = _cap(min(sz, left_ask, p.max_pos + inv[mk.cond]), -1, ask, cash, inv, mk.cond, p)
                        if q > 0:
                            left_ask -= q
                            inv[mk.cond] -= q
                            cash[mk.cond] += q * ask
                            if p.maker_fee:
                                cash[mk.cond] -= venue_fee(p.maker_fee, ask, q)
                            fills.append((int(mk.tr_ts[k]), mk.cond, st["run_id"], "sell", ask, q, fair))
            t = t_next
        if p.flatten_before_qual and st["end"] == data.get("qual_start"):
            for mk in data["markets"]:           # take the market to go flat before qualifying
                q, mid = inv[mk.cond], PublicView(mk, end).mid()
                if abs(q) < 1e-9 or mid is None:
                    continue
                px = min(mid + p.taker_cost, 1.0) if q < 0 else max(mid - p.taker_cost, 0.0)
                cash[mk.cond] += q * px
                inv[mk.cond] = 0.0
                fills.append((int(end), mk.cond, st["run_id"], "sell" if q > 0 else "buy", px, abs(q),
                              mk.fairs.get(st["run_id"])))
    fills = pd.DataFrame(fills, columns=["ts", "cond", "run_id", "side", "price", "qty", "fair"])
    quotes = pd.DataFrame(quotes, columns=["ts", "cond", "run_id", "bid", "ask", "skip"])
    out = dict(fills=_score_fills(fills, data), quotes=quotes, positions=_positions(data, cash, inv), params=p)
    if p.fill == "queue":          # share of quoted sides that had a book (the rest were filled as "through")
        out["book_coverage"] = booked[0] / booked[1] if booked[1] else 0.0
    return out
