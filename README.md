# racinglines
create databases and build prediction engines for timed race sport disciplines; become a market maker for some niche sport on prediction markets

Current focus: UCI Mountain Bike World Series downhill (DHI), Men Elite, 2026 season.

## What it does

The pipeline takes ChronoRace split timing for every round raced so far and
simulates race weekends (Q1 → Q2 → Final) many times. From those simulations it
estimates:
- each rider's chance to win, reach the podium, finish top 10, or make the Final;
- expected championship points;
- projected final standings.

It also backtests itself on rounds that have already been raced.

Demo output below comes from rounds 1–7 of 2026 (Mona Yongpyong → Les Gets),
generated with:

```
python parser.py --input-dir data/ --out splits.csv
python predictor.py season --data splits.csv --out-dir season_out   # 10k sims, seed 42
```

> ⚠️ Points use **placeholder** tables (see [TODO: points validation](#todo-points-validation)).
> Win, podium, top-10 and make-Final probabilities don't depend on the points tables.
> Everything measured in points does.

### Backtest: predict rounds 6–7 using only rounds 1–5

Each held-out round is simulated with its real start list, then compared with the
actual result.

| Round | Spearman (exp vs actual pts) | Brier win (model / uniform) | Brier podium (model / uniform) | Brier make-Final (model / uniform) | Top-10 hits | Winner's predicted win prob |
|---|---|---|---|---|---|---|
| Pal Arinsal (#6) | 0.674 | 0.0097 / 0.0110 | 0.0285 / 0.0322 | 0.1181 / 0.2222 | 5/10 | Williams, 8.7% (ranked 1st) |
| Les Gets (#7) | 0.652 | 0.0093 / 0.0092 | 0.0261 / 0.0270 | 0.1091 / 0.2006 | 5/10 | M. Alran, 1.8% |

Lower Brier is better. The model is strong at predicting who makes the Final and
at ranking riders overall. It is only marginally better than chance at picking
race winners, which is typical of DH.

Top of the Pal Arinsal prediction, next to what actually happened:

| Rider | Win | Podium | Top 10 | Make Final | Exp pts | Actual pos | Actual pts |
|---|---|---|---|---|---|---|---|
| WILLIAMS Jordan | 8.7% | 21.3% | 50.4% | 86.7% | 111 | 1 | 280 |
| PIERRON Amaury | 7.3% | 19.3% | 49.8% | 86.7% | 109 | 27 | 39 |
| ILES Finn | 7.6% | 19.4% | 46.7% | 84.9% | 104 | 5 | 180 |
| VERGIER Loris | 6.5% | 16.5% | 42.4% | 82.4% | 94 | 16 | 54 |
| PINKERTON Ryan | 5.6% | 15.2% | 40.7% | 81.4% | 90 | 3 | 196 |
| ALRAN Till | 5.0% | 13.9% | 39.4% | 79.7% | 87 | 19 | 65 |
| VERMETTE Asa | 5.2% | 14.0% | 35.1% | 77.0% | 81 | 4 | 162 |
| BROSNAN Troy | 3.1% | 10.5% | 34.6% | 74.8% | 76 | 7 | 110 |

Standings after round 7, predicted from rounds 1–5 (Spearman vs actual totals: **0.956**):

| Rider | Pts after R5 | Exp pts after R7 | Champion (lead) | Top 3 | Actual pts | Actual rank |
|---|---|---|---|---|---|---|
| PIERRON Amaury | 844 | 1063 | 54.2% | 94.5% | 928 | 4 |
| WILLIAMS Jordan | 752 | 978 | 26.2% | 76.4% | 1177 | 1 |
| VERMETTE Asa | 755 | 918 | 12.7% | 57.8% | 1042 | 2 |
| ILES Finn | 782 | 886 | 5.2% | 47.1% | 962 | 3 |
| VERGIER Loris | 508 | 699 | 0.6% | 7.4% | 627 | 9 |
| BROSNAN Troy | 539 | 691 | 0.3% | 5.5% | 760 | 7 |

### Forecast: the 2 remaining rounds (fit on all 7)

Venues for rounds 8–9 aren't known yet, so both rounds get the same odds. The field
is every rider who started any of the last 3 rounds, weighted by how often they started.

Per remaining round:

| Rider | Attend | Win | Podium | Top 10 | Make Final | Exp pts |
|---|---|---|---|---|---|---|
| WILLIAMS Jordan | 100% | 11.4% | 26.3% | 56.5% | 89.5% | 126 |
| ALRAN Max | 100% | 6.1% | 16.4% | 43.9% | 82.4% | 96 |
| PINKERTON Ryan | 100% | 5.6% | 15.8% | 41.6% | 80.9% | 93 |
| PIERRON Amaury | 100% | 5.4% | 15.0% | 41.6% | 80.3% | 91 |
| VERMETTE Asa | 100% | 5.6% | 15.5% | 39.8% | 78.4% | 88 |
| ALRAN Till | 100% | 4.9% | 14.2% | 39.4% | 78.5% | 87 |
| VERGIER Loris | 100% | 4.8% | 13.8% | 38.5% | 78.2% | 85 |
| BROSNAN Troy | 100% | 4.4% | 13.5% | 38.7% | 77.5% | 85 |

Projected final championship standings:

| Rider | Rank now | Pts now | Exp final pts | p10–p90 | Champion | Top 3 |
|---|---|---|---|---|---|---|
| WILLIAMS Jordan | 1 | 1177 | 1429 | 1257–1602 | 82.2% | 99.6% |
| VERMETTE Asa | 2 | 1042 | 1219 | 1070–1382 | 11.3% | 80.4% |
| PIERRON Amaury | 4 | 928 | 1112 | 965–1273 | 3.2% | 45.8% |
| ILES Finn | 3 | 962 | 1089 | 962–1251 | 2.4% | 35.9% |
| GOLDSTONE Jackson | 5 | 822 | 975 | 838–1132 | 0.3% | 11.8% |
| ALRAN Max | 6 | 773 | 966 | 820–1127 | 0.2% | 11.3% |
| BROSNAN Troy | 7 | 760 | 928 | 790–1082 | 0.1% | 6.6% |
| PINKERTON Ryan | 8 | 743 | 928 | 782–1092 | 0.2% | 7.0% |

## Setup

```
pip install pandas numpy beautifulsoup4 lxml scikit-learn joblib requests
```

## Pipeline

```
download_chronorace.py  ->  data/*.md  ->  parser.py  ->  splits.csv  ->  predictor.py
```

### 1. Download results — `download_chronorace.py`

Pulls per-round split timing from ChronoRace and writes one markdown file per event
(`data/2026-08_les-gets_men-elite.md`, ...). Event slugs are scraped from the Wikipedia
season page, or passed explicitly with `--events`.

```
python download_chronorace.py --year 2026 --discipline DH --category "Elite Men" --out-dir data/
```

Each file has one `## <round>` section per round (Timed Training, Qualification 1,
Qualification 2, Final), each a table of Pos / Bib / Rider / Team / Nation / splits /
Time / Gap / Status.

### 2. Parse to a tidy CSV — `parser.py`

```
python parser.py --inspect data/2026-08_les-gets_men-elite.md   # check a file
python parser.py --input-dir data/ --out splits.csv
```

Output is long format: one row per rider per sector per round, with `sector_id =
S1..Sn` or `FINISH`, cumulative and sector times, rank at split, and status
(`OK`/`DNF`/`DNS`/`DSQ`). Round labels are `practice`, `qual1`, `qual2`, `final`.

It also accepts HTML, CSV, JSON, and a copy/paste of the live-timing page saved as
`.md`/`.txt`. The format is detected automatically; see the module docstring.

### 3. Predict — `predictor.py`

**Season forecast and backtest** (the main entry point):

```
python predictor.py season --data splits.csv --out-dir season_out
```

- **Backtest** (`--backtest 2`): fits on all but the last 2 raced rounds, simulates
  those 2 using their real start lists, and scores them against what actually happened.
  Scores include rank correlation of expected vs actual points, Brier scores for
  win/podium/making the final, top-10 hits, and predicted vs actual standings.
- **Forecast** (`--remaining 2`): fits on every raced round, then simulates the
  unraced rounds and projects final championship standings. Output includes each
  rider's chance of being champion or top 3, expected points, and a p10–p90 range.

How the model works:
- **Rider pace:** estimated from log finish times, with each run's overall pace
  removed so different tracks and fields can be compared. Recent rounds count more.
- **Randomness:** run-to-run noise, a per-weekend rider × track effect, and a
  per-rider incident rate (DNF/DSQ, or a run more than 4% slower than expected).
- **Weekend format:** each weekend is simulated the way every 2026 round ran: the
  top 20 in Q1 go to the Final, everyone else rides Q2, and the top 10 in Q2 fill
  the Final (30 riders).
- **Points:** championship points are `QUAL_POINTS[qual rank] + FINAL_POINTS[final
  rank]`, added over 10,000 simulated seasons.

CSVs written to `--out-dir`: `backtest_<venue>.csv`, `backtest_standings.csv`,
`forecast_per_round.csv`, `forecast_standings.csv`.

**Per-race model** (older and separate): Elo ratings plus a gradient-boosted
`pct_back` regressor, with Plackett–Luce win probabilities from a start list.

```
python predictor.py fit --data splits.csv --out-dir model/ --validate
python predictor.py predict --model-dir model/ --start-list startlist.csv
```

## TODO: points validation

The points tables in `predictor.py` (`FINAL_POINTS`, `QUAL_POINTS`,
`QUAL_POINTS_ROUND`) are **placeholders**. Until these are fixed, every points,
standings, and championship probability is approximate.

- [ ] Get the official 2026 UCI DHI World Cup points scale (UCI MTB regulations,
      Part 4, or the published event standings PDFs on ChronoRace).
- [ ] Replace `FINAL_POINTS` with the official Final points for every scoring
      position. Check how many places score (currently 30).
- [ ] Confirm which qualifying round pays points: Q1 only, Q2, or both. Also check
      whether riders who qualify through Q2 get qualifying points, and how many
      places score. Set `QUAL_POINTS` and `QUAL_POINTS_ROUND`. If both rounds pay,
      extend `actual_event_points` and `simulate_weekend`.
- [ ] Check the edge cases:
  - [ ] DNF/DSQ in the Final: zero points, or last-place points?
  - [ ] Ties
  - [ ] Protected or wildcard riders who get into the Final without qualifying
  - [ ] Any bonus or double-points rounds (e.g. the season finale)
- [ ] **Reconcile against the official standings:** run `actual_event_points` on
      `splits.csv` and compare each rider's cumulative total after round 7 with the
      official UCI standings. Every rider should match exactly; any difference
      points to a table error or a parsing issue in `data/`.
- [ ] Add a small test that checks those totals against the official standings,
      so a points change or bad data file is caught right away.
- [ ] Re-run `predictor.py season` and refresh the tables in [What it does](#what-it-does).
