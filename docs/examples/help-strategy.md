<!-- Captured by scripts/docs/capture_examples.py (id help-strategy, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 1.4 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines strategy -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
racinglines strategy <command> SPORT [options]   (trading: replays against exchange tapes, season sweeps, paper signals, strategy searches)

    replay             f1 nascar motogp             Replay a strategy against an exchange's recorded prices.
    sweep              f1 nascar motogp             The season sweep: the taker modes and maker variants through each race's weekend.
    season-replay      nascar motogp                Champion markets replayed through the season.
    season-strategy    f1                           Default championship-market strategy through the season: as-of season forecasts pre-season and after every race, trades at Polymarket's recorded prices (+ spread and slippage), settles eliminated markets, marks the rest.
    season-checkpoints f1                           Championship markets entered at fixed points (pre-season, after 3 and after 6 grands prix) and held, per model variant:
    scorecard          f1                           Pricing scorecard of an exchange weekend (pipelines/scorecard.py): the stored stage runs' fair values vs the result and vs the venue's mid at each stage.
    signals            f1 nascar motogp             Live paper signals of users' strategy profiles (recommendations only).
    demo-history       f1 nascar motogp             Backfill the demo accounts' track record from backtest replays.
    reconcile          f1                           One account's live paper weekend against the backtest's replay of it on the recorded tape (pipelines/reconcile.py; docs/paper-trading.md, rule 1).
    profiles           f1                           List strategy profiles; create A / C / K as Lab candidates if missing.
    search             f1
    search-report      f1
    search-import      f1
    search-analyze     f1                           Analyze saved F1 sweep-search runs and write report artifacts (curves, rankings, charts, noise, HTML; beside search-report).
    live               mtb_dh                       Follow a final live from UCI timing: rank probabilities, the maker's quotes, the private book's crowd (pipelines/live_dh.py).

`racinglines strategy <command> SPORT -h` for a command's options.
```
<!-- --8<-- [end:output] -->
