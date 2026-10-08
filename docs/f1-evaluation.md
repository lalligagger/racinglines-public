# F1 evaluation

How accurate the [F1 model](f1.md) is: an as-of backtest over every race since
2021, per-season tables, the model variants, and a comparison with Polymarket's
prices. The live forecast is on [F1 forecast](f1-forecast.md).

## Headline numbers

<!-- readme: f1-accuracy -->

**Backtest run 931** (2026-09-27) covers 129 races, 2021 to Azerbaijan 2026.
Each race is priced three times, using only sessions that had ended:

- before any practice (2025–26 only, 39 races: the first seasons with practice
  data);
- before qualifying (practice known);
- after qualifying (grid known).

Brier scores, lower is better. The last model column is the best variant,
`gridq+pretrain+reset` (run 955):

| | Before practice | Before qualifying | After qualifying | After qualifying, best variant | Grid-only guess | Uniform |
|---|---|---|---|---|---|---|
| Win | 0.0413 | 0.0382 | 0.0325 | **0.0307** | 0.0309 | 0.0471 |
| Podium | 0.0913 | 0.0878 | 0.0712 | **0.0692** | 0.0708 | 0.1265 |
| Top 10 | 0.187 | 0.175 | **0.149** | 0.150 | 0.163 | 0.250 |
| Teammate head-to-head | 0.231 | 0.228 | 0.197 | **0.196** | | |
| Win probability given to the winner (average) | 12.1% | 17.8% | 27.5% | **31.0%** | | about 5% |

- **Every session sharpens the price.** Error falls at each step, from before
  practice to after qualifying.
- **After qualifying**, the baseline beats a grid-only guess on top 10, ties it
  on podium and is slightly worse on win: it underweights the front of the grid.
  The `gridq` term fixes that, and the best variant beats the grid-only guess on
  win and podium too ([variants](#model-variants-f1-roadmap-f1-2-f1-3)).
- **Against Polymarket** the picture is mixed. In 2026 the model's race-winner
  prices beat the market mid-weekend (after FP1, FP2, sprint qualifying and the
  sprint) and lose after FP3 and qualifying. In 2025 the market is sharper on
  race winners at every stage (see [Against Polymarket](#against-polymarket)).

<!-- /readme -->

## Metrics

Each metric compares one priced race with what actually happened. The keys are
those in `model_runs.metrics` (per race under `events`, averaged under
`summary`):

| Metric | Meaning | Baseline |
|---|---|---|
| `brier_win` | Mean squared error of win probabilities over the field (lower is better). | Uniform: everyone gets `1/n`. Grid-only: see below. |
| `brier_podium` | Same, for podium probabilities. | `3/n`, grid-only |
| `brier_top10` | Same, for a points finish (top 10). | `10/n`, grid-only |
| `brier_teammate_h2h` | Brier of P(driver A finishes ahead of teammate B), per team; a DNF counts as behind. | 0.25 for a coin flip |
| `brier_constructor_top` | Brier of each team's probability of scoring the most points in the race. | |
| `logloss_win`, `logloss_podium`, `logloss_top10` | Log loss of the same probabilities; punishes confident misses harder than Brier. | |
| `winner_prob` | The win probability the model gave the actual winner. | `1/n` (about 5%) |
| `spearman` | Rank correlation of expected finishing position vs actual, over classified drivers. | 0 |
| `brier_*_grid` | **Grid-only guess** (after qualifying only): P(win / podium / top 10 \| grid slot), from all earlier races. | |

Each per-race row also has `year`, `round`, `venue`, `mode` (`pre_weekend`,
`pre_quali`, `pre_race`), `cutoff`, `winner` and `favourite`. Differences
between two runs are paired by race (`racinglines f1 compare`): challenger −
baseline, ± 2 standard errors over races; negative is better.

## Types of backtest

| Type | Command | What it does |
|---|---|---|
| As-of backtest | `racinglines f1 backtest --save` | Every race since 2021, priced before practice, before qualifying and after qualifying with a hard as-of cutoff (`price_race`), then scored. Saved as `kind='backtest'`. Runs with and without track features. |
| Weekend season sweep | `racinglines f1 sweep --year 2026 --save` | Every raced weekend of a season, priced before any running and 30 min after each session, and scored against Polymarket's price at the same moment. Also trades the markets (P&L in [Market making](market-making.md#season-sweep)). Saved as `kind='sweep'`. |
| Championship checkpoints | `racinglines f1 season-checkpoints` | As-of season forecasts (pre-season, after 3 and after 6 Grands Prix) enter championship markets and hold them; P&L over the next 3 GPs and to date, per variant. Saved as `kind='season_checkpoints'`; results in [Market making](market-making.md). |
| Single event | `racinglines f1 diagnostic --event 2026-15 --cutoff … --save` | One past event as of any cutoff. Saved as `kind='diagnostic'`. |

Leakage guards: each price uses only sessions that ended before the cutoff, and
outcomes are read only after pricing.

## Results: every race, 2021–2026

Backtest runs of 2026-09-27: 129 races, 4,000 simulations per race, 120-day
half-life, track features on. One run per model variant:

| Run | Variant |
|---|---|
| 931 | `baseline` |
| 932 | `grid` |
| 933 | `gridq` |
| 934 | `pretrain` |
| 935 | `tail` |
| 936 | `reset` |
| 937 | `gridq+pretrain` |
| 955 | `gridq+pretrain+reset` |
| 979 | `gbm` |
| 1288 | `rookie` (2026-09-28) † |
| 1289 | `gridq+pretrain+reset+rookie` (2026-09-28) † |

† Run in a cloud session on a copy of the database, so these ids aren't in the owner's database;
the runs are in the bucket (`results/cloud-buildout-track-b/f1-backtests/`). Re-run locally with
`racinglines f1 --variant rookie backtest --save`.

### Per season

**After qualifying** (grid known). Cells are baseline (run 931) /
`gridq+pretrain` (run 937) / grid-only guess:

| Season | Races | Brier win | Brier podium | Brier top 10 | Teammate h2h (baseline / variant) | Winner's win prob (baseline / variant) |
|---|---|---|---|---|---|---|
| 2021 | 22 | 0.0352 / 0.0344 / 0.0343 | 0.0728 / 0.0715 / 0.0683 | 0.153 / 0.154 / 0.169 | 0.194 / 0.194 | 25.1% / 26.7% |
| 2022 | 22 | 0.0346 / 0.0334 / 0.0364 | 0.0672 / 0.0664 / 0.0777 | 0.162 / 0.162 / 0.171 | 0.218 / 0.217 | 24.9% / 27.5% |
| 2023 | 22 | 0.0223 / 0.0208 / 0.0272 | 0.0774 / 0.0757 / 0.0798 | 0.148 / 0.148 / 0.177 | 0.194 / 0.194 | 40.1% / 43.4% |
| 2024 | 24 | 0.0363 / 0.0353 / 0.0350 | 0.0748 / 0.0732 / 0.0723 | 0.116 / 0.116 / 0.132 | 0.176 / 0.175 | 24.5% / 26.9% |
| 2025 | 24 | 0.0335 / 0.0304 / 0.0265 | 0.0645 / 0.0602 / 0.0584 | 0.164 / 0.163 / 0.166 | 0.189 / 0.185 | 26.4% / 31.8% |
| 2026 | 15 | 0.0329 / 0.0285 / 0.0238 | 0.0705 / 0.0675 / 0.0686 | 0.159 / 0.159 / 0.165 | 0.222 / 0.220 | 22.5% / 29.6% |
| **All** | 129 | 0.0325 / 0.0306 / 0.0309 | 0.0712 / 0.0691 / 0.0708 | 0.149 / 0.149 / 0.163 | 0.197 / 0.196 | 27.5% / 31.0% |

**Before qualifying** (baseline; `gridq+pretrain` is identical here by design).
Practice data exists only from 2025, so 2021–24 are priced without it:

| Season | Races | Brier win | Brier podium | Brier top 10 | Teammate h2h | Top constructor | Winner's win prob | Spearman |
|---|---|---|---|---|---|---|---|---|
| 2021 | 22 | 0.0396 | 0.0873 | 0.173 | 0.228 | 0.067 | 16.7% | 0.75 |
| 2022 | 22 | 0.0402 | 0.0884 | 0.190 | 0.246 | 0.068 | 15.4% | 0.72 |
| 2023 | 22 | 0.0303 | 0.0917 | 0.174 | 0.222 | 0.054 | 26.6% | 0.70 |
| 2024 | 24 | 0.0409 | 0.0942 | 0.161 | 0.225 | 0.073 | 14.9% | 0.76 |
| 2025 | 24 | 0.0397 | 0.0828 | 0.184 | 0.214 | 0.052 | 17.5% | 0.69 |
| 2026 | 15 | 0.0384 | 0.0798 | 0.167 | 0.236 | 0.063 | 15.0% | 0.80 |
| **All** | 129 | 0.0382 | 0.0878 | 0.175 | 0.228 | 0.063 | 17.8% | 0.73 |

**Before practice** (2025–26 only). Baseline / `gridq+pretrain`:

| Season | Races | Brier win | Brier podium | Brier top 10 | Winner's win prob |
|---|---|---|---|---|---|
| 2025 | 24 | 0.0415 / 0.0410 | 0.0905 / 0.0883 | 0.192 / 0.192 | 13.4% / 14.3% |
| 2026 | 15 | 0.0409 / 0.0407 | 0.0926 / 0.0910 | 0.178 / 0.177 | 10.1% / 10.8% |
| **All** | 39 | 0.0413 / 0.0409 | 0.0913 / 0.0893 | 0.187 / 0.186 | 12.1% / 12.9% |

Uniform Brier is 0.0475 (win), 0.1275 (podium) and 0.250 (top 10) with 20
cars, and 0.0438 / 0.1187 / 0.248 in 2026 (22 cars).

- **The model beats uniform in every season and stage.**
- **Top 10 after qualifying** beats the grid-only guess in every season.
- **Win after qualifying** is the weak spot of the baseline: worse than the
  grid-only guess in 2021, 2024, 2025 and 2026. `gridq+pretrain` improves it
  in every season and beats the grid overall, ties it in 2021 and is close in
  2024. In 2025 (0.0304 vs 0.0265) and 2026 (0.0285 vs 0.0238) the grid-only
  guess is still clearly better.
- **2023 is the easiest season to call** (Red Bull won 21 of 22 races): the
  winner got 40–43% on average after qualifying.

### Model variants (F1 roadmap F1-2, F1-3)

Challengers to the baseline, each behind a switch that defaults off
(`racinglines/models/position_sim/variants.py`, `racinglines f1 --variant NAME`).
Every variant goes through the same `price_race` path and leakage guards, over
the same 129 races (runs above), compared with `racinglines f1 compare`:
differences are variant − baseline, negative is better, bold is beyond 2
standard errors.

| Variant | What changes |
|---|---|
| `grid` | A front-of-grid term, log(grid)/log(n), in the finishing model: pole is worth much more than P3, while P10 vs P13 stays small |
| `gridq` | The same term, used only once the real grid is known (after qualifying) |
| `pretrain` | Before any practice, a finishing model trained on paces without the practice prior |
| `gbm` | Gradient-boosted finishing model (scikit-learn, monotone in grid and pace, fixed settings, noise from out-of-time residuals) |
| `tail` | 35% of past races were disrupted (red flag, ≥ 10% of laps behind the safety car, or rain). Simulated races are disrupted at the venue's rate, with more noise and retirements; teammates' retirements are correlated |
| `reset` | In a season with new technical regulations (2022, 2026; `sports/f1.toml`), earlier seasons' car pace counts a quarter (set a priori) |
| `rookie` | Driver offsets: once a driver's rookie season is over, that season's teammate comparisons (the rookie's and the teammate's) count a quarter (set a priori) |
| `fastlap` | No price changes: adds the race's fastest lap (race pace plus 0.6 % noise, among classified cars) as `extra.fl_prob`. Provisional and uncalibrated, so no backtest row; scored against Kalshi's resolved fastest-lap markets first |
| `flpos` | No price changes: the fastest lap instead drawn from the simulated finishing order and race pace (per-position rates from 2022-26 races times a pace factor, `sports/f1/fastest_lap.toml`), so the winner sets it about a third of the time. Provisional (decision log 2026-10-07); used by combo pricing |

**`gridq + pretrain`** (run 937 vs baseline run 931):

| Brier | Before practice | Before qualifying | After qualifying |
|---|---|---|---|
| Win | **−0.0004 ± 0.0002** | 0 | **−0.0019 ± 0.0007** |
| Podium | **−0.0020 ± 0.0009** | 0 | **−0.0021 ± 0.0007** |
| Top 10 | −0.0009 ± 0.0012 | 0 | −0.0001 ± 0.0003 |
| Teammate head-to-head | −0.0002 ± 0.0009 | 0 | **−0.0015 ± 0.0009** |
| Top-scoring constructor | **−0.0015 ± 0.0010** | 0 | **−0.0014 ± 0.0010** |
| Log loss, win | **−0.0031 ± 0.0011** | 0 | **−0.0059 ± 0.0020** |

**`gridq + pretrain + reset`** (run 955 vs baseline run 931):

| Brier | Before practice | Before qualifying | After qualifying |
|---|---|---|---|
| Win | **−0.0007 ± 0.0003** | **−0.0002 ± 0.0001** | **−0.0018 ± 0.0007** |
| Podium | **−0.0028 ± 0.0011** | **−0.0005 ± 0.0004** | **−0.0020 ± 0.0009** |
| Top 10 | **−0.0019 ± 0.0018** | −0.0001 ± 0.0006 | +0.0000 ± 0.0006 |
| Teammate head-to-head | −0.0001 ± 0.0009 | −0.0001 ± 0.0002 | **−0.0015 ± 0.0009** |
| Top-scoring constructor | **−0.0034 ± 0.0014** | **−0.0006 ± 0.0005** | −0.0013 ± 0.0013 |
| Log loss, win | **−0.0047 ± 0.0019** | **−0.0008 ± 0.0005** | **−0.0058 ± 0.0020** |

- **Front of the grid fixed.** After qualifying, `gridq+pretrain` has win Brier
  0.0306, better than the grid-only guess (0.0309); the baseline was 0.0325.
  Podium beats the grid-only guess too (0.0691 vs 0.0708).
- **Before any practice,** `pretrain` is better than baseline on win, podium
  and constructor, and no longer worse than the no-practice model.
- **No stage is worse** on any market. Before qualifying `gridq+pretrain`
  changes nothing, by design.
- **`grid` on its own** (run 932) had the same after-qualifying gains but was
  worse before practice and before qualifying, when the grid itself is
  simulated. `gridq` was defined after seeing that (so it's a choice made on
  this data), and restricts the term to known grids.
- **`reset` helps in new-regulations seasons** (run 936). Only 2022 and 2026
  races can change. Over all 129 races it is better before practice and before
  qualifying (win, podium, constructor, log loss) and worse nowhere. The idea
  came from the 2026 championship markets, so 2022 is the fair test: there, win
  odds before qualifying are better beyond 2 SE (Brier −0.0004, log loss
  −0.0027), and nothing is worse. Combined with `gridq+pretrain` (run 955) it
  is better than baseline at every stage and worse nowhere.
- **`gbm` is worse** (run 979): teammate head-to-head is worse beyond 2 SE at
  every stage, and so are podium Brier and win log loss before and after
  qualifying. With 129 races and fixed settings, the trees add variance without
  finding structure the ridge misses; the `gridq` term already captures the
  front-of-grid curve. It isn't promoted.
- **`rookie` is a small gain on win odds, mixed on teammates** (run 1288 vs 931; run 1289 vs 955
  on profile A's model). It targets the 2026 case of Russell priced far above Antonelli, whose
  rookie-season gap carried over. Pooled over 129 races, win Brier and log loss improve before
  practice (−0.0003, −0.0016, beyond 2 SE) and, on profile A's model, before qualifying too
  (−0.0002, −0.0007); after qualifying nothing moves. Teammate head-to-heads, the target, split by
  season: better in 2026 before qualifying (−0.0029 ± 0.0021) but worse in 2021 after qualifying
  (+0.0017 ± 0.0015), and inside 2 SE elsewhere. Russell–Antonelli before qualifying at Miami
  2026 (round 4, Antonelli won): baseline 50% Russell ahead, `rookie` 46%. Not promoted; a
  candidate for profile A's model once live weekends add evidence.
- **`tail` is neutral** (run 935): no metric moves beyond 2 SE at any stage.
  The disrupted-race mixture and correlated retirements change the spread of
  outcomes without making any market's price better on average. It isn't
  promoted.

### Calibration

`racinglines f1 compare 931 937 --reliability`:

- **Before qualifying, win probabilities are too flat.** Drivers priced 20–35%
  won 45% of the time, and those under 2% won 0.07%.
- **After qualifying,** `gridq + pretrain` cuts the win calibration error from
  0.029 to 0.024 and the podium one from 0.030 to 0.026.

### Practice prior, on vs off

A one-off comparison (2026-09-26, not a saved run pair): 2025–26, 39 races with
practice data. Differences are practice − no practice; negative is better; ± is
2 standard errors over races.

| Brier | Before practice | Before qualifying | After qualifying |
|---|---|---|---|
| Win | +0.0004 ± 0.0002 (worse) | **−0.0018 ± 0.0010** | −0.0005 ± 0.0007 |
| Podium | +0.0021 ± 0.0009 (worse) | **−0.0074 ± 0.0035** | −0.0005 ± 0.0021 |
| Top 10 | +0.0009 ± 0.0013 | **−0.0088 ± 0.0072** | −0.0006 ± 0.0019 |
| Teammate head-to-head | +0.0003 ± 0.0010 | **−0.0088 ± 0.0063** | −0.0006 ± 0.0025 |
| Top-scoring constructor | +0.0016 ± 0.0011 (worse) | **−0.0074 ± 0.0040** | −0.0007 ± 0.0021 |

- **Practice is a large gain between practice and qualifying,** about 8% less
  podium error. That is the window where the first 2026 sweep lost the most;
  the re-priced sweep turned FP2 trades from −$11 into +$1,130.
- **Once the grid is known,** the effect is small.
- **The small loss before any practice** comes from the finishing model, which
  is trained on practice-informed paces that don't exist before FP1. The
  `pretrain` variant fixes it (above).

### Shared car, old vs new

A one-off comparison (2026-09-26): 129 races, 2,000 sims, track features on.
Differences are new − old; negative is better; ± is 2 standard errors over
races.

| Brier | Before qualifying | After qualifying |
|---|---|---|
| Teammate head-to-head | **−0.0029 ± 0.0011** | **−0.0016 ± 0.0011** |
| Top 10 | **−0.0010 ± 0.0006** | −0.0004 ± 0.0005 |
| Podium | −0.0004 ± 0.0004 | −0.0002 ± 0.0004 |
| Win | +0.0001 ± 0.0002 | −0.0002 ± 0.0002 |
| Top-scoring constructor | +0.0009 ± 0.0007 (worse) | +0.0008 ± 0.0006 (worse) |

- **Car pace alone** (without shared luck) is roughly neutral. It fixes the
  double-counting without changing overall accuracy.
- **The head-to-head gain comes from the shared luck** (teammate-correlated
  noise).
- **Half the finishing correlation** keeps most of the before-qualifying gain
  but loses the after-qualifying one. The measured value is used, not a tuned
  one.

## Against Polymarket

The season sweeps price each weekend at the same moments Polymarket traded, so
model and market can be scored on the same outcomes. Brier of each, lower is
better; bold is the best of the three. Runs (all 2026-09-27, default model
settings): 2026, 15 weekends: baseline **622**, `gridq+pretrain+reset`
**929**. 2025, 23 of 24 weekends (round 7 isn't in the sweep): baseline **1190**,
`gridq+pretrain+reset` **1282** (different trading settings; model prices are
the same as with the defaults). *n* is the number of priced outcomes.

**Race winner**, by stage:

| Stage | 2026 n | 2026 baseline | 2026 best variant | 2026 Polymarket | 2025 n | 2025 baseline | 2025 best variant | 2025 Polymarket |
|---|---|---|---|---|---|---|---|---|
| Before FP1 | 178 | 0.0827 | **0.0806** | 0.0812 | 322 | 0.0654 | 0.0648 | **0.0554** |
| After FP1 | 196 | 0.0765 | **0.0750** | 0.0783 | 352 | 0.0587 | 0.0587 | **0.0527** |
| After FP2 | 113 | 0.0801 | **0.0791** | 0.0836 | 261 | 0.0578 | 0.0578 | **0.0553** |
| After sprint qualifying | 81 | 0.0621 | **0.0602** | 0.0670 | 100 | 0.0523 | 0.0523 | **0.0381** |
| After the sprint | 50 | 0.0884 | **0.0861** | 0.1014 | 88 | 0.0464 | 0.0464 | **0.0307** |
| After FP3 | 97 | 0.0933 | 0.0916 | **0.0845** | 211 | 0.0614 | 0.0615 | **0.0591** |
| After qualifying | 162 | 0.0720 | 0.0620 | **0.0596** | 303 | 0.0486 | 0.0453 | **0.0373** |

**Every market kind**, all stages pooled (weighted by *n*):

| Market | 2026 n | 2026 baseline | 2026 best variant | 2026 Polymarket | 2025 n | 2025 baseline | 2025 best variant | 2025 Polymarket |
|---|---|---|---|---|---|---|---|---|
| Race winner | 877 | 0.0786 | **0.0754** | 0.0771 | 1,637 | 0.0573 | 0.0566 | **0.0495** |
| Podium | 192 | 0.1641 | 0.1598 | **0.1580** | | | | |
| Pole | 509 | 0.0646 | 0.0637 | **0.0540** | 521 | 0.0651 | 0.0651 | 0.0685 |
| Teammate / driver head-to-head | 13 | 0.1698 | **0.1676** | 0.2635 | 107 | 0.2080 | **0.2028** | 0.2108 |
| Top-scoring constructor | 64 | 0.0661 | 0.0572 | **0.0570** | 228 | 0.0514 | 0.0505 | **0.0141** |

(2025 pole: both model runs score 0.0651, better than the market's 0.0685.)

- **2026: the model is competitive.** The best variant beats the market on race
  winners overall and at every stage before FP3, and on head-to-heads. The
  market is sharper on race winners after FP3 and after qualifying, on pole
  markets, and on podiums before practice, after the sprint and after
  qualifying.
- **2025: the market is sharper** on race winners at every stage, and far
  sharper on the top-scoring constructor (0.014 vs 0.051). The model does better
  on pole markets after FP1, FP2, sprint qualifying, the sprint and FP3, and on
  head-to-heads after qualifying.
- **The variants help against the market too.** `gridq+pretrain+reset` improves
  on the baseline in most cells; its biggest gain is race winners after
  qualifying in 2026 (0.0720 → 0.0620).

### The weekend scorecard

`racinglines f1 scorecard --event 2026-15 --venue both` is the same comparison for one exchange
weekend, traded or not ([Paper trading](paper-trading.md#validation-plan), validation rule 2): at each
stage cutoff, the stored stage runs' fair values for every linked market kind, against the result and
against the venue's mid at that cutoff (`--all --year 2025` for a season, per weekend and pooled). It
scores every market with a fair value and a result (`n`), and model and venue side by side on the
markets the venue priced then (`paired`); a multi-outcome group whose prices don't sum near its target
(an empty or stale book) gives no mid, as in the sweep. Written to `data/runs/f1/scorecard/`.

## Known weaknesses

- **After-qualifying winner markets:** Polymarket is sharper in both seasons
  (2026: 0.0596 vs 0.0620; 2025: 0.0373 vs 0.0453), and the grid-only guess
  beats the model in 2025–26. The model still underweights a dominant car at
  the front.
- **Win odds before qualifying are too flat** (see [Calibration](#calibration)):
  favourites win more often than priced, and the pre-weekend forecast rarely
  goes above 15% for anyone.
- **Top-scoring constructor in 2025:** the market's Brier was much lower at
  every stage (0.014 vs 0.051 pooled). Not investigated yet.
- **Pole markets in 2026:** the market is sharper at every stage except after
  FP2.
- **Backmarkers' chances of points in chaotic races** are underpriced (see the
  Sainz vs Alonso example in [Polymarket alignment](f1.md#polymarket-alignment)).
- **Before practice there are only 39 races** (2025–26), so differences at that
  stage have wide error bars.

## Reproduce

```
racinglines f1 backtest --save                   # all races, three stages (run 931)
racinglines f1 --variant gridq+pretrain+reset backtest --save   # a variant (run 955)
racinglines f1 compare 931 955                   # paired differences ± 2 SE
racinglines f1 compare 931 937 --reliability     # calibration tables
racinglines f1 sweep --year 2026 --save          # 2026 weekends vs Polymarket (run 622)
racinglines f1 sweep --year 2025 --save          # 2025 weekends vs Polymarket (run 1190)
racinglines f1 season-checkpoints                # championship-market entries
```

All of these can also be launched from the web app's **Lab**, with your own
settings.
