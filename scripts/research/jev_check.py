"""Jev gate run on profile A's race_win buys, analysed by the rules in reports/2026-10-14-jev-gate/PREREG.md.
Research only, off the live path.

    .venv/bin/python scripts/research/jev_check.py [--yes] [--profile NAME]

The TypeSafe key is read from TYPESAFE_API_KEY, else ~/.config/racinglines/typesafe.env (mode 600, outside the repo,
like gcs-hmac.env), else asked for with a hidden prompt and saved there. Answers are cached under data/runs/jev_gate/cache/, so a rerun costs nothing.
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reports" / "2026-10-14-jev-gate"
EXPLORATION_IDS = OUT / "exploration_ids.txt"
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="A · core taker (update)")
    ap.add_argument("--yes", action="store_true", help="skip the y/N before sending states")
    args = ap.parse_args()

    from racinglines.db.config import get_engine
    from racinglines.research import jev_gate as J

    e = get_engine()
    sigs, skipped = J.load_signals(e, profile=args.profile)
    states = [J.signal_state(s, e) for s in sigs]
    p = J.plan(sigs, states=states)
    print(f"{p['signals']} signals ({skipped} skipped, no settled outcome); "
          f"{p['api_calls']} API calls, {p['cached']} cached")
    if not sigs:
        sys.exit("no signals for that profile in this database")
    if p["api_calls"]:
        if not args.yes and input("Send these states to TypeSafe? [y/N] ").strip().lower() != "y":
            sys.exit("aborted, nothing sent")
        ensure_key()
        client = J.make_client()
    else:
        client = None

    rows = []
    for i, (s, st) in enumerate(zip(sigs, states), 1):
        try:
            a = J.ask(st, client=client)["answers"]
        except Exception as ex:  # stop at the first failure and show it
            sys.exit(f"stopped at {i}/{len(sigs)}: {type(ex).__name__}: {ex}")
        won = bool(s["outcome"]) == (s["side"] == "YES")
        rows.append(dict(id=s["id"], race_id=s["race_id"], event_key=s["event_key"], stage=s["stage"],
                         subject=s["subject"], side=s["side"], won=won,
                         pnl=s["shares"] * ((1.0 if won else 0.0) - s["limit_price"]),
                         mm=a["model_missing"]["noul"], se=a["stale_edge"]["noul"],
                         gc=a["gap_cause"]["choice"], gcc=a["gap_cause"]["confidence"]))

    from racinglines.research import jev_gate_stats as S
    ids = {int(x) for x in EXPLORATION_IDS.read_text().split()}
    text = S.format_report(S.analyse(rows, ids))
    print("\n" + text)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.txt").write_text(text + "\n")
    cols = ["id", "race_id", "event_key", "stage", "subject", "side", "won", "pnl", "mm", "se", "gc", "gcc"]
    (OUT / "results.csv").write_text("\n".join([",".join(cols)] + [
        ",".join(f'"{r[c]}"' if c == "subject" else str(r[c]) for c in cols) for r in rows]) + "\n")
    print(f"\nsaved {OUT.relative_to(ROOT)}/results.txt and results.csv")


if __name__ == "__main__":
    main()
