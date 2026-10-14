<!-- Captured by scripts/docs/capture_examples.py (id help-model-backtest-kart, scripts/docs/examples.toml) on 2026-10-14 05:12 UTC, commit 3ed9335+dirty, 0.7 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines model backtest kart --demo -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines model backtest f1 [-h] [--start-year START_YEAR] [--sims SIMS] [--no-track]
                                     [--out OUT] [--save] [--races RACES] [--track {both,on,off}]

options:
  -h, --help            show this help message and exit
  --start-year START_YEAR
  --sims SIMS
  --no-track            Only the run without track features.
  --out OUT             Per-race rows CSV (default data/runs/f1/backtests/).
  --save                Store as a model run (kind='backtest').
  --races RACES         Only the last N races (quick runs).
  --track {both,on,off}
                        Track features: compare both, or one.
```
<!-- --8<-- [end:output] -->
