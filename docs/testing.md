# Testing

<!-- readme: validation -->

Three levels, fastest first:

| | Command | Checks | Time | Needs |
|---|---|---|---|---|
| **Quick check** | `racinglines check` | 21 checks: every pipeline on synthetic data, every data source, the database | ~10 s | nothing downloaded; network and Postgres optional |
| **Regression suite** | `python -m pytest -m "not live"` | 174 tests: every pipeline stage on pinned F1 and downhill fixtures, compared with golden outputs | ~10 s | Postgres (fixtures and goldens are in git) |
| **Everything** | `python -m pytest` | 221 tests, adding 47 live tests on the working database: the web app's pages per role, Baku live data, retention | ~35 s | the working database |

- **Pinned in git (since 2026-09-28):** the test fixtures (2 MB, built from FastF1,
  ChronoRace and Polymarket) and the golden outputs, so every machine and cloud session
  compares against the same baseline. A guard test fails if any other data is tracked.
- **Results can't drift silently:** an intended change is re-baselined with
  `UPDATE_GOLDEN=1` and reviewed as a diff of `tests/golden/` in its PR.

<!-- /readme -->

## Quick check (new setups)

```
racinglines check                       # code on synthetic data + data endpoints + database
racinglines check --offline --no-db     # code only
racinglines check --sport f1            # one sport
```

- **Code:** runs the real pipelines on small synthetic data
  (`racinglines/testing/synthetic.py`: a fake F1 season with practice,
  qualifying and race laps; downhill results files in ChronoRace's format; fake
  exchange tapes) and checks that the results make sense:
    - probabilities sum as they should;
    - the as-of view refuses a session still in progress;
    - P&L accounting adds up;
    - capital caps hold.
- **Endpoints:** one tiny request to each data source: FastF1's schedule, the
  F1 live-timing archive, ChronoRace, the Wikipedia calendar page, and
  Polymarket's Gamma, CLOB and Data APIs.
- **Database:** Postgres is reachable and the schema is at the latest migration.
- **No data is downloaded or stored.**

## Regression suite

```
python -m pytest -m "not live"                         # regression suite on the pinned fixtures, ~10 s
python -m pytest                                       # everything, incl. live-database smoke tests, ~35 s
UPDATE_GOLDEN=1 python -m pytest -m "not live"         # re-baseline after an intended change; commit tests/golden
python scripts/fetch_test_fixtures.py --refresh [--f1] [--mtb]   # rarely: rebuild the fixtures from today's data
```

A fixture refresh pulls today's data (FastF1 revises laps after a race, new rounds get raced), so it
changes golden outputs even with no code change. That's why it needs `--refresh`, is logged in the
[data change log](data-changes.md), and goes in its own commit: fixtures and re-baselined goldens
together, reviewed apart from code changes.

```
```

## No data in git

Nothing data-shaped is committed except the minimal allow-listed set cloud sweeps
need (see [What's in git](data.md#whats-in-git)), the test fixtures and the golden baselines.
Never committed:

- the fixture build's raw downloads (`tests/fixtures/_work/`);
- downhill downloads, order books, run outputs, logs;
- derived tables.

`.gitignore` covers `data/*` (then allow-lists `data/raw/f1`,
`data/archive/markets/polymarket/{prices,trades,links}`, `data/archive/markets/kalshi/{prices,trades,links}`,
`data/archive/db` and
`data/runs/search`, then `tests/fixtures/` minus `_work/`), and data file types.
`tests/test_no_data_in_git.py` fails if anything data-like outside the allow-list
is tracked or about to be added.

## Pre-push hook

`scripts/hooks/pre-push` runs before every push. Enable it once per clone with
`git config core.hooksPath scripts/hooks`; skip it in an emergency with
`git push --no-verify`. Steps, stopping at the first failure:

1. `python scripts/build_readme.py --check`: `README.md` matches the docs.
2. `python -m mkdocs build --strict`: the docs build with no warnings (broken links
   and anchors fail). Needs `requirements-docs.txt`.
3. `python -m pytest -q tests/test_no_data_in_git.py`: no data outside the allow-list.

It uses `.venv/bin/python` when present, else `python3`.

## Fixtures: built locally from the public sources

`scripts/fetch_test_fixtures.py` downloads only what the tests need from the
original sources, into a throwaway database (`racinglines_fixtures`, rebuilt
from the migrations), then builds `tests/fixtures/` with this repo's own
pipeline:

| Flag | Downloads | Builds |
|---|---|---|
| `--f1` | FastF1: 2026 rounds 6–15 (qualifying, sprint, race, practice). Polymarket: Monza and Baku race markets (5-minute prices, trades) and the championship markets (hourly prices). | F1 model tables, Baku's raw session files, the Baku maker-replay tape with as-of fairs, two weekends of sweep markets, and ten season-strategy markets with their as-of decisions |
| `--mtb` | ChronoRace: 18 World Cup events of 2025–26, Elite and Junior men | Two sample result files and the 2025–26 training slice |

- **FastF1 is rate limited** (500 calls/hour), so a cold `--f1` run can take up
  to an hour.
- **Resumable:** raw downloads stay in `tests/fixtures/_work/`, so re-runs are
  quick.
- **Needs** Postgres (`docker compose up -d`). `FIXTURE_DATABASE_URL`
  overrides the database.

## Golden baselines

- **What they hold:** each stage writes a compact fingerprint of its output to
  `tests/golden/<stage>.json`, compared within a relative tolerance of 1e-6.
  Seeds are fixed and simulations small (1,000–2,000 runs).
- **Committed** (since 2026-09-28; the repo is private): the goldens were local
  before, so a code change could pass in the cloud and break only the owner's
  baseline. The first shared baseline is the owner's of 2026-09-26, re-baselined
  for the approved downhill defaults (prior_n 0.5, half-life 240 days, junior
  weight 0.25), which changed the five downhill model goldens and nothing else.
- **Workflow:** make changes and run the suite. Any output change fails with the
  path of the first differing value; if intended, `UPDATE_GOLDEN=1` and commit
  the golden diff with the change.
- **Only code can change results:** new data arriving doesn't touch the pinned
  fixtures; a `--refresh` does, on purpose.
- **Ingest tests** build `racinglines_test` from the migrations and never touch
  the live database (`TEST_DATABASE_URL` overrides).
- **Live tests** read the live database and are marked `live` (47 tests): page
  smoke tests, Baku live-data checks, and the hot-token retention check.

## Stages covered

| Pipeline | Stage | Test |
|---|---|---|
| F1 | Raw FastF1 files (schema, sizes, meta) | `test_pipeline_f1::test_raw_files` |
| F1 | Ingest a weekend into a fresh DB, read back | `test_ingest` |
| F1 | Measurements: qualifying / race pace, sectors, practice | `test_measurements` |
| F1 | Car + driver model at a cutoff (team sector fits, paces, DNF) | `test_car_model` |
| F1 | Training history, finishing model, teammate correlation, practice blend | `test_history_and_finishing_model` |
| F1 | Race pricing before practice / after FP3 / after qualifying | `test_price_race[…]` |
| F1 | Backtest (3 races × 3 modes) | `test_backtest` |
| F1 | Championship forecast | `test_season_forecast` |
| F1 | Weekend taker strategies (update / hold / after-quali) | `test_weekend_trading` |
| F1 | Maker replay on the Baku tape (touch / through) | `test_maker_replay` |
| F1 | Season strategy (update / hold) | `test_season_strategy` |
| F1 | Model variants: switches set and restore, every variant prices through the leakage guards | `test_variants` |
| F1 | Comparison tools: paired ± 2 SE, reliability bins, calibration error | `test_variants` |
| F1 | Maker options (flatten before qualifying, info-timed skew, per-kind spreads), stage-aware taker | `test_replay`, `test_rebalance` |
| All | Sport schemas: required keys, modules read their values | `test_sports` (quick) |
| Downhill | Parser: results tables | `test_pipeline_mtb::test_parse_results_tables` |
| Downhill | Ingest into a fresh DB, tidy frame | `test_ingest_and_tidy` |
| Downhill | Season model fit | `test_season_model` |
| Downhill | Weekend simulation | `test_weekend_simulation` |
| Downhill | Season forecast, backtest, walk-forward | `test_season_forecast`, `test_backtest`, `test_walk_forward` |

**Rule tests** sit alongside the golden ones:

- leakage: sessions are usable only after they end, and no future data reaches
  a view;
- replay and strategy rules;
- limits and accounting;
- the Parquet store;
- job-form validation.

The suite was checked by deliberately changing one constant at a time. Each
change failed exactly the stages downstream of it:

| Change | Stages that failed |
|---|---|
| F1 driver-offset shrinkage | 7 F1 stages |
| Downhill half-life | 5 downhill stages |
| Maker quoting spread | maker replay |
| Taker trading cost | weekend trading |

## Test files

`tests/`, with the number of tests in each (`python -m pytest --co`):

| File | Tests | What it covers |
|---|---|---|
| `test_alerts.py` | 11 | New-market alerts (`markets/alerts.py`): race matching, grouping, the message, the log. |
| `test_baku.py` | 16 | Live: the 2026 Azerbaijan GP in the working database (diagnostic runs, Polymarket tape). |
| `test_edge.py` | 8 | Edge Finder combo edits (`web/edge.py`); no database. |
| `test_f1_car.py` | 4 | F1 model: the car is shared by teammates. |
| `test_http.py` | 5 | Polite HTTP (`sources/http.py`): per-host pacing and retries, with a fake client. |
| `test_kalshi.py` | 13 | Kalshi connector on mocked responses shaped like the live API (2026-09-28): client paging and prices, title classifier, link / trade / history / book rows, `/historical` endpoints, the order gate, the backtest venue per market ticker, and the maker fee. |
| `test_live_dh.py` | 4 | Live downhill finals (`pipelines/live_dh.py`): rank probabilities, quotes, safe riders, the crowd's budgets and P&L; synthetic riders, no network. |
| `test_marketstore.py` | 6 | Parquet market store: archive from Postgres (Kalshi's tokens to Kalshi's archive), merged reads, dedupe (one live retention check). |
| `test_no_data_in_git.py` | 2 | Guard: no data tracked or about to be, outside the allow-list. |
| `test_pipeline_f1.py` | 13 | F1 regression suite: every stage on pinned fixtures against golden outputs. |
| `test_pipeline_mtb.py` | 7 | Downhill regression suite: every stage on pinned fixtures against golden outputs. |
| `test_practice.py` | 6 | Practice-pace prior: leakage and behaviour on the pinned F1 fixture. |
| `test_quick.py` | 1 | The quick checks as a test (`racinglines check --offline --no-db`). |
| `test_rebalance.py` | 8 | Weekend taker strategy (`taker_weekend.py`) on synthetic stages. |
| `test_replay.py` | 41 | Maker replay (`maker_replay.py`) on synthetic tapes. |
| `test_search.py` | 6 | Search queue (`pipelines/search.py`): parsing, the automatic baseline, job identity, command lines. |
| `test_season_strategy.py` | 10 | Season-long strategy replay on synthetic markets. |
| `test_signals.py` | 24 | Paper signals (`pipelines/signals.py`): heat, taker signals = the backtest taker's trades, maker quote state, same-second maker fills kept apart, stage truncation, idempotent storage, profiles. |
| `test_sports.py` | 3 | Sport schemas (`sports/*.toml`) and the modules that read them. |
| `test_story.py` | 4 | The demo maker's decision rules (`pipelines/story.py`) on synthetic evidence. |
| `test_sweep_settings.py` | 9 | Sweep settings schema: defaults, validation, identity keys, command-line round trip, settings applied and restored. |
| `test_variants.py` | 9 | Model variants and the comparison tools (paired ± 2 SE, reliability). |
| `test_views.py` | 30 | Live: web app page smoke tests per role, and job-form validation. |

Helpers: `conftest.py` (pinned inputs and the throwaway test database) and
`golden.py` (golden-output comparison, `UPDATE_GOLDEN=1`).

Replay-vs-sweep parity on a real weekend needs the full database and minutes of
pricing, so it is a script, not a test: `scripts/signals_parity.py` (see
[CLI](cli.md#scripts)).
