# racinglines

<!-- Sections between include markers are generated from docs/ by build_readme.py.
     Edit the tagged section in docs/, then run: python scripts/build_readme.py -->

<!-- include: tagline -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

**Fair prices for race sports, strictly as of any moment, tested on real market
tapes.** racinglines turns official timing into win, podium, head-to-head and
championship odds, then trades them against the market:

- **Formula 1** against Polymarket;
- **UCI downhill** mountain biking through a private book.

<!-- /include -->

**Live demo:** [racinglines.bet](https://racinglines.bet) (one click: *Try as
maker* / *Try as taker*) · [pitch](https://racinglines.bet/pitch). Demo password:
`password`.

## At a glance

<!-- include: glance -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

| | |
|---|---|
| 🏎️ **129 F1 races backtested** | 2021 to Baku 2026. Each race is priced three times: before practice, before qualifying and after qualifying. After qualifying, top-10 Brier is **0.149**, against 0.163 for a grid-only guess. |
| ⏱️ **Practice pace prior** | Before qualifying, it cuts podium error by **8%** and teammate head-to-head error by **4%**. |
| 💹 **The full 2026 season on Polymarket's real tape** | 15 weekends, re-priced after every session. **Market making: +$751** on $8,969 filled. After FP1, FP2, sprint qualifying and the sprint, the model's race-winner odds beat Polymarket's. |
| 🚵 **43 downhill World Cup rounds** | 2021–2026, walk-forward. Error on who makes the Final is **38% lower** than a uniform guess (0.127 vs 0.204). The actual winner got **7.1%** on average, against ~1% for a uniform guess. |
| ✅ **Checks in seconds** | `racinglines check` runs 21 checks (code, every data source, database) in ~10 s. The **regression suite** runs 108 tests on pinned public fixtures and golden outputs, and **zero data** is in git. |

What's not there yet: **taking** Polymarket's price after qualifying still loses
(Polymarket is sharper there, with a win Brier of 0.060 against our 0.072), and
the season-long championship strategy is down $208 so far. The results below have the
details.

<!-- /include -->

## Results

### Formula 1: how accurate?

<!-- include: f1-accuracy -->
<!-- generated from docs/f1.md by build_readme.py - edit it there -->

**Backtest run 115** (2026-09-26) covers 129 races, 2021 to Baku 2026. Each race
is priced three times, using only sessions that had ended:

- before any practice;
- before qualifying (practice known);
- after qualifying (grid known).

Brier scores, lower is better:

| | Before practice | Before qualifying | After qualifying | Grid-only guess | Uniform |
|---|---|---|---|---|---|
| Win | 0.041 | 0.038 | 0.033 | **0.031** | 0.047 |
| Podium | 0.091 | 0.088 | **0.071** | **0.071** | 0.127 |
| Top 10 | 0.187 | 0.175 | **0.149** | 0.163 | 0.250 |
| Teammate head-to-head | 0.231 | 0.228 | **0.197** | | |

- **Every session sharpens the price.** Error falls at each step, from before
  practice to after qualifying.
- **After qualifying:**
    - **top 10** clearly beats a grid-only guess;
    - **podium** ties it;
    - **win** is still slightly worse: the model underweights the front of the
      grid (on the [TODO](docs/todo.md#f1-model) list).
- **Against Polymarket** (2026, race-winner markets), the model beats the
  market mid-weekend (after FP1, FP2, sprint qualifying and the sprint). The
  market is sharper after FP3 and qualifying (see
  [the season sweep](docs/market-making.md#season-sweep)).

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
  a data gap (see [TODO](docs/todo.md)), not a modelling one.

Slopes have standard errors of 0.15–0.8 (a title's markets are not independent),
so read them as direction, not size.

<!-- /include -->

More: the Baku minute-by-minute diagnostic and the championship-market strategy
are in [Market making](docs/market-making.md).

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
**Williams 71.1%**, Vermette 18.8%, Pierron 4.2%, Iles 4.1%
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
| **Regression suite** | `python -m pytest -m "not live"` | 108 tests: every pipeline stage on pinned F1 and downhill fixtures, compared with golden outputs | ~10 s (+ a one-time fixture build) | Postgres and `scripts/fetch_test_fixtures.py` |
| **Everything** | `python -m pytest` | 139 tests, adding smoke tests on the working database, the web app and roles | ~35 s | the working database |

- **No data in git:** fixtures are built locally from the public sources (FastF1,
  ChronoRace, Polymarket). A guard test fails if anything data-like is tracked.
- **Results can't drift silently:** an intended change is re-baselined with
  `UPDATE_GOLDEN=1`.

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
docker compose up -d                                   # PostgreSQL on localhost:5433
racinglines db init                                    # tables + reference data

racinglines f1 fetch && racinglines f1 ingest          # F1 sessions (FastF1) -> database
racinglines f1 forecast --save                         # live F1 prices: remaining races + championships
racinglines markets sync                               # Polymarket's F1 markets

racinglines mtb_dh ingest                              # downhill event files -> database
racinglines mtb_dh forecast --db --save                # downhill season forecast

ADMIN_PASSWORD=... racinglines web                     # the app on http://127.0.0.1:8000
```

<!-- /include -->

## What it does

<!-- include: overview -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

```
official timing ──> PostgreSQL ──> as-of model ──> simulated weekends ──> fair prices ──> markets
 (FastF1,           (one multi-     (only sessions   & seasons             (win, podium,   (Polymarket,
  ChronoRace)        sport schema)   ended before     (thousands of runs)   h2h, pole,      private book;
                                     the cutoff)                            titles)         replays, Lab)
```

- **Collects** official timing into one multi-sport **PostgreSQL** schema:
    - F1 via FastF1: every practice, qualifying, sprint and race session since
      2020;
    - downhill split timing from ChronoRace, 2021–2026.
  
  Heavy exchange history (prices, trades, order books) goes to a **Parquet
  archive**.
- **Models** each sport:
    - **F1:** a sector-aware car model shared by both team drivers, driver
      offsets, a practice-pace prior, and a grid/overtaking finishing model;
    - **Downhill:** a log-time model of each rider's pace, consistency and
      crash/DNF rate.
- **Simulates** race weekends and seasons thousands of times: win, podium,
  top 10, pole, head-to-head and team markets, plus championships.
- **Prices strictly as of a moment:** only sessions that have ended before the
  cutoff are used, and a leakage guard enforces it. Backtests, diagnostics and
  live forecasts all call the same function.
- **Tests strategies on real market data:** these all run on Polymarket's
  recorded prices and trades:
    - maker replays;
    - taker strategies that re-trade after every session;
    - a season-long championship strategy.
- **Web app** ([racinglines.bet](https://racinglines.bet)):
    - **Markets:** fair price vs each venue;
    - **My Book:** positions across venues;
    - **Lab:** launch backtests, scenario forecasts, diagnostics and strategy
      replays with your own settings; compare and promote them.

<!-- /include -->

## Explore the docs

<!-- include: layers -->
<!-- generated from docs/index.md by build_readme.py - edit it there -->

Each layer builds on the one before, so start at the top and stop when you
have what you need.

| Layer | Page | What's there |
|---|---|---|
| 1. **Data** | [Data](docs/data.md) | Sources, what was downloaded, and the on-disk layout (`data/raw`, `archive`, `runs`, `cache`) |
| | [Parser](docs/parser.md) | Downhill results formats and the tidy schema |
| | [Database](docs/database.md) | The multi-sport schema, ingest, stored runs, and what stays in Postgres vs Parquet |
| 2. **Models** | [Formula 1](docs/f1.md) | Car and driver pace, practice prior, finishing model, as-of pricing |
| | [Downhill model](docs/model.md) | Log-time rider model, weekend formats, season simulation |
| 3. **Accuracy** | [Formula 1 → Results](docs/f1.md#results) | 129-race backtest, A/B tests of each model change |
| | [Downhill evaluation](docs/evaluation.md) | 43-round walk-forward, per season and per event |
| | [Downhill forecast](docs/forecast.md) | The live 2026 title projection |
| 4. **Markets** | [Market making](docs/market-making.md) | Baku diagnostic, maker replay, full-season sweep, season strategy |
| | [Web app & trading](docs/webapp.md) | Roles, pages, the Lab, the private book, Polymarket orders |
| 5. **Operate** | [CLI reference](docs/cli.md) | Every command and option |
| | [Testing](docs/testing.md) | Quick check, regression suite, fixtures, golden outputs |
| 6. **Background** | [Project history](docs/history.md) · [TODO](docs/todo.md) | How it got here, and what's next |
| | [F1 roadmap](docs/f1-roadmap.md) · [F1 reference](docs/f1-reference.md) | The phased F1 plan with its ground rules, and the model and market-making ideas behind it |

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
matches the docs, and no data files are tracked. Enable it once per clone:

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
| `racinglines/sources/` | Data sources: `fastf1/` (fetch, ingest), `chronorace/` (download, parse, ingest) |
| `racinglines/models/` | Model families: `position_sim/` (F1: car/driver pace, practice prior, race and season pricing), `timed_runs/` (downhill: log-time model, weekend and season simulation) |
| `racinglines/markets/` | Exchanges and books: Polymarket `sync`/`trade`, the Parquet `store`, `venues`, the `private_book`, and `strategies/` (maker replay, weekend taker, season) |
| `racinglines/pipelines/` | Multi-stage runs: `weekend_sweep`, `season_strategy` |
| `racinglines/db/` | Database: models, reads, queries, shared ingest helpers, registry of sports and venues |
| `racinglines/web/` | The web app (`racinglines web`): Markets, My Book, Lab, admin |
| `racinglines/testing/` | Synthetic data and the checks behind `racinglines check` |
| `sports/*.toml`, `racinglines/sports.py` | Sport schemas: what differs between sports (sessions, points, categories, venues, markets), read by the code |
| `racinglines/paths.py` | Where data lives (`data/raw`, `data/archive`, `data/runs`, `data/cache`) |
| `migrations/`, `alembic.ini` | Alembic schema migrations |
| `tests/`, `scripts/fetch_test_fixtures.py` | Regression suite on fixtures built from public sources, plus golden outputs (see [Testing](docs/testing.md)) |
| `scripts/build_readme.py` | Regenerates README sections from tagged docs sections |
| `docker-compose.yml` | Local PostgreSQL 17 (port 5433) |
| `pyproject.toml`, `requirements.txt`, `requirements-docs.txt` | Package (`pip install -e .` for the `racinglines` command); pinned dependencies (pipeline / docs site) |
| `data/` (not in git) | Downloads, the market archive, run outputs and caches |
| `docs/`, `mkdocs.yml` | Documentation site (MkDocs) |

<!-- /include -->

## TODO

Full list: [`docs/todo.md`](docs/todo.md).

<!-- include: todo-summary -->
<!-- generated from docs/todo.md by build_readme.py - edit it there -->

**F1 model and trading** (phased in the [F1 roadmap](docs/f1-roadmap.md))

- [x] F1-0: CLOB V2 check (it's V1: fix below); market recorder persistent (LaunchAgent).
- [ ] **Migrate order signing to Polymarket CLOB V2** (`py-clob-client-v2`). V1 orders are rejected
      on production since 2026-04-28. Required before enabling trading.
- [x] F1-1: `racinglines f1 compare` (paired ± 2 SE tables), log loss, reliability curves.
- [x] F1-2: fix the front-of-grid weighting: after qualifying, the model loses to a
      grid-only guess on the win market (`gridq`: 0.0306 vs 0.0309).
- [ ] **Promote `gridq+pretrain` to the default** (owner's OK: it changes live prices;
      re-run the sweep and `UPDATE_GOLDEN` in the same change).
- [x] F1-2: pre-practice pricing: train the finishing model for the no-practice case too.
- [x] F1-4: stage-aware taker strategy (stop re-trading after FP3 and qualifying): +$1,874, in-sample.
- [ ] F1-4: confirm the stage-aware taker on events after Baku.
- [x] F1-4: inventory skew that grows before each session, flatten before quali, widen on bad markouts.
- [ ] F1-4: replay with recorded book depth and a queue model (needs recorded books: from 2026-09-26).
- [ ] **Download and backtest 2025 on Polymarket** (~150 events over 25 GPs, $441M traded; minute
      prices and trades are still served for closed markets, order books are not). Run the weekend
      sweep, the season strategy and the checkpoints on 2025: an out-of-sample test for the
      stage-aware taker and `reset` (both came from 2026), and a normal season to contrast with
      2026's regulation reset. Maker replays run on prices and trades only (no 2025 books).
- [ ] F1-2: driver layer in a new season: the teammate offset carries last season (2026: Russell
      priced far above Antonelli after 3 GPs). Candidate: faster forgetting for second-year drivers,
      judged on every season, not 2026 alone.
- [ ] Data: ingest pre-season testing (FastF1 testing sessions), so the pre-season forecast sees
      what the market sees in a new-regulations year.
- [x] F1-3: chaotic-race tail, correlated DNFs (`tail`: neutral, not promoted).
- [ ] F1-3: safety-car / red-flag / rain props (deferred: no strategy trades them yet).

**Downhill: points validation (highest priority)**

- [ ] Get the official UCI DHI points scales (Final and qualifying), for 2026 and
      past formats, and settle the edge cases.
- [ ] Check our 2026 totals against the official standings, and pin them in a test.
- [ ] Re-run and refresh the published numbers.

**Downhill: data and model**

- [ ] Key riders by UCI ID; parse the 2021 PDFs; add Women's categories, start order
      and weather.
- [ ] Check calibration (win probabilities look too flat); tune over all 43 rounds.
- [ ] Find a venue that lists downhill markets (none on Polymarket as of 2026-09).

**Platform**

- [x] Sport schemas (`sports/*.toml`), read by the existing code, so the differences
      between sports are configuration. Additive only (see the [F1 roadmap](docs/f1-roadmap.md) decision log).
- [x] F1 roadmap: F1-0 to F1-4 done (see the [matrix](docs/market-making.md#model-strategy-matrix)); F1-5 deferred.
- [ ] Kalshi as a second exchange.
- [ ] Per-maker exposure limits, per-taker limits and ledgers.
- [ ] Condition in-weekend forecasts on completed rounds (Q1 results, split times).

<!-- /include -->
