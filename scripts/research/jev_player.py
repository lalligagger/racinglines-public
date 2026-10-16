"""Jev as a fantasy player in the 2026 season demo (reports/2026-10-15-jev-player/PREREG.md).

    .venv/bin/python scripts/research/jev_player.py plan --styles styles.json --players players.csv [--rounds 1-17]
    .venv/bin/python scripts/research/jev_player.py backtest --rounds 1-17 --styles styles.json --players players.csv \
        [--jev-user-id N] [--yes] [--dry-run]
    .venv/bin/python scripts/research/jev_player.py live --round 18 --lock --styles styles.json --players players.csv \
        --bankroll F$ [--jev-user-id N] [--yes] [--dry-run] [--now ISO]

No database access: styles.json is `python -m racinglines.fantasy.season_demo --export-styles` (run read-only on the VM),
players.csv the read-only players export (user ids, no handles). --dry-run answers with a deterministic stand-in (no
client, no key, no network) and writes under dry-run/ only. A real run asks y/N before sending anything (--yes skips)
and refuses a STAND-IN styles file. Answers are cached under data/runs/jev_player/cache.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from racinglines.research import jev_player as J

OUT = J.OUT_DIR
LOCKS = Path("paper/locks")
# The players export (read-only, on the VM: docker compose exec -T db psql -U racinglines -d racinglines_staging_demo
# -A -F, -c "<this>"), then profile_name -> code via profiles.PROFILES and sizing/kelly -> "standard" | "kelly <k>".
PLAYERS_SQL = (
    "SELECT p.user_id, p.event_key, mr.params->>'name' AS profile_name, "
    "coalesce(u.prefs->'strategy_profile'->>'sizing','standard') AS sizing, u.prefs->'strategy_profile'->>'kelly' AS kelly, "
    "u.prefs->'strategy_profile'->>'season_demo' AS season_demo, count(*) AS positions, "
    "count(*) FILTER (WHERE p.outcome IS NOT NULL) AS settled, round(coalesce(sum(p.cash + CASE WHEN p.outcome THEN "
    "p.yes_shares WHEN p.outcome = false THEN p.no_shares ELSE 0 END) FILTER (WHERE p.outcome IS NOT NULL),0)::numeric, 4) "
    "AS pnl FROM paper_positions p JOIN users u ON u.id = p.user_id LEFT JOIN model_runs mr ON mr.id = p.candidate_id "
    "WHERE p.event_key LIKE '2026-%' AND p.venue <> 'private' AND p.candidate_id IS NOT NULL "
    "AND u.prefs->'strategy_profile' ? 'season_demo' GROUP BY 1,2,3,4,5,6 ORDER BY 1,2")


def parse_rounds(s):
    out = []
    for part in str(s).split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:                                 # noqa: BLE001
        return "unknown"


def schedule(year):
    """The FastF1 schedule (WS.schedule), or {} when it cannot be read."""
    try:
        from racinglines.pipelines import weekend_sweep as WS
        return WS.schedule(year)
    except Exception as ex:                           # noqa: BLE001
        print(f"no schedule for {year}: {ex}", flush=True)
        return {}


def calendar(styles, sched):
    cal = J.calendar_from_styles(styles)
    for r, w in sched.items():
        cal[r] = dict(name=w["name"], format=w.get("format"), date=str(w["race_start"])[:10])
    return cal


def make_ask(args):
    if args.dry_run:
        return J.stand_in_ask
    holder = {}

    def _ask(state):
        hit = J.cached_answer(state, args.model)
        if hit is not None:
            return hit
        if "client" not in holder:
            holder["client"] = J.make_client()
        return J.ask(state, client=holder["client"], model=args.model)
    return _ask


def confirm(args, n):
    if args.dry_run or args.yes:
        return True
    return input(f"send {n} request(s) to TypeSafe ({args.model})? [y/N] ").strip().lower() == "y"


def sources(out_dir, args, meta, extra=()):
    L = ["# SOURCES", "", f"- commit: {commit()}", f"- command: {' '.join(sys.argv)}",
         f"- styles: {args.styles} (meta: {json.dumps(meta, default=str)[:600]})", f"- players: {args.players} (read-only export; SQL: {PLAYERS_SQL})",
         f"- model: {args.model}; cache: {J.CACHE_DIR}", f"- decider: {'STAND-IN (dry run, no client)' if args.dry_run else 'TypeSafe System One'}",
         "", "## Interpretations", "", J.__doc__.split("Interpretations of the PREREG", 1)[1].strip(), "", *extra]
    (out_dir / "SOURCES.md").write_text("\n".join(L) + "\n")


def load(args):
    styles, meta = J.load_styles(args.styles)
    if meta.get("STAND_IN") and not args.dry_run and args.cmd != "plan":
        sys.exit("refusing: the styles file is a STAND-IN (dry runs only); export the real series on the VM first")
    players = J.load_players(args.players)
    return styles, meta, players


def cmd_plan(args):
    styles, meta, players = load(args)
    rounds = parse_rounds(args.rounds)
    cal = calendar(styles, {})
    excl = (args.jev_user_id,) if args.jev_user_id else ()
    p = J.plan(styles, players, cal, rounds, model=args.model, exclude_users=excl)
    print(json.dumps(p, indent=1))
    if meta.get("STAND_IN"):
        print("styles file is a STAND-IN: these counts are for the pipeline check only")
    return 0


def cmd_backtest(args):
    styles, meta, players = load(args)
    rounds = parse_rounds(args.rounds)
    cal = calendar(styles, {})
    excl = (args.jev_user_id,) if args.jev_user_id else ()
    out_dir = OUT / "dry-run" if args.dry_run else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    if not confirm(args, len(rounds)):
        print("nothing sent")
        return 1
    t0 = time.time()
    picks, transcript = J.run(styles, players, cal, rounds, make_ask(args), exclude_users=excl)
    res = J.analyse(styles, picks, rounds, players, args.jev_user_id, transcript)
    label = "  [DRY RUN: STAND-IN decider" + (", STAND-IN styles" if meta.get("STAND_IN") else "") + "]" \
        if args.dry_run else ""
    text = J.format_report(res, label)
    pmeta = dict(run="backtest", rounds=rounds, model=args.model, dry_run=args.dry_run, stand_in_styles=bool(meta.get("STAND_IN")),
                 commit=commit(), elapsed_sec=round(time.time() - t0, 1))
    (out_dir / "picks.json").write_text(json.dumps(J.picks_file(picks, pmeta), indent=1))
    (out_dir / "results.txt").write_text(text + "\n")
    with open(out_dir / "transcript.jsonl", "w") as fh:
        for t in transcript:
            fh.write(json.dumps(t, default=str) + "\n")
    sources(out_dir, args, meta)
    print(text)
    print(f"\nsaved {out_dir}/picks.json, results.txt, transcript.jsonl, SOURCES.md")
    return 0


def cmd_live(args):
    import pandas as pd

    from racinglines.pipelines import profiles as PF
    from racinglines.pipelines import sweep_settings as SS
    if args.now and not args.dry_run:
        print("`--now` is for --dry-run only: the deadline check uses the real clock", file=sys.stderr)
        sys.exit(2)
    if not args.lock:
        sys.exit("live needs --lock (it writes the round's lock file)")
    styles, meta, players = load(args)
    sched = schedule(J.YEAR)
    w = sched.get(args.round)
    if w is None:
        sys.exit(f"round {args.round}: not in the {J.YEAR} schedule")
    fp1 = w["sessions"][0][1]
    now = pd.Timestamp(args.now) if args.now else pd.Timestamp.now(tz="UTC").tz_localize(None)
    try:
        J.check_deadline(now, w["race_start"], fp1)
    except ValueError as e:
        sys.exit(str(e))
    out_dir = OUT / "dry-run" if args.dry_run else OUT
    lock_dir = out_dir / "locks" if args.dry_run else LOCKS
    lock_path = lock_dir / f"{J.YEAR}-{args.round}.toml"
    if lock_path.exists():
        sys.exit(f"{lock_path} exists: a lock is never rewritten (append a [[correction]] by hand)")
    cal = calendar(styles, sched)
    excl = (args.jev_user_id,) if args.jev_user_id else ()
    if not confirm(args, 1):
        print("nothing sent")
        return 1
    picks, transcript = J.run(styles, players, cal, [args.round], make_ask(args), exclude_users=excl, live=True)
    p = picks[args.round]
    key = SS.Settings.from_dict(PF.PROFILES[p["code"]]["settings"]).key
    rule = "standard (bankroll-scaled linear rule, fantasy/sizing.py)" if p["kelly"] is None else \
        f"kelly {p['kelly']:g} (fantasy/sizing.py)"
    text = J.lock_text((LOCKS / "TEMPLATE.toml").read_text(), year=J.YEAR, rnd=args.round, name=w["name"],
                       first_session_utc=f"{pd.Timestamp(fp1):%Y-%m-%dT%H:%M:%SZ}", code=p["code"], settings_key=key,
                       code_commit=commit(), bankroll=args.bankroll, stake_rule=rule, note_text=p["note"],
                       locked_at_utc=J.utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(text)
    out_dir.mkdir(parents=True, exist_ok=True)
    live = out_dir / f"live-{args.round}"
    live.mkdir(exist_ok=True)
    (live / "picks.json").write_text(json.dumps(J.picks_file(picks, dict(run="live", round=args.round, model=args.model,
                                                                            dry_run=args.dry_run, commit=commit())), indent=1))
    with open(live / "transcript.jsonl", "w") as fh:
        for t in transcript:
            fh.write(json.dumps(t, default=str) + "\n")
    sources(live, args, meta, [f"- lock file: {lock_path}"])
    print(text)
    print(f"wrote {lock_path}; commit and push it to the paper-locks branch before FP1 ({fp1} UTC)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "backtest", "live"):
        s = sub.add_parser(name)
        s.add_argument("--styles", required=True)
        s.add_argument("--players", required=True)
        s.add_argument("--model", default=J.DEFAULT_MODEL)
        s.add_argument("--jev-user-id", type=int, default=None, help="Jev's demo account: kept out of the evidence, ranked")
        if name in ("plan", "backtest"):
            s.add_argument("--rounds", default="1-17")
        if name != "plan":
            s.add_argument("--yes", action="store_true", help="skip the y/N before sending")
            s.add_argument("--dry-run", action="store_true", help="stand-in decider: no client, no key, no network")
        if name == "live":
            s.add_argument("--round", type=int, required=True)
            s.add_argument("--lock", action="store_true")
            s.add_argument("--bankroll", type=float, required=True, help="the jev account's F$ (read on the VM)")
            s.add_argument("--now", default=None, help="naive UTC time for the deadline check (tests, dry runs)")
    args = ap.parse_args(argv)
    if args.cmd == "plan":
        args.dry_run = False
    return {"plan": cmd_plan, "backtest": cmd_backtest, "live": cmd_live}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
