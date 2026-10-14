<!-- Captured by scripts/docs/capture_examples.py (id backtest-coverage-demo, scripts/docs/examples.toml) on 2026-10-14 05:07 UTC, commit 4313bf1+dirty, 1.5 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines backtest coverage --demo
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
database racinglines_demo_kart · data /home/user/racinglines-public/data/demo/kart · archive trees: /home/user/racinglines-public/data/demo/kart/archive/markets/kalshi, /home/user/racinglines-public/data/demo/kart/archive/markets/polymarket
  prices postgres            0 rows · parquet            0 rows in 0 files
  trades postgres            0 rows · parquet            0 rows in 0 files
  books  postgres            0 rows · parquet            0 rows in 0 files
  no market tape here: every price/trade/book count below is 0

=== Race markets (tier at 8+ races a season with both a settlement and a price tape; maker_tier needs a book tape) ===
sport   exchange        kind  season  links  races  settled_races  price_races  trade_races  book_races    tier maker_tier modeled  unmodeled_links
   f1     kalshi     race_p2    2026     33      3              0            0            0           0 missing    missing      no                0
   f1     kalshi race_podium    2026     49      3              0            0            0           0 missing    missing     yes                0
   f1     kalshi    race_win    2026     43      3              0            0            0           0 missing    missing     yes                0
   f1 polymarket    race_h2h    2026     30      3              0            0            0           0 missing    missing     yes                0
   f1 polymarket race_podium    2026     49      3              0            0            0           0 missing    missing     yes                0
   f1 polymarket   race_pole    2026     17      3              0            0            0           0 missing    missing     yes                0
   f1 polymarket    race_win    2026     60      3              0            0            0           0 missing    missing     yes                0
combos per tier: parity-2 0, parity-1 0, thin 0, missing 7

=== Season futures (no race) ===
none linked

=== Results depth and sources (per sport) ===
       sport  first_season  last_season  events  events_with_results  results_source                fallbacks source_modules cleared
      mtb_dh          <NA>         <NA>       0                    0                                              chronorace     yes
          f1          2024         2026      36                   33        f1timing                                  fastf1     yes
      nascar          <NA>         <NA>       0                    0       nascar_cf wikipedia (summary_only)         nascar     yes
      motogp          <NA>         <NA>       0                    0      motogp_api                                  motogp     yes
     indycar          <NA>         <NA>       0                    0                                                 indycar      no
road_cycling          <NA>         <NA>       0                    0 procyclingstats                                     pcs     yes
     le_mans          <NA>         <NA>       0                    0                                                     wec      no
      sailgp          <NA>         <NA>       0                    0                                                  sailgp      no

More results deepen the models' training (walk-forward burn-in); P&L backtests also need market tape, which starts when recording began.
```
<!-- --8<-- [end:output] -->
