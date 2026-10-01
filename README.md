# racinglines

<!-- Sections between include markers are generated from docs/ by build_readme.py.
     Edit the tagged section in docs/, then run: python scripts/build_readme.py -->

<!-- include: tagline -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

**Tools for an edge in race-sport prediction markets.** racinglines turns
official timing into win, podium, head-to-head and championship odds, priced
strictly as of any moment and tested on real market tapes, and gives makers and
takers the tools to find and size an edge inside the existing markets. Two
sports mark the ends of the range we build for:

- **Formula 1**, the big end: priced against Polymarket, with live paper trading
  from October 2026;
- **UCI downhill** mountain biking, the small end: modelled and forecast, waiting
  for an exchange to list it.

New sports qualify when their audience and expected market liquidity sit between
the two. **NASCAR Cup** and **MotoGP** are the first: results, market links on
Kalshi, Polymarket and OG.com, and a simple result-only model in replay, with no
edge yet that held up in a second season. Where every sport stands on every
exchange: [Sports and exchanges](docs/coverage.md).

<!-- /include -->

**Live demo:** [racinglines.bet](https://racinglines.bet) (one click: *Try as
maker* / *Try as taker*) · [pitch](https://racinglines.bet/pitch). Demo password:
`password`.

## At a glance

<!-- include: glance -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

| | |
|---|---|
| 🏎️ **129 F1 races backtested** | 2021 to Azerbaijan 2026. Each race is priced before practice, before qualifying and after qualifying. After qualifying, top-10 Brier is **0.149** against 0.163 for a grid-only guess; the best variant also beats it on win and podium. |
| 💹 **Every Polymarket F1 race weekend, replayed** | 38 weekends (2025 and 2026) on the real prices and trade tape. The default maker made **+$751** on $8,969 filled in 2026. |
| ☁️ **1,161 strategy combinations searched** | A 4-hour cloud search found two setups that held up in both seasons: **A** (a taker, +$1,232 in 2026 / +$1,237 in 2025) and **C** (a maker, +$653 / +$835, the best Sharpe of any combination). |
| 📡 **Live paper trading** | A and C run on every F1 weekend Polymarket lists, through 2027, stage by stage, with heat ratings, alerts and paper positions, through the same code as the backtest (checked trade for trade). Polymarket has listed no race since Baku (28 Aug 2026). |
| 🔴 **Live events** | The Whistler downhill final (27 Sep 2026) followed live from UCI timing: rank probabilities after every update, a maker re-quoting every rider, 1,000 simulated private-book takers and a hype-picking demo taker, P&L by venue. F1 next: the Bahrain GP at Sepang (2–4 Oct 2026), a private book on all 100 usual race markets. |
| 🏁 **Three exchanges, eight sports** | Polymarket, Kalshi and OG.com (OG.com read-only, from one schema file). F1 is the only sport with a real model and a backtest that held in a held-out season (on Polymarket). NASCAR on Kalshi: 2026 **+$4.2k to +$5.5k** in the taker replay but **−$242 to −$390** in 2025 in every setting, on spiky last-trade prices, so not robust. MotoGP: race win only, no held-out season. Both show in the app (status table, next races, an in-sample demo paper record on Kalshi). IndyCar, road cycling, Le Mans and SailGP: recorded tapes, no model. Of the 3 × 3 soft-launch grid (F1, NASCAR, MotoGP × Polymarket, Kalshi, OG.com), 7 cells hold data; MotoGP on Polymarket and OG.com are empty. [Status matrix](docs/coverage.md#the-status-matrix). |
| 🎮 **Fantasy trading, next** | An invite-only F1 soft launch with paper money (F$) is planned for Thu 8 Oct 2026 (Singapore), after CI, a staging host and sign-up are built. [Fantasy soft launch](docs/fantasy-launch.md). |
| 🚵 **43 downhill World Cup rounds** | 2021–2026, walk-forward. Error on who makes the Final is **38% lower** than a uniform guess (0.127 vs 0.204); the actual winner got **7.1%** on average, against ~1%. |
| ✅ **Checks in seconds** | `racinglines check` runs 21 checks (code, every data source, database) in ~10 s; the regression suite runs 174 tests on pinned public fixtures and golden outputs. |

The goal isn't to out-predict the market everywhere: on race-winner odds
Polymarket is about as sharp as the model (sharper after qualifying, and in 2025
at every stage). The tools act only where the gap is large, and quote where it's
safe. Nothing is traded with real money until paper trading has validated the
backtests. The pages below have the details.

<!-- /include -->

## Results

### Formula 1: how accurate?

<!-- include: f1-accuracy -->
<!-- generated from docs/f1-evaluation.md by build_readme.py - edit it there -->

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
  win and podium too ([variants](docs/f1-evaluation.md#model-variants-f1-roadmap-f1-2-f1-3)).
- **Against Polymarket** the picture is mixed. In 2026 the model's race-winner
  prices beat the market mid-weekend (after FP1, FP2, sprint qualifying and the
  sprint) and lose after FP3 and qualifying. In 2025 the market is sharper on
  race winners at every stage (see [Against Polymarket](docs/f1-evaluation.md#against-polymarket)).

<!-- /include -->

### Formula 1: trading the 2026 season on Polymarket

<!-- include: f1-trading -->
<!-- generated from docs/market-making.md by build_readme.py - edit it there -->

**Every 2026 weekend through Baku, traded on Polymarket's recorded prices**
(sweep run 191). Each stage is priced with the current model (shared car,
practice prior), with a 1¢ cost per share:

| Strategy | P&L | Bought / filled | Weekends up |
|---|---|---|---|
| **Maker replay** (conservative fills, ±2¢) | **+$751** | $8,969 | 7 / 15 |
| Enter before running, hold | +$214 | $6,954 | 7 / 15 |
| Enter after qualifying only | −$15 | $3,254 | 6 / 15 |
| Update & rebuy after each session | −$479 | $11,100 | 5 / 15 |

- **Making markets pays; taking doesn't yet.** Earning the spread from flow
  beats paying it on a model that isn't sharper than the market at every stage.
- **Mid-weekend the model beats Polymarket.** Race-winner Brier, model vs
  market:

  | After | FP1 | FP2 | SQ | Sprint | FP3 | Quali |
  |---|---|---|---|---|---|---|
  | Model | **0.077** | **0.080** | **0.062** | **0.088** | 0.093 | 0.072 |
  | Polymarket | 0.078 | 0.084 | 0.067 | 0.101 | **0.085** | **0.060** |

- **Re-trading after FP3 and qualifying is where it loses:** −$1,187 and
  −$1,166. Trades after FP1, FP2 and the sprint earned +$1,944.

<!-- /include -->

### Formula 1: which model, traded which way

<!-- include: f1-matrix -->
<!-- generated from docs/market-making.md by build_readme.py - edit it there -->

**Which model, traded which way?** P&L in $ on 2026 rounds 1–15 (weekends up of
15 in brackets); season strategy is the championship markets through Baku.

| Strategy | baseline | `gridq` | `pretrain` | **`gridq+pretrain`** | `tail` | `gbm` | `reset` | `gridq+pretrain+reset` |
|---|---|---|---|---|---|---|---|---|
| Maker, conservative (default) | +751 (7) | +874 (9) | +750 (7) | **+874 (9)** | +877 (9) | +557 (8) | +703 (8) | +933 (9) |
| Maker, info-timed skew | +650 (7) | +1,071 (9) | +649 (7) | **+1,070 (9)** | +792 (9) | +576 (9) | +686 (9) | +979 (8) |
| Maker, widen on bad markouts | +638 (8) | +1,008 (9) | +633 (8) | **+1,003 (9)** | +796 (9) | +434 (9) | +700 (9) | +751 (8) |
| Maker, flatten before quali | −58 (6) | +236 (10) | −57 (6) | **+237 (10)** | +125 (6) | +148 (7) | −57 (8) | +402 (9) |
| Maker, all three | −86 (7) | +478 (9) | −86 (7) | **+478 (9)** | +34 (8) | −28 (9) | −123 (7) | +310 (7) |
| Taker, enter & hold | +214 (7) | +215 (7) | +287 (7) | **+288 (7)** | +279 (7) | +81 (7) | +758 (7) | +835 (7) |
| Taker, after quali only | −15 (6) | +417 (4) | −15 (6) | **+417 (4)** | −114 (5) | −68 (5) | +117 (6) | +486 (6) |
| Taker, update every session | −479 (5) | −127 (6) | −395 (5) | **−43 (6)** | −558 (5) | −579 (6) | −140 (6) | +242 (7) |
| Taker, stage-aware ‡ | +1,874 (7) | +1,874 (7) | +1,953 (7) | **+1,953 (7)** | +1,898 (7) | +1,460 (7) | +2,205 (7) | +2,264 (8) |
| Season strategy (titles) | −208 | −208 † | −211 | **−211 †** | −220 | −262 | −354 | −349 † |

**And how accurate is each?** Brier, lower is better; ▲ / ▼ = better / worse
than baseline beyond 2 standard errors, paired over 129 races (2021 to Baku 2026).

| Model | Podium, before practice | Podium, before quali | Win, after quali | Podium, after quali | Top 10, after quali | Teammate h2h, after quali |
|---|---|---|---|---|---|---|
| grid-only guess | | | 0.0309 | 0.0708 | 0.1630 | |
| baseline | 0.0913 | 0.0878 | 0.0325 | 0.0712 | 0.1494 | 0.1971 |
| `gridq` | 0.0913 | 0.0878 | 0.0306 ▲ | 0.0691 ▲ | 0.1494 | 0.1956 ▲ |
| `pretrain` | 0.0893 ▲ | 0.0878 | 0.0325 | 0.0712 | 0.1494 | 0.1971 |
| **`gridq+pretrain`** | **0.0893 ▲** | 0.0878 | **0.0306 ▲** | **0.0691 ▲** | 0.1494 | **0.1956 ▲** |
| `tail` | 0.0912 | 0.0878 | 0.0325 | 0.0712 | 0.1495 | 0.1971 |
| `gbm` | 0.0917 | 0.0907 ▼ | 0.0336 | 0.0732 ▼ | 0.1543 ▼ | 0.2055 ▼ |
| `reset` | 0.0906 | 0.0873 ▲ | 0.0325 | 0.0711 | 0.1495 | 0.1971 |
| `gridq+pretrain+reset` | 0.0886 ▲ | 0.0873 ▲ | 0.0307 ▲ | 0.0692 ▲ | 0.1495 | 0.1956 ▲ |

- **The grid term is what pays.** Once the real grid is known, `gridq` lifts
  every maker strategy by $120–$560 and turns "enter after qualifying" from
  −$15 to +$417. It's the first model that beats the grid-only guess on win
  odds after qualifying.
- **`pretrain` fixes pre-practice accuracy** (podium −2% error) but barely moves
  P&L, since little is traded before practice.
- **`gridq+pretrain` is the safest row:** better than baseline in every cell
  where it differs and worse nowhere. The default stays the baseline for now
  (owner's decision); the variants keep being iterated.
- **`tail` doesn't earn its place:** neutral on accuracy, mixed on P&L.
- **`reset` (new-regulations seasons discount earlier car data) adds on top.**
  With `gridq+pretrain` it is the most accurate model (better than baseline on
  five of six columns), and the first where every taker strategy makes money:
  update every session +$242, enter & hold +$835; the default maker makes
  +$933. It is worse on the championship markets (see
  [Checkpoint entries](docs/market-making.md#checkpoint-entries)). Its 2026 P&L is on the season
  that suggested it; its accuracy gain holds on 2022 too (see
  [Formula 1](docs/f1.md#model-variants-f1-roadmap-f1-2-f1-3)).
- **`gbm` is worse on both:** less accurate after practice and qualifying, and
  below baseline on every strategy but two maker options.
- **The championship markets lose under every model** (−$208 to −$262): the
  market prices each race's result before we trade an hour later.

‡ The stage-aware taker's rule came from this sweep, so it is in-sample. †
`gridq` prices the season the same as baseline (and `gridq+pretrain` as
`pretrain`): future races have no grid yet. Fifteen weekends are few; the P&L
differences between variants are not tested for significance, and picking the
best of ~60 cells flatters it.

<!-- /include -->

### Formula 1: championship markets, entered at fixed checkpoints

<!-- include: f1-checkpoints -->
<!-- generated from docs/market-making.md by build_readme.py - edit it there -->

**Championship checkpoints, 2026** (33 markets; P&L in $, slope in brackets; runs 751 and 836):

| Model | Pre-season → +3 GPs | After GP 3 → +3 GPs | After GP 6 → +3 GPs | All three, to date |
|---|---|---|---|---|
| baseline | −232 (−0.30) | −267 (−0.34) | −11 (−0.21) | −793 |
| `grid` | −235 (−0.30) | −275 (−0.39) | −8 (−0.23) | −791 |
| `pretrain` | −229 (−0.28) | −252 (−0.24) | −12 (−0.14) | −779 |
| `gbm` | −241 (−0.34) | −271 (−0.66) | +11 (−0.27) | −735 |
| `tail` | −233 (−0.30) | −270 (−0.36) | −11 (−0.19) | −797 |
| `grid+pretrain` | −232 (−0.29) | −257 (−0.29) | −11 (−0.19) | −777 |
| `pretrain+tail` | −229 (−0.28) | −255 (−0.26) | −14 (−0.16) | −777 |
| `grid+pretrain+tail` | −232 (−0.29) | −259 (−0.30) | −17 (−0.19) | −782 |
| `reset` | −244 (−0.36) | −176 (−1.37) | +2 (−0.40) | −576 |
| `pretrain+reset` | −252 (−0.35) | −168 (−1.28) | +3 (−0.36) | −572 |
| `grid+pretrain+reset` | −253 (−0.37) | −166 (−1.38) | +1 (−0.40) | −566 |

- **Early in a new-regulations season, the market knows more than we do.**
  Pre-season the model priced 2026 like 2025 (McLaren 84% for the
  constructors' title, Norris 46%); the market, having seen winter testing, had
  Mercedes at 41%. After 3 GPs the model still had McLaren at 38% against the
  market's 6%. Every model variant makes the same calls, because they share
  the car-pace layer.
- **After 6 GPs the model has caught up.** Its edges are small, and its biggest
  call (Antonelli at 78% vs the market's 70%) has since gone to 92%: to date,
  the slope is positive for every variant.
- **The finishing-model variants barely matter here.** The championship
  forecast is dominated by the car and driver paces, not the finishing model.
  `gbm` takes the fewest positions after GP 6 and loses least, by staying out.
- **`reset` fixes the car, not the driver.** In a season with new technical
  regulations it counts earlier seasons' car pace a quarter. After 3 GPs it has
  Mercedes at 72% (market 78%, baseline 49%), and it loses the least over all
  three entries (−$566 with `grid+pretrain`). But within Mercedes it backs
  Russell (49%) over Antonelli (16%; market 35%, and 70% three races later):
  the driver-vs-teammate offset still carries 2025, when Antonelli was a rookie.
  Every position it took after GP 3 moved against it.
- **Pre-season, no model can see what the market saw:** winter testing. That's
  a data gap (see [Roadmap](docs/todo.md)), not a modelling one.

Slopes have standard errors of 0.15–0.8 (a title's markets are not independent),
so read them as direction, not size.

<!-- /include -->

More: the Baku minute-by-minute diagnostic and the championship-market strategy
are in [Market making](docs/market-making.md).

### Formula 1: live paper trading

Profiles A (a taker) and C (a maker), found by a 1,161-combination cloud search,
run on every F1 weekend from October 2026 through 2027: stage-by-stage calls with
heat ratings, maker quotes, alerts and paper positions, through the same code as
the backtest. No real orders. See [Paper trading](docs/paper-trading.md).

### Downhill

<!-- include: headline -->
<!-- generated from docs/evaluation.md by build_readme.py - edit it there -->

**Downhill (UCI World Cup, Men Elite):** walk-forward backtest over 43 rounds,
2021–2026. Each round is predicted only from data before it, and the model beats
the uniform baseline on podium and make-Final in every season.

| | Model | Uniform guess |
|---|---|---|
| Brier score, making the Final | **0.127** | 0.204 |
| Brier score, podium | **0.0224** | 0.0259 |
| Win probability given to the actual winner (average) | **7.1%** | ~1% |
| Rank correlation, predicted vs actual points | **0.62** | 0 |

Per-season and per-round tables: [Downhill evaluation](docs/evaluation.md#results-every-season-with-data-20212026).

<!-- /include -->

<!-- include: forecast-summary -->
<!-- generated from docs/forecast.md by build_readme.py - edit it there -->

2026 title odds with 2 rounds left (Whistler in progress, then one more round):
**Williams 71.4%**, Vermette 18.6%, Iles 4.3%, Pierron 4.0%
([full forecast](docs/forecast.md#projected-final-standings)).

<!-- /include -->

<!-- include: points-warning -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

> ⚠️ **Downhill points are placeholders**
>
> Downhill championship points use approximate tables, not the official UCI
> scale. Every downhill number measured in points (expected points,
> standings, champion odds) is approximate until
> [points validation](docs/todo.md#points-validation) is done. Win, podium, top-10
> and make-Final probabilities don't depend on points.

<!-- /include -->

## Validation

<!-- include: validation -->
<!-- generated from docs/testing.md by build_readme.py - edit it there -->

Three levels, fastest first:

| | Command | Checks | Time | Needs |
|---|---|---|---|---|
| **Quick check** | `racinglines check` | 21 checks: every pipeline on synthetic data, every data source, the database | ~10 s | nothing downloaded; network and Postgres optional |
| **Regression suite** | `python -m pytest -m "not live"` | 174 tests: every pipeline stage on pinned F1 and downhill fixtures, compared with golden outputs | ~10 s | Postgres (fixtures and goldens are in git) |
| **Everything** | `python -m pytest` | 221 tests, adding 47 live tests on the working database: the web app's pages per role, Baku live data, retention | ~35 s | the working database |

- **Pinned in git (since 2026-09-28):** the test fixtures (2 MB, built from FastF1,
  ChronoRace and Polymarket) and the golden outputs, so every machine and cloud session
  compares against the same baseline. A guard test fails if any other data is tracked.
- **Results can't drift silently:** an intended change is re-baselined with
  `UPDATE_GOLDEN=1` and reviewed as a diff of `tests/golden/` in its PR.

<!-- /include -->

## Quickstart

<!-- include: quickstart -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
python3.14 -m venv .venv && source .venv/bin/activate  # Python 3.11+
pip install -r requirements.txt && pip install -e .   # dependencies + the `racinglines` command
racinglines check                                      # code, data endpoints, database (~10 s)
```

Then the full pipeline:

```
docker compose up -d                                   # PostgreSQL on localhost:5433 (or a conda Postgres: see Database)
racinglines db init                                    # tables + reference data

racinglines f1 fetch && racinglines f1 ingest          # F1 sessions (FastF1) -> database
racinglines f1 forecast --save                         # live F1 prices: remaining races + championships
racinglines markets sync                               # Polymarket's F1 markets

racinglines mtb_dh ingest                              # downhill event files -> database
racinglines mtb_dh forecast --db --save                # downhill season forecast

racinglines f1 profiles --assign-demo                  # strategy profiles A and C for the demo accounts
racinglines f1 signals                                 # live paper signals (outside a race weekend: a no-op)
ADMIN_PASSWORD=... racinglines web                     # the app on http://127.0.0.1:8000
```

<!-- /include -->

## What it does

<!-- include: overview -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
official timing ──> PostgreSQL ──> as-of model ──> simulated weekends ──> fair prices ──> markets
 (FastF1,           (one multi-     (only sessions   & seasons             (win, podium,   (Polymarket;
  ChronoRace)        sport schema)   ended before     (thousands of runs)   h2h, pole,      paper trading,
                                     the cutoff)                            titles)         replays, Lab)
```

- **Collects** official timing into one multi-sport **PostgreSQL** schema:
    - F1 via FastF1: every practice, qualifying, sprint and race session since
      2020;
    - downhill split timing from ChronoRace, 2021–2026.

  Exchange history (prices, trades, order books) goes to a **Parquet archive**.
- **Models** each sport:
    - **F1:** a sector-aware car model shared by both team drivers, driver
      offsets, a practice-pace prior, and a grid/overtaking finishing model, with
      challenger variants behind switches;
    - **Downhill:** a log-time model of each rider's pace, consistency and
      crash/DNF rate.
- **Simulates** race weekends and seasons thousands of times: win, podium,
  top 10, pole, head-to-head and team markets, plus championships.
- **Prices strictly as of a moment:** only sessions that have ended before the
  cutoff are used, and a leakage guard enforces it. Backtests, diagnostics, the
  live forecast and the signal engine all call the same function.
- **Tests strategies on real market data:** maker replays, taker strategies that
  re-trade after every session, and a season-long championship strategy, all on
  Polymarket's recorded prices and trades; settings searches run locally or in
  the cloud.
- **Paper trades live:** strategy profiles (A, a taker; C, a maker) produce
  signals at every stage of a race weekend, with heat ratings for takers,
  alerts, paper fills and positions. No real orders are placed.
- **Web app** ([racinglines.bet](https://racinglines.bet)):
    - **Markets:** makers see our fair price against each venue; takers see
      every Polymarket market with their strategy's call;
    - **Strategy** and **Positions:** the account's calls, track record, bankroll,
      P&L history and holdings;
    - **My Book:** in-app markets a maker quotes;
    - **Lab:** the Edge Finder, backtests, scenario forecasts, diagnostics and
      strategy replays with your own settings.

<!-- /include -->

## Explore the docs

<!-- include: layers -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

Each layer builds on the one before, so start at the top and stop when you
have what you need. F1 and downhill each have a model, an evaluation and a
forecast page, and F1 also has market pages. NASCAR, MotoGP and the tape-only
sports are summarised on one status page.

| Layer | Page | What's there |
|---|---|---|
| 0. **Status** | [Sports and exchanges](docs/coverage.md) | Every sport × exchange: data, model, backtest and its caveats, live or paper, and the gaps |

| 1. **Data** | [Data](docs/data.md) | Sources, what was downloaded, the on-disk layout, and what's in git |
| | [Parser](docs/parser.md) | Downhill results formats and the tidy schema |
| | [Database](docs/database.md) | The multi-sport schema, ingest, stored runs, the snapshot, and what stays in Postgres vs Parquet |
| | [Exchanges as schemas](docs/exchanges.md) | OG.com read from one TOML file: sync, tape, fair-price indicator, buy-all check |
| 2. **Formula 1** | [F1 model](docs/f1.md) | Car and driver pace, practice prior, finishing model, as-of pricing |
| | [F1 evaluation](docs/f1-evaluation.md) | 129-race backtest, model variants, against Polymarket |
| | [F1 forecast](docs/f1-forecast.md) | The next race and the championships |
| | [Market making](docs/market-making.md) | Maker replay, season sweeps, the model × strategy matrix, the cloud settings search, season strategy |
| | [Paper trading](docs/paper-trading.md) | Profiles A and C, the signal engine, heat, alerts, the demo accounts |
| 3. **Downhill** | [Downhill model](docs/model.md) | Log-time rider model, weekend formats, season simulation |
| | [Downhill evaluation](docs/evaluation.md) | 43-round walk-forward, per season and per event |
| | [Downhill forecast](docs/forecast.md) | The live 2026 title projection |
| 4. **Web app** | [Web app](docs/webapp.md) | Pages and routes, roles, demo accounts and sessions, the Lab, the private book, Polymarket orders |
| | [Live events](docs/live-events.md) | A race followed live: the live model, the maker's quotes, the private book's crowd, replay logs |
| 5. **Operate** | [CLI reference](docs/cli.md) | Every command and option, launchd agents, scripts |
| | [Cloud sweeps](docs/cloud-sweep.md) | Running settings searches on a cloud machine |
| | [Testing](docs/testing.md) | Quick check, regression suite, fixtures, golden outputs |
| 6. **Roadmap** | [Roadmap](docs/todo.md) · [F1 live test](docs/f1-live-roadmap.md) · [F1 roadmap](docs/f1-roadmap.md) | What's next, in priority order; this week's F1 live test; the phased F1 plan with its ground rules |
| | [Project history](docs/history.md) · [F1 reference](docs/f1-reference.md) | How it got here, and the model and market-making ideas behind the F1 plan |

<!-- /include -->

<!-- include: docs-build -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
pip install -r requirements-docs.txt
mkdocs serve        # live preview at http://127.0.0.1:8000
mkdocs build        # static HTML in site/
python scripts/build_readme.py   # refresh README.md from sections tagged in docs/
```

A pre-push hook blocks a push unless the docs build with `--strict`, the README
matches the docs, and no data outside the allow-list is tracked. Enable it once
per clone:

```
git config core.hooksPath scripts/hooks   # skip once with: git push --no-verify
```

<!-- /include -->

## Repo layout

<!-- include: repo-layout -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

| Path | |
|---|---|
| `racinglines/cli/` | The `racinglines` command: `f1`, `mtb_dh`, `markets`, `db`, `web`, `check` |
| `racinglines/sources/` | Data sources: `fastf1/` (fetch, ingest), `chronorace/` (download, parse, ingest), `http.py` (paced, retried requests for every source) |
| `racinglines/models/` | Model families: `position_sim/` (F1: car/driver pace, practice prior, variants, race and season pricing), `timed_runs/` (downhill: log-time model, weekend and season simulation) |
| `racinglines/markets/` | Exchanges and books: Polymarket `sync`/`trade`/`links`, Kalshi `client`/`sync`/`trade`, the Parquet `store`, `venues`, the `private_book`, new-market and signal `alerts`, and `strategies/` (maker replay, weekend taker, season) |
| `racinglines/pipelines/` | Multi-stage runs: `weekend_sweep`, `sweep_settings`, `search` (settings searches), `season_strategy`, `season_checkpoints`, `profiles`, `signals` (live paper trading), `story` and `demo_history` (the demo accounts) |
| `racinglines/db/` | Database: models, reads, queries, shared ingest helpers, the `snapshot`, registry of sports and venues |
| `racinglines/web/` | The web app (`racinglines web`): Markets, Strategy, Positions, My Book, Lab, admin; demo sessions (`demo.py`); old-URL redirects (`legacy.py`) |
| `racinglines/testing/` | Synthetic data and the checks behind `racinglines check` |
| `sports/*.toml`, `racinglines/sports.py` | Sport schemas: what differs between sports (sessions, points, categories, venues, markets), read by the code |
| `racinglines/paths.py` | Where data lives (`data/raw`, `data/archive`, `data/runs`, `data/cache`) |
| `migrations/`, `alembic.ini` | Alembic schema migrations |
| `tests/`, `scripts/fetch_test_fixtures.py` | Regression suite on fixtures built from public sources, plus golden outputs (see [Testing](docs/testing.md)) |
| `scripts/` | `build_readme.py`, `signals_parity.py`, `cloud/` (prepare and start a cloud run), launchd agents for the recorder and the signal engine, `hooks/pre-push` |
| `sweeps/` | Settings-search queues (TOML) |
| `docker-compose.yml` | Local PostgreSQL 17 (port 5433) |
| `pyproject.toml`, `requirements.txt`, `requirements-docs.txt` | Package (`pip install -e .` for the `racinglines` command); pinned dependencies (pipeline / docs site) |
| `data/` | Downloads, the market archive, run outputs and caches; only an allow-listed minimal set is in git (see [Data](docs/data.md)) |
| `docs/`, `mkdocs.yml` | Documentation site (MkDocs) |
| `pitch.html` | The pitch deck, served at `/pitch` (screenshots in `racinglines/web/static/pitch/`) |

<!-- /include -->

## Collaborators and beta testers

This repository is private only because cloud runs need a minimal data set
committed with the code, and we don't want to publish all of that data yet. We're
open to beta testers and collaborators, and happy to share the pipeline and
web-app code with anyone interested: ask for access.

## Roadmap

Priorities, then every open item: [`docs/todo.md`](docs/todo.md). This week's F1 live test:
[`docs/f1-live-roadmap.md`](docs/f1-live-roadmap.md).

<!-- include: todo-summary -->
<!-- generated from docs/todo.md by build_readme.py - edit it there -->

**The rule:** real markets first. Events are tiered ([Strategy 2026](docs/strategy-2026.md#event-tiers)):
**T1** a real market is listed, so paper-trade it with frozen profiles; **T2** a real market we don't
model yet, so record its tape; **T3** no market anywhere, so run a simulated pool (private book). T3
proves the pricing, not an edge.

**Where things stand (30 Sep 2026, evening; VM on `306a147`, #95 and #96 merged after it):** NASCAR and MotoGP went
from tape-only listings to sports the production app shows end to end: results, Kalshi markets identified with their
race, a simple-baseline price for NASCAR's next race, and an in-sample demo paper record on Strategy and Positions
(`RACINGLINES_SPORT_STATUS=1` and `RACINGLINES_SPORT_PAPER=1`, both on on the VM). The owner's 3 × 3 soft-launch grid
(F1, NASCAR, MotoGP × Polymarket, Kalshi, OG.com) has 7 of 9 cells filled; MotoGP × Polymarket (no linked markets) and
MotoGP × OG.com (not listed) are empty. **The only held-out-robust strategy is still F1 profile A on Polymarket**, which
has listed no F1 race since 28 Aug. Status per cell: [Sports and exchanges](docs/coverage.md). The full day:
[24-hour report](https://github.com/lalligagger/racinglines/blob/main/reports/2026-09-30-sports-exchanges-24h/report.md).

**Where things stood (29 Sep 2026, after the overnight roadmap batch, PRs #23–#45 merged):** U1, U5, U6, U7, U8, U9,
reconcile, the scorecard and the K sweep are built and merged (new behaviour behind switches, off by default). What
is left before round 16 is on the VM and with the owner: the Kalshi recorder (U2), the VM cutover, freezing K, the
loss cap and the tier call. Coverage of every sport × venue is in [Coverage](docs/coverage.md).

**Where things stood (28 Sep 2026):** no F1 race markets are open on either venue. Polymarket has
listed no race since 28 Aug; Kalshi listed 2025 races only 2–4 days out, so it may still list round 16.
The F1 championships are open and deep on both (drivers' ~$38M on Polymarket, ~$9M on Kalshi). Profile
C makes money on Polymarket's tape and loses on Kalshi's.

**P0 · Sprint to the fantasy soft launch (to Thu 8 Oct), in this order.** Work is grouped into feature-track
branches, one PR per track (owner, 2026-09-30); the track is named on each item.

- [ ] **HIGH · Build CI and the staging environment** (track `staging-ci`; STG-1 to STG-4, spelled out in PR #114's
      "Staging and CI deploys" section). STG-1 `staging.racinglines.bet`, a second app instance with its own
      database restored from the latest backup, trading flags off, behind Cloudflare Access; STG-2 a GitHub CI
      workflow on every push (`racinglines check`, `pytest -m "not live"`, `mkdocs build --strict`: today nothing
      runs on GitHub); STG-3 CI deploys a track branch to staging and runs the smoke check there; STG-4 the owner
      checks staging, merges, and `main` deploys to production as today. Every step needs the owner's go; the VM, DNS
      and the GitHub secret (deploy key or service account) need sign-off. The fantasy staging rehearsal (STAGE-1,
      Wed 7 Oct) runs on this host once it exists.
- [ ] **Sign-up** (track `signup`; SEC-1, MAIL-1, ACC-1, ACC-3 from [Fantasy accounts](docs/fantasy-accounts.md)): not
      built. Copilot builds it locally Fri 2 – Sat 3 Oct behind `RACINGLINES_SIGNUP=off`; the `fantasy_schema_v1`
      migration goes to the VM Tue 6 Oct (OWNER-8, backup and sign-off). Then the trading batch, STAGE-1, the go/no-go
      Thu 8 Oct 12:00 PDT and invite-only sign-up at 18:00 PDT ([Fantasy soft launch](docs/fantasy-launch.md)).
- [ ] **Recorders on the VM** (track `recorders`): the Kalshi recorder (U2), a tapes timer for NASCAR's Chase and
      MotoGP's last rounds (U9), an OG.com weekly `trades`/`history`/`books` timer (its API forgets after a month), and
      a forecast refresh after each NASCAR race. New VM units, so each needs a backup and the owner's sign-off.
- [ ] **Round 16 live paper** (2–4 Oct, Sepang): the F1 book opens about 01:30Z Fri 2 Oct; the demo taker (profile
      A) paper-trades from round 16. No deploys around it. Owner calls: loss cap and tier.
- [ ] **Coverage gaps in the 3 × 3** (track `sports-coverage`): MotoGP calendar ingest (upcoming events, so MotoGP gets
      a next-race price; a Mac probe of the calendar endpoint first); Polymarket MotoGP links (tag slug unverified;
      Mac probe first); `RACINGLINES_OG_VENUE=1` on the VM so the OG.com column shows (owner). MotoGP × OG.com stays
      empty: OG.com lists no MotoGP.
- [ ] **Champion replays after deploy** (#95, #96, merged 2026-09-30): deploy, then VM steps 5–7 of
      `handoffs/2026-10-01-season-replays.md` (backup first; not during the round 16 book). They are the first backtest
      of any OG.com cell.
- [ ] **Progress lines** (owner rule, 2026-09-30): every long job, cloud, Mac or VM, prints a flushed progress line
      at least every 5 minutes. The overnight run has per-step lines and a heartbeat since #99; the shared helper for
      searches, replays and demo-history is PR #114 (open).
- [ ] **Report reproducibility** (owner ask, 2026-09-30): REP-1 to REP-7 in PR #114 (a `SOURCES.md` per report,
      one skeleton, `racinglines report build`, pinned inputs, scripted screenshots at 1024 px and 150% zoom).

**P0 · This week (to Thu 1 Oct): be ready to trade round 16 on whichever venue lists it**

- [ ] **U2** Kalshi recorder on the VM ([Exchanges](docs/todo.md#exchanges)). Books every 5 minutes (plus OG.com) via `vm.sh record` (`scripts/vm/record_venues.sh`); open: a trades/tape pass and a continuous `markets record` mode.
- [x] **U1** Kalshi in the signal engine, so A and C can paper-trade Kalshi's race markets (PR #34, merged 2026-09-29; [Exchanges](docs/todo.md#exchanges)).
- [x] **U6** Championship sleeve, paper only (PR #29, merged; `f1 season-strategy --paper`). Its first live rebalance is round 16's result ([Live events](docs/todo.md#live-events)).
- [ ] Freeze A and C and pre-register the rules in [Paper trading](docs/paper-trading.md#validation-plan).
- [ ] Round 16 checkpoints: both venues checked Wed 30 Sep; the tier chosen Thu 1 Oct 18:00 PDT
      (T1 on Kalshi if it lists, otherwise T3, the private book); the book opens Thu 20:30 PDT.
      Plan: [F1 live test](docs/f1-live-roadmap.md).

- [ ] **Fantasy soft launch (owner, 2026-09-29):** invite-gated F1 fantasy trading (F$ paper money only) from
      Thu 8 Oct, Singapore (R17), with the VM reliability work before R16. Plan and owner dates:
      [Fantasy soft launch](docs/fantasy-launch.md); tasks and blocks in the [runbook](docs/fantasy-runbook.md).

**P1 · October (rounds 16–19): first live weekends on real markets**

- [ ] **STG · high priority (owner, 2026-09-30): build CI and a staging environment.** GitHub CI running the
      checks on every push, `staging.racinglines.bet`, and track branches deployed to staging and verified before
      `main` goes to `racinglines.bet`. Steps STG-1 to STG-4 in [Staging and CI deploys](docs/todo.md#staging-and-ci-deploys);
      the first owner decisions are staging on the same VM or its own, and GitHub's deploy credentials.
- [x] **U5** Kalshi sprint markets before Singapore (11 Oct); built in PR #36 behind `RACINGLINES_KALSHI_SPRINTS`, merged. Priced from the race's pole and win odds
      until **U13**, a real sprint model, lands ([F1 model](docs/todo.md#f1-model)).
- [ ] **U3** Kalshi maker profile K: swept (PRs #38, #41, merged; K = `gbm`, 2¢, 10-pt filter, 25 shares, $400 volume floor); **freezing it is the owner's call** before the United States GP (25 Oct).
- [x] **U7** Cross-venue disagreement log (PR #35, behind `RACINGLINES_DISAGREE`); **U8** settlement rules for relocated or cancelled races (PR #27, behind `RACINGLINES_CANCELLED_RACE_RULES`). Both merged; the owner's two assumptions for U8 are still to confirm.
- [x] Per-weekend reconciliation (`f1 reconcile`, PR #37) and the pricing scorecard (`f1 scorecard`, PR #28), both merged; run them after every weekend ([Paper trading](docs/todo.md#paper-trading)).
- [ ] **U9** Record Kalshi's NASCAR (Chase, finale 8 Nov), MotoGP and IndyCar tapes: code merged (PR #26); first live run on the VM 2026-09-29 and NASCAR/MotoGP tapes pulled in the overnight run (2026-09-30). **Still open: a timer**, so each race is recorded without a hand run ([New sports](docs/todo.md#new-sports)); in the soft-launch sprint's `recorders` track.
- [ ] **Parallel track, owner (2026-09-28): the downhill [Data](docs/todo.md#data) items are high priority for the next
      cloud session** (Elite/Junior Women, start order, weather). They don't touch the F1 weekends. Most
      need ChronoRace (`prod.chronorace.be`), which the cloud network blocks: allow it first, or run locally.

**P2 · November (rounds 20–22): the sizing review**

- [ ] About 12 Nov, after 4–6 live weekends: sizing decision and a walk-forward with rounds 16–20 added.
- [ ] Qatar (29 Nov) and Abu Dhabi (6 Dec) may be cancelled: settle by each venue's rules (U8).

**P3 · December: close 2026, set up 2027**

- [ ] 2026 season report; walk-forward re-selection of A′, C′ and K′ for 2027, frozen before Australia.
- [ ] **U10** F1 pre-season testing ingest; the `reset` and `gridq+pretrain` decisions for 2027.
- [ ] Decide whether NASCAR joins in 2027, from the recorded tapes and the data-source review.
- [ ] **U12** Move to Google Cloud; the first real V2 order only if the validation rules are met.
- [ ] **U11** Downhill off-season: points validation (the top downhill item), then the rest of data and
      model ([Points validation](docs/todo.md#points-validation), [Data](docs/todo.md#data), [Model](docs/todo.md#model)).

<!-- /include -->
