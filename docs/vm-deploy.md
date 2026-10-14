# VM deploy

> How a change reaches racinglines.bet: merge to `main`, and GitHub Actions runs `vm.sh deploy` on the VM. Staging first, data never by merge.

racinglines.bet runs on one Compute Engine VM, `racinglines-vm`: Postgres in docker, systemd units for the web app,
the recorders and the live-event steps, and a Cloudflare tunnel (the VM opens no inbound port). Every command on
this page runs from the owner's Mac through `scripts/deploy/vm.sh`, which reaches the VM over SSH through IAP; the
VM itself is never edited by hand.

!!! warning "Merging is deploying"
    Every merge to `main` that changes more than docs deploys to production. A PR that adds an Alembic migration
    **runs that migration on the VM the moment it merges**: take `vm.sh backup <purpose>` first and merge only with
    the owner's sign-off for that migration, in the same conversation turn. Trading flags
    (`POLYMARKET_TRADING_ENABLED`, `KALSHI_TRADING_ENABLED`) are never set by any script here.

## Ship a change

The normal path, start to finish. Steps 1 and 2 are the same for every change; step 3 is where a merge becomes a
deploy.

### Step 1: check it locally

CI runs the regression suite only (`tests.yml`, below), and without the pinned fixtures every golden test skips
there. Run the full set where the fixtures are, before asking for a merge.

```bash title="LOCAL (Mac)"
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
```

The last line of each: `racinglines check` ends with its pass count, pytest with `passed` and the skip count, and a
strict docs build prints nothing at all when it is clean (a `WARNING` line fails it).

### Step 2: put it on staging and look at it

A merge or push to the `staging` branch deploys `staging.racinglines.bet` and nothing else
([Staging](#staging)). Staging deploys are allowed during a live window.

```bash title="LOCAL (Mac)"
git push origin <branch>:staging
```

Watch the `staging-deploy` run in the repo's Actions tab, then open `https://staging.racinglines.bet` (the top
bar shows a STAGING pill). Its last job step runs the smoke check against the public hostname and expects the
staging header; its passing line is:

```text title="What you should see (last line of the smoke check)"
ok    env  X-Racinglines-Env: staging
...
smoke: all checks passed (https://staging.racinglines.bet)
```
<!-- scripts/deploy/smoke.sh:55 and :91 -->

### Step 3: open the PR against `main` and merge it

```bash title="LOCAL (Mac)"
gh pr create --base main --title "[track] what it does" --body "Deploys: yes. After the deploy the VM needs: nothing."
```

Every PR description says whether merging it deploys and names anything the VM needs afterwards (a backup, a data
step under `scripts/vm/`): code arrives by merge, data never does
([Code from GitHub, data on the VM](#code-from-github-data-on-the-vm)). The owner merges (squash, on GitHub,
`gh pr merge N --squash --delete-branch`), and the `main-merge-gate` workflow deploys the merged commit. Watch
it in the Actions tab; the `deploy-production` job's log ends with the VM-side smoke check:

```text title="What you should see (end of the deploy-production job)"
[vm HH:MM:SS] timers running (one 'active' per timer):
active
active
[vm HH:MM:SS] docs site (/docs)
[docs HH:MM:SS] docs: built site/ from <sha> <subject>
[vm HH:MM:SS] smoke check on the VM
...
smoke: all checks passed (http://127.0.0.1:8000)
```
<!-- scripts/deploy/vm.sh:272-279, deploy/vm/build_docs.sh:41, scripts/deploy/smoke.sh:91 -->

Keep code merges out of a live race window unless the owner says otherwise: the deploy pauses and resumes the live
timers by itself ([What a deploy does to the timers](#what-a-deploy-does-to-the-timers)), but the web app restarts
for a few seconds.

### Step 4: when CI can't, deploy by hand

The same path, from the Mac. A bad deploy is undone by deploying the previous commit.

```bash title="LOCAL (Mac)"
bash scripts/deploy/predeploy.sh --prod main        # vm.sh deploy main, then the smoke check on https://racinglines.bet
bash scripts/deploy/vm.sh deploy <ref>              # a branch or commit, without the public smoke check
```

## The flow

Since 2026-10-01 the live repo is the public `lalligagger/racinglines-public` (base `main`) and **merging to
`main` deploys to the VM by itself**, through the GitHub Actions workflow `main-merge-gate`
(`.github/workflows/predeploy.yml`):

| Job | Runs on | What it does |
|---|---|---|
| `detect-docs-only` | every PR to `main` and every push to `main` | Lists the changed files (the PR's diff, or `HEAD^..HEAD` on a push). If every one is under `docs/` or ends in `.md` (README, CLAUDE.md, mkdocs.yml too), the change is docs-only and the two jobs below are skipped: **a docs-only merge deploys nothing** |
| `predeploy-staging` | PRs and pushes that are not docs-only | `scripts/deploy/predeploy.sh --staging <sha>`: the smoke check (`scripts/deploy/smoke.sh`, valid sign-ins only) against `https://staging.racinglines.bet`. A failure comments on the PR. It checks whatever staging serves ([Staging](#staging)); it does not deploy or run the PR's code |
| `deploy-production` | pushes to `main` only, after `predeploy-staging` passed | `scripts/deploy/predeploy.sh --prod <sha>`: `vm.sh deploy <sha>` (below), then the smoke check against `https://racinglines.bet`. Uses the `production` environment's secrets (`GCP_SERVICE_ACCOUNT_KEY`, `GCP_PROJECT_ID`, `VM_NAME`, `VM_ZONE`); without them the job prints a skip line and deploys nothing |

Two more workflows run beside it:

| Workflow | File | What it does |
|---|---|---|
| `tests` | `.github/workflows/tests.yml` | `python -m pytest -m "not live" -q -ra` on every PR into `main` or `staging` and every push to either, with Postgres as a service and `RACINGLINES_PROGRESS_SEC=0`. The pinned fixtures are not in the public repo, so the fixture-based (golden) tests skip here: a green badge is not the golden check |
| `staging-deploy` | `.github/workflows/staging.yml` | A push to `staging` (or a manual run with a `ref`): `vm.sh staging deploy <sha>`, then the smoke check against `https://staging.racinglines.bet` with `SMOKE_EXPECT_ENV=staging`, retried up to 3 times 30 s apart ([Staging](#staging)) |

!!! note "CI runs no `racinglines check`, no `mkdocs build` and no golden tests"
    Those stay local ([Ship a change](#ship-a-change)). A PR that is green on GitHub has passed the smoke check and
    the fixture-free part of the suite, nothing more. Cloud sessions can't push changes to `.github/workflows/*`
    (the token lacks the workflow scope): ship a patch for the owner.

**The smoke check** (`scripts/deploy/smoke.sh <url>`, any machine with curl) signs in as the demo accounts
(`SMOKE_PASSWORD`, default the public demo password), checks `/login`, that a request without credentials gets 401,
the main pages for maker and taker, and that `/book/quotes` is maker-only. Under the alpha layout (the app's
`X-Racinglines-Layout: alpha` header, [Alpha layout](alpha-layout.md)) it checks `/trade` and `/history` instead and
expects the archived `/live` and `/book` pages to answer 404. It makes GET requests only and **never sends a wrong
password**: that would warm the app's 15-minute failed-login throttle and fail the real checks
(`smoke.sh --auth-throttle` is the opt-in diagnostic; if the throttle was warmed, wait 15 minutes).

`staging.racinglines.bet` is the required public staging route. If the hostname is absent or misconfigured, fix the
tunnel's public hostname before a prod deploy. A temporary trycloudflare URL
(`bash scripts/deploy/staging.sh smoke 8010`) is for local ad hoc testing only, never the release path.

## What a deploy does to the timers

`vm.sh deploy` never refuses for a live event and has no `--force`. In order:

1. **Checks before touching anything.** The VM checkout must fetch from the public repo (`vm.sh repoint` sets that
   once), and production and staging must not share a venv ([Separate venvs](#separate-venvs)). A failure here
   prints `nothing paused, nothing deployed`.
2. **Pauses the active timers** (every `racinglines-*.timer`: live-event steps, signals, the recorders, schedule
   sync, forecast refresh) and writes their names to `/var/lib/racinglines/deploy-paused` on the VM first, so a
   deploy that dies half-way leaves a record: `vm.sh status` shows it and the next `vm.sh deploy` resumes them too.
3. **Waits up to 5 minutes** for a step already running. A signals pass that is the only step still running after
   that is stopped (each profile's writes are one transaction, inserts are `ON CONFLICT DO NOTHING`, and the resumed
   timer runs a fresh pass). Any other step still running means nothing is deployed and the timers resume; the
   message names the stuck unit.
4. **Deploys**: `deploy/vm/untrack.sh` (keeps on disk the files the new commit stops tracking), then
   `deploy/vm/update.sh <ref>` (checkout, `pip install`, `alembic upgrade head`, `racinglines db seed`), then the
   units are reinstalled and the running services restarted (`racinglines-web`, `racinglines-recorder`,
   `racinglines-mcp`). Deploy restarts only services that are already running, so it never starts a second recorder.
5. **Catch-up step, then resume.** Each paused live event gets one step (`systemctl start` of its service, up to 5
   minutes), then every paused timer starts again. Every step is idempotent and catches up: an F1 live step does
   every update that fell due during the pause, its crowd batch covers the whole window since the last update
   (`pipelines/live_f1.py` `due`, `_crowd`), and signals inserts with `ON CONFLICT DO NOTHING`.
6. **Docs site and smoke check.** `deploy/vm/build_docs.sh` rebuilds `site/` (served at `/docs`; fail-soft: a
   failed build keeps the old site), then `smoke.sh http://127.0.0.1:8000`.

```text title="What you should see (a deploy with two timers paused)"
[vm HH:MM:SS] pausing: racinglines-live-auto.timer racinglines-signals.timer
[vm HH:MM:SS] waiting up to 5 minutes for a step in progress
[vm HH:MM:SS] deploy <ref>
[update HH:MM:SS] checkout <ref> -> <sha12> (was <sha12>)
[update HH:MM:SS] pip install
[update HH:MM:SS] database up
[update HH:MM:SS] alembic upgrade head
[update HH:MM:SS] db seed (reference rows for every sport schema; idempotent upserts)
[update HH:MM:SS] done: <sha> <subject>
[vm HH:MM:SS] catch-up step: racinglines-live-auto.service
[vm HH:MM:SS] resuming: racinglines-live-auto.timer racinglines-signals.timer
[vm HH:MM:SS] timers running (one 'active' per timer):
```
<!-- scripts/deploy/vm.sh:234-272, deploy/vm/update.sh:30-45 -->

!!! warning "If the update fails after the checkout moved, the timers stay paused on purpose"
    No step may run on a half-updated checkout. Fix and deploy again (the next deploy resumes them), then check
    `bash scripts/deploy/vm.sh status`. A failure before the checkout moved (a fetch, an unknown ref) changed
    nothing, so those timers resume at once: `deploy failed before the checkout changed: nothing deployed, timers resumed`.

Other things to know: a running downhill poll loop (`racinglines-live-dh@<event>`) gets a `WARNING` line, not a
pause: deploy doesn't restart it, so it keeps the code it loaded. The recorder's restart costs at most one order-book
snapshot; prices and trades are unaffected, because they are fetched from the exchanges' own history. Before each
checkout, `untrack.sh` backs up to `data/backups/files/` whatever the current commit tracks and the new one doesn't,
and untracks it, so moving between histories keeps `data/` on disk.

## What's in the repo

| File | What it is |
|---|---|
| `scripts/deploy/vm.sh` | Run on your Mac (and by CI for `deploy` and `staging deploy`). Its usage header lists every subcommand; the ones you reach for are `deploy [ref]`, `status`, `logs [unit]`, `backup <purpose>`, `live <event>\|auto [off]`, the timer switches (`record`, `record fastf1`, `pm-sync`, `forecast`, `schedule`), `switch <NAME> on\|off`, `docs`, `staging …`, `mirror …`, `ssh`. Printed with no arguments |
| `scripts/deploy/predeploy.sh --staging\|--prod\|--all [ref]` | The gate CI runs: `--staging` smoke-checks staging, `--prod` runs `vm.sh deploy <ref>` then smoke-checks racinglines.bet |
| `scripts/deploy/smoke.sh <url>` | The smoke check (any machine with curl) |
| `scripts/deploy/f1_push.sh <event>`, `f1_push_auto.sh install\|remove` | F1 sessions from the Mac to the VM during a race weekend ([Live events on the VM](#live-events-on-the-vm)) |
| `.github/workflows/predeploy.yml`, `staging.yml`, `tests.yml` | `main-merge-gate`, `staging-deploy` and `tests` ([The flow](#the-flow)) |
| `deploy/vm/setup.sh` | One-time VM setup, run by `vm.sh setup`: packages, the `racinglines` user, a read-only deploy key, `/opt/racinglines` on `main`, a Python 3.14 venv (uv), Postgres, `/etc/racinglines.env`, the units |
| `deploy/vm/update.sh [ref]` | On the VM, run by `vm.sh deploy`: checkout, `pip install`, `alembic upgrade head`, `racinglines db seed` (reference rows for every sport schema, idempotent upserts). The only database writes a deploy makes. Refuses a shared or symlinked venv, and a venv that imports `racinglines` from the other checkout |
| `deploy/vm/build_docs.sh` | Piped over ssh by `vm.sh deploy` (after the timers resume), `vm.sh docs` and `vm.sh staging deploy`: builds `site/`, which the app serves at `/docs`, from the checkout's `docs/`. The theme is Material, so the first run installs `requirements-docs.txt` (mkdocs and mkdocs-material) into the venv. Builds beside the live site and swaps, so `/docs` never serves a half-built folder. Fail-soft: a failure logs a `docs:` line and the old site stays. Touches only `site/` and the venv |
| `deploy/vm/untrack.sh <ref>` | Piped over ssh by `vm.sh deploy` before `update.sh`: files the VM's current commit tracks and `<ref>` doesn't are backed up to `data/backups/files/racinglines-before-untrack-<UTC>.tar.gz` and untracked with a local commit, so the checkout leaves them on disk. Untracked files `<ref>` starts tracking are moved to `data/backups/files/moved-aside-<UTC>/` first, so the checkout cannot refuse |
| `deploy/vm/systemd/` | Every unit on the VM: `racinglines-web`, `racinglines-recorder`, `racinglines-mcp`, `racinglines-signals` + timer, the recorder timers (`record-venues`, `record-fastf1`, `pm-sync`), `schedule-sync`, `forecast-refresh`, `live-auto` + timer, the per-event templates `live-f1@` (+ timer) and `live-dh@`, and staging's twins (`staging-web`, `staging-live-*`, `staging-mirror-check`) |
| `deploy/vm/staging/setup.sh`, `update.sh` | Staging on the VM ([Staging](#staging)) |
| `deploy/vm/compose.override.yml` | Postgres on the VM's loopback only |
| `deploy/vm/racinglines.env.example` | The VM's settings file (`/etc/racinglines.env`: the admin password, `APP_SECRET`, alerts) |
| `scripts/vm/*.sh` | What the timers run, and the one-off jobs run as transient units ([Timers and jobs on the VM](#timers-and-jobs-on-the-vm)) |
| `scripts/cloud/bucket.sh restore --yes` | Loads the bucket's database dump into the docker-compose Postgres, after backing up the current one to `data/backups/db/` |

## Timers and jobs on the VM

Every timer is a systemd timer that starts a one-shot pass; `vm.sh deploy` pauses and resumes all of them. The
polling rule (owner, 2026-10-07): market prices every 5 minutes, every day; race data and forecasts only on race
weekends (`scripts/vm/race_weekend.sh <sport>`, exit 0 on Thu to Sun UTC with an event in the window).

| Timer | Every | Script | Switch from the Mac | What a pass does |
|---|---|---|---|---|
| `racinglines-record-venues.timer` | 5 min, every day | `scripts/vm/record_venues.sh` | `vm.sh record [off\|status]` | One order-book snapshot per open market for `kalshi:f1 og:f1 kalshi:nascar og:nascar kalshi:motogp`; that pair's `sync` every 60 min; OG.com `settle` every 60 min; the last 2 hours of trades every 15 min; then `tape_check.sh`. The first pass on a box backs the database up ([Market tape](market-tape.md)) |
| `racinglines-pm-sync.timer` | 5 min, every day | `scripts/vm/pm_sync.sh` | `vm.sh pm-sync [off\|status]` | Polymarket F1 links synced every pass; NASCAR and MotoGP (`PM_SPORTS`) synced every 60 min with a book snapshot every pass; every open market's trades every 15 min; then `tape_check.sh` |
| `racinglines-recorder.service` (not a timer) | continuous | `racinglines markets record --interval 60` | `vm.sh start` | Polymarket F1 books every 60 s, a sync every 30 min, and the hourly archive pass that moves cold market rows of every exchange to Parquet |
| `racinglines-signals.timer` | 5 min | the signals pass | `vm.sh start` | Paper signals for every strategy profile ([Paper trading](paper-trading.md)) |
| `racinglines-live-auto.timer` | 5 min | `racinglines live auto` | `vm.sh live auto [off]` | One step of every committed F1 spec whose window is open ([Live events on the VM](#live-events-on-the-vm)) |
| `racinglines-record-fastf1.timer` | 5 min, race weekends | `scripts/vm/record_fastf1.sh` | `vm.sh record fastf1 [on\|off\|status]` | `racinglines data record f1`: one snapshot per live session. Has stored nothing on the VM so far: F1's timing archive answers 403 there, and the pass logs `fastf1: BLOCKED` |
| `racinglines-schedule-sync.timer` | 6 h | `scripts/vm/schedule_sync.sh` | `vm.sh schedule [off\|status]` | A dry run of `racinglines data schedule <sport> --through <today + 70 days>` for `SPORTS` (default `f1`); only when a session would be added or moved does it back the database up (reused for 23 hours) and run `--apply --backup`. Rollback: `racinglines data schedule f1 --undo --backup <dump>` |
| `racinglines-forecast-refresh.timer` | 30 min | `scripts/vm/forecast-refresh.sh` | `vm.sh forecast [off\|status]` | NASCAR results, then the MotoGP calendar and results (`data fetch motogp --refresh`, `data ingest motogp`), and both forecasts, on their race weekends and Mondays; the F1 championship forecast once per new race classification (never mid-weekend). Backup first when the last one is over 23 hours old |
| `racinglines-staging-mirror-check.timer` | 5 min | `racinglines.db.mirror repair` | `vm.sh mirror on\|off` | Only while the [data mirror](#staging-the-data-mirror) is on |

Every `status` prints the timer's next run, then `--- last passes (<log>)` with the log's tail
(`data/runs/logs/<name>.log`, also in the journal: `vm.sh logs racinglines-<name>`). A pass on an off-week logs
`<sport>: off-week, skipped` and exits 0.
<!-- scripts/vm/record_venues.sh:45-49, scripts/vm/pm_sync.sh:31-35, scripts/vm/record_fastf1.sh:24 -->

**One-off jobs** run on the VM as transient systemd units (`sudo systemd-run --unit=rl-<name> --uid=racinglines …`),
never in an SSH shell: they survive an SSH drop and a deploy's pause, and every one backs the database up first:

| Job | Started by | What it is |
|---|---|---|
| `rl-demo` | `vm.sh demo [extra]`, `demo status` | The multi-sport demo: `RACINGLINES_SPORT_STATUS=1` and `RACINGLINES_SPORT_PAPER=1` in `/etc/racinglines.env`, then `scripts/vm/demo_setup.sh` (NASCAR and MotoGP demo history for maker and taker; refused while a `racinglines-live-*` unit is active). Undo: `racinglines strategy demo-history <sport> --reset --users maker,taker --backup FILE` per venue, `<sport> forecast --undo RUN_ID` ([Paper trading](paper-trading.md#nascar-and-motogp-demo-in-sample-on-by-default)) |
| `rl-overnight` | by hand | `scripts/vm/overnight.sh` in one of its modes ([Overnight VM run](overnight-vm-run.md)) |
| `rl-backfill-tape` | by hand | `scripts/vm/backfill_tape.sh`: every trade and hourly price the venues still serve ([Market tape](market-tape.md#filling-gaps-the-tape-backfill)) |
| `rl-season-demo` | `vm.sh staging demo-db build` | `scripts/vm/season_demo.sh`: the alpha's season demo database ([Season demo database](#season-demo-database)) |
| `scripts/vm/reset_fantasy.sh` | by hand, as the app user | Every active account but the demo `maker` and `taker` back to one F$1,000 sign-up grant with no paper positions, signals, house-book bets or strategy profile. `TARGET=prod\|staging` (default staging); a dry run that prints the per-account counts unless `APPLY=1`. Run after a race weekend's signal window closes (a day after the race) |
| `scripts/vm/fantasy_setup.sh` | by hand, as the app user | `racinglines users setup` (the manual-trading tables, idempotent) with a backup and a `data_changes` note. `TARGET=staging\|prod` (default staging). No Alembic migration: a deploy never runs it |

Two more switches, neither a timer: `vm.sh switch RACINGLINES_<NAME> on|off` sets an app switch in
`/etc/racinglines.env` (e.g. `RACINGLINES_OG_VENUE`) and restarts the web app; it refuses any `*TRADING*` flag with
`trading flags are never set by vm.sh: they need the owner's sign-off and a hand edit`. `vm.sh accounts [off]` opens
beta sign-up (backup, `racinglines users setup`, `RACINGLINES_SIGNUP=1`, a check of `/signup`).
<!-- scripts/deploy/vm.sh:184 -->

## Code from GitHub, data on the VM

Owner rule (2026-10-01): **a deploy carries code only.** It never restores, overwrites or deletes anything under
`data/`, the pitch images or the database's rows. Data and the database change only through ssh and the scripts
above, or through the site's admin views. (A deploy's own database writes are `alembic upgrade head` and
`racinglines db seed`, both in `update.sh`.)

**Where each kind of file lives** (checked 2026-10-01 against the public repo, the scripts and the data bucket):

| What | In the public repo? | On the VM | Off the VM (copy) | How it changes on the VM |
|---|---|---|---|---|
| Code, schemas (`sports/`, `exchanges/`), live specs (`live/`), sweeps, units, `pitch.html` | yes | the checkout | GitHub | a merge to `main` (CI deploy) |
| Database (results, links, model runs, positions, the hot market rows) | no | docker Postgres | **none from the VM**: no script or timer pushes a VM dump anywhere; the newest bucket dump a cloud session can read is the Mac's from 2026-09-28 | the timers and scripts (`vm.sh record`, `demo`, `overnight.sh`, live steps), admin views |
| Market history older than the hot window (`data/archive/markets/`, Parquet) | no | moved there from Postgres by the recorder's archive pass (`markets record`, `MS.archive(..., policy=True)`) | none from the VM; the old bucket has Polymarket only, to 2026-09-28 | the recorder, hourly. **The database dumps no longer hold these rows** (that's why they shrank from 118 MB to 56 MB), so a dump alone is not a full backup |
| Database dumps (`data/backups/db/`) and untrack tars (`data/backups/files/`) | no | yes | **none** | `vm.sh backup`, each writing script's first step |
| Raw inputs (`data/raw/f1` FastF1 cache, `nascar`, `motogp`, `mtb_dh`) | no | yes | old bucket: `mtb_dh` only | the live steps and ingest commands fetch them; F1 sessions arrive from the Mac (`f1_push.sh`) |
| Run folders (`data/runs/live`, `replay-grid`, `search`, `logs`) | no | yes | old bucket: `live`, `runs/f1` to 2026-09-28 | the units and scripts that write them |
| Built docs (`site/`, served at `/docs`) | no | built by every `vm.sh deploy` and by `vm.sh docs` (`deploy/vm/build_docs.sh`) | no (rebuilt from the checkout) | a code merge's deploy; a docs-only merge deploys nothing, so run `vm.sh docs` after one |
| Pitch images (`racinglines/web/static/pitch/*.jpg`, used by `/pitch`) | no (`*.jpg` is ignored) | yes, untracked (kept by `untrack.sh`) | the owner's Mac | by hand (scp) |
| Test fixtures (`tests/fixtures/`) | no; goldens (`tests/golden/`) yes | yes, untracked | the owner's Mac | `scripts/fetch_test_fixtures.py --refresh` (needs the exchanges and FastF1) |

**What follows from it:**

- **A rebuilt VM doesn't come back complete.** `vm.sh setup` + `vm.sh restore` loads whatever the bucket last
  received, and nothing has pushed there from the VM (the VM's bucket `racinglines-data-384052502248` was loaded from
  the Mac before cutover). That means no Kalshi or OG.com books, no NASCAR or MotoGP data, no demo rows, no `/pitch`
  images, no `site/`. Until the VM pushes its dumps and `data/archive/markets` to the bucket, its disk is the only
  copy (owner decision: a nightly push, [todo](todo.md#staging-and-ci-deploys) STG-5).
- **Cloud sessions read stale data.** Their HMAC key reaches the old bucket (`racinglines-data-650570086451`, last
  push 2026-09-28) only, and `data/` is no longer in git, so the [cloud sweep](cloud-sweep.md) path of committing
  data and results to git doesn't work on the public repo. Results go back through `bucket.py push`.
- **Without `tests/fixtures/` every golden test skips** (`conftest.py` skips, not fails): on a fresh public checkout
  `pytest -m "not live"` reports about 50 fixture skips and still looks green.
- **Re-adding an untracked file to git is handled by the deploy.** If a commit starts tracking a path the VM keeps
  as an untracked file (a template copied by hand, the pitch images, `tests/fixtures/`), `untrack.sh` moves the VM's
  copy to `data/backups/files/moved-aside-<UTC>/` before the checkout, which then writes the repo's version. Nothing
  is deleted; restore from that folder if the VM's copy was the one you wanted.
- **New data a PR needs doesn't arrive with the merge.** A new sport's tape, a FastF1 backfill, a replay grid or a
  forecast is a VM step after the deploy (a script under `scripts/vm/` run as a transient unit, backup first), named
  in the PR and run by the owner. Schemas and seeds do arrive (`db seed` runs on every deploy).

## Back up before any database write

Standing practice (owner, 2026-09-29), for every task on every sport and exchange: a task plan lists the backup as
its first step and the rollback as its last. Read-only steps need no backup.

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh backup <purpose>        # lowercase letters, digits and - only
```

```text title="What you should see"
-rw-r--r-- 1 racinglines racinglines  56M <date> data/backups/db/racinglines-before-<purpose>-<UTC>.sql.gz
```
<!-- scripts/deploy/vm.sh:284: ls -lh of the dump; the size is the 2026-10-01 figure from "Code from GitHub, data on the VM" -->

The same change adds a `data_changes` entry and a [Data changes](data-changes.md) line naming the dump. A migration
is tried on a restored copy first. The writing scripts under `scripts/vm/` take their own backup as their first step
and check the dump's trailer before writing anything.

## Check the VM

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh status
```

```text title="What you should see"
deployed: <sha> <subject> (<n> hours ago)
<systemctl list-units 'racinglines-*' 'cloudflared*'>
<systemctl list-timers 'racinglines-*'>
```
<!-- scripts/deploy/vm.sh:473 -->

A line starting `PAUSED by an unfinished deploy (the next deploy resumes them):` means a deploy died after its
checkout moved: fix and deploy again. Logs: `bash scripts/deploy/vm.sh logs [unit]` (default `racinglines-web`, the
last 100 journal lines); a shell: `bash scripts/deploy/vm.sh ssh`.

## What is Google, what is Cloudflare, what is neither

If the VM ever moves to another provider, only the first group changes.

| Group | Steps | What it is |
|---|---|---|
| **Google Cloud** (`gcloud`) | 1–4, 6 (`bucket.sh`), `vm.sh public`, `vm.sh ssh`, `vm.sh deploy`'s transport | The project, the bucket the VM restores from, the service account, the VM itself, SSH through IAP, the firewall. On another provider: any Ubuntu 24.04 box with SSH, an object store for backups, and `remote()` in `vm.sh` rewritten for that provider's SSH. |
| **Cloudflare** | 7, 8, cutover step 4 | The `racinglines-vm` tunnel (outbound only: the VM opens no inbound port), one public hostname per service (`racinglines.bet` → `localhost:8000`, `staging.racinglines.bet` → `localhost:8010`, `mcp.racinglines.bet` → `localhost:8100`), the DNS records the dashboard creates for them. Independent of where the VM runs: the same `cloudflared service install <TOKEN>` on any machine attaches it to the same tunnel. |
| **Neither** | 5, `deploy/vm/*`, `update.sh`, the units, `/etc/racinglines.env`, the MCP token | Everything `vm.sh setup` puts on the box: the `racinglines` user, `/opt/racinglines`, the venv, Postgres in docker, the systemd units, and the app's own auth (web passwords, `racinglines mcp token`). |

## One-time setup (owner-only, your accounts)

Done 2026-09-28 to 2026-10-01; kept so the box can be rebuilt. Settings: project **`racinglines`** (if that ID is
taken, pick another and set `RL_GCP_PROJECT`), region `us-west1`, VM `racinglines-vm` in `us-west1-b`, **e2-small**
(2 vCPU shared, 2 GB), Ubuntu 24.04, 30 GB balanced disk: roughly $15–20 a month with the disk and the external IP
the VM needs for outbound traffic.

### Step 1: project, billing, APIs

```bash title="LOCAL (Mac)"
gcloud projects create racinglines --name=racinglines
gcloud billing accounts list
gcloud billing projects link racinglines --billing-account=<ACCOUNT_ID>
gcloud config set project racinglines
gcloud services enable compute.googleapis.com iap.googleapis.com storage.googleapis.com
```

### Step 2: the bucket

```bash title="LOCAL (Mac)"
NUM=$(gcloud projects describe racinglines --format='value(projectNumber)')
export RACINGLINES_GCS_BUCKET=racinglines-data-$NUM
gcloud storage buckets create gs://$RACINGLINES_GCS_BUCKET --location=us-west1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$RACINGLINES_GCS_BUCKET --versioning
```

### Step 3: the VM's service account (it reads and writes the bucket; no keys)

```bash title="LOCAL (Mac)"
gcloud iam service-accounts create racinglines-vm --display-name="racinglines VM"
gcloud storage buckets add-iam-policy-binding gs://$RACINGLINES_GCS_BUCKET \
  --member=serviceAccount:racinglines-vm@racinglines.iam.gserviceaccount.com --role=roles/storage.objectUser
gcloud projects add-iam-policy-binding racinglines \
  --member=serviceAccount:racinglines-vm@racinglines.iam.gserviceaccount.com --role=roles/logging.logWriter
```

### Step 4: the VM, with SSH only through IAP

```bash title="LOCAL (Mac)"
gcloud compute instances create racinglines-vm --zone=us-west1-b --machine-type=e2-small \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-balanced --shielded-secure-boot \
  --service-account=racinglines-vm@racinglines.iam.gserviceaccount.com --scopes=cloud-platform
gcloud compute firewall-rules create allow-iap-ssh --network=default --allow=tcp:22 \
  --source-ranges=35.235.240.0/20
gcloud compute firewall-rules delete default-allow-ssh default-allow-rdp --quiet
```

### Step 5: set up the VM

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh setup     # prints a deploy key the first time
```

Add the key on GitHub (repo Settings > Deploy keys > Add, with write access off), then run `vm.sh setup` again. Set
the admin password with `bash scripts/deploy/vm.sh ssh`, then `sudo nano /etc/racinglines.env` (`APP_SECRET` is
already filled in). To try an unmerged branch first: `vm.sh setup <branch>`, then `vm.sh deploy <branch>`; the next
plain `vm.sh deploy` moves the VM back to `main`.

### Step 6: copy the data and test the VM before it serves anything

```bash title="LOCAL (Mac)"
bash scripts/cloud/bucket.sh push       # with RACINGLINES_GCS_BUCKET set to the new bucket
bash scripts/deploy/vm.sh restore
bash scripts/deploy/vm.sh start web     # the web app only: the Mac keeps recording
bash scripts/deploy/vm.sh deploy        # runs the smoke check on the VM
gcloud compute ssh racinglines-vm --zone=us-west1-b --tunnel-through-iap -- -L 8001:127.0.0.1:8000 -N
```

Then browse `http://localhost:8001`.

??? note "Public test port (before the handover only)"
    `bash scripts/deploy/vm.sh public on` opens tcp:8000 to everyone and prints `http://<VM IP>:8000`;
    `vm.sh public off` closes it. It is plain HTTP, so passwords cross the internet unencrypted: sign in with the
    demo accounts only, never as admin. Turning it on needs the owner's explicit sign-off (safety rail).

### Step 7: the VM's tunnel (Cloudflare)

In the Cloudflare dashboard, open Zero Trust > Networks > Tunnels > Create a tunnel, choose Cloudflared, name it
`racinglines-vm`, and on the install page pick Debian 64-bit, "Install and run a connector". Copy only the token (the
long `eyJ...` string after `cloudflared service install`). On the VM (`vm.sh ssh`):

```bash title="VM (production)"
sudo cloudflared service install <TOKEN>          # cloudflared itself was installed by vm.sh setup
sudo systemctl status cloudflared --no-pager      # active; the dashboard shows the connector as connected
```

If it says a service already exists, `sudo cloudflared service uninstall` first.

### Step 8: the MCP server's hostname

[MCP server](mcp.md) has the admin and user guides; this is the short form. On the VM:

```bash title="VM (production)"
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mcp token admin'
sudo systemctl enable --now racinglines-mcp
```

In the dashboard, on the tunnel `racinglines-vm` > Public hostnames > Add: subdomain `mcp`, domain
`racinglines.bet`, path empty, type `HTTP`, URL `localhost:8100`. No Access policy on it: clients send only the
bearer token. From the Mac:

```bash title="LOCAL (Mac)"
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp.racinglines.bet/mcp    # 401: tunnel and server up
curl -s -o /dev/null -w "%{http_code}\n" https://racinglines.bet/                    # 401: the app, unchanged
```

## Cutover

Done 2026-09-30, before round 16's book opened. Kept for a rebuild. Two recorders would split the order-book
history across two databases, so the Mac stops before the final copy.

1. On the Mac, stop the recorder and signals (`vm.sh start` also does this when run on the Mac):

    ```bash title="LOCAL (Mac)"
    launchctl bootout gui/$(id -u)/bet.racinglines.recorder
    launchctl bootout gui/$(id -u)/bet.racinglines.signals
    ```

2. Push the data, restore it on the VM, start everything:

    ```bash title="LOCAL (Mac)"
    bash scripts/cloud/bucket.sh push
    bash scripts/deploy/vm.sh restore
    bash scripts/deploy/vm.sh start
    ```

3. Log it, on the VM, and add a line to [Data changes](data-changes.md):

    ```bash title="VM (production)"
    racinglines db changes --add "production moved to the VM; restored from the Mac's dump"
    ```

4. **Point racinglines.bet at the VM.** Remove the `racinglines.bet` public hostname from the Mac's tunnel (or
   delete the DNS record), then add it to `racinglines-vm` with the service `http://localhost:8000`; the dashboard
   offers to replace the existing DNS record.
5. Smoke-check, then sign in by hand:

    ```bash title="LOCAL (Mac)"
    bash scripts/deploy/smoke.sh https://racinglines.bet
    ```

**Rollback.** Put the hostname back on the Mac's tunnel and reload the two LaunchAgents
(`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/bet.racinglines.recorder.plist`, and the same for
signals). Book snapshots the VM recorded in between would need copying back. A bad code deploy is simpler to undo:
`vm.sh deploy <previous commit>`.

## Live events on the VM

Each event's spec runs as a unit, in place of `racinglines live agent --install` (macOS only). The run folder's lock
works the same on the VM's disk. The full engine is on [Live events](live-events.md); this is the VM side.

!!! tip "Prefer `live auto` for F1: nothing to start or stop by hand"
    `racinglines-live-auto.timer` steps every committed F1 spec (`live/f1/*.toml`) whose window is open, from an hour
    before the book opens to a day after the results, every 5 minutes: each finished session is ingested and priced,
    the book closes at lights out and settles, and outside every window a pass does nothing. Live timers go off once
    an event is complete (owner rule), and only `live auto` does that by itself.

### Step 1: enable live auto, once

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh live auto
```

`vm.sh live 2026-16` for a spec with a `[window]` does the same thing: it enables `racinglines-live-auto.timer` (and
disables a `racinglines-live-f1@2026-16.timer` left on from before) rather than a per-event timer:

```text title="What you should see"
[vm HH:MM:SS] 2026-16 has a [window]: enabling live auto, which steps it until a day after its results (no per-event timer)
```
<!-- scripts/deploy/vm.sh:102 -->

Only a rehearsal spec (no `[window]`) still gets its own `racinglines-live-f1@<event>.timer`, which steps every 5
minutes until `vm.sh live <event> off`; a step on a settled event prints
`settled: nothing left to step (a per-event timer for it can go off: ...)`. A downhill final
(`live/mtb_dh/<event>.toml`) is a poll loop, `racinglines-live-dh@<event>.service`, not a timer.
<!-- racinglines/cli/live.py:212 -->

### Step 2: on an F1 weekend, push the sessions from the Mac

F1's timing archive answers 403 to the VM's cloud address (since 3 Oct 2026), so FastF1 can't fetch there and the
live step would log "waiting for the session's data" all weekend. The same block keeps `racinglines-record-fastf1.timer`
from storing anything (its log says `fastf1: BLOCKED`). One process on the Mac does both halves of the weekend, until
the race is in:

```bash title="LOCAL (Mac)"
caffeinate -i bash scripts/deploy/f1_push.sh 2026-16
```

- **Finished sessions, prod and staging:** a look every 5 minutes fetches each session once it is over (`f1 fetch`
  skips a session still running), copies the round's files to `data/raw/f1/fastf1/<year>/` in both copies of the
  app, and starts both live steps.
- **Live timing, staging only:** while a session runs, every 2 minutes (`RELAY_SEC`) it writes the live-timing
  panel's snapshot to staging's `data/runs/f1_relay/<year>-<round>.json`; the panel (`racinglines/web/f1_live.py`)
  reads that file while it is under 10 minutes old and asks FastF1 itself otherwise.

**Started by itself:** `bash scripts/deploy/f1_push_auto.sh install` (once, on the Mac) loads a LaunchAgent that
starts `caffeinate -i f1_push.sh <event>` whenever an F1 event's window is open (`racinglines live auto --list`) and
no push is running or the race is already on the VM; `f1_push_auto.sh remove` unloads it. The Mac still has to be
awake and online through the weekend. Logs: `data/runs/logs/f1_push_auto.log` and `f1_push-<event>.log`. A downhill
final's ChronoRace feed works from the VM.

### Step 3: watch it

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh status                           # the timers, including racinglines-live-auto.timer
bash scripts/deploy/vm.sh logs racinglines-live-auto       # the last 100 lines of the step's journal
```

Outside every window a pass prints `live auto: no f1 event window open at <date> <time> UTC`.
<!-- racinglines/cli/live.py:265 -->

On the VM itself, the same by hand:

```bash title="VM (production)"
sudo systemctl enable --now racinglines-live-auto.timer           # F1: every event whose window is open
sudo systemctl start racinglines-live-f1@2026-16.service          # F1: one step of one event, now (no timer)
sudo systemctl enable --now racinglines-live-dh@<event>           # downhill: the poll loop
sudo systemctl disable --now racinglines-live-f1@2026-16.timer    # a per-event timer left on: off
```

Only `vm.sh start` (without `web`) enables the recorder and signals, and only `vm.sh live` (or the lines above)
enables an event's timer; `vm.sh deploy` never starts a unit that wasn't already running. Run an event on one machine
only, the one whose database racinglines.bet reads. The web app restarts for a few seconds on a deploy, so between
sessions is still the kindest time.

## Staging

Since 2026-10-01 `staging.racinglines.bet` is **a second copy of the app on the same VM**, and **merging to the
`staging` branch deploys staging and nothing else**. `main` keeps deploying production ([The flow](#the-flow)).

| | Production | Staging |
|---|---|---|
| Branch that deploys it | `main` (`main-merge-gate`) | `staging` (`staging-deploy`, `.github/workflows/staging.yml`) |
| Checkout on the VM | `/opt/racinglines` | `/opt/racinglines-staging` |
| Web app | `racinglines-web`, 127.0.0.1:8000 | `racinglines-staging-web`, 127.0.0.1:8010 |
| Database | `racinglines` | `racinglines_staging`, in the same Postgres container, copied from production by `staging setup` / `staging reset` (`pg_dump \| psql`: production is only read); kept current by the [data mirror](#staging-the-data-mirror) once it is on; or `racinglines_staging_demo` ([Season demo database](#season-demo-database)) |
| Settings | `/etc/racinglines.env` | `/etc/racinglines-staging.env`: production's switches and admin password, its own `DATABASE_URL`, data folder (`/opt/racinglines-staging/data`), `APP_SECRET`, `RACINGLINES_URL`, `RACINGLINES_ENV=staging`, `WEB_PORT=8010`; **no trading flags, no ntfy topic, no alert webhook** |
| Timers and other units | recorder, signals, live events, the recorder timers, schedule sync, forecast refresh, MCP | only its own live events, by hand (`vm.sh staging live <event>\|auto`), and the mirror check while the mirror is on; no recorder or signals (two recorders would split the book history) |
| Live timing button (F1) | off (`RACINGLINES_F1_STREAM` unset) | on by default: an opt-in websocket per viewer polling FastF1, or the Mac's relay while `f1_push.sh` runs (`racinglines/web/f1_live.py`) |
| Tells you which one you're on | nothing | the `X-Racinglines-Env: staging` response header and a STAGING pill in the top bar (`RACINGLINES_ENV`) |

**What a merge to `staging` does** (`deploy-staging` job): `vm.sh staging deploy <sha>`, which pipes
`deploy/vm/staging/update.sh` over ssh (fetch, checkout, pip, `alembic upgrade head` and `db seed` **against
`racinglines_staging` only**: it refuses any other `DATABASE_URL`), restarts `racinglines-staging-web`, builds
staging's own `/docs`, and runs the smoke check on the VM and then against `https://staging.racinglines.bet` with
`SMOKE_EXPECT_ENV=staging`, which fails unless the answer carries the staging header. It never calls `vm.sh deploy`,
never reads the pause file, never stops a timer, never runs `untrack.sh` or `docker compose up`, and never opens
`/etc/racinglines.env` or the `racinglines` database for writing (`tests/test_staging_deploy.py` pins this).

```text title="What you should see (a staging deploy by hand)"
[vm HH:MM:SS] staging deploy <ref> (production's timers keep running)
...
[vm HH:MM:SS] docs site (/docs)
[vm HH:MM:SS] smoke check on the VM (expects the staging instance: X-Racinglines-Env: staging)
ok    env  X-Racinglines-Env: staging
...
smoke: all checks passed (http://127.0.0.1:8010)
```
<!-- scripts/deploy/vm.sh:401-408, scripts/deploy/smoke.sh:55,91 -->

!!! warning "One deploy at a time"
    The `staging` concurrency group serialises CI's staging deploys, and `vm.sh staging deploy` by hand warns
    (`warning: a staging workflow run is in progress; deploys share one queue`) when `gh` sees one running. Push
    the branch and wait for its run to finish before deploying by hand.

**Flow for a change:** branch off `main` → push it to `staging` → the merge deploys staging → look at
`https://staging.racinglines.bet` → PR of the same branch into `main` → the merge deploys production. Keep
`staging` close to `main`: after a batch, reset it to `main` (`git push origin main:staging`; a force push is fine
there, `staging` is a deploy pointer, not history).

**`vm.sh staging` subcommands** (from the Mac, or by CI for `deploy`):

| Command | What it does |
|---|---|
| `staging setup [ref]` | One time, as root (piped `deploy/vm/staging/setup.sh`): the checkout at `ref` (default the `staging` branch, else `main`), its venv, `racinglines_staging` copied from production, `/etc/racinglines-staging.env`, the unit installed and started. Idempotent: re-running keeps the database and the env file |
| `staging deploy [ref] [--db demo\|main]` | What CI runs on a merge to `staging` (above); `--db` switches the database first |
| `staging db demo\|main\|status` | Which database staging serves ([Season demo database](#season-demo-database)), then a redeploy of the current checkout |
| `staging demo-db build\|status` | Build the season demo database as the transient unit `rl-season-demo` |
| `staging status` | The staging checkout's commit, its units and timers, and `GET /login` with its env header |
| `staging logs` | `journalctl -u racinglines-staging-web` |
| `staging reset` | Drop `racinglines_staging` and copy production's rows and live run folders (`data/runs/live`) again (production only read). It wipes staging's own accounts and app state too, and refuses while the [mirror](#staging-the-data-mirror) is on |
| `staging live <event>\|auto [off]` | Staging's own run of a live event, the twin of `vm.sh live`: a spec with a `[window]` is stepped by `racinglines-staging-live-auto.timer`, a rehearsal by `racinglines-staging-live-f1@<event>.timer`, a downhill final by `racinglines-staging-live-dh@<event>` |
| `staging off` | Stop and disable the unit; the checkout, database and env file stay |

Not done yet: Cloudflare Access in front of staging (today it has the app's own login, as production).

### Season demo database

A third database, `racinglines_staging_demo`, beside `racinglines_staging` in production's Postgres container (owner,
2026-10-13: every user on a random strategy at various participation rates through the 2026 F1 season, its own
database, kept, and picked by a switch on a staging deploy). It persists: deploys never drop or re-copy it.

#### Step 1: build it

A copy of production (only read) on the first run; a backup of the demo database first after that. Env: `SEED`
(2026), `YEAR` (2026), `COPY=1` re-copies, `SOURCE=racinglines|racinglines_staging`.

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh staging demo-db build
```

```text title="What you should see"
started rl-season-demo: bash scripts/deploy/vm.sh staging demo-db status
```
<!-- scripts/deploy/vm.sh:437 -->

`demo-db status` prints the unit's state, the tail of `data/runs/logs/season-demo-<UTC>.log` and the
`season-demo.done` / `.failed` marker. The script prints a progress line every 5 minutes with the weekend it is on.

#### Step 2: switch staging to it (and back)

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh staging db demo                # staging serves racinglines_staging_demo
bash scripts/deploy/vm.sh staging db main                # back to racinglines_staging
bash scripts/deploy/vm.sh staging deploy <ref> --db demo # a deploy that switches too
```

```text title="What you should see (then the redeploy's lines)"
staging database: demo (racinglines_staging_demo)
```
<!-- scripts/deploy/vm.sh:421 -->

The switch is one file, `/etc/racinglines-staging-db.env` (the demo database's `DATABASE_URL`), which the staging web
unit reads after `/etc/racinglines-staging.env` and `deploy/vm/staging/update.sh` migrates; with it absent staging is
as before. CI's staging deploys leave it alone, so the choice holds until `vm.sh staging db main`. Staging's live
units keep `racinglines_staging`. The demo itself is `racinglines users season-demo`
(`racinglines/fantasy/season_demo.py`, writes only a database whose name contains "demo"), run by
`scripts/vm/season_demo.sh`.

### Separate venvs

Production (`/opt/racinglines/.venv`) and staging (`/opt/racinglines-staging/.venv`) each need their own venv. Both
checkouts are installed editable (`pip install -e .`), so a shared venv imports `racinglines` from whichever checkout
installed last: on 2026-10-12 staging's `.venv` was a symlink to production's, so production's jobs ran staging's code.

`vm.sh deploy`, `vm.sh staging deploy`, both `update.sh` scripts and both `setup.sh` scripts refuse to run when
either `.venv` is a symlink or the two resolve to the same folder (`vm.sh deploy` checks before it pauses anything),
and after `pip install` each update checks that its venv imports `racinglines` from its own checkout.

To fix a shared venv, after production's checkout is at the commit it should run:

```bash title="VM (production), as the app user"
sudo -u racinglines -H bash -c 'cd /opt/racinglines-staging && rm .venv && UV_PYTHON_INSTALL_DIR=$HOME/.uv-python /opt/uv/bin/uv venv --quiet --seed --python 3.14 .venv && .venv/bin/pip install --quiet -r requirements.txt -e .'
```

```bash title="VM (production)"
cd / && /opt/racinglines/.venv/bin/python -I -c 'import racinglines; print(racinglines.__file__)'
cd / && /opt/racinglines-staging/.venv/bin/python -I -c 'import racinglines; print(racinglines.__file__)'
sudo systemctl restart racinglines-staging-web
```

The first print names `/opt/racinglines/racinglines/__init__.py`, the second
`/opt/racinglines-staging/racinglines/__init__.py`.

### Staging: the data mirror

!!! note "Built, not yet turned on (2026-10-14)"
    The mirror code (`racinglines/db/mirror.py`, `vm.sh postgres logical`, `vm.sh mirror …`) is on `main` since
    #154. Turning it on is the owner's call: the first two steps below change production's Postgres.

**Why staging drifted.** `racinglines_staging` is a copy of production made once. Staging runs no recorder, signals
or pricing timers, so from the minute it was copied it missed every new market price, trade, book, model run and
result production recorded, while it built up state of its own (test accounts, fantasy, jobs). Catching up meant
`staging reset`, which drops the whole database, that state with it.

**The mirror** keeps staging a live copy of production with Postgres logical replication: production publishes its
tables, staging subscribes, and production's inserts, updates and deletes arrive in staging within seconds. Production
is only read: the subscription connects as `racinglines_mirror` (REPLICATION, SELECT on the mirrored tables); on and
off add or drop that role, the publication `racinglines_staging_mirror` and its replication slot in production's
catalog, and no production row is ever written. TRUNCATE is not published.

| Scope (`vm.sh mirror on <scope>`, default `all`) | What follows production | What stays staging's own |
|---|---|---|
| `data` | race history, athletes, model runs and predictions, market links, prices, trades, books, live events, data changes | users, the fantasy ledger, paper positions, signals, orders, the house book, activity, jobs |
| `accounts` | `data` + users, email preferences, `accounts.fantasy_ledger` | paper positions, signals, orders, the house book, activity, jobs |
| `all` | every table in `public` and `accounts` production has | jobs (staging's worker must never run production's queued jobs), `alembic_version` |

**Staging can still write.** Its own rows in a mirrored table take ids from 1,000,000,000 (`mirror.OFFSET`) up, so
they never collide with production's. If production later gets the same unique key, replication would stop on the
duplicate: `racinglines-staging-mirror-check.timer` runs `mirror repair` every 5 minutes, which makes staging's row
production's and carries on. A staging migration that drops or renames a column on a mirrored table stops replication
of that table until production runs the same migration (`mirror status` warns; production keeps at most 2 GB of WAL
for a stalled mirror, `max_slot_wal_keep_size`, then the mirror breaks, never production: `mirror off`, then `on`).
The check timer also copies production's newer live run folders over staging's, and `mirror on` links staging's
`data/archive` to production's; staging never archives (`markets.store.archive` refuses when
`RACINGLINES_ENV=staging`).

#### Step 1: production backup, then `wal_level=logical`

Restarts production's database container (seconds); the timers are paused and resumed as a deploy does.

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh backup before-staging-mirror
bash scripts/deploy/vm.sh postgres logical
```

```text title="What you should see (last lines)"
[vm HH:MM:SS] wal_level is now logical
smoke: all checks passed (http://127.0.0.1:8000)
```
<!-- scripts/deploy/vm.sh:354-356; a second run prints "wal_level is already logical: nothing to do" (vm.sh:338) -->

#### Step 2: preview

Read-only: per table, the staging rows production doesn't have as-is (replaced on the first mirror).

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh mirror plan all
```

#### Step 3: subscribe and check

Backs staging up first (`racinglines_staging-before-mirror-<UTC>.sql.gz`); the first copy runs in the background.

```bash title="LOCAL (Mac)"
bash scripts/deploy/vm.sh mirror on all
bash scripts/deploy/vm.sh mirror status
```

```text title="What you should see (from `mirror on`)"
[vm HH:MM:SS] backing up racinglines_staging first (staging rows production doesn't have as-is are replaced: mirror plan counts them)
...
[vm HH:MM:SS] staging reads production's data/archive in place
```
<!-- scripts/deploy/vm.sh:373,379 -->

`vm.sh staging reset` refuses while the mirror is on (production holds a slot for staging's database): `mirror off`
first. `mirror off` keeps staging's rows as of then and prints
`staging keeps its rows as of now, and still reads production's data/archive`.

## Later

- A nightly push from the VM to its bucket (the latest dump and `data/archive/markets`), so the VM's disk is not the
  only copy and cloud sessions stay current ([todo](todo.md#staging-and-ci-deploys) STG-5). `bucket.sh push` needs
  to use the docker-compose `pg_dump` on Linux, and the VM's service account needs write access to the bucket.
- Turning the staging data mirror on (above).
- `racinglines live agent --systemd`, writing the units above.
- ~~`staging.racinglines.bet` on the Mac's tunnel.~~ Done 2026-10-01 on the VM ([Staging](#staging)).
- ~~Deploys from GitHub Actions calling `vm.sh`.~~ Done 2026-10-01 ([The flow](#the-flow)).

## Next steps

<div class="grid cards" markdown>

- **Market tape**

    ---

    What the recorders store every 5 minutes, and how to backfill a gap.

    [Market tape](market-tape.md)

- **Live events**

    ---

    The live engine, `racinglines live`, and an F1 weekend's private book.

    [Live events](live-events.md)

- **Race weekend runbook**

    ---

    The checks before, during and after a race weekend.

    [Weekend runbook](weekend-data-runbook.md)

- **Testing**

    ---

    `racinglines check`, the regression suite and the goldens, before any merge.

    [Testing](testing.md)

</div>
