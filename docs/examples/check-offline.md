<!-- Captured by scripts/docs/capture_examples.py (id check-offline, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 5.9 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines check --offline
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
code (synthetic data)
  ✓ f1 code                load + measurements                      0.3s  6 events, 7,485 laps, 360 practice rows
  ✓ f1 code                as-of leakage guard                      0.0s  sessions only usable after they end
  ✓ f1 code                training history                         0.6s  120 training rows
  ✓ f1 code                race pricing                             1.2s  favourite Driver 01 36%
  ✓ f1 code                backtest                                 0.6s  6 race x mode rows, mean win Brier 0.032
  ✓ f1 code                season forecast                          0.3s  leader Driver 01 71%
  ✓ markets code           maker replay                             0.0s  172 fills, P&L +72.56
  ✓ markets code           weekend taker                            0.0s  46 trades, P&L +300.15
  ✓ markets code           season strategy                          0.2s  39 trades, P&L -93.55
  ✓ mtb_dh code            parse results tables                     0.1s  1920 rows, 60 riders, rounds ['final', 'practice', 'qual1']
  ✓ mtb_dh code            season model                             0.2s  sigma 0.0096, 60 riders
  ✓ mtb_dh code            season forecast                          0.2s  leader 69%
  ✓ mtb_dh code            backtest                                 0.2s  1 held-out round(s) scored

database
  ✓ database               Postgres                                 0.2s  localhost:5433/racinglines, schema up to date

14/14 checks passed
```
<!-- --8<-- [end:output] -->
