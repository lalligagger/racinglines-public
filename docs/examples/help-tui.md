<!-- Captured by scripts/docs/capture_examples.py (id help-tui, scripts/docs/examples.toml) on 2026-10-16 01:58 UTC, commit 806278c+dirty, 0.3 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines tui -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines tui [-h] [--local] [--db DB] [--no-jobs] [--mcp-url MCP_URL] [--user USER]
                       [--timeout TIMEOUT]

racinglines tui                          the web app's screens in the terminal, on the hosted server (docs/tui.md)
racinglines tui --local [--db URL]       the same on this machine's database: `racinglines mcp` over stdio

Hosted sign-in is `--remote`'s (cli/remote.py): RACINGLINES_MCP_TOKEN, else the browser once, kept in
~/.config/racinglines/mcp-login.json. The sign-in happens here, before the screen opens, so its URL is readable.

    RACINGLINES_MCP_URL     the hosted server (default https://mcp.racinglines.bet/mcp); --mcp-url overrides it
    RACINGLINES_USER        the account preselected on the Paper tab; --user overrides it

options:
  -h, --help         show this help message and exit
  --local            this machine's database through `racinglines mcp` (stdio)
  --db DB            with --local: the database URL (default $DATABASE_URL, else the local one)
  --no-jobs          with --local: don't run the Lab's job worker here (leave queued jobs to the
                     web app)
  --mcp-url MCP_URL  the hosted server (default RACINGLINES_MCP_URL or racinglines.bet)
  --user USER        account preselected on the Paper tab
  --timeout TIMEOUT  seconds to wait for one tool call (default 90)
```
<!-- --8<-- [end:output] -->
