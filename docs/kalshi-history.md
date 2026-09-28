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
