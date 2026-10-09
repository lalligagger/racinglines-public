# Market tape: what we record and how to backfill it

**The tape is the business.** Every edge we claim is measured against it: the sweeps and replays trade each
exchange's recorded prices, the maker replay fills only against recorded taker trades, and paper signals and CLV
compare our fair values with the venue's prices at the time. A gap in the tape is a race we can't backtest, a fill
we can't check and a price we can't quote against. So the rule is: **record everything, all the time, and backfill
any gap the venues still serve.**

## What "the tape" is

Four tables, one row set per exchange (`market_links.exchange` tells them apart), with cold rows archived to
Parquet under `data/archive/markets/<exchange>/` ([Data: exchange history](data.md#exchange-history-kalshi-and-polymarket)):

| Table | What it holds | Can it be backfilled? |
|---|---|---|
| `market_links` | Every market we know: venue, ticker or token, race, kind, latest quote, outcome | Yes: `sync` (add `--closed` for settled markets) |
| `market_trades` | Every taker trade: time, price, size, side | Yes, as far back as the venue serves (`trades`) |
| `market_price_history` | Hourly prices (Kalshi candles, Polymarket price points, OG.com minute prices) | Yes, as far back as the venue serves (`history`) |
| `market_book_snapshots` | Order-book snapshots | **No.** No venue serves book history; a missed snapshot is lost for good |

Because books can't be recovered, the recorders below must never be off for long.

## Recording it: the 5-minute recorders (every day, all day)

Owner rule, 2026-10-07: market prices are polled every 5 minutes, every day, not only on race weekends
(`WEEKEND_ONLY=1` restores the old gate). Since PR #91 (2026-10-08, merged into staging; prod gets it with the next
staging-to-main merge), they also store trades every 15 minutes.

| Unit (VM) | Script | Covers | Each pass |
|---|---|---|---|
| `racinglines-record-venues.timer` | [`scripts/vm/record_venues.sh`](https://github.com/lalligagger/racinglines-public/blob/staging/scripts/vm/record_venues.sh) | Kalshi F1, NASCAR, MotoGP; OG.com F1, NASCAR | Book snapshot of every open market; sync every `SYNC_MIN` (60); OG.com settle every `SETTLE_MIN` (60); last `TRADES_HOURS` (2) of trades every `TRADES_MIN` (15) |
| `racinglines-pm-sync.timer` | [`scripts/vm/pm_sync.sh`](https://github.com/lalligagger/racinglines-public/blob/staging/scripts/vm/pm_sync.sh) | Polymarket F1 links; NASCAR and MotoGP (`PM_SPORTS`) links and books | F1 sync every pass; `PM_SPORTS` sync every `SYNC_MIN`, books every pass; trades of every open market every `TRADES_MIN` |
| `racinglines-recorder.service` | `racinglines markets record --interval 60` | Polymarket F1 | Runs continuously: a book snapshot of every open market every 60 s, a sync every 30 min, and the hourly archive pass to Parquet for every exchange |

After each sync, [`scripts/vm/tape_check.sh`](https://github.com/lalligagger/racinglines-public/blob/staging/scripts/vm/tape_check.sh)
logs a `WARN` line for any event in the next 7 days with no links, or whose newest sync is older than `STALE_HOURS`
(3). Check it, and turn the recorders on or off, with:

```
# LOCAL (Mac)
bash scripts/deploy/vm.sh record status      # Kalshi/OG.com passes and tape_check lines
bash scripts/deploy/vm.sh pm-sync status     # Polymarket passes
bash scripts/deploy/vm.sh record             # turn the Kalshi/OG.com recorder on (off: vm.sh record off)
```

## Filling gaps: the tape backfill

[`scripts/vm/backfill_tape.sh`](https://github.com/lalligagger/racinglines-public/blob/staging/scripts/vm/backfill_tape.sh)
pulls every trade and hourly price the venues' own APIs still serve since `START`, for every exchange and sport the
recorders cover. Run it whenever a recorder was down or a comparison finds a gap. It was first written on
2026-10-08, after a comparison with a third-party book feed found no Kalshi trades stored after 29 Sep, no
NASCAR/MotoGP Polymarket tape, and new F1 markets booked late.

**What it does, in order:**

1. Backs up the target database to `data/backups/db/<db>-before-backfill-tape-<UTC>.sql.gz` and checks the dump's
   trailer; if the dump is incomplete it stops before writing anything.
2. For each `exchange:sport` pair, three steps:
   - `sync`: new market links;
   - `trades --since-hours H`: every trade since `START`;
   - `history`: hourly prices since `START` (Kalshi `--period 60`, Polymarket `--fidelity 60`, OG.com minute
     prices clipped to the month it keeps).
3. Adds a `data_changes` note naming the backup, and ends with `BACKFILL-DONE (exit N)`.

The default pairs, in run order, are `kalshi:f1 kalshi:nascar kalshi:motogp og:f1 og:nascar polymarket:f1
polymarket:nascar polymarket:motogp`: 8 pairs, 24 steps. It only adds rows (upserts on the trade and price keys)
and never deletes. One step failing doesn't stop the rest; the run then exits 1, and the step's line says
`FAILED` with its last output.

| Setting | Default | Meaning |
|---|---|---|
| `TARGET` | `prod` | `prod` or `staging`: which app checkout, env file and database |
| `START` | `2026-09-01` | UTC day to backfill from |
| `PAIRS` | all 8 above | `exchange:sport` pairs to run |

**How to run it** (staging first, then prod after the owner's go):

```
# VM (production) — staging
sudo systemd-run --unit=rl-backfill-tape-staging --uid=racinglines --setenv=TARGET=staging /opt/racinglines-staging/scripts/vm/backfill_tape.sh
```

```
# VM (production) — follow it
journalctl -u rl-backfill-tape-staging -f
```

```
# VM (production) — prod, once staging is clean and the owner says go
sudo systemd-run --unit=rl-backfill-tape --uid=racinglines --setenv=TARGET=prod /opt/racinglines/scripts/vm/backfill_tape.sh
```

The log is also written to `data/runs/logs/backfill-tape-<UTC>.log` in the app checkout.

**How long it takes.** A single step can run for over half an hour. On the first staging run (2026-10-08), Kalshi
F1 trades stored 210,556 trades in 2,190 s and Kalshi F1 history stored 46,094 price points in 2,144 s; the NASCAR
sync took 7 s. Each `racinglines` command prints its own `progress ...` line every 5 minutes; since PR #97 the
script passes those lines to the journal as they come, so a quiet journal for more than 5 minutes means something
is wrong. (Runs started before PR #97 only print each step's line when the step ends.)

**When it's done**, read the tail: every step should have a stored count, none should say `FAILED`, and the last
line should be `BACKFILL-DONE (exit 0)`.
