# Downhill evaluation

How accurate the [downhill model](model.md) is: a walk-forward backtest over
every UCI World Cup round with timing data, per season and per event. The live
projection is on [Downhill forecast](forecast.md). For Formula 1, see
[F1 evaluation](f1-evaluation.md).

!!! warning "Placeholder points"
    Metrics measured in points (Spearman on points, standings) use placeholder
    points tables, and the same tables for every era. Win, podium, top-10 and
    make-Final metrics don't depend on points.

## Headline numbers

<!-- readme: headline -->

**Downhill (UCI World Cup, Men Elite):** walk-forward backtest over 43 rounds,
2021–2026. Each round is predicted only from data before it, and the model beats
the uniform baseline on podium and make-Final in every season.

| | Model | Uniform guess |
|---|---|---|
| Brier score, making the Final | **0.127** | 0.204 |
| Brier score, podium | **0.0224** | 0.0259 |
| Win probability given to the actual winner (average) | **7.1%** | ~1% |
| Rank correlation, predicted vs actual points | **0.62** | 0 |

Per-season and per-round tables: [Downhill evaluation](#results-every-season-with-data-20212026).

<!-- /readme -->

## Metrics

Each metric compares one predicted weekend with what actually happened:

| Metric | Meaning | Uniform baseline |
|---|---|---|
| `spearman_points` | Rank correlation of expected points vs actual points, across the whole start list. | 0 |
| `brier_win` | Mean squared error of win probabilities (lower is better). | Everyone gets `1/n`. |
| `brier_podium` | Same, for podium probabilities. | `3/n` |
| `brier_final` | Same, for making the Final. | The share of starters who made the Final (known in advance from the format). |
| `top10_hits` | How many of the model's 10 most likely top-10 finishers actually finished top 10. | about `10·10/n` |
| `winner_pred_win_prob` | The win probability the model gave the actual winner. | `1/n` (about 1%) |
| `standings_spearman` | For the standings backtest: rank correlation of expected vs actual season points, over riders who scored. | 0 |

Brier scores for rare events (1 winner in about 100 starters) are small in absolute
terms, so compare them against the baseline rather than against zero.

## Types of backtest

| Type | Command | What it does |
|---|---|---|
| Walk-forward | `season --walk-forward`, `backtest` | For each target round: fit on everything strictly before it, simulate it with its actual start list and format, and score it. |
| Holdout + standings | `season --backtest 2`, `backtest` | Fit on data before the last 2 rounds, simulate both, and compare the projected end-of-season standings with the real ones. |
| Scope / tuning sweep | scratch script (see [History](history.md)) | Walk-forward under different training settings. |

All backtests use the **actual start list** of each predicted round, which is known
a day or two before racing. Forecasts of unraced rounds use the attendance model
instead.

## Results: every season with data (2021–2026)

Model run 938 (2026-09-27), command `racinglines mtb_dh backtest --db --save`. Settings: training scope
`all`, 120-day half-life, junior weight 0.5, 4,000 simulations per round.
Seasons 2019–2020 have no usable timing data (see [Data](data.md#whats-downloaded)).
2021's first round (Maribor) has no earlier history, so it isn't predicted.

### Per season (walk-forward means, plus a standings holdout of the last 2 rounds)

| Season | Rounds predicted | Format | Spearman | Brier win (model / base) | Brier podium (model / base) | Brier make-Final (model / base) | Top-10 hits | Winner's win prob | Standings Spearman | Actual champion (model prob) | Model favourite (prob) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021 | 3 | single | 0.618 | 0.010 / 0.011 | 0.024 / 0.032 | 0.148 / 0.190 | 4.3 | 10.2% | 0.896 | Bruni (4.2%) | Vergier (76.0%) |
| 2022 | 8 | single | 0.583 | 0.007 / 0.008 | 0.018 / 0.022 | 0.161 / 0.232 | 5.4 | 11.0% | 0.945 | Pierron (100%) | Pierron (100%) |
| 2023 | 8 | semi / single | 0.597 | 0.007 / 0.007 | 0.019 / 0.022 | 0.113 / 0.184 | 5.0 | 5.1% | 0.941 | Goldstone (35.2%) | Bruni (40.0%) |
| 2024 | 7 | semi / single | 0.609 | 0.006 / 0.007 | 0.018 / 0.021 | 0.101 / 0.171 | 5.9 | 7.0% | 0.870 | Bruni (91.1%) | Bruni (91.1%) |
| 2025 | 10 | q1q2 | 0.637 | 0.010 / 0.011 | 0.028 / 0.032 | 0.132 / 0.219 | 5.0 | 5.0% | 0.960 | Goldstone (6.0%) | Bruni (94.0%) |
| 2026 | 7 | q1q2 | 0.666 | 0.009 / 0.010 | 0.026 / 0.029 | 0.116 / 0.209 | 5.3 | 6.4% | 0.962 | Williams* (17.7%) | Pierron (51.0%) |

\* 2026 "champion" means the standings leader after round 7; the season isn't over.

**All 43 predicted rounds:**
- Spearman 0.618;
- Brier win 0.0082 vs 0.0088;
- Brier podium 0.0224 vs 0.0259;
- Brier make-Final 0.127 vs 0.204;
- top-10 hits 5.2 out of 10;
- the actual winner got a **7.1%** win probability on average, against about 1% for
  a uniform guess.

### What the results say

- **Qualifying is predicted well.** Make-Final Brier is 30–45% below the baseline
  in every season and format.
- **Ranking the field is solid and improving.** Spearman goes from 0.58–0.61
  (2021–24) to 0.64–0.67 (2025–26). Part of that is more history, and part is that
  the 30-rider Final format makes the points spread easier to rank.
- **Winners are hard.** The Brier improvement for winning is small. Still, the
  actual winner averages about 7× the uniform probability, and about 10% in the
  2021–22 era, when fewer riders won.
- **Late-season standings are mostly settled.** With 2 rounds left, standings
  Spearman is 0.87–0.96.
- **Championship calls with 2 rounds left can be badly wrong.** Wrong favourites:
  2021 (Vergier over Bruni), 2025 (Bruni at 94% vs Goldstone). These are probably
  placeholder-points artefacts: a points table that differs from the real one
  changes the gaps between riders. Re-check after [points validation](todo.md#points-validation).

### Per event (walk-forward)

| Season | Venue | Format | Starters | Final size | Spearman | Brier make-Final (model / base) | Top-10 hits | Winner (win prob) |
|---|---|---|---|---|---|---|---|---|
| 2021 | Lenzerheide | single | 132 | 61 | 0.458 | 0.168 / 0.249 | 5 | Vergier (19.3%) |
| 2021 | Snowshoe | single | 81 | 64 | 0.692 | 0.136 / 0.166 | 4 | Wilson (2.0%) |
| 2021 | Snowshoe | single | 78 | 63 | 0.704 | 0.139 / 0.155 | 4 | Bruni (9.2%) |
| 2022 | Lourdes | single | 148 | 60 | 0.521 | 0.153 / 0.240 | 6 | Pierron (10.0%) |
| 2022 | Fort William | single | 139 | 63 | 0.552 | 0.172 / 0.248 | 7 | Pierron (16.7%) |
| 2022 | Leogang | single | 171 | 64 | 0.607 | 0.167 / 0.234 | 5 | Walker (6.8%) |
| 2022 | Lenzerheide | single | 148 | 62 | 0.649 | 0.161 / 0.243 | 5 | Pierron (11.0%) |
| 2022 | Vallnord | single | 144 | 64 | 0.648 | 0.144 / 0.247 | 4 | Vergier (8.4%) |
| 2022 | Snowshoe | single | 88 | 63 | 0.577 | 0.153 / 0.203 | 6 | Pierron (14.8%) |
| 2022 | Mont-Sainte-Anne | single | 87 | 61 | 0.709 | 0.168 / 0.210 | 5 | Iles (8.4%) |
| 2022 | Val di Sole | single | 167 | 62 | 0.403 | 0.171 / 0.233 | 5 | Vergier (11.8%) |
| 2023 | Lenzerheide | semi | 180 | 31 | 0.533 | 0.088 / 0.143 | 3 | Williams (0.0%)† |
| 2023 | Leogang | semi | 170 | 30 | 0.590 | 0.085 / 0.145 | 7 | Kolb (6.6%) |
| 2023 | Val di Sole | semi | 153 | 32 | 0.573 | 0.101 / 0.165 | 7 | Goldstone (7.8%) |
| 2023 | Vallnord | single | 159 | 61 | 0.621 | 0.154 / 0.236 | 2 | Daprela (4.2%) |
| 2023 | Loudenvielle | semi | 141 | 32 | 0.674 | 0.090 / 0.175 | 2 | Bruni (6.6%) |
| 2023 | Les Gets | semi | 162 | 31 | 0.560 | 0.089 / 0.155 | 7 | Coulanges (6.4%) |
| 2023 | Snowshoe | semi | 86 | 31 | 0.598 | 0.161 / 0.231 | 5 | O'Callaghan (0.8%) |
| 2023 | Mont-Sainte-Anne | semi | 90 | 30 | 0.626 | 0.137 / 0.222 | 7 | Goldstone (8.2%) |
| 2024 | Fort William | semi | 137 | 31 | 0.538 | 0.122 / 0.175 | 7 | Bruni (10.5%) |
| 2024 | Bielsko-Biała | semi | 152 | 34 | 0.652 | 0.100 / 0.174 | 5 | Dunne (1.8%) |
| 2024 | Leogang | semi | 173 | 32 | 0.619 | 0.081 / 0.151 | 8 | Bruni (11.2%) |
| 2024 | Val di Sole | semi | 150 | 32 | 0.640 | 0.088 / 0.168 | 7 | Pierron (3.6%) |
| 2024 | Les Gets | semi | 160 | 31 | 0.617 | 0.083 / 0.156 | 5 | Pierron (10.6%) |
| 2024 | Loudenvielle | single | 136 | 30 | 0.583 | 0.103 / 0.172 | 5 | Coulanges (2.0%) |
| 2024 | Mont-Sainte-Anne | semi | 106 | 30 | 0.614 | 0.130 / 0.203 | 4 | Brosnan (9.6%) |
| 2025 | Bielsko-Biała | q1q2 | 95 | 30 | 0.602 | 0.135 / 0.216 | 5 | Bruni (10.0%) |
| 2025 | Loudenvielle | q1q2 | 89 | 30 | 0.593 | 0.150 / 0.223 | 3 | Goldstone (0.9%) |
| 2025 | Leogang | q1q2 | 104 | 30 | 0.695 | 0.113 / 0.205 | 2 | Goldstone (2.2%) |
| 2025 | Val di Sole | q1q2 | 92 | 30 | 0.642 | 0.132 / 0.220 | 7 | Goldstone (3.1%) |
| 2025 | La Thuile | q1q2 | 103 | 30 | 0.598 | 0.127 / 0.206 | 5 | Goldstone (5.8%) |
| 2025 | Pal Arinsal | q1q2 | 89 | 30 | 0.553 | 0.159 / 0.223 | 6 | Bruni (12.8%) |
| 2025 | Les Gets | q1q2 | 111 | 30 | 0.627 | 0.112 / 0.197 | 4 | Dunne (2.9%) |
| 2025 | Lenzerheide | q1q2 | 85 | 30 | 0.695 | 0.122 / 0.228 | 5 | Pierron (5.6%) |
| 2025 | Lake Placid | q1q2 | 80 | 30 | 0.676 | 0.140 / 0.234 | 6 | Meier-Smith (1.8%) |
| 2025 | Mont-Sainte-Anne | q1q2 | 78 | 30 | 0.689 | 0.129 / 0.237 | 7 | Goldstone (5.0%) |
| 2026 | Mona Yongpyong | q1q2 | 83 | 30 | 0.646 | 0.135 / 0.231 | 6 | Vermette (21.3%) |
| 2026 | Loudenvielle | q1q2 | 100 | 30 | 0.611 | 0.128 / 0.210 | 4 | Shaw (3.1%) |
| 2026 | Leogang | q1q2 | 107 | 30 | 0.671 | 0.113 / 0.202 | 4 | Iles (2.6%) |
| 2026 | Lenzerheide | q1q2 | 105 | 30 | 0.679 | 0.111 / 0.204 | 5 | Iles (4.9%) |
| 2026 | La Thuile | q1q2 | 114 | 30 | 0.674 | 0.100 / 0.194 | 5 | Williams (4.0%) |
| 2026 | Pal Arinsal | q1q2 | 90 | 30 | 0.679 | 0.121 / 0.222 | 6 | Williams (4.6%) |
| 2026 | Les Gets | q1q2 | 108 | 30 | 0.701 | 0.106 / 0.201 | 7 | M. Alran (4.5%) |

† Jordan Williams won 2023 Lenzerheide as `WILLIAMS Robert Jordan`. That name
doesn't match his other results, so the model treated him as an unknown rider.
This is the name-matching problem described under [rider IDs](parser.md#rider-ids).

Full per-event CSV: `backtest_events.csv`. Per season: `backtest_seasons.csv`.

## Does older and junior data help?

Measured before the 2021–22 download, with 2023–2026 data. Walk-forward on 2026
rounds 2–7 (6 rounds), so every setup is scored on the same rounds:

| Training data | Spearman | Brier podium | Brier make-Final | Top-10 hits |
|---|---|---|---|---|
| 2026 elite only (75-day half-life) | 0.643 | 0.0257 | 0.1132 | 5.0 |
| + 2023–25 elite (no juniors) | 0.662 | 0.0254 | 0.1140 | 5.3 |
| + 2023–25 elite + juniors | 0.668 | 0.0257 | 0.1107 | 5.2 |

- History mostly improves **ranking** and **making the Final**, and makes round 1
  predictable at all. It doesn't improve win or podium calibration.
- Adding 2021–22 afterwards left the 2026 numbers essentially unchanged (mean
  Spearman 0.667 over all 7 rounds). With a 120-day half-life, data that old
  carries very little weight.

### Tuning

The same 6 rounds under different settings:

| Scope | Half-life (days) | Junior weight | Spearman | Brier win | Brier podium | Brier make-Final | Top-10 hits |
|---|---|---|---|---|---|---|---|
| season | 75 | – | 0.643 | 0.0091 | 0.0257 | 0.1132 | 5.00 |
| all | 60 | 0.5 | 0.649 | 0.0091 | 0.0257 | 0.1216 | 4.83 |
| all | 120 | 0.0 | 0.662 | 0.0092 | 0.0254 | 0.1140 | 5.33 |
| **all** | **120** | **0.5** | **0.668** | 0.0093 | 0.0257 | 0.1107 | 5.17 |
| all | 120 | 1.0 | 0.667 | 0.0095 | 0.0263 | 0.1104 | 5.33 |
| all | 240 | 0.5 | 0.668 | 0.0095 | 0.0260 | 0.1058 | 5.50 |
| all | 365 | 0.5 | 0.668 | 0.0096 | 0.0261 | 0.1047 | 5.67 |

- **Longer half-lives** help make-Final predictions but slightly hurt win and podium
  calibration.
- **120 days** was kept as the balance.
- **Junior weight 0.5** was marginally better than 0 or 1.

With only 6 rounds, most of these differences are within noise. A proper sweep over
all 43 rounds is a [Roadmap](todo.md#model).

## Known weaknesses

- **Win probabilities are flat.** Favourites rarely go above 10%, and the average
  winner gets 5–10%. The recent-season base rate is roughly a 25% incident rate
  (see [Downhill model](model.md#incidents)). That rate, plus the 4% threshold, may be
  adding too much randomness at the front of the field. Worth checking calibration
  curves.
- **No track effects.** A rider's affinity for a venue is only captured through the
  per-weekend random effect `u`, which is re-drawn every simulation.
- **No start order and no weather**, even though they're known to matter in DH.
- **Rider identity is name-based** (see above).
