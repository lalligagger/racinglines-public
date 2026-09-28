# Database

Results, athletes, model runs and predictions live in **PostgreSQL**. The Python
side is `racinglines/db/`: SQLAlchemy 2 models, Alembic migrations, ingest,
and query helpers.

Why PostgreSQL:

- **Relational data:** athletes, events, rounds and results are linked, and the
  database enforces rules like "one result per athlete per round".
- **Many readers and writers:** the future web API, scheduled ingest jobs and model
  runs can all use it at the same time.
- **Room to grow:** JSONB columns hold sport-specific extras, with no schema change
  needed per sport.
- **Easy to host:** managed Postgres is available everywhere.

Analytics and backtests still run in pandas, loaded from the database.

## Setup

The connection comes from `$DATABASE_URL`, or `--db URL` on any command group. The
default is `postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines`,
the same for both local options below. Port 5433 avoids clashing with a Postgres
already on 5432.

**Option A: Docker** (`docker-compose.yml`: Postgres 17, data in the `pgdata` volume):

```
pip install -r requirements.txt
docker compose up -d                # Postgres 17 on localhost:5433
racinglines db init                 # create tables (migrations) + reference data
racinglines mtb_dh ingest data/raw/mtb_dh/chronorace
racinglines db stats
```

**Option B: Postgres without Docker** (what this machine uses now). A conda env
holding only Postgres 17, and a cluster in `data/pg/` (git-ignored):

```
conda create -n racinglines-db -c conda-forge postgresql=17
PG=~/miniconda3-arm64/envs/racinglines-db/bin
$PG/initdb -D data/pg -U racinglines -W        # password: racinglines
$PG/pg_ctl -D data/pg -o "-p 5433 -k /tmp" -l data/runs/logs/postgres.log start
$PG/createdb -h localhost -p 5433 -U racinglines racinglines
racinglines db init
```

- **Stop** it the same way: `$PG/pg_ctl -D data/pg stop`.
- **Not started on reboot:** run the `start` line again after a restart.
- **One at a time:** don't run it and the Docker container together; both use port 5433.
- The log is `data/runs/logs/postgres.log`.

**Option C: any existing Postgres (14+).** Create an empty database and point
`DATABASE_URL` at it:

```
createdb racinglines
export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/racinglines
racinglines db init
```

A new database can be filled from the raw files (`racinglines f1 ingest`,
`racinglines mtb_dh ingest`, `racinglines f1 pm-sync`) or, as an exact replica, from
the [snapshot](#snapshot-an-exact-replica).

## Data model

The data is organized in levels, each belonging to the one above:

```
Sport           mtb_dh                   what is raced
League          uci_mtb                  who organizes it
Competition     uci_dhi_wc               a league's championship in one sport
 ├─ Category    ME, MJ, WE, WJ
 └─ Season      2026
     └─ Event   Les Gets 2026            source=chronorace, source_key=20260821_mtb, venue, series round
         └─ Race          event × category, plus its weekend format (JSONB)
             └─ Round     practice / qual / qual1 / qual2 / semi / final
                 └─ Result   athlete, position, status, time_ms, bib, team, nation
                     └─ Split   idx, cum_time_ms, rank
```

| Table | Purpose |
|---|---|
| `sports`, `leagues`, `competitions`, `categories` | Reference data, seeded from `racinglines/db/registry.py`. |
| `seasons`, `events`, `venues`, `venue_aliases` | The calendar. Aliases map spellings from source data (e.g. `mont-ste-anne`) to one canonical venue. |
| `races`, `rounds` | What was raced at each event. `races.format` stores the weekend format (e.g. `{"kind": "q1q2", "q1_to_final": 20, "q2_to_final": 10}`). |
| `results`, `splits` | One row per athlete per round, and per split. Times are stored as integer milliseconds. |
| `athletes`, `athlete_identifiers` | Athletes are shared across sports. Identifiers are `(scheme, value)` pairs, e.g. `("name", "o callaghan oisin")` now and `("uci", "10007307417")` later. One athlete can have many identifiers. |
| `source_files` | Every ingested file with its content hash, so unchanged files are skipped. |
| `points_schemes` | Championship points by competition, era and round kind (`points[0]` = 1st place). Empty until the [points TODO](todo.md#points-validation) is done. |
| `model_runs` | One row per model run: competition, season, category, kind (`forecast` / `backtest`), data date, git version, `params` and `metrics` (JSONB). |
| `race_predictions` | Per-athlete probabilities (win, podium, top 10, make Final, expected points) for a race. `race_id` is empty for races that aren't in the database yet (`target = "remaining_round"`). |
| `standings_predictions` | Per-athlete projected standings for a model run. |
| `market_links` | An exchange outcome token (Polymarket) or market's YES contract (Kalshi; `exchange` says which) linked to one of the model's probabilities: athlete, prediction kind, optional race, and inverted for "No"-type tokens. Also the event slug and title, live bid / ask / price, volume, end date, resolution, `synced_at`, and `first_seen_at`: when a sync first saw the token (null for tokens synced before alerts existed); it drives the "new" badges and [new-market alerts](cli.md#racinglines-markets). |
| `orders` | Every exchange order the app built: dry run, submitted, rejected or cancelled. Includes the model probability, model run, book at the time and exchange response. |
| `house_markets` | YES/NO markets quoted in the app (race × athlete × kind × maker), with fair probability, spread, YES/NO prices, status, outcome and `maker_id` (null = legacy house markets). |
| `house_bets` | Bets against house markets: counterparty, `taker_id` (the taker account, if placed in the app), side, price, stake, payout, status. |
| `users` | Web-app accounts: username, role (`admin` / `maker` / `taker`), scrypt password hash, active, and `prefs` (JSONB, [keys below](#user-preferences)). Besides the demo `maker` / `taker` logins there is one system account, `polymarket-takers` (role `taker`, inactive, no login): the counterparty of recorded replay fills, kept separate from the demo taker (migration `d2b8e5a1c3f7`). |
| `activity_log` | Audit trail of web-app actions: time, user, role, action, JSON detail, IP, path. |
| `laps` | One row per lap of a lap-based round: lap and sector ms, speed traps, tyre, stint, pit in/out, track status, position, accuracy. Added for F1. |
| `track_profiles` | Per-event track features (sector shares, trap speeds, speed index, overtaking, street, weather) used by the F1 model. |
| `market_price_history`, `market_trades`, `market_book_snapshots` | Exchange time series per outcome token: prices, every taker trade (the tape a maker replay fills against), and recorded order books. Only recent rows stay here; the rest move to Parquet (see [Storage](#storage-postgres-for-the-app-parquet-for-heavy-history)). |
| `jobs` | Model runs launched from the web app's Lab, run as CLI subprocesses: kind, params, argv, status, progress, log, and the model run they saved. |
| `strategy_signals` | What a user's strategy profile would do now ([Paper trading](paper-trading.md)): a taker recommendation (`buy` / `sell`), a maker quote starting or stopping (`quote` / `pull`), or a paper `fill`. Never an order. Columns: user, `candidate_id` (the Lab candidate), profile name, strategy, race, `event_key`, `market_key` (taker: token id; maker: condition id), kind, subject, stage, `dedupe` (the stage, or a fill's time), action, side (`YES` / `NO`, or `bid` / `ask`), shares, limit price, fair, market price, edge, `heat` (1–3), target cost, status (`new` / `alerted` / `expired` / `filled_paper`), model run, signal / alerted / seen times, `detail` (JSONB; `backfill` marks demo-history replays). Unique on (user, candidate, market_key, dedupe, action, side), so re-runs are idempotent. |
| `paper_positions` | A user's paper position in one market under their profile, rebuilt on every signals run: YES / NO shares (maker: YES-equivalent inventory), cash, latest mark, outcome, for makers the resting bid / ask and quote state, and the **venue**: `polymarket` (paper trading on the exchange) or `private` (a maker's private book, written by the [live engine](live-events.md)). Unique on (user, candidate, market_key). |
| `live_events` | Every live private-book event once recorded (`racinglines live settle <spec>`, [Live events](live-events.md)): its run folder, sport, event key, title, when the book opened and settled, the maker's P&L (total, vs the crowd, vs the demo taker), the crowd's fills and volume, and `detail` (settings, the crowd's results, a P&L curve). The demo accounts' story dates private-book events from it. Unique on the run. |

### Multi-sport design

- **Adding a sport or league is data, not schema.** Each sport has a schema file,
  `sports/<code>.toml` (sport, league, competition, categories, sessions, points,
  venues, which markets and venues it uses). `racinglines/db/registry.py` and the
  models read their constants from it. Add the file (and its code to
  `racinglines/sports.py`), then run `racinglines db seed`.
- **Rounds are generic.** `Round.kind` is free text, so formats like heats, runs
  1/2 or sprint/feature fit without migrations. `ROUND_ORDER` in the registry sets
  the running order.
- **Sport-specific extras** go in JSONB: `races.format`, `results.extra`,
  `race_predictions.extra`, `model_runs.params` / `metrics`.
- **Result kind:** `sports.result_kind` is `time` for timed races. Other kinds
  (score, distance) can reuse `results` with `time_ms` empty and the value in `extra`.
- **Winter sports:** `seasons.year` plus an optional `label` (e.g. `2025/26`).

### User preferences

`users.prefs` holds settings that follow the account to any device
(`racinglines/web/prefs.py`; one top-level key per setting). View state (open
sections, filters) stays in the browser; history (jobs, runs, bets) has its own
tables. A demo visitor's changes go to a per-session overlay and are never saved.

| Key | Holds | Written by |
|---|---|---|
| `edge_finder` | The Lab's Edge Finder combos, `[[ref, strategy], …]` (ref: a variant or `cfg:<settings key>`) | Edge Finder (`racinglines/web/edge.py`) |
| `edge_year` | The Edge Finder's season | Edge Finder |
| `job_knobs` | Last-used knobs per Lab job type | Lab job forms |
| `strategy_profile` | The profile the user runs: `name`, `strategy`, `settings` (full sweep settings), `candidate_id`; optionally `follow_rate` (share of taker recommendations followed, e.g. 0.33 for the demo taker; set in code only) and `bankroll` (`start` in $, `since` date) | `racinglines f1 profiles --assign-demo`, the Lab |

The profile keeps the full settings, so deleting its Lab candidate doesn't break the
assignment.

## Ingest

```
racinglines mtb_dh ingest data/raw/mtb_dh/chronorace [more files or dirs ...] [--competition uci_dhi_wc] [--force]
```

Each downloaded file is one event × category, and becomes one race:

1. **Skip unchanged files:** if the file's hash matches `source_files`, it's skipped.
   `--force` re-ingests anyway.
2. **Parse** it with `parser.parse_markdown_tables_file` (the same code as the CSV
   pipeline).
3. **Look up or create** the season, venue (via aliases), event, race and weekend
   format.
4. **Replace** the race's rounds, results and splits. So re-downloading a file and
   re-ingesting it updates the race in place; nothing is duplicated.
5. **Match athletes** by the `name` identifier, the same normalized key as the
   parser's `rider_id`, creating new athletes as needed.

Files with no timing tables (PDF-only rounds) are skipped.

Current contents after ingesting `data/raw/mtb_dh/chronorace/`:

| | Rows |
|---|---|
| Events / races / rounds | 45 / 90 / 279 |
| Athletes | 1,140 |
| Results | 19,022 |
| Splits | 70,077 |

That's 2021–2026, Men Elite and Men Junior, including Whistler 2026 while it's in
progress. The full load takes about 8 seconds.

**Event status:**

- `completed`: the ingested file has Final results.
- `in_progress`: the file has rounds but no Final yet. The race's `format` stays
  empty until the Final is in.
- `scheduled`: a future event added by hand in the web app (`source = "manual"`).

## Using it from the model

`racinglines mtb_dh forecast` and `racinglines mtb_dh backtest` read from the database with
`--db`, and store their output with `--save`:

```
racinglines mtb_dh forecast   --db --walk-forward --save    # 2026 forecast, stored as a model run
racinglines mtb_dh backtest --db --save                   # 2021–2026 backtest metrics
```

`racinglines.db.queries.load_tidy()` returns the same tidy layout as `racinglines/sources/chronorace/parse.py`'s CSV,
with `race_id` and `athlete_id` added and `rider_id = "ath:<athlete id>"`. So the
model code doesn't change, and athletes merged in the database are one rider to
the model. The numbers match the CSV pipeline within simulation noise. `--data
splits.csv` still works without a database.

What `--save` stores:

| Command | `model_runs.kind` | Predictions | Metrics (JSONB) |
|---|---|---|---|
| `forecast` | `forecast` | `remaining_round` per athlete, `backtest:<event>` per athlete (linked to the race) | `walk_forward`, `backtest` |
| `backtest` | `backtest` | none | `all_events`, `seasons`, `events` |

Example queries:

```sql
-- latest title odds
SELECT a.display_name, sp.champion_prob, sp.exp_points
FROM standings_predictions sp JOIN athletes a ON a.id = sp.athlete_id
WHERE sp.model_run_id = (SELECT max(id) FROM model_runs WHERE kind = 'forecast')
ORDER BY sp.champion_prob DESC LIMIT 10;

-- an athlete's results across seasons
SELECT e.start_date, v.name AS venue, c.code, ro.kind, r.position, r.status, r.time_ms / 1000.0 AS secs
FROM results r
JOIN rounds ro ON ro.id = r.round_id JOIN races ra ON ra.id = ro.race_id
JOIN events e ON e.id = ra.event_id JOIN categories c ON c.id = ra.category_id
LEFT JOIN venues v ON v.id = e.venue_id
JOIN athlete_identifiers ai ON ai.athlete_id = r.athlete_id
WHERE ai.scheme = 'name' AND ai.value = 'williams jordan' AND ro.kind = 'final'
ORDER BY e.start_date;
```

## Other commands

```
racinglines db init       # alembic upgrade head + seed
racinglines db seed       # re-apply registry.py (after adding a sport, league or venue)
racinglines db stats      # table counts + events/rounds/results per season and category
racinglines db export --out splits.csv   # tidy CSV from the database
racinglines db snapshot-export           # see Snapshot below
racinglines db snapshot-import [--force]
```

## Snapshot: an exact replica

Rebuilding from the raw files gives the same data under different ids, and the
pricing code orders drivers by id in places, so seeded simulations would differ at
the level of simulation noise. The snapshot keeps the ids (`racinglines/db/snapshot.py`):

```
racinglines db snapshot-export     # -> data/archive/db/<table>.parquet + manifest.json (table list, row counts)
racinglines db init                # on the fresh database: schema at head
racinglines db snapshot-import     # replaces these tables, resets the id sequences
```

- **Tables** (`TABLES`, parents first): the race data (`sports`, `leagues`,
  `competitions`, `categories`, `seasons`, `points_schemes`, `venues`,
  `venue_aliases`, `athletes`, `athlete_identifiers`, `events`, `races`, `rounds`,
  `results`, `splits`, `laps`, `track_profiles`, `source_files`) and `market_links`.
- **Never exported:** web-app tables (users, books, bets, jobs, signals) and model runs.
  Market prices and trades aren't in it either: they are the Parquet market archive.
- **Import** is for a fresh database: it refuses one that already holds model runs
  unless `--force`.
- `scripts/cloud/prepare.sh` exports it before a cloud sweep and
  `scripts/cloud/start.sh` imports it (see [Cloud sweeps](cloud-sweep.md)).

**Rebuilding everything from it.** The snapshot plus the committed Parquet archive
are enough to rebuild the working database. After `snapshot-import`:

1. `racinglines f1 forecast --save`: the live forecast the web app prices from.
2. Web-app accounts aren't in the snapshot: create the demo `maker` / `taker`
   accounts, run `racinglines f1 profiles --assign-demo`, then
   `racinglines f1 demo-history` for their track record.
3. Re-run the saved research with `--save`: backtests per model variant (and the
   downhill backtest), season sweeps per variant and profile (2025 and 2026), the
   season strategy and the season checkpoints.

This was done on 2026-09-27 (a fresh local cluster, see Setup option B), and every
result reproduced exactly.

## Changing the schema

1. Edit `racinglines/db/models.py`.
2. Generate a migration:
   `DATABASE_URL=... alembic revision --autogenerate -m "what changed"`.
3. Review the file in `migrations/versions/`. Autogenerate misses some things, such
   as renames and changes to data.
4. Apply it with `racinglines db init` (or `alembic upgrade head`).

Migrations so far (in order, `migrations/versions/`):

| Revision | File | Adds |
|---|---|---|
| `1983462a0695` | `20260926_1983462a0695_initial_schema.py` | Core schema (sports → splits, source files, points schemes, model runs, predictions) |
| `66d4b92ba307` | `20260926_66d4b92ba307_market_links_and_orders.py` | `market_links`, `orders` |
| `0e47bb766d0b` | `20260926_0e47bb766d0b_house_markets_and_bets.py` | `house_markets`, `house_bets` |
| `f3e017071b76` | `20260926_f3e017071b76_laps_track_profiles_round_extra.py` | `laps`, `track_profiles`, `rounds.extra` (Formula 1) |
| `8d64d59a2940` | `20260926_8d64d59a2940_users_roles_activity_log.py` | `users`, `activity_log`, `house_markets.maker_id` (uniqueness now per maker), `house_bets.taker_id` |
| `d84cd5aa7ce4` | `20260926_d84cd5aa7ce4_polymarket_alignment.py` | `market_links`: optional athlete, `params`, event slug/title, outcome label, live bid/ask/price, volume, end date, closed, resolution, sync time. `house_markets`: optional race/athlete, `market_link_id` (mirrored exchange market), `params`. `standings_predictions.extra` |
| `8c46493d7cda` | `20260926_8c46493d7cda_house_market_uniqueness_per_mirrored_.py` | House-market uniqueness includes `market_link_id` (several head-to-heads per driver and race) |
| `50a176ca2955` | `20260926_50a176ca2955_market_price_history.py` | `market_price_history` |
| `3f94d44a125e` | `20260926_3f94d44a125e_market_trades_and_book_snapshots.py` | `market_trades`, `market_book_snapshots` |
| `81022900a936` | `20260926_81022900a936_jobs.py` | `jobs` |
| `5b1e0c7d2a41` | `20260927_5b1e0c7d2a41_user_prefs.py` | `users.prefs` (nullable JSONB) |
| `9c4d2e8f1a63` | `20260927_9c4d2e8f1a63_market_first_seen.py` | `market_links.first_seen_at` |
| `c7a1f4e2b9d0` | `20260927_c7a1f4e2b9d0_strategy_signals.py` | `strategy_signals`, `paper_positions` |
| `d2b8e5a1c3f7` | `20260927_d2b8e5a1c3f7_replay_taker_account.py` | The `polymarket-takers` system account (inactive); recorded replay fills (`house_bets`) move to it from the demo taker (data only) |
| `e4c1a9b7d205` | `20260927_e4c1a9b7d205_paper_position_venue.py` | `paper_positions.venue` (`polymarket` / `private`) |

## Not done yet

- **Public / JSON API.** The web app ([Web app](webapp.md)) reads and writes
  the database; there are no JSON endpoints for outside consumers yet.
- **UCI IDs:** add `uci` identifiers at ingest once the downloader writes them.
  That merges riders whose name changed.
- **Points:** fill `points_schemes` with official tables and have the model read
  points from it instead of the constants in `racinglines/models/timed_runs/`.
- **Scheduled events in the forecast:** in-progress events are forecast with their
  start lists, and scheduled events can be added in the web app. But
  `forecast_season` doesn't yet read `scheduled` events (with no start list) as
  named rounds; unknown rounds are still saved as `remaining_round`.


## Storage: Postgres for the app, Parquet for heavy history

| Data | Where | Why |
|---|---|---|
| Everything the app presents: sports, events, results, athletes, market links, model runs (forecasts, backtests, diagnostics, sweep summaries with P&L across weekends), users, books, bets, jobs, paper signals and positions | Postgres | Small, queried constantly |
| Exchange time series (`market_price_history`, `market_trades`, `market_book_snapshots`) for **upcoming and in-progress races, the latest completed race of each competition, and the last 7 days of open season markets** | Postgres | What the app shows live |
| All other exchange time series | Parquet, `data/archive/markets/<exchange>/{prices,trades,books}/month=YYYY-MM/*.parquet` (zstd; `polymarket`, `kalshi`) | Heavy and stale; about 20–40× smaller than in Postgres |
| Raw F1 sessions | Parquet, `data/raw/f1/fastf1/<year>/` | The record; FastF1's HTTP cache is cleared after each fetch |
| Snapshot of the model tables, market links files | Parquet, `data/archive/db/`, `data/archive/markets/{polymarket,kalshi}/links/` | Rebuild or replicate a database without the sources |

- **Reading:** everything goes through `racinglines/markets/store.py` (`read`, `last_before`),
  which merges both stores (Postgres and every exchange's Parquet tree) and drops duplicates.
  Callers don't need to know where a row lives.
- **Moving data:** `racinglines markets archive` applies the retention rule
  (`hot_tokens`). It moves rows with `DELETE … RETURNING`, and writes and
  verifies the Parquet before the transaction commits, each row in its market's
  exchange tree (`market_links.exchange`). The recorder (`markets record`) runs it every hour.
- **Options:** `--vacuum-full` returns freed space to the OS, `--compact`
  merges each month into one file, and `--stats` shows where the rows are.
