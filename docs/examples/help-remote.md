<!-- Captured by scripts/docs/capture_examples.py (id help-remote, scripts/docs/examples.toml) on 2026-10-15 03:27 UTC, commit 1b6b5a15, 0.3 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines remote -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
racinglines remote <command>   (the hosted server's MCP tools, signed in as for --remote)

    tools                       the tools this account may call, with their arguments
    call TOOL [--ARG VALUE ...] call one tool and print its JSON; --csv FILE writes its rows instead
                                e.g. racinglines remote call get_market_history --race-id 812 --series trades
                                     racinglines remote call list_live_events
                                     racinglines remote call replay_maker --run-id 10833 --half-spread 0.03
                                     racinglines remote call fantasy_strategy
                                     racinglines remote call fantasy_follow --code T2 --sizing kelly --kelly 0.5
    job JOB_TYPE [--KNOB VALUE] queue a Lab job and follow its log (list_job_types names them; --set NAME=VALUE
                                for a sweep setting), e.g. racinglines remote job f1_sweep --year 2025
    logout                      forget the stored sign-in

    --mcp-url URL               the server (default RACINGLINES_MCP_URL, else https://mcp.racinglines.bet/mcp)
```
<!-- --8<-- [end:output] -->
