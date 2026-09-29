"""
Replay a maker quoting an exchange (Polymarket) against the real trade tape.

What the maker knows at time t (and nothing later):
  - our fair value from the diagnostic run whose cutoff is the latest one <= t
    (each run was priced with data from before its own cutoff);
  - the exchange's public record up to t: minute prices and trades.

What the maker does every `step`:
  - skips a market when it looks untradeable from public data (thin trailing
    volume, price near 0/1, or our fair too far from the market to trust);
  - otherwise rests a post-only bid and ask around fair (skewed against inventory),
    never crossing the market, so YES bid + NO bid (= bid + 1 - ask) < 1;
  - respects a per-market inventory limit and an event-level capital limit;
  - pulls all quotes `pull` before each session (every session: a stage ends at the next
    session's start), and quotes again once the next pricing stage starts.
Options (off by default): flatten inventory before qualifying, skew harder as a session
approaches, per-kind half-spreads (docs/f1-roadmap.md, F1-4).

How it gets filled: only by real taker trades AFTER the quote was placed. A taker
SELL of YES at price p fills our bid b if p <= b ("touch", optimistic: we're
first in the queue) or p < b ("through", conservative: the trade went past our
level). Fill size is capped by the trade's size, our quote's remaining size and
our limits. Binary markets trade in both outcome tokens; trades of the second
token are mapped to the first (buy NO at p == sell YES at 1 - p).

"queue" (needs recorded books, `racinglines markets record`): a new quote joins the back
of its price level, behind the size the latest book snapshot shows there (0 when we
improve on the best price). A trade at our price eats that queue first and fills us
only with what's left; a trade past our price fills us as "through" does. While the
quote stays at the same price it keeps its place, and the queue ahead of it shrinks
to the displayed size when a later snapshot shows less (cancellations). Without a
snapshot from the last `book_max_age_min`, the quote falls back to "through".

Known limits (Baku test case): our quotes don't change what takers would have done;
competing makers are only what the recorded books show (top 10 levels, once a minute).
"""

import math
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from racinglines.markets import settlement_rules as SR


@dataclass(frozen=True)
class Params:
    half_spread: float = 0.02      # quote fair +- 2c (article: 3-8c total spread on mid-tier markets)
    tick: float = 0.01
    size: float = 50.0             # shares per quote per side
    max_pos: float = 250.0         # |YES-equivalent inventory| per market
    max_capital: float = 1000.0    # worst-case loss across the event
    skew: float = 1.0              # shift quotes by -skew * half_spread * inventory / max_pos
    step_min: int = 5              # requote interval
    pull_min: int = 15             # pull quotes this long before each session
    min_volume_24h: float = 100.0  # $ traded in the market over the previous 24 h (public)
    price_band: tuple = (0.03, 0.97)   # don't quote long shots / near-certain (near-resolved) markets
    max_disagree: float | None = 0.15  # don't quote when |fair - market| exceeds this
    fill: str = "through"          # "touch" (optimistic), "through" (conservative) or "queue" (recorded books)
    book_max_age_min: float = 10.0  # "queue": older snapshots don't count (the quote falls back to "through")
    # options (docs/f1-roadmap.md, F1-4); the defaults are the original maker
    flatten_before_qual: bool = False   # close all inventory at the market (mid +- taker_cost) just before qualifying
    taker_cost: float = 0.01            # $ per share paid when flattening
    info_skew: float = 0.0              # skew x (1 + info_skew * exp(-(time to next session) / info_tau_h))
    info_tau_h: float = 2.0
    half_spread_by_kind: dict | None = None   # per market kind, e.g. widened where markouts were bad
    maker_fee: float = 0.0              # a venue's maker fee: ceil(maker_fee x contracts x P x (1 - P)) cents per fill
                                        # (Kalshi: KALSHI_MAKER_FEE; Polymarket charges makers nothing)


@dataclass
class Market:
    cond: str
    kind: str
    subject: str
    question: str
    fairs: dict                    # run_id -> fair probability of YES (outcome 0)
    outcome: bool | None           # resolved YES? (read only for P&L after the replay)
    mid_ts: np.ndarray = field(repr=False)      # int64 ns, sorted
    mid_px: np.ndarray = field(repr=False)
    tr_ts: np.ndarray = field(repr=False)       # trades, YES perspective, sorted
    tr_px: np.ndarray = field(repr=False)
    tr_sz: np.ndarray = field(repr=False)
    tr_buy: np.ndarray = field(repr=False)      # taker bought YES
    link: dict | None = field(default=None, repr=False)   # the exchange link row (outcome-0 token)
    # recorded order books of the outcome-0 token (YES side), for fill="queue": snapshot times
    # (int64 ns, sorted) and per snapshot {price: size} of bids and asks
    bk_ts: np.ndarray | None = field(default=None, repr=False)
    bk_bids: list | None = field(default=None, repr=False)
    bk_asks: list | None = field(default=None, repr=False)


KALSHI_MAKER_FEE = 0.0175              # Kalshi's maker fee on most markets (check the market's own schedule)


def venue_fee(rate, price, contracts):
    """Dollars for one fill of `contracts` at `price` under a Kalshi-style fee (rounded up to the cent)."""
    return math.ceil(round(rate * contracts * price * (1 - price) * 100, 6)) / 100


class LookaheadError(AssertionError):
    pass


class PublicView:
    """The exchange's public record of one market up to (and including) time t."""

    def __init__(self, mk: Market, t: int):
        self.t = t
        i = np.searchsorted(mk.mid_ts, t, side="right")
        j = np.searchsorted(mk.tr_ts, t, side="right")
        self.mid_ts, self.mid_px = mk.mid_ts[:i], mk.mid_px[:i]
        self.tr_ts, self.tr_px, self.tr_sz = mk.tr_ts[:j], mk.tr_px[:j], mk.tr_sz[:j]
        if (len(self.mid_ts) and self.mid_ts[-1] > t) or (len(self.tr_ts) and self.tr_ts[-1] > t):
            raise LookaheadError("public view contains data after t")

    def mid(self):
        return float(self.mid_px[-1]) if len(self.mid_px) else None

    def volume(self, hours=24):
        k = np.searchsorted(self.tr_ts, self.t - int(hours * 3600e9), side="right")
        return float((self.tr_px[k:] * self.tr_sz[k:]).sum())


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


def _px(x):
    return round(float(x), 4)


def book_depth(mk: Market, t, side, price, max_age_min=10.0):
    """Size resting at `price` on `side` ("bid"/"ask") of the latest book snapshot at or
    before t: the queue a new quote there joins the back of (0 when the level is empty or
    better than the best price). None when there's no snapshot from the last max_age_min."""
    if mk.bk_ts is None or not len(mk.bk_ts):
        return None
    i = np.searchsorted(mk.bk_ts, t, side="right") - 1
    if i < 0 or t - mk.bk_ts[i] > max_age_min * 60e9:
        return None
    return float((mk.bk_bids if side == "bid" else mk.bk_asks)[i].get(_px(price), 0.0))


def to_yes(outcome_index, side, price):
    """Express a trade of either outcome token as a trade of YES (outcome 0):
    buying NO at p is selling YES at 1 - p. Returns (yes_price, taker_bought_yes)."""
    oi = np.asarray(outcome_index)
    px = np.where(oi == 0, price, 1 - np.asarray(price, float))
    return px.astype(float), (np.asarray(side) == "BUY") == (oi == 0)


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


def _join_queue(queue, mk, t, side, price, p, booked):
    """fill="queue": place (or keep) our quote on one side at time t. A quote at a new price
    joins the back of its level; one at the same price keeps its place, and the queue ahead
    of it shrinks to the displayed size if that's now smaller. No usable book: ahead = None
    (the quote fills as "through")."""
    key = (mk.cond, side)
    if price is None:
        queue.pop(key, None)
        return
    shown = book_depth(mk, t, side, price, p.book_max_age_min)
    booked[1] += 1
    booked[0] += shown is not None
    cur = queue.get(key)
    if cur is not None and cur[0] == _px(price) and cur[1] is not None and shown is not None:
        cur[1] = min(cur[1], shown)
    else:
        queue[key] = [_px(price), shown]


def _after_queue(state, px, sz, price, buy):
    """fill="queue": what's left of a taker trade of size sz at px for our quote at `price`
    once the queue ahead of it has been served; updates the queue. A trade past our price
    swept the level: it all counts (as "through") and nobody is left ahead of us."""
    if state is None or price is None:
        return sz
    through = px > price + 1e-9 if buy else px < price - 1e-9
    at = abs(px - price) <= 1e-9
    if state[1] is None:           # no book: "through"
        return sz if through else 0.0
    if through:
        state[1] = 0.0
        return sz
    if not at:
        return 0.0
    eat = min(sz, state[1])
    state[1] -= eat
    return sz - eat


def _mid_at(mk, t):
    i = np.searchsorted(mk.mid_ts, t, side="right") - 1
    return float(mk.mid_px[i]) if i >= 0 else np.nan


def _score_fills(fills, data):
    """Per fill (after the fact): spread captured vs the market price at the fill, the
    market's move over the next 5 / 60 min (adverse selection when negative), our
    model's edge at the fill, and the realized P&L at resolution."""
    if not len(fills):
        return fills.assign(mid=[], markout_5m=[], markout_60m=[], spread_pnl=[], model_edge=[], pnl=[],
                            kind=[], subject=[])
    by = {m.cond: m for m in data["markets"]}
    sgn = np.where(fills["side"] == "buy", 1.0, -1.0)
    mid = np.array([_mid_at(by[c], t) for c, t in zip(fills["cond"], fills["ts"])])
    m5 = np.array([_mid_at(by[c], t + int(300e9)) for c, t in zip(fills["cond"], fills["ts"])])
    m60 = np.array([_mid_at(by[c], t + int(3600e9)) for c, t in zip(fills["cond"], fills["ts"])])
    # a void market (settlement_rules.VOID: a cancelled race) settles every fill at its own price: P&L 0
    out = np.array([np.nan if by[c].outcome is None else (px if by[c].outcome == SR.VOID else float(by[c].outcome))
                    for c, px in zip(fills["cond"], fills["price"])])
    q = fills["qty"].to_numpy()
    return fills.assign(
        mid=mid, spread_pnl=sgn * (mid - fills["price"]) * q,
        markout_5m=sgn * (m5 - mid) * q, markout_60m=sgn * (m60 - mid) * q,
        model_edge=sgn * (fills["fair"] - fills["price"]) * q,
        pnl=sgn * (out - fills["price"]) * q,
        kind=[by[c].kind for c in fills["cond"]], subject=[by[c].subject for c in fills["cond"]])


def _positions(data, cash, inv):
    rows = []
    for mk in data["markets"]:
        o = mk.outcome
        rows.append(dict(cond=mk.cond, kind=mk.kind, subject=mk.subject, question=mk.question,
                         inventory=inv[mk.cond], cash=cash[mk.cond], worst_case=_worst_case(cash[mk.cond], inv[mk.cond]),
                         outcome=o, pnl=SR.settle_position(inv[mk.cond], 0.0, cash[mk.cond], o)))
    # named columns even with no markets (e.g. an h2h-only sweep: the maker replays position markets only)
    return pd.DataFrame(rows, columns=["cond", "kind", "subject", "question", "inventory", "cash", "worst_case",
                                       "outcome", "pnl"])


def summary(res, by="kind"):
    """P&L decomposition per market kind and in total."""
    f, pos, qt = res["fills"], res["positions"], res["quotes"]
    kinds = pos.set_index("cond")["kind"]
    qt = qt.assign(kind=qt["cond"].map(kinds))
    rows = []
    for k, g in list(pos.groupby(by)) + [("total", pos)]:
        fk = f if k == "total" else f[f["kind"] == k]
        qk = qt if k == "total" else qt[qt["kind"] == k]
        rows.append({by: k, "markets": len(g), "quoted_share": float((qk["skip"].isna()).mean()) if len(qk) else 0.0,
                     "fills": len(fk), "shares": float(fk["qty"].sum()),
                     "notional": float((fk["qty"] * fk["price"]).sum()),
                     "spread_pnl": float(fk["spread_pnl"].sum()), "markout_60m": float(fk["markout_60m"].sum()),
                     "model_edge": float(fk["model_edge"].sum()), "pnl": float(g["pnl"].fillna(0).sum()),
                     "worst_case": float(g["worst_case"].sum())})
    return pd.DataFrame(rows).set_index(by)


def by_stage(res, data):
    """Fills and P&L (held to resolution) by pricing stage."""
    f = res["fills"]
    rows = []
    for st in data["stages"]:
        g = f[f["run_id"] == st["run_id"]]
        rows.append(dict(run_id=st["run_id"], start=pd.Timestamp(st["start"], tz="UTC"), end=pd.Timestamp(st["end"], tz="UTC"),
                         fills=len(g), notional=float((g["qty"] * g["price"]).sum()), spread_pnl=float(g["spread_pnl"].sum()),
                         markout_60m=float(g["markout_60m"].sum()), model_edge=float(g["model_edge"].sum()),
                         pnl=float(g["pnl"].sum())))
    return pd.DataFrame(rows)


def skip_reasons(res):
    qt = res["quotes"]
    return qt["skip"].fillna("quoted").value_counts()


def sweep(data, half_spreads=(0.01, 0.02, 0.03, 0.04), fills=("touch", "through"), disagree=(0.15, None), base=Params()):
    rows = []
    for h in half_spreads:
        for fm in fills:
            for d in disagree:
                s = summary(replay(data, replace(base, half_spread=h, fill=fm, max_disagree=d))).loc["total"]
                rows.append(dict(half_spread=h, fill=fm, max_disagree=d if d is not None else "off",
                                 fills=int(s["fills"]), notional=s["notional"], spread_pnl=s["spread_pnl"],
                                 markout_60m=s["markout_60m"], pnl=s["pnl"], worst_case=s["worst_case"]))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Loading an event from the database
# ---------------------------------------------------------------------------

MODELED = ("race_win", "race_podium", "race_h2h", "race_constructor_top")


def _ns(ts):
    """int64 ns UTC for one timestamp (naive = UTC) or an array of them."""
    if isinstance(ts, (str, pd.Timestamp)):
        t = pd.Timestamp(ts)
        return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).as_unit("ns").value
    return pd.DatetimeIndex(pd.to_datetime(ts, utc=True)).as_unit("ns").asi8


def stages_for(runs, sessions):
    """Each run prices from its cutoff until the next run's cutoff or the next session
    start (qualifying / race), whichever comes first; nothing is quoted once the race starts."""
    sess = sorted(sessions)
    out = []
    for i, r in enumerate(runs):
        nxt = [s for s in sess if s > r["cutoff"]]
        if not nxt:
            continue
        end = nxt[0]
        if i + 1 < len(runs):
            end = min(end, runs[i + 1]["cutoff"])
        if end > r["cutoff"]:
            out.append(dict(run_id=r["run_id"], start=r["cutoff"], end=end, session_end=end in sess))
    return out


def _levels(v):
    """{price: size} from a recorded book side ([[price, size], ...] as a list or JSON text)."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return {}
    if isinstance(v, str):
        import json
        v = json.loads(v)
    out = {}
    for lv in v:
        px, sz = (lv["price"], lv["size"]) if isinstance(lv, dict) else lv
        out[_px(px)] = out.get(_px(px), 0.0) + float(sz)
    return out


def load_event(conn, run_ids, sessions=None, books=False, exchange="polymarket", rules=None):
    """Markets, fair values, public tape and outcomes for one event's diagnostic runs.
    sessions: [(kind, start)] (naive UTC) instead of the race's stored rounds (an event not yet run).
    books: also load the recorded order books (for fill="queue").
    exchange: whose markets and tape ("polymarket", or "kalshi": markets/kalshi/ writes the same tables). A
    Kalshi link's condition_id is its event ticker, shared by every market of the event, so there each market
    is its own ticker (token_id), and its trades are read by ticker.
    rules: a cancelled race's outcomes by the exchange's rules (markets/settlement_rules.py: an outcome can then
    be a 0.5 payout or VOID); None reads RACINGLINES_CANCELLED_RACE_RULES, off by default."""
    from sqlalchemy import text

    from racinglines.db import reads as D
    from racinglines.markets import private_book as house
    from racinglines.markets import settlement_rules as SR

    runs = pd.read_sql(text("SELECT id, params FROM model_runs WHERE id = ANY(:i) AND kind = 'diagnostic'"), conn,
                       params=dict(i=list(run_ids)))
    keys = {p["event_key"] for p in runs["params"]}
    if len(keys) != 1:
        raise ValueError(f"runs must be diagnostics of one event, got {keys}")
    key = keys.pop()
    runs = sorted((dict(run_id=int(i), cutoff=_ns(p["cutoff"])) for i, p in zip(runs["id"], runs["params"])),
                  key=lambda r: r["cutoff"])
    race_id = conn.execute(text("SELECT ra.id FROM races ra JOIN events e ON e.id = ra.event_id WHERE e.source_key = :k"),
                           dict(k=key)).scalar()
    rounds = sessions if sessions is not None else conn.execute(text(
        "SELECT kind, extra->>'session_date' FROM rounds WHERE race_id = :r "
        "AND extra->>'session_date' IS NOT NULL"), dict(r=race_id)).fetchall()
    sessions = [_ns(s) for _, s in rounds]
    qual_start = next((_ns(s) for k, s in rounds if k == "qual"), None)
    stages = stages_for(runs, sessions)
    t0 = min(r["cutoff"] for r in runs) - int(48 * 3600e9)
    t1 = max(sessions) + int(6 * 3600e9)

    links = pd.read_sql(text("""
        SELECT ml.*, a.display_name AS athlete FROM market_links ml LEFT JOIN athletes a ON a.id = ml.athlete_id
        WHERE ml.race_id = :r AND ml.prediction = ANY(:k) AND ml.exchange = :x
        ORDER BY ml.id"""), conn, params=dict(r=race_id, k=list(MODELED), x=exchange))
    status = SR.race_status("f1", key, SR.db_status(conn, race_id)) if SR.enabled(rules) else None
    if exchange == "kalshi":
        return _load_kalshi(conn, links, runs, key, race_id, sessions, stages, qual_start, t0, t1, books, status)
    res = house.race_outcomes(conn, race_id)
    from racinglines.markets import store as MS
    conds = links["condition_id"].dropna().unique().tolist()
    a, b = pd.Timestamp(t0, tz="UTC"), pd.Timestamp(t1, tz="UTC")
    all_tr = MS.read(conn, "trades", conditions=conds, start=a, end=b)
    all_px = MS.read(conn, "prices", tokens=links["token_id"].tolist(), start=a, end=b)
    tok = MS.read(conn, "trades", conditions=conds).drop_duplicates("token_id")
    idx = dict(zip(tok["token_id"], tok["outcome_index"]))
    tr_by, px_by = dict(tuple(all_tr.groupby("condition_id"))), dict(tuple(all_px.groupby("token_id")))
    bk_by = dict(tuple(MS.read(conn, "books", tokens=links["token_id"].tolist(), start=a, end=b)
                       .groupby("token_id"))) if books else {}
    empty_px, empty_tr = all_px.iloc[0:0], all_tr.iloc[0:0]
    markets, cache = [], {}
    for cond, g in links.groupby("condition_id", sort=False):
        # the outcome-0 token: from the trade tape, else the first link of the condition
        g = g.assign(oi=g["token_id"].map(idx))
        link = g.sort_values("oi", na_position="last").iloc[0].to_dict()
        if not pd.isna(link["oi"]) and link["oi"] != 0:
            continue    # outcome-0 token isn't linked; can't express trades from its side
        fairs = {r["run_id"]: D.model_prob(conn, link, cache, run_id=r["run_id"])[0] for r in runs}
        ath = None if pd.isna(link["athlete_id"]) else int(link["athlete_id"])
        outcome = house.outcome_for(link["prediction"], ath, link["params"], res)
        if status:
            outcome = SR.apply(exchange, status, link["prediction"], link.get("group_title") or link.get("outcome"), outcome)
        mids = px_by.get(link["token_id"], empty_px)
        tr = tr_by.get(cond, empty_tr)
        yes_px, yes_buy = to_yes(tr["outcome_index"].to_numpy(), tr["side"].to_numpy(), tr["price"].to_numpy())
        subject = link["athlete"] or (link["params"] or {}).get("team") or link["group_title"]
        if link["prediction"] == "race_h2h":
            subject = f"{link['outcome']} ahead ({link['question'].split(': ')[-1]})"
        bk = bk_by.get(link["token_id"])
        book = {} if bk is None or not len(bk) else dict(
            bk_ts=_ns(bk["ts"]), bk_bids=[_levels(v) for v in bk["bids"]], bk_asks=[_levels(v) for v in bk["asks"]])
        markets.append(Market(cond=cond, kind=link["prediction"], subject=subject, question=link["question"],
                              fairs=fairs, outcome=outcome,
                              mid_ts=_ns(mids["ts"]) if len(mids) else np.array([], dtype="int64"),
                              mid_px=mids["price"].to_numpy(float),
                              tr_ts=_ns(tr["ts"]) if len(tr) else np.array([], dtype="int64"),
                              tr_px=np.asarray(yes_px, float), tr_sz=tr["size"].to_numpy(float), tr_buy=yes_buy,
                              link=link, **book))
    return dict(event_key=key, race_id=race_id, runs=runs, sessions=sorted(sessions), stages=stages, markets=markets,
                qual_start=qual_start)


def _load_kalshi(conn, links, runs, key, race_id, sessions, stages, qual_start, t0, t1, books, status=None):
    """load_event for Kalshi links: one Market per ticker (YES contract; trades are already on its side).
    status: the race's settlement_rules status (cancelled / relocated), applied to the outcomes."""
    from racinglines.db import reads as D
    from racinglines.markets import private_book as house
    from racinglines.markets import settlement_rules as SR
    from racinglines.markets import store as MS
    res = house.race_outcomes(conn, race_id)
    toks = links["token_id"].tolist()
    a, b = pd.Timestamp(t0, tz="UTC"), pd.Timestamp(t1, tz="UTC")
    root = MS.root_for("kalshi")
    all_tr = MS.read(conn, "trades", tokens=toks, start=a, end=b, root=root)
    all_px = MS.read(conn, "prices", tokens=toks, start=a, end=b, root=root)
    tr_by, px_by = dict(tuple(all_tr.groupby("token_id"))), dict(tuple(all_px.groupby("token_id")))
    bk_by = dict(tuple(MS.read(conn, "books", tokens=toks, start=a, end=b, root=root).groupby("token_id"))) if books else {}
    empty_px, empty_tr = all_px.iloc[0:0], all_tr.iloc[0:0]
    markets, cache = [], {}
    for link in links.to_dict("records"):
        tok = link["token_id"]
        fairs = {r["run_id"]: D.model_prob(conn, link, cache, run_id=r["run_id"])[0] for r in runs}
        ath = None if pd.isna(link["athlete_id"]) else int(link["athlete_id"])
        outcome = house.outcome_for(link["prediction"], ath, link["params"], res)
        if status:
            outcome = SR.apply("kalshi", status, link["prediction"], link.get("group_title") or link.get("outcome"), outcome)
        mids, tr = px_by.get(tok, empty_px), tr_by.get(tok, empty_tr)
        subject = link["athlete"] or (link["params"] or {}).get("team") or link["group_title"]
        if link["prediction"] == "race_h2h":
            subject = f"{link['athlete'] or link['outcome']} ahead ({link['question']})"
        bk = bk_by.get(tok)
        book = {} if bk is None or not len(bk) else dict(
            bk_ts=_ns(bk["ts"]), bk_bids=[_levels(v) for v in bk["bids"]], bk_asks=[_levels(v) for v in bk["asks"]])
        markets.append(Market(cond=tok, kind=link["prediction"], subject=subject, question=link["question"],
                              fairs=fairs, outcome=outcome,
                              mid_ts=_ns(mids["ts"]) if len(mids) else np.array([], dtype="int64"),
                              mid_px=mids["price"].to_numpy(float),
                              tr_ts=_ns(tr["ts"]) if len(tr) else np.array([], dtype="int64"),
                              tr_px=tr["price"].to_numpy(float), tr_sz=tr["size"].to_numpy(float),
                              tr_buy=(tr["side"] == "BUY").to_numpy(bool), link=link, **book))
    return dict(event_key=key, race_id=race_id, runs=runs, sessions=sorted(sessions), stages=stages, markets=markets,
                qual_start=qual_start)
