"""
racinglines <command> [--sport SPORT] [options]

{commands}
  Groups
    backtest  walk-forward SPORT | coverage | clv   (the backtest core, any sport with a pricing model)
    markets   sync | history | trades | record | archive
    book      map | price | settle | view   (generic sportsbook lines and slips: model and market EV, docs/sportsbook/slips.md)
    live      new | step | run | agent | status | report   (a live private-book event, any sport)
    weather   probe | fetch | show   (weather forecasts per event, docs/weather.md)
    db        init | seed | stats | export
    users     setup | list | add | reset-password | remove | deactivate | activate   (accounts, fantasy bucks)
    web       serve the web app
    mcp       the MCP server: the data and simulations for a chat client (docs/mcp.md)
    check     quick validation: code on synthetic data, data endpoints, database

SPORT is f1, mtb_dh, nascar, motogp or cycling; without --sport, $RACINGLINES_SPORT, else the one sport offering the
command. `racinglines <command> --sport SPORT -h` gives a command's options, `racinglines <group> -h` a group's.
"""

import sys

GROUPS = ("weather", "backtest", "markets", "book", "db", "live", "web", "users", "mcp", "check")
# the sport-first form (`racinglines f1 forecast`): still runs, not listed (the VM's timers, scripts and Lab jobs use it)
SPORT_FIRST = ("f1", "mtb_dh", "nascar", "motogp", "cycling")
BACKTEST_CORE = ("walk-forward", "coverage", "clv", "-h", "--help")     # `backtest` without these is a sport's backtest


def _usage():
    from racinglines.cli import flat
    return __doc__.replace("{commands}", flat.help_text())


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    from racinglines.cli import flat
    known = GROUPS + SPORT_FIRST + flat.COMMANDS
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in known:
        print(_usage())
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    import importlib
    if argv[0] not in ("web", "mcp"):              # servers, not jobs: no heartbeat
        from racinglines import progress
        progress.start(" ".join(a for a in argv[:2] if not a.startswith("-")))   # stderr, every 5 min (progress.py)
    if argv[0] in flat.COMMANDS and not (argv[0] == "backtest" and len(argv) > 1 and argv[1] in BACKTEST_CORE):
        return flat.main(argv[0], argv[1:])
    mod = importlib.import_module(f"racinglines.cli.{argv[0]}")
    return mod.main(argv[1:])
