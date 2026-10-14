<!-- Captured by scripts/docs/capture_examples.py (id help-markets, scripts/docs/examples.toml) on 2026-10-14 05:04 UTC, commit 4313bf1+dirty, 0.4 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines markets -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
racinglines markets <command>: exchange data (Polymarket and Kalshi; F1 plus the tape-only sports).

    sync       Sync the exchange's events into market links (live prices, resolutions)
    history    Store price history for events (--fidelity 1 = minute-level)
    trades     Store every taker trade for events (the tape a maker replay fills against)
    record     Record order-book snapshots every --interval seconds (archives to Parquet hourly)
    archive    Move stale prices / trades / books from Postgres to Parquet (--stats: sizes)
    disagree   Cross-venue disagreement log: Polymarket vs Kalshi on every outcome listed on both, per tick
               (--event 2026-15, a round number, or season [--year]; --start/--end UTC, --step minutes, --no-save)
    settle-check  Read-only, any --exchange and --sport: our outcome from the results (markets/kinds.settle) beside
               the exchange's resolved_yes on every resolved link; lists disagreements, exit 1 if any [--out FILE.csv]

Options: --exchange polymarket (default) --sport f1 (default), then the command's own options.

Polymarket for a tape-only sport (--sport nascar|motogp|indycar; sports/<code>.toml [markets.polymarket] tags,
unverified against the live Gamma API; markets/polymarket/sync.py). Additive: rows are upserted, never deleted:
    sync       [--year 2026] [--closed] [--tags SLUG …]   the sport's Polymarket events into market links
    trades     [--events SLUG …]                          the tape of those events' markets
    history    [--events SLUG …] --start --end [--fidelity 60]   price history (minutes per point)
    books      [--events SLUG …]                          one order-book snapshot per open market
(--sport f1 keeps the commands above, except `trades` and `history` without --events, which take every F1 market
the same way; `record` is F1 only.) `trades --open --since-hours H` on any exchange: only markets not closed, only
trades from H hours ago on (the recorder's pass, scripts/vm/record_venues.sh and pm_sync.sh; the one-off backfill,
scripts/vm/backfill_tape.sh, takes --since-hours alone).

Kalshi (--exchange kalshi; markets/kalshi/, built on mocked responses, unverified against the live API):
    sync       [--year 2026] [--closed] [--series TICKER …]   the sport's Kalshi markets into market links
    trades     [--events TICKER …]                       the tape of those events' markets
    history    [--events TICKER …] --start --end [--period 60]   candlesticks (minutes: 1, 60, 1440): price, bid, ask
               [--save-raw DIR | --from-raw DIR]          also keep Kalshi's raw responses / re-import them offline
    books      [--events TICKER …]                       one order-book snapshot per open market
    coverage   [--events TICKER …]                       stored prices with the candle's bid/ask (Parquet + Postgres)

Exchanges defined as schemas (--exchange og; exchanges/<code>.toml, markets/exchange_driver.py), read-only:
    sync       [--year 2026]                             the sport's markets and quotes into market links
    settle     [--since UTC] [--max-pages N]             outcomes of closed links from the settlement feed
               (resolved_yes; a void is recorded in params and left empty); a schema with no feed does nothing
               --check: no scan, read-only: compare our settlement with resolved_yes (= settle-check)
    trades     [--events SYMBOL …]                       the tape the exchange still serves (about a month)
    history    [--events SYMBOL …] --start [--end]       minute prices (clipped to what the exchange keeps)
    books      [--events SYMBOL …]                       one order-book snapshot per open market
    fair       the model's fair price beside the quote, net of the taker fee: a simple indicator, no trades
    buy-all    debug, read-only: one YES and one NO of every market (modeled or not) at the first price stored
               (minute price, trade, book side or the sync's quote, whatever the spread or depth), held; P&L settled
               when resolved, else marked at the last price stored [--cost 0.01] [--fee F] [--out FILE.csv]

--sport names the sport (default f1): the tape-only sports (nascar, motogp, indycar; sports/<code>.toml
[markets.kalshi] / [markets.polymarket]) are synced only when named, every link unmodeled, under their own
competition. Without --events, trades / history / books take every event of --sport's competition on the
exchange (books: open markets).
```
<!-- --8<-- [end:output] -->
