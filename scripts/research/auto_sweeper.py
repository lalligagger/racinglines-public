#!/usr/bin/env python3
"""LOCAL (Mac): finite-pool Jev sweep research; dry-run and zero budgets by default.

Pool JSON is a list of settings dictionaries; no candidate generation or sampling.
Example (pure planning):
  .venv/bin/python scripts/research/auto_sweeper.py pool.json
Execution additionally requires --execute --budget N --jev-budget N --backup PATH.
Resume with the identical pool/flags/journal; budgets persist when omitted. To
raise a budget, pass its new total with --increase-budget. Failures require
--retry-failed; retries spend another attempt. Never reset a journal to evade a
budget. All confirmation runs and missing baselines count. Back up the local DB
before execution; rollback is the operator's separate restore of that backup.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from racinglines.research.auto_sweeper import Config, DEFAULT_MODEL, run


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pool", type=Path, help="JSON list, at most 254 full settings (same sims, default venue)")
    p.add_argument("--journal", type=Path, default=Path("data/runs/auto-sweeper/state.json"))
    p.add_argument("--strategy", default="update", help="existing search-report strategy key")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--confirm-sims", type=int, default=16000)
    p.add_argument("--stop-after", type=int, default=0)
    p.add_argument("--margin", type=float, default=0.0)
    p.add_argument("--budget", type=int, default=None, help="total sweep attempts; initially zero")
    p.add_argument("--jev-budget", type=int, default=None, help="total chooser calls; initially zero")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="opt in to real local DB writes and Jev calls")
    mode.add_argument("--dry-run", action="store_true", help="explicit pure planning (also the default)")
    p.add_argument("--backup", type=Path, help="existing nonempty backup of the local sweep database")
    p.add_argument("--increase-budget", action="store_true")
    p.add_argument("--retry-failed", action="store_true")
    a = p.parse_args(argv)
    try:
        pool = json.loads(a.pool.read_text())
        if not isinstance(pool, list):
            raise ValueError("pool JSON must be a list of settings dictionaries")
        cfg = Config(pool, strategy=a.strategy, confirm_sims=a.confirm_sims, model=a.model,
                     stop_after=a.stop_after, margin=a.margin)
        state = run(cfg, a.journal, execute=a.execute, budget=a.budget, jev_budget=a.jev_budget,
                    increase_budget=a.increase_budget, backup=a.backup, retry_failed=a.retry_failed)
        if not a.execute:
            print(json.dumps(state, indent=2))
        else:
            print(f"auto-sweeper: {len(state['attempts'])}/{state['budget']} sweeps; "
                  f"{len(state['choices'])}/{state['jev_budget']} choices; "
                  f"{len(state['evaluations'])} scored; {state['stopped'] or 'budget exhausted; resume available'}",
                  flush=True)
    except KeyboardInterrupt:
        print("auto-sweeper: interrupted; owned child reaped and journal checkpointed", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as ex:
        print(f"auto-sweeper: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
