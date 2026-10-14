<!-- Captured by scripts/docs/capture_examples.py (id help, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 0.0 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
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
    remote    tools | call | job | logout   (the hosted server's tools from the command line, docs/mcp.md)
    check     quick validation: code on synthetic data, data endpoints, database

SPORT is f1, mtb_dh, nascar, motogp or cycling, e.g. `racinglines model forecast f1 --save`.
--demo on any command: the same command on the demo store, a separate database and data folder of synthetic data
(built on first use; racinglines/cli/source.py, docs/quickstart.md), e.g. `racinglines model forecast kart --demo --save`.
`racinglines <group> -h` lists a group's commands and the sports that offer each.
```
<!-- --8<-- [end:output] -->
