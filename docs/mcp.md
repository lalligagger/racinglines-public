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

## Getting access, as a user

Two ways in. **Locally** you run the server yourself and there is no account: whoever can run the command on
that machine is the owner. **Hosted** you connect to `https://mcp.racinglines.bet/mcp` and sign in with your
web-app account (or use a token from Settings); your Claude then sees what the app's data shows and can queue what the Lab's
Run form can queue, and every job it queues is filed under your account.

### Local (stdio)

The client launches `racinglines mcp` as a subprocess with your environment (`DATABASE_URL`,
`RACINGLINES_DATA`), in the app's own venv:

```sh
# Claude Code, in any folder:
claude mcp add racinglines -e DATABASE_URL=$DATABASE_URL -- /path/to/racinglines/.venv/bin/racinglines mcp
```

Claude Desktop (Settings > Developer > Edit config), the same idea:

```json
{"mcpServers": {"racinglines": {"command": "/path/to/racinglines/.venv/bin/racinglines", "args": ["mcp"],
                                 "env": {"DATABASE_URL": "postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines"}}}}
```

### Hosted (the VM)

Your account needs a role in `RACINGLINES_MCP_ROLES` (default `admin`); Settings > Connect Claude (MCP) says
if it hasn't. Demo accounts never get access.

1. **Connect.** No token to copy: the client opens racinglines.bet in your browser, you sign in if you aren't
   already, and press **Allow** once.
   - claude.ai and Claude Desktop: Settings > Connectors > Add custom connector, name `racinglines`, URL
     `https://mcp.racinglines.bet/mcp`, leave the OAuth fields empty, then Connect.
   - Claude Code: `claude mcp add --transport http racinglines https://mcp.racinglines.bet/mcp`, then `/mcp`
     inside Claude Code and pick racinglines to sign in. `claude mcp remove racinglines` forgets it.
   - Any other MCP client: streamable HTTP, that URL; it finds the sign-in from the server's 401
     (OAuth 2.1 with dynamic client registration and PKCE).
2. **First questions.** "Call `overview` and summarize what's there" proves the whole path. Then something
   with real content: "list the race_win markets for the next F1 round with our fair value against
   Polymarket and Kalshi" (`list_markets`), or "queue a 3-race, 300-sim F1 backtest and tell me when it's
   done" (`run_job`, then `get_job`; the job shows in the Lab's Jobs section under your name).

The client keeps an access token for an hour and refreshes it by itself for 30 days of disuse; after that,
or after a disconnect, it asks you to sign in again. Settings lists where you've signed in from, and
**Disconnect all** ends every sign-in of your account at once.

**A token instead**, for scripts and clients without sign-in: Settings > Connect Claude (MCP) > **Get a token**
(an admin can also issue one on the VM, below). It is `rl_` followed by 48 hex characters, shown once, and the
card shows the `claude mcp add ... --header "Authorization: Bearer rl_..."` command with it filled in. A new
one, or Revoke, stops the old one at once; it doesn't expire on its own. Keep it like a password.

**Check the door** (any machine with curl): `401` without a token means the server is up; with your token
expect `200`:

```sh
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp.racinglines.bet/mcp
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp.racinglines.bet/mcp \
  -H "Authorization: Bearer rl_YOUR_TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
```

## Giving access, as an admin

### Once: host the server

Steps 7 and 8 of the [VM runbook](vm-deploy.md) are the same in full, with what is Google, what is
Cloudflare and what is neither. In short, and in this order:

1. **Deploy code that has the server** (`bash scripts/deploy/vm.sh deploy` on the Mac). The unit
   `racinglines-mcp.service` is installed by `vm.sh setup` and by every deploy, never enabled for you.
2. **Check `APP_SECRET`, then start the unit, on the VM** (`bash scripts/deploy/vm.sh ssh` from the Mac).
   Sign-in is signed with `APP_SECRET` from `/etc/racinglines.env`, which the web app and the MCP unit both
   read; without it the unit still serves `rl_` tokens but logs that sign-in is off, and `/admin/mcp` says so.
   If it is empty, set it (`openssl rand -hex 32`) and restart both units (it also signs web sessions, so
   everyone signs in again once):
   ```sh
   sudo grep -c '^APP_SECRET=.\+' /etc/racinglines.env                                   # 1 = set
   sudo systemctl enable --now racinglines-mcp
   sudo systemctl status racinglines-mcp --no-pager
   curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8100/mcp      # 401 on the VM itself
   ```
3. **The tunnel** (Cloudflare, once per machine): if the VM has no tunnel yet, Zero Trust > Networks >
   Tunnels > Create a tunnel > Cloudflared, name `racinglines-vm`, install option Debian 64-bit, copy only
   the token (the `eyJ...` string), then on the VM `sudo cloudflared service install <TOKEN>`
   (`cloudflared` itself is installed by `vm.sh setup`; `sudo cloudflared service uninstall` first if it says
   a service exists). The dashboard shows the connector as connected within seconds.
4. **The hostname** (Cloudflare): on the tunnel, Published application routes (the public kind, which
   creates the DNS record; not Hostname routes or Private network routes, which are WARP-only) > Add:
   subdomain `mcp`, domain `racinglines.bet`, path empty, type **HTTP** (not HTTPS: the server speaks plain
   HTTP on loopback), URL `localhost:8100`. No Access policy: clients send only the bearer token, and Access
   would refuse them. Save. The zone's DNS > Records gains a proxied CNAME `mcp`. Nothing on the
   `racinglines.bet` hostname or the Mac's tunnel changes; each hostname belongs to one tunnel.
5. **Check from anywhere**: the two curls in step 2 of the user section, `401` then `200`.

### Per user: who's connected, disconnect, revoke

**Admin > MCP** (`/admin/mcp`) lists every account that has signed in from an MCP client (which client, when it
last signed in or refreshed) or holds an `rl_` token, with **Disconnect** (ends that account's sign-ins),
**Revoke token**, and **Disconnect everyone** (every client must sign in again; signed-in people just press
Allow). Sign-ins keep nothing on the server but a counter per account (`users.prefs["mcp_oauth"]`): client ids,
codes and tokens are signed with `APP_SECRET`, and disconnecting bumps the counter. Who may connect is the role
list below; changing a role takes effect on the next request.

Tokens by hand, on the VM:

Tokens are per web-app account: real accounts only (no demos), active, and with a role listed in
`RACINGLINES_MCP_ROLES` in `/etc/racinglines.env` (default `admin`; `admin,pro` opens it to pro accounts (accounts still stored as `maker` count), then
restart the unit). One token per account; issuing again replaces the old one. On the VM:

```sh
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mcp token <account>'
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mcp token'                      # who holds one
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mcp token <account> --revoke'
```

Send the token to the person over something private; it is printed once and never again (only its SHA-256 is
stored, in `users.prefs["mcp"]`). No restart is needed for a new or revoked token: every request looks it up.
In both modes the tools read as the owner (everything the admin sees) and can queue what a maker can queue in
the Lab; per-role read scoping is a later change if makers get tokens. Tools that show paper trading take a
`user` argument to pick an account.

### After every deploy

`vm.sh deploy` restarts the unit only if it is running, after `update.sh` succeeds. The restart takes a few seconds:
on SIGTERM the server waits at most 10 seconds (`SHUTDOWN_GRACE_SEC` in `racinglines/mcp/server.py`) for requests in
flight, then cancels them, and the unit's `TimeoutStopSec=20` is systemd's margin above that. Before 2026-10-06 the
wait had no limit, so a chat client's open event stream held every restart until systemd's 90-second default killed
the process, and the connector answered 502 for those 90 seconds; a client that was connected reconnects on its own.
If a restart still takes more than 20 seconds, `journalctl -u racinglines-mcp` names what it waited on.

When a deploy's output ends early, or `systemctl status racinglines-mcp` shows an "active since" older than the deploy, restart by
hand: `sudo systemctl restart racinglines-mcp`. The unit is off by default on a fresh VM and stays whatever
you last set it to.

### When it does not work

Each line is what curl (or the log) says, in the order the request travels: DNS, the tunnel, the server,
the token.

| Symptom | Where | Cause and fix |
|---|---|---|
| `000` from curl | DNS | The hostname does not resolve: the route was not saved, or the record is new. `dig +short mcp.racinglines.bet @1.1.1.1` empty means no record: re-add the route, or add a proxied CNAME `mcp` → `<tunnel-id>.cfargotunnel.com` by hand in DNS > Records. An answer from `dig` but `000` from curl is the local resolver's cache; wait a minute. |
| `530` or `502` | Tunnel | `530`: the tunnel has no connector (`sudo systemctl status cloudflared` on the VM). `502`: cloudflared reached the VM but nothing answered on 8100: the unit is down (`journalctl -u racinglines-mcp -n 30`), or the route's URL has a typo. |
| `502` and the log says `Invalid HTTP request received` | Route | The route's type is HTTPS; the server speaks HTTP. Edit the route: type HTTP. |
| `401` with a token | Token | Not a current token: typo, revoked, replaced by a newer one, the account is inactive or a demo, or its role is not in `RACINGLINES_MCP_ROLES`. `racinglines mcp token` on the VM lists holders. `401` without a token is correct. |
| `421` with a token | Server | A build older than 2026-09-28's fix, which only accepted `Host: localhost`: deploy and restart the unit. |
| `racinglines mcp: error: unrecognized arguments: token` | Server | The VM runs a build without per-account tokens: deploy. |
| `fatal: detected dubious ownership` from `git -C /opt/racinglines` | VM | The checkout belongs to the `racinglines` user; prefix git commands with `sudo -u racinglines`. |
| The unit logs "OAuth sign-in ... is off" | Server | `APP_SECRET` is empty in `/etc/racinglines.env`: set it, restart `racinglines-web` and `racinglines-mcp`. |
| claude.ai says the connector failed after Allow | Server | The MCP unit and the web app read different `APP_SECRET`s (one not restarted since it changed): restart both. A "sign-in link has expired" page means more than 10 minutes passed: connect again. |
| Claude connects but every call errors | Client | Ask for `overview` alone; a tool error's text is the reason (a bad argument, an unknown id). The server's own log is `journalctl -u racinglines-mcp`. |

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
| `track_record(user, venue)`, `list_positions(user, venue, event_key)`, `list_signals(user, event_key, status)` | Paper trading per account: the weekend record (Polymarket, Kalshi replay, private book; `venue='all'` lists one row per weekend and venue with a `venue` column and `totals` per venue), positions, signals. |
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
table (the Lab's Jobs section shows them; `user` is the token's account in hosted mode, empty over stdio). The server runs a worker of its own unless
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
