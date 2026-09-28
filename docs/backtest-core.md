# Backtest core: one engine for timed sports and prediction exchanges

The plan for backtesting (and tuning) any timed or racing sport against any prediction exchange with one
set of code. It is the backtest counterpart of the
[multi-sport live design](f1-live-roadmap.md#multi-sport-design-one-live-core-one-adapter-per-sport): one
shared core, and per sport only data (`sports/<code>.toml`), a data source and a model wrapper.

**Status:** step 1 done (market kinds, sweep calibration, search report); steps 2–6 proposed.
Every step ships off by default, with today's F1 and downhill outputs byte-identical.

## What the params-4h search taught us

The first long settings search (2026-09-27; [Cloud sweeps](cloud-sweep.md#the-params-4h-search)):
291 F1 season sweeps, 2026 tuned and 2025 held out.

**About F1 on Polymarket**

1. **The edge is in the less-watched markets.** Winner markets were about as sharp as the model (the
   best taker lost -379 on them in 2025); head-to-heads were the only kind that earned in both seasons.
2. **The bar to act depends on the market kind.** A 10-point edge threshold was the largest robust gain,
   but head-to-heads still paid at 5 points (hence `min_edge_h2h`).
3. **Timing is a strategy setting.** Pre-weekend entries lost in both seasons; after-quali was mixed.
4. **Takers and makers want different models.** Takers a reactive, grid-aware one; the only maker that
   earned in both seasons ran on `gbm` and stayed out of markets where it disagreed with the price.
5. **Takers and makers are separate sleeves:** their weekly P&L was nearly uncorrelated.

**About backtesting (every sport)**

6. **A held-out season decides.** Many 2026 winners lost in 2025 (the top 2026 combo: +4,442 / -742).
7. **One event can carry a season:** the British GP added +900 to +1,600 to every 2026 taker. Report the
   P&L without the best event.
8. **Monte Carlo noise is as large as many effects** (±67 to ±149 across simulation counts). Measure it
   with seed replicates.
9. **Execution realism can fake an edge.** Dropping the volume filter "made" +3k to +7k from stale
   prices; doubling stakes doubled the losses too. Fill rules, costs and liquidity filters are guards,
   not tuning knobs.
10. **Identity, not position.** A re-analysis renumbered a candidate into a different combo; an analysis
    run before the last job finished read partial data.
11. **Pricing is the expensive part.** Stage prices are cached by `model_key`, so strategy settings that
    share prices cost almost nothing.

## The design

Both model families already simulate the same thing: a matrix of finishing ranks. That is the seam.

| Contract | What it is | Where | Status |
|---|---|---|---|
| **Outcome simulations** | `OutcomeSims`: entrants, `(n_sims × n)` classification ranks, finished flags, earlier rounds' ranks, rounds reached, points, groups | `racinglines/models/outcomes.py` | done: adapters for `position_sim` and `timed_runs` |
| **Market kinds** | One definition per kind gives its fair value from `OutcomeSims` **and** its settlement from the official result | `racinglines/markets/kinds.py` | done: win, podium, top 10, pole, makes the Final, head-to-head, top constructor; `private_book.outcome_for` settles through it |
| **Pricing model** | `load`, `events(data, settings, seasons)` (each with its cutoff), `history(data, settings)`, `price(hist, event, settings, rng) -> OutcomeSims`, `results(data, event)` for settlement, and the model's own `Settings` | `racinglines/models/race_model.py` | done: `TimedRuns` (downhill) and `PositionSim` (F1, pre-race) |
| **Walk-forward engine** | Prices every event from data before it, settles every kind the simulations support, scores them; model-only until a venue is given | `racinglines/core/walk_forward.py` | done: `racinglines mtb_dh walk-forward` |
| **Stages** | When new information arrives: a `[stages]` table per sport (schedule source, data lag, early closes) turned into `[(label, cutoff)]` | `sports/<code>.toml` | step 5 |
| **Venues** | `markets()`, `view(market, t)` (public data up to t only), costs, fill model, resolution | `racinglines/markets/venue_replay.py` | done: `Polymarket` (the F1 sweep reads through it) and `PrivateBook` (a live run's book replayed); model-only is no venue. `Kalshi` reads what `markets/kalshi/` stores in the same tables, with Kalshi's taker fee (built on mocked data; nothing reads it yet) |
| **Search** | One queue for every sport, with the held-out rule, seed replicates, confirmation and stable ids built in | `racinglines/pipelines/search*.py` | done: `sport = "mtb_dh"` jobs, `replicates = N`, candidate ids carried into the Lab |

**Settings.** Shared groups (timing, taker, maker, markets, guards) plus the model's own group. Per-kind
overrides (e.g. `min_edge_by_kind`) generalise `min_edge_h2h`. `settings_key` / `model_key` keep today's
hashing (settings at an unset default are left out), so saved keys never change.

### The walk-forward engine

`racinglines mtb_dh walk-forward --db [--seasons 2025 2026] [--seed N] [--save]` runs a sport's pricing
model through `racinglines/core/walk_forward.py`: every completed event is priced from the runs before it
with its real start list and format, every market kind is settled from the official result, and the
fair values are scored (Brier, log loss, ECE, reliability bins) per kind and per season. The model's
settings (`racinglines/models/timed_runs/settings.py`: category, sims, half-life, pace shrinkage, junior
weight, training scope, t noise, seed) use the same schema, keys and flags as the F1 sweep's, so the
search queue treats a downhill job like an F1 one. `--save` stores a `walk_forward` model run whose
per-event scores (`<kind>_score` = −1000 × log loss, higher is better) are the search report's curves.

Check: over the 43 rounds of 2021–2026 the engine's per-rider fair values and outcomes equal
`walk_forward_season`'s exactly (5,171 riders × win, podium, top 10, makes the Final), and the tuning
table in [the downhill model](model.md#calibration) comes out the same through it (makes the Final
−0.035 ± 0.006, 6 of 6 seasons; top 10 −0.006 ± 0.006, 5 of 6; podium −0.003 ± 0.002, 6 of 6; win
−0.001 ± 0.001, 3 of 6).

### Venues in a backtest

`racinglines/markets/venue_replay.py` holds the venues a backtest trades against, each read only as of a
moment:

- **`Polymarket`**: the recorded 5-minute prices and trade tape of one weekend. `view(market, t)` gives
  the last price within 6 hours, the 24-hour traded volume and whether the venue would take an order
  (priced strictly inside 0–1, liquid enough); `coherent(kind, t)` is the multi-outcome sanity check;
  `resolve` settles through the market-kind catalogue. The F1 sweep's `weekend_markets` now reads
  Polymarket only through it.
- **`PrivateBook.from_run(run_dir)`**: a live run's private book (downhill polls or F1 windows) replayed
  from its logged quotes and seeds. With the recorded quotes it re-derives the live book exactly; with
  `spread_quoter(half_spread)` (or any `quoter(quote, inventory)`) it replays another quoting rule
  against the same crowd draws, which is how a maker setting is backtested on a past event.

Check: full 2025 and 2026 F1 sweeps are identical before and after the change (weekends and trades), a
synthetic downhill final recorded by `live_dh.update` replays to the same book (every market's
inventory and cash, every taker's budget, the late window), and so does an F1-style run folder. The
real Whistler book is checked by `tests/test_venue_replay.py` where the data bucket's run folder is present.

### Calibration in every sweep

`racinglines f1 sweep --reliability` scores **our fair value and the exchange's price side by side** at
every tradeable stage: Brier, log loss and ECE per market kind and stage, and reliability bins with a z
per bin (`racinglines/core/calibration.py`, shared by every sport). Pooled rows count a market once per
stage it was tradeable, so they are correlated; compare model with market on the same rows rather than
reading the absolute numbers.

### The search report

`racinglines f1 search-report QUEUE.toml` turns a finished search into labelled results
(`racinglines/pipelines/search_report.py`):

- **Labels** against the default-settings baseline, beyond a noise floor: **robust** (every season),
  **target only**, **held-out-led** (held-out seasons, target within noise), **not better**, or
  **no held-out run**. A held-out season may run the combo's *twin*: the same model with switches that
  are inert that season dropped (`variants.for_season`, e.g. `reset` outside a new-regulations year).
- **Noise floor:** the largest spread of seed replicates (jobs that differ only in `seed`, three or more)
  per strategy family; the configured floor where there are none. Replicates of a combo are averaged.
- **Same-fidelity baselines:** a run is compared with the baseline at its own simulation count, seed and
  rounds.
- **Confirmation** at `confirm_sims` (default 16,000) in every season the label rests on, when run.
- **Concentration:** P&L without the best event, and which event it was.
- **Better is not profitable:** a combo that beats a losing baseline but still loses money is flagged
  (`loses_money_in`), as the params-4h hold strategies were.
- **Stable ids:** a candidate is `<strategy>-<settings_key>` (file `candidates/<id>.json`); its rank is a
  field, never its name.
- **Finished jobs only:** running or failed jobs are never read.

A downhill job is scored per market kind instead of per strategy: its per-event score is −1000 × log
loss (higher is better), the noise floor family is `model` (±25 unless replicates measure it), and
combos are ranked by their gain over the baseline (a score is never positive, so "loses money" doesn't
apply). Its report goes to `data/runs/search/<name>/mtb_dh/`, configured by `[report.mtb_dh]`.

Check: a queue with a short F1 sweep and downhill jobs (the pre-tuning settings in 2026 at three seeds,
and in 2025) ran end to end: 10 jobs, both leaderboards, and a downhill report whose noise floor came
from the seed replicates (±4 per kind) and which labels the old settings "not better" on the Final,
podium and top 10 and "target only" on win and fastest qualifier.

```toml
[[job]]
sport = "mtb_dh"               # the downhill model's settings (racinglines/models/timed_runs/settings.py)
year = 2026
prior_n = 1.5
replicates = 3                 # this job and its season's baseline at 3 seeds each

[report]                       # optional, in the queue file
target = 2026
holdout = [2025]
confirm_sims = 16000
top = 25
noise = { taker = 150, maker = 350, model = 25 }   # used where the search ran no seed replicates

[report.mtb_dh]                # another sport's jobs: the same keys
target = 2026
holdout = [2025]
```

## Plan

| Step | What | Check |
|---|---|---|
| 1 ✓ | Market-kind catalogue; calibration in the F1 sweep; the search report | F1 sweeps byte-identical; the params-4h A and C numbers reproduced |
| 2 ✓ | `PricingModel` for both families; the downhill walk-forward through the engine in model-only mode | Downhill tuning numbers reproduced |
| 3 ✓ | Sport-aware search queue (downhill jobs), `replicates = N`, stable candidate ids in the Lab | A mixed F1 + downhill queue runs end to end |
| 4 ✓ | `Venue` interface: Polymarket behind it, Kalshi mock, private-book venue with the simulated crowd | F1 sweep identical; the Whistler book replays as a backtest (synthetic finals here; Whistler where the bucket is) |
| 5 | Stages from the schema; per-kind strategy overrides; settings split | Saved F1 `settings_key`s unchanged |
| 6 | "Adding a sport": schema + data source + model wrapper, nothing else | A synthetic third sport passes the suite |

The live engine keeps working throughout; once step 4 lands it can use the same venues and kinds.
