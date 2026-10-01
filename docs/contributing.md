# Contributing

Thanks for wanting to help! racinglines is in beta, and we're looking for beta testers and collaborators.
This page is a starting point: **more detail is coming.** Questions, ideas or "I'd like to help with X":
[hello@racinglines.bet](mailto:hello@racinglines.bet?subject=racinglines%20contributor).

## Data in this repository

<!-- readme: public-data -->
This public repository (`lalligagger/racinglines-public`) holds **code, docs, schemas and golden test outputs
only**. The data it was developed with (raw FastF1 sessions, the Polymarket and Kalshi price and trade archives,
database snapshots, the pinned test fixtures) was removed from this repository and its history when it went public
on 2026-10-01: some of it isn't ours to republish, and none of it belongs in git. It lives on the production
server and in a private bucket.

**Test fixtures are available to beta testers and contributors.** Two ways to get them:

- **Ask us** at [hello@racinglines.bet](mailto:hello@racinglines.bet?subject=racinglines%20test%20fixtures)
  for the pinned fixture bundle (about 2 MB). Unpacked into `tests/fixtures/`, the regression suite matches the
  golden outputs exactly.
- **Build them yourself** from the original public sources with `python scripts/fetch_test_fixtures.py --refresh`
  (needs Postgres; the F1 part can take up to an hour because FastF1 is rate limited). Today's data differs a
  little from the pinned set, so expect some golden tests to differ: that's fine for development.

Without fixtures the fixture-based tests are skipped, not failed, and everything else runs.
<!-- /readme -->

## Getting set up

1. Python 3.12 and Docker (for Postgres).
2. Clone, then install the pinned environment:
   ```
   git clone https://github.com/lalligagger/racinglines-public racinglines && cd racinglines
   python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && pip install -e .
   ```
3. Start the database and check the install: `docker compose up -d && racinglines check`.
4. Run the tests: `python -m pytest -m "not live"` ([Testing](testing.md)). With the fixtures (above), this is
   the full regression suite.
5. Run the web app locally: `racinglines web`, then open <http://127.0.0.1:8000>.

## Making a change

- Branch off `main`; one topic per pull request. `main` deploys to racinglines.bet through CI on every merge, so
  only the owner merges.
- **New behaviour ships behind a switch that is off by default** (an `RACINGLINES_*` environment variable), and
  existing outputs stay byte-identical unless the change is meant to move them (then re-baseline with
  `UPDATE_GOLDEN=1` and explain the diff).
- Before opening a PR: `racinglines check`, `python -m pytest -m "not live"` and `mkdocs build --strict`.
- Never commit data: `tests/test_no_data_in_git.py` fails the build if you do.
- Docs live in `docs/`; parts of `README.md` are generated from them (`python scripts/build_readme.py`).

## Where to start

- [Sports and exchanges (status)](coverage.md): what's covered and what isn't yet.
- [Adding a sport](add-a-sport.md) and [Exchanges as schemas](exchanges.md): most new venues are a config file.
- [Priorities and open items](todo.md): the current list.

*More coming: code layout, how the models and backtests fit together, and good first issues.*
