<!-- Captured by scripts/docs/capture_examples.py (id help-data-pull, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 1.1 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines data pull f1 -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines data pull [-h] [--since SINCE] [--no-markets] [--keep] [--force] [--db DB]
                             [--mcp-url MCP_URL]
                             sport

`racinglines data pull SPORT`: one sport's shared data from the hosted server into the local database and data folder
(racinglines/db/pull.py says what a pull holds). Sign-in is `--remote`'s (cli/remote.py: the browser once, or
RACINGLINES_MCP_TOKEN), and the remote-access warning is printed first.

    racinglines data pull f1                   everything for F1 (the first pull wants a fresh database: db init)
    racinglines data pull f1 --since last      a top-up from where this database's last F1 pull stopped
    racinglines data pull f1 --since 2026-09-01 --no-markets

positional arguments:
  sport              a sport code (sports/<code>.toml), e.g. f1, nascar, motogp

options:
  -h, --help         show this help message and exit
  --since SINCE      'last' (where this database's last pull stopped) or a UTC date: a top-up
  --no-markets       race data and model runs only (no exchange history)
  --keep             keep the downloaded files (data/pulls/<pull id>/)
  --force            a first pull into a database that already has model runs: replace its race
                     data and the rows that point at it
  --db DB            the local database (default: DATABASE_URL or the CLI defaults)
  --mcp-url MCP_URL  the hosted server (default RACINGLINES_MCP_URL or racinglines.bet)
```
<!-- --8<-- [end:output] -->
