"""
The alpha's season demo (owner, 2026-10-13 06:36Z): "all users have picked up some random strategy and traded at
various participation rates up to now in the F1 2026 season ... on staging for alpha validation and probalytics
demo/discussion, using its own demo db (not regular staging db)"; 06:37Z: "this db should persist beyond this test and
be usable with a switch on deploy to staging" (scripts/vm/season_demo.sh builds it, `vm.sh staging db demo` points
staging at it).

Every fantasy player in the database (an active account with a grant, not a demo or system account,
sizing.excluded_users) draws, from a seed:

- a style: one of the alpha's five (profiles.ALPHA_ORDER), each equally likely;
- a weekend share (PLAY): the chance it takes part in each raced weekend of the season;
- a follow rate (FOLLOW): the share of its style's picks it takes in a weekend it plays (signals.apply_follow, the
  demo taker's mechanism);
- a sizing (SIZINGS): standard, or half or quarter Kelly (profiles.SIZINGS).

Then each raced weekend is replayed once per style exactly as the demo accounts' track record is
(pipelines/demo_history.py: signals.compute with live=False a day after the race, real tapes, our as-of pricing),
and each player who plays it gets their own copy sized to their F$ at that point (signals.for_player, weekends in
order, so a busted player stops) stored as backfilled paper rows (signals.store history=True). The draw is
deterministic: the same seed, players and weekends give the same demo.

Writes only to a database whose name contains "demo" (is_demo_db): never staging's or production's own. Without apply
it only prints the draw. Each player's 2026 F1 strategy rows (strategy_signals, paper_positions) are replaced, their
hand trades are kept, and their profile is set to the drawn style (with its follow rate and sizing), so the History
and strategy pages show it.
"""

import hashlib
import random

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import make_url

from racinglines import progress as PG
from racinglines.fantasy import sizing as FS
from racinglines.pipelines import profiles as PF

PLAY = (0.3, 1.0)                  # share of raced weekends a player takes part in, uniform
FOLLOW = (0.15, 1.0)               # share of a played weekend's picks it takes, uniform
SIZINGS = (None, None, 0.5, 0.25)  # Kelly fraction: standard (None) twice as likely as half or quarter Kelly
SETTLED = pd.Timedelta(days=1)     # each weekend replayed a day after its race (demo_history.SETTLED)


def is_demo_db(url):
    """True for a database whose name contains "demo" (racinglines_staging_demo): the only kind this module writes."""
    try:
        return "demo" in (make_url(str(url)).database or "")
    except Exception:                                  # noqa: BLE001 — anything unparseable is not a demo database
        return False


def players(conn):
    """[(user_id, username)] of every fantasy player: active, with a grant, not a demo or system account."""
    if not conn.execute(text("SELECT to_regclass('accounts.fantasy_ledger') IS NOT NULL")).scalar():
        return []
    rows = conn.execute(text("""SELECT u.id, u.username FROM users u WHERE u.active AND EXISTS (
                                  SELECT 1 FROM accounts.fantasy_ledger l WHERE l.user_id = u.id AND l.ref_table IS NULL)
                                ORDER BY u.id""")).all()
    out = set(FS.excluded_users())
    return [(i, n) for i, n in rows if n not in out]


def _u(seed, *key):
    """A uniform number in [0, 1), deterministic per (seed, key)."""
    return int(hashlib.sha1(":".join(map(str, (seed, *key))).encode()).hexdigest()[:8], 16) / 2 ** 32


def draw(users, rounds, seed=2026, styles=PF.ALPHA_ORDER):
    """Each player's demo: {user_id: dict(username, style, play, follow_rate, kelly, rounds=[played rounds])}."""
    out = {}
    for uid, name in users:
        rng = random.Random(f"{seed}:{uid}")
        play = round(rng.uniform(*PLAY), 2)
        out[uid] = dict(username=name, style=rng.choice(styles), play=play,
                        follow_rate=round(rng.uniform(*FOLLOW), 2), kelly=rng.choice(SIZINGS),
                        rounds=[r for r in rounds if _u(seed, uid, r) < play])
    return out


def raced(sched, now):
    """The rounds of a schedule (weekend_sweep.schedule) settled by `now`, in order."""
    return [r for r in sorted(sched) if sched[r]["race_start"] + SETTLED <= now]


def reset(conn, user_ids, event_keys):
    """Delete these players' strategy rows for these weekends (every venue but the private maker's). -> (signals,
    positions) deleted."""
    a = conn.execute(text("DELETE FROM strategy_signals WHERE user_id = ANY(:u) AND event_key = ANY(:e)"),
                     dict(u=list(user_ids), e=list(event_keys))).rowcount
    b = conn.execute(text("""DELETE FROM paper_positions WHERE user_id = ANY(:u) AND event_key = ANY(:e)
                             AND venue <> 'private'"""), dict(u=list(user_ids), e=list(event_keys))).rowcount
    return a, b


def build(engine, engine_url, seed=2026, year=2026, now=None, apply=False, echo=print):
    """Draw every player's demo and, with apply, replay it into the database. -> (plan, report) with report
    [(username, style, event_key, signals, P&L)]."""
    from racinglines.pipelines import signals as SG
    from racinglines.pipelines import weekend_sweep as WS
    if apply and not is_demo_db(engine.url):
        raise ValueError(f"refusing to write the season demo to {engine.url.database!r}: only a database whose name "
                         "contains 'demo' (racinglines_staging_demo)")
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    sched = WS.schedule(year)
    rounds = raced(sched, now)
    with engine.connect() as c:
        plan = draw(players(c), rounds, seed=seed)
    for uid, p in plan.items():
        size = "standard" if p["kelly"] is None else f"{p['kelly']:g} Kelly"
        echo(f"{p['username']:<24} {p['style']:3s} {PF.ALPHA_STYLES[p['style']]['label']:<17} "
             f"weekends {len(p['rounds']):2d}/{len(rounds)} (share {p['play']:.2f})  follows {p['follow_rate']:.0%}  "
             f"{size}")
    if not apply:
        echo(f"dry run: {len(plan)} players, {len(rounds)} raced {year} weekends, seed {seed} (apply writes)")
        return plan, []
    with engine.begin() as c:
        ids = PF.ensure_candidates(c)
        profs = {code: PF.load(c, ids[code]) for code in sorted({p["style"] for p in plan.values()})}
        a, b = reset(c, list(plan), [sched[r]["event_key"] for r in sched])
        echo(f"cleared the players' {year} strategy rows: {a} signals, {b} positions")
        for uid, p in plan.items():
            kelly = {} if p["kelly"] is None else dict(sizing="kelly", kelly=p["kelly"])
            PF.assign(c, uid, dict(profs[p["style"]], follow_rate=p["follow_rate"], season_demo=seed,
                                   **({"sizing": "standard"} if not kelly else kelly)))
    cache, report = {}, []
    for rnd in PG.track(rounds, "weekend", name=lambda r: sched[r]["name"]):
        w = sched[rnd]
        for code, prof in profs.items():
            uids = [u for u, p in plan.items() if p["style"] == code and rnd in p["rounds"]]
            if not uids:
                continue
            outs = SG.compute_all(engine, engine_url, prof, now=w["race_start"] + SETTLED, event=f"{year}-{rnd}",
                                  live=False, fetch=False, echo=lambda m: None, cache=cache)
            outs = [o for o in outs if o["stages"]]
            if not outs:
                echo(f"{w['event_key']} {w['name']} {code}: no markets")
                continue
            for uid in uids:
                with engine.begin() as c:
                    for o in outs:
                        SG.store(c, uid, SG.for_player(c, uid, o, kelly=plan[uid]["kelly"]),
                                 follow_rate=plan[uid]["follow_rate"], history=True)
                    n = c.execute(text("""SELECT count(*) FROM strategy_signals WHERE user_id = :u AND event_key = :e
                                          AND detail->>'followed' = 'true'"""), dict(u=uid, e=w["event_key"])).scalar()
                    pnl = c.execute(text("""SELECT coalesce(sum(cash + yes_shares * outcome::int
                                                                + no_shares * (1 - outcome::int)), 0)
                                            FROM paper_positions WHERE user_id = :u AND event_key = :e
                                            AND outcome IS NOT NULL AND venue <> 'private'"""),
                                    dict(u=uid, e=w["event_key"])).scalar()
                report.append((plan[uid]["username"], code, w["event_key"], int(n), float(pnl)))
            echo(f"{w['event_key']} {w['name']:28s} {code:3s} {len(uids):3d} players")
    return plan, report


# ---------------------------------------------------------------------------
# Jev as a player (reports/2026-10-15-jev-player/PREREG.md): the per-style series export (read-only) and one player's
# strategy rows from a picks file. Neither changes build() above.
# ---------------------------------------------------------------------------

READ_ONLY = {"options": "-c default_transaction_read_only=on"}


def read_only(url):
    """(engine, url string) on the same database with every transaction read-only: any write the replay would make
    (a stage not priced yet, a missing candidate) fails instead of happening."""
    from sqlalchemy import create_engine
    u = make_url(str(url)).update_query_dict(READ_ONLY)
    s = u.render_as_string(hide_password=False)
    return create_engine(s, future=True), s


def outcome_pnl(positions):
    """Settled P&L of a replay's positions: cash + yes_shares if the outcome is true, + no_shares if false."""
    return float(sum(p["cash"] + (p["yes_shares"] if p["outcome"] else p["no_shares"])
                     for p in positions if p.get("outcome") is not None))


def export_styles(engine_url, year=2026, now=None, styles=PF.ALPHA_ORDER, echo=print):
    """The canonical per-style weekend P&L of the season so far: each raced weekend replayed once per style exactly as
    build() does (signals.compute_all, live=False, a day after the race), at the profile's default sizing (no player
    copy, no follow rate). Read-only: a demo database only, through read_only(). -> {"meta", "styles": {code:
    {round: dict(pnl, bought, positions, settled, signals, event_key, name, format, race_start)}}}"""
    from racinglines.pipelines import signals as SG
    from racinglines.pipelines import weekend_sweep as WS
    if not is_demo_db(engine_url):
        raise ValueError(f"refusing to export from {make_url(str(engine_url)).database!r}: a demo database only")
    engine, url = read_only(engine_url)
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    sched = WS.schedule(year)
    rounds = raced(sched, now)
    with engine.connect() as c:
        profs = {code: PF.load(c, code) for code in styles}
    cache, out = {}, {code: {} for code in styles}
    for rnd in PG.track(rounds, "weekend", name=lambda r: sched[r]["name"]):
        w = sched[rnd]
        for code, prof in profs.items():
            outs = SG.compute_all(engine, url, prof, now=w["race_start"] + SETTLED, event=f"{year}-{rnd}",
                                  live=False, fetch=False, echo=lambda m: None, cache=cache)
            outs = [o for o in outs if o["stages"]]
            pos = [p for o in outs for p in o["positions"]]
            out[code][rnd] = dict(pnl=outcome_pnl(pos), bought=float(sum(max(-p["cash"], 0.0) for p in pos)),
                                  positions=len(pos), settled=sum(p.get("outcome") is not None for p in pos),
                                  signals=sum(len(o["signals"]) for o in outs), event_key=w["event_key"],
                                  name=w["name"], format=w.get("format"), race_start=str(w["race_start"]),
                                  markets=bool(outs))
            echo(f"{w['event_key']} {w['name']:28s} {code:3s} P&L {out[code][rnd]['pnl']:+9.2f}")
    meta = dict(year=year, now=str(now), rounds=rounds, database=make_url(str(engine_url)).database,
                sizing="each profile's default stake rule (no player copy, no follow rate)",
                profiles={code: dict(name=p["name"], candidate_id=p.get("candidate_id"), strategy=p["strategy"])
                          for code, p in profs.items()})
    return dict(meta=meta, styles=out)


def picks_plan(picks, rounds):
    """{round: (code, kelly)} for the raced rounds a picks file names (picks: {"rounds": {"1": {"code", "sizing",
    "kelly"}}}, as reports/2026-10-15-jev-player/picks.json). Raises ValueError for a code outside ALPHA_ORDER or a
    sizing that is neither standard nor a Kelly fraction in range."""
    rows = picks.get("rounds", picks)
    out = {}
    for rnd in rounds:
        p = rows.get(str(rnd), rows.get(rnd))
        if p is None:
            continue
        if p.get("code") not in PF.ALPHA_ORDER:
            raise ValueError(f"round {rnd}: style {p.get('code')!r} is not one of {PF.ALPHA_ORDER}")
        try:
            k = PF.kelly_value(p.get("sizing"), p.get("kelly"))
        except (ValueError, TypeError) as e:
            raise ValueError(f"round {rnd}: sizing {p.get('sizing')!r} kelly {p.get('kelly')!r}: {e}") from e
        if p.get("sizing", "standard") != "standard" and k is None:
            raise ValueError(f"round {rnd}: sizing {p.get('sizing')!r} kelly {p.get('kelly')!r}")
        out[rnd] = (p["code"], k)
    return out


def apply_picks(engine, engine_url, username, picks, year=2026, now=None, apply=False, marker="jev", echo=print):
    """One existing player's 2026 strategy rows from a picks file: each raced weekend replayed with the style named for
    that round, sized to the player's F$ (signals.for_player with the round's Kelly fraction), stored as backfilled rows
    as build() stores them (every pick followed), and the profile set to the latest pick. A demo database only; without
    apply it only prints the plan. -> (plan {round: (code, kelly)}, report [(username, code, event_key, signals, P&L)])"""
    from racinglines.pipelines import signals as SG
    from racinglines.pipelines import weekend_sweep as WS
    if apply and not is_demo_db(engine.url):
        raise ValueError(f"refusing to write picks to {engine.url.database!r}: only a database whose name contains "
                         "'demo' (racinglines_staging_demo)")
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
    sched = WS.schedule(year)
    plan = picks_plan(picks, raced(sched, now))
    with engine.connect() as c:
        uid = c.execute(text("SELECT id FROM users WHERE username = :u AND active"), dict(u=username)).scalar()
    if uid is None:
        raise ValueError(f"no active player {username!r}")
    for rnd, (code, k) in plan.items():
        echo(f"{sched[rnd]['event_key']} {sched[rnd]['name']:28s} {code:3s} "
             f"{'standard' if k is None else f'{k:g} Kelly'}")
    if not apply:
        echo(f"dry run: player #{uid}, {len(plan)} weekends from the picks file (apply writes)")
        return plan, []
    if not plan:
        return plan, []
    with engine.begin() as c:
        ids = PF.ensure_candidates(c)
        profs = {code: PF.load(c, ids[code]) for code in sorted({code for code, _ in plan.values()})}
        a, b = reset(c, [uid], [sched[r]["event_key"] for r in sched])
        echo(f"cleared player #{uid}'s {year} strategy rows: {a} signals, {b} positions")
        code, k = plan[max(plan)]
        PF.assign(c, uid, dict(profs[code], season_demo=marker,
                               **({"sizing": "standard"} if k is None else dict(sizing="kelly", kelly=k))))
    cache, report = {}, []
    for rnd in PG.track(sorted(plan), "weekend", name=lambda r: sched[r]["name"]):
        w, (code, k) = sched[rnd], plan[rnd]
        outs = SG.compute_all(engine, engine_url, profs[code], now=w["race_start"] + SETTLED, event=f"{year}-{rnd}",
                              live=False, fetch=False, echo=lambda m: None, cache=cache)
        outs = [o for o in outs if o["stages"]]
        if not outs:
            echo(f"{w['event_key']} {w['name']} {code}: no markets")
            continue
        with engine.begin() as c:
            for o in outs:
                SG.store(c, uid, SG.for_player(c, uid, o, kelly=k), follow_rate=None, history=True)
            n = c.execute(text("""SELECT count(*) FROM strategy_signals WHERE user_id = :u AND event_key = :e
                                  AND detail->>'followed' = 'true'"""), dict(u=uid, e=w["event_key"])).scalar()
            pnl = c.execute(text("""SELECT coalesce(sum(cash + yes_shares * outcome::int
                                                        + no_shares * (1 - outcome::int)), 0)
                                    FROM paper_positions WHERE user_id = :u AND event_key = :e
                                    AND outcome IS NOT NULL AND venue <> 'private'"""),
                            dict(u=uid, e=w["event_key"])).scalar()
        report.append((username, code, w["event_key"], int(n), float(pnl)))
        echo(f"{w['event_key']} {w['name']:28s} {code:3s} {int(n):3d} picks taken  P&L F${float(pnl):+,.2f}")
    return plan, report


def main(argv=None):
    """python -m racinglines.fantasy.season_demo --export-styles styles.json [--year 2026]
       python -m racinglines.fantasy.season_demo --picks picks.json --user HANDLE [--apply]
    DATABASE_URL names the database (a demo database only)."""
    import argparse
    import json

    from racinglines.db.config import database_url, get_engine
    ap = argparse.ArgumentParser(description="season demo: Jev's per-style export and picks")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--export-styles", metavar="PATH", help="write the per-style weekend P&L (read-only)")
    g.add_argument("--picks", metavar="PATH", help="a picks file (reports/2026-10-15-jev-player/picks.json)")
    ap.add_argument("--user", help="the player the picks are for (with --picks)")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--apply", action="store_true", help="write (with --picks); without it only the plan is printed")
    a = ap.parse_args(argv)
    out = lambda m: print(m, flush=True)          # noqa: E731
    PG.start("season_demo " + ("export-styles" if a.export_styles else "picks"))   # a progress line every 5 minutes
    try:
        if a.export_styles:
            res = export_styles(database_url(), year=a.year, echo=out)
            with open(a.export_styles, "w") as fh:
                json.dump(res, fh, indent=1, default=str)
            out(f"wrote {a.export_styles}: {len(res['meta']['rounds'])} weekends x {len(res['styles'])} styles")
            return 0
        if not a.user:
            ap.error("--picks needs --user")
        with open(a.picks) as fh:
            picks = json.load(fh)
        _, rep = apply_picks(get_engine(), database_url(), a.user, picks, year=a.year, apply=a.apply, echo=out)
        if rep:
            out(f"{a.user}: {len(rep)} weekends, paper P&L F${sum(r[4] for r in rep):+,.2f}")
        return 0
    except ValueError as e:
        out(str(e))
        return 1
    finally:
        PG.stop()


if __name__ == "__main__":
    raise SystemExit(main())
