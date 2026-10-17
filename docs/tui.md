# Terminal app (racinglines tui)

`racinglines tui` is the web app's tabs in a terminal, built with [Textual](https://textual.textualize.io/) and Rich. It
holds one MCP session and calls the same tools a chat client does ([MCP server](mcp.md)): every screen is a view of a
tool's JSON, so it shows what the server serves, nothing computed on the side.

```
racinglines tui                       # the hosted server, signed in as for --remote (in testing: the #aintcare warning)
racinglines tui --local [--db URL]    # this machine's database: `racinglines mcp` over stdio, owner mode
```

--8<-- "examples/help-tui.md:output"

## Sign-in

Hosted is `--remote`'s sign-in ([CLI reference](cli.md#where-the-data-comes-from-demo-remote-local)):
`RACINGLINES_MCP_TOKEN` (an `rl_` token from `racinglines mcp token ACCOUNT`), else the browser once, stored in
`~/.config/racinglines/mcp-login.json`. The sign-in runs before the screen opens, so its URL and any 401 print in the
terminal; `racinglines book logout` forgets the login. The remote-access warning prints there too and shows again in
the app on connect.

`--local` starts `racinglines mcp` with the same Python, so the TUI and the server share one environment and one
database (`--db`, else `DATABASE_URL`). Stdio has no tokens: as with any stdio client, whoever runs it is the owner.
The server's stderr goes to `~/.cache/racinglines/tui/server.log`, never to the screen. `--no-jobs` leaves queued
Lab jobs to the web app's worker.

## Tabs

| Key | Tab | Tools |
|---|---|---|
| 1 | Home: row counts, next races, live forecasts, seasons, run kinds, linked markets, venues | `overview` |
| 2 | Forecast: the next races' win / podium / top-10 and the championship, per competition and category | `get_forecast` |
| 3 | Markets: fair value against each venue, the gap drawn as a bar, freshness per venue (stale after `RACINGLINES_STALE_HOURS`); an outcome opens its price history | `list_events`, `list_markets`, `get_market_history` |
| 4 | Events: by competition, season, status; a weekend opens on results, predictions and its market matrix | `list_events`, `get_event` |
| 5 | Athletes: search; results and prediction history | `search_athletes`, `get_athlete` |
| 6 | Trade: F$ balance, tradable markets, the recorded book, the expected fill, IOC orders, positions, orders, leaderboard | `fantasy_*` |
| 7 | Paper: an account's track record with its cumulative P&L, positions with totals per venue, signals | `track_record`, `list_positions`, `list_signals` |
| 8 | Lab: jobs (refreshed every 5 s, log tail, cancel, the saved run), new jobs from `list_job_types` with every sweep setting, Edge Finder, candidates, diagnostics with maker replay, model runs with each metrics part one key away | `list_jobs`, `get_job`, `cancel_job`, `list_job_types`, `run_job`, `edge_finder`, `list_candidates`, `list_diagnostics`, `get_diagnostic`, `replay_maker`, `list_model_runs`, `get_model_run`, `get_predictions` |
| 9 | Sportsbook: a book as TOML; map, price, settle ([Sportsbook slips](sportsbook/slips.md)) | `map_book`, `price_book`, `settle_book`, `list_kinds` |
| 0 | Live: the private book's events and whether one is live now, refreshed every 30 s | `list_live_events` |
| | Data: the change log, the schema, a read-only SQL console, and `racinglines data pull` (run as a subprocess) | `data_changes`, `describe_schema`, `sql` |

Everywhere: `r` refreshes, `enter` opens a row, `[` and `]` page, `esc` goes back, `ctrl+r` reconnects, `ctrl+l` turns
[layout mode](#layout-mode) on and off, `?` lists the keys. A row that names a job, a model run (`run_id`, `result_run_id`, `last_run`, a change's `detail.run`), an event
(`event_id`, `event_key`) or an athlete opens it. Lists the server pages (signals, positions, Edge Finder, diagnostics,
the change log, SQL) page through it rather than loading everything.

Colour has one meaning each: green in our favour (fair above market, profit), red against, purple the best on the
board, amber stale. Settings (`min_edge`, `max_stake`, a sweep's knobs) print as written, never coloured as data.

## Layout mode

`ctrl+l` turns layout mode on: a bar under the header names the layout and the splits on this tab, and a divider
shows between the two sides of each split. The other keys work as usual until `esc` or `ctrl+l` again.

| In layout mode | |
|---|---|
| `←` `→` | move this tab's side-by-side split 5% (`shift` for 1%) |
| `↑` `↓` | move this tab's stacked split 5% (`shift` for 1%) |
| drag a divider | move that split with the mouse |
| `s` | save into the current layout (on `default`, asks for a name) |
| `a` | save as a new layout; an existing name is replaced |
| `n` | switch to the next saved layout |
| `x` | put this tab's splits back to the built-in sizes |

| Split | Tab | Sides |
|---|---|---|
| `trade.h` | Trade | markets ↔ book and order form |
| `trade.v` | Trade | markets and book ↕ positions, orders, leaderboard |
| `lab.diag` | Lab > Diagnostics | diagnostic runs ↔ maker replay |
| `book.h` | Sportsbook | the book's TOML ↔ the result |

A side gets 10% to 90%. Layouts are kept in `~/.config/racinglines/tui-layouts.json` (`RACINGLINES_TUI_LAYOUTS`
overrides the path) with the one last used, which the next start opens in. `default` is built in and can't be
overwritten. Leaving layout mode without saving keeps the sizes until you quit.

## Trade

Orders are fantasy F$ and reach no exchange (`fantasy_order`). Before one is sent the TUI shows the fill walked from
the recorded book (at most 10 levels, at or better than the limit) and asks to confirm. It blocks an order on a book
older than the server's `max_age_min` (15), a buy over the `max_stake` cap (F$100) or beyond the cash, and gives each
order a fresh `client_key` so a retry can't fill twice. "Search Trade" on a market outcome fills the Trade search
with its subject: a search, not a link, since a fantasy market and a matrix outcome share no exact key. The same
rule holds in the market screen's price history: it is fetched by the venue's token, else by `athlete_id` (with the
row's `exchange` when it has one), and an outcome with neither shows "no exact key" rather than a name match. The
Trade book refreshes every 20 s only while the Trade tab is in front.

## Data > Pull writes your database

Pull runs `racinglines data pull SPORT` as a subprocess and **writes to the database it names**. The TUI asks first,
showing the command and the database URL (password hidden), and makes no backup itself: take the dump before you
confirm, as in [Data changes](data-changes.md) (`data/backups/db/racinglines-before-<task>-<UTC time>.sql.gz`). The pull
is terminated if its worker is cancelled or the app quits.

## Lab: a sweep from an Edge Finder row

An Edge Finder row opens its season recap and the settings that differ from the defaults (`changed_settings` for its
`settings_key`). "Queue a sweep with these settings" fills the F1 sweep form with them and the row's year and venue;
only changed fields are sent with `run_job`. Edge Finder rows don't name a sport: for a NASCAR or MotoGP configuration
pick `nascar_sweep` or `motogp_sweep` before queueing.

## Limits

- `track_record` has no offset: past about 68 weekends the server cuts the page, and the equity curve says how many
  of the total it covers. `get_event` carries the newest 60 predictions; `search_athletes` returns one page.
- Web features with no MCP tool are not here: promoting a scenario to the live prices, following a strategy (#218
  adds it to MCP), account settings, and the private book's house markets and bets (readable with `sql`).
- The `fantasy_order` result reads `status`, `filled`, `avg_price`, `fee` and `reason`; it was the one tool not
  called against the live server while building this (it places a real F$ order).

## Tests

`python -m pytest tests/test_tui_*.py` (no network, no database): payload parsing and the book walk, a real MCP stdio
round trip (`tests/tui_stub_server.py`), the CLI wiring, and every tab driven headless against payloads captured
from the hosted server on 2026-10-16 (`tests/tui_fixtures.py`). `TUI_SHOTS=<dir>` saves an SVG of each screen.
