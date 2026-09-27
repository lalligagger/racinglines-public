# Testing

Three levels, fastest first:

| | What | Time | Needs |
|---|---|---|---|
| **Quick check** | `racinglines check` (or `python -m pytest -m quick`) | ~10 s | nothing downloaded; network and Postgres optional |
| **Regression suite** | `python -m pytest -m "not live"` on fixtures from `scripts/fetch_test_fixtures.py` | ~10 s (+ fixture build once) | Postgres, a one-time download |
| **Live tests** | `python -m pytest` | ~35 s | the working database |

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
python scripts/fetch_test_fixtures.py [--f1] [--mtb]   # once: download + build the test fixtures (default: both)
python -m pytest -m "not live"                         # regression suite on the fixtures, ~10 s
python -m pytest                                       # everything, incl. live-database smoke tests, ~35 s
UPDATE_GOLDEN=1 python -m pytest                       # re-baseline after an intended change
```

## No data in git

Nothing data-shaped is committed:

- raw downloads (FastF1, ChronoRace, Polymarket);
- derived tables;
- test fixtures;
- golden baselines.

`.gitignore` covers `data/`, `tests/fixtures/`, `tests/golden/` and data file
types, and `tests/test_no_data_in_git.py` fails if anything data-like is tracked
or about to be added.

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
- **Not committed:** golden files contain derived results (names, positions,
  times), so they stay local.
- **Workflow:** fetch the fixtures and run the suite once (this writes your
  baseline), then make changes and run it again. Any output change fails with
  the path of the first differing value.
- **Only code can change results:** new data arriving doesn't touch the
  fixtures.
- **Ingest tests** build `racinglines_test` from the migrations and never touch
  the live database (`TEST_DATABASE_URL` overrides).
- **Live tests** read the live database and are marked `live`: page smoke
  tests, Baku live-data checks, and the hot-token retention check.

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
