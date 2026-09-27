# racinglines
Databases, prediction engines and market-making tools for race sports: **Formula 1**
(priced against Polymarket) and **UCI downhill** (private book).

**Live:**
[racinglines.bet](https://racinglines.bet) ·
[racinglines.bet/pitch](https://racinglines.bet/pitch)

> Use password="password" for demo app/pitch.

<!-- Sections between include markers are generated from docs/ by build_readme.py.
     Edit the tagged section in docs/, then run: python scripts/build_readme.py -->

## What it does

<!-- include: overview -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

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

<!-- /include -->

### Headline numbers

<!-- include: headline -->
<!-- generated from docs/evaluation.md by build_readme.py - edit it there -->

Walk-forward backtest over 43 rounds, 2021–2026. Each round is predicted only from
data before it.

| | Model | Uniform guess |
|---|---|---|
| Brier score, making the Final | **0.127** | 0.204 |
| Brier score, podium | **0.0224** | 0.0259 |
| Win probability given to the actual winner (average) | **7.1%** | ~1% |
| Rank correlation, predicted vs actual points | **0.62** | 0 |

Per-season and per-round tables: [Evaluation](docs/evaluation.md#results-every-season-with-data-20212026).

<!-- /include -->

<!-- include: forecast-summary -->
<!-- generated from docs/forecast.md by build_readme.py - edit it there -->

2026 title odds with 2 rounds left (Whistler in progress, then one more round):
**Williams 71.1%**, Vermette 18.8%, Pierron 4.2%, Iles 4.1%
([full forecast](docs/forecast.md#projected-final-standings)).

<!-- /include -->

<!-- include: points-warning -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

> ⚠️ **Points are placeholders**
>
> Championship points use approximate tables, not the official UCI scale. Every
> number measured in points (expected points, standings, champion odds) is
> approximate until [points validation](docs/todo.md#points-validation) is done.
> Win, podium, top-10 and make-Final probabilities don't depend on points.

<!-- /include -->

## Quickstart

<!-- include: quickstart -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
python3.14 -m venv .venv && source .venv/bin/activate  # Python 3.11+
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

<!-- /include -->

## Docs

Full documentation covers data and storage, both sports' models, evaluation,
market making (diagnostics, replays, sweeps, season strategy), the web app, the CLI,
testing and project history. The source is in
[`docs/`](docs/).

<!-- include: docs-build -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
pip install -r requirements-docs.txt
mkdocs serve        # live preview at http://127.0.0.1:8000
mkdocs build        # static HTML in site/
python scripts/build_readme.py   # refresh README.md from sections tagged in docs/
```

<!-- /include -->

## Repo layout

<!-- include: repo-layout -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

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
| `tests/` | Regression suite on pinned fixtures + golden outputs (see [Testing](docs/testing.md)) |
| `scripts/build_readme.py` | Regenerates README sections from tagged docs sections |
| `docker-compose.yml` | Local PostgreSQL 17 (port 5433) |
| `pyproject.toml`, `requirements.txt`, `requirements-docs.txt` | Package (`pip install -e .` for the `racinglines` command); pinned dependencies (pipeline / docs site) |
| `data/raw/<sport>/<source>/` | Downloads: F1 sessions (FastF1 Parquet), downhill event files (Chronorace) |
| `data/archive/markets/<exchange>/` | Exchange price / trade / order-book history (Parquet) |
| `data/runs/`, `data/cache/` | Generated outputs; disposable caches |
| `docs/`, `mkdocs.yml` | Documentation site (MkDocs) |

<!-- /include -->

## TODO

Full list: [`docs/todo.md`](docs/todo.md).

<!-- include: todo-summary -->
<!-- generated from docs/todo.md by build_readme.py - edit it there -->

**Points validation (highest priority)**

- [ ] Get the official UCI DHI points scales (Final and qualifying), for 2026 and
      for past formats.
- [ ] Replace `FINAL_POINTS` / `QUAL_POINTS` / `QUAL_POINTS_ROUND`, per era if needed.
- [ ] Settle the edge cases: DNF/DSQ in the Final, ties, protected riders, bonus rounds.
- [ ] Check our 2026 totals after round 7 against the official standings, and add a
      test that pins them.
- [ ] Re-run and refresh the published numbers.

**Data**

- [ ] Key riders by UCI ID. It's in ChronoRace's JSON; names change across seasons.
- [ ] Parse the readable 2021 PDFs (Leogang, Les Gets). 2019–20 would need OCR.
- [ ] Build rounds missing from Wikipedia (probing) into the downloader. Clean up
      venue names.
- [ ] Add Women's categories, start order and weather.

**Model**

- [ ] Check calibration: win probabilities look too flat.
- [ ] Tune over all 43 backtest rounds. Add rider × venue effects.

**Engineering**

- [x] Tests: pinned regression suite for every pipeline stage plus web, private-book and role smoke tests (see [Testing](docs/testing.md)).
- [ ] Per-maker exposure limits and per-taker daily limits; taker balances or ledgers.
- [ ] Rate-limit and paginate the activity log view; export the log to CSV.
- [ ] Refuse house markets (and market links) for junior categories (`categories.age_group = 'junior'`).
- [ ] Persist login throttling across restarts (it's in memory now), and add a stable named tunnel with Cloudflare Access.
- [ ] Condition in-weekend forecasts on completed rounds (Q1 results, split times).

<!-- /include -->
