"""
racinglines <group> <command> [options]

    f1        fetch | ingest | forecast | backtest | diagnostic | sweep | season-strategy | replay
    mtb_dh    download | parse | ingest | forecast | backtest
    markets   sync | history | trades | record | archive
    db        init | seed | stats | export
    web       serve the web app
    check     quick validation: code on synthetic data, data endpoints, database

`racinglines <group> -h` for a group's commands and options.
"""

import sys

GROUPS = ("f1", "mtb_dh", "markets", "db", "web", "check")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in GROUPS:
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    import importlib
    mod = importlib.import_module(f"racinglines.cli.{argv[0]}")
    return mod.main(argv[1:])
