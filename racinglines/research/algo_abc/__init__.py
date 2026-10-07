"""Algorithm A/B/C study (engine roadmap E7, research form): first-stage finishing-order models compared walk-forward
on the same input (past finishing orders only), per sport.

    data.py      the results frame: from a pg_dump (`load_dump`) or CSVs pulled through the read-only sql tool
    algos.py     A (the repo's results-only form model), B (Plackett-Luce MAP), C (Weng-Lin / TrueSkill-style
                 ratings), and two controls (uniform, average recent finish)
    evaluate.py  walk-forward scoring (win log loss, top-3/top-10 Brier, head-to-head log loss and accuracy),
                 race-level bootstrap CIs, and the CLI: python -m racinglines.research.algo_abc.evaluate --help
"""
