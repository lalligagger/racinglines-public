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
profile C over the 15 Grands Prix of 2026. The Polymarket record was run on the same copy for comparison. 2025
isn't comparable yet, because Kalshi's 2025 race markets aren't classified ([F1](f1.md#kalshi-alignment)).

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

`RACINGLINES_KALSHI_VENUE=1` (off by default) marks Kalshi as a live venue on the board and race pages. It
also lets the Positions page include the Kalshi rows (`?venue=kalshi`). With the
switch off, Kalshi rows stay out of Positions, and the Strategy page never includes them, since it shows the
Polymarket record. The Positions page's venue tiles and filter menu still list only Polymarket and the
private book. Adding Kalshi to them waits for the web UI rework.
