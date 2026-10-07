# CLI reference

Everything runs through one command (after `pip install -r requirements.txt && pip install -e .`):

```
racinglines f1      fetch | ingest | forecast | backtest | compare | matrix | diagnostic
                    sweep | season-strategy | season-checkpoints | replay | search | search-import
                    profiles | signals | demo-history | reconcile
                    pm-sync | pm-history | pm-trades | pm-record | pm-archive | pm-links-export | pm-links-import
racinglines mtb_dh  download | parse | ingest | forecast | backtest | walk-forward
racinglines nascar  fetch | ingest | link | replay | season | season-replay | demo-history | forecast
                    (the free content feeds; which driver and race a market is about; the taker replay; the season forecast;
                    the champion-market replay; the demo paper portfolio; the next races' forecast)
racinglines motogp  fetch | ingest | compare | search | replay | season-replay | demo-history | forecast
racinglines markets sync | history | trades | record | archive      (= racinglines f1 pm-*)
racinglines weather probe | fetch | show                            (weather forecasts per event: Open-Meteo, no key)
racinglines db      init | seed | stats | export | snapshot-export | snapshot-import | merge-athletes | changes
racinglines web
racinglines mcp     [--http] [--host H] [--port 8100] [--no-jobs] | token ACCOUNT [--revoke]     the MCP server
racinglines check   [--sport f1|mtb_dh] [--offline] [--no-db]    quick validation (see Testing)
```

`python -m racinglines …` works too. Add `-h` to any group or command for its options.

The database connection comes from `$DATABASE_URL`, or `--db URL` on the group
(`racinglines f1 --db URL …`, `racinglines db --db URL …`). The default is the local
Postgres on port 5433 (see [Database](database.md#setup)).

## racinglines mtb_dh download

`racinglines/sources/chronorace/download.py`.

```
racinglines mtb_dh download (--year YEAR | --events SLUG [SLUG ...] | --probe START END)
                              --discipline {DH,XCO,XCC,EDR}
                              --category "Elite Men" | "Junior Men" | "Elite Women" | "Junior Women" | ...
                              [--probe-suffixes SUFFIX ...] [--pdf-results] [--out-dir DIR] [--list-only]
```

| Option | Meaning |
|---|---|
| `--year` | Find events from the Wikipedia season page (only slugs dated that year). |
| `--events` | Explicit ChronoRace slugs; skips Wikipedia. |
| `--probe` | Also find events by trying `YYYYMMDD_{dh,dhi,mtb,xco}` for every date from START to END (`YYYY-MM-DD`) against ChronoRace, for rounds missing from Wikipedia. About 2 s per day. Combines with `--year`/`--events`. |
| `--probe-suffixes` | The suffixes `--probe` tries (default `dh dhi mtb xco`). |
| `--pdf-results` | For rounds without live timing, read the result PDF into the round's table (the 2021 Leogang and Les Gets rounds, several Timed Training rounds). Needs poppler's `pdftotext` (`brew install poppler`). Off by default: the round is written as its PDF links. |
| `--discipline` | DH is the tested one; XC/EDR are best-effort. |
| `--category` | Friendly name; mapped to `ME`/`MJ`/`WE`/`WJ`/`MU`/`WU`. |
| `--out-dir` | Default `data/raw/mtb_dh/chronorace/`. |
| `--list-only` | Print the discovered slugs and stop. |

Output: `<out-dir>/<slug>_<discipline>_<category>.md`. Existing files are overwritten.

Typical full refresh:

```
for y in 2021 2022 2023 2024 2025 2026; do
  for c in "Elite Men" "Junior Men"; do
    racinglines mtb_dh download --year $y --discipline DH --category "$c" --out-dir data/raw/mtb_dh/chronorace/
  done
done
# 2021 rounds missing from Wikipedia (found by --probe 2021-04-01 2021-10-31):
racinglines mtb_dh download --events 20210914_dh 20210918_dh --discipline DH --category "Elite Men"  --out-dir data/raw/mtb_dh/chronorace/
racinglines mtb_dh download --events 20210914_dh 20210918_dh --discipline DH --category "Junior Men" --out-dir data/raw/mtb_dh/chronorace/
```

Add `--pdf-results` to fill PDF-only rounds from their result PDFs. The 2026 elite files were renamed by
hand (`2026-08_les-gets_men-elite.md`); a re-download writes `<slug>_dhi_elite-men.md` beside them, so
rename or remove one of each pair before parsing a directory into a CSV (ingest keys races by event, so
the database isn't affected).

Find unlisted events:

```
racinglines mtb_dh download --probe 2021-04-01 2021-10-31 --discipline DH --category "Elite Men" --list-only
```

## racinglines mtb_dh parse

```
racinglines mtb_dh parse --inspect FILE
racinglines mtb_dh parse [--input-dir DIR] [--input-file FILE ...] [--out splits.csv]
                 [--round LABEL] [--conditions-file CSV] [--canonical-venues]
```

| Option | Meaning |
|---|---|
| `--inspect` | Print the detected structure of one file and exit. |
| `--input-dir` | Parse every `.html/.htm/.csv/.json/.md/.txt` in the directory (not recursive). |
| `--input-file` | One file; can be repeated. |
| `--out` | Output CSV (default `splits.csv`). |
| `--round` | Force a round label on every row (rarely needed). |
| `--conditions-file` | CSV `event_id,round,track_condition` to fill in `track_condition`. |
| `--canonical-venues` | Write venues under their canonical slugs (`sports/mtb_dh.toml` `[venue_aliases]`, as the database stores them: `vallnord` → `pal-arinsal`). Default: as spelled in the source. |

## racinglines mtb_dh ingest

```
racinglines mtb_dh ingest [PATH ...] [--db URL] [--competition uci_dhi_wc] [--force] [--note WHY]
```

Loads downloaded files into the database. `PATH` is files or directories
(non-recursive `*.md`; default `data/raw/mtb_dh/chronorace`). Unchanged files are
skipped by content hash, and `--force` re-ingests them. Each ingested file replaces
its race's rounds, results and splits. See [Database](database.md#ingest). A run that ingests anything
is logged in the [data change log](data-changes.md), with `--note` as the reason.

## racinglines mtb_dh forecast

Predict and backtest one target season.

```
racinglines mtb_dh forecast (--db [URL] | --data splits.csv) [--competition uci_dhi_wc] [--save [--scenario LABEL]]
       [--out-dir data/runs/mtb_dh/forecast]
       [--season YEAR] [--category ME]
       [--train-scope {all,season}] [--half-life-days 240] [--junior-weight 0.25]
       [--prior-n 0.5] [--eps-df DF]
       [--walk-forward] [--backtest 2] [--remaining 2] [--unraced-format {default,last}]
       [--sims 10000] [--seed 42] [--top 15]
```

| Option | Default | Meaning |
|---|---|---|
| `--db [URL]` | – | Read from the database (`$DATABASE_URL` or the default if no URL is given). |
| `--data` | – | Read a tidy CSV from `racinglines mtb_dh parse` instead. |
| `--competition` | `uci_dhi_wc` | Competition code in the database. |
| `--save` | off | Store the model run, its metrics and predictions in the database (needs `--db`). |
| `--points` | `schema` | Points tables: `schema` = the placeholders in `sports/mtb_dh.toml` for every season (today's behaviour); `db` = each season's tables from `points_schemes` ([`mtb_dh points`](#racinglines-mtb_dh-points)), falling back to the placeholders. |
| `--scenario LABEL` | – | With `--save`: store as `kind='scenario'`, ignored by live prices until promoted in the web app's Lab. |
| `--season` | latest in data | Target season. |
| `--category` | `ME` | Target category. |
| `--train-scope` | `all` | `all` = every season and category in `--data`; `season` = target only. |
| `--half-life-days` | 240 | Recency half-life for training runs (120 before 2026-09-28). |
| `--junior-weight` | 0.25 | Training weight of `MJ` runs relative to elite (0.5 before 2026-09-28). |
| `--prior-n` | 0.5 | Shrinkage of each rider's pace toward the field (1.5 before 2026-09-28; [Calibration](model.md#calibration)). |
| `--eps-df` | normal | Student-t run noise with these degrees of freedom (above 2), same sd. Tried at 4 and 6: no better. |
| `--walk-forward` | off | Predict and score every target round from everything before it. |
| `--backtest N` | 2 | Hold out the last N raced rounds; score them and the standings after them. `0` skips. |
| `--remaining N` | 2 | Rounds left in the season, **including** in-progress events already in the data (forecast with their start lists). The rest are simulated as unknown rounds. `0` skips the forecast. |
| `--unraced-format` | `default` | The format those rounds are simulated in: `default` = the 2026 elite men's (`[rounds] default_format`, a 30-rider final) for every category; `last` = the category's latest completed event's own format (women, juniors), else `[rounds.category_format]`. |
| `--sims` | 10000 | Monte Carlo simulations (walk-forward uses at most 5000). |
| `--seed` | 42 | Random seed. |
| `--top` | 15 | Rows printed per table. |

Files written: `walk_forward.csv`, `backtest_<venue>.csv`, `backtest_standings.csv`,
`forecast_per_round.csv`, `forecast_standings.csv`.

## racinglines mtb_dh live

Follow a downhill final live from UCI timing (ChronoRace): rank probabilities after every update, the demo
maker's quotes, the private book's anonymous crowd, and the demo accounts' private-book positions. A demo
experiment; see [Live events](live-events.md). The loop holds a lock in the final's run folder (as
`racinglines live run` does): a second loop for the same final says so and exits instead of polling alongside it.

```
racinglines mtb_dh live --slug 20260925_mtb --final 3 --quali 2,91 --conditions "clear, rutted"
```

| Option | Default | |
|---|---|---|
| `--slug` | (required) | ChronoRace event slug |
| `--final` | (required) | Live-timing key of the final (Whistler 2026: `3` men, `6` women) |
| `--quali` | `2,91` | Live-timing keys of the qualifying sessions, comma-separated |
| `--conditions` | | Free text; "rutted" and "wet" widen the spread and raise the crash risk |
| `--interval` | 20 | Seconds between polls |
| `--minutes` | 0 | Stop after this many minutes (0: when the final is over) |
| `--once` | | One update, then exit |

## racinglines live

Launch and run a live private-book event for any sport, from a launch spec (`live/<sport>/<event>.toml`):
`new`, `step`, `run`, `agent`, `status` and `report`. The commands, options and the F1 engine are in
[Live events](live-events.md#running-an-event-racinglines-live).

```
racinglines live new f1 2026-16
racinglines live step live/f1/2026-16.toml
racinglines live agent live/f1/2026-16.toml --install
racinglines live status
```

## racinglines mtb_dh backtest

Walk-forward plus a standings holdout, for several seasons.

```
racinglines mtb_dh backtest (--db [URL] | --data splits.csv) [--competition uci_dhi_wc] [--save]
       [--out-dir data/runs/mtb_dh/backtests]
       [--seasons 2021 2022 ...] [--category ME]
       [--train-scope all] [--half-life-days 240] [--junior-weight 0.25]
       [--prior-n 0.5] [--eps-df DF] [--reliability]
       [--sims 4000] [--seed 42]
```

`--prior-n` and `--eps-df` work as for `forecast`. `--reliability` also prints and saves
(`backtest_reliability.csv`) reliability curves over every walk-forward round: win, podium,
top 10 and making the Final, per probability bin ([Calibration](model.md#calibration)).

`--db`, `--data`, `--competition`, `--save` and `--points` work as for `forecast` (with `--points db`, each season uses its own tables). With `--save`, the
per-season and per-event metrics are stored in `model_runs.metrics`. Seasons with
fewer than 3 events that have data are skipped. Files written:
`backtest_events.csv` (one row per predicted round) and `backtest_seasons.csv` (one
row per season). The printed per-season table includes the actual and predicted
champion.

## racinglines backtest walk-forward

The backtest core for any sport with a pricing model ([Backtest core](backtest-core.md#adding-a-sport)):
every event priced from data before it, model-only, calibration per market kind. The sport's settings are
its flags (`racinglines backtest walk-forward SPORT -h` lists them). What a search job for a sport other
than F1 runs.

```
racinglines backtest walk-forward SPORT [--db URL] [--seasons 2025 2026] [--kinds K1,K2] [--save]
       [--out-dir data/runs/<sport>/walk_forward] [the sport's settings, e.g. --seed N --sims N]
```

## racinglines backtest coverage

The coverage counter (parity rebuild package C0), read-only: it writes nothing to the database. It prints four
things. The first is what it counted: the database, the archive trees, and the Postgres and Parquet rows per
store. A header line says when there's no market tape at all, which is how you check a copy such as staging.
The second is one row per sport × exchange × market kind × season of race markets: links, races linked,
races settled, races with a price, trade or book tape (Postgres or the Parquet archive, through
`markets/store.py`), the parity tier, the maker tier, whether the kind is modeled, and links still `unmodeled`.
The third is the season futures. The fourth is, per sport, the race results in the database (seasons, events,
events with results) and the results sources its schema declares (`[results]`, `[replay]` or `[model]` source,
allowed fallbacks, `[sport] results_modules`, cleared or not).

```
racinglines backtest coverage [--db URL] [--seasons 2025 2026] [--out DIR]
```

A tier counts, per season, the races with both a settlement and a price tape. **parity-2** is 8 or more in two
seasons, **parity-1** is 8 or more in one, **thin** is 1 to 7, and **missing** is none. The maker tier counts
book tape in place of price tape. A kind is **modeled** when `markets/kinds.py` defines it, the sport's schema
names a `pricing_model`, and one of the schema's `kinds` / `*_kinds` lists names it. A link's kind is its
`prediction`, or `params.kind` while it's `unmodeled`. Its season is the year of the race's event, or of the
link's `end_date` for a futures market. `--out` writes `coverage_combos.csv`, `coverage_futures.csv` and
`coverage_results.csv`.

## racinglines mtb_dh walk-forward

Every completed event priced through the shared engine, model-only
([Backtest core](backtest-core.md#the-walk-forward-engine)): calibration per market kind (win, podium,
top 10, fastest qualifier, makes the Final; `--kinds race_h2h` adds head-to-heads), overall and per season.

```
racinglines mtb_dh walk-forward (--db [URL] | --data splits.csv) [--seasons 2025 2026] [--kinds K1,K2]
       [--category ME] [--sims 5000] [--half-life-days 240] [--prior-n 0.5] [--junior-weight 0.25]
       [--train-scope all] [--eps-df DF] [--seed N] [--save] [--out-dir data/runs/mtb_dh/walk_forward]
```

Writes `walk_forward_events.csv`, `walk_forward_calibration.csv` and `walk_forward_reliability.csv`.
With `--save`, stores a `walk_forward` model run (settings, per-event scores, calibration), which is
what a downhill search job runs.

## racinglines mtb_dh points

Championship points tables by season, and a rider-by-rider check against official standings
([Roadmap → Points validation](todo.md#points-validation)).

```
racinglines mtb_dh points import sports/points/uci_dhi_wc.toml --db     # file -> points_schemes
racinglines mtb_dh points show --db                                     # the tables each season uses
racinglines mtb_dh points check --db --season 2026 --through-round 7 --standings STANDINGS.toml
```

| Command | What it does |
|---|---|
| `import FILE` | Loads one table per era and round kind (`final`, `qual`, `qual1`, `semi`) into `points_schemes`, replacing rows with the same era start and round kind. Refuses tables that aren't non-negative and non-increasing. |
| `show` | Per season: where its tables come from (`db` or `schema`), official or placeholder, and their sizes. |
| `check` | Each rider's cumulative points, from the results and the season's tables, against the official standings (CSV with `rider`, `points`, or TOML as in `sports/points/standings/`). Riders match by name, ignoring accents, case and word order. Exits 1 if any rider differs. `--points schema` checks the placeholders instead. |

`sports/points/uci_dhi_wc.toml` is the entry template: every table in it is still a **placeholder**
(the schema's scales copied into each era). The owner replaces them with the official UCI scales,
sets `official = true` and cites the source.

## racinglines nascar

NASCAR Cup, from the content feeds at `cf.nascar.com` (no key). See [Data](data.md#nascar-content-feeds-verified-2026-09-29).

```
racinglines nascar fetch [--years 2026] [--series 1] [--feeds a,b] [--races 5624,5628] [--force] [--dry-run]
racinglines nascar ingest [--years 2026] [--series 1] [--force] [--no-laps]        (group option: --db URL)
racinglines nascar link [--exchange kalshi] [--apply --backup FILE] [--undo FILE]
racinglines nascar replay [--years 2025-2026] [--venue all|kalshi|polymarket|og] [--kinds a,b] [--min-edge X] [--min-volume USD]
                          [--events KEY,...|latest] [--tape probe|pull] [--require-tradeable] [--buy-all]
                          [--save --backup FILE] [--undo BATCH]
racinglines motogp replay   (the same options)
RACINGLINES_NASCAR_SEASON=1 racinglines nascar season [--year 2026] [--sims 4000] [--seed 7] [--stage-noise 5] [--race-noise auto|N|model] [--standings feed|results] [--quotes] [--csv FILE]
RACINGLINES_SEASON_REPLAY=1 racinglines nascar season-replay [--year 2026] [--venue all|kalshi|polymarket|og] [--sims 2000] [--min-edge 0.03] [--stake-per-edge 500] [--max-stake 150] [--capital 1500] [--out DIR]
RACINGLINES_SEASON_REPLAY=1 racinglines motogp season-replay   (the same options)
racinglines nascar demo-history --pick data/runs/replay-grid/nascar                       (print the selection, write nothing)
racinglines nascar demo-history --grid data/runs/replay-grid/nascar --backup FILE [--book kinds|blend|best]
                                [--venue kalshi|polymarket] [--grid-venue kalshi|polymarket] [--users taker] [--events KEY,...|latest]
racinglines nascar demo-history --reset --backup FILE [--venue kalshi|polymarket] [--users taker] [--grid FOLDER]
racinglines nascar forecast [--races 3] [--save --backup FILE] [--undo RUN_ID]
racinglines motogp demo-history | forecast   (the same options)
```

| Command | What it does |
|---|---|
| `fetch` | Download the feeds to `data/raw/nascar/cf/<year>/<series>/`, byte for byte, one request per second, for every race already run. Files on disk are skipped and a feed the server says is missing (HTTP 403) is remembered in a `.missing` marker (not for races from the last three days, whose feeds may not be published yet), so a re-run after each race weekend asks only for what is new. `--feeds` picks from `race_list_basic, points-feed, weekend-feed, pit-data, loopstats, lap-times, lap-notes`; `--races` limits to some race ids; `--force` asks again; `--dry-run` requests nothing and prints how many requests a run would make. |
| `ingest` | Load the stored feeds into the database: events (races still to run as `scheduled`), rounds (practice, qualifying, race), results, laps, and one athlete per NASCAR `driver_id`. A race whose files have not changed is skipped (`--force` rebuilds it); `--no-laps` leaves out the lap table. Only Cup (`--series 1`) has a competition. |
| `link` | Say which driver, race and contract each stored NASCAR market link is about (Kalshi, Polymarket, OG.com), the same answer the syncs now give new links ([Data](data.md#nascar-content-feeds-verified-2026-09-29)). A **dry run** by default: totals, one line per exchange, series and kind with how many links got a driver and a race, and the names it could not place. `--apply` writes `athlete_id`, `race_id` and `params` (`kind`, `nascar_series`, `season`) of the links that change and refuses without `--backup FILE`, a database dump under 24 hours old; it records a `data_changes` entry and an undo file (`data/backups/db/nascar-links-undo-<UTC>.json`) that `--undo FILE` replays. `--exchange` limits it to one exchange. Run it after `ingest`, since it matches against the drivers and races in the database. |
| `replay` | Taker replay of the season's Cup races against the recorded prices of every exchange the sport lists (`--venue all`, the default: Kalshi, then Polymarket, one report each; then OG.com where `exchanges/og.toml` lists the sport (NASCAR, not MotoGP); `--venue kalshi`, `polymarket` or `og` for one. OG.com's stored minute prices, trades and book quotes all count, whatever their spread, side or depth, except a stored 0.50 from an empty book; its fee is the schema's flat $0.02 per contract, unverified) ([`pipelines/position_replay.py`](https://github.com/lalligagger/racinglines-public/blob/main/racinglines/pipelines/position_replay.py)). Per race: the field is the race's start list, the model in `[sport] pricing_model` prices it from earlier races only, and the F1 taker (`update` / `hold` / `last`) trades at the stages of `sports/<code>.toml` `[replay]` (hours from 00:00 UTC on race day: T-3d, T-1d, race eve) wherever the market is priced, has $50 of 24 h volume, is still open and its group is coherent; the result settles by classified position. Prints P&L, Kalshi's taker fees and P&L after fees per mode, P&L by kind and model-vs-exchange calibration, and writes `data/runs/replay/<sport>-<venue>-<years>/`. Kinds: NASCAR race win, top 3/5/10/20 and head-to-head; MotoGP race win. Links are read as `link --apply` (NASCAR) or the sync (MotoGP, whose `[identity]` resolver `sources/motogp/links.py` is on by default since 2026-09-30) left them, and any link not yet identified is identified in memory; nothing is written to `market_links`. Read-only unless `--save`, which also stores one as-of model run per race (`model_runs` kind `diagnostic` + `race_predictions` + prediction records and sims, unless `RACINGLINES_PREDICTION_RECORDS=0`; with the first venue's pass only), refuses without `--backup FILE` (a dump under 24 hours old), logs a `data_changes` entry with its batch id, and is undone with `--undo BATCH`. Each report first counts races with markets, markets priced and markets tradeable; a race whose markets have no stored price at any stage is flagged `NO TAPE`, and a venue where nothing was tradeable prints `NOT TRADED` with the reason instead of P&L lines (`--require-tradeable` then exits 1). The tape (prices and trades) is pulled by `--tape pull --backup FILE`: for the selected races only, their markets' trades and hourly prices from 2 days before the first stage to 2 days after the last (idempotent upserts, logged in `data_changes`), then the replay runs; `--tape probe` asks each exchange about 3 markets of the first selected race, prints the counts, writes nothing and stops. `--buy-all` (debug, off by default; or `RACINGLINES_BUY_ALL=1`, which the F1 weekend sweep also reads) adds the mode `buy_all` ([`markets/strategies/buy_everything.py`](https://github.com/lalligagger/racinglines-public/blob/main/racinglines/markets/strategies/buy_everything.py)): one YES and one NO share of every market open and priced strictly inside (0, 1) at its first such stage, with no edge, volume, price-band or coherence filter, costs and Kalshi's fee still applied, so a pair loses exactly its costs and fees and the cell shows that the market reached the replay and settled; its report adds P&L by side and kind and `buy_all_trades.csv`, and the taker's modes are unchanged. **`buy_all` is a plumbing check, not a result:** it shows that the tape reached the replay and settled, it is never shown in the web app or in any report, no page or status cell counts it as a backtest, and `demo-history` never stores it. Otherwise the F1 sweep is not involved. |
| `demo-history` | The replay's trades as the demo accounts' paper portfolio, shown in the app and written only while `RACINGLINES_SPORT_PAPER` is on, **which is the default** since 2026-09-30 (unset = on; `0` or any value other than `1`/`true`/`yes`/`on` turns it off, and then the command refuses to write; `--pick` works either way) (also `motogp demo-history`; [Paper trading](paper-trading.md#nascar-and-motogp-demo-in-sample-off-by-default)). Every row is in-sample and labelled so. `--grid data/runs/replay-grid/<sport> --backup FILE` (the grid is the overnight run's read-only settings grid, runs `<year>-e<edge>-v<volume>/<venue>/summary.json`): picks each market kind's best grid setting (best worse-season net after fees; in-sample), replays the grid's seasons and stores each race's `update` trades as backfilled signals and Kalshi paper positions for `--users` (default `taker`), replacing that race's earlier rows; `--book blend` trades every kind at the one best setting; `--book best` is the best-effort book (best total per kind, else every kind at the best total, win or lose); `--events latest` for a spot check; `--pick FOLDER` prints the selection and writes nothing; `--reset --backup FILE` deletes this sport's demo rows on `--venue` for `--users` (with `--grid` too, it then rebuilds). `--venue` is `kalshi` (the default) or `polymarket`; `--grid-venue` picks the settings from another venue's grid (Polymarket has none, so `--venue polymarket --grid-venue kalshi` trades Polymarket's tape with the Kalshi grid's selection). `--backup` must be a dump under 24 hours old. Writes the selection to `demo-selection-<venue>.md` in the grid folder and prints the undo command. Never the debug `buy_all` mode. Logs a `data_changes` entry. On the VM, `vm.sh demo` runs it for both sports and both demo accounts ([VM deploy](vm-deploy.md#whats-in-the-repo)). |
| `forecast` | The next scheduled races priced by the sport's model (`[sport] pricing_model`, the replay's settings), field from the latest race's entrants (also `motogp forecast`; [Web app](webapp.md#accounts-demo-users-vs-polymarkets-takers)). Read-only; `--save --backup FILE` stores one `forecast` run (model_runs + race_predictions) that the board, race pages and exchange markets read as live prices; `--undo RUN_ID` removes it. Logs a `data_changes` entry. `--races N` (default 3) is how many scheduled races. A sport with no scheduled race stored (or no completed race to take a field from) says so and stores nothing: that is MotoGP today, whose ingest loads finished events only, so it has no forecast until its calendar (the upcoming events) is ingested. Nothing is tuned: the model settings are the replay's (`[replay]`, seed 7). |
| `season-replay` | The champion-market replay, **read-only and off by default** (`RACINGLINES_SEASON_REPLAY=1`; also `motogp season-replay`) ([Championship markets](championship-markets.md#championship-replays-backtests)): the F1 championship sleeve's default strategy traded against each exchange's recorded champion prices (`--venue all`, the default: every exchange the sport lists, one report each; or `kalshi`, `polymarket`, `og`), with an as-of season forecast after every points race from the results before it only (NASCAR: the Chase model of `season`, standings summed from results; MotoGP: `models/motogp_season.py`, Grand Prix and sprint points, Grand Prix only and flagged when no sprint is stored). MotoGP champion contracts are classified in memory; nothing is written to the database. Writes `decisions.csv`, `trades.csv`, `positions.csv`, `equity.csv` and `summary.json` to `data/runs/season-replay/<sport>-<venue>-<year>/` (or `--out DIR`). Not yet run on the VM as of 2026-09-30 ([Roadmap](todo.md)). |
| `season` | The Cup season forecast, **read-only and off by default** (`RACINGLINES_NASCAR_SEASON=1`) ([`models/nascar_season.py`](https://github.com/lalligagger/racinglines-public/blob/main/racinglines/models/nascar_season.py)). The standings today are NASCAR's own `points-feed.json` when it is on disk (points with penalties, the official seeds; matched by NASCAR driver id), else summed from the season's stored results (the feed's points per race, stage and bonus points included; seeds from regular-season points, ties by wins, then top 5s, then top 10s; `--standings results` forces this); the output lists every driver whose results-summed points or seed differ from the feed; every points race still to run is priced by `[sport] pricing_model` for the field of the last race run, turned into points (55 for a win, 35 for 2nd down to 1; 10..1 to each paid stage's top 10, stages simulated as the race order re-drawn with `--stage-noise` places; the one bonus point a race), each race's finishing order drawn with `--race-noise` places of spread (`auto`, the default: the spread measured on the last two seasons, about 7 places, not the race model's own 2.0, which puts most simulated wins on one favourite), and the season runs through the 2026 Chase (top 16 on points, reset 2100 / 2075 / 2065 / 2060 / 2055 then 5 fewer a place to 2000, no eliminations, most points after 10 races). Prints each driver's seed, points today, expected points and the odds of making the Chase, the title, the top 3 and the top 10, and cross-checks the points against NASCAR's own `points-feed.json` when it is on disk (penalties show up there). `--quotes` puts the champion price beside every Cup champion contract on file (OG.com's 17, Kalshi's, Polymarket's), with the edge net of the schema fee (OG.com only; Kalshi and Polymarket before fees). Nothing is saved; `exchanges/og.toml` keeps NASCAR `modeled = false`, so the board and the syncs do not change. Races are simulated independently (no form drift, no track types), which understates the spread, so the output says NOT CALIBRATED. |

Nothing here runs by default. **Back up the database before the first `ingest` on a real database, and before `link --apply`** ([Data changes](data-changes.md)).

## racinglines cycling

Road cycling sportsbook lines (winner, head-to-head) for time trials and road races, from ProCyclingStats results
on the timed-runs engine: `events`, `fetch itt|road`, `startlist <event>`, `price <event> [--calibrate]`. See
[Road cycling](road-cycling.md).

## racinglines f1 props: wet or dry and the DNF check

`racinglines f1 props --check --history <csv>` runs the walk-forward calibration of the yes/no props on a history CSV
(`props.history()`'s columns) with no database, scoring the red flag and safety car given wet or dry as well
(`climatology`, `wet_oracle`); `--dnf-check <csv>` scores the position simulation's `dnf_prob` against the
classification (`models/position_sim/dnf_check.py`). Both are read-only; see the decision log of 2026-10-06 in
[F1 roadmap](f1-roadmap.md#decision-log).

`--forecast <csv> [--lead N]` (the leads CSV of `racinglines weather leads`, e.g.
`tests/fixtures/weather/open_meteo-leads-f1.csv`, turned into a walk-forward `p_wet` per race by
`weather/wet.py`'s `p_wet_series`; lead 5 by default) adds the weather-aware variants to both: `climatology-WX` to
`--check` and `model-WX` to `--dnf-check`, each with its paired Brier difference against its base. Both read the
race history from `--history <csv>`, else the database. The forecast's own skill by lead is
`racinglines weather backtest`. See [F1: weather-aware (-WX) variants](f1.md#weather-aware-wx-variants).

## racinglines weather

Weather forecasts per event in one provider-agnostic frame: `probe --lat --lon [--out]`, `fetch <event_key> --lat
--lon [--session race=START/END]`, `show <event_key>`, `leads --out <csv> [--races <csv>]` (the forecasts issued 0 to 7
days before past races), `backtest [--lead 5] [--history <csv>] [--leads <csv>]` (the wet-race forecast against rain,
red flag, safety car and DNFs). `--provider open_meteo` (the default, no key, verified by
the probe of 2026-10-06) or `wunderground` (optional, unverified, a PWS owner's key). See
[Weather forecasts](weather.md).

| Variable | Default | Meaning |
|---|---|---|
| `WUNDERGROUND_API_KEY` | – | Weather Underground (The Weather Company API) key, a PWS owner's key; read by `weather probe` and `weather fetch` with `--provider wunderground` only. |

## racinglines db

Database commands. See [Database](database.md).

```
racinglines db [--db URL] init                     # alembic upgrade head + seed reference data
racinglines db [--db URL] seed                     # re-apply racinglines/db/registry.py
racinglines db [--db URL] stats                    # table counts + coverage per season and category
racinglines db [--db URL] export [--competition uci_dhi_wc] [--out splits.csv]
racinglines db [--db URL] snapshot-export          # model tables with ids -> data/archive/db/
racinglines db [--db URL] snapshot-import [--force]
racinglines db [--db URL] merge-athletes KEEP DROP [--dry-run]
racinglines db [--db URL] changes [--add TEXT] [--sport mtb_dh] [--limit 20]
```

| Command | What it does |
|---|---|
| `init` | Create or upgrade the schema to the latest migration (Alembic), then seed reference data. |
| `seed` | Upsert sports, leagues, competitions, categories and venues from `registry.py`. |
| `stats` | Row counts and coverage per season and category. |
| `export` | The tidy frame for a competition (same columns as `mtb_dh parse`'s CSV) to CSV. |
| `snapshot-export` | The tables the models read (race data and market links, with their ids) to `data/archive/db/<table>.parquet` plus `manifest.json`. Never web-app tables or model runs. |
| `snapshot-import` | Load that snapshot into a fresh database (schema already at head): an exact replica, same ids, so seeded prices are identical. Refuses a database that already holds model runs unless `--force`. See [Database](database.md#snapshot-an-exact-replica). |
| `merge-athletes` | Merge athlete `DROP` into `KEEP` (the same person, e.g. a name change that downhill ingest reports once files carry UCI IDs): every table referring to athletes moves to `KEEP`, then `DROP` is deleted. Refuses, changing nothing, if a row would collide (both in the same round). `--dry-run` only reports. It changes the downhill history the model sees, so it's the owner's call. Logged in the data change log. |
| `changes` | The [data change log](data-changes.md), newest first: every ingest that changed data, every merge, and notes (`--add "why"`). |

## racinglines f1

Formula 1. See [Formula 1](f1.md).

Group options go before the command:

| Option | Meaning |
|---|---|
| `--db URL` | Database URL (default: `$DATABASE_URL`, else the local one). |
| `--variant NAME` | Model variant from `racinglines/models/position_sim/variants.py`: `baseline` (default), `grid`, `gridq`, `pretrain`, `gbm`, `tail`, `reset`, or a combination such as `gridq+pretrain+reset`. Saved runs record it; the sweep and season strategy reuse only stored pricing from the same variant. The web app's live prices use baseline runs. |
| `--half-life DAYS` | Recency half-life of the pace models (default `position_sim.model.HALF_LIFE_DAYS`). |

### Data

```
racinglines f1 fetch [--years 2026,2025,…] [--sessions Q,S,R] [--rounds 6-15] [--sprints-from 2026] [--force]
racinglines f1 ingest [--years 2020-2026] [--force]
```

| Command | What it does |
|---|---|
| `fetch` | Download sessions from the F1 live-timing archive (FastF1) into `data/raw/f1/fastf1/<year>/`, newest seasons first (default `--years` 2026 back to 2020). `--sessions` takes `Q,S,R` (default) and/or practice `FP1,FP2,FP3,SQ`; `--rounds` limits to some rounds. `--sprints-from YEAR` fetches sprint races from that season on (default 2026). Sessions already on disk are skipped (`--force` re-downloads). Waits out FastF1's 500 calls/hour limit. Saves each season's schedule (`schedule.parquet`). |
| `ingest` | Load `data/raw/f1/fastf1/` into the database: events, results, laps, track profiles. Unchanged events are skipped (`--force` reloads). |

### Pricing and evaluation

```
racinglines f1 [--variant NAME] [--half-life DAYS] backtest [--start-year 2021] [--races N] [--track both|on|off] [--no-track] [--sims 4000] [--out CSV] [--save]
racinglines f1 compare BASELINE_RUN CHALLENGER_RUN [--reliability]
racinglines f1 matrix [--variants baseline,grid,gridq,pretrain,gbm,tail,gridq+pretrain] [--year 2026] [--out MD]
racinglines f1 [--half-life DAYS] diagnostic --event 2026-15 --cutoff 2026-09-25T13:30 [--sims 10000] [--no-track] [--save]
racinglines f1 [--half-life DAYS] forecast [--year 2026] [--sims 10000] [--no-track] [--save [--scenario LABEL]] [--top 10]
racinglines f1 props EVENT [--run STAGE_RUN] [--prior-n 16]  |  racinglines f1 props --check [--from 2022]
racinglines f1 [--variant NAME] scorecard --event 2026-15 [--venue polymarket|kalshi|both] [--model-key KEY] [--out DIR]
racinglines f1 [--variant NAME] scorecard --all --year 2025 [--rounds 1-12] [--venue polymarket|kalshi|both]
```

| Command | What it does |
|---|---|
| `backtest` | Walk-forward over races from `--start-year`, both before qualifying (grid simulated) and after (real grid), with track features on and off (`--track on` / `--track off`, or `--no-track`, for one). Writes one row per race and mode to `data/runs/f1/backtests/` (`--out`); `--save` stores `kind='backtest'`. `--races N` runs only the last N races. |
| `compare` | Pair two saved backtest runs by race: challenger − baseline ± 2 standard errors per metric and pricing stage. `--reliability` adds calibration bins and the calibration error (runs saved since 2026-09-27 keep each driver's probabilities). |
| `matrix` | The model × strategy matrix: for each variant, the latest saved backtest (accuracy, marked where it differs from baseline beyond 2 SE) and the latest saved sweep and season strategy (P&L). Writes `data/runs/f1/matrix.md`. See [Model × strategy matrix](market-making.md#model-strategy-matrix). |
| `diagnostic` | Price one past event as of `--cutoff` (UTC), with a leakage audit. `--save` stores `kind='diagnostic'`. See [Market making](market-making.md). |
| `forecast` | Live: cutoff = now; upcoming races and the championships. `--save` creates scheduled events for upcoming rounds and stores `kind='forecast'` (the only kind the web app uses for live fair prices). `--scenario LABEL` saves `kind='scenario'` instead, ignored by live prices until promoted in the web app's Lab. |
| `scorecard` | The pricing scorecard of an exchange weekend, traded or not ([Paper trading](paper-trading.md#validation-plan), rule 2): at every stage cutoff (before any running, after each session), the stored stage runs' fair values for every linked market kind scored against the result and against the venue's mid at that cutoff (Brier and log loss; `n` markets, and `paired` where the venue also priced it). `--venue both` runs Polymarket and Kalshi; `--all --year` every raced weekend of a season, per weekend and pooled per kind and stage. Nothing is priced or stored: the stages must have been priced by `f1 sweep` or `f1 signals` with the same model settings (`--variant`, or `--model-key`). Writes `data/runs/f1/scorecard/<event>_<venue>.md` / `.csv` / `_markets.csv` (or `<year>_<venue>…`). See [F1 evaluation](f1-evaluation.md#the-weekend-scorecard). |
| `props` | Race props for one event from the race history before it: safety car, red flag, rain (per-circuit rates shrunk to the field rate); `--run` adds fastest-lap prices from a stored stage run's finishing odds. `--check` scores the yes/no props walk-forward from `--from` against the field rate and a coin flip. Nothing is stored. See [F1 live test](f1-live-roadmap.md#props-opt-in). |

### Trading research

```
racinglines f1 [--variant NAME] sweep [--year 2026] [--rounds 1-15] [--no-fetch | --fetch-only] [--reprice] [--reliability] [--save] [SETTINGS …]
racinglines f1 season-strategy [--venue {polymarket,kalshi,og}] [--year 2026] [--sims 5000] [--no-fetch] [--reforecast] [--min-edge 0.03] [--stake-per-edge 500] [--max-stake 150] [--capital 1500] [--save]
racinglines f1 season-strategy --paper --venue {polymarket,kalshi} [--after-round N] [--user maker] [--no-fetch] [--save] [SIZING …]
racinglines f1 season-checkpoints [--variants V1,V2] [--year 2026] [--entries 0,3,6] [--window 3] [--sims 5000] [--out MD] [--save]
racinglines f1 replay --runs 11,12,9 [--sweep]
racinglines f1 search QUEUE.toml [--leaderboard]
racinglines f1 search-report QUEUE.toml
racinglines f1 search-import RESULTS.json
```

| Command | What it does |
|---|---|
| `sweep` | Trade every raced weekend of a season: price before any running and after each session, trade Polymarket, settle. Runs four taker modes (`update`, `hold`, `last`, `early`) and five maker settings side by side. See [Market making](market-making.md#season-sweep). Downloads the season's missing Polymarket history and trades first unless `--no-fetch`; `--fetch-only` only downloads (e.g. a past season). Stages are reused only when priced with the same model settings from the same data; `--reprice` prices them again. `--reliability` also scores calibration: our fair values and Polymarket's prices at every tradeable stage, per market kind and stage (Brier, log loss, ECE) and in reliability bins, written to `sweep_<year>_calibration.csv` / `_reliability.csv` (and saved with the run). `--save` stores `kind='sweep'`. `--venue kalshi` (the `venue` setting) trades Kalshi's markets instead: its `exchange='kalshi'` links, one market per ticker, its tape per market from `data/archive/markets/kalshi/` and the shared tables (nothing is downloaded), and Kalshi's maker fee ([Kalshi history](kalshi-history.md#in-the-signal-engine)). `--grid FILE.json` sweeps several settings in one process (a JSON list of `{"job": id, "settings": {...}}`; the search uses it), sharing what doesn't depend on the strategy; each result and saved run is the same as its own `sweep`. |
| `season-strategy` | The championship-market strategy through the season: as-of season forecasts pre-season and after every race, trades at Polymarket's recorded prices (plus spread and slippage), settles eliminated markets, marks the rest. `--reforecast` recomputes the cached forecasts. `--venue kalshi` or `--venue og` replays the same strategy on that exchange's stored tape instead (no fetch; Kalshi costed at its taker fee, OG.com at its flat $0.02 per contract with no volume floor and prices read as its replay venue reads them, an empty book's 0.50 dropped); Polymarket stays the default and its output is unchanged, and `--save` stores another venue's replay as kind `season_venue_replay` so no page reads it as Polymarket's. **`--paper`** is the championship sleeve (paper only, off unless given): replay through the decision after `--after-round` (default: the last raced round) on `--venue` (Polymarket's championship markets, or Kalshi's `KXF1` / `KXF1CONSTRUCTORS` champion markets by ticker, costed at the taker fee) and store that rebalance as the demo maker's (`--user`) paper positions under venue `season:<venue>`, event `<year>-season`, replacing the previous store on that venue; the weekend records of A, C and K never read that venue. `--save` also stores the rebalance as a run of kind `season_sleeve`. See [Paper trading](paper-trading.md#validation-plan). |
| `season-checkpoints` | Championship markets entered at fixed points (pre-season, after 3 and after 6 grands prix; `--entries`) and held, one $500 book each, per model variant (`--variants`). Scores each entry over the next 3 GPs (`--window`) and to date: P&L, how far the market moved toward our fair value, and the share of our edge it closed. Writes `data/runs/f1/season_checkpoints.md`; `--save` stores kind `season_checkpoints`. See [Checkpoint entries](market-making.md#checkpoint-entries). |
| `replay` | Replay a maker quoting Polymarket through an event's diagnostic runs (ids in time order), with both fill rules, against the real trade tape. `--sweep` adds the half-spread and fill-rule sensitivity table. |
| `search QUEUE.toml` | Run a queue of season sweeps in parallel (`[search] parallel`, `hours`), each saved as a sweep run. The queue file (e.g. `sweeps/poc.toml`, `sweeps/params-4h.toml`) is re-read whenever a slot frees, so pending `[[job]]` entries can be edited while it runs. A job with `venue = "kalshi"` runs `sweep --venue kalshi` (the makers on Kalshi's tape) and gets its own baseline on that venue; its id and title carry the venue, and a `[[candidate]]` may carry it too (e.g. `sweeps/kalshi-maker-k.toml`). `[search] grid = N` runs up to N sweeps of the same season and model in one process (`sweep --grid`: the measurements, stage pricings, markets and maker tape are read once; every saved run is what its own process would save), and `history_cache = true` keeps rating histories in `data/cache/history/`; `parallel` defaults to every core. Writes `data/runs/search/<name>/` (`leaderboard.md`, `results.json`, `state.json`, logs). `--leaderboard` only rewrites the leaderboard from `state.json`. See [Cloud sweeps](cloud-sweep.md). |
| `search-report QUEUE.toml` | Analyse a search's finished sweeps with the checks in [Backtest core](backtest-core.md#the-search-report): labels against the baseline in the target and held-out seasons beyond a noise floor (from seed replicates when the search ran them), same-fidelity baselines, confirmation at more simulations, P&L without the best event and without the best two, a shape label describing the record, not the risk (steady: still up without its best two events in every season; concentrated: up in every season but not without its best two in one; mixed: up in one season, down in another; losing: down in every season), and candidates with stable ids (`<strategy>-<settings_key>`). An optional `[report]` table in the queue sets `target`, `holdout`, `confirm_sims`, `rank_sims` (the simulation count combos are ranked at; default the settings' 4,000), `top`, `noise`. Writes `stats.csv`, `ranking.csv`, `pnl_curves.json`, `candidates/`, `candidates.toml` and `report.md` next to `state.json`. |
| `search-import RESULTS.json` | Load a search's sweep runs (e.g. from a cloud session) into this database, marked with `params.source`. |

**Sweep settings.** Every setting of the schema in
`racinglines/pipelines/sweep_settings.py` is a `sweep` flag; the same schema drives the
Lab's Edge Finder form, search queues and each saved sweep's params. Defaults are the
baseline. The model variant is the group's `--variant`.

| Group | Flag | Default | Meaning |
|---|---|---|---|
| Model | `--sims` | 4000 | Simulations per stage. |
| | `--half-life-days` | 120 | Recency half-life of the pace models. |
| | `--track-features` | true | Match each car's fast-vs-slow sector profile to the track. |
| | `--practice-prior` | true | Use this weekend's practice laps once they exist. |
| | `--ridge-team` | 2.0 | Team pace shrinkage (events). |
| | `--ridge-slope` | 6.0 | Track-slope shrinkage (events). |
| | `--driver-prior-n` | 3.0 | Races before a driver's gap to the teammate is trusted. |
| | `--teammate-corr` | true | Teammates share noise. |
| | `--finish-rho-scale` | 1.0 | Teammate finish correlation scale. |
| | `--reset-weight` | 0.25 | With the `reset` variant: weight of earlier seasons' car data. |
| | `--seed` | not set | Monte Carlo seed. Unset = today's fixed seed (42), the same prices and cache keys. Different seeds give independent noise draws, e.g. to check a search's winner isn't one lucky draw. |
| Timing | `--taker-stages` | every stage (`pre-weekend` … `after Quali`) | Stages takers may trade (every taker mode). |
| | `--late-stages` | `after FP3,after Quali` | Stages the stage-aware taker skips. |
| Taker | `--min-edge` | 0.05 | Min edge to act (probability). |
| | `--min-edge-h2h` | not set | Min edge for head-to-head markets; unset = `--min-edge`. |
| | `--min-edge-by-kind` | not set | Per market kind, e.g. `race_h2h=0.05,race_podium=0.08`; each overrides `--min-edge` (and `--min-edge-h2h`) for its kind. |
| | `--stake-per-edge` | 250 | Target cost = this × edge ($). |
| | `--max-stake` | 50 | Max stake per market ($). |
| | `--cost` | 0.01 | Cost per share per trade ($). |
| | `--bankroll` | not set | Bankroll-aware sizing: each taker mode starts with this bankroll, and its stakes scale with its balance after earlier weekends (`balance / bankroll`, 0 once it's gone). Unset = fixed sizing. |
| | `--kelly` | not set | Kelly sizing (needs `--bankroll`): a taker's stake in a market is this fraction × the Kelly fraction × its current balance, where the Kelly fraction is `(q − c) / (1 − c)` for a contract costing `c` (price plus cost, at the touch where there's a quote) that wins with probability `q`. Still capped at `--max-stake` × the bankroll scale per market and at `--max-deployed` per weekend. 0.5 = half Kelly. Unset = linear sizing. |
| | `--thin-edge-mult` | not set | Trade a market under the volume floor when the edge is at least this many times the minimum edge and a recorded order book (at most 10 min old) shows size at the touch: buys only, stake capped at that size. Needs recorded books (`markets record`); without them nothing changes. Unset = thin markets are skipped. |
| | `--max-deployed` | not set | Cap on the capital deployed across a weekend's markets ($). Markets are traded in time order; a buy over the cap is cut to fit. Unset = no cap. |
| Maker | `--half-spread` | 0.02 | Quote half-spread ($). |
| | `--size` | 50 | Shares per quote. |
| | `--max-pos` | 250 | Max inventory per market (shares). |
| | `--skew` | 1.0 | Inventory skew. |
| | `--max-disagree` | 0.15 | Don't quote beyond \|fair − market\|. |
| | `--maker-min-volume-24h` | not set | The maker's own per-market filter: min $ traded in the prior 24 h before quoting a market. Unset = the replay's $100 (`--min-volume-24h` is the takers' filter). |
| | `--fill` | `through` | `through`: a trade must cross our price; `touch`: at our price; `queue`: at our price once the recorded book's queue ahead of us is served ([queue rule](market-making.md#the-queue-rule)). |
| | `--info-skew` | 2.0 | Info-timed skew (`maker_skew`, `maker_all`). |
| | `--widen` | 1.5 | Widen factor on bad markouts (`maker_widen`, `maker_all`). |
| Markets | `--market-kinds` | `race_win,race_podium,race_h2h,race_constructor_top,race_pole` | Market kinds traded. `race_top10` (Kalshi's top-10 finishers, a group of ten for the coherence check) can be added; it is not in the default set and only the takers trade it. |
| | `--coherence-tol-by-kind` | not set | `kind=tolerance` pairs, e.g. `race_podium=0.35`: how far a multi-outcome group's prices may sum from its target (as a share of it) before its markets are skipped. Unset = 0.25 for every kind. |
| | `--min-volume-24h` | 50 | Min $ traded in the prior 24 h. |
| | `--venue` | not set | `polymarket` (the default) or `kalshi`: whose links and recorded tape the strategies trade. Unset = Polymarket, and unset or `polymarket` leaves every settings key as it was. A profile with this setting paper-trades Kalshi in the signal engine. |

### Paper signals and strategy profiles

```
racinglines f1 profiles [--assign-demo] [--venue kalshi]
racinglines f1 signals [--profile A|C|ID|NAME] [--user NAME ...] [--event next|ROUND|YEAR-ROUND] [--asof UTC] [--no-fetch] [--no-alert]
racinglines f1 demo-history [--reset] [--user maker taker] [--venue kalshi]
racinglines f1 reconcile --event YEAR-ROUND --profile A|C|ID|NAME [--venue polymarket|kalshi] [--user NAME] [--replicates N] [--no-price] [--asof UTC] [--markdown]
```

| Command | What it does |
|---|---|
| `profiles` | List the strategy profiles, creating A (core taker), C (maker sleeve) and K (Kalshi maker, [Kalshi history](kalshi-history.md#profile-k)) as Lab candidates if missing, and show which users run which. `--assign-demo` assigns the demo taker A and the demo maker C (`users.prefs["strategy_profile"]`, with the demo bankrolls). `--assign-demo --venue kalshi` assigns the demo maker K as its Kalshi profile only (`users.prefs["strategy_profile_kalshi"]`, with `venue = "kalshi"`), leaving the Polymarket profiles alone; nothing reads that key until the signal engine runs Kalshi, so it changes nothing live. `racinglines/pipelines/profiles.py`. |
| `signals` | Live paper signals of every user with a profile, for the weekend in progress (`racinglines/pipelines/signals.py`): refresh FastF1 and Polymarket data (skip with `--no-fetch`), price each stage whose session is in, run the profile's strategy with the backtest's code, store `strategy_signals` and `paper_positions`, and alert (skip with `--no-alert`). Recommendations only: never places an order. `--profile` runs one profile instead of each user's own; `--user` limits the users; `--event` picks the weekend (default the next). `--asof UTC` replays at that time and only prints (markets read at each stage's cutoff, like the sweep). A profile whose settings say `venue = kalshi` trades Kalshi's markets (its links, tape and maker fee; signals and positions tagged `kalshi`); there is no flag for it, the profile setting is the switch. See [Paper trading](paper-trading.md#the-signal-engine). |
| `reconcile` | One account's live paper weekend against the backtest's replay of it ([Paper trading](paper-trading.md#validation-plan), rule 1; `racinglines/pipelines/reconcile.py`): the `strategy_signals` and `paper_positions` the signal engine stored for the profile's account (`--user`, default its demo account) on that weekend and venue, against `signals.compute` replayed as of a day after the race on the recorded tape with the maker's "through" fill rule. Prints fills, notional, 60-minute markouts (from the same tape, for both sides) and P&L to resolution, live and replay, per stage, with the verdict: fills and markouts within ±25% of the replay's, P&L inside the replay's noise band, the range of the weekend's P&L over seed replicates (the profile's seed plus `--replicates` more, default 2: seeds 43 and 44, whose stage pricings are cached as diagnostic runs exactly like a sweep's), at least ±31 (taker) / ±71 (maker) wide. `--no-price` is read-only on the database (cached seeds only). The replay's signals are compared as `signals.store` keeps them (one row per market, timestamp, action and side: maker fills sharing a second on Kalshi's tape collapse into one, and the output says how many). A weekend whose rows are the backfilled replay is a self-check and must match exactly. `--markdown` adds the block for the weekend report. Exit 1 when flagged, 2 when the account has no rows for the weekend. Never writes a signal or a position. |
| `demo-history` | Backfill the demo accounts' track record: every past weekend with Polymarket race markets, replayed with the profile each account ran then, stored as paper signals and positions flagged as backtest replays (`racinglines/pipelines/demo_history.py`). Idempotent; `--reset` deletes the backfill first; `--user` limits it to `maker` or `taker`. `--venue kalshi` replays the maker's profiles on Kalshi's recorded tape instead, with Kalshi's maker fee, stored apart as venue `kalshi` ([Kalshi history](kalshi-history.md)); off by default. |

## racinglines markets

Exchange data (Polymarket; F1 is the only sport listed). `racinglines markets CMD`
is the same as `racinglines f1 pm-CMD`; group options are `--exchange polymarket`
and `--sport f1` (the defaults) and `--db URL`.

```
racinglines markets sync [--year 2026] [--closed] [--alert]
racinglines markets history --events 'f1-azerbaijan-grand-prix%' --start 2026-09-22T00:00 --end 2026-09-26T12:00 [--fidelity 60]
racinglines markets trades --events 'f1-azerbaijan-grand-prix%'
racinglines markets record [--events …] [--interval 60] [--minutes 0] [--sync-every 30] [--no-alerts] [--year 2026]
racinglines markets archive [--stats] [--vacuum-full] [--compact] [--hours H]
racinglines markets disagree --event 2026-15 | --event season [--year 2026] [--start … --end …] [--step 60] [--no-save]
racinglines f1 pm-links-export [--exchange kalshi]
racinglines f1 pm-links-import [--exchange kalshi]
```

| Command | What it does |
|---|---|
| `sync` (`f1 pm-sync`) | Sync Polymarket's F1 events of `--year` into `market_links` (live prices, resolutions). `--closed` adds every closed event of that year (e.g. a past season). `--alert` notifies about markets seen for the first time (`market_links.first_seen_at`). |
| `history` (`f1 pm-history`) | Store price history for events (slugs, or a prefix ending in `%`) between `--start` and `--end` (UTC). `--fidelity` is minutes per point (default 60; 1 = minute-level). |
| `trades` (`f1 pm-trades`) | Store every taker trade for events (the tape the maker replay fills against). |
| `record` (`f1 pm-record`) | Record order-book snapshots every `--interval` seconds (default 60) of the given events, or of the open markets of races not yet run. Runs until stopped (`--minutes N` stops after N). Re-syncs Polymarket's F1 events every `--sync-every` minutes (default 30; 0 = never) so new race markets get recorded, and alerts about new markets unless `--no-alerts`. Archives to Parquet hourly. Run it through race weekends. |
| `archive` (`f1 pm-archive`) | Move stale prices, trades and books from Postgres to Parquet under the retention policy, or every row older than `--hours H`. `--vacuum-full` returns freed space to the OS, `--compact` merges each month into one file, `--stats` only shows where the rows are. See [Database](database.md#storage-postgres-for-the-app-parquet-for-heavy-history). |
| `disagree` | The cross-venue disagreement log ([Kalshi history](kalshi-history.md#cross-venue-disagreement-log)): for every outcome of a race weekend (`--event 2026-15`, or a round number of `--year`) or of the season's drivers' and constructors' champion markets (`--event season`) that is linked on both Polymarket and Kalshi, one row per `--step` minutes (default 60) with both mids and tops of book, our fair from the run in force, each venue's fee-adjusted taker edge and the cross-venue gap net of both taker fees, upserted into `market_disagreements` (`--no-save`: report only) and printed day by day. The window defaults to where both venues have stored prices, and for a race ends at its start. Reads the archived prices, books and tapes, so it needs no exchange access. |
| `f1 pm-links-export` | Write `market_links` to `data/archive/markets/polymarket/links/market_links.parquet`, with database ids swapped for stable keys (event key and category, FastF1 driver id, competition and category codes). |
| `f1 pm-links-import` | Load that file into this database (no Polymarket access needed); replaces each token's row and reports rows whose keys don't resolve. `--exchange kalshi` does the same for Kalshi's links (`data/archive/markets/kalshi/links/`). |

### Kalshi (`--exchange kalshi`)

Built from Kalshi's public API docs, then run against the live read-only API on 2026-09-28 (sync with
`--closed`, trades, history and books; no order has been sent). Nothing runs unless you call it.
Markets settled before Kalshi's historical cutoff (about two months back) are read from its `/historical`
endpoints: settled events' markets, their trades and their candlesticks.

```
racinglines markets --exchange kalshi sync [--year 2026] [--closed] [--series TICKER …]
racinglines markets --exchange kalshi trades --events KXF1RACE-AZEGP26
racinglines markets --exchange kalshi history --events KXF1RACE-AZEGP26 --start 2026-09-24T00:00 --end 2026-09-27T00:00 [--period 60]
racinglines markets --exchange kalshi history --start 2025-01-01 --end 2026-10-05 --save-raw data/raw/kalshi/candles-2025-2026   # + raw responses
racinglines markets --exchange kalshi history --start 2025-01-01 --end 2026-10-05 --from-raw data/raw/kalshi/candles-2025-2026   # re-import, no network
racinglines markets --exchange kalshi books --events KXF1-26
racinglines markets --exchange kalshi --sport nascar sync [--closed]        # NASCAR Cup: KXNASCAR* series, links unmodeled
racinglines markets --exchange kalshi --sport nascar trades                 # every NASCAR event's tape (no --events needed)
racinglines markets --exchange kalshi --sport motogp books                  # one snapshot per open MotoGP market
racinglines markets --exchange kalshi --sport road_cycling sync --closed    # UCI road: KXCYCLING* series, incl. settled grand tours
racinglines markets --sport nascar sync [--tags nascar]                     # the same sport's Polymarket markets (tape only)
racinglines markets --sport nascar trades                                   # trades / history / books work the same way
```

| Command | What it does |
|---|---|
| `sync` | Find Kalshi's F1 series (Sports series whose ticker starts `KXF1` or whose title says Formula 1, F1 or Grand Prix, or `kalshi.sync.SERIES`; `--series TICKER …` names them instead), and upsert one `market_links` row per market (`exchange='kalshi'`, `token_id` = the market ticker's YES contract, `condition_id` = the event ticker), classified into the model's kinds: win, podium, top 10, pole, top constructor, fastest lap, head-to-head (the race read from the ticker's code, `BRIGP26`), champions. The sprint winner and sprint pole (`KXF1RACESPRINT`, `KXF1SPRINTPOLE`) classify as `race_sprint_win` / `race_sprint_pole` and get a model price ([F1](f1.md#kalshi-alignment)); `RACINGLINES_KALSHI_SPRINTS=0` lists them as unmodeled instead. The sprint's top 5, top 10, fastest lap and top constructor stay unmodeled. Each row keeps Kalshi's resolution rules (`params.rules`). `--closed` adds settled events. Races resolve within `--year` (2026: 15 weekends, 1,847 modeled links on 2026-09-28). |
| `trades` | Store every trade on those events' markets in `market_trades` (the taker's side of YES, at the YES price, in contracts). |
| `history` | Store candlesticks (`--period` 1, 60 or 1440 minutes) in `market_price_history`. |
| `books` | One order-book snapshot per open market in `market_book_snapshots` (a NO bid at p is a YES ask at 1 − p). |

`--sport nascar` / `motogp` / `indycar` / `road_cycling` / `le_mans` / `sailgp` (before the command) switches the sync to a **tape-only sport**: Kalshi's
NASCAR Cup (`KXNASCAR*`: race winners and the champion), MotoGP (`KXMOTOGP*`) or IndyCar (`KXINDYCAR*`) series,
filed under the sport's own competition (`sports/<code>.toml`, no model) with every link `unmodeled`. Off by
default: without `--sport`, `sync` is the F1 sync above and touches nothing else. For any sport, `trades`,
`history` and `books` without `--events` take every Kalshi event of that sport's competition (books: its open
markets), so recording a series from listing to settlement is `sync --closed`, `trades` and `books` per pass.
On Polymarket (`markets --sport nascar|motogp|indycar sync`, no `--exchange`) the same sports are recorded from the Gamma tags in `[markets.polymarket] tags`; the slugs are unverified against the live API and `--tags SLUG …` overrides them. The Polymarket path is additive: it upserts by token id and has no reset or delete. The series prefixes come from `[markets.kalshi] series` in the schema and were not checked against the live
listing (the cloud can't reach Kalshi): `sync --series TICKER …` syncs exact tickers.
[Data](data.md#other-series-tapes-nascar-motogp-indycar-road-cycling-le-mans-sailgp).

**The recorder unit is not changed.** `racinglines-recorder` (`deploy/vm/systemd/racinglines-recorder.service`,
`scripts/deploy/vm.sh`) still runs `markets record --interval 60`: Polymarket's F1 books, plus the hourly archive
pass that also files Kalshi's rows. There is no Kalshi `record`. To record NASCAR or MotoGP on the VM, add a
timer of your own next to `racinglines-signals.timer`, e.g. `racinglines-tapes.service` with
`ExecStart=/bin/sh -c 'for s in nascar motogp; do racinglines markets --exchange kalshi --sport $s sync --closed
&& racinglines markets --exchange kalshi --sport $s trades && racinglines markets --exchange kalshi --sport $s books; done'`
(same `User`, `WorkingDirectory` and `EnvironmentFile` as the recorder) and a `racinglines-tapes.timer` with
`OnCalendar=*:0/5` (books every 5 min; trades are deduplicated, so re-pulling them is safe), then
`vm.sh deploy` installs whatever is in `deploy/vm/systemd/`. `history --period 60` once after settlement fills
the candle series.
With `RACINGLINES_DISAGREE=1`, `markets record` also writes one tick of the disagreement log on every pass
(`disagree.record`), from the latest stored prices and books of every open race listed on both venues and of the
season's champion markets; the Markets page then shows the log's latest tick ([Web app](webapp.md#kalshi)).

`markets archive` (and the recorder's hourly pass) archives Kalshi's rows too, into `data/archive/markets/kalshi/`
([Data](data.md#exchange-history-kalshi-and-polymarket)). No `record` or links export for Kalshi yet. Pulling a season: `sync --year Y --closed`,
then `trades` and `history --period 60` per modeled event ticker, from each market's `open_time` to its `close_time`.

Orders (`markets/kalshi/trade.py`): post-only limit orders on YES, checked against the book, the 1-cent grid
and `KALSHI_MAX_ORDER_USD` (default 25), signed with RSA-PSS (`KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`),
and sent only when `KALSHI_TRADING_ENABLED=true`; otherwise a dry run that returns the request. No CLI.

### OG.com and other schema exchanges (`--exchange og`)

An exchange defined by a file in `exchanges/` goes through one generic driver
(`markets/exchange_driver.py`); the commands and the fair-price indicator are in [Exchanges](exchanges.md).

```
racinglines markets --exchange og [--sport f1|nascar|sailgp] sync | trades | history --start UTC [--end UTC] | books | fair
racinglines markets --exchange og [--sport f1|nascar|sailgp] settle [--since UTC] [--max-pages N]
racinglines markets --exchange og --sport f1|nascar|sailgp buy-all [--cost 0.01] [--fee USD] [--out FILE.csv]   # debug
```

`settle` writes the outcomes of the sport's closed, unresolved links from the exchange's settlement feed
(`[endpoints.settlements]` in its schema; OG.com's `get-expired-settlement-price`, since its listing drops a settled
instrument): `resolved_yes`, plus `params.settled_at`; a void (a 0.50 settlement) is noted in `params.settlement` and
left unresolved. Bounded (`--max-pages`, default the schema's 500) and resumed where the last pass stopped; a schema
with no feed does nothing. The VM recorder runs it hourly on race weekends
([Exchanges](exchanges.md#outcomes-the-settlement-feed)).

OG.com is also a **replay venue**: `racinglines nascar replay --venue og` (and `--venue all`, where `exchanges/og.toml`
lists the sport) and `f1 season-strategy --venue og` read its stored minute prices, trades and book quotes whatever their
spread or depth, dropping a stored 0.50 as an empty book's midpoint, at the schema's flat fee per contract
($0.02, unverified).

`buy-all` (read-only) buys one YES and one NO of every market the exchange lists for the sport, modeled or not, at the
first price stored, holds the pair and settles or marks it ([Exchanges](exchanges.md#debug-buy-one-of-everything)).
**It is an operator's plumbing check, not a result:** a pair loses exactly its costs and fees, so the P&L only shows
that each market was found, priced and valued. It is never shown in the web app or in reporting, and it never counts as a
backtest. The same holds for the race replays' `--buy-all` / `RACINGLINES_BUY_ALL=1` mode above.

**Alert channels** (`racinglines/markets/alerts.py`, used by new-market alerts and by
`signals`): a macOS notification, one JSON line per event in
`data/runs/alerts/new_markets.jsonl`, plus these when set:

| Variable | Meaning |
|---|---|
| `RACINGLINES_NTFY_TOPIC` | Phone push via ntfy.sh on this topic (sends market titles to ntfy's public server: pick an unguessable name). |
| `ALERT_WEBHOOK_URL` | JSON POST (Slack and Discord incoming webhooks work). |
| `RACINGLINES_URL` | Link in notifications (default `https://racinglines.bet`). |

### Running the recorder persistently

Polymarket has no historical order-book API, so `markets record` must run
continuously, and `f1 signals` runs every few minutes through race weekends. On
macOS both run as LaunchAgents; the plists are in `scripts/` (paths inside are
this machine's repo path: edit them for another checkout).

| Agent | Runs | Schedule | Log |
|---|---|---|---|
| `scripts/bet.racinglines.recorder.plist` (`bet.racinglines.recorder`) | `racinglines markets record --interval 60` | at login, restarted if it exits (`KeepAlive`) | `data/runs/logs/record.log` |
| `scripts/bet.racinglines.signals.plist` (`bet.racinglines.signals`) | `racinglines f1 signals` | at login and every 300 s (`StartInterval`); outside a race weekend each run only notes when signals start | `data/runs/logs/signals.log` |

```
cp scripts/bet.racinglines.recorder.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/bet.racinglines.recorder.plist   # install + start
launchctl print gui/$(id -u)/bet.racinglines.recorder | grep -E 'state|pid'               # status
launchctl bootout gui/$(id -u)/bet.racinglines.recorder                                  # stop + remove
tail -f data/runs/logs/record.log
```

The same with `bet.racinglines.signals`.

## racinglines web

The web app. See [Web app & trading](webapp.md).

```
ADMIN_USERNAME=admin ADMIN_PASSWORD=... racinglines web          # http://127.0.0.1:8000
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000     # optional public HTTPS URL
```

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / random, printed at start | Login for every page (sign-in page or HTTP Basic). |
| `APP_SECRET` | random per start | Signs session cookies and CSRF tokens. Set it to keep sessions across restarts. |
| `WEB_HOST` / `WEB_PORT` | `127.0.0.1` / `8000` | Listen address. |
| `WEB_RELOAD` | off | `1` = auto-reload on code changes (development). |
| `DATABASE_URL` | local DB on port 5433 | Database connection. |
| `POLYMARKET_*` | – | Exchange credentials and limits; see [Web app & trading](webapp.md#polymarket). |

## racinglines mcp

The MCP server: the app's data and simulations for a chat client (Claude Desktop, Claude Code, any MCP
client). See [MCP server](mcp.md).

```
racinglines mcp                                    # stdio: the client launches it as a subprocess
racinglines mcp --http                             # streamable HTTP on 127.0.0.1:8100/mcp; each request needs an account's token
racinglines mcp token admin [--revoke]             # issue (printed once) or revoke an account's token; `token` alone lists holders
```

| Option | Meaning |
|---|---|
| `--db URL` | Database URL (default `$DATABASE_URL`, else the local one). |
| `--http` | Serve streamable HTTP instead of stdio. Every request must carry a bearer token of an active, non-demo account whose role is in `RACINGLINES_MCP_ROLES` (default `admin`): one from OAuth sign-in (signed with `APP_SECRET`; [MCP server](mcp.md#hosted-the-vm)) or an `rl_` token. |
| `--host` / `--port` | Listen address in `--http` mode (default `127.0.0.1` / `8100`). |
| `--no-jobs` | Don't run the Lab's job worker in this process: queued jobs wait for the web app's worker. |

## racinglines check

Quick validation for new setups: the pipelines on synthetic data, one tiny request
to each data source, and the database. `--sport f1|mtb_dh` (default both),
`--offline` skips the endpoints, `--no-db` the database. See [Testing](testing.md).

## Scripts

| Script | What it does |
|---|---|
| `scripts/fetch_test_fixtures.py [--f1] [--mtb]` | Build the regression-test fixtures from the public sources. See [Testing](testing.md#fixtures-built-locally-from-the-public-sources). |
| `scripts/signals_parity.py [--profile A] [--year 2026] [--round 15] [--reprice] [--venue kalshi]` | Parity check: `f1 signals` replayed at a past race's start must give the same taker trades (market, stage, side, shares, price) as `f1 sweep --rounds N --no-fetch` with the profile's settings; a maker profile (replayed settled, a day after the race) must match the sweep's maker on fills and settled P&L, and `demo-history`'s stored record for the weekend when there is one. `--venue kalshi` gives the profile the `venue = kalshi` setting on both sides. Exit 1 on a difference. |
| `scripts/cloud/prepare.sh` | Before a cloud sweep: move every market row from Postgres to the Parquet archive, `db snapshot-export`, `f1 pm-links-export`, and run the no-data-in-git guard. Then commit and push. |
| `scripts/cloud/start.sh` | Bring up racinglines on a fresh Linux machine (a cloud session): `.venv` with Python 3.14, Postgres, `db init`, then `db snapshot-import` (or, without a snapshot, `f1 ingest` and `pm-links-import` / `pm-sync`), then `check --offline`. `SKIP_SYSTEM=1` runs only the database steps. See [Cloud sweeps](cloud-sweep.md). |
| `scripts/hooks/pre-push` | Git hook: README in sync, `mkdocs build --strict`, no data in git. See [Testing](testing.md#pre-push-hook). |
| `scripts/build_readme.py` | See below. |

## Docs

```
pip install -r requirements-docs.txt
mkdocs serve     # http://127.0.0.1:8000, rebuilds live while you edit
mkdocs build     # static site in site/
```

See `requirements-docs.txt` for a workaround if `watchdog` fails to install on Python 3.14.

## scripts/build_readme.py

Parts of `README.md` are generated from sections of the docs, so the two can't drift
apart. The docs are the source of truth.

**1. Tag a section in any `docs/*.md` page.** HTML comments are invisible in both
MkDocs and GitHub:

```
<!-- readme: quickstart -->
...any markdown...
<!-- /readme -->
```

Tag names must be unique across all docs pages.

**2. Include it in `README.md`:**

```
<!-- include: quickstart -->
<!-- /include -->
```

Everything between the include markers is replaced on each build, so edit the docs,
not the README. Text outside include blocks (title, section headings, anything
README-only) is left alone. Options go after the name: `shift=N` demotes headings
inside the section by N levels (negative promotes).

**3. Build:**

```
python scripts/build_readme.py            # rewrite README.md
python scripts/build_readme.py --check    # exit 1 if README.md is stale (the pre-push hook runs it)
python scripts/build_readme.py --list     # tagged sections, and whether the README uses each
```

Conversions while copying:

| In docs | In README |
|---|---|
| `[x](todo.md#points-validation)` | `[x](docs/todo.md#points-validation)` |
| `[x](#some-heading)` (same page) | `[x](docs/<page>.md#some-heading)` |
| `!!! warning "Title"` + indented body | `> ⚠️ **Title**` blockquote |

Sections currently tagged (`--list`):

| Tag | Page |
|---|---|
| `tagline`, `glance`, `quickstart`, `overview`, `results-map`, `layers`, `docs-build`, `repo-layout`, `points-warning` | index.md |
| `validation` | testing.md |
| `f1-accuracy` | f1.md |
| `f1-trading`, `f1-matrix`, `f1-checkpoints` | market-making.md |
| `headline` | evaluation.md |
| `forecast-summary` | forecast.md |
| `todo-summary` | todo.md |
