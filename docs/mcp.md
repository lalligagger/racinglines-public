# MCP server

> The app's data and simulations as typed tools for a chat client: run `racinglines mcp` locally, or connect Claude to `https://mcp.racinglines.bet/mcp` and sign in with your web-app account.

`racinglines mcp` starts a [Model Context Protocol](https://modelcontextprotocol.io) server in the app's own
Python environment, against the same database and Parquet archive the web app and the CLI use. A connected
client (Claude Desktop, Claude Code, any MCP client) can then ask questions of the data and run the app's
simulations: "how did the maker do on Kalshi in 2025?", "what did we have for the Baku winner the evening before
qualifying, and what did Polymarket say?", "replay that with a 3¢ spread", "sweep 2026 with the head-to-head
threshold at 5 points and tell me when it's done".

!!! note "A separate process"
    Nothing starts the server for you: the web app, the CLI, the recorder and the signals are untouched. The code
    is `racinglines/mcp/` (`page.py` the result envelope, `tools.py` the tools as plain functions, `server.py` the
    registration and transports) and the command `racinglines/cli/mcp.py`.

=== "Command"

    --8<-- "examples/help-mcp.md:command"

=== "Output"

    --8<-- "examples/help-mcp.md:output"

## Getting access, as a user

### Which should I use?

| | Local (stdio) | Hosted (racinglines.bet) | CLI `--remote` |
|---|---|---|---|
| Needs | the repo, a venv and a database of your own | a racinglines.bet account with MCP access (Pro or admin) | the same account, or an `rl_` token |
| Account | none: whoever runs the command owns it | your web-app account; jobs filed under it | your web-app account |
| Data | yours (`DATABASE_URL`, `RACINGLINES_DATA`) | the app's shared race data, forecasts and Lab research | the same, from the command line |
| Status | ✓ | in testing (#aintcare, below) | in testing |
| Best for | your own rebuilt data, admin tools, `sql` | asking Claude about the live data, queueing Lab jobs | pricing a book file, pulling data, scripting a tool call |

Trying the CLI needs no MCP at all: `racinglines book price --demo` prices a synthetic sample book on a local demo
store ([Quickstart](quickstart.md)).

### Local (stdio)

The client launches `racinglines mcp` as a subprocess with your environment (`DATABASE_URL`,
`RACINGLINES_DATA`), in the app's own venv. There is no account: whoever can run the command on that machine is
the owner.

=== "Claude Code"

    ```bash
    # LOCAL (Mac), in any folder
    claude mcp add racinglines -e DATABASE_URL=$DATABASE_URL -- /path/to/racinglines/.venv/bin/racinglines mcp
    ```

=== "Claude Desktop"

    Settings > Developer > Edit config:

    ```json
    {"mcpServers": {"racinglines": {"command": "/path/to/racinglines/.venv/bin/racinglines", "args": ["mcp"],
                                     "env": {"DATABASE_URL": "postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines"}}}}
    ```

=== "Any MCP client"

    Launch `/path/to/racinglines/.venv/bin/racinglines mcp` as a stdio server with `DATABASE_URL` (and
    `RACINGLINES_DATA` when your data folder is not the repo's `data/`) in its environment. `--db URL` names the
    database instead; `--no-jobs` leaves queued Lab jobs to the web app's worker.

### Hosted (the VM)

!!! warning "Remote access is in testing"
    racinglines.bet remote access is in testing (#aintcare mode). A review of venue and data-feed terms is pending,
    so data served here is for testing only. Every command that connects to the hosted server prints this warning on
    stderr (`racinglines/cli/remote.py`).

Your account needs a role in `RACINGLINES_MCP_ROLES` (default `admin,pro`); Settings > Connect Claude (MCP) says
if it hasn't. Demo accounts, including the `maker` demo, never get access. An explicit `admin` setting still
restricts access to admins; both the web and MCP services must be restarted after changing this setting.

Pro clients can read shared race data, forecasts and Lab research. Their paper records, positions, signals,
private-book market details and jobs are scoped to their own account; another username or job id does not
grant access. Raw SQL, schema inspection and the data-change audit are admin-only. Admins and local stdio
retain owner access. Saved model runs and research results are shared, as in the Lab.

A sport whose schema says `audience = "admin"` (`sports.is_public`, the gate the web pages use too; road cycling
since 2026-10-12, and MotoGP from 2026-10-11 until the owner cleared it on 2026-10-14) is hidden from every
non-admin account: it is missing from every list (overview, events, markets, model runs, forecasts, diagnostics,
paper records, kinds), and naming it, or one of its events, races, runs, tokens or its schema resource, or pricing
a book on it, answers "not available". Admins and local stdio still see it.

#### Step 1: Connect

No token to copy: the client opens racinglines.bet in your browser, you sign in if you aren't already, and press
**Allow** once.

=== "claude.ai and Claude Desktop"

    Settings > Connectors > Add custom connector: name `racinglines`, URL `https://mcp.racinglines.bet/mcp`, leave
    the OAuth fields empty, then Connect.

=== "Claude Code"

    ```bash
    # LOCAL (Mac)
    claude mcp add --transport http racinglines https://mcp.racinglines.bet/mcp
    ```

    Then `/mcp` inside Claude Code and pick racinglines to sign in. `claude mcp remove racinglines` forgets it.

=== "Any MCP client"

    Streamable HTTP at that URL; the client finds the sign-in from the server's 401 (OAuth 2.1 with dynamic client
    registration and PKCE).

=== "The CLI"

    ```bash
    # LOCAL (Mac): the first --remote opens the browser to sign in; later runs reuse the login
    racinglines book price FILE --remote
    racinglines remote tools                      # every tool this account may call
    ```

    The details, tokens and your own server: [From the command line](#from-the-command-line-racinglines-book-remote).

#### Step 2: First questions

"Call `overview` and summarize what's there" proves the whole path. Then something with real content: "list the
race_win markets for the next F1 round with our fair value against Polymarket and Kalshi" (`list_markets`), or
"queue a 3-race, 300-sim F1 backtest and tell me when it's done" (`run_job`, then `get_job`; the job shows in the
Lab's Jobs section under your name).

The client keeps an access token for an hour and refreshes it by itself for 30 days of disuse; after that,
or after a disconnect, it asks you to sign in again. Settings lists where you've signed in from, and
**Disconnect all** ends every sign-in of your account at once.

#### A token instead

For scripts and clients without sign-in: Settings > Connect Claude (MCP) > **Get a token** (an admin can also issue
one on the VM, below). It is `rl_` followed by 48 hex characters, shown once, and the card shows the
`claude mcp add ... --header "Authorization: Bearer rl_..."` command with it filled in. A new one, or Revoke, stops
the old one at once; it doesn't expire on its own. Keep it like a password: never commit it.

#### Check the door

Any machine with curl: `401` without a token means the server is up; with your token expect `200`:

```bash
# LOCAL (Mac), or anywhere
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp.racinglines.bet/mcp
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp.racinglines.bet/mcp \
  -H "Authorization: Bearer rl_YOUR_TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
```

### From the command line (`racinglines book --remote`)

`racinglines book map | price | settle` has three modes ([Sportsbook slips: Three ways in](sportsbook/slips.md#three-ways-in)),
and only one of them uses MCP:

| Mode | MCP? | What it runs on |
|---|---|---|
| `--demo [PACK]` | No; with `--remote`, the pack's hosted demo store | A demo store: a local database of synthetic data from a data pack, built on first use, priced by the same code as `--local` ([Quickstart](quickstart.md)). The first thing to run after installing. `--demo --remote` sends it to the pack's hosted demo store instead (synthetic data only; [Demo data packs](demo.md#the-hosted-demo-store)) |
| `--remote` | Yes, the hosted server | Your book file, sent as text to the `map_book` / `price_book` / `settle_book` tools; the result is the same dict `--json` prints locally, rendered the same way (`racinglines/cli/remote.py`) |
| `--local` (default) | No | Your own database (`--db`, `DATABASE_URL`) |

```bash
# LOCAL (Mac): the first --remote opens the browser to sign in; later runs reuse the login
racinglines book price FILE --remote --rich
racinglines book logout                       # forget the login
```

Sign-in is the connector flow above: the CLI registers itself as the client `racinglines CLI` (dynamic client
registration, PKCE, a loopback redirect to `http://127.0.0.1:<port>/callback`), prints the racinglines.bet URL and
opens it, and waits up to 5 minutes for **Allow**. The login is kept in `~/.config/racinglines/mcp-login.json` (mode
600, one entry per server URL; `RACINGLINES_MCP_LOGIN` moves it) and refreshed on its own, so it shows under
Settings like any other sign-in, and **Disconnect all** ends it too. The same account rules apply: a role in
`RACINGLINES_MCP_ROLES`, no demo accounts.

**A token instead** (scripts, machines with no browser): when `RACINGLINES_MCP_TOKEN` holds an `rl_` token, the CLI
sends it as the bearer and skips the sign-in. Read it without echo:

```bash
# LOCAL (Mac)
read -rs -p "rl_ token: " RACINGLINES_MCP_TOKEN && echo && export RACINGLINES_MCP_TOKEN
racinglines book price FILE --remote
```

**Your own server.** If you host the server yourself ([Once: host the server](#once-host-the-server)), point the CLI
at it once and make `--remote` the default (`racinglines/cli/config.py`, `~/.config/racinglines/cli.toml`):

```bash
# LOCAL (Mac)
racinglines book config mcp_url https://mcp.example.com/mcp
racinglines book config source remote          # plain `racinglines book price FILE` now goes there
```

`--mcp-url` and `RACINGLINES_MCP_URL` override `mcp_url` for one run. A 401 means the token or login is wrong,
revoked, or for an account without MCP access: `racinglines book logout` and run again to sign in afresh. Staging
runs no MCP server, so `--remote` always means production unless you point it elsewhere.

### More commands on the hosted server (`--remote`, `racinglines remote`, `data pull`)

Beyond `book`, three ways reach the hosted server with the same sign-in (Core C53 and C51; the owner cleared exchange
prices, books and trades and MotoGP for signed-in users on 2026-10-14; the #aintcare warning stays on every one).
These commands need the hosted server, which the docs build cannot reach, so only their help is shown.

**`--remote` on a command with a Lab job**: `model backtest|forecast f1|mtb_dh` (their usual flags), and
`strategy sweep f1|nascar|motogp`, `strategy season-strategy f1`, `model diagnostic f1`, `model combo f1`, whose flags
are the job's own knobs as the server's `list_job_types` names them (`--year 2025`, `--event 2026-15 --cutoff
2026-09-25T13:30`), plus `--set NAME=VALUE` for a sweep setting. The job is queued with `run_job` and followed to
the end, its log printed as it arrives.

```bash
# LOCAL (Mac)
racinglines model backtest f1 --remote --races 3 --sims 300
racinglines strategy sweep f1 --remote --year 2025 --set min_edge=0.08
```

**`racinglines remote`**: `tools` lists what the account may call; `call TOOL --ARG VALUE ...` calls any tool and
prints its JSON (`--csv FILE` writes its rows); `job JOB_TYPE --KNOB VALUE` queues any Lab job and follows it.

=== "Command"

    --8<-- "examples/help-remote.md:command"

=== "Output"

    --8<-- "examples/help-remote.md:output"

**`racinglines data pull SPORT [--since last|YYYY-MM-DD] [--no-markets]`**: one sport's shared data into your own
database and data folder (`racinglines/db/pull.py`): every registry table, the sport's events, races, rounds,
results, splits, laps, track profiles, source files and market links, its model runs (not candidates) with their
predictions, and its exchange prices, trades and books by month. Never accounts, profiles, positions, signals,
orders, fantasy rows or jobs. The first pull into a database is a fresh-database load (run `racinglines db init`
on an empty one first: it refuses a database that already has model runs unless `--force`, and empties the pulled
tables so the server's ids are kept); later pulls upsert by id, and `--since last` tops up from where that
database's last pull of the sport stopped (`data/pulls/state.json`). Tools: `pull_manifest(sport, since)` and
`pull_chunk(pull_id, name, offset)`, 4 MB a chunk; the server builds each file on first request
(`data/pulls/server/`, removed after a day).

```bash
# LOCAL (Mac): a fresh local database, then F1's data from the hosted server
racinglines db init
racinglines data pull f1
racinglines data pull f1 --since last          # later: a top-up
```

=== "Command"

    --8<-- "examples/help-data-pull.md:command"

=== "Output"

    --8<-- "examples/help-data-pull.md:output"

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
`RACINGLINES_MCP_ROLES` in `/etc/racinglines.env` (default `admin,pro`; legacy `maker` roles count as pro, but
the username `maker` is still excluded as a demo). If the env file explicitly sets `admin`, change it to
`admin,pro` only after deploying the account-scoped version, then restart both the web and MCP units.
One token per account; issuing again replaces the old one. On the VM:

```sh
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mcp token <account>'
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mcp token'                      # who holds one
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mcp token <account> --revoke'
```

Send the token to the person over something private; it is printed once and never again (only its SHA-256 is
stored, in `users.prefs["mcp"]`). No restart is needed for a new or revoked token: every request looks it up.
Hosted tools apply the caller's account scope on every request. Pro accounts can queue Lab simulations and
read or cancel only their own jobs; tools that take a `user` argument accept only their own username.
Admins and local stdio retain owner access.

### The sql tool's database role

The `sql` tool's text check (`check_sql` in `racinglines/mcp/tools.py`) is a first filter with friendly errors, not a
boundary: the 2026-10-05 audit got past it to `users` with a Unicode-escaped name and a query held in a string, and the
app's own database login is a superuser. The boundary is a login of its own, `racinglines_mcp_ro`: no superuser, read
only, a 10 s statement timeout, and `SELECT` on every table except `users` and `orders` (tables a later migration adds
are readable too). `RACINGLINES_MCP_SQL_URL` in `/etc/racinglines.env` points the `sql` tool at it; every other tool
keeps the app's connection. Without the line, `sql` uses the app's login as before.

```sh
bash scripts/deploy/vm.sh backup mcp-sql-role                                     # first, from the Mac
sudo bash -c 'cd /opt/racinglines && bash scripts/vm/mcp_sql_role.sh'             # on the VM: role, grants, env line, restart
sudo bash -c 'cd /opt/racinglines && bash scripts/vm/mcp_sql_role.sh status'      # superuser=false, users/orders readable: false
```

Re-running it sets a new password and rewrites the line. `DB=racinglines_staging` grants staging's database instead
(the role is shared by the Postgres container; staging runs no MCP unit today). Pro callers cannot invoke the
raw SQL tool even when the role is configured. Install this safeguard before using hosted admin SQL.
Undo: delete the `RACINGLINES_MCP_SQL_URL` line, restart `racinglines-mcp`,
then `DROP OWNED BY racinglines_mcp_ro; DROP ROLE racinglines_mcp_ro;`.

### A second server over a demo store

`racinglines mcp --http --port 8766 --demo kart` serves a data pack's demo store (synthetic data only; its own database
and `data/demo/kart/`) for `racinglines ... --demo --remote` ([Demo data packs](demo.md#the-hosted-demo-store)).
`RACINGLINES_MCP_ACCOUNTS_URL` names the database the accounts, `rl_` tokens and OAuth sign-ins are read from when
it is not the served one (there: production's, so the same accounts sign in); with it set, jobs are filed without an
owner and every signed-in caller sees the store's jobs. `scripts/vm/demo_store.sh build` (backup first) and `serve`
set it up; the owner runs them and adds the `mcp-demo.racinglines.bet` hostname (`localhost:8766`) to the tunnel.

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
| `list_events(sport, competition, season, status)`, `get_event(event_id \| source_key, include)` | Events (`sport` is any sport code the database holds: `overview()` lists them, from the `sports` and `competitions` tables) and one event's races, classification, stored predictions and market matrix (`include=results,predictions,markets`). |
| `search_athletes(q)`, `get_athlete(athlete_id, include)` | Drivers and riders, their results and prediction history. |
| `list_markets(race_id \| event_id \| competition, kinds)` | The venues matrix (`markets/venues.py`): one row per outcome with our fair value, each venue's quote (Polymarket, Kalshi with `RACINGLINES_KALSHI_VENUE=1`, the private book), the gap and, for a past race, the result and the exchange price at the time we priced. `freshness` per exchange: links, the newest sync and `stale` with the reason when an upcoming event has no link on a live exchange or its newest sync is older than `RACINGLINES_STALE_HOURS` (default 3). |
| `get_market_history(tokens \| race_id + kind/athlete_id/subject/exchange, series, start, end, resample)` | Exchange time series from the archive and the database (`markets/store.py`): prices (last per bucket), trades (count, volume, VWAP per bucket) or books (best bid/ask), at most 200 points per token. |
| `list_model_runs(kind, ...)`, `get_model_run(run_id, path)`, `get_predictions(run_id, target, top, standings)` | Runs of every kind, one run's params and metrics (large metrics as a key map; `path='metrics.weekends'` for a part), per-athlete probabilities. |
| `get_forecast(competition, category)` | The live forecast (the run the web app shows): the next races' top probabilities and the championship. |
| `edge_finder(year, strategy, venue)`, `list_candidates()` | The Lab's Edge Finder from saved sweeps: every configuration's full-season recap per strategy (`venue`: the exchange the sweep traded, a column on every row) and its closing-line value (`clv`, the run's `metrics.clv` row for that strategy; `get_model_run(run_id, path='metrics.clv')` has the per-stage and per-event tables); the saved candidates. |
| `list_diagnostics()`, `get_diagnostic(run_id)` | As-of diagnostic runs; one run's prices vs Polymarket at the cutoff, edges, scores and result. |
| `track_record(user, venue, sport)`, `list_positions(user, venue, event_key)`, `list_signals(user, event_key, status)` | Paper trading per account: the weekend record (Polymarket, Kalshi replay, private book; `venue='all'` lists one row per weekend and venue with a `venue` column and `totals` per venue; `sport` keeps one sport's weekends, NASCAR and MotoGP paper rows included where `RACINGLINES_SPORT_PAPER` is on), positions, signals. |
| `fantasy_balance(user)`, `fantasy_positions(user, open_only)`, `fantasy_orders(user)`, `fantasy_leaderboard()`, `fantasy_markets(q)`, `fantasy_book(market_link_id)` | Fantasy trading (F$ only), as the Trade and History tabs show it: your F$ (total, cash shared with your strategy, both P&Ls), hand-trade positions, orders with refusal reasons, the leaderboard (P&L, ROI, score; never balances), the tradable markets with recorded prices, one market's 10-level book. Hosted non-admin callers read their own account only (`user` is for an admin or stdio). Resolved hand trades are paid out first, as the pages do. |
| `fantasy_order(market_link_id, side, action, shares, limit_price, client_key)` | One immediate-or-cancel F$ order through `fantasy/exchange.place`, the Trade page's path: the shared F$1,000 balance check under the account's row lock, F$100 per order, depth 10, fresh book only, rate limit, an audit row tagged `via: mcp`. Over HTTP it always trades as the caller (admin included); over stdio `user` names the account. Demo accounts and a shared store's accounts are refused. Nothing reaches an exchange. |
| `pull_manifest(sport, since)`, `pull_chunk(pull_id, name, offset)` | `racinglines data pull`: the files of one sport's pull (the registry, its race data, model runs and exchange history by month) and one base64 chunk of one of them. A hidden sport is not available. |
| `list_live_events()`, `data_changes()` | Settled live private-book events and the run folders present; the data change log. |
| `list_kinds(sport)`, `map_book(book)`, `price_book(book, run_ids)`, `settle_book(book)` | Sportsbook slips ([sportsbook/slips.md](sportsbook/slips.md)): every market kind with the sports that model it; then a generic sportsbook's book, passed as TOML text, mapped to exact races and athletes, priced (the book's, the model's and the linked prediction market's probability, EV against each, never blended) or settled from the stored results. Nothing is stored. |
| `storage_status(refresh)` | Admin only. Where the data lives: VM disk, data folders, database dumps and sizes, and the data bucket per prefix (size, objects, newest), from the last snapshot (`racinglines db storage`, the admin Storage page); `refresh=true` starts a new one in the background. Sizes and counts only. |
| `sql(query, limit, offset)` | Any `SELECT` (or `WITH ... SELECT`, `EXPLAIN`), in a `READ ONLY` transaction with a 10 s timeout, paged. The `users` and `orders` tables are not readable. |

**Scenarios** (the only tools that write anything, and only what the Lab's Run form writes):

| Tool | What it does |
|---|---|
| `list_job_types()` | The Lab's job catalog (`web/jobs.py`) with knobs, ranges and defaults, and every sweep setting. |
| `run_job(job_type, params)` | Queue a job: `f1_backtest`, `f1_scenario` (a forward forecast saved as a scenario, never the live prices), `f1_diagnostic` (`event='2026-15'`, `cutoff='2026-09-25T13:30'`), `f1_sweep` (`year` + `settings`: any sweep setting), `f1_season_strategy`, `f1_combo` (combo / same-game parlay prices for one event: `event='2026-17'`, `legs=[{"kind": "race_win", "driver": "Max Verstappen"}, {"kind": "race_fastest_lap", "driver": "Max Verstappen"}]` or several as `{name: [legs]}`, optional `cutoff` (default now), `variant` (default the core taker's variant, profile A, + `flpos`); the run's `metrics.combos` holds each fair value, leg marginals, product, lift and a `calibrated` flag, `metrics.checks` the simulation's P(pole-sitter wins) and P(winner sets the fastest lap) beside history; [sportsbook: combos](sportsbook/index.md)), `dh_scenario`, `dh_backtest`. Validated exactly as the Lab validates its form. |
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
- **Tables for the terminal:** a result that holds a list of records also comes with a drawn table of it
  (`racinglines/mcp/view.py`, at most 30 rows and 12 columns per table), so Claude Code shows a table in the terminal.
  The table is the first text block and the JSON is always the last one, which is the block the CLI's `--remote` path
  parses. The tools return no `structuredContent`, so a client shows the text blocks. Colour is off by default because
  escape codes are just noise to a client that shows text as is. `RACINGLINES_MCP_COLOR=1` on the server turns it on:
  bold headers, signed EV, edge and P&L columns green above zero and red below.

## What it can't do

No exchange orders, no private-book quotes or settlements, no promotion of a scenario to the live prices, no
ingest, athlete merges or data-change notes, no reading of `users` or `orders` through `sql`. Adding any of
these is a deliberate change, not a switch.

## Checks

`python -m pytest tests/test_mcp.py` (part of the regression suite): the envelope's caps, the SQL guard, and a
client round trip over an in-memory transport against the test database (tools, errors, paging, a queued job,
the resources), and the token lifecycle with the bearer check of the hosted mode. No network.
`tests/test_book_slips.py` runs the CLI's `--remote` against a local hosted server (OAuth on, uvicorn on
127.0.0.1): with an `rl_` token, with a wrong one (401), and through the browser sign-in, its stored login and
logout, and that the #aintcare testing warning is printed for remote and not for local or demo. `tests/test_demo_store.py`
builds a demo store and prices the kart pack's book on it.

## Next steps

<div class="grid cards" markdown>

-   :material-rocket-launch: **Quickstart**

    ---

    The CLI on a synthetic demo store, every command with its real output; the hosted way in beside it.

    [:octicons-arrow-right-24: Quickstart](quickstart.md)

-   :material-book-open-variant: **Sportsbook slips**

    ---

    The book file the `map_book`, `price_book` and `settle_book` tools read.

    [:octicons-arrow-right-24: Sportsbook slips](sportsbook/slips.md)

-   :material-flask: **The Lab**

    ---

    What `run_job` queues: backtests, scenarios, diagnostics, Edge Finder sweeps, season strategies.

    [:octicons-arrow-right-24: Web app: the Lab](webapp.md)

</div>
