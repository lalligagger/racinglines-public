<!-- Captured by scripts/docs/capture_examples.py (id help-model, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 1.4 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines model -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
racinglines model <command> SPORT [options]   (pricing: forecasts, backtests, model comparisons, one-event diagnostics)

    forecast           f1 mtb_dh nascar motogp cycling Price the upcoming races with the sport's model.
    backtest           f1 mtb_dh                    Price past races as of before each one and score them against the results.
    walk-forward       mtb_dh                       Price every event through the shared engine (model-only): calibration per market kind.
    compare            f1 motogp                    A challenger model against the baseline, race by race.
    matrix             f1                           Every model variant x every trading strategy: accuracy (latest saved backtest per variant, paired vs baseline) and 2026 P&L (latest sweep + season strategy per variant).
    diagnostic         f1                           ONE PAST EVENT at a chosen cutoff (e.g. yesterday); saved as kind='diagnostic'.
    combo              f1                           Combo (same-game parlay) prices for one event (combo_job.py).
    props              f1                           Race props: safety car, red flag, rain, fastest lap (props.py).
    sprint-check       f1                           Walk-forward check of the sprint stage (models/sprint_check.py).
    season             nascar                       Cup season forecast (champion odds) from the points standings; read-only.
    price              cycling                      price an event's book
    reliability        cycling                      calibration check: favourites vs long shots, walk-forward
    search             motogp                       Sweep a small set of MotoGP recent-form settings and rank by mean log loss.

No data yet? Add --demo to any command, e.g. `racinglines model backtest kart --demo`: the same command on a synthetic demo store (docs/quickstart.md).

`racinglines model <command> SPORT -h` for a command's options.
```
<!-- --8<-- [end:output] -->
