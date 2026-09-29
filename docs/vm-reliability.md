# VM reliability plan: monitoring, backups, deploys and incident runbooks

racinglines.bet moves from the owner's Mac to one Compute Engine VM, `racinglines-vm` (e2-small, 2 GB, 30 GB
disk, us-west1-b), on Wed 30 Sep, the day before round 16's book opens. Eight days later, on Thu 8 Oct, the same
box is meant to take its first outside users: invited fantasy players, through the Singapore weekend. Today
nothing tells the owner when the site is down, and nothing backs the VM up on a schedule. The Kalshi sync runs only
when someone types it, and the recorder keeps running after it stops recording. This plan closes those gaps in the
order the calendar needs them. Monitoring, backups and the Kalshi timer go live before the R16 book opens (Thu 1 Oct
20:30 PDT / Fri 2 Oct 03:30 UTC). R16 is a closed dry run. A resize decision follows on Mon 5 Oct, and an on-call
plan covers Singapore. It is the reliability part of the fantasy soft-launch set. The overview is
[Fantasy soft launch](fantasy-launch.md); the calendar, decisions and go/no-go are in the
[runbook](fantasy-runbook.md); the other parts are
[Fantasy accounts](fantasy-accounts.md), [Fantasy trading](fantasy-trading.md) and [Email setup](email-setup.md).

**Status:** draft for the owner, Tue 2026-09-29. Nothing here has run on the VM yet. The owner runs every VM step
from the paste-ready blocks below. Numbers marked *estimate* are replaced by SCOUT-1's and DRY-1's measurements.

**Assumptions.**

- The sprint window is Tue 29 Sep to Sun 11 Oct 2026. "Next weekend" is F1 R17, Singapore (sprint format), 9–11 Oct.
  R16 (2–4 Oct, the Bahrain GP at Sepang) is the closed dry run.
- PR #71 (`work/deploy-pause`) is merged first (OWNER-1). There is no live-event freeze and no `--force`: deploys
  pause the VM's timers, deploy, run a catch-up step and resume them. Between sessions is still the kindest time.
- The cutover happens Wed 30 Sep per [VM deploy](vm-deploy.md#cutover). If it slips, the P1 ops items move with it.
- "Fantasy" is paper money only. `POLYMARKET_TRADING_ENABLED` and `KALSHI_TRADING_ENABLED` are never touched.
  `vm.sh public on` is never part of the launch (DEC-8).
- Owner-facing times are in PDT with UTC in brackets; systemd `OnCalendar` lines are in UTC.

---

## Targets (DEC-18)

| Target | Value | How it is measured |
|---|---|---|
| Availability | **99%** during the soft launch | The external uptime monitor's report: a check of `https://racinglines.bet/healthz` from outside Google every 5 minutes or faster (OPS-7). The VM's own health log (OPS-2) is the second source, and it explains the failures |
| RPO (data loss) | **24 h**; **6 h** from Thu 8 Oct 18:00 PDT to Mon 12 Oct 18:00 PDT (Fri 9 Oct 01:00 to Tue 13 Oct 01:00 UTC); plus a dump before every DB-writing change, including each event's first settlement | Nightly dump 10:00 UTC (OPS-3), the 6-hourly launch-weekend dumps (a drop-in, [Launch-weekend dumps](#launch-weekend-dumps)), disk snapshot 11:00 UTC (OPS-7), `racinglines-before-<task>` dumps (CLAUDE.md), the tick's `pre-settle-<event>` dump ([Fantasy trading](fantasy-trading.md)) |
| RTO (time to restore) | **4 h** | The recovery paths below; the DB restore part is timed in the OPS-4 drill |

**The budget in minutes.** The R17 weekend window, from sign-up opening Thu 8 Oct 18:00 PDT (Fri 9 Oct 01:00 UTC)
to Sun 11 Oct 18:00 PDT (Mon 12 Oct 01:00 UTC), is 72 h: 864 samples, so 1% is 43 minutes (about 8 samples). The whole
soft launch, to Thu 22 Oct 01:00 UTC, is 312 h: 3,744 samples, so 1% is 3 h 7 min. The P4 exit criterion is
stricter still: no unplanned outage over 15 minutes.

**What counts as downtime.**

- A sample where the external check fails: not a 200 within 10 s, or `"db"` is not `"ok"`. A Cloudflare 502, 530 or
  1033 counts. So does a 503 from the app (up, but its database is not).
- The external monitor keeps sampling while the VM is down or a deploy has paused the health timer, so those minutes
  are measured, not inferred from a gap. A gap in the health log alone is not downtime; it is a finding for the
  incident log (the web app is down only for its restart during a deploy).
- Not downtime: stale data (tracked as freshness, below), an error on one page, the demo pages, `mcp.racinglines.bet`.

**What a deploy does to users.** The web app restarts for a few seconds (Cloudflare shows a 502 meanwhile).
Sessions survive because the cookie is signed with `APP_SECRET` (`racinglines/web/app.py:47`; without it every
restart picks a random secret and signs everyone out). Three things reset: the in-memory login throttle
(`_failures`, `racinglines/web/app.py:58`) and the demo sessions' overlays (`_sessions`,
`racinglines/web/demo.py:31`), and a Lab job still running is marked "interrupted: the app restarted"
(`racinglines/web/jobs.py:241-244`). SEC-1's cookie format change signs everyone out once, so it ships in a window.

---

## Current state (29 Sep)

From the repo (`deploy/vm/systemd/`, `scripts/deploy/vm.sh`, [VM deploy](vm-deploy.md)) and the 29 Sep entry in
[Data changes](data-changes.md). What is actually enabled on the VM is SCOUT-1's first finding.

### Units and restart policies

| Unit | Type | Restart | Started by | Expected on 29 Sep (SCOUT-1 confirms) |
|---|---|---|---|---|
| `racinglines-web` | simple | always, 5 s | `vm.sh start web` | Running on the VM; racinglines.bet still served by the Mac |
| `racinglines-recorder` | simple (`markets record --interval 60`) | always, 60 s | `vm.sh start` at cutover | Off on the VM (a second recorder splits the book history); running on the Mac |
| `racinglines-signals` + `.timer` | oneshot every 5 min (`OnBootSec=1min`, `OnUnitActiveSec=5min`) | none; no `TimeoutStartSec` | `vm.sh start` at cutover | Off on the VM; running on the Mac |
| `racinglines-live-f1@<event>` + `.timer` | oneshot every 5 min | none; no `TimeoutStartSec` | by hand per event | None yet; `2026-16` is enabled before Thu 1 Oct 20:30 PDT |
| `racinglines-live-dh@<event>` | simple poll loop | on-failure, 10 s | by hand per event | None (no downhill until 2027) |
| `racinglines-mcp` | simple | always, 5 s | by hand (done 28 Sep) | Running; `mcp.racinglines.bet` |
| `cloudflared` | its own unit from `cloudflared service install` | SCOUT-1 records it | step 7 of VM deploy (done 28 Sep) | Tunnel `racinglines-vm`, one connector |
| Postgres 17 (docker compose `db`) | container | `restart: unless-stopped`; docker enabled at boot | `vm.sh setup` | Running on `127.0.0.1:5433` |

### What runs unattended, and what is manual

| Unattended (after cutover) | Manual today |
|---|---|
| Web app, MCP server, tunnel, Postgres | Deploys (`vm.sh deploy`) |
| Polymarket recorder: books every 60 s, re-sync every 30 min, Parquet archive hourly | Every Kalshi command: sync, trades, books, history (U2 is open) |
| Signals every 5 min (with the FastF1 fetch and the profile venue's prices and trades) | Closed syncs, so `market_links.resolved_yes` fills in |
| F1 live step every 5 min, once the event's timer is enabled | Tape-only sports (U9's first run was by hand on 29 Sep) and OG.com |
| | Backups: only pre-change dumps by hand; the bucket copy comes from the Mac's `bucket.sh push` |
| | Settle, reconcile, scorecard and report (the Monday routine) |
| | Enabling and disabling live-event timers; env edits; reboots |

### Gaps

| # | Gap | Evidence | Effect | Fix |
|---|---|---|---|---|
| G1 | No health check, no ops alerts | `PUBLIC_PATHS = ("/login", "/static", "/racinglines101")` (`racinglines/web/app.py:53`); `racinglines/markets/alerts.py` sends market alerts only | A user finds an outage first | OPS-1, OPS-2, OPS-7 (external monitor at cutover) |
| G2 | The recorder swallows errors | `except Exception` prints and loops (`racinglines/cli/f1.py:493`); the process never exits, so `Restart=always` never acts | Books stop silently; they can't be backfilled (no historical book API) | OPS-6 |
| G3 | No Kalshi, tape or OG.com timer | U2 and the OG.com follow-ups are open ([Roadmap](todo.md#exchanges)) | Kalshi links, books and resolutions move only when someone runs a command | OPS-5 (Kalshi F1, this sprint); tapes and OG.com in NEXT-2 |
| G4 | No VM backup unit | Only hand dumps (29 Sep: `racinglines-before-history-20260929T082054Z.sql.gz`, 14.5 MB) | A disk loss loses everything since the last hand dump | OPS-3 |
| G5 | No snapshot schedule | VM deploy step 4 creates the disk without one | No point-in-time copy of the whole box | OPS-7 |
| G6 | `bucket.sh` is Mac-only, and a push overwrites the bucket's dump | `PG_BIN` is a Mac conda path (`scripts/cloud/bucket.sh:15`, used at `:31`); push replaces `db/` (`:38-39`); the default bucket is the old one (`:14`) | No VM-to-bucket path; after cutover a Mac push can replace the VM's newer dump | OPS-3, DEC-19 |
| G7 | One tunnel connector on one VM | VM deploy step 7 | VM down means site down | Open item; recovery paths B and C |
| G8 | 2 GB box, no swap | e2-small in VM deploy's settings | OOM kills when steps overlap | OPS-7 (swap), DEC-17 (resize) |
| G9 | `--year 2026` hard-coded | `racinglines/cli/f1.py:126` (`pm-record`), `:72` (`pm-sync`); `racinglines/cli/markets.py:158` (Kalshi `sync`) | From January the recorder's 30-minute sync never sees 2027 events | A dated item before 1 Dec (Data freshness) |
| G10 | Oneshot steps have no timeout | `racinglines-signals.service` and `racinglines-live-f1@.service` set no `TimeoutStartSec`; systemd's default for oneshot is none | A hung step stops its timer (it stays `activating`, not failed, so the failed-unit check misses it). Every deploy then waits 5 minutes and gives up (PR #71) | OPS-6 (signals 45 min, live-f1@ 20 min); OPS-2's `activating` check |
| G11 | Logs uncapped | No journald or docker log settings in `deploy/vm/` | Disk fills slowly | OPS-6 (docker), OPS-7 (journald) |
| G12 | A rollback past a migration fails | `deploy/vm/update.sh:26` always runs `alembic upgrade head`; older code can't find the DB's revision | The rollback deploy stops, and PR #71 leaves the timers paused | OPS-8 |
| G13 | Secrets exist only on the VM | `/etc/racinglines.env` is in neither git nor the bucket | A rebuild can't get them | OPS-7: a copy in the owner's password manager |
| G14 | In-memory state resets on restart | Throttle, demo overlays, Lab jobs (Targets above) | A deploy resets them | Accepted; deploy in windows |
| G15 | Pooled DB connections go stale after a Postgres restart | `create_engine(database_url(url), future=True)` with no `pool_pre_ping` (`racinglines/db/config.py:24`) | After an OOM kill, a dockerd upgrade or OPS-6's container recreate, users get 500s until each stale connection is dropped | OPS-1 |

---

## Deploys after PR #71

### How a deploy works now

`bash scripts/deploy/vm.sh deploy [ref]`, run on the Mac:

1. Lists the VM's active `racinglines-*.timer` units (live-event steps and signals today; after this plan also health,
   backup, kalshi-sync and fantasy), plus any left in `/var/lib/racinglines/deploy-paused` by an earlier deploy.
2. Writes that list to `/var/lib/racinglines/deploy-paused`, stops the timers, and waits up to 5 minutes for a step
   already running. If one is still running, or the connection drops, nothing is deployed and the timers resume.
3. Runs `deploy/vm/update.sh <ref>`: checkout, `pip install`, `docker compose up -d --wait db`,
   `alembic upgrade head`, `racinglines db seed`.
4. Installs the unit files, runs `daemon-reload`, and restarts web, recorder and MCP (`try-restart`: only those
   already running).
5. Runs each live event's catch-up step (up to 5 minutes), starts the timers again and deletes the paused file.
6. Runs the smoke check on the VM against `http://127.0.0.1:8000`.

If `update.sh` fails, the timers stay paused on purpose, so no step runs on a half-updated checkout. Fix it and
deploy again; `vm.sh status` prints a `PAUSED by an unfinished deploy` line while the file exists. A running
downhill loop gets a warning, not a pause. `--force` is gone (PR #71 ignores it with a message). The pause logic
lives in the Mac's copy of `vm.sh`, so `git pull` main before deploying.

A step still running after the 5-minute wait blocks every deploy, a rollback included. The steps that can run long
are the backup (up to 60 minutes, from 10:00 UTC), signals (45) and kalshi-sync (15, OPS-5). [Bad deploy](#bad-deploy)
has the block that finds and stops the blocking step.

The new timers are paused too. The health timer takes no samples during a deploy; the dead-man grace (20 minutes)
covers the pause, and the external monitor, which no deploy pauses, still sees the site. Backup and kalshi-sync use `OnCalendar` with `Persistent=true`, so a slot missed while paused runs
as soon as the timer resumes. The fantasy timer is monotonic (every 10 minutes, [Fantasy trading](fantasy-trading.md)),
so it runs again soon after it resumes. A deploy that fails and leaves the timers paused also stops the health
timer, and then the dead-man is what alerts.

### Deploy windows

Deploys are allowed at any time; these are the kindest windows. Outside them the web restart lands on a session or a
book update. These tables are the single operational copy: other docs link here rather than repeat them. They leave an
extra 30 minutes after the FP2 and Quali updates, and no deploy lands between sign-up opening (Fri 9 Oct 01:00 UTC)
and the book opening.

**R16 (closed dry run).** Sessions: FP1 Fri 2 Oct 04:30 UTC, FP2 08:00, FP3 Sat 3 Oct 04:30, Quali 08:00, Race Sun
4 Oct 07:00, results about 10:00 ([F1 live test](f1-live-roadmap.md#2-the-event)).

| Window | UTC | PDT |
|---|---|---|
| Before the book opens | until Fri 2 Oct 02:30 | until Thu 1 Oct 19:30 |
| *Avoid:* book opens, FP1, FP2 and their updates | Fri 2 Oct 02:30 – 10:30 | Thu 1 Oct 19:30 – Fri 2 Oct 03:30 |
| W1 | Fri 2 Oct 10:30 – Sat 3 Oct 03:30 | Fri 2 Oct 03:30 – 20:30 |
| *Avoid:* FP3, Quali and their updates | Sat 3 Oct 03:30 – 10:30 | Fri 2 Oct 20:30 – Sat 3 Oct 03:30 |
| W2 | Sat 3 Oct 10:30 – Sun 4 Oct 05:00 | Sat 3 Oct 03:30 – 22:00 |
| *Avoid:* race and results | Sun 4 Oct 05:00 – 11:00 | Sat 3 Oct 22:00 – Sun 4 Oct 04:00 |
| W3 | from Sun 4 Oct 11:00 | from Sun 4 Oct 04:00 |

**R17 (soft launch).** Book opens Fri 9 Oct 07:30 UTC; FP1 08:30, SQ 12:30, Sprint Sat 10 Oct 09:00, Quali 13:00,
Race Sun 11 Oct 12:00, results about 15:00 UTC.

| Window | UTC | PDT |
|---|---|---|
| Before the soft launch | until Fri 9 Oct 00:00 | until Thu 8 Oct 17:00 |
| *Avoid:* sign-up opens, book opens, FP1, SQ | Fri 9 Oct 00:00 – 14:00 | Thu 8 Oct 17:00 – Fri 9 Oct 07:00 |
| W1 | Fri 9 Oct 14:00 – Sat 10 Oct 08:00 | Fri 9 Oct 07:00 – Sat 10 Oct 01:00 |
| *Avoid:* Sprint, Quali | Sat 10 Oct 08:00 – 15:00 | Sat 10 Oct 01:00 – 08:00 |
| W2 | Sat 10 Oct 15:00 – Sun 11 Oct 10:00 | Sat 10 Oct 08:00 – Sun 11 Oct 03:00 |
| *Avoid:* race, results, settlement | Sun 11 Oct 10:00 – 16:00 | Sun 11 Oct 03:00 – 09:00 |
| W3 | after Sun 11 Oct 16:00 | after Sun 11 Oct 09:00 |

### The migration guard (OPS-8)

OPS-8 turns every VM migration into an explicit, backed-up owner step, as CLAUDE.md requires. It builds on PR #71
and must merge before ACC-1 (`fantasy_schema_v1`).

| Case | What `vm.sh deploy` does |
|---|---|
| The target sha adds no Alembic revision | Deploys as today, but runs no `alembic upgrade` |
| The target adds revisions the DB lacks, no `--migrate` | Refuses **before anything is paused**, and names the revisions |
| The target adds revisions, with `--migrate` | Dumps first to `data/backups/db/racinglines-before-deploy-<sha>-<UTC>.sql.gz` (through `docker compose exec`), writes a `data_changes` row (`racinglines db changes --add`) naming the dump and the `alembic` from and to, then upgrades. It prints the paste-ready `docs/data-changes.md` line |
| The DB is ahead of the target (a rollback past a migration) | Warns and deploys without running `alembic`. The fantasy schema is additive, so older code runs on it. If it doesn't, see [Bad migration](#bad-migration) |

`--migrate` works before or after the ref (`vm.sh deploy --migrate`, `vm.sh deploy <sha> --migrate`). After the
on-VM smoke, OPS-8 also runs the smoke check through Cloudflare from the Mac. That check confirms `/healthz`
reports the deployed sha.

!!! warning "Owner sign-off"
    A migration against the VM needs the owner's explicit sign-off in the same conversation turn. Claude sessions
    hand over the block; the owner runs it. The migration is tried on a restored copy first (OPS-4, ACC-2).

### Smoke through Cloudflare (OPS-9)

`scripts/deploy/smoke.sh` stays GET-only, and its demo checks are unchanged. OPS-9 adds:

- `/healthz` returns 200 with `"db": "ok"`, and the freshness fields are within the thresholds below (parsed with
  `python3`, which both the Mac and the VM have).
- `/terms`, `/privacy` and `/rules` return 200, and `/signup` returns 200 when `RACINGLINES_SIGNUP` is not `off`.
  These checks sit behind smoke arguments (new; OPS-9 names them) that stay off until LEGAL-1 and ACC-3 are
  deployed. Otherwise every deploy before them would fail its smoke. The go/no-go runs smoke with them on.

### Rollback by sha

Write the running sha into the deploy log before every deploy (`vm.sh status` prints `deployed: <sha>`). A bad
deploy is undone with `bash scripts/deploy/vm.sh deploy <previous sha>`, then a `git revert` of the merge on main, so
the next plain deploy doesn't bring it back. Blocks: [Bad deploy](#bad-deploy).

### `vm.sh public on` is never part of the launch (DEC-8)

`vm.sh public on` opens plain-HTTP tcp:8000 to the internet, around Cloudflare. It gives no TLS, no Turnstile and no
rate limits, and clients can spoof the `CF-Connecting-IP` header that the throttle trusts (`client_ip`,
`racinglines/web/app.py`). The launch switch is `RACINGLINES_SIGNUP=invite` in `/etc/racinglines.env`. OWNER-4
confirms it is off at cutover, and the go/no-go checks again: no firewall rule allows tcp:8000, and
`racinglines-web` listens on `127.0.0.1` only (blocks under OWNER-4 below). Running it at all needs the owner's
explicit sign-off in the same turn.

---

## Monitoring and alerting (OPS-1, OPS-2, OPS-7)

Four layers, each catching what the one before can't:

| Layer | Catches | Misses | Owner |
|---|---|---|---|
| External uptime monitor (UptimeRobot or Better Stack, free tier), outside Google | `https://racinglines.bet/healthz` not 200 from the internet, every 5 minutes or faster: VM down, tunnel or Cloudflare down, web down, DB down (503). First alert about 5–10 minutes after the failure. Its report is the availability number | Stale data, disk, memory, backups | OPS-7, at the cutover (Wed 30 Sep) |
| `racinglines-health.timer` on the VM (every 5 min) | App, DB, tunnel (the check goes out through Cloudflare), freshness, disk, memory, backups, config, hung steps | The VM itself being down or its network gone | OPS-2 |
| Healthchecks.io dead-man (`RACINGLINES_HEALTHCHECK_PING_URL`) | No ping for 25 minutes: the health timer itself stopped (paused by a failed deploy, VM down, network down) | Nothing on the app level; slow by design, because the external monitor covers the site | OPS-7 |
| Cloudflare tunnel health notification | Tunnel `racinglines-vm` degraded or down | App-level faults | OPS-7, at the cutover |

Every alert goes to the owner's phone (ntfy) or Gmail, never to an `@racinglines.bet` address, because a DNS or
Proton problem must not hide an ops alert.

### `/healthz` (OPS-1)

New: `racinglines/web/health.py` (a router included by `racinglines/web/app.py`), with `/healthz` added to
`PUBLIC_PATHS`. It returns 200 when the DB answers and 503 otherwise. Stale data does not change the status code:
the health timer judges ages, so an uptime probe sees the app as up. The payload is computed at most every 15
seconds and cached. It carries `Cache-Control: no-store`, and it has no secrets, no user counts, no switch states,
no hostnames or IPs. The handler is `async` and serves the cached payload without a worker thread; only the refresh
runs the `SELECT 1` off the event loop. So a burst that fills the sync request threadpool slows the pages, not
`/healthz`, and doesn't raise a false P1.

OPS-1 also fixes the engine (G15): `get_engine` in `racinglines/db/config.py` sets `pool_pre_ping=True`,
`pool_recycle=1800`, and an explicit `pool_size=10`, `max_overflow=10` (the defaults are 5 and 10). Postgres's default
`max_connections` of 100 covers web, MCP, the recorder and the timers at that size. Test (`tests/test_health.py`): the
engine carries those options.

| Field | Meaning | Source |
|---|---|---|
| `ok` | `true` when `db` is `ok` | |
| `db` | `ok`, or `error` (a `SELECT 1` with a 2 s timeout) | Postgres |
| `sha` | Deployed git sha (12 characters), read once at start-up | `/opt/racinglines` checkout |
| `started_at`, `now` | Process start and response time, UTC | |
| `ages_s.recorder` | Seconds since the recorder's last good loop | `data/runs/heartbeat/recorder` (new, OPS-6); until then `max(market_book_snapshots.ts)` |
| `ages_s.kalshi_sync` | Seconds since the last Kalshi sync | `data/runs/heartbeat/kalshi-sync` (new, OPS-5); until then `max(market_links.synced_at)` for `exchange = 'kalshi'` |
| `ages_s.signals` | Seconds since the last successful signals run | `data/runs/heartbeat/signals` (new, OPS-6) |
| `ages_s.fantasy_tick` | Seconds since the last fantasy tick | `data/runs/heartbeat/fantasy-tick` (new, SETTLE-1) |
| `disk_pct` | Root filesystem used, % | `shutil.disk_usage("/")` |

An age is `null` when its unit isn't installed yet. The heartbeat directory `data/runs/heartbeat/` (under
`RACINGLINES_DATA`) is new; each writer touches its file after a successful run. The plan's OPS-5 check says
"updated_at"; the column is `market_links.synced_at` (`racinglines/db/models.py:301`).

Example response (illustrative values):

```json
{"ok": true, "db": "ok", "sha": "1a2b3c4d5e6f", "started_at": "2026-10-02T03:12:09Z", "now": "2026-10-02T03:40:00Z",
 "ages_s": {"recorder": 41, "kalshi_sync": 812, "signals": 133, "fantasy_tick": null}, "disk_pct": 38}
```

Tests (`tests/test_health.py`, new): 200 with every field; 503 when the DB is unreachable; no auth needed; only the
listed keys (a whitelist test); the 15 s cache. Verify: `python -m pytest tests/test_health.py -m "not live"`.

### The health timer (OPS-2)

New code: `racinglines/ops/health.py`, plus the `health` subcommand in `racinglines/cli/ops.py`. OPS-3 creates
`racinglines/ops/__init__.py` and `racinglines/cli/ops.py` and adds `ops` to `GROUPS` in
`racinglines/cli/__init__.py:20` (without it `racinglines ops` prints the usage and exits 2, `:28-30`). OPS-2
branches from `work/ops-3` and adds its `health` subcommand to that file, so the two branches don't both add the
file, and OPS-3 merges first. `racinglines ops health`
prints the findings; `--alert` also pushes and pings. The command exits 0 whenever the check itself ran, so findings
never turn the unit into a failed unit. It imports no pandas or numpy (target: under 120 MB).

```ini
# deploy/vm/systemd/racinglines-health.service (new, OPS-2)
[Unit]
Description=racinglines ops health check
After=network-online.target docker.service

[Service]
Type=oneshot
User=racinglines
WorkingDirectory=/opt/racinglines
EnvironmentFile=/etc/racinglines.env
ExecStart=/opt/racinglines/.venv/bin/racinglines ops health --alert
TimeoutStartSec=2min
```

```ini
# deploy/vm/systemd/racinglines-health.timer (new, OPS-2)
[Unit]
Description=racinglines ops health check every 5 minutes

[Timer]
OnCalendar=*-*-* *:00/5:00 UTC
AccuracySec=30s

[Install]
WantedBy=timers.target
```

**Checks and thresholds.**

| Check | How | Alert when | Severity |
|---|---|---|---|
| External `/healthz` | GET `$RACINGLINES_URL/healthz` (https://racinglines.bet), 10 s timeout | Not 200 or `db` not `ok`, on 2 runs in a row | P1 |
| Loopback `/healthz` | GET `http://127.0.0.1:8000/healthz` | The same | P1 (external fails with loopback OK: "unreachable through Cloudflare") |
| Failed units | `systemctl list-units --state=failed 'racinglines-*' 'cloudflared*'` | Any | P1 for web and cloudflared; P2 for the rest |
| Hung steps | `systemctl list-units --state=activating 'racinglines-*'` and each unit's `ActiveEnterTimestampMonotonic` | Activating longer than its expected run: health 3 min, kalshi-sync 15, fantasy 15 (its `TimeoutStartSec=15min`), live-f1@ 15, signals 30, backup 45 | P2 (it also blocks deploys) |
| Recorder | `ages_s.recorder` | Over 5 min | P2 |
| Kalshi sync | `ages_s.kalshi_sync` | Over 35 min | P2 |
| Closed sync | `data/runs/heartbeat/closed-sync` | Over 26 h | P2 |
| F1 live step | Age of `latest.json` in the run folder of each enabled `racinglines-live-f1@<event>.timer` | Over 15 min while the timer is enabled | P2 |
| Signals | `ages_s.signals` | Over 15 min, inside the weekend window only (4 days before the race to 24 h after: `WEEKEND_LEAD`, `WEEKEND_TAIL`, `racinglines/pipelines/signals.py:66-67`) | P2 |
| Fantasy tick | `ages_s.fantasy_tick` | Over 30 min | P2 |
| Disk | `/` used | 80% or more (P2); 90% or more (P1) | P2 or P1 |
| Memory and swap | `/proc/meminfo`; the `oom_kill` counter in `/proc/vmstat` | MemAvailable under 10% on 2 runs; swap over 50% used; any new OOM kill | P2 |
| Backup | Newest `racinglines-nightly-*` dump and `data/runs/heartbeat/backup` (written after the bucket upload) | Over 26 h | P2 |
| Mail | `activity_log` rows for failed sends in the last hour (MAIL-1's action `mail_failed`, [Email setup](email-setup.md); `n/a` until MAIL-1 ships) | 3 or more | P2 |
| Unsettled | Fantasy book markets and positions still open 24 h after their race (`racinglines/fantasy/settle.py`, SETTLE-1) | Any | P2, pushed by the tick itself, once per item per day ([Fantasy trading](fantasy-trading.md)); the health check records the count and doesn't push it again |
| Config | The service's own environment and the filesystem | `APP_SECRET` empty; a trading flag present; `racinglines-web.service.d/public.conf` present; web listening beyond `127.0.0.1` | P1 |
| Reboot required | `/var/run/reboot-required` | Exists | Info, once a day |

Each check reports `ok`, `bad` or `n/a` (unit or table not there yet), so the timer can ship before the fantasy code.
The health log is new: `data/runs/logs/health/<YYYY-MM-DD>.jsonl`, one line per run. Each line holds the time, both
HTTP results with their latency, `sha`, every age, disk %, memory, swap, the OOM count, per-unit `MemoryCurrent`,
failed units and the findings. DRY-2 and REPORT-1 compute availability from it.

**Pushes.** `racinglines/markets/alerts.py` `deliver()` gains a topic argument (default `RACINGLINES_NTFY_TOPIC`,
unchanged for market alerts) and a click URL; `_ntfy` hard-codes `/markets/polymarket` today
(`racinglines/markets/alerts.py:130`). Ops pushes go to `RACINGLINES_OPS_NTFY_TOPIC` with `mac=False`. P1 uses ntfy
priority 5 (urgent), P2 priority 4, info priority 3.

**De-dupe (1 hour).** A check alerts when it turns bad, again once an hour while it stays bad, and sends one
"recovered" push when it clears. The state lives in `data/runs/heartbeat/health-state.json` (new).

**Dead-man.** At the end of each run the service pings `RACINGLINES_HEALTHCHECK_PING_URL`, or `<url>/fail` when any
P1 is open, so P1s also reach Gmail through Healthchecks.io. The Healthchecks.io check uses a 5-minute period and a
20-minute grace: a deploy pauses the timer for up to about 15 minutes (a 5-minute wait, the update, and up to 5
minutes of catch-up). The long grace is acceptable because the dead-man no longer detects a site outage; the external
monitor does, within about 5–10 minutes. A shorter grace would need `vm.sh deploy` to pause the check through the
Healthchecks.io API, with an API key on the Mac: not worth it this sprint.

Tests (`tests/test_ops_health.py`, new; `tests/test_alerts.py` extended): each check's ok, bad and n/a (the hung-step,
closed-sync, live-step and mail checks included); the weekend-window rule; severity; de-dupe (suppressed within the hour, repeated after it, recovery once); ping versus
`/fail`; exit 0 with findings; the config checks. No network: `httpx` is mocked. Verify:
`python -m pytest tests/test_ops_health.py tests/test_alerts.py -m "not live"`. On the VM, stop the recorder for 15
minutes in a quiet window and the phone gets the P2, then the recovery ([Test alert](#test-alert)).

### Sample alert

```text
racinglines P1 · site down through Cloudflare
External https://racinglines.bet/healthz: timeout after 10 s on 2 runs (since 08:05 UTC).
Loopback /healthz: 200, db ok, sha 1a2b3c4d5e6f. cloudflared: active.
Likely the tunnel or Cloudflare, not the app. Runbook: docs/vm-reliability.md, "Site down".
```

Every push names the check, its value and threshold, when it turned bad, and the runbook heading.

### On-call (R16, R17)

| | R16 closed dry run (Thu 1 – Sun 4 Oct) | R17 soft launch (Thu 8 – Sun 11 Oct) |
|---|---|---|
| Who | The owner | The owner; a Haiku scout reads logs on request |
| P1 response | Next waking hour. Overnight PDT sessions run unattended; nobody outside is using the site | Within 30 min, 07:00–23:00 PDT. Overnight (FP1 01:30, SQ 05:30 Fri; Sprint 02:00, Quali 06:00 Sat; Race 05:00 Sun, all PDT) only if the owner lets ntfy's urgent priority through Do Not Disturb |
| P2 response | Same day | Within 2 h, 07:00–23:00 PDT |
| Watch live | Book opens Thu 20:30 PDT; results Sun about 03:00 PDT | Sign-up opens Thu 18:00 PDT; book opens Fri 00:30 PDT; results Sun about 08:00 PDT; everything settled or queued by Sun 18:00 PDT |
| Deploys | The R16 windows only | The R17 windows only |
| Off switch | Not needed (no sign-up) | `RACINGLINES_SIGNUP=off` and `RACINGLINES_FANTASY=0`, then restart web ([runbook off switch](fantasy-runbook.md#off-switch)) |

---

## Data freshness

| Feed | Unit | Cadence | Freshness signal | Alert |
|---|---|---|---|---|
| Polymarket order books | `racinglines-recorder` | Every 60 s | `ages_s.recorder` | Over 5 min |
| Polymarket F1 links (new markets, prices) | The recorder's re-sync (`--sync-every 30`); new-market pushes go to `RACINGLINES_NTFY_TOPIC` | Every 30 min | `market_links.synced_at` | Covered by the recorder check |
| Parquet archive (`data/archive/markets/`) | The recorder | Hourly | "archived" journal line | None |
| Kalshi F1 open events: links, trades, books (U2) | `racinglines-kalshi-sync` (new, OPS-5) | Every 30 min | `ages_s.kalshi_sync` | Over 35 min |
| Closed sync, Kalshi and Polymarket (`resolved_yes`) | `racinglines-kalshi-sync` | Daily, in the 20:05 UTC run | `data/runs/heartbeat/closed-sync` (new) | Over 26 h |
| Signals, with the FastF1 fetch | `racinglines-signals.timer` | Every 5 min | `ages_s.signals` | Over 15 min in the weekend window |
| F1 live step | `racinglines-live-f1@<event>.timer` | Every 5 min, live weekends | The run folder's `latest.json` | Over 15 min while the timer is enabled; failed or hung unit |
| Fantasy tick: close, settle, stats | `racinglines-fantasy` (new, SETTLE-1) | Every 10 min | `ages_s.fantasy_tick` | Over 30 min |
| Nightly backup | `racinglines-backup` (new, OPS-3) | Daily 10:00 UTC | `data/runs/heartbeat/backup` | Over 26 h |
| Live venue books for fantasy fills | None: fetched per order (EXCH-1, `racinglines/markets/books.py`) | 10 s cache | Refused above 30 s | Not a timer |
| NASCAR, MotoGP, IndyCar tapes; OG.com | None (U9, OG.com follow-ups) | By hand | None | After the sprint: NEXT-2 |

**Polymarket recorder.** `racinglines markets record --interval 60` snapshots every open, modeled Polymarket market:
season-long markets and races not yet run (`snapshot_books`, `racinglines/markets/polymarket/sync.py`). It re-syncs
F1 events every 30 minutes and moves stale rows to Parquet hourly. Books are the one feed that can't be backfilled.
Prices and trades can (`racinglines markets history`, `trades`).

**Kalshi sync (OPS-5, U2).** It must run before the R16 book opens: Kalshi has listed 7 R16 events since 28 Sep. The
VM reached Kalshi's live API on 29 Sep (the tape-only sync in [Data changes](data-changes.md)), so U2's reachability
check is done.

```ini
# deploy/vm/systemd/racinglines-kalshi-sync.service (new, OPS-5)
[Unit]
Description=racinglines Kalshi sync: F1 open events every 30 minutes, closed sync daily
After=network-online.target docker.service

[Service]
Type=oneshot
User=racinglines
WorkingDirectory=/opt/racinglines
EnvironmentFile=/etc/racinglines.env
# a new subcommand in racinglines/cli/markets.py; "tick" is a proposed name, OPS-5 fixes it
ExecStart=/opt/racinglines/.venv/bin/racinglines markets --exchange kalshi tick
TimeoutStartSec=15min
```

```ini
# deploy/vm/systemd/racinglines-kalshi-sync.timer (new, OPS-5)
[Unit]
Description=racinglines Kalshi sync every 30 minutes

[Timer]
OnCalendar=*-*-* *:05,35:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

What each run does:

1. The Kalshi F1 sync (links, quotes). This is the existing `markets/kalshi/sync.py` path, with the year taken from
   the clock, not the `2026` default.
2. Trades and books for open F1 race events only; `trades` and `books` without `--events` take every F1 event today.
3. Once a day, in the 20:05 UTC run (13:05 PDT; after every R16 and R17 session and its results, and inside a
   deploy window), the closed sync for both venues (the existing `markets --exchange kalshi sync --closed` and
   `markets sync --closed` paths). A fixed slot, not "when the stamp is older than 23 h", so a long run never lands
   at an unpredictable time and blocks a deploy. If that run was missed (VM down, paused), the next run catches up
   when the stamp is over 26 h old. OPS-5 times the closed sync on the VM; if it needs more than 10 minutes, it moves
   to a unit of its own (a new name, raised with the owner) instead of stretching `TimeoutStartSec`. Near
   settlement, SETTLE-1's on-demand closed sync covers the gap between results and 20:05 UTC.
4. The heartbeats.

On an HTTP 429 the run stops and exits non-zero with the reason, with no retry storm; the next run is 30 minutes
later. Tests (`tests/test_cli_markets.py`, new): open-event selection, the 20:05 UTC slot and the 26 h catch-up, a
429 exits non-zero, the year from the clock. Verify on the VM: `journalctl -u racinglines-kalshi-sync` shows a run every 30 minutes, and the
`KXF1RACE-BAH26` links have `synced_at` under 35 minutes old. U2 is ticked in `docs/todo.md`.

**Signals and FastF1.** The signals timer runs every 5 minutes all the time. Inside the weekend window it fetches
FastF1 when a finished session's data is missing, plus the profile venue's prices and trades
(`racinglines/pipelines/signals.py`, step 1). Between weekends nothing fetches FastF1. The F1 live step waits for
the signals stage run, so a late FastF1 archive delays that update and nothing else. R16's window runs Wed 30 Sep
07:00 UTC to Mon 5 Oct 07:00 UTC; R17's runs Wed 7 Oct 12:00 UTC to Mon 12 Oct 12:00 UTC.

**Fantasy tick.** `racinglines-fantasy.timer` runs `racinglines fantasy tick` every 10 minutes. SETTLE-1 defines
the unit ([Fantasy trading](fantasy-trading.md)) and writes `heartbeat/fantasy-tick` after each tick. It is
enabled once SETTLE-1 is deployed, before the staging rehearsal (STAGE-1), with a backup first.

**OPS-6 changes.**

- The recorder loop (`racinglines/cli/f1.py`, `pm-record`) counts consecutive failed loops. After 10 (about 10
  minutes at `--interval 60`) it exits 1, and `Restart=always` restarts it 60 s later. A good loop resets the count
  and touches `heartbeat/recorder`. What it records does not change. Test: `tests/test_recorder_loop.py` (new).
- `racinglines-signals.service` gets `TimeoutStartSec=45min` and an `ExecStartPost=` that touches
  `heartbeat/signals`. A hung run is killed instead of stopping the timer and blocking deploys.
- ⚠️ `racinglines-live-f1@.service` (a live-event unit) gets `TimeoutStartSec=20min`, one line. A normal step, catch-up
  included, takes under 5 minutes; a hung one is killed, shows as failed, and the next timer tick runs (the run
  folder's lock stops overlaps). OPS-6's branch is ready Wed 30 Sep; it is merged and deployed Mon 5 Oct after
  OWNER-5 (runbook P2 step 0), so R16 runs on the unchanged units and R17 is the first event with the timeout.
- `deploy/vm/compose.override.yml`: the `db` service logs with `json-file`, `max-size: 10m`, `max-file: 3`.
  ⚠️ Compose recreates the Postgres container once to apply it, on the first `update.sh` after the merge
  (`docker compose up -d --wait db`). That deploy restarts the database for a few seconds, so ship it in a window.
- The journald cap is a host setting, not a repo file: it is an OPS-7 owner block.

**`--year 2026` rollover (January).** The recorder's re-sync and the Kalshi `sync` default to 2026 (G9). Polymarket
and Kalshi may list 2027 championship markets in December. Before **Tue 1 Dec 2026**, change those defaults to the
current year, or pass `--year` in the units. New code (OPS-5, SETTLE-1) takes the year from the clock.

---

## Backups and restore (OPS-3, OPS-4, DEC-19)

### What is kept where

| Layer | What | When | Where | Kept |
|---|---|---|---|---|
| Nightly dump | Whole DB, plain SQL gzipped | 10:00 UTC (03:00 PDT) | `data/backups/db/racinglines-nightly-<UTC>.sql.gz` on the VM, and `gs://$RACINGLINES_GCS_BUCKET/db/nightly/` | 7 on disk; 35 days in the bucket |
| Latest copy | The newest nightly, **scrubbed of player data** (below) | After each nightly | `gs://$RACINGLINES_GCS_BUCKET/db/racinglines.sql.gz` + `db/manifest.json` (what `bucket.sh restore`, the Mac and cloud sessions read) | Overwritten; old versions 30 days |
| Launch-weekend dump | Whole DB, as the nightly | 04:00, 16:00 and 22:00 UTC as well, from Thu 8 Oct 16:00 to Tue 13 Oct 04:00 UTC | Same files and prefix as the nightly | As the nightly (so about 42 h on disk that weekend) |
| Pre-change dump | Whole DB, before a DB-writing change | Before migrations, restores, re-settles, each event's first settlement (`pre-settle-<event>`, taken by the tick), launch steps | `data/backups/db/racinglines-before-<task>-<UTC>.sql.gz` on the VM, and `gs://…/db/before/` (new) | Never pruned automatically |
| Files | `data/runs/live`, `data/archive/markets` | Daily, after the nightly | Bucket prefixes `live/`, `archive/markets/` (the prefixes `bucket.sh` uses) | Copied, never deleted by the sync; overwritten versions 30 days (`archive/` 90 days) |
| Disk snapshot | The whole boot disk `racinglines-vm` | Daily 11:00 UTC (04:00 PDT) | GCE snapshot schedule `racinglines-daily`, stored in us-west1 | 14 days |

Not in any backup: `/etc/racinglines.env` (APP_SECRET, ADMIN_PASSWORD, later the SMTP token, the ntfy topic, the
ping URL). OPS-7 keeps a copy in the owner's password manager. The cloudflared token can be copied again from the
Cloudflare dashboard, and `vm.sh setup` regenerates the deploy key.

**Player data in backups.** From ACC-1 on, the database holds player emails, password hashes, IPs in
`activity_log`, terms and 18+ timestamps, `email_tokens` and `invite_codes`. Four rules follow:

1. **The latest copy is scrubbed.** `db/racinglines.sql.gz` is what the Mac's `bucket.sh restore` and ephemeral
   cloud sessions load, so OPS-3 writes it without player data. It carries no rows from `email_tokens`,
   `invite_codes` and `activity_log`, and every `users` row keeps its id, handle, role and account type, with
   `email`, `password_hash` and `prefs` blanked. The `users` rows can't simply be left out: `house_bets`,
   `season_members` and the ledger reference them, and a plain-SQL load adds those foreign keys after the data.
   OPS-3 picks the mechanism, for example a sectioned dump (pre-data, data with the `users` rows written through a
   scrubbing `SELECT`, post-data) under one exported snapshot. Its test loads the scrubbed file with
   `ON_ERROR_STOP` and greps it for `@`. The manifest says `"scrubbed": true`. The full dumps (`db/nightly/`,
   `db/before/`) stay whole, because they are what a production restore needs. Only the owner's account and the VM's
   service account read them; the cloud sessions' credentials are the open item under DEC-19.
2. **The bucket is locked down.** Uniform bucket-level access and public access prevention are on (a check and fix in
   [Bucket lifecycle](#bucket-lifecycle)).
3. **Retention is stated.** A deleted account's data stays in backups for up to 35 days (nightly dumps in the
   bucket), plus 30 days of overwritten object versions, plus 14 days of disk snapshots. LEGAL-1's `/privacy` page
   has to say so ([Fantasy accounts](fantasy-accounts.md)).
4. **A restore re-applies deletions.** Every restore runbook here ends with a step that re-runs account deletion for
   each `account_delete` in the before-restore state that is newer than the restored dump.

### Nightly backup (OPS-3)

```ini
# deploy/vm/systemd/racinglines-backup.service (new, OPS-3)
[Unit]
Description=racinglines nightly database backup
After=network-online.target docker.service

[Service]
Type=oneshot
User=racinglines
WorkingDirectory=/opt/racinglines
EnvironmentFile=/etc/racinglines.env
ExecStart=/opt/racinglines/.venv/bin/racinglines ops backup
Nice=10
IOSchedulingClass=idle
TimeoutStartSec=60min
```

```ini
# deploy/vm/systemd/racinglines-backup.timer (new, OPS-3)
[Unit]
Description=racinglines nightly backup at 10:00 UTC

[Timer]
OnCalendar=*-*-* 10:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

`racinglines ops backup [--label <task>]` (new, `racinglines/ops/backup.py`):

1. Refuses to run when `RACINGLINES_GCS_BUCKET` is unset. `bucket.sh` would fall back to the old bucket
   (`scripts/cloud/bucket.sh:14`); the VM's service account can't write there (DEC-19).
2. Dumps with `docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6`,
   the Linux path `bucket.sh restore` already uses (`:71`), under `set -o pipefail` with `pg_dump`'s own exit status
   checked (`bucket.sh:38` has neither). No Mac `PG_BIN`. The file is `racinglines-nightly-<UTC>.sql.gz`, or
   `racinglines-before-<task>-<UTC>.sql.gz` with `--label`.
3. Checks the file: `gzip -t` passes; the decompressed stream ends with pg_dump's trailer line
   `-- PostgreSQL database dump complete` (a dump that died midway still gzips cleanly, but has no trailer); and the
   size is at least half the previous nightly (a shrinking dump alerts). A failed check deletes the file, alerts and
   exits non-zero, and nothing is uploaded.
4. Writes a manifest: `created_at`, `alembic_head`, `bytes`, `sha256`, `git_sha`, `label`, `duration_s`,
   `scrubbed`, and `source: "racinglines-vm"`. The first three match `bucket.sh`'s manifest.
5. Keeps the newest 7 nightly files on disk and never touches `racinglines-before-*`.
6. Uploads the full dump to `db/nightly/` (or `db/before/` with a label) and checks the upload's size. Only after
   that, and only for a nightly, it writes the scrubbed copy ([Player data in backups](#what-is-kept-where)), checks
   it the same way (trailer, size), and replaces `db/racinglines.sql.gz` and `db/manifest.json`.
7. Nightly only: copies `data/runs/live` and `data/archive/markets` to `live/` and `archive/markets/` with
   `gcloud storage rsync --recursive` and **without** `--delete-unmatched-destination-objects`. A partial or empty data
   folder on the VM (a rebuild, a restore before `pull` finished, a disk swap) can then never delete the bucket's
   copy of the order-book archive, which can't be backfilled. The cost is that compacted Parquet parts leave their
   hourly parts behind in the bucket: cents a month, and reads deduplicate (`store.merge`).
8. Touches `heartbeat/backup`, then prints the path and the timings.

OPS-3 also gives `bucket.sh restore` an optional dump argument (`restore --yes [gs://…/db/nightly/<file>]`, default
the latest copy) and has `vm.sh restore` pass its second argument through. Path C needs it, because the latest copy
is scrubbed. It touches `scripts/deploy/vm.sh` in a different place from OPS-8; OPS-3 merges first.

**The Mac's `bucket.sh push` guard.** After cutover the VM writes the bucket's `db/`, `live/` and `archive/markets/`.
OPS-3 changes `scripts/cloud/bucket.sh push` to read `db/manifest.json` first. When `source` is `racinglines-vm`,
push refuses those three prefixes and says to `pull` instead. Whether `runs/f1` and `raw/mtb_dh` (Mac-side inputs
today) stay pushable is OPS-3's call, stated in its PR.

Tests (`tests/test_ops_backup.py`, new): file names with and without `--label`, pruning (7 kept, `before-*` untouched),
manifest fields, refusal without a bucket, a truncated dump (no trailer) and a non-zero `pg_dump` both refused with
nothing uploaded, the latest copy replaced only after the nightly upload, the scrubbed copy has no `@` and loads with
`ON_ERROR_STOP` (on the test database), no delete flag in the rsync call, and the push guard (a fake `gcloud`).
`pg_dump` and `gcloud` are mocked except in the scrub-load test. Done when two consecutive nightly dumps are listed
in the bucket.

**If OPS-3 slips.** The snapshot schedule (at the cutover) is the first backup either way. If OPS-3 isn't deployed
by Thu 1 Oct 12:00 PDT, the owner runs the stopgap in [Fallback backup](#fallback-backup-only-if-ops-3-slips): a
full dump to `db/nightly/` once a day, without the scrub, the rsync or the manifest.

### Launch-weekend dumps

From Thu 8 Oct 16:00 UTC (09:00 PDT) to Tue 13 Oct 04:00 UTC the backup timer also fires at 04:00, 16:00 and 22:00
UTC, which makes the RPO 6 h while outside players place bets. A dump is about 15–150 MB (*estimate*) and takes
minutes. It is a drop-in, installed and removed by the owner (blocks under
[Launch-weekend backup drop-in](#launch-weekend-backup-drop-in)). On race day it adds to, and doesn't replace, the
tick's own `pre-settle-2026-17` dump, which is taken just before the first settlement write
([Fantasy trading](fantasy-trading.md)).

### GCE snapshot schedule (OPS-7)

`racinglines-daily`: daily at 11:00 UTC, an hour after the dump, so each snapshot holds the newest dump too. It keeps
14 days, keeps its snapshots if the disk is deleted, and is attached to disk `racinglines-vm`. Snapshots are
incremental and crash-consistent: Postgres recovers from one as from a power cut. Blocks:
[Snapshot schedule](#snapshot-schedule).

### Pre-change dumps (CLAUDE.md)

Before any step that writes to the database, back up first and name the dump in a `data_changes` row and a
`docs/data-changes.md` line. On the VM that is `racinglines ops backup --label <task>`. Before OPS-3 is deployed,
use the manual line from `bucket.sh restore` (`:71`). This sprint's labelled dumps are:

| Label | Before |
|---|---|
| `r16-testers` | Creating the R16 tester accounts |
| `kalshi-sync-timer` | Enabling `racinglines-kalshi-sync.timer` (it adds links on a schedule) |
| `deploy-<sha>` | `vm.sh deploy --migrate` (automatic, OPS-8) |
| `staging` | The staging rehearsal (STAGE-1) |
| `before-soft-launch` | LAUNCH-1 |
| `pre-settle-<event>` | The tick's first settlement write for each event (automatic, SETTLE-1; `pre-settle-2026-17` for R17) |
| `r16-settle` | OWNER-5, the R16 settle and reconcile (Mon 5 Oct) |
| `kalshi-sprints` | Setting `RACINGLINES_KALSHI_SPRINTS=1` for R17 (DEC-12, OWNER-9) |
| `before-r17-settle` | SETTLE-2 step 3, before the owner's settle-day writes |
| `after-r17-settle` | SETTLE-2 (after settlement, to keep the settled state) |
| `abuse-cleanup` | Revoking invites and suspending members in [Sign-up abuse wave](#sign-up-abuse-wave) |
| `resize` | OWNER-7 |
| `resettle-<event>`, `restore-<sha>` | The runbooks below |

### Restore drill (OPS-4)

`scripts/ops/restore_scratch.sh` (new) runs on the Mac:

1. Takes the newest `gs://$RACINGLINES_GCS_BUCKET/db/nightly/` dump, or a path given as its argument.
2. Downloads it to `data/backups/db/`.
3. Drops and recreates the database `racinglines_scratch` on the Mac's own Postgres, the server `DATABASE_URL` points
   at (port 5433). It refuses any target named `racinglines`. `bucket.sh restore` drops `racinglines` in place, which
   is why it isn't used.
4. Loads the dump.
5. Runs `alembic upgrade head` against the scratch database. For ACC-2 it also runs `downgrade -1` and `upgrade` again.
6. Prints row counts (`alembic_version`, `users`, `market_links`, `market_trades`, `market_book_snapshots`,
   `market_price_history`, `strategy_signals`, `paper_positions`, `house_markets`, `house_bets`, `activity_log`,
   `data_changes`, and the fantasy tables when present), then the elapsed time per step and in total.

It leaves the scratch database for comparisons; `--drop` removes it. It is the "try the migration on a restored copy
first" path for ACC-2, and the comparison path for the settlement runbook.

Timings (filled in by OPS-4 and DRY-2):

| Drill | Date | Dump | Size | Download | Load | `alembic` | Total | By |
|---|---|---|---|---|---|---|---|---|
| 1 | by Sun 4 Oct | newest nightly | | | | | | OPS-4 |
| 2 | Mon 5 Oct (ACC-2) | newest nightly + `fantasy_schema_v1` | | | | | | ACC-2 |

The Mac drill times the load step only. Path B is timed separately, on a throwaway instance booted from the newest
snapshot, before Thu 8 Oct ([Path B drill](#path-b-drill-before-thu-8-oct)):

| Drill | Date | Snapshot | Disk created | Instance booted | Postgres up | `alembic current` matches | Total | By |
|---|---|---|---|---|---|---|---|---|
| B-1 | Tue 6 Oct 16:00–18:00 UTC (09:00–11:00 PDT) | newest `racinglines-daily` | | | | | | owner |

### Recovery paths and RTO

The times are estimates until drilled. This sprint times path A's load step (OPS-4) and path B's boot from a
snapshot (drill B-1); path C is not rehearsed.

| Path | When | Steps | Expected time | Data lost |
|---|---|---|---|---|
| A. Restore the DB on the same VM | Bad migration, wrong or corrupt data | Stop writers, dump what's there, load the dump, start ([Bad migration](#bad-migration)) | 30–60 min | Everything since the dump (kept aside in the before-restore dump) |
| B. New VM from the latest snapshot | VM or disk lost, zone fine | Disk from snapshot, instance, tunnel reconnects by itself (blocks below) | 30–60 min | Since 11:00 UTC (at most 24 h) |
| C. Rebuild from scratch and the bucket | Snapshots unusable, or a different zone or provider | VM deploy steps 4–7, env from the password manager, `vm.sh restore` with the newest full nightly (it pulls the data folders first), `vm.sh start`, then the timers, backup last, smoke | 2–3 h | Since the newest nightly (at most 24 h; 6 h on the launch weekend) |

Every path ends the same way: re-apply account deletions made after the restored point (rule 4 under
[What is kept where](#what-is-kept-where)), then a `data_changes` row and a `docs/data-changes.md` line.

**Path B, LOCAL (Mac).** The snapshot carries `/etc/racinglines.env` and the cloudflared credentials, so no secret is
needed. Stop or delete the old instance first. Two recorders would split the book history, and two connectors on the
same tunnel would split traffic between two databases. ⚠️ Deleting an instance is the owner's call; `--keep-disks=all`
keeps its disk.

```sh
# LOCAL (Mac) — path B, step 1: the newest snapshots
gcloud compute snapshots list --project=racinglines --filter="sourceDisk~racinglines-vm" --sort-by=~creationTimestamp --limit=5
```

```sh
# LOCAL (Mac) — path B, step 2: ⚠️ only if the old VM is broken; its disk is kept
gcloud compute instances delete racinglines-vm --project=racinglines --zone=us-west1-b --keep-disks=all
```

```sh
# LOCAL (Mac) — path B, step 3: a disk from the snapshot, an instance with the same name, the schedule on the new disk
gcloud compute disks create racinglines-vm-r1 --project=racinglines --zone=us-west1-b --type=pd-balanced --source-snapshot=<SNAPSHOT>
gcloud compute instances create racinglines-vm --project=racinglines --zone=us-west1-b --machine-type=e2-small \
  --disk=name=racinglines-vm-r1,boot=yes,auto-delete=no --shielded-secure-boot \
  --service-account=racinglines-vm@racinglines.iam.gserviceaccount.com --scopes=cloud-platform
gcloud compute disks add-resource-policies racinglines-vm-r1 --project=racinglines --zone=us-west1-b --resource-policies=racinglines-daily
```

```sh
# VM (production) — path B, step 4, from the Mac: check and record
bash scripts/deploy/vm.sh status
bash scripts/deploy/smoke.sh https://racinglines.bet
```

Then re-apply account deletions made since the snapshot (from `activity_log` on the old disk, if it can still be read,
or from the players' requests to support@racinglines.bet), add a `data_changes` note
(`restored from snapshot <snapshot name>`) and a line in [Data changes](data-changes.md). The
boot disk is now `racinglines-vm-r1`, so change "disk racinglines-vm" in the snapshot and resize blocks to match.

**Path C.** Follow [VM deploy](vm-deploy.md) steps 4–7 on a new instance (set `RL_ZONE` for another zone). Fill
`/etc/racinglines.env` from the password manager. Run `sudo cloudflared service install <TOKEN>` with the token of
the existing tunnel `racinglines-vm` (Zero Trust > Networks > Tunnels > `racinglines-vm`); the hostnames stay on the
tunnel. Then run `vm.sh restore gs://$RACINGLINES_GCS_BUCKET/db/nightly/<newest>`: not the default, because
`db/racinglines.sql.gz` is the scrubbed copy without player logins (the dump argument is OPS-3's). `vm.sh restore`
runs `bucket.sh pull` for the data folders before it loads the dump; let it finish. Then `vm.sh start`, and enable
the timers ([Installing the new units](#installing-the-new-units)) with `racinglines-backup.timer` last, only after
the pull has finished and `data/archive/markets` holds as many files as the bucket's `archive/markets/`
(`gcloud storage ls -r … | wc -l`). Then re-apply deletions and smoke. Path C is not rehearsed this sprint (Open
items).

#### Path B drill (before Thu 8 Oct)

Drill B-1 boots the newest snapshot as a throwaway instance, `racinglines-drill`, and times it. The clone carries
production's env file and tunnel credentials, and its timers start at boot. So it gets no external IP and no service
account: it can't reach the internet (no tunnel connector, no ntfy, no pings, no venue calls) and can't write the
bucket. It is reached over IAP only. Run it in a quiet window, Tue 6 Oct 16:00–18:00 UTC (09:00–11:00 PDT).

```sh
# LOCAL (Mac) — drill B-1, step 1: the newest snapshot, the VM's network tags (IAP ssh needs them), and whether the network has a Cloud NAT
gcloud compute snapshots list --project=racinglines --filter="sourceDisk~racinglines-vm" --sort-by=~creationTimestamp --limit=1
gcloud compute instances describe racinglines-vm --project=racinglines --zone=us-west1-b --format='value(tags.items)'
gcloud compute routers list --project=racinglines --format='table(name,region,nats.list())'
```

If `routers list` shows a NAT, stop. The drill instance could then reach the internet and join the production
tunnel, so the drill needs a different design; raise it before going on.

```sh
# LOCAL (Mac) — drill B-1, step 2: a disk from the snapshot and a throwaway instance with no external IP and no service account, timed
time gcloud compute disks create racinglines-drill --project=racinglines --zone=us-west1-b --type=pd-balanced --source-snapshot=<SNAPSHOT>
time gcloud compute instances create racinglines-drill --project=racinglines --zone=us-west1-b --machine-type=e2-small \
  --disk=name=racinglines-drill,boot=yes,auto-delete=yes --shielded-secure-boot \
  --no-address --no-service-account --no-scopes --tags=<the tags from step 1>
```

```sh
# LOCAL (Mac) — drill B-1, step 3: on the drill instance (not production), over IAP: Postgres up, alembic matches, the tunnel not connected
gcloud compute ssh racinglines-drill --project=racinglines --zone=us-west1-b --tunnel-through-iap --command '
  date -u; uptime
  cd /opt/racinglines && sudo -u racinglines docker compose ps
  sudo -u racinglines bash -c "set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/alembic current"
  curl -s --max-time 5 http://127.0.0.1:8000/healthz; echo
  sudo journalctl -u cloudflared -n 5 --no-pager'
```

Expect Postgres healthy, `alembic current` equal to production's on the snapshot's day, `/healthz` 200 with `"db":
"ok"`, and cloudflared failing to connect. Record the times in the B-1 row, including from `disks create` to the
first good `/healthz`.

```sh
# LOCAL (Mac) — drill B-1, step 4: ⚠️ delete the drill instance only (check the name); its disk goes with it
gcloud compute instances delete racinglines-drill --project=racinglines --zone=us-west1-b --quiet
gcloud compute disks list --project=racinglines --filter="name=racinglines-drill"     # expect nothing listed
```

---

## Capacity (DEC-17)

### Memory

These are *estimates* from the process mix, not measurements. SCOUT-1 records the real numbers, and the health log
records the peaks during DRY-1.

| Process | Runs | Estimate |
|---|---|---|
| Postgres 17 (docker) | Always | 250–400 MB |
| `racinglines-web` (uvicorn) | Always | 250–400 MB |
| A Lab job (subprocess; one at a time in web, one in MCP: `racinglines/web/jobs.py`) | On demand; staff-only after ROLE-1 | 300–800 MB |
| `racinglines-mcp` | Always | 200–300 MB |
| `racinglines-recorder` | Always | 200–300 MB |
| Signals step (FastF1, pricing) | Every 5 min | 400–1,000 MB at peak |
| F1 live step | Every 5 min on live weekends | 300–600 MB |
| Kalshi sync (new) | Every 30 min | 150–300 MB |
| Fantasy tick (new) | Every 10 min | 150–300 MB |
| Health (new) | Every 5 min | 60–120 MB |
| Backup (new; `pg_dump` in the container, `gzip`) | Daily | 50–150 MB |
| cloudflared | Always | 30–60 MB |
| OS, dockerd, journald, guest agent | Always | 250–400 MB |
| **Always-on subtotal** | | **about 1.2–1.9 GB** |
| **Worst overlap** (signals + live step + a Lab job + Kalshi sync) | | **+1.2–2.7 GB** |

On 2 GB the always-on set nearly fills the box, and an overlap needs swap or triggers an OOM kill. The plan is:

- **Swapfile** (OPS-7): 2 GB at `/swapfile`, `vm.swappiness=10`. It is a cushion, not capacity: sustained swapping
  on a pd-balanced disk is slow.
- **Resize** (DEC-17, OWNER-7): e2-medium (4 GB) in the Mon 5 Oct window, unless R16 and load run 1
  ([Load run](#load-run-ops-11)) both show memory peaks under 60% with swap unused. E2 shared-core types burst above a baseline CPU share, and e2-medium's baseline is higher, which
  helps the signals step too. The machine price roughly doubles (about $12 to $24 a month at list price, estimate;
  check the [calculator](https://cloud.google.com/products/calculator)). Downtime is 2–3 minutes. The ephemeral
  external IP changes on stop and start, and nothing depends on it (the tunnel and IAP are outbound or Google-side).
  Blocks: [OWNER-7](#owner-7-resize-to-e2-medium).
- Open item, in no task yet: `OOMScoreAdjust=` on the oneshot units, so the kernel kills a step before web or
  Postgres.

### Concurrency

Memory is only half of it. The web app is one uvicorn process (`racinglines/cli/web.py:13`, no workers) with sync
handlers in a threadpool, and SQLAlchemy's default pool (5 plus 10 overflow; OPS-1 sets it explicitly). An exchange
order makes a venue HTTP call, up to about 12 s, inside a request thread ([Fantasy trading](fantasy-trading.md)).
Book fetches, the Kalshi sync timer and the tick's on-demand closed sync all share the VM's one IP, with no pacing
across processes. A burst at book open or lights-out, with up to 50 players (`RACINGLINES_SIGNUP_CAP`), can use up
the threads or the pool, or draw Kalshi 429s that then stall the sync. R16's staff-only traffic won't show this, so
the load run measures it.

### Load run (OPS-11)

`scripts/ops/loadtest.py` (new, a locust file; the owner installs locust in the Mac's `.venv` by hand, and it is not
a project dependency). Simulated users sign in with the tester accounts (read from a git-ignored file under `data/`,
never from the command line), then browse; in run 2 they also place private-book bets and exchange paper orders in
season `2026-dryrun`. It runs from the Mac through Cloudflare, so it tests the path players use.

| Run | When | Load | Feeds |
|---|---|---|---|
| 1 | Mon 5 Oct 08:00–08:15 PDT (15:00–15:15 UTC), before the Monday settle | 25 sessions, browse only (`/`, `/markets`, `/book`, event pages), 15 minutes | DEC-17 at 12:00 PDT, with R16's memory peaks |
| 2 | In STAGE-1, Wed 7 Oct, after the functional rehearsal | 25 sessions browsing, placing book bets and exchange orders, 15 minutes | The go/no-go |

**Pass criteria (both runs).** Page p95 under 2 s and order p95 under 4 s (an order includes the venue's book
fetch); no 5xx from the app; `/healthz` 200 throughout (the external monitor and the health log); no 429 from Kalshi
or Polymarket in the journal; no OOM kill; the MemAvailable minimum and swap maximum recorded. A Cloudflare challenge
page in the results makes the run invalid: stop and note it.

If run 2 fails on e2-small, OWNER-7 resizes on Thu 8 Oct 09:00–11:00 PDT (16:00–18:00 UTC) and run 2 is repeated
for 5 minutes. If it fails on e2-medium, the go/no-go falls back per the [runbook](fantasy-runbook.md#fallback).

```sh
# LOCAL (Mac) — load run 1 (run 2 is the same with --tags browse,bet,order and load-2 in the names)
.venv/bin/locust -f scripts/ops/loadtest.py --host https://racinglines.bet --headless -u 25 -r 5 -t 15m --tags browse --csv data/backups/load-1 2>&1 | tee data/backups/load-1-$(date -u +%Y%m%dT%H%M%SZ).log
```

```sh
# VM (production) — right after each run (block 0 with NAME=load first): memory, OOMs and 429s in the last 20 minutes
{ free -m; grep oom_kill /proc/vmstat; sudo journalctl --since "-20min" --no-pager | grep -cE ' 429|Too Many'; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

### Disk (30 GB pd-balanced)

| Item | Now | Note |
|---|---|---|
| Ubuntu, snaps (Google Cloud CLI), packages | about 5 GB (*estimate*) | Slow growth |
| Docker image `postgres:17` | about 0.5 GB | |
| venv and uv's Python 3.14 | about 2 GB (*estimate*) | |
| Postgres (docker volume under `/var/lib/docker`) | The Mac's `data/pg` is 668 MB (29 Sep). The VM is larger after 1.9M Kalshi trades loaded 29 Sep; SCOUT-1 measures it | Hot rows move to Parquet (recent 7 days kept); plain `VACUUM` reuses the space, it doesn't return it |
| `data/archive/markets` | Mac: Kalshi 30 MB, Polymarket 33 MB | Hourly parts; compaction below |
| `data/raw/f1` (FastF1), `raw/nascar`, `raw/mtb_dh` | Mac: 25, 13 and 4 MB | Per weekend |
| `data/runs` | Mac: 21 MB (live 16 MB) | |
| Dumps | 7 nightly (15–150 MB each, *estimate*) plus pre-change dumps | OPS-3 prunes nightly only |
| journald | Capped at 1 GB (OPS-7) | Ubuntu's default cap is larger |
| Docker logs | Capped at 30 MB (OPS-6) | |
| Swapfile | 2 GB | |
| **Total** | **about 13–15 GB of 30 (45–50%, *estimate*)** | Alert at 80% (24 GB); the go/no-go wants under 70% |

**Archive compaction.** The hourly archive writes one Parquet part per store and hour. `racinglines markets archive
--compact` rewrites each month as one deduplicated file (`compact`, `racinglines/markets/store.py:263`). It is safe
alongside the recorder, because a part written after the listing isn't deleted. Reads deduplicate anyway
(`store.merge`), so old parts cost space, not correctness. The owner runs it monthly in a quiet window, the first
time on Tue 13 Oct at 16:00 UTC (09:00 PDT). The next nightly rsync mirrors the change to the bucket.

### OS updates and the reboot window

Ubuntu 24.04 installs security updates by itself (`unattended-upgrades`). OPS-7 pins that behaviour down:

- Security origins only; no automatic reboot.
- The daily run moves to 16:00 UTC (09:00 PDT), which clears every R16 and R17 session and most US-afternoon ones.
- `docker.io`, `containerd` and `runc` are held back from automatic upgrades. Upgrading them restarts dockerd and
  with it Postgres, so the owner applies them in the reboot window.
- `needrestart` only lists services, so a library upgrade doesn't restart web or cloudflared mid-session.

**Reboot window.** When `/var/run/reboot-required` appears, the health check says so once a day. Reboot Tue or Wed,
16:00–18:00 UTC (09:00–11:00 PDT), never Thu–Sun of a race weekend. Every unit is enabled and Postgres has
`restart: unless-stopped`, so all of it comes back; live-event timers fire 1 minute after boot. A reboot test after
the cutover proves it (OPS-7, optional block).

---

## R16 closed dry run (DRY-1) and R17 on-call (OPS-10)

### What is on (Thu 1 Oct 18:00 PDT to Sun 4 Oct 12:00 PDT; Fri 2 Oct 01:00 to Sun 4 Oct 19:00 UTC)

- Production on the VM after the cutover: web, recorder, signals, MCP, tunnel. `racinglines-live-f1@2026-16.timer`
  is enabled before the book opens. The R16 plan in [F1 live test](f1-live-roadmap.md) runs unchanged: T1 on
  Kalshi, which already lists R16, with the private book as the demo.
- The P1 ops items: the health, backup and kalshi-sync timers; OPS-7's swap, journald, updates, snapshot schedule,
  external uptime monitor, dead-man and tunnel notification.
- 5 or fewer staff testers, admin-created at `/admin/users` after `ops backup --label r16-testers`. They bet the
  in-app private book only if BOOK-1 and BOOK-2 are merged and deployed by Thu 1 Oct 12:00 PDT. No sign-up, no public
  invite, no trading flag. The A, C and K records are untouched. LAUNCH-1 deactivates the testers.

### What to watch

The window is 66 h, or 792 five-minute slots.

| Signal | Source | Target |
|---|---|---|
| Health timer runs | Health log lines | At least 753 of 792 slots (95%), gaps explained by deploys |
| External `/healthz` | The external monitor's report; the health log for the causes | At least 99% of samples OK |
| Alerts | ntfy, Healthchecks.io, the incident log | Every P1 explained; at most 2 false P2s a day (otherwise DRY-2 tunes the threshold) |
| Nightly backup | `heartbeat/backup`; `gcloud storage ls` | Fri 2, Sat 3 and Sun 4 Oct at 10:00 UTC all succeed; duration and size recorded |
| Snapshots | `gcloud compute snapshots list` | One a day |
| Kalshi sync | `ages_s.kalshi_sync`; 429 count in the journal | Under 35 min throughout; 429s counted |
| Recorder | `ages_s.recorder` | Under 5 min, except restarts |
| Memory | Health log: MemAvailable minimum, swap maximum, OOM delta, per-unit `MemoryCurrent` | Peak recorded (the DEC-17 input: under 60% with swap unused keeps e2-small); no OOM kill |
| Disk | Health log | Under 70% |
| Deploys | The Mac's deploy logs | Only in windows; duration recorded; nothing left paused |
| Live steps | `journalctl -u racinglines-live-f1@2026-16` | All seven updates on time ([F1 live test](f1-live-roadmap.md)) |

### Incident log

One file per weekend on the VM: `/opt/racinglines/data/backups/r16-dryrun-<UTC>.log`, and
`/opt/racinglines/data/backups/r17-oncall-<UTC>.log` for R17. One line per incident, times in UTC:

```text
# id | start (UTC) | end (UTC) | sev | check or unit | what was seen | action taken | cause | follow-up (task id or none)
I-01 | <start> | <end> | P2 | <check> | <what was seen> | <action> | <cause> | <follow-up>
```

```sh
# VM (production) — append a line (block 0 with NAME=r16-dryrun sets $LOG)
echo "I-01 | <start> | <end> | P2 | <check> | <seen> | <action> | <cause> | <follow-up>" | sudo -u racinglines tee -a "$LOG"
```

### Exit criteria (feed the go/no-go)

- The external monitor shows at least 99% for the window, the health timer met its 95% run target, and every P1
  is explained in the incident log.
- Two consecutive nightly dumps are in the bucket, and one snapshot a day.
- The first restore drill is done on the Mac, with its time recorded (OPS-4).
- Kalshi sync stayed under 35 minutes, or each breach is explained.
- Peak memory, swap and disk are recorded for DEC-17, with load run 1's numbers (Mon 5 Oct).
- No trading flag was touched, and the A, C and K records are unaffected.

### Retro (DRY-2, Opus, Mon 5 Oct)

Inputs: the health log, the incident log and journal extracts, copied to the Mac with the SCOUT-1 copy block. Output:
an "R16 dry-run results" section appended to this doc. It records availability, alerts by check with the false
positives, backup durations and sizes, the restore drill time, the memory peak, swap and disk. It also gives the
DEC-17 recommendation and a list of fixes with owners. The memory and disk numbers are due by Mon 5 Oct 10:00 PDT
(17:00 UTC), before DEC-17's 12:00 PDT deadline; the rest is due by 18:00 PDT.

### Settlement replay on R16 data (REPLAY-1)

R16 runs none of the fantasy code (it deploys on Tue 6 and Wed 7 Oct), so without a replay the first real run of
the settlement code would be R17, with players. The replay is the runbook's
[REPLAY-1](fantasy-runbook.md#replay-1-r16-settlement-on-a-restored-copy-wed-7-oct-after-step-4-merges-before-1700-pdt):
the real tick on a restored copy of the VM's dump, on the Mac, writing the scratch database only. Nothing fake is
written to the production database. On the VM, STAGE-1 exercises only the tick's live behaviour on `2026-dryrun`
markets (lines 5i and 5j: a void refunded once, and settlement continuing with `RACINGLINES_FANTASY=0`). The result
is go/no-go line 19.

### R17 on-call (OPS-10)

- Phone alerts on from Thu 8 Oct 17:00 PDT to Mon 12 Oct; the response times are in the on-call table above.
- Deploys only in the between-session windows: Fri 9 Oct 14:00 UTC – Sat 10 Oct 08:00 UTC, Sat 10 Oct 15:00 UTC –
  Sun 11 Oct 10:00 UTC, and after Sun 11 Oct 16:00 UTC.
- Incident log `r17-oncall-<UTC>.log`. A Haiku scout reads logs on request, after the owner copies them to the Mac.
- Abuse response: `RACINGLINES_SIGNUP=off`, revoke invite codes, suspend accounts through `/admin/fantasy`
  ([Sign-up abuse wave](#sign-up-abuse-wave)).
- The external monitor's report gives the weekend's availability for REPORT-1; the health log explains the misses.

---

## Incident runbooks

Start each incident with block 0 (`NAME=incident`), so every write step lands in one log. Read-only diagnostics
don't need the tee. Record each incident in the weekend's incident log.

### Site down

Check in this order: outside view, VM, loopback, tunnel, web, DB.

```sh
# LOCAL (Mac) — step 1: what the outside sees
curl -s -o /dev/null -w '%{http_code} in %{time_total}s\n' --max-time 15 https://racinglines.bet/healthz
curl -s --max-time 15 https://racinglines.bet/healthz; echo
```

| Result | Meaning | Go to |
|---|---|---|
| 200, `"db": "ok"` | Up; a blip, or the phone's network | Close |
| 503 from the app | Web is up, Postgres is not | Step 5 |
| 502 | cloudflared is up, web is not | Step 4 |
| 530 / Cloudflare error 1033 | No tunnel connector | Step 3 |
| Timeout | Cloudflare or the VM | Steps 2 and 3 |

```sh
# VM (production) — step 2, from the Mac: is the VM there, and what runs?
gcloud compute instances describe racinglines-vm --project=racinglines --zone=us-west1-b --format='value(status)'
bash scripts/deploy/vm.sh status
```

```sh
# VM (production) — step 3, in a vm.sh ssh session: loopback first, then the tunnel
curl -s --max-time 10 http://127.0.0.1:8000/healthz; echo
systemctl status cloudflared --no-pager | head -5
sudo journalctl -u cloudflared -n 30 --no-pager
```

If loopback answers and cloudflared is failed or erroring, restart it. If Cloudflare itself is down
(cloudflarestatus.com), wait.

```sh
# VM (production) — step 3b: restart the tunnel
{ date -u; sudo systemctl restart cloudflared; sleep 10; systemctl status cloudflared --no-pager | head -5; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 4: web down
sudo journalctl -u racinglines-web -n 80 --no-pager
{ date -u; sudo systemctl restart racinglines-web; sleep 8; curl -s --max-time 10 http://127.0.0.1:8000/healthz; echo; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

If web crashes on start right after a deploy, see [Bad deploy](#bad-deploy).

```sh
# VM (production) — step 5: the database
cd /opt/racinglines && sudo -u racinglines docker compose ps && sudo -u racinglines docker compose logs --tail 50 db
df -h /; free -m
{ date -u; cd /opt/racinglines && sudo -u racinglines docker compose up -d --wait db; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

A full disk goes to [Disk full](#disk-full). An OOM kill: restart, record it, and it feeds DEC-17.

```sh
# LOCAL (Mac) — step 6: the VM is stopped or hung (⚠️ reset is a hard reset; Postgres recovers as after a power cut)
gcloud compute instances start racinglines-vm --project=racinglines --zone=us-west1-b     # status TERMINATED
gcloud compute instances reset racinglines-vm --project=racinglines --zone=us-west1-b     # RUNNING but unreachable
gcloud compute instances get-serial-port-output racinglines-vm --project=racinglines --zone=us-west1-b | tail -50
```

If it isn't back within 30 minutes, take recovery path B.

### Recorder stale

```sh
# VM (production) — what the recorder says, then a restart
sudo journalctl -u racinglines-recorder -n 60 --no-pager | grep -E 'error|books|sync|archived' | tail -20
{ date -u; sudo systemctl restart racinglines-recorder; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

After OPS-6 the recorder exits by itself after 10 failed loops and systemd restarts it; the alert fires earlier, at 5
minutes. Errors from Polymarket's API (5xx, timeouts) need no fix: wait, and the hourly de-dupe limits the pushes.
Errors from the DB go to [Site down](#site-down) step 5. Write the gap in the incident log. Books can't be
backfilled; prices and trades can, afterwards (`racinglines markets history`, `trades`).

### Kalshi sync failing or 429

```sh
# VM (production) — what failed, and when the next run is
sudo journalctl -u racinglines-kalshi-sync -n 300 --no-pager | grep -E '429|Too Many|error|Traceback' | tail -20
systemctl list-timers racinglines-kalshi-sync.timer --no-pager
```

What goes stale: new Kalshi markets, `market_links.last_bid`/`last_ask` (taker equity marks on the leaderboard) and
`resolved_yes` (settlement). Exchange paper fills don't: they read a live book per order (EXCH-1). One failed run is
fine, since the next is 30 minutes later. If 429s repeat, slow the timer to hourly:

```sh
# VM (production) — temporary: hourly instead of every 30 minutes (health flags over 35 min; acknowledge it)
{
  sudo mkdir -p /etc/systemd/system/racinglines-kalshi-sync.timer.d
  printf '[Timer]\nOnCalendar=\nOnCalendar=*-*-* *:05:00 UTC\n' | sudo tee /etc/systemd/system/racinglines-kalshi-sync.timer.d/hourly.conf
  sudo systemctl daemon-reload && sudo systemctl restart racinglines-kalshi-sync.timer
  systemctl list-timers racinglines-kalshi-sync.timer --no-pager
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — undo (vm.sh deploy doesn't remove drop-ins)
{ sudo rm /etc/systemd/system/racinglines-kalshi-sync.timer.d/hourly.conf && sudo systemctl daemon-reload && sudo systemctl restart racinglines-kalshi-sync.timer; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

Near settlement, SETTLE-1's on-demand closed sync and the admin queue cover a lagging resolution.

### Fantasy tick stuck or settlement wrong

"Stuck" means `ages_s.fantasy_tick` is over 30 minutes or the unit failed. "Wrong" means a player's balance is off,
or a spot check of `fantasy_stats` against `bankroll_entries` fails. ⚠️ Settlement: every fix goes through the admin
route with a reason, never through SQL.

```sh
# VM (production) — 1. pause the tick (a disabled timer stays off across deploys and reboots)
{ date -u; sudo systemctl disable --now racinglines-fantasy.timer; cat /var/lib/racinglines/deploy-paused 2>/dev/null; systemctl list-timers racinglines-fantasy.timer --all --no-pager; } 2>&1 | sudo -u racinglines tee -a "$LOG"
sudo journalctl -u racinglines-fantasy -n 100 --no-pager
```

If `deploy-paused` lists `racinglines-fantasy.timer`, the next deploy would resume it; re-check after any deploy.

```sh
# VM (production) — 2. a dump before any fix
rl ops backup --label resettle-<event> 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# LOCAL (Mac) — 3. the tick's dump from just before the bad settle, into racinglines_scratch
bash scripts/ops/restore_scratch.sh gs://<bucket>/db/before/racinglines-before-pre-settle-<event>-<UTC>.sql.gz
```

Use the tick's `pre-settle-<event>` dump: it holds every order and bet up to the first settlement write. A nightly or
launch-weekend dump from before the race misses the last hours of orders. If the bad settle came from a later tick
(a re-settle, a lagging resolution), use the newest dump in `db/before/` or `db/nightly/` from before that tick.

Then compare, per user, on scratch (psql) and on production (read-only, `/admin/sql`):
`SELECT user_id, kind, sum(amount) FROM bankroll_entries WHERE season_id = <id> AND ts >= '<race start>' GROUP BY 1, 2 ORDER BY 1, 2;`
Do the same for `fantasy_positions` of the event's markets.

**4.** Fix at `/admin/fantasy/settle`: re-settle with a reason, which writes activity_log `fantasy_resettle`.

```sh
# VM (production) — 5. one tick by hand, a second to prove it changes nothing, then the timer back on
{ rl fantasy tick; rl fantasy tick; sudo systemctl enable --now racinglines-fantasy.timer; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

**6.** Add a `data_changes` row and a `docs/data-changes.md` line naming the dump, plus an incident log line. Tell the
affected players from support@racinglines.bet.

### Disk full

```sh
# VM (production) — what is big
df -h /
sudo du -xh --max-depth=2 /opt/racinglines/data /var/lib/docker /var/log 2>/dev/null | sort -h | tail -15
journalctl --disk-usage
ls -lhS /opt/racinglines/data/backups/db | head
```

Fix in this order, each step tee'd:

1. `sudo journalctl --vacuum-size=500M`.
2. Old pre-change dumps: copy them to `gs://$RACINGLINES_GCS_BUCKET/db/before/`, check the copy with
   `gcloud storage ls -l`, and only then remove them on the VM. Keep the newest one per task.
3. `sudo docker image prune -f` (dangling images only).
4. `rl markets archive` moves old rows to Parquet. `--vacuum-full` returns the space to the OS but locks tables
   briefly, so run it only in a deploy window.
5. Grow the disk (⚠️ costs more per month):

```sh
# LOCAL (Mac) — grow the disk online
gcloud compute disks resize racinglines-vm --project=racinglines --zone=us-west1-b --size=50GB
```

```sh
# VM (production) — grow the partition and filesystem (check the device names with lsblk first)
lsblk
{ sudo growpart /dev/sda 1; sudo resize2fs /dev/sda1; df -h /; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

A Postgres with a full disk stops accepting writes. Free space first, then `docker compose up -d --wait db` if it
stopped.

### Bad deploy

```sh
# VM (production) — from the Mac: what is deployed, and is anything paused?
bash scripts/deploy/vm.sh status
bash scripts/deploy/vm.sh logs racinglines-web
```

```sh
# VM (production) — from the Mac: back to the previous good sha (from the deploy log, or git log --first-parent main)
bash scripts/deploy/vm.sh deploy <previous sha> 2>&1 | tee data/backups/deploy-rollback-$(date -u +%Y%m%dT%H%M%SZ).log
bash scripts/deploy/smoke.sh https://racinglines.bet
curl -s https://racinglines.bet/healthz; echo
```

```sh
# LOCAL (Mac) — so the next plain deploy doesn't bring it back
git checkout main && git pull
git revert -m 1 <merge sha>
python -m pytest -m "not live"
git push
```

If `update.sh` failed half-way, PR #71 left the timers paused, and the rollback deploy resumes them. Before OPS-8, a
rollback across a migration stops at `alembic` (G12): use [Bad migration](#bad-migration). After OPS-8 it deploys
with a warning.

**The rollback refuses: "a step in progress".** PR #71 waits 5 minutes for a running step, then deploys nothing and
resumes the timers. There is no `--force`. Find the step and stop it, then deploy again. Stopping the backup costs one
dump (run `rl ops backup` by hand afterwards); stopping kalshi-sync or signals costs one run; stopping a live step
costs one update, which the deploy's catch-up step redoes.

```sh
# VM (production) — block 0 with NAME=incident first: which step blocks the deploy, and since when
systemctl list-units --no-legend --plain --state=activating 'racinglines-*'
for u in $(systemctl list-units --no-legend --plain --state=activating 'racinglines-*' | awk '{print $1}'); do systemctl show "$u" -p ActiveEnterTimestamp; done
```

```sh
# VM (production) — stop it (one unit name from the list above), then deploy again from the Mac
{ date -u; sudo systemctl stop <unit>; systemctl list-units --state=activating 'racinglines-*' --no-pager; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

### Bad migration

!!! warning "Owner sign-off and backup first"
    A DB write on the VM: it needs the owner's explicit sign-off in the same turn. The current state is dumped before
    the restore, and a `data_changes` row names both dumps. Everything written between the migration and the restore
    (bets, fills, sign-ups, book snapshots) is only in the before-restore dump. The owner decides what to re-apply.

```sh
# VM (production) — from the Mac: 1. old code first (after OPS-8 it deploys without running alembic, with a warning)
bash scripts/deploy/vm.sh deploy <sha before the migration>
```

```sh
# VM (production) — in a vm.sh ssh session, block 0 with NAME=restore: 2. stop writers, dump what's there, load the pre-deploy dump
{
  date -u
  systemctl list-units --no-legend --plain --state=active 'racinglines-*.timer' | awk '{print $1}' | sudo tee /var/lib/racinglines/restore-paused
  sudo systemctl stop $(cat /var/lib/racinglines/restore-paused) racinglines-web racinglines-recorder racinglines-mcp
  rl ops backup --label restore-<sha>
  cd /opt/racinglines
  sudo -u racinglines docker compose exec -T db psql -U racinglines -d postgres -v ON_ERROR_STOP=1 \
    -c "drop database if exists racinglines with (force)" -c "create database racinglines owner racinglines"
  gunzip -c data/backups/db/racinglines-before-deploy-<sha>-<UTC>.sql.gz | sudo -u racinglines docker compose exec -T db psql -U racinglines -d racinglines -v ON_ERROR_STOP=1 -q >/dev/null
  sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/alembic current'
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — 3. start everything again
{ sudo systemctl start racinglines-web racinglines-recorder racinglines-mcp $(cat /var/lib/racinglines/restore-paused) && sudo rm /var/lib/racinglines/restore-paused; systemctl list-units 'racinglines-*' --no-pager | head -20; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# LOCAL (Mac) — 4. smoke through Cloudflare
bash scripts/deploy/smoke.sh https://racinglines.bet
```

```sh
# VM (production) — 5. the record (plus a docs/data-changes.md line in the next docs PR)
rl db changes --add "restored racinglines-before-deploy-<sha>-<UTC>.sql.gz after a bad migration; the state before the restore is racinglines-before-restore-<sha>-<UTC>.sql.gz" 2>&1 | sudo -u racinglines tee -a "$LOG"
```

**6.** Re-apply account deletions. Load the before-restore dump into `racinglines_scratch` on the Mac
(`scripts/ops/restore_scratch.sh <path>`), list `activity_log` rows with action `account_delete` newer than the
restored dump's `created_at`, and delete each of those accounts again through the account-deletion path (ACC-3,
[Fantasy accounts](fantasy-accounts.md)). Record the count in the incident log.

This is the one rollback runbook for a migration. The OWNER-8 rollback in [Fantasy accounts](fantasy-accounts.md)
points here; if the two ever read differently, this order (old code first, then stop, dump, restore) is the one to
follow.

### Mail failing

Symptoms: players report no verification mail, the web journal shows SMTP errors, or `racinglines mail test` fails.
DNS, token and Proton limits (535 auth, 421 4.7.0, 550 5.4.5) are covered in [Email setup](email-setup.md).

```sh
# VM (production) — what the mailer says
sudo journalctl -u racinglines-web --since "-2h" --no-pager | grep -iE 'mail|smtp' | tail -30
rl mail test --to <your Gmail>
```

Fall back to the log backend (mail text, links included, goes to the journal and `activity_log`): set
`RACINGLINES_MAIL_BACKEND=log` with the [env edit blocks](#editing-etcracinglinesenv) (copy, edit, check, restart).

Then verify the stuck players by hand. Use the admin member page if ADM-1 includes a verify action
([Fantasy accounts](fantasy-accounts.md)); otherwise send each player the verification link from the journal, from
support@racinglines.bet. Switch back to `smtp` once `rl mail test` delivers.

### Sign-up abuse wave

Symptoms: sign-ups spike, `RACINGLINES_SIGNUP_CAP` is reached, `signup_rejected` rows pile up, or the mail cap is hit.

**1.** Close sign-up now: set `RACINGLINES_SIGNUP=off` with the [env edit blocks](#editing-etcracinglinesenv) (copy,
edit, check, restart).

```sh
# VM (production) — 2. a dump, then see and revoke the codes in use (argument form per ACC-4)
{ rl ops backup --label abuse-cleanup; rl fantasy invite list; rl fantasy invite revoke <code>; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

**3.** Suspend accounts at `/admin/fantasy/members/{user_id}` (ADM-1). Suspension bumps `session_epoch`, so their
sessions end.

**4.** Turn on Turnstile (DEC-16): create the widget in Cloudflare, put `RACINGLINES_TURNSTILE_SITEKEY` and
`RACINGLINES_TURNSTILE_SECRET` in `/etc/racinglines.env` with the env edit blocks, and restart web. Add a Cloudflare rate-limiting rule on
`/login`, `/signup` and `/password` if the plan allows one.

**5.** Re-open with `RACINGLINES_SIGNUP=invite` and fresh codes once it's quiet. Record it in the incident log.

---

## Owner command blocks

Each block is one step, in order. **VM (production)** blocks run in a `bash scripts/deploy/vm.sh ssh` session and tee
to `/opt/racinglines/data/backups/<name>-<UTC>.log`. Blocks marked "from the Mac" use `vm.sh`, which acts on the VM.
**LOCAL (Mac)** blocks are `gcloud`, git or dashboard steps.

### Block 0: a session log

```sh
# VM (production) — block 0, once per ssh session; set NAME for the job (hardening, baseline, r16-dryrun, incident, restore, ...)
export NAME=hardening
export LOG=/opt/racinglines/data/backups/$NAME-$(date -u +%Y%m%dT%H%M%SZ).log
sudo -u racinglines mkdir -p /opt/racinglines/data/backups && sudo -u racinglines touch "$LOG" && echo "logging to $LOG"
rl() { sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && exec .venv/bin/racinglines "$@"' rl "$@"; }
```

If the connection drops, run block 0 again: that starts a new log.

### Editing /etc/racinglines.env

Every switch, secret and the off switch live in this one file, and a typo in it is an outage: the web unit restarts
every 5 seconds, ACC-3 refuses to start with sign-up on and a short `APP_SECRET`, and an unquoted value with `<` or
`>` (a mail From line) breaks every `rl` command, which sources the file with bash. So every edit is copy, edit,
check, restart, with the revert ready. The copy, the check and the revert are run as written; only step 2 changes.

```sh
# VM (production) — env edit, step 1: a timestamped copy (block 0 first)
export ENVBAK=/etc/racinglines.env.before-$(date -u +%Y%m%dT%H%M%SZ)
sudo cp -p /etc/racinglines.env "$ENVBAK" && echo "env copy: $ENVBAK" | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — env edit, step 2: the edit itself (not tee'd: the file holds secrets). Quote any value with spaces, < or >
sudoedit /etc/racinglines.env
```

```sh
# VM (production) — env edit, step 3: check before any restart; every line should say OK, and the diff lists only the keys you meant to add or remove
{
  sudo bash -n /etc/racinglines.env && echo "OK: bash parses it"
  sudo bash -c 'set -a; . /etc/racinglines.env; set +a; for k in APP_SECRET DATABASE_URL RACINGLINES_URL; do [ -n "${!k}" ] && echo "OK: $k set" || echo "PROBLEM: $k empty"; done'
  sudo grep -E '^(POLYMARKET|KALSHI)_TRADING_ENABLED=' /etc/racinglines.env >/dev/null && echo "PROBLEM: a trading flag is present" || echo "OK: trading flags absent"
  rl db -h >/dev/null && echo "OK: the CLI starts with this file"
  diff <(sudo cut -d= -f1 "$ENVBAK") <(sudo cut -d= -f1 /etc/racinglines.env) && echo "OK: same keys (only values changed)"
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — env edit, step 4: restart web and check it answers
{ date -u; sudo systemctl restart racinglines-web; sleep 8; systemctl is-active racinglines-web; curl -s --max-time 10 http://127.0.0.1:8000/healthz; echo; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — env edit, revert: only if step 3 or 4 went wrong
{ date -u; sudo cp -p "$ENVBAK" /etc/racinglines.env && sudo systemctl restart racinglines-web; sleep 8; systemctl is-active racinglines-web; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

The `.before-*` copies hold secrets; they stay in `/etc` (root-only, like the file) and are never copied to the Mac or
the bucket. A checker command in code (`racinglines ops env-check`) would be tidier, but it is not in the plan's
names; these four blocks do the same job without new code.

### OWNER-1: merge and deploy PR #71 (Wed 30 Sep, by 12:00 PDT)

```sh
# LOCAL (Mac) — merge PR #71, run in order
git checkout main && git pull
git merge --no-ff origin/work/deploy-pause   # ⚠️ needs special attention: replaces the live-event freeze in vm.sh deploy with pause, catch-up and resume of the VM's timers; read the diff first
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git push
```

If you merge on GitHub instead, `git pull` main before the next block. The PR's diff touches `scripts/deploy/vm.sh`,
`CLAUDE.md` and `docs/vm-deploy.md`.

```sh
# VM (production) — from the Mac: deploy it, then confirm
bash scripts/deploy/vm.sh deploy 2>&1 | tee data/backups/deploy-$(date -u +%Y%m%dT%H%M%SZ).log
bash scripts/deploy/vm.sh status     # 'deployed:' shows the merge; no "PAUSED by an unfinished deploy" line
```

### OWNER-4: cutover checks (Wed 30 Sep)

Do the cutover itself per [VM deploy](vm-deploy.md#cutover). When re-pointing racinglines.bet, edit only that
hostname and never touch the MX, TXT or DKIM records ([Email setup](email-setup.md)).

```sh
# LOCAL (Mac) — no firewall rule opens tcp:8000
gcloud compute firewall-rules list --project=racinglines --format=json | grep -n '"8000"' || echo "OK: no tcp:8000 rule"
```

If it lists `rl-test-web`, run `bash scripts/deploy/vm.sh public off`. It also restarts web, and it errors if the rule
is already gone.

```sh
# VM (production) — block 0 with NAME=cutover first; loopback only, no public drop-in, APP_SECRET set, trading flags absent
{
  ss -ltn | grep -E ':(8000|8100|5433) '
  test -e /etc/systemd/system/racinglines-web.service.d/public.conf && echo "PROBLEM: public.conf present" || echo "OK: no public.conf"
  sudo awk -F= '$1=="APP_SECRET"{print ($2=="" ? "PROBLEM: APP_SECRET empty" : "OK: APP_SECRET set")}' /etc/racinglines.env
  sudo grep -E '^(POLYMARKET|KALSHI)_TRADING_ENABLED=' /etc/racinglines.env && echo "PROBLEM: a trading flag is present" || echo "OK: trading flags absent"
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

Expect `127.0.0.1:8000`, `127.0.0.1:8100` and `127.0.0.1:5433` only. Then sign in on the site, run `sudo systemctl
restart racinglines-web`, and reload: you should still be signed in (APP_SECRET works). Add
`RACINGLINES_OPS_NTFY_TOPIC` with the env block under OPS-7.

### SCOUT-1: read-only baseline (Wed 30 Sep, after the cutover)

The scout runs these read-only commands over ssh. If the permission classifier refuses, the owner pastes them.

```sh
# VM (production) — block 0 with NAME=baseline first; read-only
{
  date -u; uname -r; grep PRETTY /etc/os-release
  sudo -u racinglines git -C /opt/racinglines log -1 --format='deployed: %h %s (%cr)'
  cat /var/lib/racinglines/deploy-paused 2>/dev/null || echo "no deploy-paused file"
  systemctl list-unit-files 'racinglines-*' 'cloudflared*' --no-pager
  systemctl list-units 'racinglines-*' 'cloudflared*' --all --no-pager
  systemctl list-timers --all --no-pager
  for u in racinglines-web racinglines-recorder racinglines-mcp cloudflared; do systemctl show $u -p Restart,RestartUSec,MemoryCurrent,ActiveEnterTimestamp; done
  free -m; swapon --show
  df -h /; sudo du -sh /var/lib/docker /opt/racinglines/.venv /opt/racinglines/data/* 2>/dev/null
  journalctl --disk-usage; ls -ld /var/log/journal; cat /etc/systemd/journald.conf.d/*.conf 2>/dev/null
  cd /opt/racinglines && sudo -u racinglines docker compose ps && sudo -u racinglines docker stats --no-stream
  sudo -u racinglines docker compose exec -T db psql -U racinglines -d racinglines -Atc "select pg_size_pretty(pg_database_size('racinglines'))"
  sudo awk -F= '/^[A-Z_]+=/{print $1, ($2 == "" ? "(empty)" : "(set)")}' /etc/racinglines.env
  sudo bash -c '. /etc/racinglines.env; echo "bucket: ${RACINGLINES_GCS_BUCKET:-UNSET}"'
  ss -ltn
  test -e /etc/systemd/system/racinglines-web.service.d/public.conf && echo "public.conf PRESENT" || echo "no public.conf"
  apt-config dump | grep -E '^Unattended-Upgrade::(Allowed-Origins|Automatic-Reboot)'
  cat /var/run/reboot-required 2>/dev/null || echo "no reboot required"
  ls -lh /opt/racinglines/data/backups/db 2>/dev/null | tail -5
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# LOCAL (Mac) — the Google side, read-only
gcloud compute instances describe racinglines-vm --project=racinglines --zone=us-west1-b --format='value(machineType.basename(),status)'
gcloud compute disks describe racinglines-vm --project=racinglines --zone=us-west1-b --format='value(sizeGb,type.basename(),resourcePolicies)'
gcloud compute firewall-rules list --project=racinglines --format='table(name,sourceRanges.list(),targetTags.list())'
gcloud compute resource-policies list --project=racinglines
```

```sh
# LOCAL (Mac) — copy the VM's logs to the Mac for the scout (data/ is git-ignored)
mkdir -p data/backups/vm-logs
gcloud compute scp --project=racinglines --zone=us-west1-b --tunnel-through-iap 'racinglines-vm:/opt/racinglines/data/backups/baseline-*.log' data/backups/vm-logs/
```

The scout's output is a table of findings, with NOT FOUND for anything missing. The same copy block works for
`r16-dryrun-*`, `r17-oncall-*` and `data/runs/logs/health/*.jsonl`.

### OPS-7: VM hardening (finish before Thu 1 Oct 18:00 PDT / Fri 2 Oct 01:00 UTC)

OPS-7 comes in two parts, because the P1 code (eight branches) might not all land by Thu 1 Oct and the VM should not
serve production for 30 hours with no backup and no outside eyes.

- **At the cutover, Wed 30 Sep, right after OWNER-4** (no code needed): the snapshot schedule (step 8), the external
  uptime monitor and the Cloudflare tunnel notification (step 4b), the ntfy topic (4a), and, as soon as the bucket
  exists (DEC-19), the bucket lockdown and lifecycle (step 9).
- **By Thu 1 Oct 18:00 PDT**: swap, journald, updates (steps 1–3), the env keys and the password-manager copy (4c–5),
  Healthchecks.io, the test alert.
- **Before `RACINGLINES_SIGNUP` leaves `off`** (STAGE-1, Wed 7 Oct): Cloudflare Access on `/admin` (step 10) and HSTS
  (step 11).

**The minimum if P1 code slips.** Without OPS-1/OPS-2 the external monitor and the tunnel notification still alert;
without OPS-3 the [fallback backup](#fallback-backup-only-if-ops-3-slips) runs once a day; without OPS-5 the owner
runs the Kalshi sync by hand before the R16 book opens. OPS-6 and OPS-8 are not part of P1 anyway: they merge Mon 5 Oct, and
OPS-8 only has to precede ACC-1.

```sh
# VM (production) — block 0 with NAME=hardening first. Step 1: 2 GB swapfile, swappiness 10
{
  if [ -e /swapfile ]; then echo "/swapfile exists, skipping"; else
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  fi
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-racinglines.conf
  sudo sysctl -p /etc/sysctl.d/99-racinglines.conf
  swapon --show; free -m
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 2: persistent journal, capped at 1 GB (a drop-in; same effect as editing /etc/systemd/journald.conf)
{
  sudo mkdir -p /etc/systemd/journald.conf.d
  printf '[Journal]\nStorage=persistent\nSystemMaxUse=1G\n' | sudo tee /etc/systemd/journald.conf.d/racinglines.conf
  sudo systemctl restart systemd-journald
  journalctl --disk-usage
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 3: security updates only, no auto-reboot, daily at 16:00 UTC, docker held back, needrestart list-only
{
  apt-config dump | grep -E '^Unattended-Upgrade::(Allowed-Origins|Automatic-Reboot)'
  sudo tee /etc/apt/apt.conf.d/52racinglines >/dev/null <<'EOF'
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Package-Blacklist { "docker.io"; "containerd"; "runc"; };
EOF
  sudo mkdir -p /etc/systemd/system/apt-daily-upgrade.timer.d
  sudo tee /etc/systemd/system/apt-daily-upgrade.timer.d/racinglines.conf >/dev/null <<'EOF'
[Timer]
OnCalendar=
OnCalendar=*-*-* 16:00:00 UTC
RandomizedDelaySec=0
EOF
  [ -d /etc/needrestart/conf.d ] && echo "\$nrconf{restart} = 'l';" | sudo tee /etc/needrestart/conf.d/racinglines.conf
  sudo systemctl daemon-reload
  systemctl list-timers apt-daily-upgrade.timer --no-pager
  sudo unattended-upgrade --dry-run 2>&1 | tail -5
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# LOCAL (Mac) — step 4a: a hard-to-guess ntfy topic (ntfy.sh topics are readable by anyone who knows the name)
echo "racinglines-ops-$(openssl rand -hex 8)"
```

Step 4b, dashboards (the owner's Gmail on every one; menu names may differ slightly):

- **ntfy app** (phone): subscribe to that topic on ntfy.sh. Allow priority-5 pushes through Do Not Disturb if you want
  night pages for R17.
- **Healthchecks.io** (free tier): create a check "racinglines-vm health" with a 5-minute period and a 20-minute
  grace, and copy its ping URL. Email to Gmail is the default integration; ntfy is optional.
- **Cloudflare**: Notifications > Add > Tunnel Health Alert for tunnel `racinglines-vm`, delivered by email to Gmail.
  At the cutover.
- **External uptime monitor** (UptimeRobot or Better Stack, free tier; at the cutover): an HTTP(S) monitor on
  `https://racinglines.bet/login` every 5 minutes (Better Stack's free tier allows 3), with a 10 s timeout, alerting
  to Gmail and to the ntfy app if the free plan has a webhook or ntfy integration. Once OPS-1 is deployed, point it
  at `https://racinglines.bet/healthz`, and use a keyword check for `"db": "ok"` if the plan offers one (a 503
  fails it either way). Keep its monthly report: it is the availability number for DRY-2, the go/no-go and REPORT-1.

```sh
# VM (production) — step 4c: add the ops keys with the env edit blocks (Editing /etc/racinglines.env): copy, sudoedit, check, restart
#   RACINGLINES_OPS_NTFY_TOPIC=racinglines-ops-<16 hex from step 4a>
#   RACINGLINES_HEALTHCHECK_PING_URL=https://hc-ping.com/<uuid from Healthchecks.io>
#   RACINGLINES_GCS_BUCKET=racinglines-data-<project number>      (if missing; DEC-19)
```

```sh
# VM (production) — step 4d: which keys are set (names only)
sudo awk -F= '/^[A-Z_]+=/{print $1, ($2 == "" ? "(empty)" : "(set)")}' /etc/racinglines.env 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 5: copy every value into your password manager (not tee'd: it prints secrets)
sudo cat /etc/racinglines.env
```

#### Test alert

```sh
# VM (production) — step 6: a test push to the ops topic; it should reach the phone within a minute
sudo bash -c 'set -a; . /etc/racinglines.env; set +a; curl -s -o /dev/null -w "%{http_code}\n" -H "Title: racinglines ops test" -H "Priority: high" -d "test from racinglines-vm at $(date -u +%H:%M) UTC" "https://ntfy.sh/$RACINGLINES_OPS_NTFY_TOPIC"' 2>&1 | sudo -u racinglines tee -a "$LOG"
```

The OPS-2 end-to-end test runs after the health timer is on, in a quiet window: before Thu 1 Oct 18:00 PDT, or after
the R16 weekend. It costs about 15 book snapshots per open Polymarket token.

```sh
# VM (production) — the recorder off for 15 minutes; expect the P2 push after about 10 minutes
{ date -u; sudo systemctl stop racinglines-recorder; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — 15 minutes later: back on; expect the "recovered" push
{ date -u; sudo systemctl start racinglines-recorder; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 7 (optional): a reboot test, Wed 30 Sep after the cutover or Thu 1 Oct before 12:00 PDT
echo "reboot at $(date -u)" | sudo -u racinglines tee -a "$LOG"; sudo systemctl reboot
```

```sh
# VM (production) — from the Mac, 3 minutes later: everything came back
bash scripts/deploy/vm.sh status
bash scripts/deploy/smoke.sh https://racinglines.bet
```

#### Snapshot schedule

```sh
# LOCAL (Mac) — step 8: the daily snapshot schedule (14 days), attached to the VM's disk
gcloud compute resource-policies create snapshot-schedule racinglines-daily \
  --project=racinglines --region=us-west1 \
  --daily-schedule --start-time=11:00 \
  --max-retention-days=14 --on-source-disk-delete=keep-auto-snapshots \
  --storage-location=us-west1
gcloud compute disks add-resource-policies racinglines-vm \
  --project=racinglines --zone=us-west1-b --resource-policies=racinglines-daily
gcloud compute disks describe racinglines-vm --project=racinglines --zone=us-west1-b --format='value(resourcePolicies)'
```

```sh
# LOCAL (Mac) — the next day: one snapshot listed
gcloud compute snapshots list --project=racinglines --filter="sourceDisk~racinglines-vm" --sort-by=~creationTimestamp --limit=3
```

#### Bucket lifecycle

```sh
# LOCAL (Mac) — step 9a (DEC-19, at the cutover if the bucket exists): the bucket's top-level prefixes, and whether it is locked down
export RACINGLINES_GCS_BUCKET=racinglines-data-$(gcloud projects describe racinglines --format='value(projectNumber)')
gcloud storage ls gs://$RACINGLINES_GCS_BUCKET
gcloud storage buckets describe gs://$RACINGLINES_GCS_BUCKET --format=yaml | grep -iE 'uniform_bucket_level_access|public_access_prevention|versioning'
```

```sh
# LOCAL (Mac) — step 9b: uniform bucket-level access and public access prevention on (the full dumps hold player data)
gcloud storage buckets update gs://$RACINGLINES_GCS_BUCKET --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets describe gs://$RACINGLINES_GCS_BUCKET --format=yaml | grep -iE 'uniform_bucket_level_access|public_access_prevention'
```

```sh
# LOCAL (Mac) — step 9c: nightly dumps kept 35 days; overwritten versions kept 30 days, 90 under archive/ (the order-book archive can't be backfilled)
cat > "$TMPDIR/rl-lifecycle.json" <<'EOF'
{"rule": [
  {"action": {"type": "Delete"}, "condition": {"age": 35, "matchesPrefix": ["db/nightly/"]}},
  {"action": {"type": "Delete"}, "condition": {"isLive": false, "daysSinceNoncurrentTime": 30, "matchesPrefix": ["db/", "live/", "runs/", "raw/"]}},
  {"action": {"type": "Delete"}, "condition": {"isLive": false, "daysSinceNoncurrentTime": 90, "matchesPrefix": ["archive/"]}}
]}
EOF
gcloud storage buckets update gs://$RACINGLINES_GCS_BUCKET --lifecycle-file="$TMPDIR/rl-lifecycle.json"
gcloud storage buckets describe gs://$RACINGLINES_GCS_BUCKET --format=yaml | grep -A 30 -i lifecycle
```

The bucket has versioning on (VM deploy step 2), so the noncurrent rules are what stop old versions piling up. A
lifecycle rule acts when any rule matches, which is why the 30-day rule names its prefixes rather than covering
`archive/` too. If step 9a lists a top-level prefix not named in the rules, add it to the 30-day list. At 150 MB a
dump, 35 nightly dumps plus the launch-weekend extras are about 6 GB, which costs cents a month at list price
(*estimate*).

#### Cloudflare Access on /admin

Step 10, before `RACINGLINES_SIGNUP` leaves `off` (STAGE-1, Wed 7 Oct). Public sign-up puts players on the same
origin as `/admin`, which includes `/admin/sql` with its write toggle and `/admin/db`, and today only a password
guards it. SEC-1's per-username lock also lets anyone lock the admin handle for 15 minutes, which would block
suspend, settle and adjust during an incident. Cloudflare Access (Zero Trust free tier, up to 50 users) adds a
second factor in front of the app.

- Zero Trust > Access > Applications > Add > Self-hosted: application domain `racinglines.bet`, path `admin`
  (covers `/admin` and everything under it). Policy: Allow, Include "Emails": the owner's Gmail (and any staff
  admin's). Login method: one-time PIN to email, or Google. Session duration: 24 h.
- Leave `mcp.racinglines.bet` out for now: its clients send only a bearer token and can't answer an Access login. An
  Access service token for them is the open item below.
- Check from a private window: `https://racinglines.bet/admin` shows the Cloudflare login, `/login`, `/signup` and
  `/healthz` don't. The external monitor still passes.

If Access isn't in place when sign-up opens, the fallback is SEC-1's side (in [Fantasy accounts](fantasy-accounts.md)):
key the per-username lock on username plus IP for admin and staff handles, and refuse the `/admin/sql` write toggle
while `RACINGLINES_SIGNUP` is not `off`. The go/no-go needs one or the other.

#### HSTS

Step 11, with step 10. Cloudflare > SSL/TLS > Edge Certificates > HTTP Strict Transport Security: on, max-age 1
month, include subdomains off, preload off. Every hostname is served only through the tunnel over https, so nothing
breaks, and a short max-age keeps it reversible. The app's own security headers (frame, referrer, content-type, CSP)
are SEC-1's, not this doc's: see [What this doesn't cover](#what-this-doesnt-cover).

### P1 ops batch: merge, deploy, enable

```sh
# LOCAL (Mac) — P1 ops batch in this order, one branch per task (branch names as the workers report them).
# OPS-6 and OPS-8 are not in this batch: they merge Mon 5 Oct as runbook P2 step 0, after OWNER-5.
git checkout main && git pull
BASE=$(git rev-parse HEAD)
git merge --no-ff work/ops-1      # /healthz and its PUBLIC_PATHS entry; the engine's pool settings (every process that uses the DB)
git merge --no-ff work/ops-9      # smoke.sh: /healthz through Cloudflare
git merge --no-ff work/ops-3      # ⚠️ needs special attention: new VM backup unit, the scrubbed latest copy, bucket.sh push guard and restore argument, vm.sh restore (the backup and restore path); creates the ops CLI group
git merge --no-ff work/ops-2      # ⚠️ needs special attention: new VM units racinglines-health.service/.timer and the ops alert path; branched from work/ops-3
git merge --no-ff work/ops-4      # the Mac-only restore script; never touches the racinglines database
git merge --no-ff work/ops-5      # ⚠️ needs special attention: new VM unit racinglines-kalshi-sync (U2); writes market_links on a timer
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git diff --stat $BASE HEAD -- tests/golden      # must print nothing
git push
```

```sh
# VM (production) — from the Mac: deploy the batch by Thu 1 Oct 12:00 PDT (19:00 UTC), then smoke through Cloudflare
bash scripts/deploy/vm.sh deploy 2>&1 | tee data/backups/deploy-$(date -u +%Y%m%dT%H%M%SZ).log
bash scripts/deploy/smoke.sh https://racinglines.bet
curl -s https://racinglines.bet/healthz; echo
```

#### Installing the new units

`vm.sh deploy` already copies the unit files and runs `daemon-reload`; it doesn't enable new timers.

```sh
# VM (production) — block 0 with NAME=units first. A dump (the Kalshi timer adds links on a schedule), then enable the three timers
{
  rl ops backup --label kalshi-sync-timer
  sudo systemctl enable --now racinglines-health.timer racinglines-backup.timer racinglines-kalshi-sync.timer
  systemctl list-timers 'racinglines-*' --no-pager
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — the data_changes row (CLAUDE.md), naming the dump printed above
rl db changes --add "U2: racinglines-kalshi-sync.timer enabled on the VM (every 30 min, daily closed sync); backup data/backups/db/racinglines-before-kalshi-sync-timer-<UTC>.sql.gz" 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — first run of each by hand, then the last lines
{
  sudo systemctl start racinglines-health.service racinglines-kalshi-sync.service racinglines-backup.service
  for u in racinglines-health racinglines-kalshi-sync racinglines-backup; do journalctl -u $u -n 15 --no-pager; done
  ls -lh /opt/racinglines/data/backups/db | tail -5
  rl ops health
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

The matching `docs/data-changes.md` line goes in the next docs PR. `racinglines-fantasy.timer` is enabled the same
way once SETTLE-1 is deployed, after `rl ops backup --label staging` (STAGE-1).

#### Fallback backup (only if OPS-3 slips)

Only if OPS-3 isn't deployed by Thu 1 Oct 12:00 PDT. A full dump to `db/nightly/` once a day, checked for pg_dump's
trailer; no scrubbed copy, no rsync, no manifest. The transient timer is named `rl-…`, not `racinglines-…`, so a
deploy's pause doesn't stop (and so unload) it. It does not survive a reboot: run step 2 again after one.

```sh
# VM (production) — fallback, step 1, block 0 with NAME=fallback-backup first: the script
sudo tee /usr/local/bin/rl-fallback-backup >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
set -a; . /etc/racinglines.env; set +a
: "${RACINGLINES_GCS_BUCKET:?RACINGLINES_GCS_BUCKET is not set}"
cd /opt/racinglines && mkdir -p data/backups/db
f=data/backups/db/racinglines-nightly-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
docker compose exec -T db pg_dump --no-owner --no-privileges -U racinglines racinglines | gzip -6 > "$f"
gunzip -c "$f" | tail -n 5 | grep -q 'PostgreSQL database dump complete' || { echo "no trailer: $f"; rm -f "$f"; exit 1; }
gcloud storage cp "$f" "gs://$RACINGLINES_GCS_BUCKET/db/nightly/" --quiet
ls -1t data/backups/db/racinglines-nightly-*.sql.gz | tail -n +8 | xargs -r rm --
echo "ok: $f"
EOF
sudo chmod 755 /usr/local/bin/rl-fallback-backup && echo "rl-fallback-backup installed" | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — fallback, step 2: a daily transient timer at 10:00 UTC, then one run now
{
  sudo systemd-run --unit=rl-fallback-backup --uid=racinglines --on-calendar='*-*-* 10:00:00 UTC' /usr/local/bin/rl-fallback-backup
  sudo systemctl start rl-fallback-backup.service
  sudo journalctl -u rl-fallback-backup -n 5 --no-pager
  systemctl list-timers rl-fallback-backup.timer --no-pager
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — fallback, step 3: once OPS-3's racinglines-backup.timer is enabled, stop the stopgap
{ sudo systemctl stop rl-fallback-backup.timer; systemctl list-timers --all --no-pager | grep -E 'backup'; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

#### Launch-weekend backup drop-in

```sh
# VM (production) — install by Thu 8 Oct 16:00 UTC (09:00 PDT), block 0 with NAME=launch-backups first: the backup timer also at 04:00, 16:00 and 22:00 UTC
{
  sudo mkdir -p /etc/systemd/system/racinglines-backup.timer.d
  printf '[Timer]\nOnCalendar=*-*-* 04,16,22:00:00 UTC\n' | sudo tee /etc/systemd/system/racinglines-backup.timer.d/launch-weekend.conf
  sudo systemctl daemon-reload && sudo systemctl restart racinglines-backup.timer
  systemctl list-timers racinglines-backup.timer --no-pager
} 2>&1 | sudo -u racinglines tee -a "$LOG"
```

A second `OnCalendar=` in a drop-in adds to the unit's 10:00 UTC line rather than replacing it; `list-timers` shows
the next of the four.

```sh
# VM (production) — remove on Tue 13 Oct after the 04:00 UTC run (vm.sh deploy doesn't remove drop-ins)
{ sudo rm /etc/systemd/system/racinglines-backup.timer.d/launch-weekend.conf && sudo systemctl daemon-reload && sudo systemctl restart racinglines-backup.timer; systemctl list-timers racinglines-backup.timer --no-pager; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

### OWNER-7: resize to e2-medium

Only if DEC-17 says yes: Mon 5 Oct 13:00–15:00 PDT (20:00–22:00 UTC), after DEC-17 is signed at 12:00 PDT, and not
while the Monday settle or reconcile commands run. ⚠️ It restarts every unit on the VM.

```sh
# VM (production) — block 0 with NAME=resize first: a dump
rl ops backup --label resize 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# LOCAL (Mac) — a disk snapshot, then stop, resize, start (2–3 minutes down)
gcloud compute disks snapshot racinglines-vm --project=racinglines --zone=us-west1-b --snapshot-names=racinglines-vm-before-resize-$(date -u +%Y%m%d)
gcloud compute instances stop racinglines-vm --project=racinglines --zone=us-west1-b
gcloud compute instances set-machine-type racinglines-vm --project=racinglines --zone=us-west1-b --machine-type=e2-medium
gcloud compute instances start racinglines-vm --project=racinglines --zone=us-west1-b
```

```sh
# VM (production) — from the Mac: check
bash scripts/deploy/vm.sh status
bash scripts/deploy/smoke.sh https://racinglines.bet
curl -s https://racinglines.bet/healthz; echo
```

Rollback: the same three `gcloud` lines with `--machine-type=e2-small`. Afterwards add a `data_changes` note and
update the machine type in [VM deploy](vm-deploy.md) (DOC-2).

### Go/no-go evidence for the reliability lines

| Go/no-go line | Evidence |
|---|---|
| PR #71 and OPS-8 in the running sha; no paused timers | `vm.sh status` (no PAUSED line) |
| `vm.sh public off`; loopback only | The two OWNER-4 check blocks |
| APP_SECRET set; trading flags absent | The OWNER-4 VM block; `rl ops health` config checks |
| Two consecutive nightly dumps in the bucket; the latest copy scrubbed; the bucket locked down | `gcloud storage ls -l gs://$RACINGLINES_GCS_BUCKET/db/nightly/` (the newest lines); `"scrubbed": true` in `db/manifest.json`; step 9a's describe line |
| Launch-weekend backup drop-in installed | `systemctl list-timers racinglines-backup.timer` shows the 16:00 or 22:00 UTC run next |
| Restore drills done, RTO recorded: the Mac load (OPS-4) and path B from a snapshot (B-1) | The two timings tables above |
| Snapshot schedule attached | `gcloud compute disks describe racinglines-vm … --format='value(resourcePolicies)'` |
| Health timer green; a test alert reached the phone | `rl ops health`; the push in the log |
| External uptime monitor on `/healthz`, at least 99% since the cutover; dead-man and tunnel notification configured | The monitor's report; Healthchecks.io shows "up"; the Cloudflare notification is listed |
| Cloudflare Access in front of `/admin`, or SEC-1's fallback (admin lock keyed on username plus IP, `/admin/sql` writes refused while sign-up is on) | A private window: `/admin` shows the Cloudflare login; or the SEC-1 tests |
| HSTS on | `curl -sI https://racinglines.bet/login` lists a `strict-transport-security` header |
| Load run 2 passed | The locust CSV and the VM block after it ([Load run](#load-run-ops-11)) |
| Settlement replay on R16 data passed, elapsed time recorded | The REPLAY-1 log on the Mac ([Settlement replay](#settlement-replay-on-r16-data-replay-1)) |
| Kalshi under 35 min, recorder under 5 min, disk under 70% | `curl -s https://racinglines.bet/healthz` |
| Swap on, or resized per DEC-17 | `swapon --show; free -m` |
| R16 incidents closed or accepted in writing | DRY-2's section in this doc |

---

## Task list

The merge order for this doc's code tasks: the P1 ops batch OPS-1 → OPS-9 → OPS-3 → OPS-2 → OPS-4 → OPS-5 (Thu 1
Oct), then OPS-6 → OPS-8 on Mon 5 Oct (runbook P2 step 0), with OPS-8 before ACC-1. OPS-2 depends on OPS-3 (it adds
`health` to the `racinglines/cli/ops.py` that OPS-3 creates), so its branch starts from `work/ops-3`. OPS-11 (a Mac-only script) merges
on its own by Sun 4 Oct. Branches are `work/<task id lowercase>` (`work/ops-1`, …). Every task passes `racinglines check`, `python -m pytest -m "not live"` and
`mkdocs build --strict` before merge, with `tests/golden` unchanged.

| Task | What | Role | Model | Files | Size | Depends on | Due | Verify | ⚠️ |
|---|---|---|---|---|---|---|---|---|---|
| OWNER-1 | Merge PR #71 and deploy it | owner | owner | `scripts/deploy/vm.sh`, `deploy/vm/update.sh` (the PR's diff: `vm.sh`, `CLAUDE.md`, `docs/vm-deploy.md`) | S | — | Wed 30 Sep 12:00 PDT | `vm.sh status`: its sha, no PAUSED line | ⚠️ needs special attention: the VM deploy path and timer handling; replaces the freeze |
| OWNER-4 | VM cutover; `vm.sh public off`, APP_SECRET, `RACINGLINES_OPS_NTFY_TOPIC` | owner | owner | `/etc/racinglines.env` (VM), the tunnel's `racinglines.bet` hostname | M | OWNER-1 | Wed 30 Sep | The OWNER-4 blocks; smoke through Cloudflare | ⚠️ needs special attention: moves production and starts the recorder and signals on the VM |
| SCOUT-1 | Read-only VM baseline | scout | Haiku | — | S (~6 calls) | OWNER-4 | Wed 30 Sep | A findings table, NOT FOUND where missing | — |
| OPS-1 | `/healthz` (async, cached); the engine's `pool_pre_ping`, `pool_recycle` and pool size (G15) | implement | Sonnet | `racinglines/web/health.py` (new), `racinglines/web/app.py`, `racinglines/db/config.py`, `tests/test_health.py` (new) | S (~12 calls, 4 files) | — | Wed 30 Sep | `python -m pytest tests/test_health.py -m "not live"` | — |
| OPS-2 | `racinglines ops health` and the health timer, including the hung-step, closed-sync, live-step and mail checks | own | Opus | `racinglines/ops/health.py` (new), `racinglines/cli/ops.py` (adds `health` to OPS-3's file), `racinglines/markets/alerts.py`, `deploy/vm/systemd/racinglines-health.service`/`.timer` (new), `deploy/vm/racinglines.env.example`, `tests/test_ops_health.py` (new) | M (~26 calls, 7 files) | OPS-1, OPS-3 (branches from `work/ops-3`) | Thu 1 Oct 12:00 PDT | The pytest line above; the recorder-stop test on the VM | ⚠️ new VM systemd units |
| OPS-3 | Nightly backup (pipefail, trailer check), scrubbed latest copy, rsync without deletes, `bucket.sh` push guard and restore argument | own | Opus | `racinglines/ops/__init__.py`, `racinglines/ops/backup.py`, `racinglines/cli/ops.py` (all new; registers the `ops` group), `racinglines/cli/__init__.py` (`GROUPS`), `deploy/vm/systemd/racinglines-backup.service`/`.timer` (new), `scripts/cloud/bucket.sh`, `scripts/deploy/vm.sh` (`restore` passes a dump through), `tests/test_ops_backup.py` (new) | M (~32 calls, 9 files) | — (needs DEC-19) | Thu 1 Oct 12:00 PDT | `python -m pytest tests/test_ops_backup.py -m "not live"`; two nightly dumps in the bucket | ⚠️ VM systemd unit and the backup path |
| OPS-4 | `scripts/ops/restore_scratch.sh` and the first timed drill | implement | Sonnet | `scripts/ops/restore_scratch.sh` (new) | S (~8 calls, 1 file) | OPS-3 | Sun 4 Oct | The script prints counts and timings; the timings table filled in | — |
| OPS-5 | U2: `racinglines-kalshi-sync` every 30 min (`TimeoutStartSec=15min`), closed sync in the 20:05 UTC run | own | Opus | `deploy/vm/systemd/racinglines-kalshi-sync.service`/`.timer` (new), `racinglines/cli/markets.py`, `tests/test_cli_markets.py` (new), `docs/todo.md` | M (~20 calls, 5 files) | EXCH-0 | Thu 1 Oct 12:00 PDT (before the book opens at 20:30) | `python -m pytest tests/test_cli_markets.py -m "not live"`; on the VM a run every 30 min, `KXF1RACE-BAH26` `synced_at` under 35 min | ⚠️ new VM unit that writes market_links |
| OPS-6 | Recorder exits after 10 failed loops; signals `TimeoutStartSec=45min`; live-f1@ `TimeoutStartSec=20min`; docker log cap | implement | Sonnet | `racinglines/cli/f1.py`, `deploy/vm/systemd/racinglines-recorder.service`, `deploy/vm/systemd/racinglines-signals.service`, `deploy/vm/systemd/racinglines-live-f1@.service`, `deploy/vm/compose.override.yml`, `tests/test_recorder_loop.py` (new) | S (~11 calls, 6 files) | — | Branch Wed 30 Sep; merged and deployed Mon 5 Oct (after OWNER-5) | `python -m pytest tests/test_recorder_loop.py -m "not live"`; `systemctl show racinglines-signals racinglines-live-f1@2026-17 -p TimeoutStartUSec` on the VM | ⚠️ systemd unit edits, one of them a live-event unit; the first deploy recreates the Postgres container |
| OPS-7 | VM hardening. At the cutover: snapshot schedule, external uptime monitor, tunnel notification, ntfy topic, bucket lockdown and lifecycle. By Thu: swap, journald, updates, Healthchecks.io, secrets copy. Before sign-up: Cloudflare Access on `/admin`, HSTS. Plus the launch-weekend backup drop-in (Thu 8 – Tue 13 Oct) and, only if OPS-3 slips, the fallback backup | owner | owner | `/swapfile`, `/etc/systemd/journald.conf` (as a drop-in), GCE policy `racinglines-daily`, the bucket's settings, Cloudflare notifications, Access and HSTS, the uptime monitor, `/etc/racinglines.env`, the backup timer drop-in | S (~1.5 h over four sittings) | OWNER-4 | Cutover part Wed 30 Sep; the rest Thu 1 Oct 18:00 PDT; Access and HSTS Wed 7 Oct before STAGE-1 | The checks inside each block; the test push; the monitor's first report | ⚠️ VM configuration and the admin's access path |
| OPS-8 | Migration guard, dump before `--migrate`, smoke through Cloudflare | own | Opus | `scripts/deploy/vm.sh`, `deploy/vm/update.sh`, `scripts/deploy/smoke.sh` | M (~18 calls, 3 files) | OWNER-1, OPS-1 | Branch Wed 30 Sep; merged and deployed Mon 5 Oct (after OWNER-5), before ACC-1 merges (OWNER-8, Tue 6 Oct) | A fake-`gcloud` dry run of the four cases in the table above, as PR #71 was tested | ⚠️ needs special attention: the deploy path; makes every VM migration an explicit, backed-up owner step |
| OPS-9 | `smoke.sh`: `/healthz` through Cloudflare, freshness, legal pages and `/signup` behind arguments | implement | Sonnet | `scripts/deploy/smoke.sh` | S (~6 calls, 1 file) | OPS-1 | Wed 30 Sep | `bash scripts/deploy/smoke.sh http://127.0.0.1:8000`, then against https://racinglines.bet | — |
| OPS-11 | Load run: `scripts/ops/loadtest.py` (locust), browse-and-bet on Mon 5 Oct, orders in STAGE-1 ([Load run](#load-run-ops-11)) | implement (script) · owner (runs) | Sonnet | `scripts/ops/loadtest.py` (new) | S (~8 calls, 1 file) | OPS-1; for the STAGE-1 run, the P2 fantasy batch | Script Sun 4 Oct; run 1 Mon 5 Oct 08:00–08:15 PDT (before OWNER-5); run 2 in STAGE-1 part B (5o) | The pass criteria in Load run; the numbers in DRY-2 and the go/no-go | — |
| DRY-1 | R16 closed reliability dry run | owner | owner + Haiku (log readback) | `/opt/racinglines/data/backups/r16-dryrun-<UTC>.log` (VM) | weekend | OPS-2, OPS-3, OPS-5, OPS-7 | Thu 1 Oct 18:00 PDT – Sun 4 Oct 12:00 PDT | The exit criteria above | — |
| DRY-2 | R16 retro: incidents, alert noise, backup and restore timings, memory and disk peaks | own | Opus | `docs/vm-reliability.md` | S (~8 calls) | DRY-1, OPS-4 | Mon 5 Oct (memory by 10:00 PDT) | The results section with every number | — |
| OWNER-7 | Resize to e2-medium if DEC-17 says yes | owner | owner | GCE instance `racinglines-vm` | S (~15 min, 2–3 min down) | OWNER-6 | Mon 5 Oct 13:00–15:00 PDT | smoke, `free -m` | ⚠️ restarts every unit on the VM |
| OPS-10 | R17 on-call: phone alerts, deploys in windows, incident log | owner | owner + Haiku | `/opt/racinglines/data/backups/r17-oncall-<UTC>.log` (VM) | weekend | LAUNCH-1 | Thu 8 – Sun 11 Oct | No unplanned outage over 15 min in the health log | — |

---

## Names used across these docs

This subset of the conventions block is copied word for word. The master copy is in
[Fantasy soft launch](fantasy-launch.md).

```text
TERMS
- account type = users.account_type: player (signed up through /signup), staff (owner, admin, collaborators, R16 testers), demo (maker, taker), system (polymarket-takers). Only players appear in leaderboards and fantasy stats.
- closed dry run = R16, Thu 1 Oct to Sun 4 Oct, 5 or fewer admin-created staff tester accounts, no sign-up. staging rehearsal = Wed 7 Oct on the VM with RACINGLINES_SIGNUP=invite and tester codes in season 2026-dryrun. soft launch = RACINGLINES_SIGNUP=invite from Thu 8 Oct 18:00 PDT (Fri 9 Oct 01:00 UTC). open sign-up = RACINGLINES_SIGNUP=open (not before Thu 22 Oct).
- Times: owner-facing times in PDT with UTC in brackets; systemd OnCalendar in UTC.

TABLES: one additive Alembic revision fantasy_schema_v1, file migrations/versions/2026MMDD_<rev>_fantasy_schema_v1.py, down_revision = the single head at branch time (c8e3f6a2d4b1 on 29 Sep)
- bankroll_entries: id, season_id, user_id, ts, kind (grant|stake|payout|refund|trade|fee|settle|book_pnl|adjust), amount Numeric(12,2) signed, ref_table, ref_id, note, created_by. UNIQUE(ref_table, ref_id, kind). balance = SUM(amount).
- fantasy_positions: id, season_id, user_id, market_link_id, exchange, yes_shares, no_shares, cost, fees, status (open|settled|void), outcome Boolean NULL, payout, settled_at. UNIQUE(season_id, user_id, market_link_id).
- fantasy_stats: season_id, user_id, venue (all|kalshi|polymarket|book), role, starting_bankroll, balance, equity, pnl, roi, turnover, bets, settled, won, hit_rate, max_drawdown (positive number), sharpe (x sqrt(24); NULL under 4 events), events, rank, computed_at. PK(season_id, user_id, venue).

ENV (in /etc/racinglines.env on the VM; every new one is off or safe by default)
RACINGLINES_FANTASY=0|1 (master switch: nav, /fantasy, /leaderboard); RACINGLINES_SIGNUP=off|invite|open (default off); RACINGLINES_SIGNUP_CAP=50; RACINGLINES_FANTASY_BOOK=0|1; RACINGLINES_FANTASY_EXCHANGE=0|1; RACINGLINES_FANTASY_EXCHANGE_MAKERS=0 (stays 0 this sprint); RACINGLINES_MAIL_BACKEND=log|smtp (default log); RACINGLINES_SMTP_HOST=smtp.protonmail.ch; RACINGLINES_SMTP_PORT=587; RACINGLINES_SMTP_USER=noreply@racinglines.bet; RACINGLINES_SMTP_TOKEN (secret, never in git); RACINGLINES_MAIL_FROM=racinglines <noreply@racinglines.bet>; RACINGLINES_MAIL_REPLY_TO=support@racinglines.bet; RACINGLINES_MAIL_DAILY_CAP=200; RACINGLINES_TURNSTILE_SITEKEY and RACINGLINES_TURNSTILE_SECRET (empty = widget off); RACINGLINES_OPS_NTFY_TOPIC (ops alerts, separate from RACINGLINES_NTFY_TOPIC for market alerts); RACINGLINES_HEALTHCHECK_PING_URL (dead-man ping). Existing: RACINGLINES_URL=https://racinglines.bet (base for mail links); RACINGLINES_GCS_BUCKET; APP_SECRET (must be set); MAX_STAKE (per-bet cap, F$100); RACINGLINES_KALSHI_SPRINTS; RACINGLINES_CANCELLED_RACE_RULES (not changed by fantasy); RACINGLINES_DEMO_USERS; RACINGLINES_DEMO_CONTEXT. Never touched: POLYMARKET_TRADING_ENABLED, KALSHI_TRADING_ENABLED.

COOKIES: rl_session = uid|expires|sid|epoch|HMAC (epoch = users.session_epoch; bumping it ends every session). rl_csrf = signed double-submit token for unauthenticated forms.

ROUTES
Public (add to PUBLIC_PATHS): /signup, /verify/{token}, /verify/resend, /password/forgot, /password/reset/{token}, /terms, /privacy, /rules, /healthz.
Admin: /admin/fantasy, /admin/fantasy/seasons/{id}, /admin/fantasy/invites, /admin/fantasy/members/{user_id}, /admin/fantasy/settle.

CLI: racinglines fantasy season create|set|close|list; racinglines fantasy invite create|revoke|list; racinglines fantasy tick [--full]; racinglines fantasy stats [--full]; racinglines mail test --to <addr>; racinglines ops health [--alert]; racinglines ops backup [--label <task>].

CODE: racinglines/fantasy/{seasons,ledger,book,exchange,settle,stats}.py; racinglines/markets/books.py (read-only live order books; does not import polymarket/trade.py); racinglines/web/{accounts,mailer,health}.py; racinglines/ops/{health,backup}.py; racinglines/cli/{fantasy,ops,mail}.py; TERMS_VERSION = '2026-10-08' in racinglines/web/accounts.py. Templates: signup, verify, forgot, reset, account, terms, privacy, rules, fantasy, fantasy_markets, fantasy_book, leaderboard, admin_fantasy (.html); mail/verify.txt, mail/reset.txt, mail/welcome.txt, mail/email_changed.txt. Tests: tests/test_auth.py, test_signup.py, test_mailer.py, test_fantasy_schema.py, test_fantasy_seasons.py, test_ledger.py, test_private_book.py, test_fantasy_book.py, test_fantasy_exchange.py, test_fantasy_settle.py, test_fantasy_stats.py, test_health.py, test_ops_health.py, test_ops_backup.py; fixtures in tests/fixtures/fantasy/.

activity_log actions (new): signup, signup_rejected, email_verify, verify_resend, password_reset_request, password_reset, password_change, email_change, account_delete, role_override, bankroll_adjust, member_suspend, invite_create, invite_revoke, season_update, fantasy_order, fantasy_order_rejected, fantasy_settle, fantasy_resettle, mail_sent, mail_failed.

SYSTEMD (deploy/vm/systemd/): racinglines-health.service + .timer (every 5 min); racinglines-backup.service + .timer (daily 10:00 UTC); racinglines-kalshi-sync.service + .timer (every 30 min, daily closed sync; this is U2); racinglines-fantasy.service + .timer (every 10 min: close, settle, stats). Existing and unchanged in name: racinglines-web, racinglines-recorder, racinglines-signals(.timer), racinglines-live-f1@<event>(.timer), racinglines-live-dh@, racinglines-mcp, cloudflared. GCE: snapshot resource policy racinglines-daily (14-day retention) on disk racinglines-vm.

BACKUPS: pre-change data/backups/db/racinglines-before-<task>-<UTC>.sql.gz (CLAUDE.md); nightly data/backups/db/racinglines-nightly-<UTC>.sql.gz (7 kept on disk) and gs://$RACINGLINES_GCS_BUCKET/db/nightly/ (35-day lifecycle); owner-run logs /opt/racinglines/data/backups/<name>-<UTC>.log.

EMAIL (Proton Mail Plus, 10-address cap): admin@racinglines.bet (owner mailbox), support@racinglines.bet (catch-all target and reply-to), noreply@racinglines.bet (app sender, holds the SMTP token). DMARC reports go to the rua address from Cloudflare DMARC Management.
```

---

## What this doesn't cover

- The fantasy features themselves: sign-up, seasons, the ledger and stats are in [Fantasy accounts](fantasy-accounts.md);
  exchange paper trading, the private book and settlement are in [Fantasy trading](fantasy-trading.md).
- Mail DNS and the Proton setup: [Email setup](email-setup.md).
- The launch-day command blocks, the off switch and the full go/no-go: [Fantasy launch runbook](fantasy-runbook.md).
- High availability. There is one VM in one zone with one tunnel connector. A second region, a standby or a managed
  database is U12 (a Google Cloud move, December) and the [Google Cloud proposal](google-cloud.md).
- A staging environment separate from production. The staging rehearsal runs on the production VM in season
  `2026-dryrun`.
- The Mac's own backups, and the cloud sessions' copy of the old bucket.
- Security review of the app beyond the config checks, Cloudflare Access and HSTS here. SEC-1 in
  [Fantasy accounts](fantasy-accounts.md) covers auth hardening. Two items this review raised belong there, not
  here: a constant-time login (one scrypt verify against a dummy hash when the handle or email is unknown, inactive
  or deleted, with a timing test), and the app's security headers (`X-Frame-Options: DENY` or
  `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a CSP allowing
  self plus `challenges.cloudflare.com` for Turnstile).
- The `/privacy` wording on backup retention: LEGAL-1 writes it from the numbers under
  [What is kept where](#what-is-kept-where).
- Cost review beyond the rough monthly figures marked as estimates.

## Open items

- **SCOUT-1:** which units and timers were enabled on 29 Sep; the VM's DB size after the Kalshi tape load; which env
  keys exist; cloudflared's restart policy; whether journald was already persistent.
- **The tunnel's second connector or a standby.** A second `cloudflared` on the same VM guards only against a process
  crash. A connector elsewhere would serve a different database, so it is only safe with a shared DB. For now the
  answer is recovery path B. Owner's call whether that is enough for the soft launch.
- **Cloudflare Access for `mcp.racinglines.bet`.** `/admin` gets Access before sign-up opens (step 10); the MCP host
  doesn't yet, because its clients send only the bearer token ([MCP server](mcp.md)) and can't answer an Access
  login. An Access service token for those clients would add the second factor; it needs a check that each MCP
  client can send the two service-token headers.
- **Cloud sessions and the full dumps** (DEC-19). The scrubbed latest copy is what cloud sessions should read. Whether
  their credentials can also read `db/nightly/` and `db/before/` depends on how DEC-19 grants them access; if they
  can, the full dumps move to a second, owner-only bucket or a managed folder with its own IAM.
- **When to move off one VM:** the triggers proposed are more than about 200 active players, memory peaks over 80% on
  e2-medium, or U12 in December.
- **`OOMScoreAdjust=` on the oneshot units** (Capacity), in no task yet.
- **Path C (full rebuild) is not rehearsed.** A timed rebuild into a scratch project after the sprint would turn its
  2–3 h estimate into a number.
- **The restore drill timings** (OPS-4, ACC-2, B-1), **the load run numbers** (OPS-11) and **DRY-2's results
  section** are still to fill in.
- **Decisions this doc depends on:** DEC-17 (resize), DEC-18 (targets) and DEC-19 (bucket), with DEC-18 and DEC-19
  due Thu 1 Oct 12:00 PDT ([Roadmap](todo.md#owner-decisions)).
- **Unverified details:** Kalshi's read rate limits (EXCH-0 records the headers); the dashboard menu names at
  Healthchecks.io, Cloudflare (Access, HSTS) and the uptime monitor, and which free plans offer a webhook or ntfy
  integration and a keyword check; whether the closed sync fits in 10 minutes (OPS-5 times it); whether `gcloud` accepts a snapshot `--start-time` that is not on the hour (11:00
  is used, so this doesn't bite); `needrestart`'s default mode on the VM (SCOUT-1's `apt-config` output and step 3
  settle it).
- **The `--year 2026` rollover** before Tue 1 Dec 2026 (G9).
