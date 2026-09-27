# racinglines

<!-- readme: tagline -->

**Tools for an edge in race-sport prediction markets.** racinglines turns
official timing into win, podium, head-to-head and championship odds, priced
strictly as of any moment and tested on real market tapes, and gives makers and
takers the tools to find and size an edge inside the existing markets. Two
sports mark the ends of the range we build for:

- **Formula 1**, the big end: priced against Polymarket, with live paper trading
  from October 2026;
- **UCI downhill** mountain biking, the small end: modelled and forecast, waiting
  for an exchange to list it.

New sports qualify when their audience and expected market liquidity sit between
the two.

<!-- /readme -->

## At a glance

<!-- readme: glance -->

| | |
|---|---|
| 🏎️ **129 F1 races backtested** | 2021 to Azerbaijan 2026. Each race is priced before practice, before qualifying and after qualifying. After qualifying, top-10 Brier is **0.149** against 0.163 for a grid-only guess; the best variant also beats it on win and podium. |
| 💹 **Every Polymarket F1 race weekend, replayed** | 38 weekends (2025 and 2026) on the real prices and trade tape. The default maker made **+$751** on $8,969 filled in 2026. |
| ☁️ **1,161 strategy combinations searched** | A 4-hour cloud search found two setups that held up in both seasons: **A** (a taker, +$1,232 in 2026 / +$1,237 in 2025) and **C** (a maker, +$653 / +$835, the best Sharpe of any combination). |
| 📡 **Live paper trading** | A and C run on every F1 weekend from Malaysia (4 Oct 2026) through 2027, stage by stage, with heat ratings, alerts and paper positions, through the same code as the backtest (checked trade for trade). |
| 🚵 **43 downhill World Cup rounds** | 2021–2026, walk-forward. Error on who makes the Final is **38% lower** than a uniform guess (0.127 vs 0.204); the actual winner got **7.1%** on average, against ~1%. |
| ✅ **Checks in seconds** | `racinglines check` runs 21 checks (code, every data source, database) in ~10 s; the regression suite runs 174 tests on pinned public fixtures and golden outputs. |

The goal isn't to out-predict the market everywhere: on race-winner odds
Polymarket is about as sharp as the model (sharper after qualifying, and in 2025
at every stage). The tools act only where the gap is large, and quote where it's
safe. Nothing is traded with real money until paper trading has validated the
backtests. The pages below have the details.

<!-- /readme -->

## Try it

1. **Open [racinglines.bet](https://racinglines.bet)** and click a demo button
   (or log in with the password `password`); "I'm already confused." on the login
   page opens a plain-language introduction:
    - **Maker** (Markets · Strategy · Positions · My Book · Lab): our fair price
      against every venue for each sport's next races and season; its strategy's
      quotes, track record and decisions; backtests, the Edge Finder and strategy
      replays;
    - **Taker** (Markets · Strategy · Positions): every open Polymarket F1 market
      with its strategy's call and heat; its track record and positions.

    Both demo accounts carry a paper bankroll and a track record replayed from
    real weekends. Demo sessions are disposable: nothing a visitor changes is
    kept.
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
docker compose up -d                                   # PostgreSQL on localhost:5433 (or a conda Postgres: see Database)
racinglines db init                                    # tables + reference data

racinglines f1 fetch && racinglines f1 ingest          # F1 sessions (FastF1) -> database
racinglines f1 forecast --save                         # live F1 prices: remaining races + championships
racinglines markets sync                               # Polymarket's F1 markets

racinglines mtb_dh ingest                              # downhill event files -> database
racinglines mtb_dh forecast --db --save                # downhill season forecast

racinglines f1 profiles --assign-demo                  # strategy profiles A and C for the demo accounts
racinglines f1 signals                                 # live paper signals (outside a race weekend: a no-op)
ADMIN_PASSWORD=... racinglines web                     # the app on http://127.0.0.1:8000
```

<!-- /readme -->

## What it does

<!-- readme: overview -->

```
official timing ──> PostgreSQL ──> as-of model ──> simulated weekends ──> fair prices ──> markets
 (FastF1,           (one multi-     (only sessions   & seasons             (win, podium,   (Polymarket;
  ChronoRace)        sport schema)   ended before     (thousands of runs)   h2h, pole,      paper trading,
                                     the cutoff)                            titles)         replays, Lab)
```

- **Collects** official timing into one multi-sport **PostgreSQL** schema:
    - F1 via FastF1: every practice, qualifying, sprint and race session since
      2020;
    - downhill split timing from ChronoRace, 2021–2026.

  Exchange history (prices, trades, order books) goes to a **Parquet archive**.
- **Models** each sport:
    - **F1:** a sector-aware car model shared by both team drivers, driver
      offsets, a practice-pace prior, and a grid/overtaking finishing model, with
      challenger variants behind switches;
    - **Downhill:** a log-time model of each rider's pace, consistency and
      crash/DNF rate.
- **Simulates** race weekends and seasons thousands of times: win, podium,
  top 10, pole, head-to-head and team markets, plus championships.
- **Prices strictly as of a moment:** only sessions that have ended before the
  cutoff are used, and a leakage guard enforces it. Backtests, diagnostics, the
  live forecast and the signal engine all call the same function.
- **Tests strategies on real market data:** maker replays, taker strategies that
  re-trade after every session, and a season-long championship strategy, all on
  Polymarket's recorded prices and trades; settings searches run locally or in
  the cloud.
- **Paper trades live:** strategy profiles (A, a taker; C, a maker) produce
  signals at every stage of a race weekend, with heat ratings for takers,
  alerts, paper fills and positions. No real orders are placed.
- **Web app** ([racinglines.bet](https://racinglines.bet)):
    - **Markets:** makers see our fair price against each venue; takers see
      every Polymarket market with their strategy's call;
    - **Strategy** and **Positions:** the account's calls, track record, bankroll,
      P&L history and holdings;
    - **My Book:** in-app markets a maker quotes;
    - **Lab:** the Edge Finder, backtests, scenario forecasts, diagnostics and
      strategy replays with your own settings.

<!-- /readme -->

## Results

<!-- readme: results-map -->

| Question | Answer | Details |
|---|---|---|
| How accurate is the F1 model? | Beats uniform everywhere and a grid-only guess on top 10; the best variant also beats it on win and podium after qualifying. | [F1 evaluation](f1-evaluation.md) |
| How does it compare with Polymarket? | Close, which is the point: in 2026 better mid-weekend on race winners, worse after qualifying; in 2025 the market is sharper at every stage. The edge comes from the few large gaps. | [F1 evaluation → Against Polymarket](f1-evaluation.md#against-polymarket) |
| Can it make money on Polymarket? | In backtests, yes: the default maker +$751 over 2026; profiles A and C made money in both 2025 and 2026. Live paper trading is the test. | [Market making](market-making.md), [Paper trading](paper-trading.md) |
| Which model, traded which way? | A: the update taker on `gridq+pretrain+reset`, 10-point edges (5 on head-to-head), no pre-weekend stage. C: the conservative maker on `gbm`, 5-point filter, 25-share quotes. | [Market making → Cloud settings search](market-making.md) |
| What does F1 look like now? | The next race's favourites and the championship odds. | [F1 forecast](f1-forecast.md) |
| How accurate is the downhill model? | Better than uniform on podium and make-Final in every season; win odds too flat. | [Downhill evaluation](evaluation.md) |
| Who wins the 2026 downhill title? | [Downhill forecast](forecast.md) | |

<!-- /readme -->

## Explore, one layer at a time

<!-- readme: layers -->

Each layer builds on the one before, so start at the top and stop when you
have what you need. Every sport has a model, an evaluation and a forecast page;
F1, which has exchange markets, also has market pages.

| Layer | Page | What's there |
|---|---|---|
| 1. **Data** | [Data](data.md) | Sources, what was downloaded, the on-disk layout, and what's in git |
| | [Parser](parser.md) | Downhill results formats and the tidy schema |
| | [Database](database.md) | The multi-sport schema, ingest, stored runs, the snapshot, and what stays in Postgres vs Parquet |
| 2. **Formula 1** | [F1 model](f1.md) | Car and driver pace, practice prior, finishing model, as-of pricing |
| | [F1 evaluation](f1-evaluation.md) | 129-race backtest, model variants, against Polymarket |
| | [F1 forecast](f1-forecast.md) | The next race and the championships |
| | [Market making](market-making.md) | Maker replay, season sweeps, the model × strategy matrix, the cloud settings search, season strategy |
| | [Paper trading](paper-trading.md) | Profiles A and C, the signal engine, heat, alerts, the demo accounts |
| 3. **Downhill** | [Downhill model](model.md) | Log-time rider model, weekend formats, season simulation |
| | [Downhill evaluation](evaluation.md) | 43-round walk-forward, per season and per event |
| | [Downhill forecast](forecast.md) | The live 2026 title projection |
| 4. **Web app** | [Web app](webapp.md) | Pages and routes, roles, demo accounts and sessions, the Lab, the private book, Polymarket orders |
| 5. **Operate** | [CLI reference](cli.md) | Every command and option, launchd agents, scripts |
| | [Cloud sweeps](cloud-sweep.md) | Running settings searches on a cloud machine |
| | [Testing](testing.md) | Quick check, regression suite, fixtures, golden outputs |
| 6. **Background** | [Project history](history.md) · [TODO](todo.md) | How it got here, and what's next |
| | [F1 roadmap](f1-roadmap.md) · [F1 reference](f1-reference.md) | The phased F1 plan with its ground rules, and the model and market-making ideas behind it |

<!-- /readme -->

## Collaborators and beta testers

The GitHub repository is private for one reason: cloud runs need a minimal data
set committed with the code (see [Data](data.md)), and we don't want to publish
all of that data yet. We're open to beta testers and collaborators, and happy to
share the pipeline and web-app code with anyone interested: ask for access.

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
matches the docs, and no data outside the allow-list is tracked. Enable it once
per clone:

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
| `racinglines/sources/` | Data sources: `fastf1/` (fetch, ingest), `chronorace/` (download, parse, ingest), `http.py` (paced, retried requests for every source) |
| `racinglines/models/` | Model families: `position_sim/` (F1: car/driver pace, practice prior, variants, race and season pricing), `timed_runs/` (downhill: log-time model, weekend and season simulation) |
| `racinglines/markets/` | Exchanges and books: Polymarket `sync`/`trade`/`links`, the Parquet `store`, `venues`, the `private_book`, new-market and signal `alerts`, and `strategies/` (maker replay, weekend taker, season) |
| `racinglines/pipelines/` | Multi-stage runs: `weekend_sweep`, `sweep_settings`, `search` (settings searches), `season_strategy`, `season_checkpoints`, `profiles`, `signals` (live paper trading), `story` and `demo_history` (the demo accounts) |
| `racinglines/db/` | Database: models, reads, queries, shared ingest helpers, the `snapshot`, registry of sports and venues |
| `racinglines/web/` | The web app (`racinglines web`): Markets, Strategy, Positions, My Book, Lab, admin; demo sessions (`demo.py`); old-URL redirects (`legacy.py`) |
| `racinglines/testing/` | Synthetic data and the checks behind `racinglines check` |
| `sports/*.toml`, `racinglines/sports.py` | Sport schemas: what differs between sports (sessions, points, categories, venues, markets), read by the code |
| `racinglines/paths.py` | Where data lives (`data/raw`, `data/archive`, `data/runs`, `data/cache`) |
| `migrations/`, `alembic.ini` | Alembic schema migrations |
| `tests/`, `scripts/fetch_test_fixtures.py` | Regression suite on fixtures built from public sources, plus golden outputs (see [Testing](testing.md)) |
| `scripts/` | `build_readme.py`, `signals_parity.py`, `cloud/` (prepare and start a cloud run), launchd agents for the recorder and the signal engine, `hooks/pre-push` |
| `sweeps/` | Settings-search queues (TOML) |
| `docker-compose.yml` | Local PostgreSQL 17 (port 5433) |
| `pyproject.toml`, `requirements.txt`, `requirements-docs.txt` | Package (`pip install -e .` for the `racinglines` command); pinned dependencies (pipeline / docs site) |
| `data/` | Downloads, the market archive, run outputs and caches; only an allow-listed minimal set is in git (see [Data](data.md)) |
| `docs/`, `mkdocs.yml` | Documentation site (MkDocs) |
| `pitch.html` | The pitch deck, served at `/pitch` (screenshots in `racinglines/web/static/pitch/`) |

<!-- /readme -->

<!-- readme: points-warning -->

!!! warning "Downhill points are placeholders"
    Downhill championship points use approximate tables, not the official UCI
    scale. Every downhill number measured in points (expected points,
    standings, champion odds) is approximate until
    [points validation](todo.md#points-validation) is done. Win, podium, top-10
    and make-Final probabilities don't depend on points.

<!-- /readme -->
