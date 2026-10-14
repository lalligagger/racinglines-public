<!-- Captured by scripts/docs/capture_examples.py (id db-stats-demo, scripts/docs/examples.toml) on 2026-10-14 05:05 UTC, commit 4313bf1+dirty, 55.5 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines db stats --demo
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
demo: building the kart pack's store (no database): database racinglines_demo_kart, folder
/home/user/racinglines-public/data/demo/kart. Synthetic data, made once (a few minutes).
🔧 demo store 0/7 creating the database
🔧 demo store 1/7 schema and reference data (alembic upgrade head, seed)
🔧 demo store 2/7 the pack's data files
🔧 demo store generating: 2024 R01 Mario Kart Stadium
🔧 demo store generating: 2025 R01 Mario Kart Stadium
🔧 demo store generating: 2026 R01 Mario Kart Stadium
🔧 demo store generating: files written
🔧 demo store generating: exchange odds 2026-09
🔧 demo store generating: exchange odds 2026-10
🔧 demo store generating: exchange odds 2026-11
🔧 demo store 3/7 racinglines data ingest f1 --years 2024-2026
🔧 demo store 4/7 racinglines model forecast f1 --save --sims 2000
🔧 demo store 5/7 racinglines data pm-links-import f1
🔧 demo store 6/7 racinglines data pm-links-import f1 --exchange kalshi
🔧 demo store 7/7 ready
demo: the kart store is ready (f1 data; `racinglines db stats --demo kart`) Let's-a go! 🍄
╭─ 📦 database racinglines_demo_kart ──────────────────────────────────────────╮
│ 📅 calendar          🏁 results                    🔮 model                  │
│ sports          8    athletes                20    model runs              1 │
│ leagues         8    athlete identifiers     20    race predictions       60 │
│ competitions    8    results              3,300    standings predictions  20 │
│ categories     11    splits                   0                              │
│ venues         27    source files            33                              │
│ events         36                                                            │
│ races          36                                                            │
│ rounds        165                                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
coverage

  competition   year   category   events   rounds   results
 ───────────────────────────────────────────────────────────
  f1_wdc        2024   DRV            12       60     1,200
  f1_wdc        2025   DRV            12       60     1,200
  f1_wdc        2026   DRV             9       45       900
```
<!-- --8<-- [end:output] -->
