# Market making

How we test whether trading a market is worth it before risking money: on one
event in depth, then on a whole season.

| | What | Result |
|---|---|---|
| [Baku diagnostic](#baku-2026-09-26-first-test-event) | One race priced as of every moment, with a maker replay on the minute-level tape | Maker −$303 at default settings |
| [Season sweep](#season-sweep) | All 15 raced 2026 weekends, re-priced after every session | **Maker +$751**; taker strategies −$479 to +$214 |
| [Model × strategy matrix](#model-strategy-matrix) | Every model variant × every trading strategy | Weekends: `gridq+pretrain+reset` makes money with every taker and maker default (+$933); titles: every model loses |
| [Cloud settings search](#cloud-settings-search-params-4h) | 291 sweeps of settings on the 9 variants, 2026 and 2025 held out | Two profiles robust in both seasons: taker A +$1,232 / +$1,237, maker C +$653 / +$835 |
| [Season strategy](#season-strategy-championship-markets) | Championship markets, rebalanced after every race | −$208 (hold: −$532) |

## How the market works

- **The market is Polymarket's order book.** Takers are everyone who trades
  against resting orders; other makers post resting orders of their own.
  Together they set the price.
- **Takers see prices only.** They never see our fair value or our strategy.
- **Our maker is one participant.** It watches prices, trades and books, and
  posts post-only quotes where providing liquidity is worth it. A taker's order
  fills against whichever resting orders are best, so it may fill against us,
  against another maker, or against both.
- **Private books.** The app's in-house book for friends-and-family takers works
  the same way: takers see our quotes, not our fair values.

## Two separate things

| | Backtest | Diagnostic |
|---|---|---|
| Question | Is the model calibrated across many past races? | What would we have quoted for one event, and how would it have gone? |
| Command | `racinglines f1 backtest` | `racinglines f1 diagnostic --event 2026-15 --cutoff 2026-09-25T13:30 --save` |
| Prices | Every race, before qualifying and before the race | One event at a chosen cutoff |
| Stored as | `model_runs.kind = 'backtest'` | `model_runs.kind = 'diagnostic'` |

Neither one feeds the live app. Live fair prices come only from
`kind = 'forecast'` runs.

**No leakage.** Every run prices through `position_sim.pricing.price_race` with a hard cutoff:

- `Measurements.view(cutoff)` keeps only sessions that started before the cutoff.
- `assert_no_leak` raises `LeakageError` if anything later gets through.
- The finishing model trains only on races before the cutoff.
- The grid is the real qualifying order if qualifying ran before the cutoff;
  otherwise it's simulated.
- Polymarket prices are never used to fit or price anything. They're only
  compared afterwards.

## Data recorded from Polymarket

| Command | Table | Available for past events? |
|---|---|---|
| `racinglines markets history --events '<slug prefix>%' --start … --end … --fidelity 1` | `market_price_history` (minute prices per outcome token) | Yes |
| `racinglines markets trades --events '<slug prefix>%'` | `market_trades` (every taker trade: side, price, size, time) | Yes |
| `racinglines markets record --interval 60` | `market_book_snapshots` (top 10 bid/ask levels per token) | **No.** Polymarket has no historical book API, so this has to run before and through each race weekend. |

`markets record` snapshots every open modeled market once a minute. It re-syncs
Polymarket's F1 events every 30 minutes, so new race markets are recorded as
soon as they're listed.

## Data recorded from Kalshi

| Command | Table | Available for past events? |
|---|---|---|
| `racinglines markets --exchange kalshi history --events <event ticker> … --start … --end … --period 1` | `market_price_history` (per market ticker: the candle's traded close, else its bid/ask mid) | Yes; past Kalshi's cutoff (about two months) from `/historical` |
| `racinglines markets --exchange kalshi trades --events <event ticker> …` | `market_trades` (every trade: the taker's side of YES, YES price, contracts, time; no wallets) | Yes; the same cutoff |
| `racinglines markets --exchange kalshi books --events <event ticker> …` | `market_book_snapshots` (YES bids, and NO bids as YES asks) | **No.** One snapshot per call; there is no Kalshi recorder loop yet, so the queue fill rule has no Kalshi books |

The differences that matter for a replay are in
[Data](data.md#exchange-history-kalshi-and-polymarket). The biggest is that Kalshi's
`condition_id` is the event ticker, so its tape is read per market ticker.

Kalshi's F1 history from 2025 to 2026-09-28 is pulled and archived under `data/archive/markets/kalshi/`
([Data changes](data-changes.md)).

## The maker replay (`racinglines/markets/strategies/maker_replay.py`)

The replay steps through the event in 5-minute steps.

**What the maker knows at time t:**

- the fair value from the latest diagnostic run whose cutoff is at or before t;
- Polymarket's minute prices and trades up to t.

`PublicView` enforces this, and a test changes the tape after t to check that
the quote doesn't change.

**How it quotes:**

- **Price:** post-only bid and ask at fair ± half-spread, shifted against its
  inventory. The quotes never cross the market price, so YES bid + NO bid < $1.
- **Skips a market** when:
    - the price is outside 3–97¢;
    - less than $100 traded in the last 24 hours;
    - our fair value is more than 15 points from the market.
- **Limits:**
    - 50 shares per quote;
    - 250 shares per market;
    - $1,000 worst-case loss for the event, enforced on every fill.
- **Pulls quotes** 15 minutes before qualifying and before the race. Positions
  are held to the result.

**How it gets filled:**

- Only real taker trades that happen after the quote was placed can fill it.
- **Touch** (optimistic): a trade at our price fills us, as if we were first in
  the queue.
- **Through** (conservative): only a trade past our price fills us.
- **Queue** (recorded books; see [below](#the-queue-rule)): a trade at our price
  fills us only after the size resting ahead of us is served.
- A trade in the NO token is treated as the opposite trade in YES: buying NO at
  p is selling YES at 1 − p.

**On Kalshi** (`load_event(exchange="kalshi")`, `f1 demo-history --venue kalshi`), the same rules apply to
Kalshi's recorded tape. Each market ticker is one market, and its trades are already in YES terms. Each fill
pays Kalshi's maker fee, ceil(0.0175 × C × P × (1 − P)) cents (`Params.maker_fee`, 0 on Polymarket).
See [Kalshi history](kalshi-history.md).

**What it reports:**

| Measure | Meaning |
|---|---|
| `spread_pnl` | Captured vs the market price at the fill |
| `markout_60m` | The market's move over the next hour. Negative means adverse selection: the takers knew something. |
| `model_edge` | What our fair value said the fills were worth |
| `pnl` | Held to the official result |
| `worst_case` | Worst loss of the open positions |

Results are broken down by pricing stage and market type. The report also shows
why markets weren't quoted and a sweep of half-spread × fill rule × disagreement
filter.

**Polymarket's takers in the app.** On the diagnostic page (`/lab/diagnostics/{id}`), *Record the replay's
fills* writes each fill as a bet by the `polymarket-takers` system account (no
login) on the demo `maker`'s in-app market. That account stands in for the
Polymarket traders whose real trades filled the replayed maker, so its P&L is
exactly the maker's P&L reversed. It is **not** the demo `taker` account, which
paper trades its own strategy (see [Web app](webapp.md#accounts-demo-users-vs-polymarkets-takers)).

## Baku, 2026-09-26 (first test event)

Three as-of runs:

| Run | Cutoff (UTC) | Knows |
|---|---|---|
| 11 | Sep 24 00:00 | Nothing from the weekend (grid simulated) |
| 12 | Sep 25 13:30 | Qualifying (30 min after it ended) |
| 9 | Sep 25 23:59 | Same as 12 ("priced yesterday") |

**Tape:** 7,664 trades and minute prices for 8 events.

| Market type | Traded Sep 22 – race start |
|---|---|
| Win | $68k |
| Podium | $13k |
| Head-to-head | $482 |
| Top-scoring constructor | $0 |

The top-constructor book was empty. Its hourly prices summed to 2.7 across 11
teams, so the diagnostic page excludes groups whose prices don't sum to roughly
their number of winners.

**Model vs Polymarket at the run 9 cutoff (Brier score, lower is better):**

| Market | Model | Polymarket |
|---|---|---|
| Win | 0.027 | **0.007** |
| Podium | **0.086** | 0.093 |
| Head-to-head | 0.233 | **0.212** |

**Maker replay at ±2¢, conservative fills:**

- 82 fills, $371 notional;
- spread captured +$12, 60-minute mark-out −$29;
- **P&L −$303** held to the result.

Most of the loss came from two short positions that hit the 250-share limit:

- Russell to win, sold at 23¢ against a fair of 14¢ before qualifying. He took
  pole and won: −$196.
- Verstappen podium, sold at 36¢: −$161.

The model's own view of the fills was +$176, which shows the losses weren't bad
luck on good trades: the model was wrong on those two positions.

**What to take from it:**

- The takers who hit us were informed: the mark-outs are negative.
- Pre-qualifying inventory is the biggest risk. The maker holds positions into
  qualifying, and qualifying moves these markets the most.
- The sweep has disagreement filter **off** doing better (−$41 vs −$303). That's
  one race, so it isn't a reason to change the default. Tuning on Baku would be
  overfitting.

## Season sweep

`racinglines f1 sweep --save` (or the Lab's **Edge Finder sweep** job, which adds its combos to the Edge Finder) trades every raced
weekend of a season through its sessions:

1. **Stages** come from the real session schedule (FastF1):
    - 1 h before FP1 (before any running);
    - 30 min after each session ends: FP1–FP3, or sprint qualifying and the sprint;
    - 30 min after qualifying, the last stage. The race itself is never traded.
2. **Pricing:** each stage is priced as of that moment (`price_race`, sessions
   before the cutoff only) and stored as a diagnostic run tagged `sweep_stage`.
   Stored stages are reused.
3. **Trading:** each stage trades against Polymarket's price at that moment
   (5-minute history) in win, podium, pole, head-to-head and top-constructor
   markets. A market is tradeable only if it had at least $50 traded in the
   previous 24 h, isn't priced at an extreme, and its group of prices is
   coherent. Pole markets close at qualifying.
4. **Strategies** (`racinglines/markets/strategies/taker_weekend.py`), run side by side:
    - **update & rebuy:** rebalance at every stage to a target of $250 × edge
      (max $50 per market) when the edge is at least 5 points, closing when the
      edge disappears;
    - **enter & hold:** the first tradeable stage only;
    - **after quali only:** the last stage only.
   
   All pay 1¢ per share per trade. The **maker replay** also runs through the
   same stages.
5. **Settlement:** the result is read only after trading, to settle and score.

### 2026, rounds 1–15

<!-- readme: f1-trading -->

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

<!-- /readme -->

**What changed with the practice prior.** Run 96 used the same stages without
the prior:

| Strategy | Run 96 (no practice prior) | Run 191 (practice prior) |
|---|---|---|
| Update & rebuy | −$1,313 | **−$479** |
| Enter & hold | −$2 | **+$214** |
| After quali only | −$512 | **−$15** |
| Maker replay | +$852 | +$751 |

The biggest swing is after FP2 (−$11 → +$1,130): our fair value now moves with
practice, so we're no longer taking the other side of what practice revealed.

**The update strategy's P&L by stage:**

| Stage | Trades | P&L |
|---|---|---|
| Pre-weekend | 148 | −$206 |
| After FP1 | 135 | +$320 |
| After SQ | 41 | +$135 |
| After Sprint | 50 | +$495 |
| After FP2 | 95 | +$1,130 |
| After FP3 | 133 | −$1,187 |
| After Quali | 116 | −$1,166 |

**By market:**

| Market | Trades | P&L |
|---|---|---|
| Teammate head-to-head | 31 | **+$392** |
| Podium | 152 | +$84 |
| Top-scoring constructor | 36 | −$36 |
| Win | 333 | −$355 |
| Pole | 166 | −$564 |

Head-to-heads, which the shared car helps most, are the best market. Win and
pole are the worst: they are the markets that depend most on the front of the
grid, which the model underweights.

**Per weekend:**

- **Maker:** most of the total comes from Monza (+$447), Austria (+$307) and
  Silverstone (+$279). Zandvoort (−$171) and Baku (−$140) were the worst.
- **Update strategy:** best was Silverstone (+$846), worst Spa (−$435).

It's noisy: 15 weekends is a small sample.

**Since then:**

- the front-of-grid weighting is fixed (`gridq`, F1-2);
- a stage-aware taker is in the sweep (F1-4); confirming it out of sample is still
  open ([Roadmap](todo.md#market-making)).

Pricing is cached, so re-running with new trading settings takes minutes.

### Strategy options (F1 roadmap F1-4)

The sweep also replays these, side by side, on every weekend. The settings were
fixed before looking at results (no tuning on these 15 weekends):

| Strategy | Rule |
|---|---|
| **Stage-aware taker** (`early`) | Like update & rebuy, but no new trades after FP3 or qualifying: positions are held through them |
| **Maker, flatten before quali** | Close all inventory at the market (mid ± 1¢) at the pull before qualifying |
| **Maker, info-timed skew** | Skew quotes against inventory harder as a session approaches: ×(1 + 2·e^(−t/2h)) |
| **Maker, widen on bad markouts** | 1.5× half-spread on market kinds whose maker fills lost on 60-min markouts in *earlier* weekends |
| **Maker, all three** | The three maker options together |

Baseline model, 2026 rounds 1–15 (sweep run 574):

| Strategy | P&L | Bought / filled | Weekends up |
|---|---|---|---|
| **Stage-aware taker** | **+$1,874** | $7,859 | 7 / 15 |
| Maker (default) | +$751 | $8,969 | 7 / 15 |
| Maker, info-timed skew | +$650 | $9,024 | 7 / 15 |
| Maker, widen on bad markouts | +$638 | $8,294 | 8 / 15 |
| Enter before running, hold | +$214 | $6,954 | 7 / 15 |
| Enter after qualifying only | −$15 | $3,254 | 6 / 15 |
| Maker, flatten before quali | −$58 | $12,010 | 6 / 15 |
| Maker, all three | −$86 | $10,921 | 7 / 15 |
| Update & rebuy | −$479 | $11,100 | 5 / 15 |

- **The stage-aware taker is in-sample.** Its rule came from this sweep's
  stage split, so +$1,874 is the upper end of what to expect. It has to be
  confirmed on weekends after Baku before it's trusted.
- **Out of sample, 2025: not confirmed.** The same sweep (baseline model, default settings) on all 23
  2025 weekends with markets, measured 2026-09-28 on the bucket's database:

  | Strategy | 2026 (in-sample) | 2025 (out of sample) | 2025 bought / filled | 2025 weekends up |
  |---|---|---|---|---|
  | **Stage-aware taker** | +$1,874 | **−$316** | $7,914 | 9 / 23 |
  | Update & rebuy | −$479 | +$220 | $11,842 | 9 / 23 |
  | Maker (default) | +$751 | −$176 | $11,232 | 10 / 23 |
  | Enter before running, hold | +$214 | −$754 | $7,105 | 7 / 23 |
  | Enter after qualifying only | −$15 | −$1,303 | $3,907 | 7 / 23 |

  The stage split flips: in 2025 the update taker's trades after qualifying made +$669, its best
  stage, and that is the stage the rule skips. No profile uses the stage-aware taker, and the Edge
  Finder still flags it in-sample. The live weekends are the next check.
- **None of the maker options beats the default maker.** Flattening before
  qualifying pays the spread twice and gives up positions that were, on
  average, on the right side. The skew and the widening each give back about
  $100.
- **Model vs Polymarket, every market kind** (Brier, lower is better): the model
  is sharper on head-to-heads (after FP3 0.153 vs 0.344; after qualifying 0.181
  vs 0.213). On top-scoring constructor it's sharper after FP3 and qualifying,
  and on podium after FP1 and FP2. Polymarket is sharper on pole and after the
  sprint.

## Model × strategy matrix

`racinglines f1 matrix` puts every model variant (see
[Model variants](f1.md#model-variants-f1-roadmap-f1-2-f1-3)) against every
trading strategy on the same 2026 weekends. Each variant is re-priced at every
stage, then traded by each strategy on Polymarket's recorded prices.

<!-- readme: f1-matrix -->

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
  [Checkpoint entries](#checkpoint-entries)). Its 2026 P&L is on the season
  that suggested it; its accuracy gain holds on 2022 too (see
  [Formula 1](f1.md#model-variants-f1-roadmap-f1-2-f1-3)).
- **`gbm` is worse on both:** less accurate after practice and qualifying, and
  below baseline on every strategy but two maker options.
- **The championship markets lose under every model** (−$208 to −$262): the
  market prices each race's result before we trade an hour later.

‡ The stage-aware taker's rule came from this sweep, so it is in-sample. †
`gridq` prices the season the same as baseline (and `gridq+pretrain` as
`pretrain`): future races have no grid yet. Fifteen weekends are few; the P&L
differences between variants are not tested for significance, and picking the
best of ~60 cells flatters it.

<!-- /readme -->

Runs: baseline backtest 193 / sweep 574 / season 515; `gridq` 347 / 655 / 515;
`pretrain` 195 / 653 / 532; `gridq+pretrain` 423 / 664 / 532; `tail` 196 / 644
/ 549; `gbm` 665 / 741 / 663; `reset` 837 / 867 / 851; `gridq+pretrain+reset` 854 / 943 / 866. The plain `grid` variant (the term at every stage, 194 / 647 / 566) gets
the same after-quali gains but costs accuracy before quali, so `gridq` replaces
it.

## Cloud settings search (params-4h)

A 4-hour [cloud search](cloud-sweep.md#the-params-4h-search) (2026-09-27) of **settings only**, on the 9
existing model variants × the 9 existing strategies: no new variants, strategies or model code. Each
2026 finding was checked on 2025 (23 weekends, "live from the first race") before it counted. Per-event
race markets only; championship markets were out of scope. Report and data:
`data/runs/search/params-4h/`.

- **291 season sweeps** (0 failures), 2,619 strategy backtests, 1,161 distinct 2026 strategy × settings
  combos.
- **Held fixed** as realism guards, never tuned: the 1¢-per-share cost, the conservative *through* fill
  rule, and the $50 floor on 24 h volume.
- **Noise floor:** re-running the same combo at 8k and 16k simulations moves a season's P&L by about
  ±$150 for takers and ±$350 for makers. Smaller differences aren't evidence.

**What held in both seasons (robust):**

- **`min_edge` 0.05 → 0.10:** act only on edges of 10 points or more.
- **Skip the pre-weekend stage:** takers trade after FP1 at the earliest.

**The two recommended profiles** (now [strategy profiles](paper-trading.md#strategy-profiles)):

| Profile | Setup | 2026 (15 weekends) | 2025 (23 weekends) |
|---|---|---|---|
| **A · core taker** | Update taker, `gridq+pretrain+reset`, `min_edge` 0.10, no pre-weekend stage | +$1,232 (Sharpe 1.53, max DD $249) | +$1,237 (1.35, $306) |
| **C · maker sleeve** | Conservative maker, `gbm`, `max_disagree` 0.05, `size` 25 | +$653 (1.78, $279) | +$835 (1.63, $176) |
| **A + C** | Both | +$1,885 | +$2,072 |

- **A and C are nearly uncorrelated:** weekly P&L correlation −0.03 (2026) and 0.18 (2025).
- **Noise replicates** (7 simulation counts, 3k to 20k): A +$1,270 ± 67 (2026) and +$1,020 ± 149 (2025);
  C +$717 ± 72 and +$881 ± 63. Neither goes negative in any replicate.
- **`gbm` is the only model whose makers make money in both seasons.** C's 2026 P&L matches the default
  maker's rather than beating it; the case for it is 2025, where the default maker loses.
- **Head-to-head at 5 points.** Profile A adds `min_edge_h2h` 0.05 (for A, head-to-head was the one
  market kind that earned in both seasons). With it, A makes +$1,242.9 in 2026 and +$1,363.2 in 2025 (computed
  locally, not by the search).

**Rejected:**

| Change | Why |
|---|---|
| Loosen the $50 volume filter | Looks like +$3k to +$7k, but it's a thin-market artifact: fills at stale prices |
| Double the stakes | Leverage, not edge: it doubles the 2025 loss too |
| Stop taking before FP3 | Works only in 2026 |
| Hold strategies | Lose in 2025 |

Live paper trading of A and C, and how it's checked against these numbers, is in
[Paper trading](paper-trading.md).

## Season strategy (championship markets)

`racinglines f1 season-strategy --save` replays a default strategy for
Polymarket's drivers' and constructors' championship markets through 2026. Its
latest run feeds the Markets board and the race pages.

- **Decisions:** pre-season, then 1 h after every race. At each, an as-of
  season forecast (only sessions that had ended) gives the fair values.
- **Trading:**
    - rebalance to $500 × edge when the edge is at least 3 points, up to $150
      per market, with $1,500 of capital in total;
    - execution at Polymarket's price one hour after the decision, plus half
      the recorded spread and 0.5¢ slippage;
    - positions are exited even when the price has left the tradeable band.
- **Markets:** only those with at least $100k traded.
- **Demo liberty:** the pre-season forecast simulates the published 2026 entry
  list instead of the 2025 field.

**Run 515** (baseline model, through Baku, 16 decisions, 98 trades):

| | P&L | Bought | Max drawdown |
|---|---|---|---|
| **Update after every race** | **−$208** | $2,172 | −$722 |
| Enter pre-season and hold | −$532 | $915 | −$532 |

The model variants land between −$262 (`gbm`) and −$208 (baseline): see the
[matrix](#model-strategy-matrix).

Updating after each race loses less than holding the pre-season view, but it
still loses: championship prices move on the same information our forecast
uses, and the market has priced it by the time we trade an hour later.

### The championship sleeve

The same strategy runs live as a paper sleeve, one per exchange, off unless
invoked:

```
racinglines f1 season-strategy --paper --venue polymarket --after-round 16
racinglines f1 season-strategy --paper --venue kalshi --after-round 16
```

Each replays the strategy from pre-season through the decision after that
round (the last raced round by default) on the exchange's recorded prices and
stores the state after that rebalance as the demo maker's paper positions:
`paper_positions.venue = 'season:polymarket'` or `'season:kalshi'`, event
`2026-season`, no candidate. Every run replaces the previous store on that
venue, so the rows are always the latest rebalance; `--save` also keeps the
rebalance as a run of kind `season_sleeve` (this decision's trades, the
positions, P&L to date). The two venues differ only in their markets and costs:
Kalshi's `KXF1-26-*` / `KXF1CONSTRUCTORS-26-*` markets are one per ticker
(their `condition_id` is the event ticker shared by every driver) and cost the
taker fee at the price, 7% × p × (1 − p) per contract, plus 0.5¢ slippage,
instead of half the spread.

The sleeve stays out of A, C and K's records: their track records
(`pipelines/story.py`), the signal engine's rebuilds and the Positions page
each select their own venues and weekends (a Positions row needs a signal on
its market), so nothing of theirs changes when the sleeve is stored. The MCP
`positions` tool lists it under its own venue. After round 15 (Baku) the
Polymarket sleeve held Antonelli and Mercedes at −$193 to date, the Kalshi
sleeve the same two at −$18: the [validation plan](paper-trading.md#validation-plan)
expects little of it.

### Checkpoint entries

`racinglines f1 season-checkpoints` asks a narrower question than the strategy
above: **if a desk takes a championship position at a fixed point in the season
and holds it, does the market come to our number?** It separates the model's
view from how fast the market reacts to each race.

- **Entries,** fixed before looking at results: pre-season, after 3 grands prix,
  after 6. Each is a separate $500 book (the default sizing) that holds.
- **Windows:** the next 3 GPs after each entry (the same length for all three,
  so they compare), and to date.
- **Scores:**
    - P&L at liquidation value (price − cost), with eliminated markets settled;
    - **drift:** how far the market moved toward our fair value, in points,
      over the markets where we saw ≥ 3 points of edge;
    - **slope:** the share of our edge the market later closed, over every
      tradeable market. 1 = it went all the way to our number, 0 = our edge said
      nothing about the move, negative = it moved away.

<!-- readme: f1-checkpoints -->

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
  a data gap (see [Roadmap](todo.md)), not a modelling one.

Slopes have standard errors of 0.15–0.8 (a title's markets are not independent),
so read them as direction, not size.

<!-- /readme -->

## The queue rule

`fill="queue"` (sweep `--fill queue`, off by default) replaces the touch/through
bounds with a queue position read from the recorded books (`markets record`, the
outcome-0 token's book, top 10 levels once a minute):

- A new quote joins the **back of its level**, behind the size the latest snapshot
  shows at that price. When it improves on the best price the level is empty, so it
  is first in line (as *touch*).
- A trade **at** our price serves the queue ahead first; we get what's left. A trade
  **past** our price swept the level: it fills us (as *through*) and nobody is left
  ahead.
- A quote that stays at the same price across requotes **keeps its place**. When a
  later snapshot shows less at the level than is ahead of us, the queue shrinks to it
  (cancellations); orders that join later queue behind us.
- **No snapshot** from the last `book_max_age_min` (10) minutes: that quote fills as
  *through*. The result's `book_coverage` is the share of quoted sides that had a book.

On synthetic books it lands between the two bounds: at *touch* with empty levels,
close to *through* with deep ones (`tests/test_replay.py`). It hasn't been run on
recorded books yet: that needs several weekends of `markets record` data
([Roadmap](todo.md#market-making)).

## Limits of the Baku test

- No order-book depth, so queue position and competing makers are unknown. The
  touch and through rules bound the fill rate from each side.
- Our quotes don't change what takers would have done.
- One event. The replay needs many recorded events before any setting is tuned.

**Since then:**

- the replay runs across every race with a tape (2025 and 2026, the `params-4h`
  cloud search);
- flattening before qualifying was tried and doesn't beat the default maker (F1-4);
- the queue model is built and tested on synthetic books ([the queue rule](#the-queue-rule));
  still open: running it on recorded books, once enough weekends are recorded
  ([Roadmap](todo.md#market-making)).

## Tests

Part of the [regression suite](testing.md):

- **`tests/test_rebalance.py`** and **`tests/test_season_strategy.py`** (no
  database) check the weekend taker and season strategies on synthetic stages:
  sizing, edge thresholds, capital caps, exits and P&L accounting.

- **`tests/test_replay.py`** (no database) checks the replay's rules:
    - no lookahead;
    - quotes never cross, and YES bid + NO bid < 1;
    - skew and skip reasons;
    - fills only after the quote, touch vs through, taker-side mapping;
    - the queue rule: queue ahead served first, sweeps, keeping place,
      cancellations, the stale-book fallback, and touch ≥ queue ≥ through on
      synthetic books;
    - size, inventory and capital limits;
    - pulling before sessions;
    - P&L accounting;
    - determinism.
- **`tests/test_baku.py`** (skipped without the database and Baku data) checks:
    - each run's audit: sessions used only before the cutoff;
    - `LeakageError` on injected future data;
    - the pre-qualifying grid is simulated;
    - the tape is well formed;
    - stages stop at the race;
    - fills are inside their stage and priced with that stage's run;
    - limits hold and P&L adds up;
    - hiding every outcome changes no quote or fill;
    - page access by role.

Baku is a temporary fixture. Events recorded with `markets record` should replace it.
