# Database

Results, athletes, model runs and predictions live in **PostgreSQL**. The Python
side is the `racedb/` package: SQLAlchemy 2 models, Alembic migrations, ingest,
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

**Option A: Docker** (the default connection settings expect this):

```
pip install -r requirements.txt
docker compose up -d                # Postgres 17 on localhost:5433
python -m racedb init               # create tables (migrations) + reference data
python -m racedb ingest data/script-generated
python -m racedb stats
```

**Option B: any existing Postgres (14+).** Create an empty database and point
`DATABASE_URL` at it:

```
createdb racinglines
export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/racinglines
python -m racedb init
```

The connection comes from `$DATABASE_URL`, or `--db URL` on any command. The
default is `postgresql+psycopg://racinglines:racinglines@localhost:5433/racinglines`,
which matches `docker-compose.yml`. Host port 5433 avoids clashing with a Postgres
already on 5432.

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
| `sports`, `leagues`, `competitions`, `categories` | Reference data, seeded from `racedb/registry.py`. |
| `seasons`, `events`, `venues`, `venue_aliases` | The calendar. Aliases map spellings from source data (e.g. `mont-ste-anne`) to one canonical venue. |
| `races`, `rounds` | What was raced at each event. `races.format` stores the weekend format (e.g. `{"kind": "q1q2", "q1_to_final": 20, "q2_to_final": 10}`). |
| `results`, `splits` | One row per athlete per round, and per split. Times are stored as integer milliseconds. |
| `athletes`, `athlete_identifiers` | Athletes are shared across sports. Identifiers are `(scheme, value)` pairs, e.g. `("name", "o callaghan oisin")` now and `("uci", "10007307417")` later. One athlete can have many identifiers. |
| `source_files` | Every ingested file with its content hash, so unchanged files are skipped. |
| `points_schemes` | Championship points by competition, era and round kind (`points[0]` = 1st place). Empty until the [points TODO](todo.md#points-validation) is done. |
| `model_runs` | One row per model run: competition, season, category, kind (`forecast` / `backtest`), data date, git version, `params` and `metrics` (JSONB). |
| `race_predictions` | Per-athlete probabilities (win, podium, top 10, make Final, expected points) for a race. `race_id` is empty for races that aren't in the database yet (`target = "remaining_round"`). |
| `standings_predictions` | Per-athlete projected standings for a model run. |
| `market_links` | An exchange outcome token (Polymarket) linked to one of the model's probabilities: athlete, prediction kind, optional race, and inverted for "No"-type tokens. |
| `orders` | Every exchange order the app built: dry run, submitted, rejected or cancelled. Includes the model probability, model run, book at the time and exchange response. |
| `house_markets` | YES/NO markets quoted by the app itself (race × athlete × kind), with fair probability, spread, YES/NO prices, status and outcome. |
| `house_bets` | Bets recorded against house markets: counterparty, side, price, stake, payout, status. |

### Multi-sport design

- **Adding a sport or league is data, not schema.** Add it to `racedb/registry.py`
  (sport, league, competition, categories, venues) and run `python -m racedb seed`.
- **Rounds are generic.** `Round.kind` is free text, so formats like heats, runs
  1/2 or sprint/feature fit without migrations. `ROUND_ORDER` in the registry sets
  the running order.
- **Sport-specific extras** go in JSONB: `races.format`, `results.extra`,
  `race_predictions.extra`, `model_runs.params` / `metrics`.
- **Result kind:** `sports.result_kind` is `time` for timed races. Other kinds
  (score, distance) can reuse `results` with `time_ms` empty and the value in `extra`.
- **Winter sports:** `seasons.year` plus an optional `label` (e.g. `2025/26`).

## Ingest

```
python -m racedb ingest data/script-generated [more files or dirs ...] [--competition uci_dhi_wc] [--force]
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

Current contents after ingesting `data/script-generated/`:

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

`predictor.py season` and `predictor.py backtest` read from the database with
`--db`, and store their output with `--save`:

```
python predictor.py season   --db --walk-forward --save    # 2026 forecast, stored as a model run
python predictor.py backtest --db --save                   # 2021–2026 backtest metrics
```

`racedb.queries.load_tidy()` returns the same tidy layout as `parser.py`'s CSV,
with `race_id` and `athlete_id` added and `rider_id = "ath:<athlete id>"`. So the
model code doesn't change, and athletes merged in the database are one rider to
the model. The numbers match the CSV pipeline within simulation noise. `--data
splits.csv` still works without a database.

What `--save` stores:

| Command | `model_runs.kind` | Predictions | Metrics (JSONB) |
|---|---|---|---|
| `season` | `forecast` | `remaining_round` per athlete, `backtest:<event>` per athlete (linked to the race) | `walk_forward`, `backtest` |
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
python -m racedb init       # alembic upgrade head + seed
python -m racedb seed       # re-apply registry.py (after adding a sport, league or venue)
python -m racedb stats      # table counts + events/rounds/results per season and category
python -m racedb export --out splits.csv   # tidy CSV from the database
```

## Changing the schema

1. Edit `racedb/models.py`.
2. Generate a migration:
   `DATABASE_URL=... alembic revision --autogenerate -m "what changed"`.
3. Review the file in `migrations/versions/`. Autogenerate misses some things, such
   as renames and changes to data.
4. Apply it with `python -m racedb init` (or `alembic upgrade head`).

Migrations so far (in order):

| Revision | File | Adds |
|---|---|---|
| `1983462a0695` | `20260926_1983462a0695_initial_schema.py` | Core schema (sports → splits, source files, points schemes, model runs, predictions) |
| `66d4b92ba307` | `20260926_66d4b92ba307_market_links_and_orders.py` | `market_links`, `orders` |
| `0e47bb766d0b` | `20260926_0e47bb766d0b_house_markets_and_bets.py` | `house_markets`, `house_bets` |

## Not done yet

- **Public / JSON API.** The admin web app ([Web app](webapp.md)) reads and writes
  the database; there are no JSON endpoints for outside consumers yet.
- **UCI IDs:** add `uci` identifiers at ingest once the downloader writes them.
  That merges riders whose name changed.
- **Points:** fill `points_schemes` with official tables and have the model read
  points from it instead of the constants in `predictor.py`.
- **Scheduled events in the forecast:** in-progress events are forecast with their
  start lists, and scheduled events can be added in the web app. But
  `forecast_season` doesn't yet read `scheduled` events (with no start list) as
  named rounds; unknown rounds are still saved as `remaining_round`.
