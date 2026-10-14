<!-- Captured by scripts/docs/capture_examples.py (id help-backtest, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 1.0 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines backtest -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines backtest [-h] {walk-forward,coverage,clv} ...

racinglines backtest <command>: the backtest core for any sport with a pricing model (docs/backtest-core.md).

    walk-forward SPORT   price every event from data before it (racinglines/core/walk_forward.py), model-only:
                         calibration per market kind; --save stores it as a walk_forward model run (what a
                         search job runs). The sport's pricing model is named in sports/<code>.toml
                         ([sport] pricing_model), and its settings are its flags.

    racinglines backtest walk-forward mtb_dh --seasons 2025 --half-life-days 120 [--save]
    racinglines backtest walk-forward motogp --model global --seasons 2026     # the one engine at the results level
    racinglines backtest walk-forward nascar --model nascar_recent_form        # a challenger ([sport] challengers)
    racinglines backtest walk-forward f1 --model global --seasons 2025 2026 --venue polymarket kalshi
                         # also scores each venue's price beside the model's (model_vs_market): for F1 at the first
                         # stage, 1 h before any running (--market-stage 'after Quali' for another)

    coverage             read-only: per sport x exchange x market kind x season, the races linked, settled and taped
                         (prices, trades, books in Postgres and the Parquet archive) and the parity tier that gives;
                         season futures; per sport, the race results in the database and the declared results
                         sources (racinglines/pipelines/coverage.py, docs/parity-rebuild.md "C0")

    racinglines backtest coverage [--seasons 2025 2026] [--out DIR]

    clv                  read-only: closing-line value of every paper bet (strategy_signals: the taker's followed
                         trades, the maker's fills) on any sport and venue, per bet and per sport x venue x kind x
                         strategy x profile: bets, mean CLV, share positive (racinglines/pipelines/clv.py, "C4")

    racinglines backtest clv [--user NAME ...] [--sport nascar] [--venue kalshi] [--event KEY] [--asof UTC] [--summary] [--json]
                             [--out DIR]

positional arguments:
  {walk-forward,coverage,clv}
    walk-forward        Price every event through the shared engine (model-only).
    coverage            Read-only: linked, settled and taped races per sport, exchange, kind and
                        season.
    clv                 Read-only: closing-line value per paper bet, and per sport, venue, kind
                        and profile.

options:
  -h, --help            show this help message and exit
```
<!-- --8<-- [end:output] -->
