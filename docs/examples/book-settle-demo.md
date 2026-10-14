<!-- Captured by scripts/docs/capture_examples.py (id book-settle-demo, scripts/docs/examples.toml) on 2026-10-14 05:07 UTC, commit 4313bf1+dirty, 1.8 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines book settle --demo
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
demo: the demo store's synthetic data (made-up names, results and prices); nothing is traded
                                         book settle

  id            selection                                   odds   result    payout   profit
 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  win           Super Mario                                 3.20   pending        –        –
  win-no        Luigi not to win                            1.30   pending        –        –
  podium        Peach                                       2.40   pending        –        –
  top5          Daisy                                       1.90   pending        –        –
  top10         Bowser                                      1.25   pending        –        –
  p2            Luigi                                       4.50   pending        –        –
  pole          Mario                                       2.75   pending        –        –
  fl            Luigi                                       5.00   manual         –        –
  h2h           Daisy v Peach                               2.10   pending        –        –
  mover         Yoshi                                       6.00   pending        –        –
  spr-win       Mario                                       2.90   pending        –        –
  spr-pole      Luigi                                       4.00   pending        –        –
  red           No                                          1.45   manual         –        –
  sgp-joint     Mario win + Luigi podium                    4.20   pending        –        –
  └ 14.1        race_win Mario  (f1 2026-10)                       pending
  └ 14.2        race_podium Luigi  (f1 2026-10)                    pending
  sgp-product   Peach podium + Daisy top 10                 2.50   pending        –        –
  └ 15.1        race_podium Peach  (f1 2026-10)                    pending
  └ 15.2        race_top10 Daisy  (f1 2026-10)                     pending
  parlay        Mario wins Rainbow Road and Wario Stadium   9.60   pending        –        –
  └ 16.1        race_win Mario  (f1 2026-10)                       pending
  └ 16.2        race_win Mario  (f1 2026-11)                       pending
  typo          Maryo                                          –   –              –        –

       book_demo · event 2026-10 · f1 · captured 2026-10-15T09:00Z · odds decimal · USD
╭────────────────── unmapped lines ───────────────────╮
│ typo                                                │
│ exact keys only: fix the book file or its [aliases] │
╰─────────────────────────────────────────────────────╯
```
<!-- --8<-- [end:output] -->
