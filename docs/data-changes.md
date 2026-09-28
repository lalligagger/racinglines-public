# Data changes

A record of the changes to the race history the models read: what changed, when, why, and how to undo it.

Two places keep it:

- **The database** (table `data_changes`): every `mtb_dh ingest` run that ingested anything, every
  `db merge-athletes`, and notes. Read it with `racinglines db changes`; add a note with
  `racinglines db changes --add "why" --sport mtb_dh`, or give an ingest its reason with `--note`. Ingests that
  change nothing aren't logged. The table travels with database dumps (the bucket's full dump).
- **This page**, for the major updates: the story, the numbers, and where the backup is.

Before a major update, keep what it replaces: a database dump in `data/archive/db/backups/` and the old raw
files in `data/archive/<sport>/` (both git-ignored; `data/raw` is the record, so it isn't edited in place
without a copy).

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

**Undo.** `data/archive/db/backups/racinglines-2026-09-28-before-uci-reingest.dump` (restore with
`pg_restore --clean`), and the old files in `data/archive/mtb_dh/chronorace-2026-09-28-before-uci/`.

## Earlier

- 2026-09-27 · Database rebuilt from the snapshot (`db snapshot-import`); sweeps, runs and market links came
  back from it, event diagnostics and scenarios didn't ([Roadmap](todo.md)).
