# Market making

How we test whether trading a market is worth it before risking money: on one
event in depth, then on a whole season.

| | What | Result |
|---|---|---|
| [Baku diagnostic](#baku-2026-09-26-first-test-event) | One race priced as of every moment, with a maker replay on the minute-level tape | Maker −$303 at default settings |
| [Season sweep](#season-sweep) | All 15 raced 2026 weekends, re-priced after every session | **Maker +$751**; taker strategies −$479 to +$214 |
| [Season strategy](#season-strategy-championship-markets) | Championship markets, rebalanced after every race | −$241 (hold: −$532) |

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
- A trade in the NO token is treated as the opposite trade in YES: buying NO at
  p is selling YES at 1 − p.

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

**Sample taker.** On the diagnostic page, *Record the replay's fills* writes each
fill as a bet by the sample `taker` account on the sample `maker`'s in-app
market. The `taker` account stands in for Polymarket's takers, so taker P&L is
exactly the maker's P&L reversed.

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

`racinglines f1 sweep --save` (or the Lab's **Season sweep** job) trades every raced
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

**Next:**

- fix the front-of-grid weighting;
- try a stage-aware strategy that stops re-trading after FP3 and qualifying,
  checked on the next events, not tuned on these.

Pricing is cached, so re-running with new trading settings takes minutes.

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

**Run 113** (through Baku, 16 decisions, 102 trades):

| | P&L | Bought | Max drawdown |
|---|---|---|---|
| **Update after every race** | **−$241** | $2,276 | −$758 |
| Enter pre-season and hold | −$532 | $961 | −$532 |

Updating after each race loses less than holding the pre-season view, but it
still loses: championship prices move on the same information our forecast
uses, and the market has priced it by the time we trade an hour later.

## Limits of the Baku test

- No order-book depth, so queue position and competing makers are unknown. The
  touch and through rules bound the fill rate from each side.
- Our quotes don't change what takers would have done.
- One event. The replay needs many recorded events before any setting is tuned.

**Next:**

- replay with recorded book snapshots and a queue model;
- flatten or hedge inventory before qualifying;
- run the replay across every backtest race once their Polymarket tapes are
  fetched.

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
