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

**The venue.** A profile trades Polymarket unless its settings say `venue = "kalshi"` (the sweep
settings schema's optional `venue`; unset by default and left out of every settings key, so existing
profiles, sweeps and their keys are untouched). A Kalshi profile reads the race's `exchange='kalshi'`
market links, one market per ticker (`token_id`; never grouped by `condition_id`, which on Kalshi is the
event ticker shared by every driver's market), its minute prices and trade tape per market from
`data/archive/markets/kalshi/` and the shared tables (so the 24 h volume filter is per market), and its
maker pays `KALSHI_MAKER_FEE` per fill. Its signals carry `detail.venue = 'kalshi'` and its positions
`venue = 'kalshi'`; a Polymarket run replaces only Polymarket's positions and a Kalshi run only Kalshi's.
The setting is the only switch: a live run can't be pointed at another exchange (`compute(venue=...)` is
for replays, as `demo-history --venue kalshi` uses it), and nothing here reads `KALSHI_TRADING_ENABLED`.
Paper only, on every venue. See [Kalshi history](kalshi-history.md#in-the-signal-engine).

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
shares and price of every trade (exit 1 on a difference). A maker profile is replayed as `demo-history`
replays it (a day after the race, settled) and compared with the sweep's maker on fills and settled P&L,
and with the demo maker's stored record for that weekend when there is one. `--venue kalshi` gives the
profile the `venue = kalshi` setting on both sides, so the same check runs on Kalshi's links and tape.

```
.venv/bin/python scripts/signals_parity.py                     # profile A, 2026 round 15 (Azerbaijan)
.venv/bin/python scripts/signals_parity.py --round 12 --reprice
.venv/bin/python scripts/signals_parity.py --venue kalshi      # A on Kalshi's links and tape
.venv/bin/python scripts/signals_parity.py --profile C --venue kalshi   # C's fills and P&L vs the sweep and demo-history
```

| Check | Result |
|---|---|
| Profile A, 2026 round 15 | Replay = sweep: 11 of 11 trades identical |
| Same, with the sweep repricing every stage itself (`--reprice`) | Identical |
| Maker C, same round | 15 fills, P&L −$22.29, identical to the sweep's maker |
| Profile A, same round, on Kalshi (`--venue kalshi`, 2026-09-29) | Replay = sweep: 23 of 23 trades identical (sweep update P&L −$49.84) |
| Maker C, same round, on Kalshi | 41 fills, settled P&L −$61.90: identical to the sweep's maker and to `demo-history --venue kalshi`'s stored Azerbaijan record |
| Profile A, Polymarket, before and after the venue setting existed | 11 of 11 trades identical both times (the default path is unchanged) |

### Cancelled and relocated races

A market kind says what pays when the race runs ([kinds](backtest-core.md)). `racinglines/markets/settlement_rules.py`
says what each venue pays when it doesn't, and applies it wherever paper positions settle: the private book
(`private_book.settle_from_results`), the weekend's markets the signal engine's positions are built from
(`weekend_sweep.weekend_markets`) and the maker replay (`maker_replay.load_event`). **Off by default:** set
`RACINGLINES_CANCELLED_RACE_RULES=1` (or pass `rules=True` to those calls). Without it nothing changes: a
cancelled race never settles (there is no classification) and a relocated race settles on its result.

A race's status is `cancelled` when `events.status = 'cancelled'` in the database, when the env
`RACINGLINES_RACE_STATUS` says so (`f1:2026-22=cancelled,f1:2026-23=cancelled`), or from the module's
`RACE_STATUS` table, which also records the one `relocated` race so far: **2026 round 16, the Bahrain GP run
at Sepang** ("Bahrain Grand Prix in Malaysia"). A relocated race's markets settle on the race that was run,
at every venue (its test: `tests/test_settlement_rules.py`).

What a YES share pays on a cancelled race, per venue (`settlement_rules.RULES`), from the venues' own market
rules (checked 2026-09-29):

| Venue | Named outcome (driver, constructor) | "Other" / "any other driver" | Binary (head-to-head) |
|---|---|---|---|
| Polymarket | **0** — rule and fact | **1** — rule and fact | **0.5** — rule |
| Kalshi | last fair price | last fair price | last fair price |
| Private book | void, stakes returned | void | void |

- **Polymarket, driver and constructor markets:** the market rules say the market resolves to "Other" if the
  race is cancelled or rescheduled past a deadline about a week after the scheduled date (the 2026 Australian
  GP: "after March 14, 2026"; Canada: "after May 31"; Monaco: "after June 14"). The archived April 2026 Bahrain
  markets (`data/archive/markets/polymarket/links/`, `f1-bahrain-grand-prix-*-2026-04-12`) show it: when the
  race didn't run on its date, all 174 recorded named markets resolved NO and the 9 "Other" markets ("Will any
  other driver win the 2026 F1 Bahrain Grand Prix?") resolved YES. The October race got new markets, which
  settle at Sepang.
- **Polymarket, head-to-heads:** the rules on every F1 head-to-head event (Japan, Monaco, Azerbaijan, Abu
  Dhabi 2025, ...) say "If a Grand Prix is permanently canceled, the market will resolve 50-50", a tie between
  the two drivers resolves 50-50 as well, and "If a Grand Prix is postponed, the market will remain open until
  the event has been completed". So the 0.5 payout is the rule, not a guess.
- **Kalshi:** the F1 race markets (winner, podium, pole, head-to-heads) all carry the same clause (read from search
  excerpts of Kalshi's market pages; the pages themselves are blocked from the cloud environment): a race
  postponed but started within 48 hours of its scheduled start settles on the official final result, and "if
  the race is cancelled or not started within 48 hours of its originally scheduled start, all markets will
  resolve to a fair price". Kalshi's rulebook (6.3(c)) makes that the last fair market price as Kalshi
  determines it, usually the last traded price, else a figure from its Outcome Review Committee. Kalshi does
  **not** resolve NO and does not void (refund at cost): every contract settles at that price. Here that is
  `settlement_rules.FAIR`, paid at the market's last recorded price (`apply(..., last_price=...)`: the last
  5-minute price in the weekend sweep and the maker replay). What stays approximate is only which price Kalshi
  picks. Kalshi's own market on whether a race happens (`KXF1OCCUR-26ADGP`, "take place in Abu Dhabi before
  December 7, 2026", about 38¢ on 2026-09-27) is unmodeled and not settled by this.
- **Void** refunds every share at its own price: a position's P&L is 0. A paper position that is voided, paid
  0.5 or paid Kalshi's last price is closed to cash at that payout (`paper_positions.outcome` stays null, shares
  0), which the track record reads as settled at that P&L; a Kalshi position whose market has no recorded price
  stays open. The private book is a YES/NO book, so a 0.5 payout or a price there is voided with a note saying
  so. Every settlement note names the venue's rule.

The `[live]` F1 engine (`live_f1.outcomes`) is not wired to this: round 16 is a relocated race and settles on its
classification as before.

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

### The taker's history

The demo taker follows the **same rule at the same decision points** (`story.decisions(conn, taker=True)`),
on its own pool fixed in advance: the taker re-sweep's round 1 (baseline, `gridq+pretrain`,
`gridq+pretrain+reset` and `gbm` × minimum edge 0.05 / 0.08 / 0.10 / 0.15, update and stage-aware takers),
with the takers' measured noise floor of $400. The evidence is the pool's 2025 season sweeps
(`sweeps/demo-taker-story.toml`). Figures are the sweeps' own (every recommendation taken); the account
follows about a third of them.

| Decision | Evidence | Chosen |
|---|---|---|
| Before the first race of 2025 | None yet | TW1, the defaults (update taker, baseline model, 5-pt edge) |
| After 2025 round 8 | Leader: `gridq+pretrain+reset` 10-pt update taker, +$327 over 8 weekends | TW2 |
| After 2025 round 16 | Same leader, +$1,216 | TW2 (kept) |
| Before the 2026 season | Same leader, +$1,196, the most consistent within $400 | TW2 (kept) |

TW2 is profile A's core without A's head-to-head threshold and with pre-weekend entry. The rule never picks
a blend, so the story has none; the blend is a Pro option (taker re-sweep report, `data/runs/search/taker-resweep/REPORT.md`, section 6).

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

### NASCAR and MotoGP (demo, in-sample; off by default)

`RACINGLINES_SPORT_PAPER=1` adds the result-only sports to the demo taker's portfolio
([`pipelines/sport_paper.py`](https://github.com/lalligagger/racinglines/blob/main/racinglines/pipelines/sport_paper.py)).
`racinglines nascar demo-history` (and `motogp demo-history`) replays every race of the seasons in the overnight settings
grid (`data/runs/replay-grid/<sport>/`, runs `<year>-e<edge>-v<volume>`) with the taker replay (`nascar replay`), and
stores each race's `update` trades as the account's backfilled signals and paper positions on the exchange
(`paper_positions.venue = 'kalshi'`, `candidate_id` empty, the sport's own event keys), each position's cash net of the
exchange's taker fee.

**How the strategy is chosen, and why it is only a demo.** Per market kind (NASCAR win, top 3/5/10/20, head-to-head;
MotoGP win), the grid setting (min edge, 24 h volume floor) whose worse season's net P&L on that kind is highest; a kind
whose best setting still lost money in its worse season is not traded. `--book blend` instead trades every kind at the
one setting with the best worse season across them all. The selection is made on the same seasons it is replayed on,
so the P&L is **in-sample**: it shows what the strategy would have done, not that it has an edge. The app labels every
such race and position "demo replay, in-sample". `--pick FOLDER` prints the selection (per kind, the blend, each
season's net) and writes nothing; a run also writes it to `demo-selection-<venue>.md` in the grid folder.
A season in which a kind had nothing to trade at any setting (MotoGP 2025: Kalshi listed no race markets) is left out of that kind's worse-season test rather than counted as a $0 season, which would veto every kind.

**Never buy_all.** The replay runs with the debug `buy_all` mode switched off whatever `RACINGLINES_BUY_ALL` says, only
the taker's `update` trades are stored, and the app's nav P&L, Positions and Signals never count a row whose strategy or
`detail.mode` is `buy_all`.

With the switch on, the nav P&L adds these rows to the Polymarket ones, Positions lists them (with the race names), and
Signals shows them in the track record on their race dates beside F1. With it off, nothing reads them and every page is
as before. Writes need `--backup FILE` (a dump under 24 hours old) and log a `data_changes` entry; `--reset` deletes only
this sport's demo rows on that venue for the named accounts (default `taker`), nothing else.
`bash scripts/deploy/vm.sh demo` (`scripts/vm/demo_setup.sh`, backup first) stores them for both demo accounts
(`--users maker,taker`), so the Pro account shows its F1 maker record and the NASCAR / MotoGP taker demo side by side.
It uses `--book best`, the best-effort book (owner, 2026-09-30: paper P&L for as many sports as possible): each kind at
the setting with its best total over the seasons it traded, the kinds with a positive total; if none is positive, every
kind at the one setting with the best total, win or lose, so the sport still has a record and a loss shows as a loss.
It is at least as in-sample as the strict rule (`--book kinds`) and is labelled the same way.
`vm.sh demo` also stores the same demo on Polymarket's NASCAR and MotoGP tape (`--venue polymarket --grid-venue
kalshi`: there is no Polymarket grid, so Kalshi's selection is traded at Polymarket's prices and fees), and `vm.sh demo
extra` runs only that step and the forecasts. First run on the VM (2026-09-30, Kalshi, backup
`racinglines-before-demo-setup-20260930T213425Z.sql.gz`): NASCAR maker 2025 8 races −$278.31, 2026 32 races +$6,525.45;
taker 2025 −$357.23, 2026 +$2,657.23 (the Basic demo follows about a third of the signals); MotoGP 2026 11 races, maker
+$31.25, taker +$7.70.

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
| Championship sleeve | demo maker | Both | `racinglines f1 season-strategy --paper --venue polymarket --after-round N` and the same with `--venue kalshi`, run by hand after each race (nothing schedules it); stored as paper positions under venue `season:<venue>`, event `<year>-season`, which A, C and K's records never read. See [Season strategy](market-making.md#the-championship-sleeve) |

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
   against the result and against the venue's mid at each stage. `racinglines f1 scorecard --event
   YEAR-ROUND --venue both` scores a Polymarket or Kalshi weekend from its stored stage runs (per stage
   and market kind, and pooled; `--all --year` for a season; see [F1 evaluation](f1-evaluation.md#the-weekend-scorecard)),
   `racinglines live report` a private book.
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
