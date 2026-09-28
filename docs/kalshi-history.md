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
Polymarket's. One difference matters everywhere: a Kalshi link's `condition_id` is its **event** ticker,
shared by every driver's market of the event, so Kalshi code reads and groups the tape by market ticker
(`token_id`), never by condition.

## Kalshi's historical feed vs Polymarket's

Both land in the same tables, but they don't mean quite the same thing. From the connectors
(`markets/kalshi/`, `markets/polymarket/sync.py`) and the live read-only checks of 2026-09-28. How much each
F1 market trades on Kalshi won't be known until the first pull is summarised.

| | Polymarket | Kalshi |
|---|---|---|
| **One market** | a *condition*: a binary question with two outcome tokens (YES / NO, or both drivers of a head-to-head) | a market *ticker*: one YES contract; NO is its mirror, with no token of its own |
| `token_id` / `condition_id` | outcome token / the question | market ticker / the **event** ticker, shared by every market of the event (every driver in "Azerbaijan Grand Prix Winner"). Group Kalshi data by `token_id`, never by `condition_id` |
| **Trades** | Data API, taker trades only, newest first, offset paging (capped at 100,000 per market). `side` is BUY / SELL of the token traded, `outcome_index` 0 or 1, with a tx hash and the taker's **wallet** | `/markets/trades`, then `/historical/trades` once a market is past the cutoff, cursor paging. `taker_side` yes / no at `yes_price`; stored as the taker's side of YES (bought NO = SELL YES), `outcome_index` always 0, `trade_id` as the hash. **No wallets** (stored as `""`), so there is no per-trader analysis on Kalshi |
| **Size** | shares (a share pays $1) | contracts (a contract pays $1); fractional since `count_fp` |
| **Price history** | `/prices-history`: one price per point at `fidelity` minutes (60 by default) | candlesticks, OHLC per 1, 60 or 1440 minutes; we store the close of the traded price, else the mid of the bid / ask closes. A period with neither has no row |
| **Price units** | decimals | cents on older responses, dollar strings (`_dollars`, or `"0.0700"` in historical candlesticks) on current ones; `kalshi.client.price()` reads all of them |
| **Old markets** | served by the same endpoints | once settled past Kalshi's cutoff (about two months), a market leaves the live endpoints: its event lists no markets, `/markets/{ticker}` is a 404, and markets, trades and candlesticks move to `/historical/...` |
| **Order books** | recorded by us (`markets record`), both tokens | recorded by us (`books`): YES bids and NO bids (a NO bid at p is a YES ask at 1 − p). Neither exchange serves past books, so the queue fill model (`--fill queue`) only works where we recorded them |
| **Fees** | none charged to makers (the replays use 0) | takers pay ceil(0.07 × C × P × (1 − P)) cents per order, and makers ceil(0.0175 × C × P × (1 − P)) on most markets; check a market's own schedule |
| **Tick** | 0.01 or 0.001 by market | 1 cent (`tick_size`) |
| **Resolution rules** | question text | `rules_primary`, kept in `params.rules`, so markets are compared across venues only when their rules agree |
| **Kinds listed for F1** | win, podium, head-to-head, top constructor, pole, champions, season wins, championship head-to-heads | win, podium, top 10, pole, top constructor, fastest lap, head-to-head, champions, plus sprint series (unmodeled). Head-to-head titles don't name the Grand Prix, so it's read from the ticker (`KXF1H2H-BRIGP26…`) |

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

## In the app

`RACINGLINES_KALSHI_VENUE=1` (off by default) marks Kalshi as a live venue on the board and race pages. It
also lets the Positions page include the Kalshi rows (`?venue=kalshi`). With the
switch off, Kalshi rows stay out of Positions, and the Strategy page never includes them, since it shows the
Polymarket record. The Positions page's venue tiles and filter menu still list only Polymarket and the
private book. Adding Kalshi to them waits for the web UI rework.
