# Market tape

> What the recorders store every 5 minutes, every day, and how to backfill any gap the venues still serve.

**The tape is the business.** Every edge we claim is measured against it: the sweeps and replays trade each
exchange's recorded prices, the maker replay fills only against recorded taker trades, and paper signals and CLV
compare our fair values with the venue's prices at the time. A gap in the tape is a race we can't backtest, a fill
we can't check and a price we can't quote against. So the rule is: **record everything, all the time, and backfill
any gap the venues still serve.**

!!! warning "Order books cannot be recovered"
    No venue serves book history. A missed snapshot is lost for good, so the recorders below must never be off for
    long, and a deploy's pause costs at most one snapshot ([VM deploy](vm-deploy.md#what-a-deploy-does-to-the-timers)).

## What "the tape" is

Four tables, one row set per exchange (`market_links.exchange` tells them apart), with cold rows archived to
Parquet under `data/archive/markets/<exchange>/` ([Data: exchange history](data.md#exchange-history-kalshi-and-polymarket)):

| Table | What it holds | Can it be backfilled? |
|---|---|---|
| `market_links` | Every market we know: venue, ticker or token, race, kind, latest quote, outcome | Yes: `sync` (add `--closed` for settled markets) |
| `market_trades` | Every taker trade: time, price, size, side | Yes, as far back as the venue serves (`trades`) |
| `market_price_history` | Hourly prices (Kalshi candles, Polymarket price points, OG.com minute prices) | Yes, as far back as the venue serves (`history`) |
| `market_book_snapshots` | Order-book snapshots | **No.** No venue serves book history |

## Recording it: the 5-minute recorders

Owner rule, 2026-10-07: market prices are polled every 5 minutes, every day, not only on race weekends
(`WEEKEND_ONLY=1` restores the old gate, `scripts/vm/race_weekend.sh`). Since #91 (2026-10-08) they also store
trades every 15 minutes. On 2026-10-14 production's Postgres held book snapshots on all three venues to 04:49 UTC
(Kalshi since 2026-09-30, Polymarket since 2026-10-03, OG.com since 2026-10-08) and the hot trade window since 9 Oct
(Kalshi, OG.com) and 4 Oct (Polymarket F1); older rows are in the Parquet archive.

| Unit (VM) | Script | Covers | Each pass |
|---|---|---|---|
| `racinglines-record-venues.timer` | [`scripts/vm/record_venues.sh`](https://github.com/lalligagger/racinglines-public/blob/main/scripts/vm/record_venues.sh) | `kalshi:f1 og:f1 kalshi:nascar og:nascar kalshi:motogp` (`PAIRS`) | A book snapshot of every open market; that pair's `sync` every `SYNC_MIN` (60); OG.com `settle` every `SETTLE_MIN` (60); the last `TRADES_HOURS` (2) of trades every `TRADES_MIN` (15) |
| `racinglines-pm-sync.timer` | [`scripts/vm/pm_sync.sh`](https://github.com/lalligagger/racinglines-public/blob/main/scripts/vm/pm_sync.sh) | Polymarket F1 links; NASCAR and MotoGP (`PM_SPORTS`) links and books | F1 `sync` every pass; `PM_SPORTS` `sync` every `SYNC_MIN` (60), their books every pass; the trades of every open market every `TRADES_MIN` (15) |
| `racinglines-recorder.service` | `racinglines markets record --interval 60` | Polymarket F1 | Runs continuously: a book snapshot of every open market every 60 s, a sync every 30 min, and the hourly archive pass to Parquet for every exchange |

Every pass is additive only (`ON CONFLICT DO NOTHING` on books, upserts on links; trades deduplicated by
`uq_market_trade`), built from the read-only `racinglines markets` commands; no trading, no buy-all. One pair failing
doesn't stop the others, and the pass exits non-zero so `systemctl status` shows it. The first pass on a box backs
the database up (`data/backups/db/racinglines-before-record-venues-<UTC>.sql.gz`) and adds a `data_changes` note.

### Step 1: turn the recorders on (once)

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh record             # Kalshi and OG.com, every 5 minutes (off: vm.sh record off)
bash scripts/deploy/vm.sh pm-sync            # Polymarket, every 5 minutes (off: vm.sh pm-sync off)
```

Each prints the timer's next run (`systemctl list-timers`). `vm.sh deploy` pauses and resumes both with the other
timers; nothing else needs doing.

### Step 2: check them

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh record status
```

```text title="What you should see"
NEXT                        LEFT     LAST                        PASSED  UNIT                              ACTIVATES
<...>                                                                    racinglines-record-venues.timer   racinglines-record-venues.service
--- last passes (data/runs/logs/record-venues.log)
2026-10-01T00:05:02Z kalshi f1 books: 184 book snapshots stored (12 s)
...
--- tape warnings, last 24 hours
--- book snapshots stored per venue, per 5 minutes (UTC), last 30 minutes
  utc  | exchange | snapshots
```
<!-- scripts/vm/record_venues.sh:45-56; the log line is the example in its header (:28) -->

The last table has one row per venue per 5-minute bucket for the last 30 minutes: a venue missing from it for more
than one bucket is a recorder problem. The Polymarket side:

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh pm-sync status
```

```text title="What you should see (one line per sync)"
2026-10-03T21:30:02Z polymarket f1 sync: 4 events, 34 links upserted (8 s)
```
<!-- scripts/vm/pm_sync.sh:21 -->

### Step 3: read the tape warnings

After each sync, [`scripts/vm/tape_check.sh`](https://github.com/lalligagger/racinglines-public/blob/main/scripts/vm/tape_check.sh)
looks at every event of the sport from 3 days ago to `LEAD_DAYS` (7) ahead and prints one line per event; the
recorders log its lines, and `vm.sh record status` shows the WARN lines of the last 24 hours:

```text title="The lines tape_check.sh prints"
OK   kalshi f1 <event key> <event name>: <n> links, last sync <h> h ago
WARN kalshi f1 <event key> <event name>: no links with this race (sync, then link)
WARN kalshi f1 <event key> <event name>: <n> links, last sync <h> h ago (over STALE_HOURS=3)
OK   kalshi f1 <event key> <event name>: <n> links, all <n> links closed (a finished event: no sync to expect)
SKIP og f1: no race market on this exchange for this sport yet
```
<!-- scripts/vm/tape_check.sh:8-16 -->

A `WARN ... no links with this race` for an event in the next 7 days means the venue has listed it and we haven't
linked it, or hasn't listed it yet: run the sport's `sync` and `link` by hand, or wait for the hourly sync. Exact
keys only (owner policy): links use `market_links.race_id` foreign keys, never fuzzy matching.

## Filling gaps: the tape backfill

[`scripts/vm/backfill_tape.sh`](https://github.com/lalligagger/racinglines-public/blob/main/scripts/vm/backfill_tape.sh)
pulls every trade and hourly price the venues' own APIs still serve since `START`, for every exchange and sport the
recorders cover. Run it whenever a recorder was down or a comparison finds a gap. It was first written on 2026-10-08,
after a comparison with a third-party book feed found no Kalshi trades stored after 29 Sep, no NASCAR/MotoGP
Polymarket tape, and new F1 markets booked late.

**What it does, in order:**

1. Backs up the target database to `data/backups/db/<db>-before-backfill-tape-<UTC>.sql.gz` and checks the dump's
   trailer; if the dump is incomplete it stops before writing anything.
2. For each `exchange:sport` pair, three steps: `sync` (new market links), `trades` (every trade since `START`) and
   `history` (hourly prices since `START`: Kalshi `--period 60`, Polymarket `--fidelity 60`, OG.com minute prices
   clipped to the month it keeps).
3. Adds a `data_changes` note naming the backup, and ends with `BACKFILL-DONE (exit N)`.

The default pairs, in run order, are `kalshi:f1 kalshi:nascar kalshi:motogp og:f1 og:nascar polymarket:f1
polymarket:nascar polymarket:motogp`: 8 pairs, 24 steps. It only adds rows (upserts on the trade and price keys) and
never deletes. One step failing doesn't stop the rest; the run then exits 1, and the step's line says `FAILED` with
its last output.

| Setting | Default | Meaning |
|---|---|---|
| `TARGET` | `prod` | `prod` or `staging`: which app checkout, env file and database |
| `START` | `2026-09-01` | UTC day to backfill from |
| `PAIRS` | all 8 above | `exchange:sport` pairs to run |

### Step 1: staging first

```bash title="VM (production)"
sudo systemd-run --unit=rl-backfill-tape-staging --uid=racinglines --setenv=TARGET=staging /opt/racinglines-staging/scripts/vm/backfill_tape.sh
```

### Step 2: follow it

```bash title="VM (production)"
journalctl -u rl-backfill-tape-staging -f
```

The log is also written to `data/runs/logs/backfill-tape-<UTC>.log` in the app checkout. A single step can run for
over half an hour: on the first staging run (2026-10-08), Kalshi F1 trades stored 210,556 trades in 2,190 s and
Kalshi F1 history stored 46,094 price points in 2,144 s; the NASCAR sync took 7 s. Each `racinglines` command prints
its own `progress ...` line every 5 minutes ([`racinglines/progress.py`](https://github.com/lalligagger/racinglines-public/blob/main/racinglines/progress.py)),
and the script passes those lines to the journal as they come, so **a quiet journal for more than 5 minutes means
something is wrong**.

### Step 3: production, once staging is clean and the owner says go

```bash title="VM (production)"
sudo systemd-run --unit=rl-backfill-tape --uid=racinglines --setenv=TARGET=prod /opt/racinglines/scripts/vm/backfill_tape.sh
```

### Step 4: read the tail

Every step should have a stored count, none should say `FAILED`, and the last line should be:

```text title="What you should see"
BACKFILL-DONE (exit 0)
```

Then add the [Data changes](data-changes.md) line naming the backup.

## Next steps

<div class="grid cards" markdown>

- **VM deploy**

    ---

    Every timer on the VM, what a deploy does to them, and the backup rule.

    [VM deploy](vm-deploy.md#timers-and-jobs-on-the-vm)

- **Exchange history**

    ---

    The Parquet archive, the hot window and what the exchange-data counts mean.

    [Data: exchange history](data.md#exchange-history-kalshi-and-polymarket)

- **Kalshi history**

    ---

    What Kalshi's candles and trades endpoints serve, and how far back.

    [Kalshi history](kalshi-history.md)

</div>
