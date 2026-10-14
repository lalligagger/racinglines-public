# racinglines

[![Tests](https://github.com/lalligagger/racinglines-public/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/lalligagger/racinglines-public/actions/workflows/tests.yml)
[![CI](https://github.com/lalligagger/racinglines-public/actions/workflows/predeploy.yml/badge.svg?branch=main)](https://github.com/lalligagger/racinglines-public/actions/workflows/predeploy.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/github/license/lalligagger/racinglines-public)](LICENSE)

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

**Live demo:** [racinglines.bet](https://racinglines.bet) (one click: *Try the demo*, or sign up for the fantasy
league alpha) · [Racinglines 101](https://racinglines.bet/racinglines101) ·
[quickstart replay](https://racinglines.bet/docs/quickstart/term) · [pitch](https://racinglines.bet/pitch).

## At a glance

<!-- include: glance -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

| | |
|---|---|
| 🏎️ **129 F1 races backtested** | 2021 to Azerbaijan 2026. Each race is priced before practice, before qualifying and after qualifying. After qualifying, top-10 Brier is **0.149** against 0.163 for a grid-only guess; the best variant also beats it on win and podium. |
| 💹 **Every Polymarket F1 race weekend, replayed** | 38 weekends (2025 and 2026) on the real prices and trade tape. The default maker made **+$751** on $8,969 filled in 2026. |
| ☁️ **1,161 strategy combinations searched** | A 4-hour cloud search found two setups that held up in both seasons: **A** (a taker, +$1,232 in 2026 / +$1,237 in 2025) and **C** (a maker, +$653 / +$835, the best Sharpe of any combination). |
| 📡 **Live paper trading** | A and C run on every F1 weekend Polymarket lists, through 2027, stage by stage, with heat ratings, alerts and paper positions, through the same code as the backtest (checked trade for trade). Polymarket lists F1 race markets again: production's database holds them for every 2026 round from Italy (6 Sep) to Brazil (8 Nov), checked 2026-10-14. |
| 🔴 **Live events** | The Whistler downhill final (27 Sep 2026) followed live from UCI timing: rank probabilities after every update, a maker re-quoting every rider, 1,000 simulated private-book takers and a hype-picking demo taker, P&L by venue. Live events and private books are admin-only while the fantasy alpha runs ([Alpha layout](docs/alpha-layout.md)). |
| 🏁 **Three exchanges, eight sports** | Polymarket, Kalshi and OG.com (OG.com read-only, from one schema file). F1 is the only sport with a real model and a backtest that held in a held-out season (on Polymarket). NASCAR on Kalshi: 2026 **+$4.2k to +$5.5k** in the taker replay but **−$242 to −$390** in 2025 in every setting, on spiky last-trade prices, so not robust. MotoGP: race win only, no held-out season. Both show to every signed-in user (MotoGP again since 2026-10-14). Road cycling is priced by the same engine, for admins only. IndyCar, Le Mans and SailGP: recorded tapes, no model. Of the 3 × 3 grid (F1, NASCAR, MotoGP × Polymarket, Kalshi, OG.com), 8 cells hold data; only MotoGP on OG.com is empty (OG.com doesn't list it). [Status matrix](docs/coverage.md#the-status-matrix). |
| 🎮 **Fantasy league alpha, open** | Every signed-in account gets F$1,000 of fantasy money: trade F1 markets by hand on the recorded order books, or follow one of five strategy styles, and climb the leaderboard. No real money, nothing reaches an exchange. [Alpha layout](docs/alpha-layout.md), [Fantasy trading](docs/fantasy-trading.md). |
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
| **Regression suite** | `python -m pytest -m "not live"` | 174 tests: every pipeline stage on pinned F1 and downhill fixtures, compared with golden outputs | ~10 s | Postgres and the fixtures ([how to get them](docs/contributing.md#data-in-this-repository); goldens are in git) |
| **Everything** | `python -m pytest` | 221 tests, adding 47 live tests on the working database: the web app's pages per role, Baku live data, retention | ~35 s | the working database |

- **Pinned:** the test fixtures (2 MB, built from FastF1, ChronoRace and Polymarket) and the golden
  outputs, so every machine compares against the same baseline. The goldens are in git; the fixtures are not in
  the public repository ([how to get them](docs/contributing.md#data-in-this-repository)), and without them the
  fixture tests skip. A guard test fails if any data is tracked.
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

The demo ([Quickstart](docs/quickstart.md)): the real commands on a synthetic Mario Kart season, a separate database
built on first use (needs Postgres: `docker compose up -d`):

```
racinglines model backtest kart --demo                 # every past race priced as of before it, scored
racinglines model forecast kart --demo --save          # the rest of the season and the championships
racinglines live run kart/demo-2026-09 --demo --simulate --no-fetch # a live private book, 100 simulated takers
```

Then the full pipeline:

```
docker compose up -d                                   # PostgreSQL on localhost:5433 (or a conda Postgres: see Database)
racinglines db init                                    # tables + reference data

racinglines data fetch f1 && racinglines data ingest f1          # F1 sessions (FastF1) -> database
racinglines model forecast f1 --save                         # live F1 prices: remaining races + championships
racinglines markets sync                               # Polymarket's F1 markets

racinglines data ingest mtb_dh                              # downhill event files -> database
racinglines model forecast mtb_dh --db --save                # downhill season forecast

racinglines strategy profiles f1 --assign-demo                  # strategy profiles A and C for the demo accounts
racinglines strategy signals f1                                 # live paper signals (outside a race weekend: a no-op)
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
- **Web app** ([racinglines.bet](https://racinglines.bet)), laid out for the fantasy league alpha:
    - **Markets:** our fair price against each venue for each sport's next races;
    - **Trade** and **History:** fantasy trading in F$ on the recorded books, every trade, and the leaderboard;
    - **Lab:** follow a strategy style, its track record and positions, and the Edge Finder, backtests, scenario
      forecasts, diagnostics and strategy replays with your own settings.
- **Reaches the hosted server from the command line:** `--remote` runs the book commands and Lab jobs on
  racinglines.bet, `racinglines remote` calls any hosted tool, and `racinglines data pull SPORT` copies one sport's
  shared data into your own database ([MCP server](docs/mcp.md#more-commands-on-the-hosted-server-remote-racinglines-remote-data-pull)).

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
| `racinglines/cli/` | The `racinglines` command, task first: `data`, `model`, `strategy`, `markets`, `book`, `live`, `db`, `web`, `mcp`, `remote`, `check` and more ([CLI reference](docs/cli.md)) |
| `racinglines/sources/` | Data sources: `fastf1/` (fetch, ingest), `chronorace/` (download, parse, ingest), `http.py` (paced, retried requests for every source) |
| `racinglines/models/` | The one engine, `model_global.py` (every modelled sport's pricing model, its inputs declared in `sports/<code>.toml` [model]), and its input layers in `inputs/`: `laps.py`, `laps_pricing.py`, `practice.py`, `grid.py` (F1: car/driver pace, sectors, practice prior, race and season pricing), `run_times/` (downhill: log-time model, weekend and season simulation), `results.py` (finishing positions); `variants.py`, `props.py`, `evaluate.py` beside them |
| `racinglines/markets/` | Exchanges and books: Polymarket `sync`/`trade`/`links`, Kalshi `client`/`sync`/`trade`, the Parquet `store`, `venues`, the `private_book`, new-market and signal `alerts`, and `strategies/` (maker replay, weekend taker, season) |
| `racinglines/pipelines/` | Multi-stage runs: `weekend_sweep`, `sweep_settings`, `search` (settings searches), `season_strategy`, `season_checkpoints`, `profiles`, `signals` (live paper trading), `story` and `demo_history` (the demo accounts) |
| `racinglines/db/` | Database: models, reads, queries, shared ingest helpers, the `snapshot`, registry of sports and venues |
| `racinglines/web/` | The web app (`racinglines web`): Markets, Trade, History, Lab and admin under the alpha layout (`layout.py`; the older pages are archived behind it); demo sessions (`demo.py`); old-URL redirects (`legacy.py`) |
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

We're looking for beta testers and collaborators! Try the app at
[racinglines.bet](https://racinglines.bet), and if you'd like to help, test, or just say hi, drop us a line at
[hello@racinglines.bet](mailto:hello@racinglines.bet?subject=racinglines%20beta%20tester%20%2F%20collaborator).
We'd love to hear from you. The [contributor guide](docs/contributing.md) says how to get set up.

### Data in this repository

<!-- include: public-data -->
<!-- generated from docs/contributing.md by build_readme.py - edit it there -->

This public repository (`lalligagger/racinglines-public`) holds **code, docs, schemas and golden test outputs
only**. The data it was developed with (raw FastF1 sessions, the Polymarket and Kalshi price and trade archives,
database snapshots, the pinned test fixtures) was removed from this repository and its history when it went public
on 2026-10-01: some of it isn't ours to republish, and none of it belongs in git. It lives on the production
server and in a private bucket.

**Test fixtures are available to beta testers and contributors.** Two ways to get them:

- **Ask us** at [hello@racinglines.bet](mailto:hello@racinglines.bet?subject=racinglines%20test%20fixtures)
  for the pinned fixture bundle (about 2 MB). Unpacked into `tests/fixtures/`, the regression suite matches the
  golden outputs exactly.
- **With access to the private repository** (the owner's machines and cloud sessions):
  `bash scripts/restore_test_fixtures.sh` copies the pinned set from its git into `tests/fixtures/`, untracked.
- **Build them yourself** from the original public sources with `python scripts/fetch_test_fixtures.py --refresh`
  (needs Postgres; the F1 part can take up to an hour because FastF1 is rate limited). Today's data differs a
  little from the pinned set, so expect some golden tests to differ: that's fine for development.

Without fixtures the fixture-based tests are skipped, not failed, and everything else runs.

<!-- /include -->

## Roadmap

Priorities, then every open item: [`docs/todo.md`](docs/todo.md).

<!-- include: todo-summary -->
<!-- generated from docs/todo.md by build_readme.py - edit it there -->

**Where things stand (14 Oct 2026).** [racinglines.bet](https://racinglines.bet) runs the **fantasy league alpha**:
every signed-in account gets F$1,000 of fantasy money and four tabs, Markets, Trade, History and Lab
([Alpha layout](docs/alpha-layout.md)). Hand trading is F1 only, on the recorded Polymarket and Kalshi books; Markets shows
F1, NASCAR and MotoGP. Polymarket lists F1 race markets again (rounds 13 to 20 are linked); no real order is placed
(the trading flags are unset, [Sports and exchanges](docs/coverage.md)). The three recorders poll Polymarket, Kalshi and
OG.com every 5 minutes, every day. From the command line, `--remote`, `racinglines remote` and `racinglines data
pull SPORT` reach the hosted server, in testing, with a warning that the review of venue and data terms is still
pending ([MCP server](docs/mcp.md#more-commands-on-the-hosted-server-remote-racinglines-remote-data-pull)).

The goals (owner): **G1, October to early November, prove the edge**, closing-line value above +2% over 100 live
bets; **G2, November to December**, real fills, venue capacity, more users; **G3, January to March 2027**, billing.
The real-money gate stays at six or more live weekends. What is in flight now, in order: the staging-to-production
promotion (PR #180: MotoGP for every signed-in user, `data pull`, `remote`, race-data triggers); CLV on every fill;
the calibration check of every sport's model (C48); the Probalytics tape comparison (PR #181); the one engine for the
first package release (C56).

<!-- /include -->
