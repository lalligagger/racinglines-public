# CLI reference

## download_chronorace.py

```
python download_chronorace.py (--year YEAR | --events SLUG [SLUG ...])
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
| `--out-dir` | Default `chronorace_results`. Use `data/script-generated/` for this project. |
| `--list-only` | Print the discovered slugs and stop. |

Output: `<out-dir>/<slug>_<discipline>_<category>.md`. Existing files are overwritten.

Typical full refresh:

```
for y in 2021 2022 2023 2024 2025 2026; do
  for c in "Elite Men" "Junior Men"; do
    python download_chronorace.py --year $y --discipline DH --category "$c" --out-dir data/script-generated/
  done
done
# 2021 rounds missing from Wikipedia:
python download_chronorace.py --events 20210914_dh 20210918_dh --discipline DH --category "Elite Men"  --out-dir data/script-generated/
python download_chronorace.py --events 20210914_dh 20210918_dh --discipline DH --category "Junior Men" --out-dir data/script-generated/
```

## parser.py

```
python parser.py --inspect FILE
python parser.py [--input-dir DIR] [--input-file FILE ...] [--out splits.csv]
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

## python -m racedb

Database commands. The connection comes from `$DATABASE_URL`, or `--db URL` before
the command. See [Database](database.md).

```
python -m racedb [--db URL] init                     # alembic upgrade head + seed reference data
python -m racedb [--db URL] seed                     # re-apply racedb/registry.py
python -m racedb [--db URL] ingest PATH [PATH ...] [--competition uci_dhi_wc] [--force]
python -m racedb [--db URL] stats                    # table counts + coverage per season and category
python -m racedb [--db URL] export [--competition uci_dhi_wc] [--out splits.csv]
```

`ingest` takes files or directories (non-recursive `*.md`). Unchanged files are
skipped by content hash, and `--force` re-ingests them. Each ingested file replaces
its race's rounds, results and splits.

## predictor.py season

Predict and backtest one target season.

```
python predictor.py season (--db [URL] | --data splits.csv) [--competition uci_dhi_wc] [--save]
       [--out-dir season_out]
       [--season YEAR] [--category ME]
       [--train-scope {all,season}] [--half-life-days 120] [--junior-weight 0.5]
       [--walk-forward] [--backtest 2] [--remaining 2]
       [--sims 10000] [--seed 42] [--top 15]
```

| Option | Default | Meaning |
|---|---|---|
| `--db [URL]` | – | Read from the database (`$DATABASE_URL` or the docker-compose default if no URL is given). |
| `--data` | – | Read a tidy CSV from `parser.py` instead. |
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

## predictor.py backtest

Walk-forward plus a standings holdout, for several seasons.

```
python predictor.py backtest (--db [URL] | --data splits.csv) [--competition uci_dhi_wc] [--save]
       [--out-dir backtest_out]
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

## python -m webapp

Admin web app. See [Web app & trading](webapp.md).

```
ADMIN_USERNAME=admin ADMIN_PASSWORD=... python -m webapp          # http://127.0.0.1:8000
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

## predictor.py fit / predict (older per-race model)

```
python predictor.py fit --data splits.csv --out-dir model/ [--validate]
python predictor.py predict --model-dir model/ --start-list startlist.csv [--out predictions.csv]
```

`startlist.csv` needs `rider_id` or `rider_name`, plus optional `start_order`,
`track_condition` and `round`.

## Docs

```
pip install -r requirements-docs.txt
mkdocs serve     # http://127.0.0.1:8000, rebuilds live while you edit
mkdocs build     # static site in site/
```

See `requirements-docs.txt` for a workaround if `watchdog` fails to install on Python 3.14.

## build_readme.py

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
python build_readme.py            # rewrite README.md
python build_readme.py --check    # exit 1 if README.md is stale (for CI / pre-commit)
python build_readme.py --list     # tagged sections, and whether the README uses each
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
