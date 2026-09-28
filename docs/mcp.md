# MCP server

`racinglines mcp` starts a [Model Context Protocol](https://modelcontextprotocol.io) server in the app's own
Python environment, against the same database and Parquet archive the web app and the CLI use. A connected
chat client (Claude Desktop, Claude Code, any MCP client) can then ask questions of the data and run the
app's simulations through typed tools: "how did the maker do on Kalshi in 2025?", "what did we have for the
Baku winner the evening before qualifying, and what did Polymarket say?", "replay that with a 3¢ spread",
"sweep 2026 with the head-to-head threshold at 5 points and tell me when it's done".

It is a separate process that nothing starts for you: the web app, the CLI, the recorder and the signals are
untouched. The code is `racinglines/mcp/` (`page.py` the result envelope, `tools.py` the tools as plain
functions, `server.py` the registration and transports) and the command `racinglines/cli/mcp.py`.

## Connecting a client

**Locally (stdio, the default).** The client launches the server as a subprocess with your environment
(`DATABASE_URL`, `RACINGLINES_DATA`), so access is whoever can run commands on that machine.

```sh
# Claude Code, in any folder:
claude mcp add racinglines -e DATABASE_URL=$DATABASE_URL -- /path/to/racinglines/.venv/bin/racinglines mcp
```

Claude Desktop (Settings > Developer > Edit config), the same idea:

```json
{"mcpServers": {"racinglines": {"command": "/path/to/racinglines/.venv/bin/racinglines", "args": ["mcp"],
                                 "env": {"DATABASE_URL": "postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines"}}}}
```

**Hosted (the VM, streamable HTTP).** `racinglines mcp --http` serves `http://127.0.0.1:8100/mcp`, and every
request must carry the bearer token of a real web-app account:

```sh
racinglines mcp token admin          # issue the admin account's token (printed once; replaces any earlier one)
racinglines mcp token                # who holds one
racinglines mcp token admin --revoke
```

A token is `rl_` plus 48 hex characters; only its SHA-256 is stored, in `users.prefs["mcp"]`. A request is
accepted when the token matches an active, non-demo account whose role is in `RACINGLINES_MCP_ROLES` (default
`admin`: the owner tests with their own Claude first; `admin,maker` later opens it to makers, each with their
own token and no other change). The server refuses to start in `--http` mode while no account has a token.
The account behind a request is recorded as the `user` of any job it queues. Demo accounts never get a token.

On the VM the unit `racinglines-mcp.service` runs it (`deploy/vm/systemd/`; installed by `vm.sh setup`,
restarted by `vm.sh deploy` only if it is running, never enabled for you). Setting it up the first time,
as done on 2026-09-28 (steps 7–8 of the [VM runbook](vm-deploy.md) have the same in full):

1. **On the VM** (`bash scripts/deploy/vm.sh ssh` from the Mac), issue the token and start the unit:
   ```sh
   sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mcp token admin'
   sudo systemctl enable --now racinglines-mcp
   ```
   The token is printed once; copy it. `racinglines mcp token` (no account) lists who holds one.
2. **In the Cloudflare dashboard** (Zero Trust > Networks > Tunnels > `racinglines-vm` > Public hostnames >
   Add): subdomain `mcp`, domain `racinglines.bet`, type `HTTP`, URL `localhost:8100`, no Access policy
   (clients send only the bearer token). The VM needs the tunnel from runbook step 7 first. This is the
   only Cloudflare-specific part: on any other host it is "expose 127.0.0.1:8100 as HTTPS on a hostname".
3. **On the Mac**, check, then connect:
   ```sh
   curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp.racinglines.bet/mcp     # 401 = up and locked
   claude mcp add --transport http racinglines https://mcp.racinglines.bet/mcp --header "Authorization: Bearer rl_..."
   ```
   `000` from curl is DNS: the hostname was not saved, or its record is still propagating. Claude Desktop
   takes the same URL and header as a custom connector. First ask for `overview`, then something with a
   market matrix or a queued backtest (`run_job` then `get_job`; the job's `user` is the token's account).

Nothing in this is Google-specific: the VM is any Linux box with the units installed by `vm.sh setup`, and
the tunnel follows the machine that runs `cloudflared service install`.

Over stdio there are no tokens: whoever can run the command on that machine is the owner. In both modes the
tools read as the owner (everything the admin sees) and can queue what a maker can queue in the Lab; tools that
show paper trading take a `user` argument to pick an account.

## Tools

`overview()` first: sports, seasons, the live forecast per competition, run counts by kind, market links per
exchange, venues, users and the next races. Then:

| Tool | What it reads or does |
|---|---|
| `describe_schema(table)` | The tables with one-line meanings, or one table's columns (for `sql`). |
| `list_events(sport, competition, season, status)`, `get_event(event_id \| source_key, include)` | Events and one event's races, classification, stored predictions and market matrix (`include=results,predictions,markets`). |
| `search_athletes(q)`, `get_athlete(athlete_id, include)` | Drivers and riders, their results and prediction history. |
| `list_markets(race_id \| event_id \| competition, kinds)` | The venues matrix (`markets/venues.py`): one row per outcome with our fair value, each venue's quote (Polymarket, Kalshi with `RACINGLINES_KALSHI_VENUE=1`, the private book), the gap and, for a past race, the result and the exchange price at the time we priced. |
| `get_market_history(tokens \| race_id + kind/athlete_id/subject/exchange, series, start, end, resample)` | Exchange time series from the archive and the database (`markets/store.py`): prices (last per bucket), trades (count, volume, VWAP per bucket) or books (best bid/ask), at most 200 points per token. |
| `list_model_runs(kind, ...)`, `get_model_run(run_id, path)`, `get_predictions(run_id, target, top, standings)` | Runs of every kind, one run's params and metrics (large metrics as a key map; `path='metrics.weekends'` for a part), per-athlete probabilities. |
| `get_forecast(competition, category)` | The live forecast (the run the web app shows): the next races' top probabilities and the championship. |
| `edge_finder(year, strategy)`, `list_candidates()` | The Lab's Edge Finder from saved sweeps: every configuration's full-season recap per strategy; the saved candidates. |
| `list_diagnostics()`, `get_diagnostic(run_id)` | As-of diagnostic runs; one run's prices vs Polymarket at the cutoff, edges, scores and result. |
| `track_record(user, venue)`, `list_positions(user, venue, event_key)`, `list_signals(user, event_key, status)` | Paper trading per account: the weekend record (Polymarket, Kalshi replay, private book), positions, signals. |
| `list_live_events()`, `data_changes()` | Settled live private-book events and the run folders present; the data change log. |
| `sql(query, limit, offset)` | Any `SELECT` (or `WITH ... SELECT`, `EXPLAIN`), in a `READ ONLY` transaction with a 10 s timeout, paged. The `users` and `orders` tables are not readable. |

**Scenarios** (the only tools that write anything, and only what the Lab's Run form writes):

| Tool | What it does |
|---|---|
| `list_job_types()` | The Lab's job catalog (`web/jobs.py`) with knobs, ranges and defaults, and every sweep setting. |
| `run_job(job_type, params)` | Queue a job: `f1_backtest`, `f1_scenario` (a forward forecast saved as a scenario, never the live prices), `f1_diagnostic` (`event='2026-15'`, `cutoff='2026-09-25T13:30'`), `f1_sweep` (`year` + `settings`: any sweep setting), `f1_season_strategy`, `dh_scenario`, `dh_backtest`. Validated exactly as the Lab validates its form. |
| `get_job(job_id, log_lines)`, `list_jobs(status)`, `cancel_job(job_id)` | Follow a job (status, progress, the last log lines, the model run it saved), list them, cancel one that has not started. |
| `replay_maker(run_id, fill, half_spread, size, max_pos, max_capital, skew, max_disagree, min_volume_24h, pull_min, exchange, with_sweep)` | The event diagnostic's maker replay with every knob, against the real trade tape of Polymarket or Kalshi (`exchange`): synchronous, seconds, nothing stored. |

Jobs run as CLI subprocesses through the same worker the web app uses, one at a time, and land in the `jobs`
table (the Lab's Jobs section shows them; `user` is empty). The server runs a worker of its own unless
`--no-jobs`, so a queued job runs whether or not the web app is up; with both running, whichever is free takes
the next job. Forecasts started here are scenarios: the live prices change only when a maker promotes one in
the Lab.

**Resources**: `racinglines://docs` lists the documentation pages and `racinglines://docs/<page>` returns one
(`model.md`, `market-making.md`, `f1-forecast.md`, ...); `racinglines://sports/<code>` is a sport's schema. A
client can pull the page that defines a number before explaining it.

## Guardrails against a flooded context

Every tabular result goes through one envelope (`racinglines/mcp/page.py`):

```json
{"columns": ["..."], "rows": [{"...": "..."}], "total": 1187, "offset": 0, "limit": 50, "truncated": true,
 "next_offset": 50, "note": "50 of 1,187 rows; pass offset=50 for the next page"}
```

- **Row cap:** 50 rows per call by default, 500 at most (`limit`); `total` always says how many exist.
- **Byte cap:** a page over 24 KB (`RACINGLINES_MCP_MAX_BYTES`) is cut to the rows that fit, and the note says so.
- **Summaries first:** `get_event` and `get_athlete` return only what `include` asks for; `list_markets` counts
  outcomes per kind before listing them; `get_market_history` resamples to at most 200 points per token;
  `get_model_run` returns large metrics as a key map with sizes and one part on request; `get_job` returns a log
  tail, never the log.
- **Values:** floats to 4 decimals, timestamps ISO-8601 UTC, NaN as null; long text and JSON columns are
  previewed with their size in lists and returned whole by the `get_*` tool for one row.
- **`sql`:** an outer `LIMIT/OFFSET` is applied for you, plus the row and byte caps; one statement, reads only.
- Results are one line of JSON (no indentation), which halves the bytes an indented dump would cost.

## What it can't do

No exchange orders, no private-book quotes or settlements, no promotion of a scenario to the live prices, no
ingest, athlete merges or data-change notes, no reading of `users` or `orders` through `sql`. Adding any of
these is a deliberate change, not a switch.

## Checks

`python -m pytest tests/test_mcp.py` (part of the regression suite): the envelope's caps, the SQL guard, and a
client round trip over an in-memory transport against the test database (tools, errors, paging, a queued job,
the resources), and the token lifecycle with the bearer check of the hosted mode. No network.
