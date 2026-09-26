# racinglines

racinglines builds databases and prediction engines for timed race disciplines.
The first target is the **UCI Mountain Bike World Series downhill (DHI), Men Elite,
2026 season**. The long-term goal is to be accurate enough to make markets on a
niche sport.

These docs cover everything built so far in detail. The top-level `README.md` is
the short version, and parts of it are generated from sections of these pages
(see [Docs & README](cli.md#build_readmepy)).

<!-- readme: built-with -->

> **Built in one session.** This project is my first (vibe-)coding session with
> Claude (Claude Code). Everything here was built in a single session, within the
> session credit limit of a basic paid plan: the data pipeline, the model and
> backtests, the PostgreSQL database, the admin web app with its house book and
> Polymarket tools, and these docs.
>
> ![Claude Code session limit at 96% near the end of the session](img/session-limit.png)

<!-- /readme -->

## What it does

<!-- readme: overview -->

- **Downloads** official split timing from ChronoRace. Men Elite and Men Junior
  2021–2026 have usable data; 2019–20 exist only as PDFs.
- **Parses** it and stores it in **PostgreSQL**, in a schema built for many sports
  and leagues.
- **Learns** each rider's pace, consistency and crash/DNF rate from every season
  and category.
- **Simulates** race weekends (qualifying → Final) thousands of times. The output
  is each rider's chance to win, podium, finish top 10 and make the Final, plus
  expected championship points and final standings.
- **Backtests** itself on every season since 2021, predicting each round only from
  what came before it.
- **Forecasts a race weekend while it's in progress,** using the real start list, and
  checks whether Timed Training times are usable before relying on them.
- **Stores** every model run's settings, metrics and predictions in the database.
- **Admin web app:** latest predictions for upcoming events, model-run and backtest
  history, and athlete and event pages. It also has a house book of our own YES/NO
  markets (fair value ± spread, bet log, exposure, settlement) and maker-only
  (post-only) Polymarket orders checked against the model's fair price. Sign-in
  page, login throttling, and it can be exposed through a Cloudflare tunnel.

<!-- /readme -->

## What exists today

| Piece | File | What it does |
|---|---|---|
| Downloader | `download_chronorace.py` | Finds World Cup events for a year and writes per-round split timing to one markdown file per event and category. |
| Parser | `parser.py` | Turns downloaded files, copy/pastes, HTML, CSV or JSON into one tidy long-format table. |
| Database | `racedb/`, `docker-compose.yml`, `migrations/` | PostgreSQL store for results, athletes, model runs and predictions. Designed for many sports and leagues. |
| Season model | `predictor.py season` | Estimates each rider's pace from all seasons and categories, simulates race weekends in each event's own format, and projects 2026 championship standings. Includes walk-forward and holdout backtests. |
| Multi-season backtest | `predictor.py backtest` | Runs the walk-forward and standings backtests for every season with data (2021–2026). |
| Per-race model | `predictor.py fit` / `predict` | Earlier, separate approach: Elo ratings, a gradient-boosted time-gap regressor, and Plackett–Luce win probabilities. |

## Pipeline

```
download_chronorace.py ──> data/script-generated/*.md ──> python -m racedb ingest ──> PostgreSQL ──> predictor.py --db
     (ChronoRace API)          (1 file / event / category)    (parser.py inside)                   (backtests, forecast;
                                                                                                    --save stores runs)
```

Without a database, `parser.py` can still write a tidy CSV for `predictor.py --data splits.csv`.

## Quickstart

<!-- readme: quickstart -->

```
pip install -r requirements.txt
docker compose up -d                            # PostgreSQL on localhost:5433
python -m racedb init                           # tables + reference data
python -m racedb ingest data/script-generated   # load results

python predictor.py season   --db --walk-forward --save   # 2026 forecast + backtests, stored in the db
python predictor.py backtest --db                        # every season since 2021
ADMIN_PASSWORD=... python -m webapp                       # admin app on http://127.0.0.1:8000
```

No database? `python parser.py --input-dir data/script-generated --out splits.csv`, then use
`--data splits.csv` instead of `--db`.

<!-- /readme -->

To build these docs:

<!-- readme: docs-build -->

```
pip install -r requirements-docs.txt
mkdocs serve        # live preview at http://127.0.0.1:8000
mkdocs build        # static HTML in site/
python build_readme.py   # refresh README.md from sections tagged in docs/
```

<!-- /readme -->

On very new Pythons (e.g. 3.14) the `watchdog` dependency may have no prebuilt
package and fail to build. `watchdog` is only needed for `mkdocs serve`'s live
reload. Either use Python ≤3.13, or install with
`pip install --no-deps mkdocs mkdocs-get-deps` plus mkdocs's other dependencies,
then run `mkdocs build` and open `site/index.html`.

## Repo layout

<!-- readme: repo-layout -->

| Path | |
|---|---|
| `download_chronorace.py` | Event discovery and download from ChronoRace |
| `parser.py` | Raw files → tidy CSV |
| `predictor.py` | Season model: `season`, `backtest`. Older per-race model: `fit`, `predict` |
| `racedb/` | Database package: models, ingest, queries, `python -m racedb` CLI |
| `racedb/registry.py` | Sports, leagues, competitions, categories and venues (add new ones here) |
| `migrations/`, `alembic.ini` | Alembic schema migrations |
| `docker-compose.yml` | Local PostgreSQL 17 (port 5433) |
| `webapp/` | Admin web app: predictions, histories, backtests, Polymarket maker orders (`python -m webapp`) |
| `build_readme.py` | Regenerates README sections from tagged docs sections |
| `requirements.txt`, `requirements-docs.txt` | Pinned dependencies (pipeline / docs site) |
| `data/script-generated/` | Downloaded event files (one per event and category) |
| `data/copy-paste/` | Raw live-timing copy/pastes. Duplicates of 2026 data; don't train on them. |
| `docs/`, `mkdocs.yml` | Documentation site (MkDocs) |

<!-- /readme -->

## Page map

- [Data](data.md): where the data comes from, what was downloaded, file format,
  and the race formats by year.
- [Parser](parser.md): input formats, the tidy schema, round labels, and rider-ID
  normalization.
- [Database](database.md): PostgreSQL setup, the multi-sport data model, ingest,
  and stored model runs.
- [Web app & trading](webapp.md): the admin app, and how Polymarket maker orders
  are linked, checked and placed.
- [Season model](model.md): the statistical model, how it's fit, and how weekends
  and seasons are simulated.
- [Evaluation](evaluation.md): metrics, walk-forward and holdout results, and
  whether older and junior data helps.
- [Current forecast](forecast.md): the latest projection for the remaining 2026 rounds.
- [CLI reference](cli.md): every command and option.
- [Project history](history.md): what was built, in what order, and why.
- [TODO](todo.md): open work, starting with points validation.

<!-- readme: points-warning -->

!!! warning "Points are placeholders"
    Championship points use approximate tables, not the official UCI scale. Every
    number measured in points (expected points, standings, champion odds) is
    approximate until [points validation](todo.md#points-validation) is done.
    Win, podium, top-10 and make-Final probabilities don't depend on points.

<!-- /readme -->
