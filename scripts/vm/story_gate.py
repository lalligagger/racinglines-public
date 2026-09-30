"""
Gate (c) of the demo taker story on the VM (docs/overnight-vm-run.md): before the taker's backfill is reset, check
that the walk-forward rule, run on the evidence sweeps just saved, picks what the taker re-sweep's section 6 says.
Read-only. Exit 0 to go on, 1 to stop (nothing is reset).

    python scripts/vm/story_gate.py

Expected: the defaults before 2025 round 1, then "update · gridq+pretrain+reset · min_edge=0.1" after round 8, kept
after round 16 and before 2026, with 32 candidates (16 settings x update and stage-aware) at the last decision.
"""

import inspect
import sys

EXPECTED = "update · gridq+pretrain+reset · min_edge=0.1"
CANDIDATES = 32


def check(ds):
    """[problems] for the decisions story.decisions(conn, taker=True) returned."""
    bad = []
    if len(ds) != 4:
        return [f"expected 4 decisions, got {len(ds)}"]
    if not ds[0]["chosen"].startswith("update · baseline"):
        bad.append(f"before the first race: {ds[0]['chosen']!r}, expected the defaults (update · baseline)")
    for d in ds[1:]:
        if d["chosen"] != EXPECTED:
            bad.append(f"{d['label']}: {d['chosen']!r}, expected {EXPECTED!r}")
    if ds[-1]["candidates"] == 0:
        bad.append("0 candidates at the last decision: the evidence sweeps are missing")
    elif ds[-1]["candidates"] != CANDIDATES:
        bad.append(f"{ds[-1]['candidates']} candidates at the last decision, expected {CANDIDATES}")
    return bad


def main():
    from racinglines.db.config import get_engine
    from racinglines.pipelines import story
    if "taker" not in inspect.signature(story.decisions).parameters:
        print("STOP: this checkout has no taker story (merge PR #87 and run vm.sh deploy first)")
        return 1
    with get_engine().connect() as c:
        ds = story.decisions(c, taker=True)
    for d in ds:
        print(f"{d['label']:30s} candidates {d['candidates']:3d}  weekends {d['weekends']:2d}  "
              f"{'switched to' if d['switched'] else 'kept'} {d['chosen']}")
    bad = check(ds)
    for b in bad:
        print("STOP:", b)
    if not bad:
        print("GATE OK: the rule picks the taker re-sweep's story")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
