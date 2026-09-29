# Kalshi history

The maker's record on Kalshi, filled only by Kalshi's real taker trades. Everything here is off by
default: nothing changes until the Kalshi tape is synced and one of the commands below is run.

## The data

`markets/kalshi/` stores Kalshi's F1 markets in the tables Polymarket uses (`market_links` with
`exchange = 'kalshi'`, `market_trades`, `market_price_history`). The cloud can't reach Kalshi, so the pull
runs on a machine that can:

    racinglines markets --exchange kalshi sync --year 2025 --closed
    racinglines markets --exchange kalshi sync --year 2026 --closed
    racinglines markets --exchange kalshi trades  --events KXF1RACE-... ...
    racinglines markets --exchange kalshi history --events KXF1RACE-... --start ... --end ... --period 60

Archived Kalshi rows live in `data/archive/markets/kalshi/` (`store.root_for("kalshi")`), apart from
Polymarket's; `markets archive` sends Kalshi's tokens there. One difference matters everywhere: a Kalshi link's `condition_id` is its **event** ticker,
shared by every driver's market of the event, so Kalshi code reads and groups the tape by market ticker
(`token_id`), never by condition.

## Kalshi's historical feed vs Polymarket's

The full comparison (API, contract shape, grouping, trades and wallets, price history, books, fees, tick,
coverage) is in [Data](data.md#exchange-history-kalshi-and-polymarket); what was pulled is in
[Data changes](data-changes.md).

What this means for the replays:

- The maker replay's market kinds (`maker_replay.MODELED`) are win, podium, head-to-head and top
  constructor on both venues. Kalshi's top 10 and fastest lap are synced but not replayed.
- The fill rule is the same on both. A taker trade after our quote, at or through our price, fills us up to
  the trade's size. On Polymarket a trade on either token is first turned into YES terms. Kalshi's tape is
  already in YES terms.
- The liquidity filter (`min_volume_24h`) is per market on Kalshi. Summing by `condition_id` would count the
  whole event's volume toward each driver.

## The maker's record on Kalshi

    racinglines f1 demo-history --venue kalshi [--reset]

This runs the same profiles as the Polymarket record (M1-M3 in 2025, C in 2026) and the same maker replay,
filled by Kalshi's real taker trades, with Kalshi's maker fee (`maker_replay.KALSHI_MAKER_FEE`: 0.0175 x C x P x (1 − P),
rounded up to the cent, per fill). The results are stored as `paper_positions.venue = 'kalshi'`, with signals
flagged `detail.venue = 'kalshi'`. The Polymarket record, its `--reset` and live signals leave these rows
alone, and the reverse holds too.

Check (2026-09-28): Baku 2026's Polymarket tape, copied into Kalshi's shape (one ticker per question, one event
ticker per kind), replays to the same 72 positions as the Polymarket replay. Only the maker fee differs
(net cash $30.55 → $29.86).

## First real run (2026-09-28)

On the pulled Kalshi tape ([Data changes](data-changes.md)), in a cloud copy of the database, the demo maker ran
its profiles over all 24 Grands Prix of 2025 (M1–M3) and the 15 of 2026 so far (C). The Polymarket record was run
on the same copy for comparison, and matches [Paper trading](paper-trading.md) to the cent.

| Profile (weekends) | Kalshi | Kalshi, no maker fee | Polymarket |
|---|---:|---:|---:|
| M1, 2025 R1–8 | **+$521.61** (8) | +$545.73 | **+$169.02** (7) |
| M2, 2025 R9–16 | **−$646.13** (8) | −$553.26 | **+$214.68** (8) |
| M3, 2025 R17–24 | **+$317.91** (8) | +$373.74 | **−$98.85** (8) |
| 2025 total | **+$193.39** | +$366.20 | **+$284.85** |
| C, 2026 R1–15 | **−$118.84** (15) | −$54.45 | **+$653.03** (15) |

"No maker fee" is the same replay with the fee set to zero. It isn't the with-fee P&L plus the fees: the fee
changes the maker's cash, and so a few later quotes.

**2025 on Kalshi is win and podium only** (pole and fastest lap were listed for the last three races, and the
profiles don't quote them). Kalshi opened its 2025 race markets only two to four days before each race, so the
tape is thinner than 2026's (median trades per market: win 19, podium 26). The maker still filled in 93 of 481
win markets and 100 of 441 podium markets. By kind, without the fee: win +$356.27,
podium +$9.94. Hungary 2025 (M2, −$508) is most of M2's loss.

### 2026, profile C

| 2026, profile C | Kalshi | Polymarket |
|---|---:|---:|
| Paper P&L, settled | **−$118.84** (−$66.30 before $52.54 of maker fees) | **+$653.03** (as in [Paper trading](paper-trading.md)) |
| Fills | 1,263 | 843 |
| Quoted markets filled: win | 75 of 87 (86%) | 64 of 74 (86%) |
| Quoted markets filled: podium | 71 of 80 (89%) | 46 of 62 (74%) |
| Quoted markets filled: top constructor | 10 of 17 | 5 of 8 |
| Quoted markets filled: head-to-head | 2 of 3 | 11 of 20 |
| P&L by kind: win / podium / constructor / h2h | −95.29 / −78.43 / +41.78 / +13.10 | +424.01 / +216.04 / +22.02 / −9.05 |

- **Kalshi's tape fills the maker reliably.** Most quoted win and podium markets fill, so the record needs no
  simulated takers. Head-to-heads are the exception, since Kalshi lists few of them.
- **The same maker loses on Kalshi even before fees.** Profile C was tuned on Polymarket's flow. On Kalshi it
  fills more often (podium: 647 fills vs 222) and does worse on those fills. That suggests Kalshi's takers are
  better informed against our quotes, or Kalshi's prices are closer to the result. Whether a Kalshi-tuned
  maker (spread, disagreement filter) does better is a question for a sweep, and nothing here tunes for it.
- Weekend by weekend (Kalshi, including fees): Australia −25, China +141, Japan +225, Miami −91, Canada +120,
  Monaco −50, Barcelona −301, Austria −237, Britain −209, Belgium +32, Hungary +137, Netherlands +37,
  Italy +165, Spain 0, Azerbaijan −62.

## In the app

Kalshi is at the same level as Polymarket across the app, on by default (the owner's call, 2026-09-28).
`RACINGLINES_KALSHI_VENUE=0` turns it off: nothing below appears, Kalshi shows as "soon" on the board and race
pages, its rows stay out of Positions, and `/markets/kalshi` is a 404.

| Page | With Kalshi on |
|---|---|
| Markets (board) | Kalshi as a live venue chip per race; the winner's Kalshi price next to Polymarket's in recent results; a link to the Kalshi list |
| Race and season pages | a Kalshi column with its bid–ask (open races) or its price as of our pricing (past races); the price-history tab plots Polymarket or Kalshi; a Kalshi mirror button and link |
| `/markets/kalshi` | every listed Kalshi event, as `/markets/polymarket`: outcomes, bid/ask/last, our fair, edge, a quote at ± spread/2, mirror into my book, refresh from Kalshi (read-only) |
| Positions | a Kalshi P&L tile (a filter, like the others), the Kalshi curve in the P&L history, `?venue=kalshi` in the venue menu, Kalshi pills on rows and fills in the all-venues view, Coming up lists Kalshi's open markets with the maker's quotes |
| Strategy | a Polymarket / Kalshi switch; `?venue=kalshi` shows the maker's Kalshi record, weekend by weekend, with its signals and positions |
| Lab | Event diagnostics get Kalshi fills / P&L columns (the same replay on Kalshi's tape, with its maker fee); a diagnostic's maker replay has an Exchange selector |

The Polymarket record, its pages and the private book render exactly as before with Kalshi off. A Kalshi
`condition_id` is the whole event, so the race page, the mirror and the Coming-up volume group Kalshi's rows by
market ticker (`token_id`), where Polymarket's group by condition.

## Profile K

`K · Kalshi maker` is the maker tuned on Kalshi's own tape: the queue `sweeps/kalshi-maker-k.toml`
(`racinglines f1 search`, then `search-report`), every job with `venue = "kalshi"`, so each run replays the
five maker strategies on Kalshi's markets and trades with its maker fee (`f1 sweep --venue kalshi`) against a
default-settings baseline on the same venue. Judged as params-4h was: 2026 the target, 2025 held out, maker
noise floor ±350, ranked by 2026 P&L less any 2025 loss.

**The grid (2026-09-29, complete).** Round 1 = model (`gbm`, `gridq+pretrain`) × `half_spread` (0.01–0.04)
× `max_disagree` (0.05, 0.07, 0.10, 0.15), 25-share quotes. Round 2 = quote `size` (10, and the default 50) and
the maker's per-market `maker_min_volume_24h` (50 / 200 / 400; unset = the replay's own $100) at 2¢ quotes, with
`max_disagree` 0.05 and 0.10. Every combo ran in both seasons: 104 jobs plus the two Kalshi baselines, 3 at a
time on 4 cores, about an hour. The top 3, and the partial grid's pick, were then re-run at 16,000 simulations in
both seasons against a 16k baseline. Sanity checks: the grid's `gbm · max_disagree 0.05, size 25` (profile C) on
2026 is −118.84, the same as `demo-history --venue kalshi` above, and every combo the partial grid ran came out
to the cent.

Conservative maker, Kalshi, with the maker fee (P&L in $; 16k = the same combo at 16,000 simulations):

| Settings (rest default) | Label | 2026 | vs baseline | 2025 | vs baseline | 16k: 2026 / 2025 |
|---|---|---:|---:|---:|---:|---:|
| **gbm · max_disagree 0.10, size 25, min volume $400 (K)** | robust, confirmed | **+490** | +1,360 | **+855** | +1,250 | **+453 / +933** |
| gridq+pretrain · half_spread 0.04, size 25 | robust, confirmed | +710 | +1,581 | +50 | +446 | +649 / **−104** |
| gbm · half_spread 0.04, max_disagree 0.10, size 25 | robust, confirmed | +469 | +1,340 | +617 | +1,013 | +219 / +684 |
| gbm · half_spread 0.03, max_disagree 0.10, size 25 (the partial grid's K) | robust, confirmed | +450 | +1,321 | +707 | +1,103 | +228 / +734 |
| gbm · max_disagree 0.10, size 25, min volume $200 | robust | +389 | +1,259 | +832 | +1,228 | |
| gbm · max_disagree 0.10, size 25 | robust | +223 | +1,094 | +829 | +1,224 | |
| gbm · max_disagree 0.10, size 10 | robust | +164 | +1,035 | +662 | +1,058 | |
| gbm · max_disagree 0.10 (size 50) | robust | −78 | +793 | +780 | +1,175 | |
| gbm · max_disagree 0.05, size 25 (C) | robust | −119 | +752 | +685 | +1,080 | |
| baseline (defaults) | | −871 | | −395 | | −1,261 / −394 |

**The pick.** Under the held-out rule the top score at 4k simulations is `gridq+pretrain · half_spread 0.04`
(+710 in 2026), but it only just clears the noise floor in 2025 (+446 vs baseline, +50 P&L) and at 16k it loses
money there (−104, +290 vs the 16k baseline, inside the noise floor). K is the next one down: `gbm`, 2¢ quotes,
out of markets where the model and price disagree by more than 10 points, and out of markets with less than $400
traded in the prior 24 hours. It is the only top combo that holds up at 16k in both seasons (+453 / +933, against
+228 / +734 for the partial grid's pick), and it has the best 2025 of the lot (Sharpe 1.53). K beats C on Kalshi by
+609 in 2026 (beyond the noise floor) and +170 in 2025 (within it).

What the grid says: gbm is the maker's model on Kalshi, as on Polymarket; `gridq+pretrain` is good in 2026 and
loses or barely wins in 2025 almost everywhere. A looser disagreement filter (10 points) beats C's 5 on Kalshi.
Staying out of thin markets (the $400 volume floor) does what the wider 3–4¢ quote did in the partial grid, with
less 16k slippage. Quote size matters less: 25 beats 10 and 50.

**Caveats.** 2026's Sharpe is modest (0.62) and its max drawdown ($499) is larger than C's on Polymarket. Without
its best weekend K's 2026 is −145, so the season's profit rests on a few weekends. One seed per combo (the noise
floor is params-4h's ±350, not measured here). Freezing K is the owner's call. `signals.maker_call` now reads a
profile's `maker_min_volume_24h`, so a live K quote uses the same $400 floor as the replay (unset = $100, as
before).

The full table of every combo × maker strategy, with the 16k columns, is in the project files
(`roadmap-spinup/u3-kalshi-maker-k/`).

**Assigning K is an explicit step.** `racinglines f1 profiles` creates K as a Lab candidate
(`params.venue = "kalshi"`); `racinglines f1 profiles --assign-demo --venue kalshi` stores it as the demo
maker's Kalshi profile (`users.prefs["strategy_profile_kalshi"]`), beside its Polymarket profile C, which it
leaves alone. Nothing reads that key until the signal engine runs Kalshi, so the deployed app doesn't change.
