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
without a copy). Since 2026-10-01 nothing under `data/` is in git, and production data lives on the VM: back up
there with `vm.sh backup <purpose>`.

## 2026-10-07 · Staging only: parity sprint data run (NASCAR, MotoGP, Kalshi, NASCAR links)

Database `racinglines_staging` only; production was not touched.

**Why.** The parity sprint (PRs #81, #87 and #88 into `staging`) changed what the NASCAR and MotoGP ingests store:
race start times in UTC, MotoGP Q1/Q2 and sprints as rounds, one round per kind for a restarted race, and real
names for drivers first stored without one. The ingests were re-run with `--force`, and Kalshi was re-synced to
re-file links by series ticker.

**Backups** (on the VM, under `/opt/racinglines-staging/data/backups/db/`):
- `racinglines_staging-before-parity-data-20261007T104619Z.sql.gz` (76M), before every step below except the link apply;
- `racinglines_staging-before-nascar-links-20261007T200822Z.sql.gz` (76M), before `nascar link --apply`.

**What.**
- NASCAR `fetch` and `ingest --years 2019-2026 --force` on `a282154`, then the ingest again on `8d5bd66` (#88):
  321 races ingested, 5 scheduled. Afterwards the athletes "NASCAR driver 4180" and "NASCAR driver 4093" are
  "Austin Cindric" and "Daniel Hemric"; "NASCAR driver -1" (one result, never named in a feed) remains.
- MotoGP `fetch` and `ingest --years 2016-2026 --force`: the first run stopped at 2016 NED (two `RAC` sessions).
  After #87 it finished: 204 events ingested of 211 seen; 2016 NED keeps the restarted race and lists the stopped
  session's date in `extra.superseded`.
- Kalshi `sync --closed` (one run covers every year).
- `nascar link --apply`: 221 of 15,081 links changed, all of them the links naming Austin Cindric. Undo:
  `racinglines nascar link --undo /opt/racinglines-staging/data/backups/db/nascar-links-undo-20261007T200920Z.json`.

**Verification.** `markets --exchange kalshi --sport nascar settle-check`: no disagreement (agree 5,980, undecided
769, unmodeled 6,241, void 0). `backtest coverage` after the run: MotoGP events with results 202 to 204 and newly recorded tape
files, no other change in the NASCAR or MotoGP Kalshi rows (Copilot's comparison with the first run).

**Rollback.** Restore the first dump into `racinglines_staging`, or `vm.sh staging reset` (re-copies production).

## 2026-10-05 · Kalshi F1 bid/ask candles re-pulled

**Why.** The stored Kalshi `price` is the candle's last-trade close, which can sit far outside the closing
bid/ask. PRs #52 and #53 added nullable `bid` / `ask` columns, the history upsert, and raw-response save/re-import.

**Backup.** Before the write, the VM database was backed up to
`data/backups/db/racinglines-before-kalshi-bid-ask-backfill-20261005T104713Z.sql.gz` (86 MB).

**What.** Kalshi rejects a 60-minute candle request spanning more than 5,000 candles. The F1 backfill therefore
ran in five ranges, from 2025-01-01 through 2026-10-05 10:00 UTC, committing each market as it completed:
2025-01-01–2025-05-01, 2025-05-01–2025-09-01, 2025-09-01–2026-01-01, 2026-01-01–2026-05-01, and
2026-05-01–2026-10-05 10:00 UTC. The five runs upserted 336,137 price points.

The raw API responses are retained on the VM in
`data/raw/kalshi/candles-f1-20261005T104748Z/`, in `chunk-01` through `chunk-05`: 3,958 market response files per
range (19,790 files total, 289 MB). Each chunk can be re-imported offline with
`racinglines markets --exchange kalshi history --start <chunk-start> --end <chunk-end> --from-raw
data/raw/kalshi/candles-f1-20261005T104748Z/chunk-<NN>`.

**Verification.** The transient systemd unit exited successfully. At verification time, the retained F1 rows in
Postgres numbered 200,496: 189,407 had a bid, 195,238 had an ask, and 188,190 had both. Of rows with both sides,
8,440 (4.48%) had the last-trade `price` outside the candle's bid/ask; 575 were more than 5¢ outside, the median
outside amount was 1¢, and the largest was 90¢. This is a notable share and should be considered before treating
the candles as validated replay fills. These SQL counts cover rows still in Postgres; older market rows may
already have moved to Parquet.

The database `data_changes` note records the backup, raw archive, point count, and these validation results.

**Rollback caution.** The database backup is from before the pull, but the hourly market archiver can move newly
backfilled old rows from Postgres to Parquet. Restoring only the database dump would not necessarily undo the
write; inspect both Postgres and the Kalshi Parquet archive before attempting a rollback. The retained raw
responses allow the history to be rebuilt offline.

## 2026-10-01 · The VM moved to the public repo; deploys carry code only

**Why.** The owner moved the live repo to the public `lalligagger/racinglines-public` (history restarting at
"Initial public release") and made merges to `main` deploy through GitHub Actions. **What changed on the VM.** No row
in the database. `vm.sh repoint` pointed the checkout at the public repo; the first deploy from it (`a449e18`, PR 3)
ran `deploy/vm/untrack.sh`, which backed up and untracked every file the private history tracked and the public
one doesn't (`data/raw`, `data/archive`, `tests/fixtures`, the pitch images), so they stayed on disk as untracked
files: `data/backups/files/racinglines-before-untrack-<UTC>.tar.gz`. Database backup before it:
`racinglines-before-public-deploy-20261001T071316Z.sql.gz`. From now on a deploy never restores, overwrites or
deletes data; data changes go through scripts and admin views and get their own entry here.
**Also.** The recorder's hourly archive pass (`markets record`) moves cold market rows from Postgres to Parquet
under `data/archive/markets/` on the VM's disk: the database dump fell from 118 MB to 56 MB (2026-10-01 01:56Z,
counts verified). A dump alone is therefore not the whole market history; the archive folder is the rest, and it
has no copy off the VM yet ([todo](todo.md#staging-and-ci-deploys) STG-5).
**Undo.** `vm.sh deploy <commit>` moves code only; the untracked files can be restored from the tar.

## 2026-10-01 · Kalshi and OG.com order books recorded on the VM (vm.sh record)

**Why.** The owner wanted Kalshi and OG.com recorded live through the round-16 weekend, beside the Polymarket
recorder. **What changes.** `racinglines-record-venues.timer` runs `scripts/vm/record_venues.sh` every 5 minutes:
one order-book snapshot per open market (`market_book_snapshots`, insert-only) for Kalshi F1 / NASCAR / MotoGP and
OG.com F1 / NASCAR, and an hourly sync per pair (market links and quotes upserted). The first pass backs up to
`data/backups/db/racinglines-before-record-venues-<UTC>.sql.gz` and its `data_changes` note names the file.
**Undo.** `vm.sh record off`; the snapshots are additive (delete by `ts` after the backup's time, or restore it).

## 2026-09-30 · NASCAR and MotoGP demo paper portfolio on the VM (rl-demo)

**Why.** The owner wanted a paper P&L history for the demo accounts beyond F1. **What changed.** `vm.sh demo` ran
`scripts/vm/demo_setup.sh` (unit `rl-demo`, best-effort book): each sport's selection from the overnight Kalshi
settings grid stored as both demo accounts' backfilled Kalshi paper positions (in-sample, never buy-all). NASCAR maker
2025 8 races -$278.31, 2026 32 races +$6,525.45; NASCAR taker 2025 -$357.23, 2026 +$2,657.23; MotoGP 2026 11 races
maker +$31.25, taker +$7.70. The `data_changes` rows name the backup:
`data/backups/db/racinglines-before-demo-setup-20260930T213425Z.sql.gz`.
**Undo.** `racinglines <sport> demo-history --reset --users maker,taker --backup FILE`, or restore the backup.

## 2026-09-30 · Reattached the maker's Kalshi profile on the VM

**Why.** The maker account had lost `users.prefs["strategy_profile_kalshi"]` even though the Kalshi replay rows
were still present, so the Strategy page for `?venue=kalshi` rendered a zero-dollar cumulative record instead of
its historical maker replay. **What changed.** The VM ran `racinglines f1 profiles --assign-demo --venue kalshi`,
restoring `K · Kalshi maker` as the maker's Kalshi profile beside its existing Polymarket profile, and the
`data_changes` row named the backup. Backup: `data/backups/db/racinglines-before-kalshi-profile-20260930T172425Z.sql.gz`.
**Undo.** Restore the backup or clear `users.prefs["strategy_profile_kalshi"]` and leave the Polymarket profile
alone.

## 2026-09-30 · Overnight VM run: NASCAR and MotoGP results, links, tape and replay saves on the VM

**Why.** The overnight run (report: `reports/2026-09-30-overnight-vm-run/report.md`) needed NASCAR and MotoGP on the
VM, which had their Kalshi links but no results. **What ran (VM).** NASCAR: results fetched and ingested for 2016-2026
(408 events), Kalshi re-synced and `nascar link --apply` (7,544 Kalshi links with a race), then the Kalshi tape pull
(NASCAR Kalshi hourly prices 152,257 before the dead-book cleanup, 295,553 during the pull) and the replay saves
(`RACINGLINES_PREDICTION_RECORDS=1`). MotoGP: results ingested newest seasons first (202 events), Kalshi re-synced,
tape pulled and replay saves stored. The demo taker's backfill was rebuilt (`f1 demo-history --reset --user taker`).
Backups: `racinglines-before-overnight-replay-20260930T092216Z.sql.gz` (97 MB),
`racinglines-before-nascar-ingest-link-*.sql.gz`, `racinglines-before-demo-taker-story-20260930T152320Z.sql.gz`
(118 MB), all in `data/backups/db/` on the VM. **Undo.** The replay saves with `racinglines <sport> replay --undo
BATCH` (batch ids: `grep "batch replay-"` in the run logs); the NASCAR links with `nascar link --undo` and the undo
file in `data/backups/db/`; the taker's backfill by restoring the story backup. Results, links and tape are additive
and harmless to keep.

## 2026-09-30 · NASCAR and MotoGP Kalshi prices: dead-book 0.50 cleanup

**Why.** Before PR #90, a Kalshi candle with one empty book side was stored as a 0.50 mid. The VM must never pull
with that rule, so the NASCAR and MotoGP Kalshi prices pulled with it were removed and pulled again. A read-only check
first showed the stage 1 replay P&L didn't depend on them (share of P&L from trades opened at 0.50: NASCAR −0.8%,
MotoGP 0%). Backup first: `data/backups/db/racinglines-before-deadbook-cleanup-20260930T060600Z.sql.gz` (19 MB).

**What ran (LOCAL, main at 430c17b).** Deleted the `market_price_history` rows for Kalshi links in `nascar_cup` and
`motogp_wc` (27,024 rows). 9 MotoGP Kalshi price Parquet files under `data/archive/markets/kalshi/prices/` (months
2026-03 to 2026-09, written 2026-09-30 05:40 UTC with the old rule) were moved to the Mac's Trash,
`~/.Trash/kalshi-prices-deadbook-20260930/`. Then `nascar replay --years 2026 --events latest --venue kalshi --tape
pull` (15,174 prices, 73 at 0.50, was 17,079 and 151) and `motogp replay --years 2026 --venue kalshi --tape pull`
(5,082 prices, 41 at 0.50, was 9,885 and 214). The replay at a $0 floor: NASCAR 240 trades, +1,293.24 (was 220,
+1,350.49); MotoGP 93 trades, +413.62 (was 67, +508.67). Trades, links and F1 rows untouched. `data_changes` notes
for both sports, plus the two tape-pull entries.

**Undo.** Restore the backup, and move the Parquet files back from the Trash (until it's emptied).

## 2026-09-30 · NASCAR Cup live market sync

**Why.** Fill the valid Cup market universe from the live exchange feeds so the app and backtests have the same market set as the identified NASCAR tape. Backup first: `data/backups/db/racinglines-before-nascar-market-sync-20260930T021142Z.sql.gz`.

**What ran.** `racinglines markets --exchange polymarket --sport nascar sync --year 2026 --closed` and `racinglines markets --exchange kalshi --sport nascar sync --year 2026 --closed`, then `racinglines nascar link --apply --backup ...` to attach athlete / race / kind. The result was 14,700 NASCAR market links in the local DB, with 7,044 outcomes fully identified across both venues.

**Undo.** Restore the backup or delete `market_links` rows with `competition_id` for `nascar_cup` and their associated prices/trades/books.

## 2026-09-29 · VM: Kalshi tape-only sports (NASCAR, MotoGP, IndyCar) and OG.com, first live run

**Why.** After deploying main (7e5d64d) to the VM: rebuild the Kalshi F1 demo record there, and run the fixture-tested
Kalshi tape-only sport sync (PR #26, U9) and the OG.com connector (PR #44) against the live APIs for the first time.
Read-only APIs, no orders. Backup first: `data/backups/db/racinglines-before-history-20260929T082054Z.sql.gz` on the
VM (pg_dump through docker compose, 14.5 MB). Run log: `data/backups/history-rebuild-20260929.log` on the VM.

**What ran (VM, as `racinglines`).** `f1 pm-links-import --exchange kalshi` (3,793 rows, 0 unresolved) and
`f1 demo-history --venue kalshi --reset` (5,054 backfilled signals deleted; 39 weekends rebuilt: 2025 24 weekends,
paper P&L +193.39; 2026 15 weekends, −118.84). Then per sport `markets --exchange kalshi --sport <s> sync`,
`trades`, `history --start 2026-08-29T00:00 --end 2026-09-29T00:00`, `books` (no `--closed`). The Polymarket half
(`pm-links-import --exchange polymarket`, `demo-history --venue polymarket --reset`) was not run.

**Two things broke on the way.** (1) The three sports' `competitions` rows (`nascar_cup`, `motogp_wc`,
`indycar_series`) did not exist on the VM, so every tape-only sync (and the OG.com NASCAR sync) failed with
`NoResultFound` in `kalshi/sync.py competition()`; the rows were added (ids 3–5) and the run resumed. A sync
should seed its sport's competition from `sports/<code>.toml` instead of requiring it. (2) The OG.com F1 sync
failed with `400 {"code": 40004, "message": "Invalid event_symbol"}`: `get-instruments` takes at most 10
`event_symbols` per call (checked one by one and in sets of 10 and 11 on 2026-09-29; every symbol is valid alone;
`get-tickers` took 20), and `exchanges/og.toml` batched 25. Fixed here: `batch_size = 10`, the test's fake API
now refuses 11. The OG.com F1 sync has still not run; the NASCAR one had one event and worked.

| Kalshi, first live tape-only sync | Links (all `unmodeled`) | Events | Trades | Hourly prices (last 31 days) | Book snapshots |
|---|---:|---:|---:|---:|---:|
| NASCAR (`competition_id` 3) | 13,599 (13,186 closed) | 419 | 1,693,932 | 152,257 | 826 |
| MotoGP (4) | 322 (289 closed) | 15 | 12,451 | 4,792 | 33 |
| IndyCar (5) | 1,374 (all closed) | 54 | 166,737 | 14,460 | 0 (nothing open) |

Series matched (by event ticker prefix): NASCAR `KXNASCAR`, `KXNASCARRACE` (3,480), `KXNASCARTOP3`/`TOP5`/`TOP10`/
`TOP20`, `KXNASCARFASTLAP` (1,944), `KXNASCARPOLE`, `KXNASCARH2H`, `KXNASCARTOPTEAM`, `KXNASCARBIGGESTMOVER`,
`KXNASCARCUPSEASON`, `KXNASCARCUPSERIES`, `KXNASCARCHALLENGE`, and two that are not Cup: `KXNASCARAUTOPARTSSERIES`
(40, the Xfinity-tier series) and `KXNASCARTRUCKSERIES` (35). MotoGP `KXMOTOGP`, `KXMOTOGPRACE` (289), `KXMOTOGPTEAMS`.
IndyCar `KXINDYCARRACE` (433), `TOP3`/`TOP5`/`TOP10`, `KXINDYCARFASTLAP`, `KXINDYCARPOLE`, `KXINDYCARSERIES`,
`KXINDYCARBIGGESTMOVER`. Nothing was classified as modeled, as designed. Open question: whether the Truck and
Auto Parts series belong under `nascar_cup` (they match the `KXNASCAR` prefix) or should be filtered.

OG.com: `markets --exchange og --sport nascar sync` → 1 event (`NSCAR-00002-2026`, Cup Champion moneyline), 17
links, quotes stored (Larson 0.41/0.55, Hamlin 0.28/0.46). No trades, history, books or `fair` yet.

**OG.com, full run later the same day** (after 6244a4a on main): `db seed` added `sailgp_champ` (PR #51's schema,
never seeded on the VM; deploy runs migrations, not the seed), then F1 25 events / 64 links (20 modeled, 44
unmatched), NASCAR 1 event / 17 links, SailGP 6 events / 13 links (all new); 319 trades, 19,000 minute price rows
(from 2026-08-29), 64 book snapshots, and `fair` printed the F1 championship table (Antonelli fair 0.96 vs
0.84/0.92, the one YES call). Two API limits found on the first attempt and fixed in the same commit: `get-trades`
takes at most `count=150` (was 1000, "Invalid count"; no cursor, so a run keeps the newest 150 per instrument),
and `get-ticker-histories` refused a span of 2678400001 ms (the start clip and the end read `now` a millisecond
apart; now one read, start a second inside the 31-day cap). Log: `data/backups/og-sync-20260929.log` on the VM.

Row counts on the VM before → after (joined to `market_links` on `token_id`): links kalshi 3,793 → 19,088, og 0 →
17, polymarket 7,285; trades kalshi 37,416 → 1,910,536; hourly prices kalshi 16,083 → 187,592; book snapshots kalshi
0 → 859, polymarket 17,029.

**Undo.** Restore the backup above (`gunzip -c … | psql`), or delete `market_links` rows with `competition_id in
(3, 4, 5)` or `exchange = 'og'` and their trades, prices and books by `token_id`.

## 2026-09-28 · Kalshi F1 history pulled (2025–2026)

**Why.** To backtest and show Kalshi next to Polymarket: Polymarket has listed no F1 race since Baku, Kalshi lists
every weekend. Owner-approved; read-only Kalshi API (no orders, no portfolio calls). Backups first:
`data/backups/db/racinglines-2026-09-28-before-kalshi-history.dump`, and before the 2025 re-sync
`data/backups/db/racinglines-2026-09-28-before-kalshi-2025.dump`.

**What.** `markets --exchange kalshi sync --year 2025 --closed` and `--year 2026 --closed`, then trades and hourly
candlesticks (`--period 60`) for every event with modeled links, from each market's `open_time` to its close
(or now, for the open championships). No failures, no rate-limit errors. Settled markets older than Kalshi's
cutoff (before about August 2026) came from its `/historical` endpoints.

**Season-matching bug, fixed the same day.** `sync --closed` returns every settled event whatever `--year` is,
and `--year` chose the season markets were matched against, so the second run (2026) re-matched all 2025 markets
against 2026's races and left them unmodeled. Kalshi's data was fine (prices, trades, results, close times);
only our matching was wrong. The sync now matches each event against its own season (the ticker's `25` / `26`,
else its close date) and reads 2025's title forms (`F1 Australian Grand Prix Winner?`, `Las Vegas GP: …`,
`Gran Premio de Mexico Winner?`). Re-syncing changed no 2026 link; 2025 then got its trades and prices.

| | Rows |
|---|---:|
| Kalshi links (`market_links.exchange='kalshi'`) | 3,793 (200 events), 2,890 modeled in 150 events |
| Modeled, 2025 | win 481 · podium 441 · pole 60 · fastest lap 60 · drivers' champion 20 · constructors' champion 10 (all 24 weekends; pole and fastest lap only for the last three) |
| Modeled, 2026 | win 330 · podium 330 · top 10 330 · fastest lap 330 · pole 308 · top constructor 143 · h2h 14 · drivers' champion 22 · constructors' champion 11 (15 weekends, Australia to Azerbaijan) |
| Trades | 1,065,605 (108.9 M contracts): 247,465 in 2025 markets, 818,140 in 2026; 295 modeled markets never traded (long shots) |
| Hourly prices | 520,969, on every modeled market, 2025-02-12 to 2026-09-28 |
| Parquet (`data/archive/markets/kalshi/`, in git) | links 144 KB · prices 1.0 MB · trades 29 MB |

Not modeled, on purpose: sprint markets, props (`KXUSAF1`, `KXAFRICAF1`), and six Bahrain 2025 markets on reserve
drivers who didn't race. Kalshi quirks: `KXF1TOPCONSTRUCTOR-AUSGP26` is a second **Austria** market despite its
ticker (title and rules say Austria, it closed on 6 July; matched to Austria, settled like the other one), so
Australia 2026 has no top-constructor market; Azerbaijan 2026 has no pole market. 2025's markets opened only 2–4
days before each race and are thinner (median trades per market: win 19, podium 26, pole 49, fastest lap 5).
How Kalshi's feed differs from Polymarket's: [Data](data.md#exchange-history-kalshi-and-polymarket).

**Side effect.** The market recorder's hourly archive pass isn't per exchange: from 14:06 UTC on it moved the
stale Kalshi rows out of Postgres into new part files under `data/archive/markets/polymarket/{prices,trades}/`
(untracked in the main checkout; by 18:09 UTC, 94 files and 1.2 M rows, all `KX…` tokens). Nothing was lost:
the exports read Postgres and those files together and deduplicated, and every row in them was checked to be
in `data/archive/markets/kalshi/`; they were deleted (132 files by 19:10 UTC). Fixed the same day: the archive
pass now writes each row to its exchange's tree ([Data](data.md#exchange-history-kalshi-and-polymarket)).

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
on disk predated it. PR #8 (in the private repo).

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
