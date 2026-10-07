"""
racinglines <group> <command> [options]

    f1        fetch | ingest | forecast | backtest | diagnostic | sweep | season-strategy | replay
    mtb_dh    download | parse | ingest | forecast | backtest | walk-forward
    nascar    fetch | ingest   (the free content feeds: results, stages, laps)
    motogp    fetch | ingest   (the free public results API: race classifications)
    cycling   events | fetch | startlist | price   (road cycling sportsbook lines: TTs and road races)
    backtest  walk-forward SPORT   (the backtest core, any sport with a pricing model); coverage (read-only)
    markets   sync | history | trades | record | archive
    db        init | seed | stats | export
    live      new | step | run | agent | status | report   (a live private-book event, any sport)
    web       serve the web app
    users     setup | list | add | reset-password | remove | deactivate | activate   (accounts, fantasy bucks)
    mcp       the MCP server: the data and simulations for a chat client (docs/mcp.md)
    check     quick validation: code on synthetic data, data endpoints, database

`racinglines <group> -h` for a group's commands and options.
"""

import sys

GROUPS = ("f1", "mtb_dh", "nascar", "motogp", "cycling", "backtest", "markets", "db", "live", "web", "users", "mcp", "check")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in GROUPS:
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    import importlib
    if argv[0] not in ("web", "mcp"):              # servers, not jobs: no heartbeat
        from racinglines import progress
        progress.start(" ".join(a for a in argv[:2] if not a.startswith("-")))   # stderr, every 5 min (progress.py)
    mod = importlib.import_module(f"racinglines.cli.{argv[0]}")
    return mod.main(argv[1:])
