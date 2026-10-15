"""Jev desk trader: 20-lot allocation per 2026 weekend, by reports/2026-10-14-jev-desk/PREREG.md (v2).
Research only, off the live path. Reads model_runs and events (SELECT only); the sweeps come from a scratch database.

    .venv/bin/python scripts/research/jev_trader.py --db URL [--bankroll 10000] [--weeks N] [--lots 20] [--dry-run] [--yes]

The TypeSafe key is read from TYPESAFE_API_KEY, else ~/.config/racinglines/typesafe.env (mode 600), else asked for
with a hidden prompt and saved there. Answers are cached under data/runs/jev_trader/cache/, so a rerun costs nothing.
Weeks run strictly in order, lots sequentially: the bankroll in each state is the rolling bankroll, so nothing runs in
parallel. Stops at the first API failure.
"""
import argparse
import csv
import getpass
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "2026-10-14-jev-desk"
KEY_FILE = Path.home() / ".config" / "racinglines" / "typesafe.env"


def ensure_key():
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    if KEY_FILE.exists():
        for line in KEY_FILE.read_text().splitlines():
            if line.startswith("TYPESAFE_API_KEY="):
                os.environ["TYPESAFE_API_KEY"] = line.split("=", 1)[1].strip().strip("\"'")
                print(f"key: read from {KEY_FILE}")
                return
        sys.exit(f"{KEY_FILE} has no TYPESAFE_API_KEY= line")
    if not sys.stdin.isatty():
        sys.exit("No TYPESAFE_API_KEY and no terminal to ask on: run this in a terminal, or export the key.")
    key = getpass.getpass(f"TypeSafe API key (hidden, saved to {KEY_FILE}): ").strip()
    if not key:
        sys.exit("no key given")
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"TYPESAFE_API_KEY={key}\n")
    os.environ["TYPESAFE_API_KEY"] = key
    print(f"key: saved to {KEY_FILE} (mode 600)")


class Heartbeat:
    """Progress line to stderr at least every `every` seconds while a run is in flight."""

    def __init__(self, every=30.0):
        self.every, self.t0, self.pos, self._stop = every, time.time(), "starting", threading.Event()
        self._th = threading.Thread(target=self._loop, daemon=True)

    def set(self, week, weeks, lot, lots):
        self.pos = f"week {week} of {weeks} · lot {lot} of {lots}"

    def line(self):
        return f"progress jev-trader: {self.pos} · {time.time() - self.t0:.0f} s elapsed"

    def _loop(self):
        while not self._stop.wait(self.every):
            print(self.line(), file=sys.stderr, flush=True)

    def __enter__(self):
        print(self.line(), file=sys.stderr, flush=True)
        self._th.start()
        return self

    def __exit__(self, *a):
        self._stop.set()


def plan(u, rounds, bankroll, lots, model, cache_dir):
    """No network. Leak-checks the first state of every week, replays the cache for the exact count still to make."""
    from racinglines.research import jev_trader as T
    for r in rounds:
        v = u.view(r)
        T.guard(T.lot_state(v, bankroll, {}), u.canaries(r))
    inner, cached, b = T.cache_only_ask(model, cache_dir), [0], float(bankroll)

    def ask(state, options):
        a = inner(state, options)
        cached[0] += 1
        return a
    try:
        for r in rounds:
            table, _ = T.allocate_week(u.view(r), u.canaries(r), b, ask, lots)
            b = T.account(u, {r: table}, [r], b)["path"][-1]
    except T.MissingCache:
        pass
    cached = cached[0]
    total = len(rounds) * lots
    return {"weeks": len(rounds), "requests": total, "cached": cached, "to_make": total - cached}


def run_trader(u, *, bankroll=10000.0, weeks=None, lots=20, model="jev-latest", yes=False, dry_run=False,
               out_dir=OUT, cache_dir=None, client_factory=None, confirm=input, argv=None, db_note="", out=print, subset="all", sizing="all"):
    from racinglines.research import jev_trader as T
    cache_dir = cache_dir or T.CACHE_DIR
    rounds = list(u.rounds(2026))
    if weeks:
        rounds = rounds[:weeks]
    if not rounds:
        raise SystemExit("no 2026 rounds in this universe")
    out(f"universe: {json.dumps(u.meta(), default=str)}")
    p = plan(u, rounds, bankroll, lots, model, cache_dir)
    out(f"{p['weeks']} weeks x {lots} lots = {p['requests']} requests; {p['cached']} cached "
        f"(replayed from the start), {p['to_make']} to make; leak guard passed on every week's first state")
    if dry_run:
        return None
    client = None
    if p["to_make"]:
        if not yes and confirm("Send these states to TypeSafe? [y/N] ").strip().lower() != "y":
            raise SystemExit("aborted, nothing sent")
        if client_factory:
            client = client_factory()
        else:
            ensure_key()
            client = T.make_client()

    t0 = time.time()
    tables, transcript, b = {}, [], float(bankroll)
    with Heartbeat() as hb:
        for wi, r in enumerate(rounds, 1):
            v = u.view(r)
            n = [0]

            def ask(state, options, wi=wi):
                n[0] += 1
                hb.set(wi, len(rounds), n[0], lots)
                try:
                    return T.ask_choice(state, options, client=client, model=model, cache_dir=cache_dir)
                except Exception as ex:
                    raise SystemExit(f"stopped at week {wi}/{len(rounds)} lot {n[0]}/{lots}: "
                                     f"{type(ex).__name__}: {ex}")

            table, tr = T.allocate_week(v, u.canaries(r), b, ask, lots)
            tables[r] = table
            transcript += tr
            b = T.account(u, {r: table}, [r], b)["path"][-1]
    res = T.analyse(u, rounds, tables, bankroll, transcript, elapsed=time.time() - t0)
    text = T.format_report(res)
    out("\n" + text)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.txt").write_text(text + "\n")
    cols = ["week", "sid", "lots", "pct", "dollars", "ret", "pnl"]
    with open(out_dir / "weeks.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(T.weeks_rows(res))
    (out_dir / "transcript.jsonl").write_text("".join(json.dumps(t, sort_keys=True, default=str) + "\n"
                                                      for t in transcript))
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = "unknown"
    t = res["totals"]
    (out_dir / "SOURCES.md").write_text("\n".join([
        "# Sources: Jev desk trader", "", f"- commit: {commit} (the working tree may hold uncommitted research files)",
        f"- command: {' '.join(argv or sys.argv)}", f"- bankroll: {bankroll}", f"- model: {model}", f"- lots per week: {lots}",
        f"- weeks: {rounds[0]}..{rounds[-1]} ({len(rounds)})", f"- database: {db_note}",
        f"- subset: {subset}", f"- sizing: {sizing}",
        f"- universe: `{json.dumps(u.meta(), default=str)}`",
        f"- tokens: input {t['input_tokens']}, output {t['output_tokens']}; requests {t['requests']} "
        f"(API {t['api_calls']}, cached {t['cached']}); {t['elapsed_sec']:.0f} s", "",
        "Interpretations: see the docstring of racinglines/research/jev_trader.py.", ""]))
    out(f"\ntokens: input {t['input_tokens']:,} output {t['output_tokens']:,}")
    out(f"saved {out_dir}/results.txt, weeks.csv, transcript.jsonl, SOURCES.md")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=None, help="database URL (default DATABASE_URL / repo default)")
    ap.add_argument("--bankroll", type=float, default=10000.0)
    ap.add_argument("--weeks", type=int, default=None, help="only the first N rounds (cheap trial)")
    ap.add_argument("--model", default="jev-latest")
    ap.add_argument("--lots", type=int, default=20)
    ap.add_argument("--sizing", choices=("all", "flat"), default="all",
                    help="flat drops the Kelly strategies (robustness run; their stored P&L assumes unlimited depth at the touch)")
    ap.add_argument("--subset", choices=("all", "untuned"), default="all",
                    help="untuned keeps only the plain default-settings variant sweeps (params label == variant); "
                         "outputs go to a sibling reports folder")
    ap.add_argument("--yes", action="store_true", help="skip the y/N before sending states")
    ap.add_argument("--dry-run", action="store_true", help="universe, leak check and request counts only; no key, no network")
    args = ap.parse_args(argv)

    from racinglines.db.config import get_engine
    from racinglines.research import jev_desk as D
    from racinglines.research.jev_universe import Universe, load_events

    e = get_engine(args.db)
    runs = D.load_runs(e)
    u = Universe.from_runs(runs, load_events(e), sizing=args.sizing, subset=args.subset)
    out_dir = OUT
    if args.subset != "all" or args.sizing != "all":
        out_dir = OUT.parent / (OUT.name + (f"-{args.subset}" if args.subset != "all" else "")
                                + ("-flat" if args.sizing == "flat" else ""))
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"outputs: {out_dir}")
    run_trader(u, out_dir=out_dir, subset=args.subset, sizing=args.sizing, bankroll=args.bankroll, weeks=args.weeks, lots=args.lots, model=args.model, yes=args.yes,
               dry_run=args.dry_run, argv=sys.argv, db_note=f"{len(runs)} sweep runs read (url not recorded)")


if __name__ == "__main__":
    main()
