# Data changes

A record of the changes to the race history the models read: what changed, when, why, and how to undo it.

Two places keep it:

- **The database** (table `data_changes`): every `mtb_dh ingest` run that ingested anything, every
  `db merge-athletes`, and notes. Read it with `racinglines db changes`; add a note with
  `racinglines db changes --add "why" --sport mtb_dh`, or give an ingest its reason with `--note`. Ingests that
  change nothing aren't logged. The table travels with database dumps (the bucket's full dump).
- **This page**, for the major updates: the story, the numbers, and where the backup is.

Before a major update, keep what it replaces: a database dump in `data/backups/db/` and the old raw
files in `data/archive/<sport>/` (both git-ignored; `data/raw` is the record, so it isn't edited in place
without a copy). Not `data/archive/db/`: that folder is tracked in git (the snapshot).

## 2026-09-28 · Kalshi F1 history pulled (2025–2026)

**Why.** To backtest and show Kalshi next to Polymarket: Polymarket has listed no F1 race since Baku, Kalshi lists
every weekend. Owner-approved; read-only Kalshi API (no orders, no portfolio calls). Backup first:
`data/backups/db/racinglines-2026-09-28-before-kalshi-history.dump`.

**What.** `markets --exchange kalshi sync --year 2025 --closed` and `--year 2026 --closed`, then trades and hourly
candlesticks (`--period 60`) for every event with modeled links, from each market's `open_time` to its close
(or now, for the open championships). No failures, no rate-limit errors; every modeled event had trades.

| | Rows |
|---|---:|
| Kalshi links (`market_links.exchange='kalshi'`) | 3,793 (200 events), 1,847 modeled |
| Modeled, by kind | win 330 · podium 330 · top 10 330 · fastest lap 330 · pole 308 · top constructor 143 · h2h 14 · drivers' champion 41 (19 in 2025, 22 in 2026) · constructors' champion 21 (10 + 11) |
| Trades | 857,797 (71.7 M contracts) on 1,722 markets; 126 modeled markets never traded |
| Hourly prices | 408,211 on all 1,848 markets of those events, 2025-02-12 to 2026-09-28 |
| Parquet (`data/archive/markets/kalshi/`, in git) | links 140 KB · prices 0.8 MB · trades 23 MB |

Covered: the 15 Grands Prix of 2026 so far (Australia to Azerbaijan; no pole market for Azerbaijan) and the 2025 and
2026 championships. **2025 race markets are stored but unmodeled**, so they have no trades or prices yet: the
classifier doesn't read their older titles ([F1](f1.md#kalshi-alignment)). How Kalshi's feed differs from
Polymarket's: [Data](data.md#exchange-history-kalshi-and-polymarket).

**Side effect.** The market recorder's hourly archive pass isn't per exchange: at 14:06 UTC it moved 201,751
Kalshi price rows and 283,468 trade rows (all Kalshi) out of Postgres into new part files under
`data/archive/markets/polymarket/{prices,trades}/` (untracked files in the main checkout). Nothing was lost:
the export read Postgres and those files together and deduplicated. Those part files hold only `KX…` tokens and
should move out of the Polymarket tree; later passes will move the rest of the stale Kalshi rows the same way
until archiving is per exchange.

**Undo.** Restore the backup with `pg_restore --clean`, or delete the rows: `market_links` where
`exchange='kalshi'`, and `market_price_history` / `market_trades` rows whose `token_id` starts `KX`. Delete
`data/archive/markets/kalshi/` and the `KX`-only part files in the Polymarket tree.

## 2026-09-28 · Whistler run folder: replay.json added

`data/runs/live/20260925_mtb_3/replay.json` (and in the bucket, `live/20260925_mtb_3/`). Nothing in the run's
record changed; the file tells the replay how two groups of polls ran, so the replay re-derives the recorded
book fill for fill ([Live events](live-events.md#kept-for-replay)). The local folder and the bucket copy were
checked identical first (1,541 files, checksums). Undo: delete the file.

## 2026-09-28 · Downhill: athlete merges and PDF backfill

Right after the UCI re-ingest below. Backup first:
`data/backups/db/racinglines-2026-09-28-before-merges-and-pdf-backfill.dump`.

**Merges.** 53 of the 58 same-UCI-ID pairs merged with `db merge-athletes` (each logged in `data_changes`).
The duplicates had no results left, so this moved 53 name identifiers, 12 `race_predictions` rows and 5
`standings_predictions` rows onto the kept athlete and deleted the empty rows. Five pairs weren't merged:
309/762 (PINKERTON), 460/502 (MUÑOZ), 698/914 (BRADLEY), 866/1037 (HAWKINBERRY) and 1021/1035 (YOUNG). Both
athletes of each pair have a row in saved forecast run 1287's standings, and merging would have to rewrite
that run. They hold no results, so the models don't see them.

**PDF backfill.** `mtb_dh download --pdf-results` for the six events with PDF-only rounds (old files kept in
`data/archive/mtb_dh/chronorace-2026-09-28-before-pdf-backfill/`), then ingest. Feed rounds are unchanged
(checked file by file: no finish time changed, no rider lost).

| | Before | After |
|---|---:|---:|
| Downhill results | 19,214 | 19,989 |
| Events | 45 | 47 (2021 Léogang and Les Gets) |
| Athletes | 1,184 | 1,166 (−53 merged, +35 riders only seen in those rounds, all with UCI IDs) |

Added: 2021 Léogang (all rounds but the elite Qualification, whose PDF is missing on ChronoRace's server), 2021
Les Gets (all rounds), and Timed Training for 2021 Maribor and Lenzerheide, 2022 Snowshoe juniors and 2025 Val
di Sole juniors: 775 results. Timed Training PDFs carry no UCI ID, so those riders are matched by name.
Still missing: 2019–2020 (PDF text layer unreadable, needs OCR), 2025 Pal Arinsal junior Final (standings
PDF only).

## 2026-09-28 · Downhill: re-downloaded with UCI rider IDs

**Why.** Downhill athletes were matched by name, so a rider printed two ways across seasons (`WILLIAMS Jordan` /
`WILLIAMS Robert Jordan`, accents, middle names, double surnames) was two athletes with split histories. The
ChronoRace feed carries each rider's UCI ID; the downloader writes it since the cloud build-out, but the files
on disk predated it. [PR #8](https://github.com/lalligagger/racinglines/pull/8).

**What.** All 118 files in `data/raw/mtb_dh/chronorace/` re-downloaded from the feed (same events,
categories and file names; no PDF backfill), then `racinglines mtb_dh ingest` into the local database (logged
in `data_changes`).

| | Before | After |
|---|---:|---:|
| Downhill results | 19,022 | 19,214 |
| Athletes with results | 1,181 | 1,125 |
| UCI identifiers | 0 | 1,090 |
| Events | 45 | 45 |

- Existing rows: no finish time changed and no rider was lost in any round (checked file by file before
  ingesting).
- 584 results moved from 58 duplicate athletes to the athlete their UCI ID matches (ingest matches the UCI ID
  first). The duplicates are left with no results.
- Added: 2026 round 8 (Whistler, `20260925_mtb`) Final and qualifying, which the old file predated (+192
  results).
- Not done: `db merge-athletes` for the 58 reported pairs. The duplicates are now empty rows holding a name
  identifier (and 19 old `race_predictions` rows); merging them is the owner's call. Pairs:
  `racinglines db changes` detail (`merge_pairs`) or the ingest output.
- Schema: `alembic upgrade head` ran first (`live_events`, `data_changes`). A checkout older than PR #8 won't
  recognise the database's revision; pull `live-event` (with PR #8) before `db init` there.

**Undo.** `data/backups/db/racinglines-2026-09-28-before-uci-reingest.dump` (restore with
`pg_restore --clean`), and the old files in `data/archive/mtb_dh/chronorace-2026-09-28-before-uci/`.

## Earlier

- 2026-09-27 · Database rebuilt from the snapshot (`db snapshot-import`); sweeps, runs and market links came
  back from it, event diagnostics and scenarios didn't ([Roadmap](todo.md)).
