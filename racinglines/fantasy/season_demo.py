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
