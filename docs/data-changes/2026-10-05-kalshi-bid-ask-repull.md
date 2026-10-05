# Kalshi bid/ask re-pull — 2026-10-05

## Why

Kalshi taker replays read `market_price_history.price`, the hourly candle's last-trade close (or the bid/ask mid
when nothing traded). A last trade can be far from where a taker could have filled. Kalshi's candlesticks also
carry the YES bid and ask closes, so we store them and re-pull the 2025–26 history to fill them in.

## What changed

| Change | Where |
|---|---|
| `bid`, `ask` (nullable floats) on `market_price_history` | migration `a7e3c1f9b4d2` (PR #52, deployed 2026-10-05) |
| Kalshi candles store price, bid and ask; an hour with no price (no trade, one-sided or dead book) gives no row, as before | `markets/kalshi/sync.py` `history_rows` |
| The archive pass keeps `bid`/`ask` in Parquet; files written before them read as null; when a key is stored twice (a re-pull over archived rows), the row with bid/ask wins on read and on `compact` | `markets/store.py` |
| `history --save-raw DIR` keeps Kalshi's raw candlesticks responses (`DIR/<series>/<ticker>.json`); `history --from-raw DIR` re-imports them without the network | `cli/markets.py`, `fetch_history` |

Polymarket and OG.com price rows leave `bid`/`ask` null. Nothing reads them yet: the Kalshi replay
(`markets/venue_replay.py`) still fills on `price` until a separate change switches it.

## The re-pull (VM)

1. Backup: `data/backups/db/racinglines-before-kalshi-bid-ask-phase-2-20261005T084328Z.sql.gz` (86 MB, taken
   before the migration).
2. Pull with raw responses kept, on the VM (it reaches Kalshi; the cloud doesn't):
   `racinglines markets --exchange kalshi history --start 2025-01-01 --end <today> --save-raw data/raw/kalshi/candles-<UTC>`
   (per sport with `--sport`, as for `sync`). Rows are committed per market, so a stopped run keeps what it stored.
3. Check: the share of Kalshi rows with both sides, and `bid <= price <= ask` on a sample.
4. A `data_changes` entry (`racinglines db changes --add ...`) naming the backup and the raw folder.

## Reproducing it

The raw folder is the source. On a copy restored from the backup, after `alembic upgrade head`:

```
racinglines markets --exchange kalshi history --start 2025-01-01 --end <today> --from-raw data/raw/kalshi/candles-<UTC>
```

gives the same rows (`tests/test_kalshi_bidask.py` checks the round trip). `data/` is never in git, so the raw folder
stays on the VM with the backups.

## Rollback

The columns are additive and nullable, and old code ignores them. To undo the data only, restore the backup. To undo
the schema, `alembic downgrade f8a2c4e7b5d1` (drops both columns; take a backup first).
