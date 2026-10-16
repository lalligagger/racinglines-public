"""
racinglines <group> <command> [SPORT] [options]

    data      fetch | ingest | link | download | parse | record | pull | ...   SPORT   (results, sessions, feeds)
    model     forecast | backtest | compare | diagnostic | props | ...   SPORT   (pricing)
    strategy  replay | sweep | season-replay | signals | scorecard | ...  SPORT   (trading against exchange tapes)
    backtest  walk-forward SPORT | coverage | clv   (the backtest core, any sport with a pricing model)
    weather   probe | fetch | show   (weather forecasts per event: Weather Underground, docs/weather.md)
    markets   sync | history | trades | record | archive
    book      map | price | settle | view | render | new   (generic sportsbook lines and slips: model and market EV, docs/sportsbook/slips.md)
    db        init | seed | stats | export
    live      new | step | run | agent | status | report   (a live private-book event, any sport)
    web       serve the web app
    users     setup | list | add | reset-password | remove | deactivate | activate   (accounts, fantasy bucks)
    mcp       the MCP server: the data and simulations for a chat client (docs/mcp.md)
    tui       the web app's screens in the terminal, over MCP: hosted, or --local (docs/tui.md)
    remote    tools | call | job | logout   (the hosted server's tools from the command line, docs/mcp.md)
    check     quick validation: code on synthetic data, data endpoints, database

SPORT is f1, mtb_dh, nascar, motogp or cycling, e.g. `racinglines model forecast f1 --save`.
--demo on any command: the same command on the demo store, a separate database and data folder of synthetic data
(built on first use; racinglines/cli/source.py, docs/quickstart.md), e.g. `racinglines model forecast kart --demo --save`.
`racinglines <group> -h` lists a group's commands and the sports that offer each.
"""

import sys

GROUPS = ("data", "model", "strategy", "weather", "backtest", "markets", "book", "db", "live", "web", "users", "mcp", "remote",
          "tui", "check")
# the sport-first form (`racinglines f1 forecast`): deprecated, an alias for one version with a notice on stderr, not listed
VERB_GROUPS = ("data", "model", "strategy")
SPORT_FIRST = ("f1", "mtb_dh", "nascar", "motogp", "cycling")


def _notice(argv):
    """One line on stderr naming the new form of a sport-first command (`racinglines f1 forecast` is now
    `racinglines model forecast f1`). Help and unknown commands print nothing."""
    from racinglines.cli import verbs
    try:
        cmd = next((a for a in argv[1:] if a in verbs.commands(argv[0])), None)
    except Exception:                              # never let the notice break the command
        return
    group = cmd and verbs.group_of(cmd, argv[0])
    if group and not {"-h", "--help"} & set(argv):
        print(f"deprecated: `racinglines {argv[0]} {cmd}` is going away, use `racinglines {group} {cmd} {argv[0]}`",
              file=sys.stderr)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in GROUPS + SPORT_FIRST:
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    import importlib
    if argv[0] not in ("web", "mcp", "tui"):       # servers and the full-screen TUI, not jobs: no heartbeat
        from racinglines import progress
        progress.start(" ".join(a for a in argv[:3 if argv[0] in VERB_GROUPS else 2] if not a.startswith("-")))   # stderr, every 5 min (progress.py)
    from racinglines.cli import source
    argv = source.apply(argv)                      # the data source (--demo, first run) before any module reads it
    try:
        if argv[0] in VERB_GROUPS:
            from racinglines.cli import verbs
            return verbs.main(argv[0], argv[1:])
        if argv[0] in SPORT_FIRST:
            _notice(argv)
        mod = importlib.import_module(f"racinglines.cli.{argv[0]}")
        return mod.main(argv[1:])
    finally:
        source.reset()
