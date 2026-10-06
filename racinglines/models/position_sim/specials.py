"""Sportsbook-style specials: one market spec, priced from the race simulation and settled against real results.

A spec is a plain dict, {"kind": ..., ...}, so a book's board can be typed in or OCR'd straight into a list:

    classified          athlete                     finishes classified (status OK; DNF, DNS and DSQ are not)
    team_classified     team                        every car of the team classified
    team_points         team                        every car of the team in the points (top 10)
    n_classified        line                        classified finishers over `line` (e.g. 17.5)
    last_classified     athlete                     the last classified finisher
    h2h                 a, b, both_dnf="void"       a finishes ahead of b ("void": both out voids the bet;
                                                    "behind": both out is a loss for a)

`sim_prob` counts simulations (sim = position_sim.model.simulate_race output, ids/teams in column order);
`settle` returns 1 / 0 / None (void) from one race's actual results, so the same spec scores a backtest.
The classified rule is the data's (status OK); F1's 90%-of-distance rule is not applied, see
docs/f1-specials-feasibility.md.
"""

import itertools

import numpy as np
import pandas as pd

KINDS = ("classified", "team_classified", "team_points", "n_classified", "last_classified", "h2h")
# also priced by sim_prob (listed per book, not by board()): win, team_win, team_most_points (a tie is shared),
# first_retirement / first_team_retirement / no_retirement (approximate: retirement order within a race is
# exchangeable, so each retiring car is equally likely to go first; real first retirements cluster on lap 1)
EXTRA_KINDS = ("win", "team_win", "team_most_points", "first_retirement", "first_team_retirement", "no_retirement")


def _cols(ids, teams, spec):
    ids = list(ids)
    if "athlete" in spec:
        return [ids.index(spec["athlete"])]
    if "team" in spec:
        return [i for i, t in enumerate(teams) if t == spec["team"]]
    if "a" in spec:
        return [ids.index(spec["a"]), ids.index(spec["b"])]
    return []


def _indicator(spec, pos, dnf, cols, pts=None, teams=None):
    """(win, void) arrays over the rows of a (sims, drivers) position / dnf pair (win is fractional for ties)."""
    k = spec["kind"]
    void = np.zeros(len(pos), bool)
    if k == "win":
        win = (pos[:, cols[0]] == 1) & ~dnf[:, cols[0]]
    elif k == "team_win":
        win = ((pos[:, cols] == 1) & ~dnf[:, cols]).any(1)
    elif k == "team_most_points":
        tl = sorted(set(teams))
        tp = np.stack([pts[:, [i for i, t in enumerate(teams) if t == x]].sum(1) for x in tl], 1)
        mine = tp[:, tl.index(spec["team"])]
        top = tp.max(1)
        win = np.where(mine == top, 1.0 / (tp == top[:, None]).sum(1), 0.0)
    elif k in ("first_retirement", "first_team_retirement", "no_retirement"):
        n = dnf.sum(1)
        if k == "no_retirement":
            win = n == 0
        else:
            share = np.where(n[:, None] > 0, dnf / np.maximum(n[:, None], 1), 0.0)
            win = share[:, cols].sum(1)
    elif k == "top_n":
        win = (pos[:, cols[0]] <= spec["n"]) & ~dnf[:, cols[0]]
    elif k == "classified":
        win = ~dnf[:, cols[0]]
    elif k == "team_classified":
        win = ~dnf[:, cols].any(1) if cols else np.zeros(len(pos), bool)
    elif k == "team_points":
        win = ((pos[:, cols] <= 10) & ~dnf[:, cols]).all(1) if cols else np.zeros(len(pos), bool)
    elif k == "n_classified":
        win = (~dnf).sum(1) > spec["line"]
    elif k == "last_classified":
        worst = np.where(dnf, -1, pos).argmax(1)
        win = (worst == cols[0]) & ~dnf[:, cols[0]]
    elif k == "h2h":
        a, b = cols
        both = dnf[:, a] & dnf[:, b]
        win = ~dnf[:, a] & (dnf[:, b] | (pos[:, a] < pos[:, b]))
        if spec.get("both_dnf", "void") == "void":
            void = both
    else:
        raise ValueError(f"unknown special kind {k!r}")
    return win, void


def sim_prob(spec, sim, ids, teams):
    """Model probability of the spec (conditional on not void) and the void rate."""
    pos, dnf = np.asarray(sim["pos"]), np.asarray(sim["dnf"]).astype(bool)
    win, void = _indicator(spec, pos, dnf, _cols(ids, teams, spec), np.asarray(sim.get("points", pos)), list(teams))
    live = ~void
    return (float(win[live].mean()) if live.any() else float("nan")), float(void.mean())


def settle(spec, actual):
    """1 / 0 / None (void) from actual = DataFrame(athlete_id, team_key, status, position) of one race."""
    ids, teams = actual["athlete_id"].tolist(), actual["team_key"].tolist()
    status, pos = actual["status"].to_numpy(), actual["position"].to_numpy(float)
    dnf = (status != "OK")[None, :]
    p = np.where(status == "OK", pos, 99.0)[None, :]
    cols = _cols(ids, teams, spec)
    pts = actual["points"].to_numpy(float)[None, :] if "points" in actual else p
    win, void = _indicator(spec, p, dnf, cols, pts, teams)
    return None if void[0] else (int(win[0]) if float(win[0]).is_integer() else float(win[0]))


def board(entrants, kinds=KINDS, line=None, h2h_pairs="all", both_dnf="void"):
    """Every spec of the chosen kinds for one race's entrants (DataFrame athlete_id, driver, team_key).

    h2h_pairs: "all" (every pair), "teammates", or a list of (athlete_a, athlete_b); each unordered pair is
    listed once in each direction so both sides of a book's line can be priced."""
    specs = []
    for r in entrants.itertuples():
        for k in ("classified", "last_classified"):
            if k in kinds:
                specs.append(dict(kind=k, athlete=r.athlete_id, label=f"{r.driver} {k.replace('_', ' ')}"))
    for t in sorted(set(entrants["team_key"])):
        for k in ("team_classified", "team_points"):
            if k in kinds:
                specs.append(dict(kind=k, team=t, label=f"{t} {k.replace('_', ' ')}"))
    if "n_classified" in kinds:
        n = len(entrants)
        for ln in ([line] if line is not None else [n - 4.5, n - 3.5, n - 2.5]):
            specs.append(dict(kind="n_classified", line=ln, label=f"classified over {ln}"))
    if "h2h" in kinds:
        names = dict(zip(entrants["athlete_id"], entrants["driver"]))
        team = dict(zip(entrants["athlete_id"], entrants["team_key"]))
        ids = list(entrants["athlete_id"])
        if h2h_pairs == "all":
            pairs = list(itertools.permutations(ids, 2))
        elif h2h_pairs == "teammates":
            pairs = [(a, b) for a, b in itertools.permutations(ids, 2) if team[a] == team[b]]
        else:
            pairs = list(h2h_pairs)
        for a, b in pairs:
            specs.append(dict(kind="h2h", a=a, b=b, both_dnf=both_dnf, label=f"{names[a]} ahead of {names[b]}"))
    return specs


def price(specs, sim, entrants):
    """DataFrame of every spec with its model probability, void rate and fair decimal odds."""
    ids, teams = entrants["athlete_id"].tolist(), entrants["team_key"].astype(str).tolist()
    rows = []
    for s in specs:
        p, v = sim_prob(s, sim, ids, teams)
        rows.append(dict(kind=s["kind"], label=s.get("label", ""), prob=p, void=v,
                         fair_odds=(1 / p if p and p > 0 else float("inf")), spec=s))
    return pd.DataFrame(rows)


def decimal(odds, fmt="auto"):
    """Decimal odds from American (+230 / -150), fractional ("7/2") or decimal input. fmt="decimal" takes the
    number as decimal odds as-is; "auto" treats a number of 100 or more (or any negative) as American, which
    misreads a decimal 501.00, so a decimal board must say fmt="decimal"."""
    if fmt == "decimal":
        return float(odds)
    if isinstance(odds, str):
        o = odds.strip()
        if "/" in o:
            n, d = o.split("/")
            return 1 + float(n) / float(d)
        odds = float(o)
    odds = float(odds)
    if abs(odds) >= 100:
        return 1 + odds / 100 if odds > 0 else 1 + 100 / -odds
    return odds


def devig(odds):
    """Margin-free probabilities of one market's outcomes (proportional removal), from any odds format."""
    inv = np.array([1 / decimal(o) for o in odds])
    return inv / inv.sum()


def edge_table(priced, book_odds, bankroll=400.0):
    """Join model prices to a book. book_odds: {label: odds in any format} for the side being bet. Returns edge
    = prob * decimal - 1 (expected profit per $1), and half-Kelly stake = bankroll * 0.5 * edge / (decimal - 1)."""
    t = priced[priced["label"].isin(book_odds)].copy()
    t["odds"] = t["label"].map(lambda k: decimal(book_odds[k]))
    t["edge"] = t["prob"] * t["odds"] - 1
    t["half_kelly_stake"] = (bankroll * 0.5 * t["edge"] / (t["odds"] - 1)).clip(lower=0).round(2)
    return t.sort_values("edge", ascending=False).reset_index(drop=True)


def backtest(meas, hist, kinds=KINDS, start_year=2024, n_sims=2000, mode="pre_quali", seed=0, h2h_pairs="teammates",
             last_n=None, echo=None):
    """Price every special of `kinds` for each past race strictly before its cutoff (price_race enforces the
    leakage audit), settle it on the real result, and return one row per race x spec with prob and outcome.
    Score with `score`. Void bets are dropped."""
    from racinglines.models.position_sim import pricing as PRC
    rng = np.random.default_rng(seed)
    events = meas.drivers[meas.drivers["year"] >= start_year].drop_duplicates("event_id").sort_values("r_ts")
    if last_n:
        events = events.tail(last_n)
    rows = []
    for i, ev in enumerate(events.itertuples(), 1):
        s = meas.sessions(ev.event_id)
        anchor = s.get("qual") if mode == "pre_quali" else s.get("race")
        if anchor is None or pd.isna(anchor):
            continue
        cutoff = anchor - PRC.ONE_MIN
        if not (hist["r_ts"] + PRC.M.RACE_DONE < cutoff).any():
            continue
        summ, ex = PRC.price_race(meas, hist, cutoff, ev.event_id, n_sims=n_sims, rng=rng)
        ent = ex["entrants"]
        specs = board(ent, kinds=kinds, h2h_pairs=h2h_pairs)
        priced = price(specs, ex["sim"], ent)
        actual = meas.drivers[meas.drivers["event_id"] == ev.event_id][["athlete_id", "team_key", "status", "position"]]
        actual = actual[actual["athlete_id"].isin(set(ent["athlete_id"]))]
        have = set(actual["athlete_id"])
        for sp, pr in zip(specs, priced.itertuples()):
            if not {sp.get(k) for k in ("athlete", "a", "b")} - {None} <= have:
                continue            # a driver with no result row (did not take part): nothing to settle
            y = settle(sp, actual)
            if y is not None:
                rows.append(dict(event_id=ev.event_id, year=ev.year, round=ev.series_round, kind=sp["kind"],
                                 label=pr.label, prob=pr.prob, y=y))
        if echo:
            echo(f"progress {i}/{len(events)} {ev.year} R{ev.series_round:02d} {ev.venue}")
    return pd.DataFrame(rows)


def score(bt, bins=(0, .05, .15, .3, .5, .7, .85, .95, 1.0001)):
    """Per kind: bets, mean prob, hit rate, Brier, Brier of the constant hit-rate baseline, and the reliability bins."""
    out, rel = [], []
    for k, g in bt.groupby("kind"):
        brier = float(((g["prob"] - g["y"]) ** 2).mean())
        base = float(((g["y"].mean() - g["y"]) ** 2).mean())
        out.append(dict(kind=k, n=len(g), mean_prob=g["prob"].mean(), hit_rate=g["y"].mean(), brier=brier,
                        brier_constant=base, skill=1 - brier / base if base else float("nan")))
        b = pd.cut(g["prob"], list(bins), right=False)
        r = g.groupby(b, observed=True).agg(n=("y", "size"), mean_prob=("prob", "mean"), hit_rate=("y", "mean")).reset_index(drop=True)
        r.insert(0, "kind", k)
        rel.append(r)
    return pd.DataFrame(out), pd.concat(rel, ignore_index=True)


BOOK_KINDS = dict(race_win="win", team_win="team_win", team_most_points="team_most_points",
                  first_retirement="first_retirement", first_team_retirement="first_team_retirement")


def _fold(s):
    import unicodedata
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()


def price_book(book, sim, entrants, extra=None, bankroll=400.0, fmt="decimal", thin=(), sprint=None, session_sims=None):
    """Price a typed-in book. book: DataFrame(market, subject, odds); market in BOOK_KINDS (priced from the sim),
    or a key of `extra` ({market: {subject: prob}}, e.g. safety_car from props.py); drivers by surname, teams by
    their model key, "none" for no retirement. Unpriced markets (fastest lap, VSC) come back with prob NaN.
    thin: markets whose model input is too thin to stake on (stake forced to 0). Returns the book with its margin-free probability per market, our prob, edge (prob x decimal - 1), half-Kelly stake."""
    ids, teams = entrants["athlete_id"].tolist(), entrants["team_key"].astype(str).tolist()
    sur = {}
    for i, n in zip(ids, entrants["driver"]):
        sur.setdefault(_fold(n).replace(" jr", "").split()[-1], i)
    out = []
    for r in book.itertuples():
        prob = float("nan")
        if extra and r.market in extra:
            prob = extra[r.market].get(r.subject, float("nan"))
        elif r.market in ("team_classified", "team_points", "driver_classified"):
            sub, _, side = str(r.subject).partition(":")        # "ferrari:yes" / "ferrari:no", "Norris:yes"
            kind = dict(team_classified="team_classified", team_points="team_points", driver_classified="classified")[r.market]
            key = sur.get(_fold(sub)) if kind == "classified" else (sub if sub in teams else None)
            if key is not None:
                p_yes = sim_prob(dict(kind=kind, **({"athlete": key} if kind == "classified" else {"team": key})), sim, ids, teams)[0]
                prob = p_yes if side == "yes" else 1 - p_yes
        elif session_sims and str(r.market).rsplit("_", 1)[0] in session_sims:
            sess, _, what = str(r.market).rpartition("_")           # "fp1_win", "qual_top3"
            spec = (dict(kind="win", athlete=sur.get(_fold(r.subject))) if what == "win"
                    else dict(kind="top_n", n=int(what[3:]), athlete=sur.get(_fold(r.subject))) if what.startswith("top") else None)
            if spec and spec["athlete"] is not None:
                prob = sim_prob(spec, session_sims[sess], ids, teams)[0]
        elif r.market in ("sprint_win", "sprint_team_win") and sprint is not None:
            if r.market == "sprint_win":
                prob = sim_prob(dict(kind="win", athlete=sur[_fold(r.subject)]), sprint, ids, teams)[0] if _fold(r.subject) in sur else prob
            elif r.subject in teams:
                prob = sim_prob(dict(kind="team_win", team=r.subject), sprint, ids, teams)[0]
        elif r.market in BOOK_KINDS:
            k, sub = BOOK_KINDS[r.market], _fold(r.subject)
            if sub == "none":
                spec = dict(kind="no_retirement")
            elif k in ("first_retirement", "win"):
                spec = dict(kind=k, athlete=sur[sub]) if sub in sur else None
            else:
                spec = dict(kind=k, team=r.subject) if r.subject in teams else None
            if spec:
                prob = sim_prob(spec, sim, ids, teams)[0]
        out.append(dict(market=r.market, subject=r.subject, odds=decimal(r.odds, fmt), prob=prob))
    t = pd.DataFrame(out)
    t["_g"] = t["market"] + "|" + t["subject"].astype(str).map(lambda x: x.split(":")[0] if ":" in x else "")
    t["book_prob"] = t.groupby("_g")["odds"].transform(lambda o: pd.Series(1 / o.to_numpy() / (1 / o).sum(), index=o.index))
    t["edge"] = t["prob"] * t["odds"] - 1
    t["half_kelly_stake"] = (bankroll * 0.5 * t["edge"] / (t["odds"] - 1)).clip(lower=0).round(2)
    t = t.drop(columns="_g")
    t["thin"] = t["market"].isin(thin)
    # an edge above +100%, or a 100x-or-longer price, is the model's longshot tail against a placeholder price
    # (a book's "501.00" for every backmarker), not a bet
    t["suspect"] = (t["edge"] > 1.0) | (t["odds"] >= 100)
    t.loc[t["thin"] | t["suspect"], "half_kelly_stake"] = 0.0
    return t


# ---------------------------------------------------------------------------
# Sprints: the race finishing model on the sprint-qualifying grid, with sprint points and fewer retirements
# ---------------------------------------------------------------------------

SPRINT_DNF_SCALE = 0.5      # 8 of 110 sprint starts in 2025-26 ended out vs about 14% in races; untuned (decision log needed)
SPRINT_SIGMA_SCALE = 1.0    # finishing noise vs a full race; untuned


def lap_order(view, event_id, round_kind, entrants):
    """Finishing order of a practice-type session (fp1/fp2/fp3/sprint_qual) from each driver's best lap, since those
    sessions have no stored classification. Ranks 1..n over the entrants; a driver without a timed lap ranks last.
    None until the session is in the as-of view."""
    p = view.practice[(view.practice["event_id"] == event_id) & (view.practice["round"] == round_kind)]
    if p.empty:
        return None
    best = p.groupby("athlete_id")["best_def"].min()
    rank = best.rank(method="first")
    return entrants["athlete_id"].map(rank).fillna(len(entrants)).to_numpy(float)


def sprint_grid(view, event_id, entrants):
    """Sprint grid = sprint-qualifying order (best lap) from the as-of view; None until that session has run."""
    return lap_order(view, event_id, "sprint_qual", entrants)


def sprint_sim(meas, hist, cutoff, event_id, n_sims=10000, rng=None, entrants=None, venue=None, year=None,
               dnf_scale=None, sigma_scale=None):
    """Simulate the sprint of an event with data before `cutoff`. Returns (sim, entrants frame, audit grid label).
    The grid is the sprint-qualifying order when that session is before the cutoff, else simulated from qualifying pace."""
    from dataclasses import replace
    from racinglines.models.position_sim import model as M, pricing as PRC
    rng = rng if rng is not None else np.random.default_rng(0)
    _, ex = PRC.price_race(meas, hist, cutoff, event_id, n_sims=200, rng=np.random.default_rng(0), entrants=entrants, venue=venue)
    e, tf, fm = ex["entrants"].copy(), ex["track"], ex["model"]
    e["p_dnf"] = e["p_dnf"] * (SPRINT_DNF_SCALE if dnf_scale is None else dnf_scale)
    fm = replace(fm, sigma=fm.sigma * (SPRINT_SIGMA_SCALE if sigma_scale is None else sigma_scale))
    grid = sprint_grid(meas.view(cutoff), event_id, e)
    if grid is not None:
        e["grid"] = grid
    elif "grid" in e:
        e = e.drop(columns="grid")
    has = (meas.res["event_id"] == event_id).any()
    y = year if year else (int(meas.res.loc[meas.res["event_id"] == event_id, "year"].iloc[0]) if has else None)
    pts = M.SPRINT_POINTS.get(y, M.SPRINT_POINTS_DEFAULT)
    sim = M.simulate_race(fm, e, tf, n_sims=n_sims, rng=rng, grid_known=grid is not None, points=pts)
    return sim, e, ("sprint qualifying order" if grid is not None else "simulated from qualifying pace")


def sprint_backtest(meas, hist, mode="after_sprint_qual", n_sims=2000, seed=0, start_year=2021, dnf_scale=None,
                    sigma_scale=None, echo=None):
    """One row per sprint x driver: sprint win probability and outcome (and the team's win share), priced before
    the sprint. mode: after_sprint_qual (grid known) or pre_weekend (before FP1)."""
    from racinglines.models.position_sim import pricing as PRC
    rng = np.random.default_rng(seed)
    sp = meas.res[(meas.res["round"] == "sprint") & (meas.res["year"] >= start_year)]
    rows = []
    for ev_id in sp.drop_duplicates("event_id").sort_values("start_date")["event_id"]:
        s = meas.sessions(ev_id)
        anchor = s.get("sprint") if mode == "after_sprint_qual" else min(
            [t for t in (s.get(k) for k in ("fp1", "fp2", "fp3", "sprint_qual")) if t is not None and pd.notna(t)] or [pd.NaT])
        if anchor is None or pd.isna(anchor):
            continue
        cutoff = anchor - PRC.ONE_MIN
        if not (hist["r_ts"] + PRC.M.RACE_DONE < cutoff).any():
            continue
        sim, e, grid = sprint_sim(meas, hist, cutoff, ev_id, n_sims=n_sims, rng=rng, dnf_scale=dnf_scale, sigma_scale=sigma_scale)
        a = sp[sp["event_id"] == ev_id].set_index("athlete_id")
        ids, teams = e["athlete_id"].tolist(), e["team_key"].astype(str).tolist()
        won = {i: float(a["position"].get(i, 99) == 1 and a["status"].get(i) == "OK") for i in ids}
        wt = {t: any(won[i] for i, tt in zip(ids, teams) if tt == t) for t in set(teams)}
        for i, t, d in zip(ids, teams, e["driver"]):
            rows.append(dict(event_id=ev_id, driver=d, team=t, grid=grid, kind="sprint_win",
                             prob=sim_prob(dict(kind="win", athlete=i), sim, ids, teams)[0], y=won[i]))
        for t in sorted(set(teams)):
            rows.append(dict(event_id=ev_id, driver="", team=t, grid=grid, kind="sprint_team_win",
                             prob=sim_prob(dict(kind="team_win", team=t), sim, ids, teams)[0], y=float(wt[t])))
        if echo:
            echo(f"sprint {ev_id} done")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Finishing-order odds for any session
# ---------------------------------------------------------------------------

SESSIONS = ("race", "sprint", "qual", "sprint_qual", "fp1", "fp2", "fp3")
FP_SIGMA_SCALE = 0.3        # practice order noise = qualifying noise x this; picked on 2025-26 FP1-3 pre-weekend backtests (in-sample), needs a decision-log entry


def session_sim(meas, hist, cutoff, event_id, session, n_sims=10000, rng=None, entrants=None, venue=None, year=None,
                fp_sigma_scale=None):
    """Simulated finishing order of one session of an event, from data before `cutoff`. Returns (sim, entrants)
    with sim = dict(pos (n_sims, drivers; 1 = first), dnf (False outside race and sprint)) in the entrants' row order.
    race / sprint: the finishing models. qual / sprint_qual: qualifying pace + qualifying noise. fp1-3: qualifying pace
    + FP_SIGMA_SCALE x qualifying noise (order of each driver's best lap)."""
    from racinglines.core.stats import ranks
    from racinglines.models.position_sim import model as M, pricing as PRC
    if session not in SESSIONS:
        raise ValueError(f"unknown session {session!r}: one of {SESSIONS}")
    rng = rng if rng is not None else np.random.default_rng(0)
    if session == "sprint":
        sim, e, _ = sprint_sim(meas, hist, cutoff, event_id, n_sims, rng, entrants, venue, year)
        return dict(pos=sim["pos"], dnf=sim["dnf"]), e
    summ, ex = PRC.price_race(meas, hist, cutoff, event_id, n_sims=n_sims if session == "race" else 200,
                              rng=rng if session == "race" else np.random.default_rng(0), entrants=entrants, venue=venue)
    e = ex["entrants"]
    if session == "race":
        return dict(pos=ex["sim"]["pos"], dnf=ex["sim"]["dnf"]), e
    fm = ex["model"]
    scale = 1.0 if session in ("qual", "sprint_qual") else (FP_SIGMA_SCALE if fp_sigma_scale is None else fp_sigma_scale)
    teams = e["team_key"].astype(str).to_numpy()
    q = e["qp"].to_numpy()[None, :] + M._noise(rng, fm.sigma_q * scale, fm.rho_q, teams, n_sims)
    return dict(pos=ranks(q).astype(float), dnf=np.zeros(q.shape, bool)), e


def rank_table(sim, entrants, tops=(1, 3, 5, 10)):
    """Per driver: P(finish in the top n) for each n in `tops`, P(exact rank) columns r1..rN and the mean rank."""
    pos, dnf = np.asarray(sim["pos"]), np.asarray(sim["dnf"]).astype(bool)
    n = pos.shape[1]
    t = pd.DataFrame(dict(athlete_id=entrants["athlete_id"].to_numpy(), driver=entrants["driver"].to_numpy(),
                          team_key=entrants["team_key"].to_numpy()))
    for k in tops:
        t[f"top{k}"] = ((pos <= k) & ~dnf).mean(0)
    for r in range(1, n + 1):
        t[f"r{r}"] = ((pos == r) & ~dnf).mean(0)
    t["mean_rank"] = pos.mean(0)
    return t.sort_values("top1", ascending=False).reset_index(drop=True)


def session_backtest(meas, hist, session, n_sims=1000, seed=0, start_year=2025, fp_sigma_scale=None, echo=None):
    """Price a session's order before the weekend's first session (no information from the weekend) and score
    P(win), P(top 3) and teammate head-to-heads against the real order. Rows: one per event x driver and per
    teammate pair."""
    from racinglines.models.position_sim import pricing as PRC
    rng = np.random.default_rng(seed)
    rows = []
    if session in ("qual", "race", "sprint"):
        src = meas.res[(meas.res["round"] == session) & (meas.res["year"] >= start_year)]
    else:
        src = meas.practice[meas.practice["round"] == session]
        src = src[src["event_id"].isin(meas.res.loc[meas.res["year"] >= start_year, "event_id"])]
    for ev_id in src.drop_duplicates("event_id")["event_id"]:
        s = meas.sessions(ev_id)
        first = [t for t in (s.get(k) for k in ("fp1", "fp2", "fp3", "sprint_qual", "qual", "race")) if t is not None and pd.notna(t)]
        if not first:
            continue
        cutoff = min(first) - PRC.ONE_MIN
        if not (hist["r_ts"] + PRC.M.RACE_DONE < cutoff).any():
            continue
        sim, e = session_sim(meas, hist, cutoff, ev_id, session, n_sims, rng, fp_sigma_scale=fp_sigma_scale)
        if session in ("qual", "race", "sprint"):
            a = src[src["event_id"] == ev_id].set_index("athlete_id")
            pos = a["position"].where(a["status"].eq("OK") | (session == "qual"))
        else:
            b = src[src["event_id"] == ev_id].groupby("athlete_id")["best_def"].min()
            pos = b.rank(method="first")
        ids = e["athlete_id"].tolist()
        if pos.dropna().empty:
            continue
        tab = rank_table(sim, e, tops=(1, 3))
        got = pos.reindex(ids)
        for i, r in tab.iterrows():
            y = got.get(r["athlete_id"])
            if pd.isna(y):
                continue
            rows.append(dict(event_id=ev_id, kind="win", prob=r["top1"], y=float(y == 1)))
            rows.append(dict(event_id=ev_id, kind="top3", prob=r["top3"], y=float(y <= 3)))
        teams = dict(zip(ids, e["team_key"]))
        for t in set(teams.values()):
            m2 = [i for i in ids if teams[i] == t and pd.notna(got.get(i))]
            if len(m2) == 2:
                a1, b1 = m2
                p, _ = sim_prob(dict(kind="h2h", a=a1, b=b1), sim, ids, [teams[i] for i in ids])
                rows.append(dict(event_id=ev_id, kind="teammate_h2h", prob=p, y=float(got[a1] < got[b1])))
        if echo:
            echo(f"{session} {ev_id} done")
    return pd.DataFrame(rows)


# Weight on the model (rest on the book's margin-free price) when sizing: lower where the backtests or the specials
# doc say the model is weak or biased. 0 = never staked. Judgment, untuned.
CONFIDENCE = dict(race_win=0.4, team_win=0.4, team_most_points=0.35, team_classified=0.35, driver_classified=0.3,
                  team_points=0.6, sprint_win=0.35, sprint_team_win=0.35, fp1_win=0.3, fp2_win=0.3, fp3_win=0.3,
                  qual_win=0.4, sprint_qual_win=0.35, first_retirement=0.0, first_team_retirement=0.0, safety_car=0.0)


def recommend(t, bankroll, cap_frac=0.06, min_edge=0.04, weights=None, max_odds=100.0):
    """Stake list from price_book output. The model probability is shrunk toward the book's margin-free price by the
    market's CONFIDENCE weight; a line needs a positive shrunk edge >= min_edge and odds under max_odds; stake =
    half-Kelly on the shrunk edge, capped at cap_frac of the bankroll per bet, then scaled so the total stays
    within `bankroll`."""
    w = {**CONFIDENCE, **(weights or {})}
    r = t.dropna(subset=["prob"]).copy()
    r["w"] = r["market"].map(w).fillna(0.0)
    r["p_adj"] = r["w"] * r["prob"] + (1 - r["w"]) * r["book_prob"]
    r["edge_adj"] = r["p_adj"] * r["odds"] - 1
    r = r[(r["w"] > 0) & (r["edge_adj"] >= min_edge) & (r["odds"] < max_odds) & ~r["suspect"]].copy()
    r["stake"] = (0.5 * r["edge_adj"] / (r["odds"] - 1) * bankroll).clip(upper=cap_frac * bankroll)
    tot = r["stake"].sum()
    if tot > bankroll:
        r["stake"] *= bankroll / tot
    r["stake"] = r["stake"].round(2)
    return r.sort_values("edge_adj", ascending=False)[["market", "subject", "odds", "prob", "book_prob", "p_adj",
                                                       "edge", "edge_adj", "stake"]].reset_index(drop=True)
