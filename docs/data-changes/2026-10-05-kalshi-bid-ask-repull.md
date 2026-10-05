# Kalshi Bid/Ask Re-Pull — 2026-10-05

## Problem Statement

Kalshi taker replays were using spiky last-trade prices from `market_price_history.price`, which do not accurately reflect the order book state when trades occurred. For accurate taker fills, we need to use the bid/ask from Kalshi candlesticks (hourly snapshots of the top-of-book), not the volatile last-trade close.

## Solution

### Schema Change

**Migration:** `20261005_a7e3c1f9b4d2_kalshi_candlestick_bid_ask.py`

```sql
ALTER TABLE market_price_history
  ADD COLUMN bid FLOAT,      -- Candlestick bid close (YES side)
  ADD COLUMN ask FLOAT;      -- Candlestick ask close (YES side)
```

- Columns are nullable for backward compatibility during migration and re-pull
- `price` column retained for existing queries (stores last-trade close or bid/ask mid)
- New code reads `bid`/`ask` directly for replay fills

### Code Changes

**`racinglines/markets/kalshi/sync.py`:**
- `history_rows()`: Now extracts bid/ask closes separately from candlesticks
- Stores them in the new columns alongside `price`
- `fetch_history()`: Updated upsert to include bid/ask in conflict resolution

### Data Preservation (Reproducibility Audit Trail)

#### 1. Database Backup

**Before migration:**
```bash
pg_dump racinglines | gzip > data/backups/db/racinglines-before-kalshi-bid-ask-repull-2026-10-05T06:25:00Z.sql.gz
```

- Captures schema at v-f8a2c4e7b5d1 (FastF1 snapshots)
- Preserves existing `market_price_history` with only `price` column
- Can restore to test migration or audit history transformation

#### 2. Candlestick Source Preservation

**Save raw Kalshi API responses:**
```bash
# Download candlesticks for all Kalshi F1 markets, 2025-01-01 to now
racinglines markets --exchange kalshi --archive-candlesticks 2025-01-01 2026-10-05
# Saves to: data/backups/kalshi/candlesticks-2025-2026.json
```

- JSON array of Kalshi `/v2/candlesticks` responses
- Includes all bid/ask/open/close/volume data
- Sources for all rows stored in `market_price_history` during re-pull

#### 3. Transformation Reproducibility

**Commit:**
- Migration file (versioned in `migrations/versions/`)
- Updated sync.py code (commit hash)
- This file (transformation log)

**To re-derive identical data:**
```bash
# 1. Restore backup database
pg_restore racinglines-before-kalshi-bid-ask-repull-2026-10-05T06:25:00Z.sql

# 2. Apply migration
alembic upgrade head

# 3. Re-import candlesticks
racinglines markets --exchange kalshi --reimport-candlesticks data/backups/kalshi/candlesticks-2025-2026.json

# 4. Verify against live API (spot-check)
```

Output: identical `market_price_history` rows with bid/ask populated.

## Scope

**Markets affected:** All Kalshi F1/NASCAR/MotoGP/IndyCar markets

**Data range:** Full history from inception through 2026-10-05

**Rows affected:**
- F1 2025-26: ~408k price history rows (bid/ask added)
- NASCAR/MotoGP/IndyCar: Additional rows (if any)

## Rollback Plan

**If issues found during Phase 2:**
```bash
# Restore pre-migration database
pg_restore racinglines-before-kalshi-bid-ask-repull-2026-10-05T06:25:00Z.sql
# Code reverts to previous sync.py version
```

This is a **safe downgrade** because:
1. No data is deleted, only columns added
2. Existing `price` column remains intact
3. Old queries continue to work
4. Only new code paths (future replay updates) depend on bid/ask

## Next Steps

See `CLAUDE.md` section "Kalshi bid/ask re-pull automation" (roadmap reference and Phase 2-3 plan).
