"""
The Mario Kart tour's engine (the `--demo` flag; racinglines/demo/tour.py): the pipeline end to end on a synthetic
sport, in miniature, with no database or network. Settings in racinglines/demo/kart.toml; everything is made up.

    history(cfg, seed)                 seasons of past races: every driver's sector times, the items, the result
    fit(races, half_life, shrink)      the pace model: each driver's pace from past sector times (robust to items)
    backtest(cfg, races, progress)     walk-forward over the history, a sweep of the fit's settings, each race priced
                                       before the start by Monte Carlo and scored (Brier, log loss) against the result
    forecast(cfg, model, track, n)     the next race's win / podium / top-5 probabilities from a big Monte Carlo
    Race(cfg, model, track, seed, out) the live race: sector by sector the model re-prices the rest of the race, the
                                       bookie re-quotes every market (markets/quoting.py), the crowd trades
                                       (markets/crowd.py), and the run folder is written for live_report

A race is `laps x sectors` sectors. Each sector every driver takes sector_s - pace + noise, plus the items: a mushroom
boost (more likely the further back), a banana, a red shell (not the leader), a blue shell (the leader). The model
knows the item rates and its own pace estimates; the race runs on the hidden true pace, which drifts a little from
season to season, so a fit that weights recent races does better.
"""

import json
from datetime import datetime, timedelta

import numpy as np

KINDS = ("race_win", "race_podium")
HALF_LIVES = (2.0, 4.0, 8.0, 1e9)        # races; 1e9 = every past race weighs the same
SHRINKS = (0.0, 2.0, 5.0)                # pseudo-races of pace 0 (an average kart) added to the fit
DRIFT = 0.025                            # s per sector: the true pace's season-to-season random walk


def load():
    import tomllib
    from importlib.resources import files
    return tomllib.loads((files("racinglines.demo") / "kart.toml").read_text())


def names(cfg):
    return [d["name"] for d in cfg["drivers"]]


def n_sectors(cfg):
    return cfg["laps"] * cfg["sectors"]


def label(cfg, k):
    """The update after k sectors: 'Start', 'Lap 2 · S3', 'Finish'."""
    if k == 0:
        return "Start"
    if k >= n_sectors(cfg):
        return "Finish"
    return f"Lap {k // cfg['sectors'] + 1} · S{k % cfg['sectors'] + 1}"


# ---------------------------------------------------------------------------
# The race process: one sector for many simulated races at once
# ---------------------------------------------------------------------------

def _ranks(cum):
    return np.argsort(np.argsort(cum, axis=-1), axis=-1)


def sector(cum, pace, track, items, rng):
    """One sector for every row of cum (sims x drivers, cumulative times): (sector times, {item: hit mask})."""
    n = cum.shape[-1]
    chaos = track["chaos"]
    rank = _ranks(cum)
    hit = {}
    u = rng.random((5,) + cum.shape)
    hit["boost"] = u[0] < chaos * (items["boost"]["p"] + items["boost"]["back"] * rank / max(n - 1, 1))
    hit["banana"] = u[1] < chaos * items["banana"]["p"]
    hit["red_shell"] = (u[2] < chaos * items["red_shell"]["p"]) & (rank > 0)
    blue = u[3][..., :1] < chaos * items["blue_shell"]["p"]             # once per race-sector, on the leader
    hit["blue_shell"] = blue & (rank == 0)
    dt = track["sector_s"] - pace + track["noise"] * rng.standard_normal(cum.shape)
    for k, m in hit.items():
        dt = dt + m * items[k]["s"]
    return dt, hit


def finish(cum, k, cfg, track, pace, n_sims, rng):
    """Monte Carlo of the rest of the race from cum (drivers) after k sectors: finishing times (n_sims x drivers)."""
    sims = np.repeat(np.asarray(cum, float)[None, :], n_sims, axis=0)
    for _ in range(k, n_sectors(cfg)):
        dt, _ = sector(sims, pace, track, cfg["items"], rng)
        sims += dt
    return sims


def probs(times):
    """{kind: per-driver probability} from finishing times (n_sims x drivers)."""
    rank = _ranks(times)
    return dict(race_win=(rank == 0).mean(0), race_podium=(rank < 3).mean(0), race_top5=(rank < 5).mean(0))


def run_race(cfg, track, pace, rng):
    """One real race on the true pace: dict(grid, times (sectors+1 x drivers, cumulative), events per sector, order)."""
    nm = names(cfg)
    n = len(nm)
    grid = rng.permutation(n)                                    # starting order: 0.15 s a place
    cum = np.zeros((1, n))
    cum[0, grid] = np.arange(n) * 0.15
    times, events, items = [cum[0].copy()], [], []
    for _ in range(n_sectors(cfg)):
        dt, hit = sector(cum, pace, track, cfg["items"], rng)
        cum = cum + dt
        times.append(cum[0].copy())
        events.append([cfg["items"][k]["text"].format(name=nm[i]) for k, m in hit.items() for i in np.flatnonzero(m[0])])
        items.append(np.any([m[0] for m in hit.values()], axis=0))
    order = [int(i) for i in np.argsort(times[-1])]
    return dict(grid=[int(i) for i in grid], times=np.array(times), events=events, items=np.array(items), order=order)


# ---------------------------------------------------------------------------
# History, the pace model, the backtest
# ---------------------------------------------------------------------------

def true_pace(cfg, seed, seasons):
    """The hidden true pace per season (seasons+1 rows: the last is the season the demo race is in)."""
    rng = np.random.default_rng([seed, 1])
    base = np.array([d["pace"] for d in cfg["drivers"]])
    walk = np.cumsum(rng.normal(0, DRIFT, (seasons + 1, len(base))), axis=0)
    return base + walk - walk.mean(1, keepdims=True)


def history(cfg, seed=7, seasons=5, progress=None):
    """Seasons of past races, one per track per season: [dict(season, track, times, order, events)]."""
    pace = true_pace(cfg, seed, seasons)
    rng = np.random.default_rng([seed, 2])
    tracks = list(cfg["tracks"])
    out, n = [], seasons * len(tracks)
    for s in range(seasons):
        for t in tracks:
            r = run_race(cfg, cfg["tracks"][t], pace[s], rng)
            out.append(dict(season=2021 + s, track=t, times=r["times"].tolist(), order=r["order"],
                            items=r["items"].tolist(), events=sum(len(e) for e in r["events"])))
            if progress:
                progress(len(out), n, f"{2021 + s} {cfg['tracks'][t]['name']}")
    return out


def race_pace(race):
    """Each driver's pace in one past race, from the clean sectors only (the feed says where an item hit, and the
    model adds the items back itself): the field's mean clean sector time minus theirs, averaged over sectors."""
    dt = np.diff(np.asarray(race["times"]), axis=0)               # sectors x drivers
    clean = ~np.asarray(race["items"], bool)
    d = np.where(clean, dt, np.nan)
    rel = np.nanmean(d, axis=1, keepdims=True) - d
    return np.nan_to_num(np.nanmean(rel, axis=0))


def fit(races, half_life=4.0, shrink=2.0):
    """Pace per driver: the recency-weighted mean of race_pace over past races (newest weighs 1, halving every
    half_life races), shrunk toward an average kart by `shrink` pseudo-races."""
    if not races:
        return None
    p = np.array([race_pace(r) for r in races])
    w = 0.5 ** (np.arange(len(races))[::-1] / half_life)
    return (w[:, None] * p).sum(0) / (w.sum() + shrink)


def _score(pr, order):
    """Brier and log loss of win and podium probabilities against one result."""
    n = len(order)
    pos = np.empty(n, int)
    pos[order] = np.arange(n)
    out = {}
    for kind, y in (("race_win", pos == 0), ("race_podium", pos < 3)):
        p = np.clip(pr[kind], 1e-4, 1 - 1e-4)
        out[kind] = ((p - y) ** 2).mean(), -(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()
    return out


def backtest(cfg, races, sims=2500, warmup=4, progress=None, seed=7):
    """Walk-forward: for every race after the first `warmup`, fit on the races before it with each setting
    (HALF_LIVES x SHRINKS), price it before the start and score it. Returns the leaderboard (best first) with the
    baseline (every driver equal) as the reference."""
    rng = np.random.default_rng([seed, 3])
    settings = [(h, s) for h in HALF_LIVES for s in SHRINKS]
    n = len(races[0]["order"])
    tot = {st: np.zeros(4) for st in settings}
    base_tot = np.zeros(4)
    steps, done = (len(races) - warmup) * len(settings), 0
    for i in range(warmup, len(races)):
        r = races[i]
        track = cfg["tracks"][r["track"]]
        start = np.asarray(r["times"][0])
        b = _score(dict(race_win=np.full(n, 1 / n), race_podium=np.full(n, 3 / n)), r["order"])
        base_tot += [b["race_win"][0], b["race_win"][1], b["race_podium"][0], b["race_podium"][1]]
        for st in settings:
            pr = probs(finish(start, 0, cfg, track, fit(races[:i], *st), sims, rng))
            sc = _score(pr, r["order"])
            tot[st] += [sc["race_win"][0], sc["race_win"][1], sc["race_podium"][0], sc["race_podium"][1]]
            done += 1
            if progress:
                progress(done, steps, f"{r['season']} {track['name']} · half-life {_hl(st[0])}, shrink {st[1]:g}")
    m = len(races) - warmup
    rows = [dict(half_life=h, shrink=s, win_brier=v[0] / m, win_logloss=v[1] / m, podium_brier=v[2] / m,
                 podium_logloss=v[3] / m) for (h, s), v in tot.items()]
    rows.sort(key=lambda r: r["win_logloss"] + r["podium_logloss"])
    baseline = dict(win_brier=base_tot[0] / m, win_logloss=base_tot[1] / m, podium_brier=base_tot[2] / m,
                    podium_logloss=base_tot[3] / m)
    return dict(races=m, sims=sims, leaderboard=rows, baseline=baseline)


def _hl(h):
    return "all" if h >= 1e8 else f"{h:g}"


def forecast(cfg, model, track, n=200_000, chunk=10_000, progress=None, seed=7):
    """The next race at `track` before the start (grid unknown: everyone level): {kind: probabilities}, n sims."""
    rng = np.random.default_rng([seed, 4])
    t = cfg["tracks"][track]
    pace = np.asarray(model["pace"])
    acc = {k: np.zeros(len(pace)) for k in ("race_win", "race_podium", "race_top5")}
    done = 0
    while done < n:
        m = min(chunk, n - done)
        pr = probs(finish(np.zeros(len(pace)), 0, cfg, t, pace, m, rng))
        for k in acc:
            acc[k] += pr[k] * m
        done += m
        if progress:
            progress(done, n, f"{done:,} of {n:,} races simulated")
    return {k: (v / n).tolist() for k, v in acc.items()}


# ---------------------------------------------------------------------------
# The live race: the bookie's private book against the crowd, written for live_report
# ---------------------------------------------------------------------------

class Race:
    """One live race, update by update. step() advances one sector and returns the snapshot it wrote."""

    def __init__(self, cfg, model, track="rainbow-road", seed=7, sims=None):
        from racinglines.markets import crowd as C
        from racinglines.markets import quoting as Q
        from racinglines.pipelines import live as LV
        self.C, self.Q, self.LV = C, Q, LV
        self.cfg, self.track_key, self.track, self.seed = cfg, track, cfg["tracks"][track], seed
        self.names = names(cfg)
        self.pace = np.asarray(model["pace"])                     # the model's pace (fitted)
        true = np.asarray(model.get("true_pace") or self.pace)    # the race runs on the hidden truth
        self.race = run_race(cfg, self.track, true, np.random.default_rng([seed, 5]))
        self.rng = np.random.default_rng([seed, 6])
        self.sims = sims or cfg["sims"]
        self.qp = Q.Params.from_dict(cfg["quoting"])
        self.cp = C.Params.from_dict(cfg["crowd"])
        self.run = f"kart-{track}-{seed}"
        self.k = 0
        self.t0 = datetime.fromisoformat(cfg["start"])
        self.out = LV.folder(self.run)
        for f in list(self.out.rglob("*")):                       # a re-run starts clean: this demo's own folder
            if f.is_file():
                f.unlink()
        self.book = C.new_book(self.cp)
        self.picks = []

    @property
    def done(self):
        return self.k > n_sectors(self.cfg)

    def fair(self, k):
        """{key: fair} after k sectors: a Monte Carlo of the rest, certain at the finish."""
        cum = self.race["times"][k]
        if k >= n_sectors(self.cfg):
            pos = np.argsort(np.argsort(cum))
            pr = dict(race_win=(pos == 0).astype(float), race_podium=(pos < 3).astype(float))
        else:
            pr = probs(finish(cum, k, self.cfg, self.track, self.pace, self.sims, self.rng))
        return {f"{kind}:{nm}": float(pr[kind][i]) for kind in KINDS for i, nm in enumerate(self.names)}

    def step(self):
        """One update: re-price, re-quote, one crowd poll (none at the finish), snapshot. None once settled."""
        if self.done:
            return None
        C, Q, LV, cfg = self.C, self.Q, self.LV, self.cfg
        k, N = self.k, n_sectors(cfg)
        fair = self.fair(k)
        over = k >= N
        outcomes = {key: bool(v) for key, v in fair.items()} if over else {}
        quotes = []
        for key, f in fair.items():
            m = self.book["markets"].get(key, {})
            bid, ask = (None, None) if over else Q.capped(f, self.qp.half_spread, m.get("inv", 0.0), m.get("cash", 0.0),
                                                          self.qp)
            kind, subj = key.split(":", 1)
            quotes.append(dict(key=key, kind=kind, subject=subj, fair=f, inv=m.get("inv", 0.0), bid=bid, ask=ask))
        fills = [] if over else C.fills(quotes, self.book, self.rng, self.cp)
        ts = self.t0 + timedelta(seconds=cfg["interval_s"] * k)
        stamp = ts.strftime("%Y%m%dT%H%M%S")
        cum = self.race["times"][k]
        order = np.argsort(cum)
        standings = [dict(pos=p + 1, name=self.names[i], gap=float(cum[i] - cum[order[0]])) for p, i in enumerate(order)]
        res = C.crowd_results(self.book, fair, outcomes, spotlight_seed=self.seed)
        crowd = dict(self.book["crowd"], takers=self.cp.takers, active=len(self.book["takers"]), results=res,
                     name=cfg["crowd"]["name"])
        snap = dict(ts=ts.isoformat(), sport="kart", done=over, update=dict(label=label(cfg, k), k=k, of=N),
                    markets=[dict(key=q["key"], kind=q["kind"], subject=q["subject"], fair=q["fair"]) for q in quotes],
                    quotes=quotes, fills=len(fills), events=self.race["events"][k - 1] if k else [],
                    standings=standings, maker_pnl=C.book_pnl(self.book, fair, outcomes, self.picks), crowd=crowd,
                    outcomes=[dict(key=key, yes=v) for key, v in outcomes.items()])
        if k == 0:
            LV.write_meta(self.out, dict(sport="kart", event_key=self.run, title=f"{self.track['name']} ({cfg['title']})",
                                         opened_at=ts.isoformat(), maker=cfg["bookie"]["name"],
                                         crowd=cfg["crowd"]["name"],
                                         settings=dict(track=self.track, quoting=self.qp.to_dict(),
                                                       crowd=self.cp.to_dict(), sims=self.sims)), stamp)
        (self.out / "book.json").write_text(json.dumps(self.book))
        LV.append(self.out, "crowd.jsonl", dict(ts=snap["ts"], seed=k, fills=fills, done=over))
        LV.write_snapshot(self.out, snap, stamp)
        LV.append(self.out, "history.jsonl", dict(ts=snap["ts"], label=snap["update"]["label"], fair=fair))
        self.k += 1
        return snap


def odds(p):
    """Fair decimal odds for a probability ('–' at zero)."""
    return "–" if p <= 0 else f"{1 / p:.2f}" if p < 1 else "1.00"


def money(x):
    return f"{'+' if x >= 0 else '-'}${abs(x):,.2f}"

