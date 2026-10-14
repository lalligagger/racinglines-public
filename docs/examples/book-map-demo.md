<!-- Captured by scripts/docs/capture_examples.py (id book-map-demo, scripts/docs/examples.toml) on 2026-10-14 05:07 UTC, commit 4313bf1+dirty, 1.6 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines book map --demo
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
demo: the demo store's synthetic data (made-up names, results and prices); nothing is traded
                                              book map

  id            selection             kind                 status       race   reason
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  win           Super Mario           race_win             mapped         34
  win-no        Luigi not to win      race_win             mapped         34
  podium        Peach                 race_podium          mapped         34
  top5          Daisy                 race_top5            mapped         34
  top10         Bowser                race_top10           mapped         34
  p2            Luigi                 race_p2              mapped         34
  pole          Mario                 race_pole            mapped         34
  fl            Luigi                 race_fastest_lap     mapped         34
  h2h           Daisy v Peach         race_h2h             mapped         34
  mover         Yoshi                 race_biggest_mover   mapped         34
  spr-win       Mario                 race_sprint_win      mapped         34
  spr-pole      Luigi                 race_sprint_pole     mapped         34
  red           No                    race_red_flag        mapped         34
  sgp-joint     Mario win + Luigi     combo                mapped         34
                podium
  └ 14.1        race_win Mario  (f1                        mapped         34
                2026-10)
  └ 14.2        race_podium Luigi                          mapped         34
                (f1 2026-10)
  sgp-product   Peach podium +        combo                mapped         34
                Daisy top 10
  └ 15.1        race_podium Peach                          mapped         34
                (f1 2026-10)
  └ 15.2        race_top10 Daisy                           mapped         34
                (f1 2026-10)
  parlay        Mario wins Rainbow    combo                mapped     34, 35
                Road and Wario
                Stadium
  └ 16.1        race_win Mario  (f1                        mapped         34
                2026-10)
  └ 16.2        race_win Mario  (f1                        mapped         35
                2026-11)
  typo          Maryo                 race_win             unmapped       34   leg 17: driver
                                                                               'Maryo' is not an
                                                                               exact name in race
                                                                               34's field
  └ 17          race_win  (f1                              unmapped       34   driver 'Maryo' is
                2026-10)                                                       not an exact name
                                                                               in race 34's field

          book_demo · event 2026-10 · f1 · captured 2026-10-15T09:00Z · odds decimal · USD
╭────────────────── unmapped lines ───────────────────╮
│ typo                                                │
│ exact keys only: fix the book file or its [aliases] │
╰─────────────────────────────────────────────────────╯
```
<!-- --8<-- [end:output] -->
