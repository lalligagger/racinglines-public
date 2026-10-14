<!-- Captured by scripts/docs/capture_examples.py (id model-backtest-kart-demo, scripts/docs/examples.toml) on 2026-10-14 05:06 UTC, commit 4313bf1+dirty, 44.9 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines model backtest kart --demo
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
progress 0/1 building history (track features on)
📊 backtest, track features on
progress 10/33 2024 R10 rainbow-road
progress 20/33 2025 R08 mount-wario
progress 30/33 2026 R06 thwomp-ruins
progress 33/33 2026 R09 bowser-s-castle
📊 Track features ON: mean over 32 races
╭────────┬─────────────┬─────────────┬─────────┬────────┬──────────────────┬──────────╮
│ market │ stage       │ model Brier │ uniform │   grid │ skill vs uniform │ log loss │
├────────┼─────────────┼─────────────┼─────────┼────────┼──────────────────┼──────────┤
│ win    │ pre weekend │      0.0431 │  0.0475 │      – │   ▉          +9% │   0.1518 │
│        │ pre quali   │      0.0405 │  0.0475 │      – │  █▍         +15% │   0.1388 │
│        │ pre race    │      0.0381 │  0.0475 │ 0.0410 │  █▉         +20% │   0.1266 │
├────────┼─────────────┼─────────────┼─────────┼────────┼──────────────────┼──────────┤
│ podium │ pre weekend │      0.0988 │  0.1275 │      – │  ██▎        +23% │   0.3155 │
│        │ pre quali   │      0.0913 │  0.1275 │      – │  ██▊        +28% │   0.3058 │
│        │ pre race    │      0.0772 │  0.1275 │ 0.0824 │  ███▉       +39% │   0.2699 │
├────────┼─────────────┼─────────────┼─────────┼────────┼──────────────────┼──────────┤
│ top10  │ pre weekend │      0.1662 │  0.2500 │      – │  ███▎       +34% │   0.5105 │
│        │ pre quali   │      0.1543 │  0.2500 │      – │  ███▊       +38% │   0.4897 │
│        │ pre race    │      0.1295 │  0.2500 │ 0.1345 │  ████▊      +48% │   0.4353 │
╰────────┴─────────────┴─────────────┴─────────┴────────┴──────────────────┴──────────╯
🏁 favourite won 34% of 32 races · rank correlation 0.83 · mean winner probability 22.7%
   best call  2024 R04 Royal Raceway: Donkey Kong won at 48.6%
   upset      2024 R08 Mount Wario: Donkey Kong won at 1.7% (favourite Peach)
progress 0/1 building history (track features off)
📊 backtest, track features off
progress 10/33 2024 R10 rainbow-road
progress 20/33 2025 R08 mount-wario
progress 30/33 2026 R06 thwomp-ruins
progress 33/33 2026 R09 bowser-s-castle
📊 Track features OFF: mean over 32 races
╭────────┬─────────────┬─────────────┬─────────┬────────┬──────────────────┬──────────╮
│ market │ stage       │ model Brier │ uniform │   grid │ skill vs uniform │ log loss │
├────────┼─────────────┼─────────────┼─────────┼────────┼──────────────────┼──────────┤
│ win    │ pre weekend │      0.0437 │  0.0475 │      – │   ▊          +8% │   0.1629 │
│        │ pre quali   │      0.0407 │  0.0475 │      – │  █▍         +14% │   0.1391 │
│        │ pre race    │      0.0377 │  0.0475 │ 0.0410 │  ██         +21% │   0.1240 │
├────────┼─────────────┼─────────────┼─────────┼────────┼──────────────────┼──────────┤
│ podium │ pre weekend │      0.1033 │  0.1275 │      – │  █▉         +19% │   0.3356 │
│        │ pre quali   │      0.0915 │  0.1275 │      – │  ██▊        +28% │   0.3104 │
│        │ pre race    │      0.0768 │  0.1275 │ 0.0824 │  ███▉       +40% │   0.2650 │
├────────┼─────────────┼─────────────┼─────────┼────────┼──────────────────┼──────────┤
│ top10  │ pre weekend │      0.1879 │  0.2500 │      – │  ██▍        +25% │   0.5659 │
│        │ pre quali   │      0.1573 │  0.2500 │      – │  ███▋       +37% │   0.4944 │
│        │ pre race    │      0.1296 │  0.2500 │ 0.1345 │  ████▊      +48% │   0.4326 │
╰────────┴─────────────┴─────────────┴─────────┴────────┴──────────────────┴──────────╯
🏁 favourite won 38% of 32 races · rank correlation 0.83 · mean winner probability 23.1%
   best call  2024 R04 Royal Raceway: Donkey Kong won at 52.3%
   upset      2024 R08 Mount Wario: Donkey Kong won at 1.6% (favourite Peach)

Per-race rows -> /home/user/racinglines-public/data/demo/kart/runs/f1/backtests/backtest_20261014_0506.csv
```
<!-- --8<-- [end:output] -->
