"""
Live downhill final: poll UCI's live timing (ChronoRace), simulate the rest of the final, and re-quote.

    racinglines mtb_dh live --slug 20260925_mtb --final 3 --quali 2,91 --conditions "clear, rutted"

Every --interval seconds:
  1. **Feed.** The final's live JSON: who has finished (time), who is on course (latest split), who is
     still to start (start order), DNF / DNS.
  2. **Pace.** Each rider's time blends this weekend's qualifying (best run, sessions put on one scale)
     with the season model's pre-final view (its podium-probability rank mapped onto the field's
     qualifying times; SEASON_WEIGHT). Riders who were mathematically safe to qualify (the season model's
     make-the-final probability in the top quarter of the field, fading to none at the median) may have
     cruised: when their run came out slower than their season rank implies, that gap becomes extra
     uncertainty (wider spread, up to SAFE_SIGMA_CAP) rather than a faster expected time; a fast run is
     genuine pace. The time is
     scaled by how the final is running against qualifying so far (median final/qualifying ratio of the
     finishers, starting from a small prior). A rider on course is projected from the latest split with
     the split-to-finish ratio (finishers of the final, else qualifying). Noise shrinks with the distance
     left; track conditions ("rutted", "wet") widen it and raise the crash / DNF risk.
  3. **Monte Carlo.** N_SIMS simulated finishes -> each rider's probability of every top rank: P(1st),
     P(2nd), P(3rd), top 3, top 5, top 10.
  4. **Maker.** The demo maker quotes YES on "wins" and "podium" for every rider: fair +- a half-spread,
     wider while the rider is on course and just before they start; no quote once the outcome is certain.
     Every quote is appended to the history.
  5. **Taker.** The demo taker's picks (picks.json, chosen once; see make_picks) are marked against the
     quotes and settled when the final is over.

Files: data/runs/live/<slug>_<key>/
    latest.json        the newest snapshot (the web app's Live tab reads it)
    history.jsonl      one line per poll: counts, every market's fair value and quote
    picks.json         the demo taker's picks
    meta.json          the model inputs and parameters (qualifying times, split ratios, season priors,
                       conditions), written on the first poll and whenever they change
    book.json          the maker's private book: position and cash per market, crowd totals, the seeds
    crowd.jsonl        every anonymous crowd fill, per poll, with that poll's random seed
    raw/<ts>.json.gz   every raw feed response, as received      } kept permanently, so the final can be
    snaps/<ts>.json.gz every full snapshot (rank probabilities)   } replayed or re-scored later
A demo experiment: the quotes are simulated, nothing is traded anywhere.
"""

import json
import math
import time
from datetime import datetime, timezone

import numpy as np

from racinglines import paths

FEED = "https://prod.chronorace.be/api/results/generic/uci/{slug}/dh?key={key}"
MODEL_VERSION = 2               # v2 (27 Sep 2026, mid-final): track trend by start order, shared track shock,
                                # recent-finisher split ratios, quotes pulled after a rider's last split
N_SIMS = 20_000
TREND_RECENCY = 0.85            # weight of a finisher k slots before the latest: TREND_RECENCY ** k
TREND_PRIOR_N = 8.0             # the trend slope is shrunk toward flat with the weight of this many runs
TREND_BLEND = 0.5               # riders still to come: this share of the trend, the rest the whole final's level
                                # (start order is reverse qualifying rank, so the slope also carries regression to
                                # the mean of slow qualifiers, not only track wear)
RECENT_SPLITS = 6               # split-to-finish ratios from this many most recent finishers
RANKS = 10
SEASON_WEIGHT = 0.4             # share of the pace from the season model for a rider who had to push in qualifying
SAFE_SIGMA_CAP = 0.012          # a safe rider's slow qualifying adds up to this much log-time spread (they may have cruised)
PRIOR_FACTOR = 1.01             # a final runs ~1% slower than qualifying before any evidence (tired track)
SIGMA_START = 0.016             # log-time s.d. of a rider still to start
DNF_START = 0.05                # crash / DNF probability of a rider still to start
COND = {"rutted": (0.004, 0.02), "wet": (0.010, 0.04), "dry": (0.0, 0.0), "clear": (0.0, 0.0)}
HALF_SPREAD = 0.03
WIDEN_ON_COURSE = 0.02          # the rider is on course: information arrives fast
WIDEN_NEXT = 0.01               # next few to start
MARKETS = {"win": "Wins the final", "podium": "Podium (top 3)"}
# the private book's crowd: CROWD anonymous takers, each hitting a quoted market with probability CROWD_P per
# poll, on a random side; each taker has an event budget of $10-200 and bets part of what's left each time;
# anonymous, tracked as one group
CROWD = 1000
CROWD_P = 0.0004
CROWD_BUDGET = (10.0, 200.0)    # $ each taker may bet over the whole event, log-uniform (a private beta, play money)
CROWD_BET = (0.2, 0.8)          # each bet: this share of what the taker has left (at least MIN_BET)
MIN_BET = 2.0
LATE_WHEN_LEFT = 3              # the late window opens once the fourth-to-last rider has started (<= 3 to start):
LATE_INTERVAL = 2               # polls every 2 s, and every taker gets a fresh $LATE_CAP for the window
LATE_CAP = 100.0
LATE_PACE = 50.0                # the late window trades at the push pace: 50x the normal crowd rate
BASE_INTERVAL = 5               # CROWD_P is per BASE_INTERVAL seconds; faster polls scale it down (same rate)
MAX_POS = 2500.0                # the maker's shares per market, either way
SKEW = 1.0                      # quotes lean against inventory: shift = -SKEW x half-spread x inventory / MAX_POS


EVENT_NAMES = {"20260925_mtb": "Whistler DH final (private book)"}


def event_name(slug):
    """A private-book event's display name (its positions have no events row)."""
    return EVENT_NAMES.get(slug, slug)


def book_curve(slug, maker=True):
    """The private book's P&L through the event, from every saved snapshot since the book opened (all of the event's finals):
    [(time, P&L)], the maker's total (maker) or the demo taker's (the negative of the maker's P&L vs the
    taker). Cached per snapshot count: the files are only ever added to."""
    import glob
    import gzip

    import pandas as pd
    files = sorted(glob.glob(str(paths.DATA / "runs" / "live" / f"{slug}_*" / "snaps" / "*.json.gz")))
    opened = min((book_opened(*p.parent.name.rsplit("_", 1))
                  for p in (paths.DATA / "runs" / "live").glob(f"{slug}_*/crowd.jsonl")), default=None)
    cache = book_curve.__dict__.setdefault("cache", {})
    if cache.get(slug, (None,))[0] != len(files):
        pts = []
        for f in files:
            with gzip.open(f, "rt") as fh:
                s = json.load(fh)
            if s.get("maker_pnl") and (opened is None or s["ts"] >= opened):   # a replaced book's snapshots: not this one
                pts.append((pd.Timestamp(s["ts"]), s["maker_pnl"]["total"], -s["maker_pnl"]["taker"]))
        cache[slug] = (len(files), pts)
    return [(t, m if maker else k) for t, m, k in cache[slug][1]]


def outdir(slug, key):
    d = paths.DATA / "runs" / "live" / f"{slug}_{key}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch(slug, key, session=None):
    import requests

    from racinglines.sources import http
    s = session or requests.Session()
    r = http.get(s, FEED.format(slug=slug, key=key), headers={"User-Agent": "racinglines/0.1"}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d if isinstance(d, dict) else {}


def quali_best(slug, keys, session=None):
    """{bib: best qualifying time ms, on the first session's scale} and the qualifying split-to-finish
    ratios (median per split). Later sessions can run in different conditions (Whistler's Q2 ran ~2% slower
    than Q1), so each is rescaled to the first with the median time ratio of the riders who finished both."""
    sessions, ratios = [], {}
    for k in keys:
        d = fetch(slug, k, session)
        t = {}
        for r in d.get("Results") or []:
            if r.get("Status") != "Finished" or not r.get("RaceTime"):
                continue
            t[r["RaceNr"]] = r["RaceTime"]
            for i, x in enumerate(r.get("Times") or []):
                if x.get("RaceTime"):
                    ratios.setdefault(i, []).append(r["RaceTime"] / x["RaceTime"])
        sessions.append(t)
    best = dict(sessions[0]) if sessions else {}
    for t in sessions[1:]:
        both = [best[n] / t[n] for n in t if n in best and 0.9 < best[n] / t[n] < 1.1]
        scale = float(np.median(both)) if len(both) >= 5 else 1.0
        for n, x in t.items():
            best[n] = min(best.get(n, 1e12), x * scale)
    return best, {i: float(np.median(v)) for i, v in ratios.items() if v}


def parse(d):
    """Riders of the final: dict(bib, name, nation, uci_rank, status, time, splits, order)."""
    riders = d.get("Riders") or {}
    nxt = {n: i for i, n in enumerate(d.get("NextToStart") or [])}
    on = {r["RaceNr"]: r for r in d.get("OnTrack") or []}
    out = []
    for r in d.get("Results") or []:
        n = r["RaceNr"]
        rd = riders.get(str(n), {})
        live = on.get(n, r)
        status = live.get("Status") or r.get("Status")
        splits = [t.get("RaceTime") for t in (live.get("Times") or r.get("Times") or []) if t.get("RaceTime")]
        out.append(dict(bib=n, name=rd.get("PrintName") or str(n), nation=rd.get("Nation"), team=rd.get("UciTeamName"),
                        uci_rank=rd.get("UciRank"), status=status, start=r.get("ExpectedStartTime"),
                        time=r.get("RaceTime") if status == "Finished" else None, splits=splits,
                        split_pos=[t.get("Position") for t in (live.get("Times") or [])],
                        sort=r.get("SortOrder"), next=nxt.get(n)))
    order = sorted(out, key=lambda x: (x["start"] is None, x["start"] or 0))
    for i, x in enumerate(order):
        x["slot"] = i                                                   # start order
    return out


def track_trend(fin, qbest):
    """(ratio(slot) function, s.d. of the ratio for the next riders): how the final runs against qualifying,
    by start slot. A recency-weighted line through the clean runs (crashes and big mistakes left out), its
    slope shrunk toward flat; None until three clean runs."""
    pts = [(r["slot"], r["time"] / qbest[r["bib"]]) for r in fin if r["bib"] in qbest and r.get("slot") is not None]
    pts = [(x, y) for x, y in pts if 0.85 < y < 1.12]
    if len(pts) < 3:
        return None, None
    x = np.array([p[0] for p in pts], float)
    y = np.log([p[1] for p in pts])
    keep = np.ones(len(x), bool)
    for _ in range(3):                                   # robust: drop runs far off the line (mistakes), refit
        w = TREND_RECENCY ** (x.max() - x) * keep
        xm, ym = np.average(x, weights=w), np.average(y, weights=w)
        sxx = float(np.sum(w * (x - xm) ** 2))
        slope = float(np.sum(w * (x - xm) * (y - ym)) / (sxx + TREND_PRIOR_N * max(float(np.var(x)), 1.0)))
        resid = y - (ym + slope * (x - xm))
        sd = max(float(np.sqrt(np.average(resid ** 2, weights=w))), 0.008)
        new = np.abs(resid) <= 2.5 * sd
        if new.sum() < 3 or (new == keep).all():
            break
        keep = new
    w = TREND_RECENCY ** (x.max() - x) * keep
    n_eff = float(w.sum() ** 2 / np.sum(w ** 2))
    lo, hi = float(y.min()) - 0.02, float(y.max()) + 0.02

    def ratio(slot):
        return float(np.exp(np.clip(ym + slope * (slot - xm), lo, hi)))
    return ratio, sd / math.sqrt(max(n_eff, 1.0)) + 0.003


def conditions_noise(cond):
    extra_s, extra_d = 0.0, 0.0
    for word, (s, dnf) in COND.items():
        if word in (cond or "").lower():
            extra_s, extra_d = extra_s + s, extra_d + dnf
    return extra_s, extra_d


def season_prior(slug, category="ME"):
    """{rider name: (podium probability, make-the-final probability)} from the latest downhill forecast for
    this event's race."""
    from sqlalchemy import text

    from racinglines.db.config import get_engine
    try:
        with get_engine().connect() as c:
            rows = c.execute(text("""
                SELECT a.display_name, rp.podium_prob, rp.make_final_prob FROM race_predictions rp
                JOIN athletes a ON a.id = rp.athlete_id JOIN races ra ON ra.id = rp.race_id
                JOIN events e ON e.id = ra.event_id JOIN categories ca ON ca.id = ra.category_id
                WHERE e.source_key = :k AND ca.code = :c AND rp.model_run_id = (
                    SELECT max(rp2.model_run_id) FROM race_predictions rp2 WHERE rp2.race_id = ra.id)"""),
                dict(k=slug, c=category)).all()
        return {n: (float(p or 0), float(mf or 0)) for n, p, mf in rows}
    except Exception:                                  # noqa: BLE001  (no database: qualifying only)
        return {}


def safety(riders, prior):
    """{bib: 0..1}: how safe each rider was to qualify, by the season model's make-the-final probability
    within this field (top quarter = 1, fading to 0 at the median)."""
    mf = {r["bib"]: prior[r["name"]][1] for r in riders if r["name"] in prior}
    if len(mf) < 4:
        return {}
    v = np.array(sorted(mf.values()))
    med, q3 = float(np.quantile(v, 0.5)), float(np.quantile(v, 0.75))
    return {b: float(np.clip((x - med) / max(q3 - med, 1e-9), 0, 1)) for b, x in mf.items()}


def blended_pace(riders, qbest, prior):
    """({bib: base time ms}, {bib: extra log-time s.d.}): qualifying blended with the season model's rank
    (mapped onto the field's qualifying times); a safe rider's slow qualifying adds spread, not speed."""
    field = [r for r in riders if r["bib"] in qbest]
    qtimes = sorted(qbest[r["bib"]] for r in field)
    if not prior or not field:
        return {r["bib"]: qbest[r["bib"]] for r in field}, {}
    ranked = sorted(field, key=lambda r: -prior.get(r["name"], (0.0, 0.0))[0])
    model_t = {r["bib"]: qtimes[i] for i, r in enumerate(ranked)}
    safe = safety(riders, prior)
    out, extra = {}, {}
    for r in field:
        b = r["bib"]
        out[b] = (1 - SEASON_WEIGHT) * qbest[b] + SEASON_WEIGHT * model_t[b]
        # cruising only makes a run slower: a safe rider whose run came out slower than their season rank
        # implies is less known, not faster; a fast run is genuine pace whoever sets it
        gap = math.log(qbest[b] / model_t[b]) if qbest[b] > model_t[b] else 0.0
        extra[b] = min(SAFE_SIGMA_CAP, 0.5 * safe.get(b, 0.0) * gap)
        r["safety"], r["extra_sigma"] = safe.get(b, 0.0), extra[b]
    return out, extra


def simulate(riders, qbest, qratio, cond="", n=N_SIMS, seed=7, prior=None):
    """Rank probabilities for every rider. Returns (rows, factor)."""
    rng = np.random.default_rng(seed)
    extra_s, extra_d = conditions_noise(cond)
    fin = [r for r in riders if r["status"] == "Finished" and r["time"]]
    # how the final runs against qualifying: the median of clean runs (crashes and big mistakes, > 12% off,
    # are left out), shrunk toward the prior with the weight of two runs
    ratios = [r["time"] / qbest[r["bib"]] for r in fin if r["bib"] in qbest]
    clean = [x for x in ratios if 0.85 < x < 1.12]
    k = len(clean)
    factor = (PRIOR_FACTOR * 2 + float(np.median(clean)) * k) / (2 + k) if k else PRIOR_FACTOR
    trend, trend_sd = track_trend(fin, qbest)                            # v2: the track changes through the final
    shock = rng.normal(0, trend_sd, n) if trend_sd else np.zeros(n)      # one shared track shock per simulation
    # split -> finish ratios from the final's finishers, else qualifying
    fratio = {}
    clean_fin = [r for r in fin if r["bib"] not in qbest or 0.85 < r["time"] / qbest[r["bib"]] < 1.12]
    clean_fin = sorted(clean_fin, key=lambda r: r.get("slot") or 0)[-RECENT_SPLITS:]     # v2: recent finishers
    for i in range(6):
        v = [r["time"] / r["splits"][i] for r in clean_fin if len(r["splits"]) > i and r["splits"][i]]
        fratio[i] = float(np.median(v)) if len(v) >= 3 else qratio.get(i)
    slowest = max(qbest.values()) if qbest else 240_000
    base, extra_sig = blended_pace(riders, qbest, prior or {})
    times = np.full((n, len(riders)), np.inf)
    for j, r in enumerate(riders):
        st = r["status"]
        if st == "Finished" and r["time"]:
            times[:, j] = r["time"]
        elif st in ("DNF", "DNS", "DSQ"):
            continue
        elif st == "InRace" and r["splits"] and fratio.get(len(r["splits"]) - 1):
            i = len(r["splits"]) - 1
            mu = r["splits"][i] * fratio[i]
            left = max(0.05, 1 - r["splits"][i] / mu)                 # share of the run still to go
            t = mu * np.exp(rng.normal(0, (SIGMA_START + extra_s) * math.sqrt(left), n))
            dnf = rng.random(n) < (DNF_START + extra_d) * left
            times[:, j] = np.where(dnf, np.inf, t)
        else:                                                           # still to start (or on course, no split yet)
            f = (trend(r["slot"]) ** TREND_BLEND * factor ** (1 - TREND_BLEND)
                 if trend and r.get("slot") is not None else factor)
            mu = base.get(r["bib"], slowest * 1.02) * f
            t = mu * np.exp(rng.normal(0, SIGMA_START + extra_s + extra_sig.get(r["bib"], 0.0), n) + shock)
            dnf = rng.random(n) < DNF_START + extra_d
            times[:, j] = np.where(dnf, np.inf, t)
    order = np.argsort(times, axis=1, kind="stable")
    ranks = np.empty_like(order)
    ranks[np.arange(n)[:, None], order] = np.arange(1, len(riders) + 1)
    finished_any = np.isfinite(times)
    rows = []
    for j, r in enumerate(riders):
        rk = np.where(finished_any[:, j], ranks[:, j], 999)
        p = {f"p{i}": float((rk == i).mean()) for i in range(1, RANKS + 1)}
        rows.append(dict(r, **p, top3=float((rk <= 3).mean()), top5=float((rk <= 5).mean()),
                         top10=float((rk <= 10).mean()), p_finish=float(finished_any[:, j].mean()),
                         expected=None if not np.isfinite(times[:, j]).any() else float(np.median(times[:, j][np.isfinite(times[:, j])]))))
    simulate.trend = None if not trend else dict(next_ratio=trend(max((r.get("slot") or 0) for r in riders)),
                                                  sd=trend_sd)
    return rows, factor


def quote(fair, rider, n_next=3, inv=0.0):
    """The maker's YES quote on one market: (bid, ask) in cents-rounded dollars, or (None, None). Leans
    against inventory; stops adding to a position at MAX_POS."""
    if fair is None or fair <= 0.005 or fair >= 0.995:
        return None, None
    hs = HALF_SPREAD
    if rider["status"] == "InRace":
        if MODEL_VERSION >= 2 and len(rider.get("splits") or []) >= 4:   # past the last split: the result is all but
            return None, None                                             # known, so only informed takers would trade
        hs += WIDEN_ON_COURSE
    elif rider.get("next") is not None and rider["next"] < n_next:
        hs += WIDEN_NEXT
    if MODEL_VERSION >= 2 and rider["status"] not in ("Finished", "InRace"):
        hs += 0.01                                                        # the track is changing under them
    shift = -SKEW * hs * inv / MAX_POS
    bid = math.floor((fair - hs + shift) * 100) / 100
    ask = math.ceil((fair + hs + shift) * 100) / 100
    bid = bid if bid >= 0.01 and inv < MAX_POS else None
    ask = ask if ask <= 0.99 and inv > -MAX_POS else None
    return bid, ask


def load_book(out):
    p = out / "book.json"
    if p.exists():
        return json.loads(p.read_text())
    import uuid
    rng = np.random.default_rng(20260927)                       # the crowd's budgets and ids, fixed once (replayable)
    budget = np.exp(rng.uniform(math.log(CROWD_BUDGET[0]), math.log(CROWD_BUDGET[1]), CROWD)).round(2).tolist()
    ids = [str(uuid.UUID(bytes=rng.bytes(16), version=4)) for _ in range(CROWD)]   # anonymous: no accounts
    return dict(markets={}, crowd=dict(fills=0, volume=0.0, budget_total=round(sum(budget), 2)), seeds=[],
                budget=budget, left=list(budget), ids=ids, takers={})


def crowd_fills(quotes, book, rng, intensity=1.0, pot="left"):
    """One poll of the anonymous crowd against the maker's quotes (intensity x the normal hit rate). Mutates
    book; returns the fills."""
    fills = []
    for q in quotes:
        if q["bid"] is None and q["ask"] is None:
            continue
        for _ in range(int(rng.binomial(CROWD, min(1.0, CROWD_P * intensity)))):
            who = int(rng.integers(CROWD))                             # an anonymous taker with money left
            if book[pot][who] < MIN_BET:
                continue
            m = book["markets"].setdefault(f"{q['bib']}:{q['market']}", dict(inv=0.0, cash=0.0, crowd_inv=0.0, crowd_cash=0.0))
            sides = [s for s, px in (("buy", q["ask"]), ("sell", q["bid"])) if px is not None]
            side = sides[int(rng.integers(len(sides)))]
            px = q["ask"] if side == "buy" else q["bid"]
            cost = px if side == "buy" else 1 - px                     # a crowd seller buys NO at 1 - bid
            stake = max(MIN_BET, book[pot][who] * float(rng.uniform(*CROWD_BET)))
            stake = min(stake, book[pot][who])
            shares = round(stake / max(cost, 0.01), 2)
            room = MAX_POS + m["inv"] if side == "buy" else MAX_POS - m["inv"]
            shares = min(shares, max(room, 0.0))
            if shares <= 0:
                continue
            book[pot][who] = round(book[pot][who] - shares * cost, 2)
            tid = book["ids"][who]
            pos = book["takers"].setdefault(tid, {}).setdefault(f"{q['bib']}:{q['market']}", [0.0, 0.0])
            sg = 1 if side == "buy" else -1                             # crowd's YES shares
            m["inv"] -= sg * shares
            m["cash"] += sg * shares * px
            m["crowd_inv"] += sg * shares
            m["crowd_cash"] -= sg * shares * px
            pos[0] += sg * shares                                       # this taker's YES shares and cash
            pos[1] -= sg * shares * px
            book["crowd"]["fills"] += 1
            book["crowd"]["volume"] += shares * cost
            fills.append(dict(bib=q["bib"], market=q["market"], side=side, price=px, shares=shares, fair=q["fair"],
                              taker=tid))
    return fills


PRIVATE = "private"
MAKER_USER, TAKER_USER = "maker", "taker"        # the demo accounts: the book's maker, and the tracked taker


def sync_positions(slug, rows, book, picks, fair, outcomes):
    """Write the private book into paper_positions (venue 'private', event_key = the event slug): the demo
    maker's position per market (the crowd's fills and the demo taker's picks) and the demo taker's picks.
    Replaced on every update, so the Positions page shows them live and settled."""
    from sqlalchemy import text

    from racinglines.db.config import get_engine
    names = {r["bib"]: r["name"] for r in rows}
    maker = {}
    for k, mk in book["markets"].items():
        maker[k] = dict(yes=mk["inv"], cash=mk["cash"])
    for p in picks:
        k = f"{p['bib']}:{p['market']}"
        m = maker.setdefault(k, dict(yes=0.0, cash=0.0))
        m["yes"] -= p["shares"]
        m["cash"] += p["stake"]

    def row(uid, k, yes, cash):
        b, m = k.split(":")
        o = outcomes.get((int(b), m))
        return dict(u=uid, e=slug, k=f"{slug}:{k}", kind=f"dh_{m}", subj=names.get(int(b), b), yes=yes, no=0.0,
                    cash=cash, mark=fair.get(k), out=o, v=PRIVATE)
    with get_engine().begin() as c:
        ids = dict(c.execute(text("SELECT username, id FROM users WHERE username = ANY(:u)"),
                             dict(u=[MAKER_USER, TAKER_USER])).all())
        c.execute(text("DELETE FROM paper_positions WHERE venue = :v AND event_key = :e"), dict(v=PRIVATE, e=slug))
        rows_ = []
        if MAKER_USER in ids:
            rows_ += [row(ids[MAKER_USER], k, m["yes"], m["cash"]) for k, m in maker.items() if abs(m["yes"]) > 1e-9]
        if TAKER_USER in ids:
            rows_ += [row(ids[TAKER_USER], f"{p['bib']}:{p['market']}", p["shares"], -p["stake"]) for p in picks]
        for r in rows_:
            c.execute(text("""INSERT INTO paper_positions (user_id, candidate_id, race_id, event_key, market_key, kind, subject,
                                yes_shares, no_shares, cash, mark, outcome, venue)
                              VALUES (:u, NULL, NULL, :e, :k, :kind, :subj, :yes, :no, :cash, :mark, :out, :v)"""), r)


def crowd_results(book, fair, outcomes, spotlight_seed=20260927):
    """Each anonymous taker's P&L (marked to fair; settled where known), summarised as a group, plus one
    randomly chosen taker's bets."""
    def value(k):
        b, m = k.split(":")
        o = outcomes.get((int(b), m))
        return float(o) if o is not None else fair.get(k, 0.0)
    pnl = {tid: sum(c + y * value(k) for k, (y, c) in mk.items()) for tid, mk in book.get("takers", {}).items()}
    if not pnl:
        return None
    v = np.array(list(pnl.values()))
    ids = sorted(pnl)
    pick = ids[int(np.random.default_rng(spotlight_seed).integers(len(ids)))]
    bets = [dict(market=k, yes=y, cash=c, value=value(k), pnl=c + y * value(k)) for k, (y, c) in book["takers"][pick].items()]
    return dict(bettors=len(v), up=int((v > 0.005).sum()), down=int((v < -0.005).sum()), median=float(np.median(v)),
                best=float(v.max()), worst=float(v.min()), total=float(v.sum()),
                spotlight=dict(taker=pick, pnl=pnl[pick], bets=bets))


def book_pnl(book, fair, outcomes, picks=()):
    """The maker's P&L, marked to fair (settled where the outcome is known): total, vs the crowd, vs the demo taker."""
    def value(key):
        b, m = key.split(":")
        o = outcomes.get((int(b), m))
        return float(o) if o is not None else fair.get(key, 0.0)
    crowd = sum(mk["cash"] + mk["inv"] * value(k) for k, mk in book["markets"].items())
    taker = sum(p["stake"] - p["shares"] * value(f"{p['bib']}:{p['market']}") for p in picks)
    return dict(total=crowd + taker, crowd=crowd, taker=taker)


def settle(rows, done):
    """Outcomes once the final is over: {(bib, market): bool}."""
    if not done:
        return {}
    fin = sorted([r for r in rows if r["status"] == "Finished" and r["time"]], key=lambda r: r["time"])
    rank = {r["bib"]: i + 1 for i, r in enumerate(fin)}
    return {(r["bib"], m): (rank.get(r["bib"], 999) <= (1 if m == "win" else 3)) for r in rows for m in MARKETS}


def update(slug, key, quali_keys, cond="", session=None, interval=BASE_INTERVAL):
    """One poll: feed -> simulation -> quotes -> files. Returns the snapshot."""
    import gzip
    d = fetch(slug, key, session)
    fetched = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = outdir(slug, key)
    (out / "raw").mkdir(exist_ok=True)
    (out / "snaps").mkdir(exist_ok=True)
    with gzip.open(out / "raw" / f"{fetched}.json.gz", "wt") as f:                 # the feed, as received
        json.dump(d, f)
    import hashlib
    riders = parse(d)
    cache = update.__dict__.setdefault("cache", {})                   # per process: nothing old is re-processed
    if "q" not in cache:
        cache["q"] = quali_best(slug, quali_keys, session)            # qualifying: fixed for the final
        cache["prior"] = season_prior(slug)                           # the season model's pre-final view: fixed
    qbest, qratio = cache["q"]
    prior = cache["prior"]
    # the timing state that pricing depends on; an unchanged feed reuses the last simulation
    state = hashlib.sha1(json.dumps([(r["bib"], r["status"], r["time"], r["splits"]) for r in riders]).encode()).hexdigest()
    meta = dict(slug=slug, key=key, quali_keys=list(quali_keys), conditions=cond,
                params=dict(MODEL_VERSION=MODEL_VERSION, TREND_RECENCY=TREND_RECENCY, TREND_PRIOR_N=TREND_PRIOR_N,
                            TREND_BLEND=TREND_BLEND,
                            RECENT_SPLITS=RECENT_SPLITS, N_SIMS=N_SIMS, SIGMA_START=SIGMA_START, DNF_START=DNF_START, PRIOR_FACTOR=PRIOR_FACTOR,
                            SEASON_WEIGHT=SEASON_WEIGHT, SAFE_SIGMA_CAP=SAFE_SIGMA_CAP, COND=COND, HALF_SPREAD=HALF_SPREAD,
                            WIDEN_ON_COURSE=WIDEN_ON_COURSE, WIDEN_NEXT=WIDEN_NEXT, seed=7, CROWD=CROWD,
                            CROWD_P=CROWD_P, CROWD_BUDGET=CROWD_BUDGET, CROWD_BET=CROWD_BET, MIN_BET=MIN_BET,
                            LATE_WHEN_LEFT=LATE_WHEN_LEFT,
                            LATE_INTERVAL=LATE_INTERVAL, LATE_CAP=LATE_CAP, LATE_PACE=LATE_PACE,
                            MAX_POS=MAX_POS, SKEW=SKEW),
                qbest={str(k): v for k, v in qbest.items()}, qratio={str(k): v for k, v in qratio.items()},
                prior={k: list(v) for k, v in prior.items()})
    blob = json.dumps(meta, sort_keys=True, default=str)
    if not (out / "meta.json").exists() or (out / "meta.json").read_text() != blob:
        (out / "meta.json").write_text(blob)
        (out / f"meta_{fetched}.json").write_text(blob)                               # every version kept
    if cache.get("state") == state and cache.get("rows") is not None:
        rows, factor = json.loads(cache["rows"]), cache["factor"]       # nothing new on the timing screen
        changed = False
    else:
        rows, factor = simulate(riders, qbest, qratio, cond, prior=prior)
        cache.update(state=state, rows=json.dumps(rows), factor=factor)
        changed = True
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in {r["status"] for r in rows}}
    done = not any(r["status"] in ("InRace", "NA", "Waiting") for r in rows) and counts.get("Finished", 0) > 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    book = load_book(out)
    picks = json.loads((out / "picks.json").read_text()) if (out / "picks.json").exists() else []
    pick_inv = {}
    for p in picks:                                                     # the demo taker's YES: the maker is short
        pick_inv[f"{p['bib']}:{p['market']}"] = pick_inv.get(f"{p['bib']}:{p['market']}", 0.0) - p["shares"]
    quotes = []
    for r in rows:
        r["quali"] = qbest.get(r["bib"])
        for m, fair in (("win", r["p1"]), ("podium", r["top3"])):
            k = f"{r['bib']}:{m}"
            inv = book["markets"].get(k, {}).get("inv", 0.0) + pick_inv.get(k, 0.0)
            bid, ask = quote(fair, r, inv=inv)
            quotes.append(dict(bib=r["bib"], market=m, fair=round(fair, 4), bid=bid, ask=ask, inv=round(inv, 2)))
    outcomes = settle(rows, done)
    # The anonymous crowd trades on every individually valid quote until the next poll (seeded: replayable).
    # Existing books closed by the retired global lockout are reopened while the final is still running.
    seed = int(datetime.now(timezone.utc).timestamp())
    to_start = sum(1 for r in rows if r["status"] in ("NA", "Waiting"))
    if book.get("closed") and not done:
        book.pop("closed", None)
        book.pop("closed_at", None)
    if to_start <= LATE_WHEN_LEFT and not book.get("late"):             # the late window opens: fresh $100 caps
        book["late"], book["late_at"] = True, now
        book["late_left"] = [LATE_CAP] * CROWD
    pot = "late_left" if book.get("late") else "left"
    rate = interval / BASE_INTERVAL                                      # same crowd rate per second at any poll rate
    if book.get("late"):
        rate *= LATE_PACE                                                # late window: the high-volume push pace
    if done:
        fills = []
    else:
        fills = crowd_fills(quotes, book, np.random.default_rng(seed), intensity=rate, pot=pot)
    book["seeds"].append(seed)
    (out / "book.json").write_text(json.dumps(book))
    with (out / "crowd.jsonl").open("a") as f:
        f.write(json.dumps(dict(ts=now, seed=seed, fills=fills, last_call=None)) + "\n")
    fairmap = {f"{q['bib']}:{q['market']}": q["fair"] for q in quotes}
    pnl = book_pnl(book, fairmap, outcomes, picks)
    cres = crowd_results(book, fairmap, outcomes)
    try:
        if changed or fills or not cache.get("synced"):                 # only when the book or the prices moved
            sync_positions(slug, rows, book, picks, fairmap, outcomes)
            cache["synced"] = True
    except Exception as ex:                          # noqa: BLE001  never stop the live loop for the database
        print(f"positions sync failed: {ex}", flush=True)
    snap = dict(ts=now, slug=slug, key=key, round=d.get("DisplayName"), conditions=cond, factor=factor,
                model_version=MODEL_VERSION, trend=getattr(simulate, "trend", None),
                counts=counts, done=done, riders=rows, quotes=quotes, maker_pnl=pnl,
                betting=dict(closed=False, closed_at=None, last_call=False,
                             to_start=to_start, late=bool(book.get("late")), late_at=book.get("late_at"),
                             interval=interval, late_cap=LATE_CAP),
                crowd=dict(book["crowd"], takers=CROWD, last_fills=len(fills),
                           active=sum(1 for x, b in zip(book["left"], book["budget"]) if x < b - 0.005),
                           left=round(sum(book["left"]), 2), results=cres),
                outcomes=[dict(bib=b, market=m, yes=v) for (b, m), v in outcomes.items()])
    with gzip.open(out / "snaps" / f"{fetched}.json.gz", "wt") as f:
        json.dump(snap, f, default=str)
    tmp = out / "latest.json.tmp"
    tmp.write_text(json.dumps(snap, default=str))
    tmp.replace(out / "latest.json")
    with (out / "history.jsonl").open("a") as f:
        f.write(json.dumps(dict(ts=now, counts=counts, fair={f"{q['bib']}:{q['market']}": q["fair"] for q in quotes},
                                quotes={f"{q['bib']}:{q['market']}": [q["bid"], q["ask"]] for q in quotes})) + "\n")
    return snap


def run(slug, key, quali_keys, cond="", interval=BASE_INTERVAL, minutes=0, echo=print):
    import requests
    s = requests.Session()
    t0 = time.time()
    late = False
    while True:
        try:
            snap = update(slug, key, quali_keys, cond, s, interval=LATE_INTERVAL if late else interval)
            if not late and (snap.get("betting") or {}).get("late"):      # relaunch at the late-window pace
                late = True
                echo(f"{snap['ts']} late window: polling every {LATE_INTERVAL} s, fresh ${LATE_CAP:.0f} caps")
            lead = max(snap["riders"], key=lambda r: r["p1"])
            echo(f"{snap['ts']} {snap['counts']} favourite {lead['name']} {lead['p1']:.1%}"
                 + (" · FINAL OVER" if snap["done"] else ""))
            if snap["done"]:
                return snap
        except Exception as ex:                      # noqa: BLE001  keep polling through feed hiccups
            echo(f"error: {ex}")
        if minutes and time.time() - t0 > minutes * 60:
            return None
        time.sleep(LATE_INTERVAL if late else interval)


# ---------------------------------------------------------------------------
# The demo taker's picks: chosen once, at the maker's quotes of that moment
# ---------------------------------------------------------------------------

def make_picks(slug, key, picks, stake=25.0):
    """picks: [dict(name (substring of the rider's name), market 'win'|'podium', side 'YES'|'NO', hype 1-5,
    why)]. Each is taken at the maker's current ask (YES) or 1 - bid (NO), for `stake` dollars. Written to
    picks.json with the time and price; never re-priced."""
    out = outdir(slug, key)
    snap = json.loads((out / "latest.json").read_text())
    by = {r["bib"]: r for r in snap["riders"]}
    qs = {(q["bib"], q["market"]): q for q in snap["quotes"]}
    done = []
    for p in picks:
        r = next(r for r in snap["riders"] if p["name"].lower() in r["name"].lower())
        q = qs[(r["bib"], p["market"])]
        price = q["ask"] if p["side"] == "YES" else (1 - q["bid"] if q["bid"] is not None else None)
        if price is None:
            continue
        done.append(dict(p, bib=r["bib"], rider=r["name"], price=round(price, 2), stake=stake,
                         shares=round(stake / price, 2), fair_then=q["fair"], ts=snap["ts"], status_then=by[r["bib"]]["status"]))
    (out / "picks.json").write_text(json.dumps(done, indent=1))
    return done


def load(slug, key):
    out = outdir(slug, key)
    snap = json.loads((out / "latest.json").read_text()) if (out / "latest.json").exists() else None
    picks = json.loads((out / "picks.json").read_text()) if (out / "picks.json").exists() else []
    hist = []
    if (out / "history.jsonl").exists():
        hist = [json.loads(line) for line in (out / "history.jsonl").read_text().splitlines() if line.strip()]
    return snap, picks, hist


def latest():
    """(slug, key) of the most recently updated final, however old (replay), or None."""
    base = paths.DATA / "runs" / "live"
    found = list(base.glob("*/latest.json")) if base.exists() else []
    if not found:
        return None
    slug, key = max(found, key=lambda p: p.stat().st_mtime).parent.name.rsplit("_", 1)
    return slug, key


def state(max_age_h=6):
    """'live' while a final is running (updated within max_age_h hours and not over), 'replay' once it is
    over (or stale), None when nothing was ever recorded. Cached on latest.json's mtime (read per page)."""
    cur = latest()
    if cur is None:
        return None
    p = outdir(*cur) / "latest.json"
    m = p.stat().st_mtime
    cache = state.__dict__.setdefault("cache", {})
    if cache.get(p) is None or cache[p][0] != m:
        cache[p] = (m, bool(json.loads(p.read_text()).get("done")))
    return "live" if not cache[p][1] and time.time() - m <= max_age_h * 3600 else "replay"


def snap_times(slug, key):
    """The saved snapshots' times (their file names, e.g. 20260927T223221), oldest first."""
    return sorted(f.name.split(".")[0] for f in (outdir(slug, key) / "snaps").glob("*.json.gz"))


def load_at(slug, key, t):
    """load() as of one snapshot (the last one at or before t, a snap_times name): the snapshot, the picks,
    the history up to it."""
    import bisect
    import gzip
    times = snap_times(slug, key)
    if not times:
        return load(slug, key)
    name = times[max(0, bisect.bisect_right(times, t) - 1)]
    with gzip.open(outdir(slug, key) / "snaps" / f"{name}.json.gz", "rt") as f:
        snap = json.load(f)
    _, picks, hist = load(slug, key)
    return snap, picks, [h for h in hist if h["ts"] <= snap["ts"]]


def book_opened(slug, key):
    """When the private book that ran opened: its first crowd poll's time (ISO), or None."""
    p = outdir(slug, key) / "crowd.jsonl"
    if not p.exists():
        return None
    with p.open() as f:
        first = f.readline()
    return json.loads(first)["ts"] if first.strip() else None


def book_at(slug, key, ts=None):
    """The maker's private book rebuilt from the crowd's fills up to ts (ISO; None = all): {market: dict(inv,
    cash)} (the maker's side; the same as book.json at the end) and the crowd polls up to ts, newest last."""
    p = outdir(slug, key) / "crowd.jsonl"
    polls = [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []
    polls = [e for e in polls if ts is None or e["ts"] <= ts]
    markets = {}
    for e in polls:
        for f in e["fills"]:
            mk = markets.setdefault(f"{f['bib']}:{f['market']}", dict(inv=0.0, cash=0.0))
            sg = -1 if f["side"] == "buy" else 1                       # the crowd buys YES: the maker is short it
            mk["inv"] += sg * f["shares"]
            mk["cash"] -= sg * f["shares"] * f["price"]
    return markets, polls


def current(max_age_h=12):
    """(slug, key) of the most recently updated live final, if updated within max_age_h hours."""
    base = paths.DATA / "runs" / "live"
    if not base.exists():
        return None
    latest = [p for p in base.glob("*/latest.json")]
    if not latest:
        return None
    p = max(latest, key=lambda p: p.stat().st_mtime)
    if time.time() - p.stat().st_mtime > max_age_h * 3600:
        return None
    slug, key = p.parent.name.rsplit("_", 1)
    return slug, key
