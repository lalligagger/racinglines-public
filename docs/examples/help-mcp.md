<!-- Captured by scripts/docs/capture_examples.py (id help-mcp, scripts/docs/examples.toml) on 2026-10-14 05:12 UTC, commit 3ed9335+dirty, 0.4 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines mcp -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines mcp [-h] [--db DB] [--http] [--host HOST] [--port PORT] [--no-jobs]

racinglines mcp                          the MCP server over stdio (docs/mcp.md)
racinglines mcp --http [--port 8100]     streamable HTTP on 127.0.0.1:8100/mcp; each request needs an account's token
racinglines mcp token ACCOUNT [--revoke] issue (print once) or revoke an account's bearer token; `token` alone lists holders

options:
  -h, --help   show this help message and exit
  --db DB      database URL (default $DATABASE_URL, else the local one)
  --http       serve streamable HTTP (per-account bearer tokens) instead of stdio
  --host HOST
  --port PORT
  --no-jobs    don't run the Lab's job worker here (leave queued jobs to the web app)
```
<!-- --8<-- [end:output] -->
