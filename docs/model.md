# Downhill model

The downhill season model lives in `racinglines/models/timed_runs/` (section 7) and is driven by
`racinglines mtb_dh forecast` and `racinglines mtb_dh backtest`. It answers:

- Before a weekend: what's each rider's chance to make the Final, finish top 10,
  reach the podium, or win? How many championship points do they get on average?
- Mid-season: how will the championship end up?

How accurate it is: [Downhill evaluation](evaluation.md). The live 2026
projection: [Downhill forecast](forecast.md). Formula 1 uses a different model
family: [F1 model](f1.md).

## Overview

```
tidy splits.csv
   │  FINISH rows of every round, every season and category
   ▼
fit_season_model ──> rider pace μ, noise σ, rider × weekend spread τ, incident rates
   │
   ▼
simulate_weekend (format-aware) ──> qualifying ranks, Final ranks, points  × N sims
   │
   ▼
simulate_standings ──> points so far + simulated rounds ──> title / top-3 odds
```

## What gets modelled

The model works on the log of each rider's finish time. For rider *i* in run *r*
(one run = one event + category + round, e.g. Les Gets 2026 ME Q2):

```
log(time[i, r]) = run_effect[r] + μ[i] + u[i, weekend] + ε[i, r]
```

| Term | Meaning |
|---|---|
| `run_effect[r]` | How long that run's track and conditions are. It absorbs track length, weather, and differences between categories. |
| `μ[i]` | The rider's pace, as a fraction of time. μ = −0.02 means about 2% faster than the median rider. |
| `u[i, weekend] ~ N(0, τ²)` | Rider × track effect: shared by all of a rider's runs that weekend (track suits them, feeling good, setup). |
| `ε ~ N(0, σ²)` | Run-to-run noise. |

On top of this, each rider has an **incident rate** `p_inc[i]`. An incident is a
DNF or DSQ, or a finished run more than `INCIDENT_THRESHOLD` (4%) slower than
expected: a crash, puncture or big mistake.

Log times make the terms proportional, so a 2% gap means the same thing on a
2:45 track and a 4:10 track.

## Fitting

`fit_season_model(raw, category, half_life_days, category_weights, prior_n,
incident_prior_n, n_iter)`

### Which runs are used, and their weights

Every `FINISH` row with `status == OK` from rounds in `RUN_WEIGHTS` is used, from
every season and category passed in. Each run's weight is the product of three
factors:

| Factor | Value |
|---|---|
| Round type (`RUN_WEIGHTS`) | `practice` 0.5; `qual`, `qual1`, `qual2`, `semi`, `final` 1.0 |
| Category (`CATEGORY_WEIGHTS`, `--junior-weight`) | `ME` 1.0, `MJ` 0.5, anything else 0.5 |
| Recency | `0.5 ** (days_before_latest / half_life_days)`, default half-life 120 days |

With a 120-day half-life, last season's results count about a quarter to a half as
much as this month's, and results from three seasons ago barely count. That
setting was chosen by backtesting (see [Evaluation](evaluation.md#tuning)).

### Estimation, step by step

Estimation alternates between two steps, repeated 30 times:

1. **Run effects:** `run_effect[r] = median over riders in r of (log time − μ[i])`,
   using only clean runs. The median is robust to crashes.
2. **Rider pace:** `μ[i] = Σ w·(log time − run_effect) / (Σ w + prior_n)` over the
   rider's clean runs. `prior_n = 1.5` shrinks riders with little data toward the
   field median, since one lucky run shouldn't make a rider a favourite. After each
   step, μ is re-centred so its median is 0.
3. **Clean runs:** a run counts as clean if its residual
   `log time − run_effect − μ` is below 0.04. Incidents are excluded from the pace
   estimate.

**How junior results line up with elite ones:** each run has its own run effect,
so junior times aren't compared directly with elite times. The link comes from the
177 riders who raced both categories: their μ has to fit both sets of runs, which
puts junior and elite on one scale. The same happens across seasons through riders
who race several years.

### Noise terms

These come from clean race runs (`qual`/`qual1`/`qual2`/`semi`/`final`) in the
**target category** only:

- σ² is the pooled variance within each rider's weekend (`residual − mean for that
  rider and weekend`).
- τ² is the variance of rider-weekend means, minus the part already explained by σ²
  (`var(mean) − mean(σ²/n)`), with a small floor.

The backtest fit up to 2026 round 5 gives σ ≈ 0.012 and τ ≈ 0.011 (log-time). A
rider's time scatters by about 1.2% run to run, and about 1.1% extra from weekend
to weekend.

### Incidents

- **Base rate `p0`:** the share of started race runs in the target category that
  were incidents. It's about 24% in 2026 elite, which includes slow-but-finished runs.
- **Per-rider rate:** recency- and category-weighted, then shrunk toward `p0`:
  `(Σ w·incident + 8·p0) / (Σ w + 8)`.
- **How incidents play out:** about 14% of incidents are DNF/DSQ. The rest are
  finished-but-slow, and their time losses are kept in a list that the simulator
  samples from.

### Unknown riders

A rider with no history gets μ at the 75th percentile of the target category's
riders (slower than the median), and the base incident rate `p0`.

## Simulating a weekend

`simulate_weekend(model, riders, n_sims, attend_prob, rng, fmt)` works on
`(n_sims × riders)` arrays, all at once:

1. **Attendance:** each rider starts with probability `attend_prob` (or always, if
   no probabilities are given).
2. **Weekend effect:** draw `u` once per rider per simulation; it's shared by all
   their runs that weekend.
3. **Each run:** `μ + u + N(0, σ²)`. With probability `p_inc[i]` it's an incident:
   a DNF (time = ∞) with probability `dnf_share`, otherwise a time loss sampled
   from the observed losses.
4. **Rank** each run and move riders through the stages of the weekend format.

### Weekend formats

`event_format(raw, event_id)` works out an event's format from its own results.
This is fair in backtests, because the format and field sizes are published
before the race.

| Kind | Stages | Field sizes taken from | Seasons |
|---|---|---|---|
| `q1q2` | Q1 → (top `q1_to_final` go through) → Q2 for everyone else → (top `q2_to_final`) → Final | Finalists who didn't ride Q2 / did ride Q2 | Elite 2025–26 |
| `semi` | Qualifier → (top `to_semi`) → Semi-Final → (top `to_final`) → Final | Semi-Final and Final entry counts | Elite 2023–24 |
| `single` | Qualifier → (top `to_final`) → Final | Final entry count | Elite 2021–22, juniors, weather-shortened weekends |

Unraced rounds use `DEFAULT_FORMAT = q1q2 (20 + 10)`, the 2026 format.

Protected riders (older formats let top-ranked riders into the Final even if they
failed to qualify) aren't modelled explicitly. Using the actual Final size
(e.g. 64 instead of 60) accounts for them roughly.

## Points and standings

```
points = QUAL_POINTS[qualifying rank] + FINAL_POINTS[final rank]
```

- **Which round pays qualifying points** depends on the format, via
  `QUAL_POINTS_ROUND`: `qual1` (q1q2), `semi` (semi), `qual` (single).
- **Real points so far** come from `actual_event_points` applied to the target
  season's actual results.
- **Standings:** `simulate_standings` adds simulated points for each remaining
  weekend to the real points so far, then ranks everyone in every simulation, with
  random tie-breaks. That gives each rider's chance of being champion, top 3 and
  top 10, plus expected points and a p10–p90 range.

!!! warning
    `FINAL_POINTS` (250/210/180/…/11 for places 1–30) and `QUAL_POINTS`
    (60/50/40/…/2 for places 1–20) are **placeholders**, and the same tables are
    used for every era. See [Roadmap](todo.md#points-validation). Official tables, once entered,
    go in `points_schemes` per era (`racinglines mtb_dh points import`), and `--points db` uses them
    ([CLI](cli.md#racinglines-mtb_dh-points)).

## Forecasting the rest of the season

`forecast_season(raw, target, n_remaining, ...)` simulates `n_remaining` rounds in
total. Some may already be in the data (a weekend in progress), and the rest are
unknown.

### Rounds already in the data (weekend in progress)

`completed_events(target)` is the set of target events whose Final has `OK`
results. Any target event without them (e.g. Timed Training done, Q1 start list
published) is treated as **in progress**:

- **Field:** its real start list (`event_starters`: first-qualifier entrants not
  marked DNS, including `START` rows). Attendance is certain.
- **Training cutoff:** the model is fit only on data dated **before** that weekend,
  so this weekend's runs aren't counted twice.
- **Weekend effect:** each rider's `u` is conditioned on this weekend's Timed
  Training (`weekend_prior`). A rider's residual `e` gives the posterior
  `mean = τ²·e / (τ² + σₚ²)`, `sd = √(τ²σₚ² / (τ² + σₚ²))`, where
  `σₚ = 1.5·σ` because training runs are noisier. Riders without a training run
  keep `N(0, τ²)`; runs slower than `INCIDENT_THRESHOLD` are ignored.
- **Safety check:** if the session's residual interquartile range is above `max_iqr`
  (0.08 in log-time), the session isn't a pace signal (e.g. riders held on track)
  and is ignored with a warning. This happened at Whistler 2026 (IQR 0.71).
- **Format:** simulated with `DEFAULT_FORMAT` (Q1 top 20 + Q2 top 10).
- **Output:** a summary per upcoming event (`forecast_<venue>.csv`, and
  `race_predictions.target = "event:<event_id>"` with its `race_id` when saved),
  including `tt_pace_adj_pct`.

### Rounds not in the data yet

`n_unknown = n_remaining − len(upcoming)` rounds use a field of riders who started
the first qualifier in any of the last `attend_window = 3` completed events. Each
rider attends with probability `starts / 3`, so a rider who missed one of the last
three rounds (e.g. through injury) attends with probability 2/3. They're saved as
`target = "remaining_round"`.

### Championship rank movement

For the next upcoming weekend, `rank_moves(current_points, riders, sim_points)`
compares each rider's championship rank before and after the simulated weekend
(ranks are "min" style, so tied riders share the better rank). It gives
`current_rank`, `rank_up_prob`, `rank_down_prob` and `exp_rank_after`, which are
stored in `race_predictions.extra`. These use the placeholder points tables.

## Training scope and targets

- **Target** (`select_target`): only the target season and category are predicted
  and scored. Points, start lists, standings and every metric come from target rows.
- **Training** (`_training_rows`): `train_scope="all"` uses every row in the CSV;
  `"season"` uses only the target season. Backtests only train on data from strictly
  before the round being predicted.

## The older per-race model

The `fit` / `predict` subcommands are the first approach, built before any real
data existed. They're kept but aren't part of the season pipeline:

1. `pct_back` and a robust z-score per round;
2. pairwise Elo ratings from finishing order;
3. a recency-weighted form average and a venue prior;
4. a gradient-boosted regressor on `pct_back`;
5. Plackett–Luce win, podium and top-10 probabilities from Elo.

They haven't been checked against the multi-season data. They don't model the
qualifying format or points.
