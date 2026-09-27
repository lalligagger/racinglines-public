# racinglines

<!-- Sections between include markers are generated from docs/ by build_readme.py.
     Edit the tagged section in docs/, then run: python scripts/build_readme.py -->

<!-- include: tagline -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

**Fair prices for race sports, strictly as of any moment, tested on real market
tapes.** racinglines turns official timing into win, podium, head-to-head and
championship odds, then trades them against the market:

- **Formula 1** against Polymarket;
- **UCI downhill** mountain biking through a private book.

<!-- /include -->

**Live demo:** [racinglines.bet](https://racinglines.bet) (one click: *Try as
maker* / *Try as taker*) · [pitch](https://racinglines.bet/pitch). Demo password:
`password`.

## At a glance

<!-- include: glance -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

| | |
|---|---|
| 🏎️ **129 F1 races backtested** | 2021 to Baku 2026. Each race is priced three times: before practice, before qualifying and after qualifying. After qualifying, top-10 Brier is **0.149**, against 0.163 for a grid-only guess. |
| ⏱️ **Practice pace prior** | Before qualifying, it cuts podium error by **8%** and teammate head-to-head error by **4%**. |
| 💹 **The full 2026 season on Polymarket's real tape** | 15 weekends, re-priced after every session. **Market making: +$751** on $8,969 filled. After FP1, FP2, sprint qualifying and the sprint, the model's race-winner odds beat Polymarket's. |
| 🚵 **43 downhill World Cup rounds** | 2021–2026, walk-forward. Error on who makes the Final is **38% lower** than a uniform guess (0.127 vs 0.204). The actual winner got **7.1%** on average, against ~1% for a uniform guess. |
| ✅ **Checks in seconds** | `racinglines check` runs 21 checks (code, every data source, database) in ~10 s. The **regression suite** runs 88 tests on pinned public fixtures and golden outputs, and **zero data** is in git. |

What's not there yet: **taking** Polymarket's price after qualifying still loses
(Polymarket is sharper there, with a win Brier of 0.060 against our 0.072), and
the season-long championship strategy is down $241 so far. The results below have the
details.

<!-- /include -->

## Results

### Formula 1: how accurate?

<!-- include: f1-accuracy -->
<!-- generated from docs/f1.md by build_readme.py - edit it there -->

**Backtest run 115** (2026-09-26) covers 129 races, 2021 to Baku 2026. Each race
is priced three times, using only sessions that had ended:

- before any practice;
- before qualifying (practice known);
- after qualifying (grid known).

Brier scores, lower is better:

| | Before practice | Before qualifying | After qualifying | Grid-only guess | Uniform |
|---|---|---|---|---|---|
| Win | 0.041 | 0.038 | 0.033 | **0.031** | 0.047 |
| Podium | 0.091 | 0.088 | **0.071** | **0.071** | 0.127 |
| Top 10 | 0.187 | 0.175 | **0.149** | 0.163 | 0.250 |
| Teammate head-to-head | 0.231 | 0.228 | **0.197** | | |

- **Every session sharpens the price.** Error falls at each step, from before
  practice to after qualifying.
- **After qualifying:**
    - **top 10** clearly beats a grid-only guess;
    - **podium** ties it;
    - **win** is still slightly worse: the model underweights the front of the
      grid (on the [TODO](docs/todo.md#f1-model) list).
- **Against Polymarket** (2026, race-winner markets), the model beats the
  market mid-weekend (after FP1, FP2, sprint qualifying and the sprint). The
  market is sharper after FP3 and qualifying (see
  [the season sweep](docs/market-making.md#season-sweep)).

<!-- /include -->

### Formula 1: trading the 2026 season on Polymarket

<!-- include: f1-trading -->
<!-- generated from docs/market-making.md by build_readme.py - edit it there -->

**Every 2026 weekend through Baku, traded on Polymarket's recorded prices**
(sweep run 191). Each stage is priced with the current model (shared car,
practice prior), with a 1¢ cost per share:

| Strategy | P&L | Bought / filled | Weekends up |
|---|---|---|---|
| **Maker replay** (conservative fills, ±2¢) | **+$751** | $8,969 | 7 / 15 |
| Enter before running, hold | +$214 | $6,954 | 7 / 15 |
| Enter after qualifying only | −$15 | $3,254 | 6 / 15 |
| Update & rebuy after each session | −$479 | $11,100 | 5 / 15 |

- **Making markets pays; taking doesn't yet.** Earning the spread from flow
  beats paying it on a model that isn't sharper than the market at every stage.
- **Mid-weekend the model beats Polymarket.** Race-winner Brier, model vs
  market:

  | After | FP1 | FP2 | SQ | Sprint | FP3 | Quali |
  |---|---|---|---|---|---|---|
  | Model | **0.077** | **0.080** | **0.062** | **0.088** | 0.093 | 0.072 |
  | Polymarket | 0.078 | 0.084 | 0.067 | 0.101 | **0.085** | **0.060** |

- **Re-trading after FP3 and qualifying is where it loses:** −$1,187 and
  −$1,166. Trades after FP1, FP2 and the sprint earned +$1,944.

<!-- /include -->

More: the Baku minute-by-minute diagnostic and the championship-market strategy
are in [Market making](docs/market-making.md).

### Downhill

<!-- include: headline -->
<!-- generated from docs/evaluation.md by build_readme.py - edit it there -->

**Downhill (UCI World Cup, Men Elite):** walk-forward backtest over 43 rounds,
2021–2026. Each round is predicted only from data before it, and the model beats
the uniform baseline on podium and make-Final in every season.

| | Model | Uniform guess |
|---|---|---|
| Brier score, making the Final | **0.127** | 0.204 |
| Brier score, podium | **0.0224** | 0.0259 |
| Win probability given to the actual winner (average) | **7.1%** | ~1% |
| Rank correlation, predicted vs actual points | **0.62** | 0 |

Per-season and per-round tables: [Downhill evaluation](docs/evaluation.md#results-every-season-with-data-20212026).

<!-- /include -->

<!-- include: forecast-summary -->
<!-- generated from docs/forecast.md by build_readme.py - edit it there -->

2026 title odds with 2 rounds left (Whistler in progress, then one more round):
**Williams 71.1%**, Vermette 18.8%, Pierron 4.2%, Iles 4.1%
([full forecast](docs/forecast.md#projected-final-standings)).

<!-- /include -->

<!-- include: points-warning -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

> ⚠️ **Downhill points are placeholders**
>
> Downhill championship points use approximate tables, not the official UCI
> scale. Every downhill number measured in points (expected points,
> standings, champion odds) is approximate until
> [points validation](docs/todo.md#points-validation) is done. Win, podium, top-10
> and make-Final probabilities don't depend on points.

<!-- /include -->

## Validation

<!-- include: validation -->
<!-- generated from docs/testing.md by build_readme.py - edit it there -->

Three levels, fastest first:

| | Command | Checks | Time | Needs |
|---|---|---|---|---|
| **Quick check** | `racinglines check` | 21 checks: every pipeline on synthetic data, every data source, the database | ~10 s | nothing downloaded; network and Postgres optional |
| **Regression suite** | `python -m pytest -m "not live"` | 88 tests: every pipeline stage on pinned F1 and downhill fixtures, compared with golden outputs | ~10 s (+ a one-time fixture build) | Postgres and `scripts/fetch_test_fixtures.py` |
| **Everything** | `python -m pytest` | 118 tests, adding smoke tests on the working database, the web app and roles | ~35 s | the working database |

- **No data in git:** fixtures are built locally from the public sources (FastF1,
  ChronoRace, Polymarket). A guard test fails if anything data-like is tracked.
- **Results can't drift silently:** an intended change is re-baselined with
  `UPDATE_GOLDEN=1`.

<!-- /include -->

## Quickstart

<!-- include: quickstart -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
python3.14 -m venv .venv && source .venv/bin/activate  # Python 3.11+
pip install -r requirements.txt && pip install -e .   # dependencies + the `racinglines` command
racinglines check                                      # code, data endpoints, database (~10 s)
```

Then the full pipeline:

```
docker compose up -d                                   # PostgreSQL on localhost:5433
racinglines db init                                    # tables + reference data

racinglines f1 fetch && racinglines f1 ingest          # F1 sessions (FastF1) -> database
racinglines f1 forecast --save                         # live F1 prices: remaining races + championships
racinglines markets sync                               # Polymarket's F1 markets

racinglines mtb_dh ingest                              # downhill event files -> database
racinglines mtb_dh forecast --db --save                # downhill season forecast

ADMIN_PASSWORD=... racinglines web                     # the app on http://127.0.0.1:8000
```

<!-- /include -->

## What it does

<!-- include: overview -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
official timing ──> PostgreSQL ──> as-of model ──> simulated weekends ──> fair prices ──> markets
 (FastF1,           (one multi-     (only sessions   & seasons             (win, podium,   (Polymarket,
  ChronoRace)        sport schema)   ended before     (thousands of runs)   h2h, pole,      private book;
                                     the cutoff)                            titles)         replays, Lab)
```

- **Collects** official timing into one multi-sport **PostgreSQL** schema:
    - F1 via FastF1: every practice, qualifying, sprint and race session since
      2020;
    - downhill split timing from ChronoRace, 2021–2026.
  
  Heavy exchange history (prices, trades, order books) goes to a **Parquet
  archive**.
- **Models** each sport:
    - **F1:** a sector-aware car model shared by both team drivers, driver
      offsets, a practice-pace prior, and a grid/overtaking finishing model;
    - **Downhill:** a log-time model of each rider's pace, consistency and
      crash/DNF rate.
- **Simulates** race weekends and seasons thousands of times: win, podium,
  top 10, pole, head-to-head and team markets, plus championships.
- **Prices strictly as of a moment:** only sessions that have ended before the
  cutoff are used, and a leakage guard enforces it. Backtests, diagnostics and
  live forecasts all call the same function.
- **Tests strategies on real market data:** these all run on Polymarket's
  recorded prices and trades:
    - maker replays;
    - taker strategies that re-trade after every session;
    - a season-long championship strategy.
- **Web app** ([racinglines.bet](https://racinglines.bet)):
    - **Markets:** fair price vs each venue;
    - **My Book:** positions across venues;
    - **Lab:** launch backtests, scenario forecasts, diagnostics and strategy
      replays with your own settings; compare and promote them.

<!-- /include -->

## Explore the docs

<!-- include: layers -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

Each layer builds on the one before, so start at the top and stop when you
have what you need.

| Layer | Page | What's there |
|---|---|---|
| 1. **Data** | [Data](docs/data.md) | Sources, what was downloaded, and the on-disk layout (`data/raw`, `archive`, `runs`, `cache`) |
| | [Parser](docs/parser.md) | Downhill results formats and the tidy schema |
| | [Database](docs/database.md) | The multi-sport schema, ingest, stored runs, and what stays in Postgres vs Parquet |
| 2. **Models** | [Formula 1](docs/f1.md) | Car and driver pace, practice prior, finishing model, as-of pricing |
| | [Downhill model](docs/model.md) | Log-time rider model, weekend formats, season simulation |
| 3. **Accuracy** | [Formula 1 → Results](docs/f1.md#results) | 129-race backtest, A/B tests of each model change |
| | [Downhill evaluation](docs/evaluation.md) | 43-round walk-forward, per season and per event |
| | [Downhill forecast](docs/forecast.md) | The live 2026 title projection |
| 4. **Markets** | [Market making](docs/market-making.md) | Baku diagnostic, maker replay, full-season sweep, season strategy |
| | [Web app & trading](docs/webapp.md) | Roles, pages, the Lab, the private book, Polymarket orders |
| 5. **Operate** | [CLI reference](docs/cli.md) | Every command and option |
| | [Testing](docs/testing.md) | Quick check, regression suite, fixtures, golden outputs |
| 6. **Background** | [Project history](docs/history.md) · [TODO](docs/todo.md) | How it got here, and what's next |

<!-- /include -->

<!-- include: docs-build -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
pip install -r requirements-docs.txt
mkdocs serve        # live preview at http://127.0.0.1:8000
mkdocs build        # static HTML in site/
python scripts/build_readme.py   # refresh README.md from sections tagged in docs/
```

A pre-push hook blocks a push unless the docs build with `--strict`, the README
matches the docs, and no data files are tracked. Enable it once per clone:

```
git config core.hooksPath scripts/hooks   # skip once with: git push --no-verify
```

<!-- /include -->

## Repo layout

<!-- include: repo-layout -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

| Path | |
|---|---|
| `racinglines/cli/` | The `racinglines` command: `f1`, `mtb_dh`, `markets`, `db`, `web`, `check` |
| `racinglines/sources/` | Data sources: `fastf1/` (fetch, ingest), `chronorace/` (download, parse, ingest) |
| `racinglines/models/` | Model families: `position_sim/` (F1: car/driver pace, practice prior, race and season pricing), `timed_runs/` (downhill: log-time model, weekend and season simulation) |
| `racinglines/markets/` | Exchanges and books: Polymarket `sync`/`trade`, the Parquet `store`, `venues`, the `private_book`, and `strategies/` (maker replay, weekend taker, season) |
| `racinglines/pipelines/` | Multi-stage runs: `weekend_sweep`, `season_strategy` |
| `racinglines/db/` | Database: models, reads, queries, shared ingest helpers, registry of sports and venues |
| `racinglines/web/` | The web app (`racinglines web`): Markets, My Book, Lab, admin |
| `racinglines/testing/` | Synthetic data and the checks behind `racinglines check` |
| `racinglines/paths.py` | Where data lives (`data/raw`, `data/archive`, `data/runs`, `data/cache`) |
| `migrations/`, `alembic.ini` | Alembic schema migrations |
| `tests/`, `scripts/fetch_test_fixtures.py` | Regression suite on fixtures built from public sources, plus golden outputs (see [Testing](docs/testing.md)) |
| `scripts/build_readme.py` | Regenerates README sections from tagged docs sections |
| `docker-compose.yml` | Local PostgreSQL 17 (port 5433) |
| `pyproject.toml`, `requirements.txt`, `requirements-docs.txt` | Package (`pip install -e .` for the `racinglines` command); pinned dependencies (pipeline / docs site) |
| `data/` (not in git) | Downloads, the market archive, run outputs and caches |
| `docs/`, `mkdocs.yml` | Documentation site (MkDocs) |

<!-- /include -->

## TODO

Full list: [`docs/todo.md`](docs/todo.md).

<!-- include: todo-summary -->
<!-- generated from docs/todo.md by build_readme.py - edit it there -->

**F1 model and trading**

- [ ] Fix the front-of-grid weighting: after qualifying, the model loses to a
      grid-only guess on the win market.
- [ ] Pre-practice pricing: train the finishing model for the no-practice case too.
- [ ] Stage-aware taker strategy (stop re-trading after FP3 and qualifying),
      tested on events after Baku.
- [ ] Record every race weekend's Polymarket tape and order books, then replay
      with book depth and a queue model.
- [ ] Chaotic-race tail (rain, safety cars, multiple DNFs); top-constructor calibration.

**Downhill: points validation (highest priority)**

- [ ] Get the official UCI DHI points scales (Final and qualifying), for 2026 and
      past formats, and settle the edge cases.
- [ ] Check our 2026 totals against the official standings, and pin them in a test.
- [ ] Re-run and refresh the published numbers.

**Downhill: data and model**

- [ ] Key riders by UCI ID; parse the 2021 PDFs; add Women's categories, start order
      and weather.
- [ ] Check calibration (win probabilities look too flat); tune over all 43 rounds.
- [ ] Find a venue that lists downhill markets (none on Polymarket as of 2026-09).

**Platform**

- [ ] Sport schemas (`sports/*.yaml`) over one shared core, so the differences
      between sports are configuration, not code.
- [ ] Kalshi as a second exchange.
- [ ] Per-maker exposure limits, per-taker limits and ledgers.
- [ ] Condition in-weekend forecasts on completed rounds (Q1 results, split times).

<!-- /include -->
