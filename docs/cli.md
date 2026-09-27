# CLI reference

Everything runs through one command (after `pip install -r requirements.txt && pip install -e .`):

```
racinglines f1      fetch | ingest | forecast | backtest | diagnostic | sweep | season-strategy | replay
racinglines mtb_dh  download | parse | ingest | forecast | backtest
racinglines markets sync | history | trades | record | archive
racinglines db      init | seed | stats | export
racinglines web
racinglines check   [--sport f1|mtb_dh] [--offline] [--no-db]    quick validation (see Testing)
```

`python -m racinglines …` works too. Add `-h` to any group for its options.

## racinglines/sources/chronorace/download.py

```
racinglines mtb_dh download (--year YEAR | --events SLUG [SLUG ...])
                              --discipline {DH,XCO,XCC,EDR}
                              --category "Elite Men" | "Junior Men" | "Elite Women" | "Junior Women" | ...
                              [--out-dir DIR] [--list-only]
```

| Option | Meaning |
|---|---|
| `--year` | Find events from the Wikipedia season page (only slugs dated that year). |
| `--events` | Explicit ChronoRace slugs; skips Wikipedia. |
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
# 2021 rounds missing from Wikipedia:
racinglines mtb_dh download --events 20210914_dh 20210918_dh --discipline DH --category "Elite Men"  --out-dir data/raw/mtb_dh/chronorace/
racinglines mtb_dh download --events 20210914_dh 20210918_dh --discipline DH --category "Junior Men" --out-dir data/raw/mtb_dh/chronorace/
```

## racinglines mtb_dh parse

```
racinglines mtb_dh parse --inspect FILE
racinglines mtb_dh parse [--input-dir DIR] [--input-file FILE ...] [--out splits.csv]
                 [--round LABEL] [--conditions-file CSV]
```

| Option | Meaning |
|---|---|
| `--inspect` | Print the detected structure of one file and exit. |
| `--input-dir` | Parse every `.html/.htm/.csv/.json/.md/.txt` in the directory (not recursive). |
| `--input-file` | One file; can be repeated. |
| `--out` | Output CSV (default `splits.csv`). |
| `--round` | Force a round label on every row (rarely needed). |
| `--conditions-file` | CSV `event_id,round,track_condition` to fill in `track_condition`. |

## racinglines db

Database commands. The connection comes from `$DATABASE_URL`, or `--db URL` before
the command. See [Database](database.md).

```
racinglines db [--db URL] init                     # alembic upgrade head + seed reference data
racinglines db [--db URL] seed                     # re-apply racinglines/db/registry.py
racinglines db [--db URL] ingest PATH [PATH ...] [--competition uci_dhi_wc] [--force]
racinglines db [--db URL] stats                    # table counts + coverage per season and category
racinglines db [--db URL] export [--competition uci_dhi_wc] [--out splits.csv]
```

`ingest` takes files or directories (non-recursive `*.md`). Unchanged files are
skipped by content hash, and `--force` re-ingests them. Each ingested file replaces
its race's rounds, results and splits.

## racinglines mtb_dh forecast

Predict and backtest one target season.

```
racinglines mtb_dh forecast (--db [URL] | --data splits.csv) [--competition uci_dhi_wc] [--save]
       [--out-dir data/runs/mtb_dh/forecast]
       [--season YEAR] [--category ME]
       [--train-scope {all,season}] [--half-life-days 120] [--junior-weight 0.5]
       [--walk-forward] [--backtest 2] [--remaining 2]
       [--sims 10000] [--seed 42] [--top 15]
```

| Option | Default | Meaning |
|---|---|---|
| `--db [URL]` | – | Read from the database (`$DATABASE_URL` or the docker-compose default if no URL is given). |
| `--data` | – | Read a tidy CSV from `racinglines/sources/chronorace/parse.py` instead. |
| `--competition` | `uci_dhi_wc` | Competition code in the database. |
| `--save` | off | Store the model run, its metrics and predictions in the database (needs `--db`). |
| `--season` | latest in data | Target season. |
| `--category` | `ME` | Target category. |
| `--train-scope` | `all` | `all` = every season and category in `--data`; `season` = target only. |
| `--half-life-days` | 120 | Recency half-life for training runs. |
| `--junior-weight` | 0.5 | Training weight of `MJ` runs relative to elite. |
| `--walk-forward` | off | Predict and score every target round from everything before it. |
| `--backtest N` | 2 | Hold out the last N raced rounds; score them and the standings after them. `0` skips. |
| `--remaining N` | 2 | Rounds left in the season, **including** in-progress events already in the data (forecast with their start lists). The rest are simulated as unknown rounds. `0` skips the forecast. |
| `--sims` | 10000 | Monte Carlo simulations (walk-forward uses at most 5000). |
| `--seed` | 42 | Random seed. |
| `--top` | 15 | Rows printed per table. |

Files written: `walk_forward.csv`, `backtest_<venue>.csv`, `backtest_standings.csv`,
`forecast_per_round.csv`, `forecast_standings.csv`.

## racinglines mtb_dh backtest

Walk-forward plus a standings holdout, for several seasons.

```
racinglines mtb_dh backtest (--db [URL] | --data splits.csv) [--competition uci_dhi_wc] [--save]
       [--out-dir data/runs/mtb_dh/backtests]
       [--seasons 2021 2022 ...] [--category ME]
       [--train-scope all] [--half-life-days 120] [--junior-weight 0.5]
       [--sims 4000] [--seed 42]
```

`--db`, `--data`, `--competition` and `--save` work as for `season`. With `--save`, the
per-season and per-event metrics are stored in `model_runs.metrics`. Seasons with
fewer than 3 events that have data are skipped. Files written:
`backtest_events.csv` (one row per predicted round) and `backtest_seasons.csv` (one
row per season). The printed per-season table includes the actual and predicted
champion.

## racinglines f1

Formula 1. See [Formula 1](f1.md).

```
racinglines f1 fetch [--years 2026,2025 | 2020-2026] [--sprints-from 2026] [--force]
racinglines f1 ingest [--years 2020-2026] [--force]
racinglines f1 [--half-life DAYS] backtest [--start-year 2021] [--races N] [--track both|on|off] [--sims 4000] [--out CSV] [--save]
racinglines f1 [--half-life DAYS] diagnostic --event 2026-15 --cutoff 2026-09-25T13:30 [--sims 10000] [--no-track] [--save]
racinglines f1 [--half-life DAYS] forecast [--year 2026] [--sims 10000] [--no-track] [--save [--scenario LABEL]] [--top 10]
racinglines markets sync [--year 2026]
racinglines markets history --events 'f1-azerbaijan-grand-prix%' --start 2026-09-22T00:00 --end 2026-09-26T12:00 [--fidelity 1]
racinglines markets trades --events 'f1-azerbaijan-grand-prix%'
racinglines markets record [--events …] [--interval 60] [--minutes 0] [--sync-every 30]
racinglines f1 replay --runs 11,12,9 [--sweep]
racinglines markets archive [--stats] [--vacuum-full] [--compact] [--hours H]
racinglines f1 sweep [--year 2026] [--rounds 1-15] [--sims 4000] [--min-edge 0.05] [--stake-per-edge 250] [--max-stake 50] [--cost 0.01] [--no-fetch] [--reprice] [--save]
```

| Command | What it does |
|---|---|
| `fetch` | Download qualifying, sprint and race sessions from the F1 live-timing archive into `data/raw/f1/fastf1/`. Newest seasons first. Waits out FastF1's 500 calls/hour limit. |
| `ingest` | Load `data/raw/f1/fastf1/` into the database: events, results, laps, track profiles. Unchanged events are skipped. |
| `backtest` | Walk-forward over races from `--start-year`, both before qualifying (grid simulated) and after (real grid), with track features on and off. Writes one row per race and mode. |
| `forecast` | Simulate the rest of the season and the championship. `--save` creates scheduled events for upcoming rounds and stores the run. |
| `diagnostic` | Price one past event as of `--cutoff` (UTC), with a leakage audit. Stored as `kind='diagnostic'`. See [Market making](market-making.md). |
| `markets sync` | Sync Polymarket's F1 events into `market_links`. |
| `markets history` | Store Polymarket price history for events. `--fidelity 1` is minute-level. |
| `markets trades` | Store every taker trade for events (the tape the replay fills against). |
| `markets record` | Record order-book snapshots of every open modeled market once a minute. Re-syncs events every 30 min. Run it through race weekends. |
| `markets archive` | Move stale exchange data from Postgres to Parquet (see [Database](database.md#storage-postgres-for-the-app-parquet-for-heavy-history)). |
| `sweep` | Trade every raced weekend of a season: price before any running and after each session, trade Polymarket, settle. See [Market making](market-making.md#season-sweep). |
| `replay` | Replay a maker quoting Polymarket through an event's diagnostic runs, with both fill rules. `--sweep` adds the sensitivity table. |

`--half-life` overrides the pace models' recency half-life. `--scenario LABEL`
saves a forecast as `kind='scenario'`, which live prices ignore until it is
promoted in the web app's Lab. `racinglines mtb_dh forecast --scenario LABEL` does the
same for downhill.

Tests: `python -m pytest` (see [Market making](market-making.md#tests)).

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
| `DATABASE_URL` | docker-compose DB | Database connection. |
| `POLYMARKET_*` | – | Exchange credentials and limits; see [Web app & trading](webapp.md#polymarket). |


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
python scripts/build_readme.py --check    # exit 1 if README.md is stale (for CI / pre-commit)
python scripts/build_readme.py --list     # tagged sections, and whether the README uses each
```

Conversions while copying:

| In docs | In README |
|---|---|
| `[x](todo.md#points-validation)` | `[x](docs/todo.md#points-validation)` |
| `[x](#some-heading)` (same page) | `[x](docs/<page>.md#some-heading)` |
| `!!! warning "Title"` + indented body | `> ⚠️ **Title**` blockquote |

Sections currently tagged:

| Tag | Page |
|---|---|
| `overview` | index.md, What it does |
| `quickstart` | index.md, Quickstart |
| `docs-build` | index.md, building the docs |
| `repo-layout` | index.md, Repo layout |
| `points-warning` | index.md, placeholder-points warning |
| `headline` | evaluation.md, Headline numbers |
| `forecast-summary` | forecast.md, title odds |
| `todo-summary` | todo.md, Summary |
