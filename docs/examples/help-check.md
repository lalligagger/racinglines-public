<!-- Captured by scripts/docs/capture_examples.py (id help-check, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 0.5 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines check -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines check [-h] [--sport {f1,mtb_dh}] [--offline] [--no-db]

racinglines check: quick validation for new setups (about a minute, no data downloaded).

    code       the pipelines on small synthetic data (no network, no database)
    endpoints  one tiny request to each data source (FastF1, ChronoRace, Polymarket)
    database   Postgres reachable and migrated (skipped with --no-db)

Options: --sport f1|mtb_dh (default both) --offline (skip endpoints) --no-db
The full regression suite on real data: docs/testing.md.

options:
  -h, --help           show this help message and exit
  --sport {f1,mtb_dh}  Default: both.
  --offline            Skip the data-endpoint checks.
  --no-db              Skip the database check.
```
<!-- --8<-- [end:output] -->
