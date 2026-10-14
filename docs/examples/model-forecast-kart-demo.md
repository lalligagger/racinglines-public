<!-- Captured by scripts/docs/capture_examples.py (id model-forecast-kart-demo, scripts/docs/examples.toml) on 2026-10-14 05:06 UTC, commit 4313bf1+dirty, 10.0 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines model forecast kart --demo --save
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
🔮 forecast 2026 · cutoff 2026-10-14 05:06 UTC · latest results 2026-10-04 14:00
🏁 R10 Rainbow Road Grand Prix (18 Oct)
╭─────────────┬──────────┬───────┬──────────────┬────────┬──────────────┬────────┬───────┬─────────╮
│ driver      │ team     │   win │              │ podium │              │ top 10 │   DNF │ exp pts │
├─────────────┼──────────┼───────┼──────────────┼────────┼──────────────┼────────┼───────┼─────────┤
│ Mario       │ mushroom │ 26.4% │ ███▋         │  58.7% │ ████████▏    │  95.0% │  3.2% │    15.1 │
│ Luigi       │ mushroom │ 18.8% │ ██▋          │  49.7% │ ██████▉      │  93.8% │  3.1% │    13.4 │
│ Bowser      │ koopa    │ 14.4% │ ██           │  40.2% │ █████▋       │  82.2% │ 13.9% │    11.2 │
│ Peach       │ royal    │  9.9% │ █▍           │  33.1% │ ████▋        │  86.7% │  5.5% │    10.2 │
│ Daisy       │ royal    │  8.3% │ █▏           │  29.6% │ ████▏        │  84.4% │  5.9% │     9.5 │
│ Donkey Kong │ kong     │  8.0% │ █            │  27.4% │ ███▊         │  85.8% │  3.5% │     9.3 │
│ Bowser Jr.  │ koopa    │  6.7% │ ▉            │  23.6% │ ███▎         │  75.2% │ 13.7% │     8.1 │
│ Diddy Kong  │ kong     │  2.8% │ ▍            │  12.3% │ █▋           │  72.9% │  3.3% │     5.8 │
│ Yoshi       │ yoshi    │  1.6% │ ▏            │   7.7% │ █            │  60.1% │  7.3% │     4.2 │
│ Rosalina    │ comet    │  1.2% │ ▏            │   5.9% │ ▊            │  55.5% │  5.6% │     3.6 │
╰─────────────┴──────────┴───────┴──────────────┴────────┴──────────────┴────────┴───────┴─────────╯
🏁 R11 Wario Stadium Grand Prix (01 Nov)
╭─────────────┬──────────┬───────┬──────────────┬────────┬──────────────┬────────┬───────┬─────────╮
│ driver      │ team     │   win │              │ podium │              │ top 10 │   DNF │ exp pts │
├─────────────┼──────────┼───────┼──────────────┼────────┼──────────────┼────────┼───────┼─────────┤
│ Mario       │ mushroom │ 24.4% │ ███▍         │  59.3% │ ████████▎    │  95.4% │  3.0% │    15.0 │
│ Luigi       │ mushroom │ 20.7% │ ██▉          │  52.9% │ ███████▍     │  94.8% │  3.0% │    14.0 │
│ Peach       │ royal    │ 15.6% │ ██▏          │  44.2% │ ██████▏      │  90.8% │  5.9% │    12.4 │
│ Bowser      │ koopa    │ 12.9% │ █▊           │  37.3% │ █████▏       │  82.2% │ 14.0% │    10.8 │
│ Daisy       │ royal    │ 12.1% │ █▋           │  36.9% │ █████▏       │  89.1% │  5.7% │    11.2 │
│ Bowser Jr.  │ koopa    │  4.6% │ ▋            │  19.1% │ ██▋          │  75.1% │ 13.7% │     7.3 │
│ Donkey Kong │ kong     │  4.2% │ ▌            │  18.4% │ ██▌          │  82.0% │  3.1% │     7.6 │
│ Yoshi       │ yoshi    │  2.1% │ ▎            │  11.0% │ █▌           │  69.3% │  7.4% │     5.4 │
│ Diddy Kong  │ kong     │  1.0% │ ▏            │   6.1% │ ▊            │  61.1% │  3.6% │     4.0 │
│ Birdo       │ yoshi    │  0.9% │ ▏            │   5.3% │ ▋            │  56.3% │  7.3% │     3.6 │
╰─────────────┴──────────┴───────┴──────────────┴────────┴──────────────┴────────┴───────┴─────────╯
🏆 2026 drivers' championship
╭──────────────┬────────┬──────────┬──────────┬────────────────┬────────╮
│ driver       │ points │ expected │ champion │                │  top 3 │
├──────────────┼────────┼──────────┼──────────┼────────────────┼────────┤
│ Luigi        │    191 │      234 │    99.8% │ █████████████▉ │ 100.0% │
│ Mario        │    134 │      182 │     0.2% │                │  99.1% │
│ Peach        │    106 │      141 │     0.0% │                │  60.5% │
│ Bowser       │     99 │      135 │     0.0% │                │  39.9% │
│ Daisy        │     62 │       95 │     0.0% │                │   0.2% │
│ Donkey Kong  │     57 │       85 │     0.0% │                │   0.2% │
│ Bowser Jr.   │     60 │       85 │     0.0% │                │   0.1% │
│ Koopa Troopa │     55 │       58 │     0.0% │                │   0.0% │
│ Birdo        │     36 │       48 │     0.0% │                │   0.0% │
│ Diddy Kong   │     28 │       46 │     0.0% │                │   0.0% │
╰──────────────┴────────┴──────────┴──────────┴────────────────┴────────╯
constructors

  team                 points   expected   champion
 ────────────────────────────────────────────────────────────────────
  Mushroom Racing         325        416     100.0%   ██████████████
  Royal Racing            168        236       0.0%
  Koopa Kart Works        159        220       0.0%
  Kong Jungle Racing       85        132       0.0%
  Yoshi Island GP          62         91       0.0%

finishing model coef {'g': 0.527, 'g_ease': -0.149, 'rp_rel': 0.041, 'rp_ease': 0.051, 'qp_rel':
0.08, 'street_g': 0.0} sigma 0.155; season drift (as-of) {'team_sd': 0.002652025069557153,
'driver_sd': 0.0005339299639313828}

Saved forecast run 2.
```
<!-- --8<-- [end:output] -->
