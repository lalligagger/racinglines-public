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

The same tables and archive take the **tape-only sports** (NASCAR Cup, MotoGP, IndyCar): synced only when named
(`markets --exchange kalshi --sport nascar sync`), under their own competitions, every link `unmodeled`, so the
replays below (which read F1's modeled links) never see them.
[Data](data.md#other-series-tapes-nascar-motogp-indycar), [CLI](cli.md#kalshi-exchange-kalshi).

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

## In the signal engine

A strategy profile paper-trades Kalshi when its settings say `venue = "kalshi"` (roadmap U1; the setting
is optional, unset by default and left out of every settings key, so every Polymarket profile and saved
sweep is untouched). Then `racinglines f1 signals`, `f1 sweep --venue kalshi` and the Lab's sweeps read
the race's `exchange='kalshi'` links, one market per ticker (never grouped by `condition_id`, the event
ticker), Kalshi's tape per market (its own 24 h volume), and the maker pays `KALSHI_MAKER_FEE`; the taker
strategies (`taker_weekend`) and the maker replay run unchanged on top. Signals carry
`detail.venue = 'kalshi'`, positions `venue = 'kalshi'`, apart from the Polymarket rows as the maker's
record above. Live, a Kalshi profile refreshes Kalshi's minute candlesticks and trades for the event
(`markets/kalshi/sync.py`) before pricing, as a Polymarket profile refreshes Polymarket's. No order is
ever sent and `KALSHI_TRADING_ENABLED` is never read by the engine.

Checks (2026-09-29, Azerbaijan 2026, `scripts/signals_parity.py --venue kalshi`; see
[Paper trading](paper-trading.md#parity-with-the-sweep)): profile A's Kalshi replay through the engine
gives the sweep's 23 taker trades exactly; profile C's gives 41 fills and −$61.90 settled, the sweep
maker's figures and the −$61.90 Azerbaijan line of the record above, to the cent. Profile A on Polymarket
gives the same 11 trades before and after the change.

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

## Cross-venue disagreement log

Roadmap U7. `racinglines markets disagree --event …` ([CLI](cli.md#racinglines-markets)) keeps, for every F1
outcome linked on both Polymarket and Kalshi (a race's win, podium, top 10, pole, top-constructor and head-to-head
markets, and the season's drivers' and constructors' champion markets), one row per tick in `market_disagreements`
(`racinglines/markets/disagree.py`, migration `c8e3f6a2d4b1`):

| Column | Meaning |
|---|---|
| `pm_mid`, `pm_bid`, `pm_ask` / `kalshi_*` | Each venue's price and top of book at the tick, as the outcome's YES side (an inverted Polymarket link is flipped). The mid is the venue's last stored price at or before the tick, no older than 6 h; a book recorded within one step replaces it with (bid + ask) / 2 and gives the top of book. |
| `fair`, `run_id` | Our fair value from the run in force at the tick: for a race, the latest diagnostic or forecast with predictions for it, as of its cutoff; for the season, the latest forecast. Before the first run there is no fair and no edge (the gap columns still fill). |
| `pm_edge`, `pm_side` / `kalshi_edge`, `kalshi_side` | The better taker trade on that venue vs fair, net of its taker fee: buy YES at the ask (`fair − ask − fee`) or sell at the bid (`bid − fair − fee`); without a book, at the mid. Kalshi's taker fee is `0.07 × P × (1 − P)` per contract (`venue_replay.Kalshi.TAKER_FEE`); Polymarket charges takers nothing on these markets. |
| `gap`, `gap_net` | `kalshi_mid − pm_mid`, and `|gap|` net of both taker fees at their mids: above 0, the venues disagree by more than it costs to take both sides. |
| `pm_vol24`, `kalshi_vol24` | USD traded on each venue in the 24 h before the tick (`market_trades`; null where no tape is stored). A row is *liquid* when neither venue's tape shows nothing traded: Polymarket's stored history is a mid, and an empty book reads 0.5, so a gap on a dead market is on paper. The report and the panel count liquid rows. |

The backfill reads the archived prices, books and tapes (`data/archive/markets/{polymarket,kalshi}/`), so it runs
without exchange access; the window defaults to where both venues have prices, on an hourly grid, and for a race ends
at the race start (after it the venues settle at different speeds). With `RACINGLINES_DISAGREE=1` the recorder writes
one tick per pass from the latest stored quotes, and the Markets page shows the log's latest tick
([Web app](webapp.md#kalshi)). A price jump inside one step shows as a one-tick gap (Kalshi's hourly candle closes
at the tick, Polymarket's sample can be a few minutes older), so read the share of rows above fees and the median,
not the maximum.

**2026 championship markets** (33 outcomes, 2026-01-12 to 2026-09-27, hourly): 141,220 rows, 81,919 liquid (Kalshi's
tape is stored; Polymarket's champion tape isn't, so the Polymarket side is taken as liquid), 65,250 of them above fees
(80%). The typical net gap is small, 0.3 to 0.6 points, so most "above fees" rows are a mid-to-mid difference of a
cent or two on low-priced outcomes, where Kalshi's fee at P(1 − P) is almost nothing; the widest liquid gaps are
one-tick jumps on race days (Antonelli's championship, 2026-05-24 21:00: Polymarket 0.357 vs Kalshi 0.640). Our fair
exists only from the 2026-09-27 forecast on, which the stored prices end before, so this backfill carries no edge
columns; the recorder's ticks will. Day by day, the report is in the pull request that added it.

**Azerbaijan 2026 (round 15)**, 55 outcomes, 2026-09-22 to the race start on the 26th: 4,922 rows, 1,879 liquid,
1,221 above fees (65%; median net +0.3 points). The largest liquid gaps are Polymarket's top-constructor and
long-shot podium markets reading ~0.5 (a one-sided book) against Kalshi's 0.5 to 5 cents, which a recorded book
would have shown as a spread, not a price.
