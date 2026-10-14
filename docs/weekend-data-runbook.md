# Race weekend runbook

> The checks before, during and after a race weekend on the VM: recorders, the live book, the F1 session push, and what to look at when something is quiet.

Everything on a race weekend runs on timers ([VM deploy: Timers and jobs](vm-deploy.md#timers-and-jobs-on-the-vm)):
the market recorders every 5 minutes every day, `racinglines live auto` for every F1 event whose window is open,
the signals pass every 5 minutes, and the forecast refresh after each result. The one thing a person does on an F1
weekend is keep the Mac pushing sessions. This page is the walk-through; the commands are all `vm.sh` subcommands.

!!! warning "Keep code merges out of the live window"
    A merge to `main` deploys, and the deploy pauses the timers and restarts the web app for a few seconds. It catches
    up by itself, but between sessions is still the kindest time; a staging deploy is fine any time
    ([VM deploy: Ship a change](vm-deploy.md#ship-a-change)). Live books never freeze: every update requotes until
    lights out.

## Before the weekend (Thursday)

### Step 1: the timers are on

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh status
```

```text title="What you should see"
deployed: <sha> <subject> (<when>)
<units: racinglines-web, racinglines-recorder, racinglines-mcp ... active>
<timers: racinglines-live-auto, racinglines-signals, racinglines-record-venues, racinglines-pm-sync, racinglines-schedule-sync, racinglines-forecast-refresh ...>
```
<!-- scripts/deploy/vm.sh:473: git log -1, list-units 'racinglines-*', list-timers 'racinglines-*' -->

No `PAUSED by an unfinished deploy` line. If `racinglines-live-auto.timer` is missing: `bash scripts/deploy/vm.sh live auto`.

### Step 2: the venues have listed the race and we have linked it

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh record status
bash scripts/deploy/vm.sh pm-sync status
```

The `--- tape warnings, last 24 hours` block should be empty. A line like
`WARN kalshi f1 <event key> <event name>: no links with this race (sync, then link)` means the venue listed the race
and the hourly sync hasn't linked it yet, or the venue hasn't listed it ([Market tape](market-tape.md#step-3-read-the-tape-warnings)).
<!-- scripts/vm/tape_check.sh:10 -->

### Step 3: the sessions' start times are loaded

`racinglines-schedule-sync.timer` reruns `racinglines data schedule f1` every 6 hours and writes only when a
session was added or moved (backup first). Its last passes:

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh schedule status
```

### Step 4: the Mac is ready to push sessions (F1)

F1's timing archive answers 403 to the VM, so the sessions come from the Mac
([VM deploy: push the sessions](vm-deploy.md#step-2-on-an-f1-weekend-push-the-sessions-from-the-mac)). Either
the LaunchAgent is installed (`bash scripts/deploy/f1_push_auto.sh install`, once), or start the push by hand before
FP1 and leave the Mac awake and online:

```bash title="LOCAL (Mac)"
caffeinate -i bash scripts/deploy/f1_push.sh 2026-16
```

It prints a progress line every look (at most 5 minutes apart) and stops once the race is pushed.

## During the weekend

### After each session

The push copies the session to prod and staging and starts both live steps, which ingest and price it. Check the
step's journal:

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh logs racinglines-live-auto
```

A step that is waiting prints that it is waiting for the session's data; a step with nothing due prints
`<event>: nothing new`. The Mac side's logs are `data/runs/logs/f1_push-<event>.log` and `f1_push_auto.log`.
<!-- racinglines/cli/live.py:225 -->

### Every few hours: the recorders

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh record status
```

The last block, `--- book snapshots stored per venue, per 5 minutes (UTC), last 30 minutes`, has a row per venue per
bucket. A venue missing for more than one bucket, or a `WARN` line, is worth a look at
`bash scripts/deploy/vm.sh logs racinglines-record-venues`.

### After a deploy

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh status
```

Every timer back in the list and no `PAUSED by an unfinished deploy` line. The deploy's own last lines are
`timers running (one 'active' per timer):` followed by one `active` per timer
([What a deploy does to the timers](vm-deploy.md#what-a-deploy-does-to-the-timers)).

## After the race

- **The book settles by itself** at the results update, and `live auto` drops the event a day after its results;
  nothing to turn off.
- **The F1 championship forecast** refreshes once per new race classification (`racinglines-forecast-refresh.timer`):
  `bash scripts/deploy/vm.sh forecast status` shows the pass.
- **The event report**, from the run folder: `racinglines live report live/f1/<event>.toml --pdf`
  ([Live events](live-events.md#step-4-watch-settle-report)).
- **A fantasy reset**, if the owner wants one, only after the signal window closes (a day after the race):
  `scripts/vm/reset_fantasy.sh` ([VM deploy: one-off jobs](vm-deploy.md#timers-and-jobs-on-the-vm)).

## Where the data lands

| What | Where on the VM | Notes |
|---|---|---|
| Polymarket F1 books | Postgres `market_book_snapshots`, every 60 s (`racinglines-recorder.service`) | the hourly archive pass moves cold rows to `data/archive/markets/` |
| Kalshi and OG.com books | the same table, every 5 min (`racinglines-record-venues.timer`): `kalshi:f1 og:f1 kalshi:nascar og:nascar kalshi:motogp` | sync and OG.com settle every 60 min; trades every 15 min |
| Polymarket NASCAR and MotoGP | links and books every 5 min (`racinglines-pm-sync.timer`) | |
| F1 sessions | `data/raw/f1/fastf1/<year>/`, from the Mac | the VM's own FastF1 recorder stores nothing (`fastf1: BLOCKED`) |
| The live book | `data/runs/live/<event>/` ([Kept for replay](live-events.md#kept-for-replay)) and `live_events` at settlement | settings pinned in `meta.json` at the first update |
| Backups | `data/backups/db/` | on demand (`vm.sh backup`) and each writing script's first step; no schedule yet |

??? note "Round 16 (Bahrain GP at Sepang, 2–4 October 2026): the first weekend, as it was planned"
    This page was written for round 16 and kept as the record. What was true then: the venue recorders covered Kalshi
    F1 and NASCAR and OG.com F1, NASCAR and MotoGP on race weekends only (every day since 2026-10-07); Kalshi stored
    no bid/ask; MotoGP had no calendar and a forecast stored once; Polymarket listed no MotoGP and no new F1 race
    since round 11; NASCAR and MotoGP paper history was in-sample and not refreshed. F1's private book was priced with
    a per-market loss cap (`[live.quoting] max_loss = 500.0` in `live/f1/2026-16.toml`) and head-to-head pairs from
    the last listed race (`[live.markets] h2h_from = "last_listed"`); the venue strategies A (early), C (hold) and K
    (late) ran from the signals timer every 5 minutes during book hours (2026-10-02 03:30 to 2026-10-04 07:00 UTC).
    The settings were pinned in `data/runs/live/2026-16/meta.json` at the first update (a later change needs
    `--unfreeze`). The event report and the decisions that followed are on the [F1 live test](f1-live-roadmap.md)
    page.

## Next steps

<div class="grid cards" markdown>

- **VM deploy**

    ---

    Every timer, what a deploy does to them, and the backup rule.

    [VM deploy](vm-deploy.md)

- **Market tape**

    ---

    What the recorders store and how to backfill a gap.

    [Market tape](market-tape.md)

- **Live events**

    ---

    The engine, `racinglines live`, and the F1 private book.

    [Live events](live-events.md)

</div>
