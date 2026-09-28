"""
A synthetic, anonymous taker pool calibrated to an exchange's recorded tape (built for Kalshi's; any tape in
the shared tables works), for backtests and the demo maker's record. Off by default: nothing calls it unless
`racinglines f1 demo-history --venue kalshi --crowd synthetic` does.

The idea: the maker replay (strategies/maker_replay.py) fills our quotes from a taker tape. Here the tape is
generated instead of recorded, by takers whose decisions are driven by the exchange's historical price:

    fit(events)         per market kind, from the recorded tape and minute prices of past events:
                          rate     trades per market-hour, by hours before the race (buckets)
                          sizes    the contracts of each trade (resampled as they are)
                          noise    how far trades print from the prevailing mid (the spread of takers' views)
                          buy      the share of takers buying YES
    generate(mk, calib) one market's synthetic tape: arrivals ~ Poisson(rate x step x intensity); each arrival
                        is an anonymous taker from a seeded pool who values YES at
                            belief = mid(t) + lean + N(0, noise)            (noise traders)
                            belief = mid(t + horizon) + lean + N(0, noise)  (an `informed` share: where the
                                                                             price went)
                        lean = noise x Φ⁻¹(buy), so noise traders buy YES as often as the tape's takers did
                        and sends a marketable order toward that view: buy YES up to belief - edge, or sell
                        YES down to belief + edge (edge: what they want over their fee). The order is a tape
                        row at its limit price, so the maker replay fills our quote only when it's inside the
                        taker's limit ("touch": a buy at L fills our ask if L >= ask).
    retape(ev, calib)   the event's markets with their recorded tape swapped for a synthetic one (prices are
                        kept: the maker still sees the exchange's public mid)

Takers are anonymous (seeded UUIDs, no accounts), each with a log-uniform budget for the event as in
markets/crowd.py, spent as their orders are generated. Every draw comes from one seeded generator per market
(seed, market key), so a replay is exact.

The informed share looks ahead in the recorded prices; it is a backtest device (the adverse selection a real
maker faces) and never runs live.
"""

import hashlib
import math
import uuid
from statistics import NormalDist
from dataclasses import asdict, dataclass, replace

import numpy as np

HOUR = int(3600e9)
BUCKETS_H = (1, 3, 6, 12, 24, 48, 96)       # hours before the market's last recorded trade (upper edges)


@dataclass(frozen=True)
class Params:
    takers: int = 1000
    budget: tuple = (20.0, 2000.0)   # each taker's event budget ($), log-uniform
    informed: float = 0.15           # share of arrivals that see the price `horizon_min` ahead
    horizon_min: float = 60.0
    edge: float = 0.01               # what a taker wants over their view (about Kalshi's taker fee mid-book)
    intensity: float = 1.0           # x the fitted arrival rate
    step_min: float = 5.0            # arrivals are drawn per step
    min_noise: float = 0.005
    seed: int = 20260928

    def to_dict(self):
        return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(self).items()}


def _bucket(hours_before):
    for i, h in enumerate(BUCKETS_H):
        if hours_before <= h:
            return i
    return len(BUCKETS_H)


def _mid_at(mk, ts):
    """The recorded mid at or before each ts (NaN before the first)."""
    i = np.searchsorted(mk.mid_ts, ts, side="right") - 1
    out = np.where(i >= 0, mk.mid_px[np.clip(i, 0, None)] if len(mk.mid_px) else np.nan, np.nan)
    return out.astype(float)


def fit(events):
    """Calibration by market kind from recorded events: [(markets, ref)], markets being maker_replay.Market
    (YES-side tape and mids) and ref the event's last session start (int64 ns: the race), which the arrival
    rate is timed against; trades from the race start on are left out (nobody quotes into them). The noise
    is measured against a mid at most an hour old. -> {kind: dict(rate=[trades per market-hour, per bucket of hours before ref],
    sizes=[...], noise, buy, markets, trades)}."""
    acc = {}
    for markets, ref in events:
        for m in markets:
            keep = m.tr_ts < ref                                    # before the race: what a maker quotes into
            m = replace(m, tr_ts=m.tr_ts[keep], tr_px=m.tr_px[keep], tr_sz=m.tr_sz[keep], tr_buy=m.tr_buy[keep])
            if not len(m.tr_ts):
                continue
            a = acc.setdefault(m.kind, dict(counts=np.zeros(len(BUCKETS_H) + 1), hours=np.zeros(len(BUCKETS_H) + 1),
                                            sizes=[], dev=[], buys=[], markets=0))
            a["markets"] += 1
            np.add.at(a["counts"], [_bucket(max(ref - int(t), 0) / HOUR) for t in m.tr_ts], 1)
            span_h = max(ref - int(m.tr_ts[0]), 0) / HOUR        # the market traded from its first trade to ref
            lo = 0.0
            for i, hi in enumerate(BUCKETS_H + (math.inf,)):
                a["hours"][i] += max(0.0, min(hi, span_h) - lo)
                lo = hi
            a["sizes"] += m.tr_sz.tolist()
            a["buys"] += m.tr_buy.astype(bool).tolist()
            mid = _mid_at(m, m.tr_ts - 1)
            j = np.searchsorted(m.mid_ts, m.tr_ts - 1, side="right") - 1        # only a mid from the last hour
            fresh = (j >= 0) & ((m.tr_ts - m.mid_ts[np.clip(j, 0, None)]) <= HOUR) if len(m.mid_ts) else j < -1
            ok = ~np.isnan(mid) & fresh
            a["dev"] += (m.tr_px[ok] - mid[ok]).tolist()
    out = {}
    for kind, a in sorted(acc.items()):
        out[kind] = dict(rate=[float(c / h) if h > 0 else 0.0 for c, h in zip(a["counts"], a["hours"])],
                         sizes=[float(x) for x in a["sizes"]], noise=float(np.std(a["dev"])) if a["dev"] else 0.0,
                         buy=float(np.mean(a["buys"])), markets=a["markets"], trades=int(a["counts"].sum()))
    return out


def fit_db(conn, year, exchange="kalshi", kinds=None):
    """fit() over every race of `year` with `exchange` links in the shared tables (default: Kalshi's, the
    tape markets/kalshi/sync.py stores). The rate is timed against each race's start. The fit is in-sample
    for the season (the shape of the flow, not prices); held-out fits can pass their own events to fit()."""
    return fit(events_db(conn, year, exchange, kinds))


def check(conn, year, p=Params(), exchange="kalshi"):
    """The calibration check: the season's recorded tape against the synthetic crowd over the same weeks
    (each race from its first recorded trade to its start). -> compare() rows."""
    evs = events_db(conn, year, exchange)
    cal = fit(evs)
    real, syn = [], []
    for mks, ref in evs:
        mks = [replace(m, tr_ts=m.tr_ts[m.tr_ts < ref], tr_px=m.tr_px[m.tr_ts < ref], tr_sz=m.tr_sz[m.tr_ts < ref],
                       tr_buy=m.tr_buy[m.tr_ts < ref]) for m in mks]
        first = min((int(m.tr_ts[0]) for m in mks if len(m.tr_ts)), default=ref)
        ev = dict(markets=mks, stages=[dict(run_id=0, start=first, end=ref)], sessions=[ref])
        real += mks
        syn += retape(ev, cal, p)["markets"]
    return compare(real, syn)


def events_db(conn, year, exchange="kalshi", kinds=None):
    """[(markets, race start)] per race of `year` with `exchange` links: tape and mids only (no fairs)."""
    import pandas as pd
    from sqlalchemy import text

    from racinglines.markets import store as MS
    from racinglines.markets.strategies import maker_replay as R
    kinds = list(kinds or R.MODELED)
    links = pd.read_sql(text("""
        SELECT ml.token_id, ml.prediction, ml.race_id, max(ro.extra->>'session_date') AS race_start
        FROM market_links ml JOIN races ra ON ra.id = ml.race_id JOIN events e ON e.id = ra.event_id
        JOIN seasons se ON se.id = e.season_id JOIN rounds ro ON ro.race_id = ra.id
        WHERE ml.exchange = :x AND ml.prediction = ANY(:k) AND se.year = :y AND ro.extra->>'session_date' IS NOT NULL
        GROUP BY ml.token_id, ml.prediction, ml.race_id"""), conn, params=dict(x=exchange, k=kinds, y=year))
    if not len(links):
        return []
    root, toks = MS.root_for(exchange), links["token_id"].tolist()
    tr, px = MS.read(conn, "trades", tokens=toks, root=root), MS.read(conn, "prices", tokens=toks, root=root)
    tr_by, px_by = dict(tuple(tr.groupby("token_id"))), dict(tuple(px.groupby("token_id")))
    events = []
    for rid, g in links.groupby("race_id"):
        ref = R._ns(g["race_start"].iloc[0])
        mks = []
        for r in g.to_dict("records"):
            t, p = tr_by.get(r["token_id"], tr.iloc[0:0]), px_by.get(r["token_id"], px.iloc[0:0])
            mks.append(R.Market(cond=r["token_id"], kind=r["prediction"], subject="", question="", fairs={}, outcome=None,
                                mid_ts=R._ns(p["ts"]) if len(p) else np.array([], dtype="int64"),
                                mid_px=p["price"].to_numpy(float),
                                tr_ts=R._ns(t["ts"]) if len(t) else np.array([], dtype="int64"),
                                tr_px=t["price"].to_numpy(float), tr_sz=t["size"].to_numpy(float),
                                tr_buy=(t["side"] == "BUY").to_numpy(bool)))
        events.append((mks, ref))
    return events


def _rng(seed, key):
    h = int.from_bytes(hashlib.sha256(f"{seed}:{key}".encode()).digest()[:8], "little")
    return np.random.default_rng(h)


def pool(p=Params()):
    """The anonymous takers: ids (seeded UUIDs) and event budgets."""
    rng = np.random.default_rng(p.seed)
    budget = np.exp(rng.uniform(math.log(p.budget[0]), math.log(p.budget[1]), p.takers)).round(2)
    ids = [str(uuid.UUID(bytes=rng.bytes(16), version=4)) for _ in range(p.takers)]
    return ids, budget


def generate(mk, cal, start, end, ref, p=Params(), left=None):
    """One market's synthetic tape over [start, end) (int64 ns): (ts, limit price, contracts, buys YES, taker
    index) arrays, sorted by time. cal: fit()'s entry for the market's kind; ref: the event's last session
    start (as in fit). left: the pool's budgets left
    (mutated; default a fresh pool). Arrivals before the first recorded mid are skipped (no view to trade on)."""
    if left is None:
        left = pool(p)[1].copy()
    rng = _rng(p.seed, mk.cond)
    step = int(p.step_min * 60e9)
    sizes = np.asarray(cal["sizes"] or [1.0])
    noise = max(cal["noise"], p.min_noise)
    buy = min(max(cal["buy"], 0.02), 0.98)          # views lean so a noise trader buys YES this often, as recorded
    bias = noise * NormalDist().inv_cdf(buy)
    rows = []
    for t in range(int(start), int(end), step):
        lam = cal["rate"][_bucket(max(ref - t, 0) / HOUR)] * step / HOUR * p.intensity
        n = int(rng.poisson(lam)) if lam > 0 else 0
        if not n:
            continue
        ts = np.sort(t + (rng.random(n) * step).astype("int64"))
        informed = rng.random(n) < p.informed
        seen = np.where(informed, ts + int(p.horizon_min * 60e9), ts)
        view = _mid_at(mk, np.minimum(seen, end))
        now = _mid_at(mk, ts)
        belief = view + bias + rng.normal(0.0, noise, n)
        who = rng.integers(len(left), size=n)
        sz = sizes[rng.integers(len(sizes), size=n)]
        for k in range(n):
            if np.isnan(now[k]) or np.isnan(belief[k]):
                continue
            buy = bool(belief[k] > now[k]) if belief[k] != now[k] else bool(rng.random() < cal["buy"])
            limit = belief[k] - p.edge if buy else belief[k] + p.edge
            limit = float(min(max(limit, 0.01), 0.99))
            cost = limit if buy else 1 - limit
            q = min(float(sz[k]), math.floor(left[who[k]] / max(cost, 0.01)))
            if q < 1:
                continue
            left[who[k]] -= q * cost
            rows.append((int(ts[k]), limit, q, buy, int(who[k])))
    if not rows:
        return (np.array([], dtype="int64"), np.array([]), np.array([]), np.array([], dtype=bool),
                np.array([], dtype="int64"))
    ts, px, sz, buy, who = map(np.array, zip(*rows))
    return ts.astype("int64"), px.astype(float), sz.astype(float), buy.astype(bool), who.astype("int64")


def retape(ev, cal, p=Params()):
    """load_event()'s dict with each market's tape replaced by a synthetic one over the event's stages (a kind
    without a calibration gets no trades). Adds ev["takers"]: {market key: taker index per synthetic trade}
    and ev["pool"]: (ids, budgets)."""
    ids, budget = pool(p)
    left = budget.copy()
    start = min(s["start"] for s in ev["stages"]) if ev["stages"] else 0
    end = max(s["end"] for s in ev["stages"]) if ev["stages"] else 0
    ref = max(ev["sessions"]) if ev.get("sessions") else end
    markets, who = [], {}
    for mk in sorted(ev["markets"], key=lambda m: m.cond):
        c = cal.get(mk.kind)
        if c is None:
            ts, px, sz, buy, w = (np.array([], dtype="int64"), np.array([]), np.array([]), np.array([], dtype=bool),
                                  np.array([], dtype="int64"))
        else:
            ts, px, sz, buy, w = generate(mk, c, start, end, ref, p, left)
        markets.append(replace(mk, tr_ts=ts, tr_px=px, tr_sz=sz, tr_buy=buy))
        who[mk.cond] = w
    order = {m.cond: i for i, m in enumerate(ev["markets"])}
    markets.sort(key=lambda m: order[m.cond])
    return dict(ev, markets=markets, takers=who, pool=(ids, budget))


def _q(a, x):
    return float(np.quantile(a, x)) if len(a) else None


def compare(real, synthetic):
    """Calibration check: per kind, the real tape against the synthetic one (trades, median and 90th
    percentile size, buy share). real / synthetic: lists of Markets. -> list of dict rows."""
    rows = []
    for kind in sorted({m.kind for m in real}):
        r = [m for m in real if m.kind == kind]
        s = [m for m in synthetic if m.kind == kind]
        rs, ss = np.concatenate([m.tr_sz for m in r] or [[]]), np.concatenate([m.tr_sz for m in s] or [[]])
        rb, sb = np.concatenate([m.tr_buy for m in r] or [[]]), np.concatenate([m.tr_buy for m in s] or [[]])
        rows.append(dict(kind=kind, real_trades=len(rs), synth_trades=len(ss), real_median=_q(rs, 0.5),
                         synth_median=_q(ss, 0.5), real_p90=_q(rs, 0.9), synth_p90=_q(ss, 0.9),
                         real_buy=float(rb.mean()) if len(rb) else None, synth_buy=float(sb.mean()) if len(sb) else None))
    return rows
