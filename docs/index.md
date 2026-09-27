# racinglines

<!-- readme: tagline -->

**Fair prices for race sports, strictly as of any moment, tested on real market
tapes.** racinglines turns official timing into win, podium, head-to-head and
championship odds, then trades them against the market:

- **Formula 1** against Polymarket;
- **UCI downhill** mountain biking through a private book.

<!-- /readme -->

## At a glance

<!-- readme: glance -->

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

<!-- /readme -->

## Try it

1. **Open [racinglines.bet](https://racinglines.bet)** and click a demo
   button, or log in with the password `password`:
    - **Maker** (Markets · My Book · Lab · Pitch):
        - our fair price against every venue for each sport's next races and
          season;
        - quoting, backtests and strategy replays;
    - **Taker:** browse the makers' markets and bet at the quoted price.
2. **Run it locally**, then check the setup (about 10 seconds, nothing
   downloaded):

<!-- readme: quickstart -->

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

<!-- /readme -->

## What it does

<!-- readme: overview -->

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

<!-- /readme -->

## Results

<!-- readme: results-map -->

| Question | Answer | Details |
|---|---|---|
| How accurate is the F1 model? | Beats uniform everywhere and a grid-only guess on top 10. Loses to the grid on the win market after qualifying. | [Formula 1 → Results](f1.md#results) |
| Does practice data help? | Yes, a lot, before qualifying. | [Formula 1 → Results](f1.md#results) |
| Can it make money on Polymarket? | Making markets: +$751 over 2026. Taking: not yet. | [Market making → Season sweep](market-making.md#season-sweep) |
| What about the championship markets? | Season strategy: −$241 so far (holding does worse: −$532). | [Market making → Season strategy](market-making.md#season-strategy-championship-markets) |
| How accurate is the downhill model? | Better than uniform on podium and make-Final in every season; win odds too flat. | [Evaluation](evaluation.md) |
| Who wins the 2026 downhill title? | [Current forecast](forecast.md) | |

<!-- /readme -->

## Explore, one layer at a time

<!-- readme: layers -->

Each layer builds on the one before, so start at the top and stop when you
have what you need.

| Layer | Page | What's there |
|---|---|---|
| 1. **Data** | [Data](data.md) | Sources, what was downloaded, and the on-disk layout (`data/raw`, `archive`, `runs`, `cache`) |
| | [Parser](parser.md) | Downhill results formats and the tidy schema |
| | [Database](database.md) | The multi-sport schema, ingest, stored runs, and what stays in Postgres vs Parquet |
| 2. **Models** | [Formula 1](f1.md) | Car and driver pace, practice prior, finishing model, as-of pricing |
| | [Downhill model](model.md) | Log-time rider model, weekend formats, season simulation |
| 3. **Accuracy** | [Formula 1 → Results](f1.md#results) | 129-race backtest, A/B tests of each model change |
| | [Downhill evaluation](evaluation.md) | 43-round walk-forward, per season and per event |
| | [Downhill forecast](forecast.md) | The live 2026 title projection |
| 4. **Markets** | [Market making](market-making.md) | Baku diagnostic, maker replay, full-season sweep, season strategy |
| | [Web app & trading](webapp.md) | Roles, pages, the Lab, the private book, Polymarket orders |
| 5. **Operate** | [CLI reference](cli.md) | Every command and option |
| | [Testing](testing.md) | Quick check, regression suite, fixtures, golden outputs |
| 6. **Background** | [Project history](history.md) · [TODO](todo.md) | How it got here, and what's next |

<!-- /readme -->

## Building these docs

The top-level `README.md` is the short version. Parts of it are generated
from sections of these pages (see [Docs & README](cli.md#scriptsbuild_readmepy)).

<!-- readme: docs-build -->

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

<!-- /readme -->

On very new Pythons (e.g. 3.14), `watchdog` may have no prebuilt package and fail
to build. It's only needed for `mkdocs serve`'s live reload. Either use
Python ≤3.13, or install with `pip install --no-deps mkdocs mkdocs-get-deps`
plus mkdocs's other dependencies, then run `mkdocs build` and open
`site/index.html`.

## Repo layout

<!-- readme: repo-layout -->

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
| `tests/`, `scripts/fetch_test_fixtures.py` | Regression suite on fixtures built from public sources, plus golden outputs (see [Testing](testing.md)) |
| `scripts/build_readme.py` | Regenerates README sections from tagged docs sections |
| `docker-compose.yml` | Local PostgreSQL 17 (port 5433) |
| `pyproject.toml`, `requirements.txt`, `requirements-docs.txt` | Package (`pip install -e .` for the `racinglines` command); pinned dependencies (pipeline / docs site) |
| `data/` (not in git) | Downloads, the market archive, run outputs and caches |
| `docs/`, `mkdocs.yml` | Documentation site (MkDocs) |

<!-- /readme -->

<!-- readme: points-warning -->

!!! warning "Downhill points are placeholders"
    Downhill championship points use approximate tables, not the official UCI
    scale. Every downhill number measured in points (expected points,
    standings, champion odds) is approximate until
    [points validation](todo.md#points-validation) is done. Win, podium, top-10
    and make-Final probabilities don't depend on points.

<!-- /readme -->
