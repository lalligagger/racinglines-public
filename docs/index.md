# racinglines

racinglines builds databases, prediction engines and market-making tools for race
sports. Two sports so far:

- **Formula 1**, priced against real Polymarket markets;
- **UCI Mountain Bike World Series downhill** (Men Elite / Junior), which has no
  exchange yet and is quoted through our private book.

The goal is to be accurate enough to make markets.

These docs cover everything built so far in detail. The top-level `README.md` is
the short version, and parts of it are generated from sections of these pages
(see [Docs & README](cli.md#scriptsbuild_readmepy)).

## What it does

<!-- readme: overview -->

- **Collects** official timing: F1 from the live-timing archive via FastF1 (every
  qualifying, sprint, race and practice session since 2020), and downhill split
  timing from ChronoRace (2021–2026). Everything is stored in **PostgreSQL**, in
  one multi-sport schema.
- **Models** each sport:
    - **F1:** a sector-aware car model shared by both team drivers, driver
      offsets, a practice-pace prior, and a grid/overtaking finishing model;
    - **Downhill:** a log-time model of each rider's pace, consistency and
      crash/DNF rate.
- **Simulates** race weekends and seasons thousands of times: win, podium, top
  10, pole, head-to-head and team markets, plus championships.
- **Prices strictly as of a moment:** only sessions that have ended before the
  cutoff are used. Backtests, single-event diagnostics and live forecasts all
  use the same function.
- **Tests strategies on real market data:**
    - Polymarket's recorded prices, trades and order books (Parquet archive);
    - maker replays, weekend taker strategies traded after every session, and a
      default season-long strategy for the championship markets.
- **Web app** ([racinglines.bet](https://racinglines.bet)):
    - **Markets:** every sport's next races and season, with our fair price
      against each venue;
    - **My Book:** positions across venues;
    - **Lab:** launch backtests, scenario forecasts, diagnostics and strategy
      replays; compare and promote them.
    - Takers bet on makers' private markets at the quoted price.

<!-- /readme -->

## What exists today

| Piece | File | What it does |
|---|---|---|
| Downloader | `racinglines/sources/chronorace/download.py` | Finds World Cup events for a year and writes per-round split timing to one markdown file per event and category. |
| Parser | `racinglines/sources/chronorace/parse.py` | Turns downloaded files (and pasted HTML, CSV or JSON tables) into one tidy long-format table. |
| Database | `racinglines/db/`, `docker-compose.yml`, `migrations/` | PostgreSQL store for results, athletes, model runs and predictions. Designed for many sports and leagues. |
| Season model | `racinglines mtb_dh forecast` | Estimates each rider's pace from all seasons and categories, simulates race weekends in each event's own format, and projects 2026 championship standings. Includes walk-forward and holdout backtests. |
| Multi-season backtest | `racinglines mtb_dh backtest` | Runs the walk-forward and standings backtests for every season with data (2021–2026). |
| Formula 1 | `racinglines f1` | Second sport: official F1 timing (FastF1) since 2020 into the same database, with a sector-aware pace model, grid/overtaking finishing model, and race + championship simulation. See [Formula 1](f1.md). |

## Pipeline

```
racinglines/sources/chronorace/download.py ──> data/raw/mtb_dh/chronorace/*.md ──> racinglines mtb_dh ingest ──> PostgreSQL ──> racinglines mtb_dh forecast
     (ChronoRace API)          (1 file / event / category)    (parses on the way in)                   (backtests, forecast;
                                                                                                    --save stores runs)
```

Without a database, `racinglines/sources/chronorace/parse.py` can still write a tidy CSV for `racinglines mtb_dh forecast --data splits.csv`.

## Quickstart

<!-- readme: quickstart -->

```
pip install -r requirements.txt && pip install -e .   # dependencies + the `racinglines` command
docker compose up -d                                   # PostgreSQL on localhost:5433
racinglines db init                                    # tables + reference data

racinglines f1 fetch && racinglines f1 ingest          # F1 sessions (FastF1) -> database
racinglines f1 forecast --save                         # live F1 prices: remaining races + championships
racinglines markets sync                               # Polymarket's F1 markets

racinglines mtb_dh ingest                              # downhill event files -> database
racinglines mtb_dh forecast --db --save                # downhill season forecast

ADMIN_PASSWORD=... racinglines web                     # the app on http://127.0.0.1:8000
racinglines check                                      # quick validation: code, data endpoints, database (~10 s)
```

<!-- /readme -->

To build these docs:

<!-- readme: docs-build -->

```
pip install -r requirements-docs.txt
mkdocs serve        # live preview at http://127.0.0.1:8000
mkdocs build        # static HTML in site/
python scripts/build_readme.py   # refresh README.md from sections tagged in docs/
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
| `racinglines/cli/` | The `racinglines` command: `f1`, `mtb_dh`, `markets`, `db`, `web` groups |
| `racinglines/sources/` | Data sources: `fastf1/` (fetch, ingest), `chronorace/` (download, parse, ingest) |
| `racinglines/models/` | Model families: `position_sim/` (F1: car/driver pace, practice prior, race and season pricing), `timed_runs/` (downhill: log-time model, weekend and season simulation) |
| `racinglines/markets/` | Exchanges and books: Polymarket `sync`/`trade`, the Parquet `store`, `venues`, the `private_book`, and `strategies/` (maker replay, weekend taker, season) |
| `racinglines/pipelines/` | Multi-stage runs: `weekend_sweep`, `season_strategy` |
| `racinglines/db/` | Database: models, migrations' target, reads, queries, shared ingest helpers, registry of sports and venues |
| `racinglines/web/` | The web app (`racinglines web`): Markets, My Book, Lab, admin |
| `racinglines/paths.py` | Where data lives (`data/raw`, `data/archive`, `data/runs`, `data/cache`) |
| `migrations/`, `alembic.ini` | Alembic schema migrations |
| `tests/` | Regression suite on pinned fixtures + golden outputs (see [Testing](testing.md)) |
| `scripts/build_readme.py` | Regenerates README sections from tagged docs sections |
| `docker-compose.yml` | Local PostgreSQL 17 (port 5433) |
| `pyproject.toml`, `requirements.txt`, `requirements-docs.txt` | Package (`pip install -e .` for the `racinglines` command); pinned dependencies (pipeline / docs site) |
| `data/raw/<sport>/<source>/` | Downloads: F1 sessions (FastF1 Parquet), downhill event files (Chronorace) |
| `data/archive/markets/<exchange>/` | Exchange price / trade / order-book history (Parquet) |
| `data/runs/`, `data/cache/` | Generated outputs; disposable caches |
| `docs/`, `mkdocs.yml` | Documentation site (MkDocs) |

<!-- /readme -->

## Page map

- [Data](data.md): where the data comes from, what was downloaded, file format,
  and the race formats by year.
- [Parser](parser.md): input formats, the tidy schema, round labels, and rider-ID
  normalization.
- [Database](database.md): PostgreSQL setup, the multi-sport data model, ingest,
  and stored model runs.
- [Web app & trading](webapp.md): the maker / taker app, and how Polymarket maker orders
  are linked, checked and placed.
- [Season model](model.md): the statistical model, how it's fit, and how weekends
  and seasons are simulated.
- [Formula 1](f1.md): data source, database layout, the sector-aware model, and
  backtests.
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
