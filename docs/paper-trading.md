# Paper trading

How a strategy found in the backtests is run live, on paper: each user gets a strategy profile, a
signal engine replays that profile on the current race weekend every 5 minutes, and the results show
on the Strategy and Positions pages. Nothing here places an order.

| Piece | Code | What it does |
|---|---|---|
| [Strategy profiles](#strategy-profiles) | `racinglines/pipelines/profiles.py` | A Lab candidate (model × strategy × settings) assigned to a user |
| [Signal engine](#the-signal-engine) | `racinglines/pipelines/signals.py` | The profile's trades or quotes on the current weekend, stage by stage |
| [Heat](#heat) and [following](#following) | `signals.py` | What a taker sees instead of fair values; which calls it takes |
| [Alerts](#alerts) | `racinglines/markets/alerts.py` | New Polymarket markets, new signals |
| [Demo accounts](#the-demo-accounts) | `pipelines/demo_history.py`, `pipelines/story.py` | The maker's and taker's track record, replayed from backtests |

## Strategy profiles

The two profiles come from the params-4h cloud search (see
[Market making](market-making.md#cloud-settings-search-params-4h)):

| Profile | Strategy | Model | Settings (the rest default) |
|---|---|---|---|
| **A · core taker (update)** | Update taker | `gridq+pretrain+reset` | `min_edge` 0.10, `min_edge_h2h` 0.05, no pre-weekend stage (after FP1, FP2, FP3, SQ, Sprint and Quali only) |
| **C · maker sleeve (gbm)** | Conservative maker | `gbm` | `max_disagree` 0.05, `size` 25 |

- **Stored as Lab candidates** (`model_runs.kind = 'candidate'`), so they can be loaded into the Edge
  Finder sweep form like any other candidate.
- **Assigned per user** in `users.prefs["strategy_profile"]`, with the full settings, so deleting the
  candidate doesn't break the assignment. An admin sets or clears it on `/admin/users/{id}`
  (**Strategy profile**).

```
racinglines f1 profiles                  # list; create A and C as Lab candidates if missing
racinglines f1 profiles --assign-demo    # demo taker -> A, demo maker -> C
```

### The head-to-head threshold

Profile A trades head-to-head markets at a lower edge (5 points) than the rest (10 points). That's the
`min_edge_h2h` setting (`racinglines/pipelines/sweep_settings.py`); `taker_weekend.params_for` swaps it
in for `race_h2h` markets.

It is optional: its default is `None` ("not set"). Optional settings are left out of `settings_key` and
`model_key` while unset, so every saved key, and every earlier sweep, is unchanged.

With `min_edge_h2h` 0.05, A makes +$1,242.9 in 2026 and +$1,363.2 in 2025 (the search's A, without
it: +$1,232 and +$1,237).

## The signal engine

`racinglines/pipelines/signals.py` computes what each profile would do on the current race weekend,
using the backtest's own code. Recommendations and paper fills only.

**One run, for each distinct profile assigned to an active user:**

1. **Data** (live only): if a finished session's data is missing, FastF1 fetch and ingest for that
   round. Then Polymarket 5-minute prices and the trade tape for the event's markets, up to now
   (`fetch_trades(since=...)` re-reads only the last 6 hours once prices are stored).
2. **Pricing:** each stage whose cutoff has passed **and** whose session data is ingested, priced as of
   that cutoff with the profile's model settings. It stops at the first stage still waiting for data.
   Stages are cached like the sweep's (`model_key` + `data_key`), so a stage is priced once.
3. **Markets:** `weekend_sweep.weekend_markets`, with the same filters as the sweep. Live, each stage
   reads the market when the stage was priced (`price_times`; its trades couldn't have been made
   earlier). A replay reads it at the cutoff, like the sweep.
4. **Strategy:**
    - taker profiles: `taker_weekend.run_market` over the stages so far. Every trade is a signal; the
      replay's position is the paper position;
    - maker profiles: `maker_replay.replay` up to now. Each paper fill is a signal, and so is a market
      starting or stopping quoting in a stage (not every requote).
5. **Store:** `strategy_signals` and `paper_positions` (see [Database](database.md)). Idempotent per
   profile, market, stage and side: existing signals are kept, the user's paper positions for the event
   are replaced.
6. **Expire:** a taker's unacted signals from earlier stages are marked `expired`.
7. **Alert:** one batched message with the new signals (see [Alerts](#alerts)).

**When it runs:** from 4 days before the race to 24 hours after it. After the race, the next runs fetch
its result, and the paper positions settle. Outside that window a run only notes when signals start.

```
racinglines f1 signals                                   # every user with a profile, the weekend in progress
racinglines f1 signals --profile A --user taker          # this profile, these users
racinglines f1 signals --event 2026-15 --asof 2026-09-27T12:00 --no-fetch   # replay (prints only)
racinglines f1 signals --no-alert                        # store, don't notify
```

| Option | Meaning |
|---|---|
| `--profile` | A candidate id, name, or `A` / `C`, instead of each user's own |
| `--user` | Only these usernames |
| `--event` | `next` (default), a round number, or `YEAR-ROUND` |
| `--asof` | **Replay** at this UTC time: markets read at each stage's cutoff, exactly like the sweep; prints a table with our fair values and stores nothing |
| `--no-fetch` | Don't refresh FastF1 or Polymarket data first |
| `--no-alert` | Don't send alerts |

**The launchd agent** `scripts/bet.racinglines.signals.plist` runs `racinglines f1 signals` every 5
minutes (log: `data/runs/logs/signals.log`):

```
cp scripts/bet.racinglines.signals.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/bet.racinglines.signals.plist
```

### Between weekends

When a taker profile has no stage to trade, the run calls `price_upcoming`: each of the next 3 races
with Polymarket race markets listed is priced as of now with the profile's model (stored as a
diagnostic run with `sweep_stage = "now"`). It's done once per race and data set: the data only
changes when a session runs.

### The current call on any market

The Markets page (takers) and the Positions page's **Coming up** show the profile's call on every listed
market, not only this weekend's signals:

- **`call`** (takers): the backtest taker's rule on one market at the current price (sizing, the
  head-to-head threshold, the price band, the volume filter). Returns side, shares, the most to pay and
  the heat, or why there's no call (not priced yet, outside the price band, too thin, no edge). Never the
  fair value or edge.
- **`maker_call`** (makers): where the maker would quote, by the replay's rules (spread around fair,
  never crossing the market, the price band, the volume floor, the disagreement filter), with no
  inventory yet.

### Parity with the sweep

`scripts/signals_parity.py` replays a taker profile on a past weekend with the signal engine and runs
`racinglines f1 sweep` on the same round with the same settings, then compares market, stage, side,
shares and price of every trade (exit 1 on a difference).

```
.venv/bin/python scripts/signals_parity.py                     # profile A, 2026 round 15 (Azerbaijan)
.venv/bin/python scripts/signals_parity.py --round 12 --reprice
```

| Check | Result |
|---|---|
| Profile A, 2026 round 15 | Replay = sweep: 11 of 11 trades identical |
| Same, with the sweep repricing every stage itself (`--reprice`) | Identical |
| Maker C, same round | 15 fills, P&L −$22.29, identical to the sweep's maker |

## Heat

A taker never sees our fair value or edge. Each entry gets a **heat** instead: its modelled EV,
shares × (our probability of the side − limit price), graded.

| Heat | Modelled EV of the entry |
|---|---|
| warm | under $12 |
| hot | $12 to $30 |
| very hot | $30 or more |

The cut points are the median and the top quartile of profile A's 472 backtest entries (2025 and 2026;
modelled EV quartiles $4.8 / $12.0 / $29.8).

**Heat grades conviction; it doesn't promise returns.** Realised ROI by EV quartile, lowest to highest:

| Season | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| 2026 | +10% | +10% | +40% | +70% |
| 2025 | +10% | +20% | −20% | 0% |

Realised P&L was about a quarter of the modelled EV.

## Following

A taker needn't take every call. A profile's `follow_rate` (set in code only, e.g. the demo taker's 0.33
in `profiles.DEMO_FOLLOW`; not in the UI) decides which markets the user follows:

- **Once per market,** at its first entry, with probability
  `follow_rate × HEAT_WEIGHT[heat] / HEAT_MIX_MEAN`. The weights are 0.6 / 1.0 / 1.4 (warm / hot / very
  hot), and 0.9 is their mean over A's backtest entries, so hotter entries are followed more often and the
  overall rate stays about `follow_rate`.
- **Deterministic** per (user, market).
- **A followed market is followed through** every later resize and exit. The others are marked
  **passed**. Paper positions hold followed markets only.

## Alerts

`racinglines/markets/alerts.py` sends two kinds of alert through the same channels.

**New markets.** Every Polymarket sync stamps tokens it sees for the first time with
`market_links.first_seen_at`, groups them by event and announces them, upcoming races first. In the web
app they carry a **new** badge for 48 hours on the Markets board's race cards and the Polymarket page.

- `racinglines markets record` re-syncs Polymarket every 30 minutes and alerts on what's new
  (`--no-alerts` turns it off).
- `racinglines f1 pm-sync --alert` is a one-off sync that alerts too.

**Signals.** One batched message per signal run and profile: each new signal as a line (stage, action,
side, shares, limit price, and the heat, never the fair value).

| Channel | When |
|---|---|
| macOS notification | Always, on a Mac (with a sound for an upcoming race or a new entry) |
| Phone push via [ntfy.sh](https://ntfy.sh) | `RACINGLINES_NTFY_TOPIC` is set. It sends titles to ntfy's public server, so pick an unguessable topic. |
| Webhook (JSON POST; Slack and Discord read it) | `ALERT_WEBHOOK_URL` is set |
| Log | New markets: `data/runs/alerts/new_markets.jsonl` |

A failing channel is skipped: an alert never stops the recorder or a signal run.

## The demo accounts

The demo `maker` and `taker` (the **Try as maker** / **Try as taker** buttons; see
[Web app](webapp.md#accounts-demo-users-vs-polymarkets-takers)) each have a paper bankroll from
2025-01-01 (`profiles.DEMO_BANKROLL`): $10,000 for the maker, $1,000 for the taker.

Sizing is fixed today: the bankroll is recorded, not used. The sweep can test two sizing rules on
the backtest, both unset by default: `--bankroll` (stakes scale with the balance) and `--max-deployed`
(a cap on capital deployed per weekend); see [CLI](cli.md). On 2026 (in-sample, one season; measured
2026-09-28), a $1,000 bankroll took the stage-aware taker from +$1,874 to +$1,338, and a $200 cap to
+$265. Neither is a decision: sizing waits for 4–6 live weekends.

Their weekends before live paper trading are **backtest replays** (`racinglines/pipelines/demo_history.py`):
real Polymarket prices and trade tapes, our as-of pricing, and the backtest's strategy code (the signal
engine's replay mode, the same path as the sweep). Every row is flagged `detail.backfill` and labelled
"backtest replay" in the app.

```
racinglines f1 demo-history                  # backfill (idempotent)
racinglines f1 demo-history --reset          # delete the backfill, then rebuild it
racinglines f1 demo-history --user taker     # one account only
racinglines f1 demo-history --venue kalshi   # the maker's record on Kalshi's tape, stored apart (off by default)
```

The Kalshi record uses the same profiles and the same maker replay, filled by Kalshi's real taker trades
with Kalshi's maker fee. See [Kalshi history](kalshi-history.md), which also covers how Kalshi's
historical feed differs from Polymarket's.

### The maker's history

| Phase | Setup | Weekends run | P&L |
|---|---|---|---|
| M1 | Conservative maker on the baseline (the defaults) | 2025 R1–8 (7 weekends) | +$169 |
| M2 | Grid-aware maker (`gridq+pretrain`), 10-pt disagreement filter | 2025 R9–16 (8) | +$215 |
| M3 | `gbm` maker, 7-pt filter | 2025 R17–24 (8) | −$99 |
| C | Profile C | 2026 (15) | +$653.03 |

C's +$653.03 is the same figure as the cloud report's C in 2026.

**Each switch follows a fixed rule** (`racinglines/pipelines/story.py`) on the Edge Finder's
walk-forward evidence: each setup's P&L over only the weekends raced so far.

- **Mid-season:** switch to the P&L leader if it beats the current setup by more than $100.
- **Before a season:** among the setups within $350 of the leader (the makers' noise floor), take the
  most consistent (mean / s.d. of weekend P&L × √weekends).

| Decision | Evidence | Chosen |
|---|---|---|
| Before the first race of 2025 | None yet | M1, the defaults |
| After 2025 round 8 | Leader: `gridq+pretrain` 10-pt maker, +$697 over 7 weekends | M2 |
| After 2025 round 16 | Leader: `gbm` 7-pt maker, +$1,134 over 15 weekends | M3 |
| Before the 2026 season | Leader: `gbm` 7-pt maker +$1,035; C +$835, within the noise floor, with the best consistency (1.59 vs the leader's 1.45) and the smallest drawdown (−$176 vs −$318) | C |

### Results

Backtest replays of real weekends, 2025 and 2026 through round 15:

| | Maker | Taker |
|---|---|---|
| Bankroll | $10,000 → **$10,937.87** (+9.4%) | $1,000 → **$1,897.73** (+89.8%) |
| Worst drawdown | −$317.54 | −$338.35 |
| Most capital in use in a weekend | $785 | $261 |
| Sharpe (mean / s.d. of weekend P&L × √24) | 0.92 | 0.95 |

**What the taker took,** following about a third of A's calls:

| Heat | Recommended | Taken |
|---|---|---|
| warm | 131 | 20 |
| hot | 79 | 24 |
| very hot | 101 | 56 |
| **Total** | **311** | **100** |

Taking every recommendation would have made +$2,606.

**Demo sessions are disposable:** every sign-in starts from the account's saved baseline, and anything
that would change data is refused. See [Web app](webapp.md#accounts-demo-users-vs-polymarkets-takers).

## Validation plan

Pre-registered on 2026-09-28, before any live F1 weekend on a real market, and judged by these rules
only. The reasoning is in [Strategy 2026](strategy-2026.md); the calendar is on the
[Roadmap](todo.md#race-weekends-to-31-december).

**What counts.** Only live weekends on a real market (tier T1): Polymarket or Kalshi. Private-book
weekends (T3, like round 16 if no venue lists it) score the pricing, never the strategy. Each venue is a
separate trial.

**The profiles are frozen until 31 Dec 2026:**

| Profile | Account | Venue | Settings |
|---|---|---|---|
| A · core taker | demo taker | Polymarket, Kalshi | As in [Strategy profiles](#strategy-profiles). Judged on A's own calls; the demo taker's followed third is shown too |
| C · maker sleeve | demo maker | Polymarket, Kalshi | As in [Strategy profiles](#strategy-profiles). On Kalshi it is a control: its Kalshi replay lost $119 in 2026 |
| K · Kalshi maker | demo maker | Kalshi | Chosen by a Kalshi sweep and frozen before round 18 (Roadmap U3) |
| Championship sleeve | demo maker | Both | `f1 season-strategy` after each race; kept out of A, C and K's records |

Any change to a profile makes a new profile with its own count.

**The rules:**

1. **Each weekend against its replay.** Re-run the backtest's replay of the same weekend on the recorded
   tape (the conservative "through" fill rule). Live fill counts and markouts should be within ±25% of
   the replay's, and live P&L inside the replay's noise band. A weekend outside is flagged and explained
   before the next one. `racinglines f1 reconcile --event 2026-NN --profile A|C --venue V` does this
   ([CLI](cli.md#racinglines-f1)): the account's stored signals and positions against `signals.compute`
   replayed as of a day after the race, both reduced to fills, 60-minute markouts read from the same tape,
   and P&L to resolution (a taker is judged on its own calls, the demo taker's followed third shown too).
   The noise band comes from seed replicates ([Backtest core](backtest-core.md#the-search-report), the
   noise floor): the weekend replayed with the profile's model at its own seed and two more (43, 44), the
   band being the range of their P&L, at least as wide as the search's configured season floors (150
   taker / 350 maker) scaled to one weekend of 24 (±31 / ±71). Markouts within $1 of the replay's never
   miss. A weekend whose rows are the backfilled replay is a self-check and must match to the cent.
2. **The pricing scorecard on every weekend,** traded or not: Brier and log loss of the fair values
   against the result and against the venue's mid at each stage.
3. **How many weekends.** From the 2025–26 replays, about 17 live weekends to show the maker's edge at
   about 2 standard errors (~$71 a weekend, s.d. ~$146), and about 40 for the taker (~$83, s.d. ~$262).
   The maker can be proved by the end of 2027; the taker is borderline.
4. **Sizing** is decided after 4–6 live T1 weekends (about 12 Nov), not before.
5. **No real orders in 2026 unless** 6 or more live weekends pass rule 1. Even then, one small V2 order
   first. `POLYMARKET_TRADING_ENABLED` and `KALSHI_TRADING_ENABLED` stay unset until the owner approves;
   order signing is on CLOB V2 but only dry-run tested (see [Web app](webapp.md#placing-orders)).

**Status (28 Sep 2026):** no live T1 weekend yet. Polymarket has listed no race since round 15
(28 Aug); Kalshi's live signals are Roadmap item U1. Round 16 is a private book unless Kalshi lists it
([F1 live test](f1-live-roadmap.md)).
