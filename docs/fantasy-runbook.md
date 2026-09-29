# Fantasy launch runbook: tasks, merges and launch-day blocks

The working detail behind the [Fantasy soft launch](fantasy-launch.md) index: the day-by-day calendar, every task
with its role, model and money flag, the merge sequence, the full decision table, the staging rehearsal, the
go/no-go checklist, the launch, off-switch and rollback blocks, the risks and the report outline. The index holds
the verdict, the phase table, the decision list and the master copy of the names; this page is reference.

**Status:** draft for the owner, Tue 2026-09-29. Nothing here is built yet. Every decision is open until the owner
signs it.

---

## Roles and models

Stated before any work, per `CLAUDE.md`. Fable plans, decides and reviews; it never does hands-on work a worker
could do. Every spawn names its model. The owner does every VM write and every merge.

| Role | Model | This sprint | Why this seat |
|---|---|---|---|
| Decide / review | Fable | DOC-1 final review; the BOOK-2 read; FABLE-OPS (OPS-2, OPS-3, OPS-5 before the Thu 1 Oct merge); the ACC-1 + OPS-8 read (Mon 5 Oct); FABLE-1a (SEC-1, ACC-3, ACC-4, ROLE-1, LEGAL-1); FABLE-1b (BOOK-3, EXCH-1, STAT-1, SETTLE-1, STAT-2, ADM-1); GO-1 verdict; REPORT-1 verdict; NEXT-1 design (after the sprint) | Settlement, ledger and fill rules, auth and role gates, the deploy path, the migration and the launch call are the judgement calls |
| Own | Opus | OPS-2, OPS-3, OPS-5, OPS-8, SEC-1, ACC-1, ACC-2, ACC-3, BOOK-3, EXCH-1, SETTLE-1 (with REPLAY-1), INT-1, DRY-2, REPORT-1 draft; later NEXT-1 build, NEXT-2 | Large or risky multi-file work: new units, the deploy path, auth, the schema, fills, settlement |
| Implement | Sonnet | DOC-1 writers (6), EXCH-0, OPS-1, OPS-4, OPS-6, OPS-9, OPS-11, BOOK-1, BOOK-2, MAIL-1, LEGAL-1, ACC-4, ROLE-1, STAT-1, STAT-2, ADM-1 | The decision is made; write it inside the given scope. Tests that look wrong come back up as a question |
| Scout | Haiku | SCOUT-1, DOC-2, log readback for DRY-1, STAGE-1, OPS-10 and SETTLE-2 | Read-only lookups, doc sync, reading logs so the owner does not have to |
| Owner | – | OWNER-1 to OWNER-10, OPS-7, DRY-1, MAIL-2, LEGAL-2, STAGE-1, GO-1 sign-off, LAUNCH-1, OPS-10, SETTLE-2 | Every merge, every VM write, every decision |

EXCH-0 is a Sonnet task, not a Haiku scout, because it edits a test file: it adds `tests/fixtures/fantasy/` to
`ALLOWED_DATA` in `tests/test_no_data_in_git.py` (today the list holds `tests/fixtures/f1/`, `market/` and `mtb/`
only), without which every pre-merge check fails once the fixtures land.

**Agent count, written down before launching** (`CLAUDE.md` fan-out rule). In-sprint spawns: Sonnet 6 + 15 = 21 (six DOC-1 writers, one per doc; 15 implement tasks including OPS-11),
Opus 14, Haiku 2 + 4 readbacks = 6, Fable 8 (DOC-1, BOOK-2, FABLE-OPS, ACC-1 + OPS-8, FABLE-1a, FABLE-1b, GO-1,
REPORT-1). That is 49 spawns over 14 days, not one fan-out. The largest simultaneous wave is the P1 build (Tue 29 -
Wed 30 Sep): 13 builders (EXCH-0, OPS-1, OPS-2, OPS-3, OPS-5, OPS-6, OPS-8, OPS-9, SEC-1, BOOK-1, MAIL-1, ACC-1,
LEGAL-1) + 1 scout (SCOUT-1) + 0 verifiers = 14. The P2 wave is 12 workers (ACC-2, ACC-3, ACC-4, ROLE-1, BOOK-3,
EXCH-1, STAT-1, SETTLE-1, STAT-2, ADM-1, INT-1, DRY-2) + 2 Fable judges (FABLE-1a, FABLE-1b) = 14. Both are under
the ceiling of 30. Each worker gets one task on its own branch (`work/<task id in lowercase>`, for example
`work/ops-1`) off `main`.

**A sample dispatch** (the format every spawn uses):

```text
# EST: 10 calls, 3 files · model: Sonnet (implement)
Task: OPS-1 /healthz
Scope: racinglines/web/health.py (new), racinglines/web/app.py (PUBLIC_PATHS), tests/test_health.py (new)
Done when: GET /healthz returns 200 with db ok, git sha, recorder / Kalshi sync / signals / fantasy tick ages and
  disk %, and 503 when the DB is unreachable; no secrets and no user counts in the payload
Verify: python -m pytest tests/test_health.py -m "not live"
Report: files changed, the verify command and its last line, the paths checked, what you did not check
```

Every worker ends with that footer. A claim with no evidence line counts as unverified, and Fable reads footers
and diffs, not transcripts.

## Calendar

One row per day, Tue 29 Sep to Mon 12 Oct. R16 is the closed dry run; R17 is the soft-launch weekend. Before R16
only additive ops items reach the VM; the unit edits (OPS-6) and the deploy-path change (OPS-8) wait for the Monday
window after the race.

| Day | Racing (PDT, UTC in brackets) | Owner steps and decisions | Build and merges |
|---|---|---|---|
| **Tue 29 Sep** | Kalshi lists R16 events (7 since 28 Sep) | Review PR #71; read the [index](fantasy-launch.md) | DOC-1 (6 writers); EXCH-0 probe from the Mac; branches start: OPS-1, OPS-3, OPS-6, SEC-1, BOOK-1, MAIL-1 |
| **Wed 30 Sep** | – | **OWNER-1** merge and deploy PR #71 by 12:00 PDT (19:00 UTC). **OWNER-4** VM cutover, `vm.sh public off`. **OWNER-2** decision batch A by 18:00 PDT (Thu 01:00 UTC). Nothing else: Proton waits | DOC-1 merged; SCOUT-1 baseline after the cutover; OPS-2, OPS-5, OPS-8, OPS-9, ACC-1, LEGAL-1 start |
| **Thu 1 Oct** | R16 book opens **20:30 PDT (Fri 2 Oct 03:30 UTC)**; FP1 21:30 PDT (Fri 04:30 UTC) | **LEGAL-2a** read the Kalshi and Polymarket market-data terms (~30 min) and DEC-18, DEC-19 by 12:00 PDT. Early answers DEC-1, DEC-5, DEC-7, DEC-10, DEC-11, DEC-13, DEC-14 by 18:00 PDT (Fri 01:00 UTC). P1 ops batch merged and deployed by 12:00 PDT; BOOK-1/BOOK-2 by 12:00 PDT if used in the dry run. **OPS-7** hardening by 18:00 PDT. New timers on and a test alert on the phone before 20:30 PDT. R16 tier call 18:00 PDT (existing routine). **DRY-1** starts 18:00 PDT with the tester block | **FABLE-OPS** by 09:00 PDT; OPS-4 restore drill; ACC-1 on its branch |
| **Fri 2 Oct** | FP2 01:00 PDT (08:00 UTC); FP3 21:30 PDT (Sat 04:30 UTC). MotoGP Japan (2-4 Oct, tape-only) | First nightly dump 03:00 PDT (10:00 UTC) in the bucket. **OWNER-3** Proton Mail and DNS in the Fri window (recommended; any day to Sun 4 Oct). On call for alerts | ACC-1 branch complete; SEC-1, MAIL-1, LEGAL-1 PRs open; **INT-1** starts `work/fantasy-integration` |
| **Sat 3 Oct** | Quali 01:00 PDT (08:00 UTC) | Second nightly dump 03:00 PDT (10:00 UTC) | From `work/acc-1`: ACC-3, ACC-4, ROLE-1, STAT-1 start |
| **Sun 4 Oct** | Race 00:00 PDT (07:00 UTC); results ~03:00 PDT (10:00 UTC). NASCAR Chase, Las Vegas (tape-only) | DRY-1 ends 12:00 PDT (19:00 UTC) | BOOK-3 and EXCH-1 start once ACC-4's footer names the ledger API; OPS-11 load script (`scripts/ops/loadtest.py`) merged |
| **Mon 5 Oct** | – | **OPS-11 load run 1** 08:00-08:15 PDT (15:00-15:15 UTC), before OWNER-5. **OWNER-5** R16 settle, reconcile, report; disable `racinglines-live-f1@2026-16.timer`. DEC-17 by 12:00 PDT; **OWNER-7** resize if yes. Proton green checks by 12:00 PDT (hard deadline). **P2 step 0**: OPS-6 and OPS-8 merged and deployed in the Monday window. **OWNER-6** batch B by 18:00 PDT (Tue 01:00 UTC) | DRY-2 retro; **ACC-2** restored-copy trial; Fable reads ACC-1 + OPS-8; SETTLE-1 and STAT-2 start on the integration branch; **FABLE-1a** overnight |
| **Tue 6 Oct** | Kalshi R17 listing expected Mon 5 - Tue 6 | **OWNER-8** migration **09:00 PDT (16:00 UTC)** with sign-off; step 2 SEC-1 + MAIL-1; **MAIL-2**; **LEGAL-2** page text and DEC-22 by 12:00 PDT; Turnstile setup if DEC-16 = yes; step 3 LEGAL-1, ACC-3, ACC-4, ROLE-1 merged and deployed by 16:00 PDT. **STAGE-1 part A 18:00-20:00 PDT (Wed 01:00-03:00 UTC)** | ADM-1 starts; SETTLE-1 adds REPLAY-1; INT-1 runs the full suite on the integration branch |
| **Wed 7 Oct** | – | **OWNER-9** R17 listings check; `RACINGLINES_KALSHI_SPRINTS` per DEC-12. Batch C by 12:00 PDT (19:00 UTC). Step 4 fantasy batch merged 12:00-16:00 PDT and deployed. **REPLAY-1** on the Mac before 17:00 PDT. **STAGE-1 part B 17:00-21:00 PDT (Thu 00:00-04:00 UTC)**, with **OPS-11 load run 2** (5o) | **FABLE-1b** by 12:00 PDT; DOC-2 after the merges |
| **Thu 8 Oct** | – | **GO-1** go/no-go **12:00 PDT (19:00 UTC)**. R17 tier call 18:00 PDT (existing routine). **LAUNCH-1** sign-up opens **18:00 PDT (Fri 9 Oct 01:00 UTC)**; invites sent. Enable `racinglines-live-f1@2026-17.timer` before Fri 00:30 PDT | Haiku reads the go/no-go evidence logs |
| **Fri 9 Oct** | R17 book opens **00:30 PDT (07:30 UTC)**; FP1 01:30 PDT (08:30 UTC); Sprint Qualifying 05:30 PDT (12:30 UTC). MotoGP Indonesia (9-11 Oct, tape-only) | **OPS-10** on call; deploys only in the [deploy windows](vm-reliability.md#deploy-windows) | Fixes only, logged |
| **Sat 10 Oct** | Sprint 02:00 PDT (09:00 UTC); Quali 06:00 PDT (13:00 UTC) | On call | Fixes only, logged |
| **Sun 11 Oct** | Race 05:00 PDT (12:00 UTC); results ~08:00 PDT (15:00 UTC). NASCAR Chase, Charlotte Roval (tape-only) | **SETTLE-2** from ~08:00 PDT; manual queue clear by 18:00 PDT (Mon 01:00 UTC); `ops backup --label after-r17-settle`; disable `racinglines-live-f1@2026-17.timer` | Haiku reads the settle logs |
| **Mon 12 Oct** | – | **OWNER-10** retro decisions | **REPORT-1** draft (Opus), verdict (Fable) |

**Deploy windows.** PR #71 allows a deploy at any time, but a deploy restarts the web app for a few seconds and
resets the in-memory throttle and demo sessions. The kindest windows for R16 and R17 are kept in one place only:
[VM reliability, deploy windows](vm-reliability.md#deploy-windows).

**The expected outcome if STAGE-1 finds a P0.** The build is tight: the fantasy batch is first on production on
Tue 6 (accounts) and Wed 7 Oct (trading and settlement), and the go/no-go is Thu 12:00 PDT. If either STAGE-1 part
finds a P0 that cannot be fixed, reviewed, merged, deployed and re-run before Thu 12:00 PDT, the fallback (R17 as
closed dry run #2, launch Thu 22 Oct) is the expected outcome, not a surprise.

## Email

The owner's Proton Mail setup is in [Email setup](email-setup.md): steps 0-12 (accounts, Proton domain, every DNS
record in **Cloudflare**, nothing at Squarespace), then MAIL-2. Dates for this sprint:

| When | What |
|---|---|
| Wed 30 Sep 18:00 PDT | DEC-3 and DEC-21 signed with batch A (before any DNS work) |
| Fri 2 - Sun 4 Oct (recommended Fri 2 Oct) | OWNER-3: email-setup steps 0-12 (~1-2 h hands-on) |
| Mon 5 Oct 12:00 PDT | Hard deadline: green checks in Proton and the mail-tester round trip |
| Tue 6 Oct | MAIL-2: SMTP token for noreply@ into `/etc/racinglines.env`, backend still `log`; `racinglines mail test` to Gmail |
| Thu 8 Oct 18:00 PDT | `RACINGLINES_MAIL_BACKEND=smtp` (launch step 6) |
| Tue 6 Oct | DMARC to `p=quarantine` once step 11 and MAIL-2 show PASS at two providers (DEC-21); no later than the go/no-go |

At the cutover (OWNER-4), edit only the racinglines.bet hostname record; never touch the MX, TXT or DKIM records.

## Phases

Task ids are the plan's. "⚠️" marks money-adjacent work (settlement, bets and fills, the ledger, trading paths, VM
units, the deploy path, DB migrations) and says why. Files marked "(new)" do not exist on 29 Sep.

### P0: Unblock, decide, cut over (Tue 29 Sep - Wed 30 Sep)

**Goal.** Remove the blockers for everything else. PR #71 merged, so deploys pause and resume timers. Build-scope
decisions signed. VM cutover done with the plain-HTTP public port closed. The sprint docs merged, so every worker
builds against the same names.

| ID | Task | Role · model | Files | Size | Depends on | Money flag |
|---|---|---|---|---|---|---|
| OWNER-1 | Merge PR #71 (deploy pauses timers, deploys, runs catch-up, resumes) and deploy it; due Wed 30 Sep 12:00 PDT | owner | `scripts/deploy/vm.sh`, `CLAUDE.md`, `docs/vm-deploy.md` (the PR's diff) | S (diff review + one deploy) | – | ⚠️ changes the VM deploy path and timer handling; replaces the live-event freeze (no `--force`) |
| DOC-1 | Write the sprint docs, add a Fantasy section to the `mkdocs.yml` nav, link them from `docs/todo.md` | implement (writers) + decide (review) · Sonnet (six writers, one per doc), Fable final review | `docs/fantasy-launch.md`, `fantasy-runbook.md`, `fantasy-accounts.md`, `fantasy-trading.md`, `vm-reliability.md`, `email-setup.md` (all new), `mkdocs.yml`, `docs/todo.md` | M (6 docs, ~12 calls each) | – | – |
| OWNER-2 | Sign decision batch A: DEC-2, DEC-3, DEC-6, DEC-9, DEC-18, DEC-19, DEC-20 (build scope), DEC-21 | owner | [Decisions](#decisions), `docs/todo.md#owner-decisions` | S | DOC-1 | – |
| OWNER-4 | VM cutover per [VM deploy](vm-deploy.md#cutover); confirm `vm.sh public off`, `APP_SECRET` set; add `RACINGLINES_OPS_NTFY_TOPIC` | owner | `/etc/racinglines.env` (VM), Cloudflare tunnel racinglines-vm public hostname | M (existing cutover plan) | OWNER-1 | ⚠️ moves production to the VM and starts the recorder and signals units there; edit only the racinglines.bet hostname record |
| SCOUT-1 | Read-only VM baseline after the cutover: enabled units and timers, disk and memory, swap, journald persistence, env key names present (no values), firewall rules for tcp:8000, the bucket named by `RACINGLINES_GCS_BUCKET` | scout · Haiku | – (read-only) | S (~6 calls) | OWNER-4 | – |
| EXCH-0 | Read-only probe from the Mac: Kalshi orderbook for KXF1RACE-BAH26 tickers, a Polymarket CLOB book for an F1 champion token; save small fixtures with a README; add `tests/fixtures/fantasy/` to `ALLOWED_DATA`; note depth levels, timestamps and rate-limit headers | implement · Sonnet | `tests/fixtures/fantasy/kalshi_orderbook_bah26.json`, `polymarket_book_f1_champion.json`, `README.md` (all new), `tests/test_no_data_in_git.py` | S (~10 calls, 4 files) | – | – |

Notes:

- The runbook is reference; the index ([Fantasy soft launch](fantasy-launch.md)) is what the owner reads first.
- OWNER-1 comes before the cutover. After it, `vm.sh status` shows the new sha and
  `/var/lib/racinglines/deploy-paused` is absent. PR #71 also rewrites the `CLAUDE.md` freeze paragraph and the
  `vm.sh deploy` text in [VM deploy](vm-deploy.md), so DOC-2 does not touch those.
- OWNER-3 (Proton Mail and DNS) is no longer on Wed 30 Sep: see [Email](#email). Wednesday holds only PR #71, the
  cutover and batch A.
- SCOUT-1 is read-only ssh. If the permission classifier refuses it, the owner pastes the block from
  [VM reliability](vm-reliability.md) and the scout reads the log. NOT FOUND for anything missing.
- EXCH-0 follows the `CLAUDE.md` rule to probe a data source from the owner's machine before any full run. LOCAL
  (Mac) only, because cloud sessions cannot reach the venues. The steps are in [Fantasy trading](fantasy-trading.md).

**Exit criteria.**

- PR #71 merged and deployed; `vm.sh status` shows its sha; `/var/lib/racinglines/deploy-paused` absent.
- Decision batch A signed by Wed 30 Sep 18:00 PDT.
- racinglines.bet served by tunnel racinglines-vm; `vm.sh public off` confirmed (no tcp:8000 firewall rule);
  `APP_SECRET` set.
- The sprint docs merged; `mkdocs build --strict` green.
- Kalshi and Polymarket order-book fixtures saved from the Mac probe; `tests/test_no_data_in_git.py` passes.

### P1: Reliability build and R16 closed dry run (Tue 29 Sep - Sun 4 Oct)

**Goal.** Make the VM observable and recoverable before any outside user arrives, then use R16 as a closed dry
run. Monitoring, nightly backups, a snapshot schedule, ops alerts and the Kalshi sync timer are on, with 5 or fewer
staff testers. Only additive items reach the VM before the R16 book opens (Thu 1 Oct 20:30 PDT / Fri 2 Oct 03:30
UTC); OPS-6's unit and compose edits and OPS-8's deploy-path change wait for Mon 5 Oct. Meanwhile the schema, auth
hardening, mailer, private-book fixes and terms drafts are built on branches behind switches that stay off.

| ID | Task | Role · model | Files | Size | Depends on | Money flag |
|---|---|---|---|---|---|---|
| OPS-1 | `/healthz`: public JSON health (db ok, git sha, recorder / Kalshi sync / signals / fantasy tick ages, disk %) and a `PUBLIC_PATHS` entry | implement · Sonnet | `racinglines/web/health.py` (new), `racinglines/web/app.py`, `tests/test_health.py` (new) | S (~10 calls, 3 files) | – | – |
| OPS-3 | Nightly DB backup: `racinglines ops backup` + `racinglines-backup.service/.timer` (10:00 UTC), 7 on disk, copy to `gs://$RACINGLINES_GCS_BUCKET/db/nightly/` (35-day lifecycle, manifest), daily rsync of `data/runs/live` and `data/archive/markets`; guard `bucket.sh push` so the Mac cannot overwrite the VM's dump. **Owns `racinglines/cli/ops.py` and registers the `ops` group in `GROUPS`** | own · Opus | `racinglines/ops/__init__.py`, `racinglines/ops/backup.py`, `racinglines/cli/ops.py` (all new), `racinglines/cli/__init__.py`, `deploy/vm/systemd/racinglines-backup.service`, `.timer` (new), `scripts/cloud/bucket.sh`, `tests/test_ops_backup.py` (new) | M (~24 calls, 8 files) | – (needs DEC-19) | ⚠️ VM systemd unit and the backup path |
| OPS-2 | `racinglines ops health` (a subcommand in OPS-3's `cli/ops.py`) + `racinglines-health.service/.timer` (5 min): external and loopback `/healthz`, failed `racinglines-*` units, freshness (the fantasy tick is checked whenever a fantasy season is open, whatever `RACINGLINES_FANTASY` says), disk, memory, backup age; ntfy to `RACINGLINES_OPS_NTFY_TOPIC` with 1-hour de-dupe; dead-man ping | own · Opus | `racinglines/ops/health.py` (new), `racinglines/cli/ops.py`, `racinglines/markets/alerts.py`, `deploy/vm/systemd/racinglines-health.service`, `.timer` (new), `deploy/vm/racinglines.env.example`, `tests/test_ops_health.py` (new) | M (~25 calls, 7 files) | OPS-1, OPS-3 (branches from `work/ops-3`) | ⚠️ new VM systemd units |
| OPS-4 | `scripts/ops/restore_scratch.sh`: restore the newest dump into `racinglines_scratch` on the Mac, `alembic upgrade head`, print row counts and elapsed time; run the first timed drill | implement · Sonnet | `scripts/ops/restore_scratch.sh` (new) | S (~8 calls, 1 file) | OPS-3 | – |
| OPS-5 | U2: `racinglines-kalshi-sync.service/.timer`: F1 open events every 30 min (links, trades, books), plus a daily closed sync for Kalshi and Polymarket so `market_links.resolved_yes` stays fresh | own · Opus | `deploy/vm/systemd/racinglines-kalshi-sync.service`, `.timer` (new), `racinglines/cli/markets.py`, `tests/test_cli_markets.py` (new), `docs/todo.md` | M (~20 calls, 5 files) | EXCH-0 | ⚠️ new VM unit; writes market links every run |
| OPS-6 | Recorder exits non-zero after 10 consecutive failed loops so `Restart=always` acts; `TimeoutStartSec=45min` on racinglines-signals; journald and docker log caps. **Merged and deployed Mon 5 Oct, after R16** (its first deploy recreates the Postgres container) | implement · Sonnet | `racinglines/cli/f1.py`, `deploy/vm/systemd/racinglines-recorder.service`, `racinglines-signals.service`, `deploy/vm/compose.override.yml`, `tests/test_recorder_loop.py` (new) | S (~10 calls, 5 files) | – | ⚠️ systemd unit edits and a Postgres container recreation (does not change what the recorder records) |
| OPS-7 | VM hardening, owner-run: 2 GB swapfile, persistent journald (`SystemMaxUse=1G`), security-only unattended-upgrades with no auto-reboot, GCE snapshot schedule `racinglines-daily` (14 days) on disk racinglines-vm, the bucket lifecycle (nightly dumps 35 days, [step 9](vm-reliability.md#bucket-lifecycle)), Cloudflare tunnel health notification, Healthchecks.io check, ntfy app on the ops topic | owner | `/swapfile`, `/etc/systemd/journald.conf`, GCE resource policy `racinglines-daily`, the bucket's lifecycle, Cloudflare notifications, `/etc/racinglines.env` | S (~1 h) | OWNER-4 | ⚠️ VM configuration; finish before Thu 1 Oct 18:00 PDT |
| OPS-8 | `vm.sh deploy` migration guard: refuse a target sha with Alembic revisions the DB lacks unless `--migrate`; with `--migrate`, first `pg_dump` to `data/backups/db/racinglines-before-deploy-<sha>-<UTC>.sql.gz` and write a `data_changes` row; DB ahead of the target warns and skips `alembic`; post-deploy smoke also through https://racinglines.bet/healthz ([the guard](vm-reliability.md#the-migration-guard-ops-8)). **Merged and deployed Mon 5 Oct** | own · Opus (Fable reads with ACC-1) | `scripts/deploy/vm.sh`, `deploy/vm/update.sh`, `scripts/deploy/smoke.sh` | M (~18 calls, 3 files) | OWNER-1, OPS-1 | ⚠️ needs special attention: the deploy path; makes every VM migration an explicit, backed-up owner step. Must merge before ACC-1 |
| OPS-9 | `smoke.sh`: `/healthz` through Cloudflare; the `/terms`, `/privacy`, `/rules` and `/signup` checks behind smoke arguments that stay off until LEGAL-1 and ACC-3 are deployed ([smoke](vm-reliability.md#smoke-through-cloudflare-ops-9)) | implement · Sonnet | `scripts/deploy/smoke.sh` | S (~6 calls, 1 file) | OPS-1 | – |
| OPS-11 | Load run script: `scripts/ops/loadtest.py` (locust, installed by hand in the Mac's `.venv`, not a project dependency); tester credentials from a git-ignored file under `data/`. The owner runs it: run 1 Mon 5 Oct 08:00-08:15 PDT (browse only, before OWNER-5, feeds DEC-17), run 2 in STAGE-1 part B (5o) ([Load run](vm-reliability.md#load-run-ops-11)) | implement · Sonnet (script); owner (runs) | `scripts/ops/loadtest.py` (new) | S (~8 calls, 1 file) | OPS-1; run 2 needs the P2 fantasy batch | – (read-mostly; run 2 writes bets and orders in season `2026-dryrun` only) |
| SEC-1 | Auth hardening, no schema change: per-session CSRF token; CSRF on POST /login; POST /logout; signed `rl_csrf` double-submit cookie; URL-encode `next`; throttle pruning plus a per-username counter; handle normalisation, regex, reserved names and password policy (min 10) inside `create_user` | own · Opus (Fable reads in FABLE-1a) | `racinglines/web/app.py`, `users.py`, `admin.py`, `demo.py`, `templates/login.html`, `templates/base.html`, `scripts/deploy/smoke.sh`, `tests/test_auth.py` (new), `tests/test_views.py` | L (~35 calls, 9 files) | – | – (the cookie format change signs everyone out once: deploy between sessions) |
| BOOK-1 | Taker page for the private book (`/fantasy/book`) with a bet form posting to the existing `/book/markets/{id}/take`, behind `RACINGLINES_FANTASY_BOOK`; first committed tests for generate/bet/settle | implement · Sonnet | `racinglines/web/app.py`, `views.py`, `templates/fantasy_book.html` (new), `templates/base.html`, `tests/test_private_book.py` (new) | M (~18 calls, 5 files) | – | ⚠️ bet path |
| BOOK-2 | Private-book safety fixes: quote bounds (fair 0.01-0.99, spread 0.02-0.30, yes+no >= 1.00); settle only open/closed markets (re-settle needs an admin reason); `SELECT ... FOR UPDATE` in `record_bet` and settle; one "latest forecast" rule; de-dup generated markets with NULL `market_link_id`; `settle_from_exchange` note names the real exchange | implement · Sonnet (Fable reviews) | `racinglines/markets/private_book.py`, `racinglines/web/app.py`, `tests/test_private_book.py` | M (~20 calls, 3 files) | BOOK-1 | ⚠️ settlement code: Fable reads the footer and the diff before merge |
| ACC-1 | `fantasy_schema_v1`: one additive Alembic revision plus models for every table and column in the [names](fantasy-launch.md#names-used-across-these-docs), with the `account_type` backfill and a real downgrade | own · Opus (Fable reviews) | `racinglines/db/models.py`, `migrations/versions/2026MMDD_<rev>_fantasy_schema_v1.py` (new), `tests/test_fantasy_schema.py` (new), `docs/database.md` | L (~30 calls, 4 files) | OPS-8 (merge order) | ⚠️ DB migration; on a branch by Fri 2 Oct, merged only at OWNER-8 |
| MAIL-1 | Mailer: `racinglines/web/mailer.py` with `RACINGLINES_MAIL_BACKEND` set to `log` or `smtp` (STARTTLS on 587, 10 s timeout, background send with 3 retries, daily cap), plain-text templates, `racinglines mail test --to` | implement · Sonnet | `racinglines/web/mailer.py`, `racinglines/cli/mail.py`, `templates/mail/*.txt` (all new), `racinglines/cli/__init__.py`, `deploy/vm/racinglines.env.example`, `tests/test_mailer.py` (new) | M (~16 calls, 9 files) | – | – |
| LEGAL-1 | Draft `/terms`, `/privacy`, `/rules` (TERMS_VERSION 2026-10-08): F$ paper money with no cash value, no prizes, 18+, one account per person, not investment advice, data sources and attribution, deletion and retention; owner placeholders where a decision is open | implement · Sonnet (Fable reads in FABLE-1a) | `templates/terms.html`, `privacy.html`, `rules.html` (new), `racinglines/web/app.py`, `tests/test_views.py` | S (~10 calls, 5 files) | OWNER-2 | – (a plain-language draft; not legal advice) |
| DRY-1 | R16 closed reliability dry run, Thu 1 Oct 18:00 PDT to Sun 4 Oct 12:00 PDT: monitoring, backups, alerts and Kalshi sync on; 5 or fewer admin-created staff testers ([tester block](#dry-1-the-r16-testers), backup first); the in-app book only if BOOK-1/BOOK-2 are deployed; incident log | owner + Haiku (log readback) | `/opt/racinglines/data/backups/r16-dryrun-<UTC>.log` (VM) | weekend | OPS-2, OPS-3, OPS-5, OPS-7 | – (creating the testers writes `users`, so `ops backup --label r16-testers` comes first) |

Notes:

- OPS-2 thresholds live in [VM reliability](vm-reliability.md): recorder under 5 min, Kalshi sync under 35 min,
  signals under 15 min inside the weekend window, fantasy tick under 30 min while a fantasy season is open, disk
  under 80%, backup under 26 h.
- `racinglines/cli/__init__.py` has `GROUPS = (...)` on one line, and `main()` refuses any group not in it. OPS-3
  adds `ops`, MAIL-1 adds `mail` and ACC-4 adds `fantasy`. MAIL-1 and ACC-4 rebase onto `main` after the ops batch,
  so each adds its name to the tuple as it stands and the merges do not conflict.
- OPS-5 must run before the R16 book opens. Verify on the VM: `journalctl -u racinglines-kalshi-sync` shows a run
  every 30 min, and the KXF1RACE-BAH26 links were updated within 35 min. Watch for Kalshi 429s. It ticks U2 in
  [the roadmap](todo.md).
- DRY-1: no sign-up and no public invite. The existing R16 live-test plan ([F1 live test](f1-live-roadmap.md);
  T1 on Kalshi since it lists R16, the private book as a demo) runs on the Thursday code plus the additive ops
  items only. Testers bet the in-app book only if BOOK-1 and BOOK-2 are merged and deployed by Thu 1 Oct 12:00
  PDT; the owner then sets `RACINGLINES_FANTASY_BOOK=1` (plus anything else BOOK-1's footer says the page needs)
  for the weekend, and back to 0 on Mon 5 Oct.

**Exit criteria.**

- racinglines-health, racinglines-backup and racinglines-kalshi-sync timers active on the VM before Thu 1 Oct
  20:30 PDT; a forced test alert reached the owner's phone.
- First nightly dump in the bucket with the lifecycle set; snapshot schedule `racinglines-daily` attached;
  Healthchecks.io dead-man and Cloudflare tunnel notification configured.
- First timed restore-to-scratch drill done on the Mac, elapsed time recorded.
- R16 weekend completed with an incident log; no trading flag touched; A/C/K records unaffected.
- ACC-1 (`fantasy_schema_v1`) complete on its branch; SEC-1, MAIL-1, BOOK-2 and LEGAL-1 PRs open or merged with
  switches off; OPS-6 and OPS-8 reviewed and waiting for Monday.

### P2: Schema on the VM, fantasy features, staging rehearsal (Mon 5 Oct - Wed 7 Oct)

**Goal.** Settle and review R16. Ship OPS-6 and OPS-8 in the Monday window. Apply `fantasy_schema_v1` to the VM
after a backup and a restored-copy trial, with the owner's sign-off. Merge and deploy each reviewed piece as soon as
it is ready, with switches off: accounts on Tue 6 Oct, trading and settlement on Wed 7 Oct. Wire Proton SMTP.
Rehearse in two parts on the VM with tester invite codes, and replay R16 settlement on a restored copy.

| ID | Task | Role · model | Files | Size | Depends on | Money flag |
|---|---|---|---|---|---|---|
| OWNER-5 | R16 Monday routine: settle, reconcile, scorecard, live report; disable `racinglines-live-f1@2026-16.timer` | owner | `reports/<R16 event>/report.md` | M (existing routine) | DRY-1 | ⚠️ live-event unit |
| DRY-2 | R16 dry-run retro: incidents, alert noise, backup and restore timings, memory and disk peaks; queue fixes | own · Opus | `docs/vm-reliability.md` | S (~8 calls) | DRY-1, OPS-4 | – |
| OWNER-6 | Sign decision batch B: DEC-15, DEC-16, DEC-17 (the rest were answered early, Thu 1 Oct) | owner | [Decisions](#decisions) | S | DRY-2 | – |
| OWNER-7 | If DEC-17 = yes: resize racinglines-vm to e2-medium in the Monday window (stop, set machine type, start, smoke) | owner | GCE instance racinglines-vm | S (~15 min, 2-3 min downtime) | DEC-17 | ⚠️ restarts every unit on the VM (no race session on Mon 5 Oct) |
| INT-1 | Integration branch `work/fantasy-integration`: each evening Fri 2 - Tue 6 Oct, rebuild it from `main` plus `work/acc-1` and every P2 branch with a footer, run the full suite, report conflicts and the last line. Never merged itself | own · Opus | – (a test branch) | S per evening | ACC-1 | – |
| ACC-2 | Try `fantasy_schema_v1` on a restored copy (OPS-4), then add the `data_changes` entry and the `docs/data-changes.md` line naming the backup | own · Opus | `docs/data-changes.md`, `scripts/ops/restore_scratch.sh` | S (~10 calls) | ACC-1, OPS-4 | ⚠️ writes the scratch DB only |
| OWNER-8 | Apply `fantasy_schema_v1` on the VM Tue 6 Oct 09:00 PDT (16:00 UTC): merge the PR, `vm.sh deploy --migrate` (dumps first), smoke, check `alembic current` | owner | `migrations/versions/2026MMDD_<rev>_fantasy_schema_v1.py` | S (~30 min) | ACC-2, OPS-8 | ⚠️ needs special attention: a DB migration against the VM; needs the owner's explicit sign-off in the same turn |
| ACC-3 | Sign-up and account flows behind `RACINGLINES_SIGNUP`: `/signup`, `/verify/{token}`, `/verify/resend`, `/password/forgot`, `/password/reset/{token}`, `/account`, `/account/delete`; login by handle or email; `session_epoch` in `rl_session`; the sign-up cap; Turnstile when keys are set; `ensure_admin` never touches a non-staff account | own · Opus (Fable reads in FABLE-1a) | `racinglines/web/accounts.py` (new), `users.py`, `app.py`, templates `signup`, `verify`, `forgot`, `reset`, `account` (new), `login`, `base`, `tests/test_signup.py` (new), `tests/test_auth.py` | XL (~45 calls, 12 files) | ACC-1, SEC-1, MAIL-1 | – (auth and sessions: reviewed like money-adjacent code) |
| ACC-4 | Seasons, membership and ledger: `racinglines/fantasy/seasons.py` and `ledger.py`; at verification a `season_members` row with the locked role plus the F$ grant; admin role change refused for locked members without an override reason; `racinglines fantasy season` / `invite` CLI, with `fantasy` added to `GROUPS` | implement · Sonnet (Fable reads in FABLE-1a) | `racinglines/fantasy/__init__.py`, `seasons.py`, `ledger.py`, `racinglines/cli/fantasy.py` (all new), `racinglines/cli/__init__.py`, `racinglines/web/admin.py`, `tests/test_fantasy_seasons.py`, `tests/test_ledger.py` (new) | L (~28 calls, 8 files) | ACC-1 | ⚠️ the ledger: idempotent by UNIQUE(ref_table, ref_id, kind) |
| ROLE-1 | Player makers and demo separation: Lab launch, forecast promotion and exchange syncs become staff-only; `demo_context` bubbles only for demo viewers; `/live` labels the demo taker's picks; admin totals split by `account_type`; players' `/markets` goes to `/fantasy/markets` | implement · Sonnet (Fable reads in FABLE-1a) | `racinglines/web/app.py`, `views.py`, `jobs.py`, `admin.py`, templates `_macros`, `live_f1`, `live_picks`, `login`, `tests/test_views.py` | M (~22 calls, 9 files) | ACC-1 | – (the permission gates that keep takers from fair values and staff tools) |
| BOOK-3 | Private book for players: taker free-balance check and stake entry; maker collateral = worst-case liability within free balance; per-market `max_liability`; `closes_at` from the F1 stage schedule with auto-close; `season_id` and `fair_prob_at_bet` on bets; handle shown to counterparties; sprint kinds excluded from player mirrors | own · Opus (Fable reads in FABLE-1b) | `racinglines/fantasy/book.py` (new), `racinglines/markets/private_book.py`, `app.py`, `views.py`, templates `house`, `house_market`, `fantasy_book`, `tests/test_fantasy_book.py` (new) | L (~35 calls, 8 files) | ACC-4, BOOK-2 | ⚠️ bet and collateral rules |
| EXCH-1 | Exchange paper trading for takers: `racinglines/fantasy/exchange.py` on a live book from `racinglines/markets/books.py` (10 s cache, 30 s max age); walk levels to limit and shares; Kalshi taker fee via `venue_replay.Kalshi.taker_fee`; sell-to-close at bid; kinds allow-list; closed at session start; per-user rate limit; `/fantasy/markets`, POST `/fantasy/orders`; import-guard test. Venue scope follows DEC-7 (answered Thu 1 Oct) | own · Opus (Fable reads in FABLE-1b) | `racinglines/fantasy/exchange.py`, `racinglines/markets/books.py`, `templates/fantasy_markets.html` (all new), `app.py`, `tests/test_fantasy_exchange.py` (new), `tests/test_signals.py` | XL (~40 calls, 6 files) | ACC-4, EXCH-0 | ⚠️ paper fill and fee logic; must never import the order path |
| STAT-1 | Stats: `racinglines/fantasy/stats.py` fills `fantasy_event_results` and `fantasy_stats` using `reporting/metrics.curve_stats` for drawdown (positive) and Sharpe (x sqrt(24)); equity at bid; eligibility minimums; `racinglines fantasy stats [--full]` | implement · Sonnet | `racinglines/fantasy/stats.py` (new), `racinglines/cli/fantasy.py`, `tests/test_fantasy_stats.py` (new) | M (~18 calls, 3 files) | ACC-4 | – |
| SETTLE-1 | `racinglines fantasy tick` + `racinglines-fantasy.service/.timer` (10 min): auto-close; settle book markets from results (private U8 rule applied directly, not through `RACINGLINES_CANCELLED_RACE_RULES`) and mirrored markets from any exchange; settle `fantasy_positions` from `resolved_yes`; idempotent payouts; stats refresh; alert on anything unsettled 24 h after the race. **The tick gates on season status, not on `RACINGLINES_FANTASY`** (see [Off switch](#off-switch)). Adds `scripts/ops/replay_settle.py` for REPLAY-1 | own · Opus (Fable reads in FABLE-1b) | `racinglines/fantasy/settle.py` (new), `racinglines/cli/fantasy.py`, `deploy/vm/systemd/racinglines-fantasy.service`, `.timer` (new), `scripts/ops/replay_settle.py` (new), `tests/test_fantasy_settle.py` (new) | L (~36 calls, 6 files) | BOOK-3, EXCH-1, STAT-1, OPS-5 | ⚠️ needs special attention: settlement plus a new VM unit |
| STAT-2 | Pages: `/fantasy` (balance, equity, open positions, history), `/leaderboard` (maker and taker boards, venue filter, season select, handles only, login-only), MCP leaderboard tool | implement · Sonnet | `app.py`, templates `fantasy`, `leaderboard` (new), `base`, `racinglines/mcp/tools.py`, `racinglines/mcp/server.py`, `tests/test_views.py`, `tests/test_mcp.py` | M (~20 calls, 8 files) | STAT-1 | – |
| ADM-1 | Admin: `/admin/fantasy` (season dates and status, invites, member search with paging, suspend, role override with reason, F$ adjust with reason, manual settle queue, revoke sessions, anonymise); MCP `SQL_HIDDEN` adds `activity_log`, `email_tokens`, `invite_codes`; IPs pruned after 90 days | implement · Sonnet (Fable reads in FABLE-1b) | `racinglines/web/admin.py`, `templates/admin_fantasy.html` (new), `racinglines/mcp/tools.py`, `racinglines/fantasy/ledger.py`, `tests/test_admin_fantasy.py` (new) | L (~28 calls, 5 files) | ACC-4, SETTLE-1 | ⚠️ manual settlement and bankroll adjustments |
| MAIL-2 | Generate the Proton SMTP token for noreply@racinglines.bet; add the `RACINGLINES_SMTP_*` / `RACINGLINES_MAIL_*` block to `/etc/racinglines.env` (backend still `log`); restart web; `racinglines mail test --to <owner Gmail>` with `--backend smtp` | owner | `/etc/racinglines.env` (VM) | S (~20 min) | OWNER-3, MAIL-1 | – (the token lives only in `/etc/racinglines.env`, never in git or chat) |
| LEGAL-2 | Tue 6 Oct by 12:00 PDT: approve the terms, privacy and rules text; read the F1/OpenF1 data terms; sign DEC-22. (The Kalshi and Polymarket terms were read Thu 1 Oct, LEGAL-2a, for DEC-7) | owner | `templates/terms.html`, `privacy.html`, `rules.html` | M (~1.5 h reading) | LEGAL-1 | – |
| FABLE-1a | Pre-merge review of the accounts batch: footers and diffs of SEC-1, ACC-3, ACC-4, ROLE-1 and LEGAL-1; writes the Tue 6 Oct merge sequence with ⚠️ reasons | decide · Fable | – (reads footers and diffs, not transcripts) | M | ACC-3, ACC-4, ROLE-1, INT-1 | ⚠️ auth, the role gates and the ledger |
| FABLE-1b | Pre-merge review of the trading batch: footers and diffs of BOOK-3, EXCH-1, STAT-1, SETTLE-1, STAT-2 and ADM-1, plus INT-1's last run; writes the Wed 7 Oct merge sequence | decide · Fable | – (reads footers and diffs) | M | BOOK-3, EXCH-1, SETTLE-1, ADM-1, STAT-2, INT-1 | ⚠️ the review of every settlement and fill change |
| DOC-2 | Doc sync after the merges: `docs/webapp.md`, `docs/database.md`, `docs/cli.md`, `docs/vm-deploy.md` (`--migrate`, the new units, the machine type if resized), `docs/todo.md` U2 tick; the `/racinglines101` fantasy section | scout · Haiku | those files plus `racinglines/web/templates/racinglines101.html` | M (~12 calls, mechanical) | FABLE-1b | – |
| REPLAY-1 | R16 settlement replay on a restored copy: a `2026-dryrun` book market on the R16 event and a KXF1RACE-BAH26 position, settled by the real tick from the R16 classification and `resolved_yes`; outcome and elapsed time recorded | own · Opus (the SETTLE-1 worker) + owner runs the block | `scripts/ops/replay_settle.py`, `data/backups/replay-r16-<UTC>.log` (Mac) | S (~20 min) | SETTLE-1 merged, OPS-4 | – (writes the scratch DB only) |
| STAGE-1 | Staging rehearsal on the VM in two parts: **A** Tue 6 Oct 18:00-20:00 PDT (accounts, invites, mail, the role lock, Turnstile); **B** Wed 7 Oct 17:00-21:00 PDT (book, exchange, settlement, stats, admin, deletion, demo). Backup first, season `2026-dryrun`, `RACINGLINES_SIGNUP=invite` with tester codes | owner + Haiku (log readback) | `/etc/racinglines.env` (VM), `/opt/racinglines/data/backups/staging-<UTC>.log` | M (~2 h + ~4 h) | A: OWNER-8, FABLE-1a, MAIL-2. B: FABLE-1b | – (writes test players to the production DB, so `ops backup --label staging` comes first) |
| OWNER-9 | R17 checkpoints: Wed 7 Oct check Kalshi and Polymarket for R17 race and sprint listings; `RACINGLINES_KALSHI_SPRINTS` per DEC-12; Thu 8 Oct tier call; enable `racinglines-live-f1@2026-17.timer` before Fri 9 Oct 00:30 PDT (07:30 UTC) | owner | `/etc/racinglines.env` (VM), `racinglines-live-f1@2026-17.timer` | S | OWNER-5 | ⚠️ live-event unit |

**Exit criteria.**

- R16 settled, reconciled and reported; `racinglines-live-f1@2026-16.timer` disabled.
- OPS-6 and OPS-8 deployed Mon 5 Oct; `fantasy_schema_v1` on the VM, applied by `vm.sh deploy --migrate` after
  its automatic dump; the `data_changes` row and the [Data changes](data-changes.md) line name the dump; the
  restored-copy trial log exists.
- All P2 PRs merged with the switches off; `racinglines check`, `python -m pytest -m "not live"` and
  `mkdocs build --strict` green; `git diff --stat 1c417b2 -- tests/golden` empty.
- `racinglines mail test` from the VM delivered to Gmail within 2 minutes with SPF/DKIM/DMARC pass.
- REPLAY-1 settled both R16 test positions correctly; STAGE-1 parts A and B passed with no open P0 bug; decision
  batches B and C signed.

#### DRY-1: the R16 testers

Thu 1 Oct before 18:00 PDT, after the ops batch is deployed (for `ops backup`). Paste the
[shell helpers](#owner-command-blocks) first.

```sh
# VM (production) — DRY-1 step 1: backup before creating the tester accounts (⚠️ first step of a DB-writing change)
startlog r16-testers
rl ops backup --label r16-testers 2>&1 | sudo -u racinglines tee -a "$LOG"
rl db changes --add "DRY-1: up to 5 R16 staff tester accounts created at /admin/users; backup racinglines-before-r16-testers" 2>&1 | sudo -u racinglines tee -a "$LOG"
```

Step 2, in a browser at https://racinglines.bet/admin/users: create up to five accounts (role taker, or maker if
the tester is to quote the book), each password generated in your password manager and sent to the tester
privately. Passwords never go into the log.

```sh
# VM (production) — DRY-1 step 3: the tester accounts (read-only); the usernames are needed at launch step 4
rlsql <<'SQL' 2>&1 | sudo -u racinglines tee -a "$LOG"
SELECT id, username, role, active, created_at FROM users WHERE created_at >= '2026-10-01' ORDER BY id;
SQL
```

#### OWNER-5: the R16 Monday routine

This is the existing routine from [F1 live test](f1-live-roadmap.md#9-after-the-weekend-mon-5-oct) and the
[weekend routine](todo.md#weekend-routine); it is listed here for sequencing only. `live settle` writes the
database, so the backup comes first.

```sh
# VM (production) — OWNER-5, Mon 5 Oct (after: bash scripts/deploy/vm.sh ssh, then the helper block)
# ⚠️ needs special attention: writes live_events and stops a live-event unit
startlog r16-monday
rl ops backup --label r16-settle 2>&1 | sudo -u racinglines tee -a "$LOG"
rl live settle live/f1/2026-16.toml 2>&1 | sudo -u racinglines tee -a "$LOG"
rl live report live/f1/2026-16.toml 2>&1 | sudo -u racinglines tee -a "$LOG"     # no --pdf here: deploy/vm/setup.sh installs no browser
sudo systemctl disable --now racinglines-live-f1@2026-16.timer 2>&1 | sudo -u racinglines tee -a "$LOG"
```

The reconciliation and the fair-price scorecard follow the F1 live test plan. If `RACINGLINES_FANTASY_BOOK` was
set to 1 for the dry run, set it back to 0 with `setenv RACINGLINES_FANTASY_BOOK=0` and restart web.

#### OWNER-9: R17 checkpoints

```sh
# VM (production) — OWNER-9 step 1, Wed 7 Oct: what has been listed since 1 Oct (read-only)
startlog r17-listings
rlsql <<'SQL' 2>&1 | sudo -u racinglines tee -a "$LOG"
SELECT exchange, prediction, count(*) AS links, min(created_at) AS first_listed
FROM market_links WHERE created_at >= '2026-10-01' GROUP BY 1, 2 ORDER BY 1, 2;
SQL
```

Only if DEC-12 = yes and Kalshi lists R17 sprint markets. Turning on sprint classification retags links on the
next Kalshi sync, so the backup comes first (`CLAUDE.md`).

```sh
# VM (production) — OWNER-9 step 2, Wed 7 Oct: sprint markets on (DEC-12)
# ⚠️ needs special attention: the next Kalshi sync retags market links
startlog kalshi-sprints
rl ops backup --label kalshi-sprints 2>&1 | sudo -u racinglines tee -a "$LOG"
sudo cp -p /etc/racinglines.env /etc/racinglines.env.before-kalshi-sprints
setenv RACINGLINES_KALSHI_SPRINTS=1
sudo systemctl restart racinglines-web
sudo grep '^RACINGLINES_KALSHI_SPRINTS=' /etc/racinglines.env | sudo -u racinglines tee -a "$LOG"
rl db changes --add "R17: RACINGLINES_KALSHI_SPRINTS=1 (DEC-12); backup racinglines-before-kalshi-sprints" 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — OWNER-9 step 3, Thu 8 Oct, after the 18:00 PDT tier call and before Fri 00:30 PDT (07:30 UTC)
# ⚠️ needs special attention: starts a live-event unit
startlog r17-timer
sudo systemctl enable --now racinglines-live-f1@2026-17.timer 2>&1 | sudo -u racinglines tee -a "$LOG"
systemctl --no-pager list-timers 'racinglines-live-f1@*' 2>&1 | sudo -u racinglines tee -a "$LOG"
```

#### Turnstile and the rate-limiting rule (DEC-16)

Only if DEC-16 = yes. Owner, Tue 6 Oct before STAGE-1 part A (about 15 minutes):

1. Cloudflare dashboard > Turnstile > Add widget: name `racinglines-signup`, hostname `racinglines.bet`, mode
   Managed. Copy the site key and the secret key into your password manager.
2. On the VM, add them without printing: `setenv RACINGLINES_TURNSTILE_SITEKEY=<site key>
   RACINGLINES_TURNSTILE_SECRET=<secret>`, then `sudo systemctl restart racinglines-web`. (Type the values at the
   prompt; do not tee this line.)
3. Cloudflare dashboard > racinglines.bet > Security > WAF > Rate limiting rules (if the plan allows one): one rule
   for URI path starting with `/login`, `/signup` or `/password`, 10 requests per minute per IP, action Block for 10
   minutes.

STAGE-1 part A line 5c checks both.

#### The Fable review briefs

```text
# EST: reads 3 diffs and footers · model: Fable (decide)
Task: FABLE-OPS, Thu 1 Oct by 09:00 PDT, before the P1 ops batch merge
Read: the footers and diffs of OPS-2, OPS-3 and OPS-5 (new VM units, the backup path, a timer that writes
  market_links). Not transcripts.
Check: every unit is Type=oneshot with a timeout; nothing runs as root that need not; ops backup never overwrites
  an existing dump; the bucket.sh guard refuses a push of db/ from the Mac; the Kalshi sync respects rate limits
Report: merge / fix first / hold per task, the evidence line for each, what was not checked
```

```text
# EST: reads 5 diffs and footers, writes one merge sequence · model: Fable (decide)
Task: FABLE-1a pre-merge review of the accounts batch, by Tue 6 Oct 08:00 PDT
Read: the footers and diffs of SEC-1, ACC-3, ACC-4, ROLE-1 and LEGAL-1; INT-1's last run. Not transcripts.
Check: CSRF on every POST; session_epoch ends sessions; the sign-up cap and invite limits hold; ensure_admin never
  touches a non-staff account; takers never reach fair values, Lab launch, promotion or syncs; ledger entries are
  idempotent by UNIQUE(ref_table, ref_id, kind); git diff --stat 1c417b2 -- tests/golden is empty; every new
  behaviour is behind a switch that is off by default
Report: verdict per task, the evidence line for each, the merge sequence with ⚠️ reasons, what was not checked
```

```text
# EST: reads 6 diffs and ~15 footers, writes one merge sequence · model: Fable (decide)
Task: FABLE-1b pre-merge review of the trading batch, Wed 7 Oct by 12:00 PDT
Read: every remaining P2 footer; the diffs of BOOK-3, EXCH-1, STAT-1, SETTLE-1, STAT-2, ADM-1; INT-1's last run;
  the notes from the BOOK-2, ACC-1 + OPS-8 and FABLE-1a reads. Not transcripts.
Check: fantasy code never imports racinglines/markets/polymarket/trade.py, racinglines/markets/kalshi/trade.py or
  post_order; nothing writes paper_positions or strategy_signals; a second tick changes nothing; the tick settles
  with RACINGLINES_FANTASY=0 while a season is open; takers never see fair value or edge;
  RACINGLINES_CANCELLED_RACE_RULES untouched; git diff --stat 1c417b2 -- tests/golden is empty
Report: verdict per task (merge / fix first / hold), the evidence line for each, the merge sequence, what was not
  checked
```

#### LEGAL-2: what the owner reads

**LEGAL-2a, Thu 1 Oct by 12:00 PDT (about 30 minutes):** the Kalshi and Polymarket API and market-data terms (may a
third-party site show their prices to signed-in users, with attribution?). Answer DEC-7 by 18:00 PDT, so EXCH-1's
venue scope is known before it starts on Sun 4 Oct. If Kalshi forbids display, EXCH-1 builds Polymarket only and
the launch is the private book plus Polymarket season markets.

**LEGAL-2, Tue 6 Oct by 12:00 PDT:** the three page drafts from LEGAL-1 and the F1 and OpenF1 data terms; sign
DEC-22. None of this is legal advice; counsel is the owner's call.

#### DOC-2: the doc sync

After FABLE-1b's merges, one Haiku pass over `docs/webapp.md` (roles, accounts, auth), `docs/database.md` (new
tables), `docs/cli.md` (`racinglines fantasy`, `ops`, `mail`), `docs/vm-deploy.md` (`--migrate`, the new units, the
machine type if OWNER-7 resized), the U2 tick in `docs/todo.md`, and a fantasy section in
`racinglines/web/templates/racinglines101.html`. PR #71 already rewrote the freeze text in `CLAUDE.md` and
`docs/vm-deploy.md`, so DOC-2 leaves it. Verify: `mkdocs build --strict`.

### P3: Go/no-go and invite-gated soft launch (Thu 8 Oct)

**Goal.** Decide on evidence at 12:00 PDT (19:00 UTC), then open invite-gated sign-up for `2026-s1` at 18:00 PDT
(Fri 9 Oct 01:00 UTC), ahead of the Singapore book opening (Fri 9 Oct 00:30 PDT), with a paste-ready off switch.

| ID | Task | Role · model | Files | Size | Depends on | Money flag |
|---|---|---|---|---|---|---|
| GO-1 | Go/no-go: Fable reads the checklist evidence (test output, logs, rehearsal notes) and writes a verdict; the owner signs at 12:00 PDT or triggers the fallback | decide · Fable + owner | [Go / no-go](#go-no-go) | S | STAGE-1, REPLAY-1, LEGAL-2, FABLE-1b | ⚠️ the launch call |
| LAUNCH-1 | Soft launch at 18:00 PDT: backup; close `2026-dryrun`; create `2026-s1` (DEC-4 dates, DEC-5 bankrolls); deactivate the R16 testers; invite codes; set `RACINGLINES_FANTASY=1`, `RACINGLINES_SIGNUP=invite`, `RACINGLINES_FANTASY_BOOK=1`, `RACINGLINES_FANTASY_EXCHANGE=1`, `RACINGLINES_MAIL_BACKEND=smtp`; restart web; smoke; send invites from admin@racinglines.bet | owner | `/etc/racinglines.env` (VM), `fantasy_seasons`, `invite_codes` | S (~45 min) | GO-1 | ⚠️ needs special attention: production DB writes plus switch flips. Do not run `vm.sh public on` (DEC-8) |

**Exit criteria.**

- Go/no-go signed by the owner at 12:00 PDT, or the fallback triggered.
- Pre-launch backup taken and named in `data_changes`; `2026-dryrun` closed; `2026-s1` created; R16 tester
  accounts deactivated.
- Switches set, web restarted, `smoke.sh` green through https://racinglines.bet; `vm.sh public off` confirmed.
- First invited player signed up, verified email and was granted F$.

### P4: Singapore soft-launch weekend, F1 R17 (Fri 9 Oct - Sun 11 Oct)

**Goal.** Run the first public-facing weekend with on-call alerts, deploys only between sessions, and complete
settlement of every player position by Sunday evening. Sessions: FP1 Fri 08:30 UTC; Sprint Qualifying Fri 12:30;
Sprint Sat 09:00; Quali Sat 13:00; Race Sun 12:00; results ~15:00 UTC.

| ID | Task | Role · model | Files | Size | Depends on | Money flag |
|---|---|---|---|---|---|---|
| OPS-10 | Singapore on-call: phone alerts on; deploys only in the [deploy windows](vm-reliability.md#deploy-windows); incident log; support@ inbox (below); the scout reads logs on request | owner + Haiku | `/opt/racinglines/data/backups/r17-oncall-<UTC>.log` (VM) | weekend | LAUNCH-1 | – |
| SETTLE-2 | Sun 11 Oct after results (~08:00 PDT): confirm the tick settled every book market and Kalshi position (venue resolution may lag); clear the manual queue by 18:00 PDT; `ops backup --label after-r17-settle`; leaderboard snapshot; disable `racinglines-live-f1@2026-17.timer` | owner + Haiku | `/admin/fantasy/settle` | S | OPS-10 | ⚠️ settlement and a live-event unit; re-settle only through the admin route with a reason |

**The support@ inbox.** The owner is the only cover. Check support@racinglines.bet (the catch-all and the reply-to
of every app mail) after each session and at least every 6 waking hours from Thu 8 Oct 18:00 PDT to Mon 12 Oct;
reply within 12 hours. Keep two saved replies in Proton: "no verification mail" (resend from `/verify/resend`, or
the admin verifies by hand after checking the address) and "delete my account" (`/account/delete`, or the admin
anonymises). If the owner will be away for more than 12 hours, run the [off switch](#off-switch) first: sign-up
closes and the tick keeps settling.

Abuse response during the weekend: the [off switch](#off-switch), then revoke invite codes and suspend accounts
through `/admin/fantasy` (the "sign-up abuse wave" runbook in [VM reliability](vm-reliability.md)). SETTLE-2's steps
are in [Fantasy trading](fantasy-trading.md).

**Exit criteria.**

- No unplanned outage over 15 minutes (health log); no trading flag changed.
- Every R17 book market and fantasy position settled, or queued with a reason, by Sun 11 Oct 18:00 PDT.
- Leaderboard spot check: 3 players' `fantasy_stats` match their `bankroll_entries` sums.
- Post-settle backup taken; `racinglines-live-f1@2026-17.timer` disabled after settlement.

### P5: Retro, report and the road to open sign-up (Mon 12 Oct; follow-on to Thu 22 Oct)

**Goal.** Report the soft launch at the project's report bar, decide on open sign-up for R18, and queue the
deferred scope.

| ID | Task | Role · model | Files | Size | Depends on | Money flag |
|---|---|---|---|---|---|---|
| REPORT-1 | Soft-launch report: sign-ups, verified share, active players by role, bets and orders, F$ turnover, settle latency, uptime from the health log, incidents, alerts, what it does and doesn't show; rendered with `markdown_html.render` | own · Opus (draft), Fable (verdict) | `reports/2026-10-11-singapore-fantasy/report.md`, `img/` | M (~20 calls) | SETTLE-2 | – |
| OWNER-10 | Retro decisions: open sign-up for R18 (Thu 22 Oct) or stay invite-only; the DMARC `p=reject` decision; transactional mail provider or stay on Proton; go/no-go for NEXT-1 and NEXT-2 | owner | – | S | REPORT-1 | – |
| NEXT-1 | Makers on exchange markets (target R19 or later): factor the `maker_replay` fill loop into a function human quotes can call, keep `tests/golden/f1_maker_replay.json` byte-identical, fetch trades from the Kalshi timer outside the signals window, behind `RACINGLINES_FANTASY_EXCHANGE_MAKERS` | decide (design) then own · Fable (design), Opus (build) | `racinglines/markets/strategies/maker_replay.py`, `racinglines/fantasy/exchange.py`, `tests/golden/f1_maker_replay.json` (unchanged) | XL | OWNER-10 | ⚠️ touches the replay the frozen profiles are scored with; golden parity is the exit test |
| NEXT-2 | Tape-only sports and OG.com for takers: U9 tapes timer; NASCAR/MotoGP/IndyCar Kalshi taker trading settled on venue resolution; OG.com venue class once its fee is confirmed | own · Opus | `deploy/vm/systemd/`, `racinglines/fantasy/exchange.py`, `exchanges/og.toml` | L | OWNER-10 | ⚠️ new VM units and settlement sources; probe each source from the Mac first |

**Exit criteria.**

- `reports/2026-10-11-singapore-fantasy/report.md`, `.html` and `.pdf` published with a verdict and a "what this
  does and doesn't show" section.
- The owner's decision on open sign-up for Thu 22 Oct recorded.
- The DMARC `p=reject` decision recorded (quarantine has been on since before the go/no-go).
- NEXT-1 and NEXT-2 briefs written with size, done and verify.

## Merge sequence

Branches are `work/<task id in lowercase>` (ACC-1 is `work/acc-1`). The owner merges. Every merge touching
money-adjacent code carries "⚠️ needs special attention" and the reason in the block. The golden baseline is `main`
on 29 Sep (1c417b2), and the one golden check used everywhere is `git diff --stat 1c417b2 -- tests/golden`.

### Pre-merge checks

Run on each branch before its merge is proposed, not after (`CLAUDE.md`). Run the full suite too when the local
database is up. `UPDATE_GOLDEN=1` is never used this sprint.

```sh
# LOCAL (Mac) — on the task's branch, before proposing the merge
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git diff --stat 1c417b2 -- tests/golden    # must print nothing
```

### P0: the sprint docs (DOC-1)

```sh
# LOCAL (Mac) — DOC-1 step 1, Wed 30 Sep: rebase the docs branch in its worktree (not pushed yet, so no force push)
cd /Users/lalligagger/py_dev/racinglines-fantasy
git fetch origin && git rebase origin/main    # the branch sits one merge behind main (PR #70)
mkdocs build --strict
git push -u origin docs/fantasy-launch-plan
```

```sh
# LOCAL (Mac) — DOC-1 step 2: merge it in the main checkout; docs only
cd /Users/lalligagger/py_dev/racinglines
git checkout main && git pull
git merge --no-ff docs/fantasy-launch-plan
mkdocs build --strict
git push
```

### P1: the ops batch (Thu 1 Oct by 12:00 PDT)

Additive items only, after FABLE-OPS. Needs OWNER-1 (PR #71) merged first. OPS-6 and OPS-8 are not in this batch.

```sh
# LOCAL (Mac) — P1 ops batch, run in order
git checkout main && git pull
git merge --no-ff work/exch-0    # probe fixtures, their README, and tests/fixtures/fantasy/ in ALLOWED_DATA (tests/test_no_data_in_git.py)
git merge --no-ff work/ops-1     # /healthz: public JSON, no secrets, no user counts
git merge --no-ff work/ops-9     # smoke.sh: /healthz through Cloudflare; the page checks stay behind arguments until LEGAL-1 and ACC-3 deploy
git merge --no-ff work/ops-3     # ⚠️ needs special attention: new VM unit racinglines-backup, the bucket.sh push guard (the backup path), and the ops CLI group
git merge --no-ff work/ops-2     # ⚠️ needs special attention: new VM units racinglines-health.service/.timer and ops alerts
git merge --no-ff work/ops-4     # restore_scratch.sh; a Mac-only script that never touches the racinglines database
git merge --no-ff work/ops-5     # ⚠️ needs special attention: new VM unit racinglines-kalshi-sync (U2), writes market links every 30 min
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git diff --stat 1c417b2 -- tests/golden    # must print nothing
git push
```

```sh
# VM (production), via scripts/deploy/vm.sh from the Mac — deploy the ops batch
# ⚠️ needs special attention: a production deploy; by Thu 1 Oct 12:00 PDT (19:00 UTC), well before the R16 book opens
bash scripts/deploy/vm.sh deploy
bash scripts/deploy/smoke.sh https://racinglines.bet
```

Then turn on the three timers with the block in
[VM reliability, installing the new units](vm-reliability.md#installing-the-new-units): it takes
`ops backup --label kalshi-sync-timer` first, writes the `data_changes` row, and runs each unit once by hand. That
block is the only copy; there is no short version here.

### P1: the book batch

By Thu 1 Oct 12:00 PDT only if the testers are to use it in the R16 dry run; otherwise any time before Mon 5 Oct.
BOOK-2 merges only after a Fable read of its footer and diff.

```sh
# LOCAL (Mac) — P1 book batch, run in order
git checkout main && git pull
git merge --no-ff work/book-1    # ⚠️ needs special attention: the bet path (/fantasy/book posts to the existing /book/markets/{id}/take), behind RACINGLINES_FANTASY_BOOK=0
git merge --no-ff work/book-2    # ⚠️ needs special attention: private-book settlement and locking (FOR UPDATE, settle guards, quote bounds); Fable has read it
python -m pytest tests/test_private_book.py tests/test_settlement_rules.py -m "not live"
python -m pytest -m "not live"
git diff --stat 1c417b2 -- tests/golden    # must print nothing
git push
```

```sh
# VM (production), via scripts/deploy/vm.sh from the Mac — deploy the book batch in a deploy window
# ⚠️ needs special attention: the bet path and private-book settlement reach production (behind RACINGLINES_FANTASY_BOOK=0)
bash scripts/deploy/vm.sh deploy
bash scripts/deploy/smoke.sh https://racinglines.bet
```

### P2: the order

The order is **OPS-6 + OPS-8 (Mon) -> ACC-1 (OWNER-8, Tue 09:00) -> SEC-1 -> MAIL-1 -> LEGAL-1 -> ACC-3 -> ACC-4 ->
ROLE-1 (Tue afternoon) -> BOOK-3 -> EXCH-1 -> STAT-1 -> SETTLE-1 -> STAT-2 -> ADM-1 (Wed)**. The P2 branches that
need the new models start from `work/acc-1` and are rebased onto `main` after step 1. INT-1 has been running them
together on `work/fantasy-integration` since Fri 2 Oct, so the rebases are not their first contact.

**Step 0, Mon 5 Oct, in the Monday window after OWNER-5: OPS-6 and OPS-8.** Fable has read OPS-8 with ACC-1.

```sh
# LOCAL (Mac) — P2 step 0
git checkout main && git pull
git merge --no-ff work/ops-6     # ⚠️ needs special attention: edits the racinglines-recorder and racinglines-signals units; its first deploy recreates the Postgres container once (log settings)
git merge --no-ff work/ops-8     # ⚠️ needs special attention: the deploy path (vm.sh deploy refuses new Alembic revisions without --migrate, and dumps first with it)
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git diff --stat 1c417b2 -- tests/golden    # must print nothing
git push
```

```sh
# VM (production), via scripts/deploy/vm.sh from the Mac — deploy OPS-6 and OPS-8 (no race session on Mon 5 Oct)
# ⚠️ needs special attention: restarts the database container once and changes the deploy path
bash scripts/deploy/vm.sh deploy
bash scripts/deploy/smoke.sh https://racinglines.bet
```

**Step 1, Tue 6 Oct 09:00 PDT (16:00 UTC): `fantasy_schema_v1` (OWNER-8).** The detailed blocks, including the
restored-copy trial, are in [Fantasy accounts](fantasy-accounts.md); the rollback is the
[bad migration](vm-reliability.md#bad-migration) runbook.

```sh
# LOCAL (Mac) — P2 step 1a: merge ACC-1
# ⚠️ needs special attention: a DB migration (new tables, new users columns, the account_type backfill). Before
#    this: ACC-2's restored-copy trial log exists, Fable has read the footer and diff, and OPS-8 is deployed.
git checkout main && git pull
grep -q -- '--migrate' scripts/deploy/vm.sh && echo "OPS-8 is in main"
git merge --no-ff work/acc-1
alembic heads                             # exactly one head: fantasy_schema_v1's revision
python -m pytest -m "not live"
git diff --stat 1c417b2 -- tests/golden   # must print nothing
git push
```

```sh
# VM (production), via scripts/deploy/vm.sh from the Mac — P2 step 1b: apply it
# ⚠️ needs special attention: runs a DB migration against the VM. Needs the owner's explicit sign-off in the
#    same turn. vm.sh dumps to data/backups/db/racinglines-before-deploy-<sha>-<UTC>.sql.gz first and writes a
#    data_changes row. Rollback = the bad-migration runbook in vm-reliability.md; the downgrade has not been
#    rehearsed on the VM.
bash scripts/deploy/vm.sh deploy main --migrate
bash scripts/deploy/smoke.sh https://racinglines.bet
```

**Step 2, Tue 6 Oct after step 1: SEC-1 and MAIL-1.** SEC-1 changes the cookie format and signs everyone out
once; Tuesday has no race session. The mail backend stays `log`. MAIL-2 follows the deploy.

```sh
# LOCAL (Mac) — P2 step 2
git checkout main && git pull
git merge --no-ff work/sec-1     # CSRF on login and logout, rl_csrf, throttle, handle and password policy; signs everyone out once
git merge --no-ff work/mail-1    # mailer and the mail CLI group, RACINGLINES_MAIL_BACKEND stays log
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git diff --stat 1c417b2 -- tests/golden    # must print nothing
git push
```

```sh
# VM (production), via scripts/deploy/vm.sh from the Mac — deploy SEC-1 and MAIL-1; then MAIL-2 (email-setup.md)
bash scripts/deploy/vm.sh deploy
bash scripts/deploy/smoke.sh https://racinglines.bet
```

**Step 3, Tue 6 Oct 13:00-16:00 PDT, after FABLE-1a and LEGAL-2: the accounts batch.** LEGAL-1 goes first because
the sign-up page links to `/terms`, and only after LEGAL-2 approves the text (the pages are public once deployed).

```sh
# LOCAL (Mac) — P2 step 3, in FABLE-1a's order
git checkout main && git pull
git merge --no-ff work/legal-1   # /terms, /privacy, /rules (TERMS_VERSION 2026-10-08), text approved at LEGAL-2
git merge --no-ff work/acc-3     # ⚠️ needs special attention: sign-up, verify, reset, sessions and deletion (auth), all behind RACINGLINES_SIGNUP=off
git merge --no-ff work/acc-4     # ⚠️ needs special attention: the F$ ledger (grants at verification, idempotent entries), the role lock and the fantasy CLI group
git merge --no-ff work/role-1    # ⚠️ needs special attention: the permission gates (staff-only Lab, promote and sync; demo separation)
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git diff --stat 1c417b2 -- tests/golden    # must print nothing
git push
```

```sh
# VM (production), via scripts/deploy/vm.sh from the Mac — deploy the accounts batch by 16:00 PDT, switches still off
bash scripts/deploy/vm.sh deploy
bash scripts/deploy/smoke.sh https://racinglines.bet
```

**Step 4, Wed 7 Oct 12:00-16:00 PDT, after FABLE-1b: the trading batch.**

```sh
# LOCAL (Mac) — P2 step 4, in FABLE-1b's order
git checkout main && git pull
git merge --no-ff work/book-3    # ⚠️ needs special attention: bet and collateral rules for players (balance checks, maker liability, auto-close)
git merge --no-ff work/exch-1    # ⚠️ needs special attention: paper fill and fee logic against live venue books; never imports the order path
git merge --no-ff work/stat-1    # stats and the canonical drawdown and Sharpe
git merge --no-ff work/settle-1  # ⚠️ needs special attention: settlement of book markets and exchange positions, the new racinglines-fantasy unit, the replay script
git merge --no-ff work/stat-2    # /fantasy, /leaderboard, the MCP leaderboard tool
git merge --no-ff work/adm-1     # ⚠️ needs special attention: manual settlement, bankroll adjustments, anonymisation
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git diff --stat 1c417b2 -- tests/golden    # must print nothing
git push
```

```sh
# VM (production), via scripts/deploy/vm.sh from the Mac — deploy the trading batch by 16:00 PDT, switches still off
# ⚠️ needs special attention: settlement code and a new unit reach production; no new Alembic revision, so no --migrate
bash scripts/deploy/vm.sh deploy
bash scripts/deploy/smoke.sh https://racinglines.bet
```

DOC-2 merges after step 4 (docs only; `mkdocs build --strict`), before the go/no-go.

## Decisions

Every decision is open until the owner signs it here and in [the roadmap's owner decisions](todo.md#owner-decisions).
**DEC-1 and DEC-22 are not legal advice**; neither is any other wording on this page about prizes, terms or
jurisdictions. Until a decision is signed, workers build to its recommendation, and anything undecided stays behind
a switch that is off.

Batches: **A** by Wed 30 Sep 18:00 PDT (OWNER-2). **Early** by Thu 1 Oct 18:00 PDT (Fri 2 Oct 01:00 UTC): DEC-1,
DEC-5, DEC-7, DEC-10, DEC-11, DEC-13 and DEC-14, because LEGAL-1, ACC-4, ROLE-1, BOOK-3, EXCH-1, STAT-1 and
SETTLE-1 build on them from Sat 3 Oct. **B** by Mon 5 Oct 18:00 PDT, DEC-17 by 12:00 PDT (OWNER-6). **LEGAL-2** by
Tue 6 Oct 12:00 PDT (DEC-22). **C** by Wed 7 Oct 12:00 PDT. **Go** at Thu 8 Oct 12:00 PDT (GO-1).

| ID | Question | Options | Recommendation | Needed by | Batch | Status |
|---|---|---|---|---|---|---|
| DEC-1 | Prizes: paper-money fantasy with no prizes, or a sweepstakes/contest with prizes? | (a) No prizes, no entry fee, F$ with no cash value; the leaderboard is the only reward. (b) Sweepstakes: free entry plus prizes; needs official rules, a free entry method, "void where prohibited", and in some states registration or bonding above a prize threshold. (c) Paid-entry skill contest: rules differ state by state; avoid. | (a) for all of `2026-s1`: no prizes of any kind (no cash, gift cards or merchandise tied to rank) and no fees. With no consideration and no prize it is a free game. Adding prizes brings in sweepstakes and contest law, and pairing prizes with event-contract prices could draw gaming or CFTC attention. Treat any prize later as a new decision taken with counsel. Not legal advice. | Thu 1 Oct 18:00 PDT (drives the LEGAL-1 draft) | Early | open |
| DEC-2 | Invite-only or open sign-up for the soft launch, and who tests at R16? | (a) Invite codes with `RACINGLINES_SIGNUP_CAP=50`. (b) Open sign-up with the cap. (c) Admin-created accounts only. | (a) Invite codes, cap 50, issued by the owner; open sign-up considered at the retro for Thu 22 Oct. R16: 5 or fewer admin-created staff testers, no sign-up. | Wed 30 Sep 18:00 PDT | A | open |
| DEC-3 | Email provider for app mail (verification, reset, email change)? | (a) Proton SMTP token from noreply@racinglines.bet (smtp.protonmail.ch:587). (b) A transactional provider (Postmark, Resend, SES) on a sending subdomain. (c) Both: Proton now, switch later. | (c) Proton SMTP token for the invite-gated launch: low volume, one vendor, one DNS setup, and GCE allows port 587. The mailer speaks generic SMTP, so switching to Postmark or Resend on a subdomain later is an env change plus DNS. Switch before open sign-up if volume passes about 100 mails a day or mail lands in spam (Proton's paid SMTP cap is undisclosed). | Wed 30 Sep 18:00 PDT (before DNS work) | A | open |
| DEC-4 | Dates of the first fantasy season (`2026-s1`)? | Start at the soft launch; end after Abu Dhabi, at a fixed date, or TBD. | `signup_opens_at` Thu 8 Oct 18:00 PDT; trading from R17. `ends_at` NULL (TBD) until the owner sets it, with a recommended end once the 2026 championship markets resolve (expected 7-8 Dec, after Abu Dhabi on 6 Dec; earlier if Qatar or Abu Dhabi is cancelled). Roles stay locked until the season's status becomes `closed`. | Wed 7 Oct 12:00 PDT (sign-up page copy) | C | open |
| DEC-5 | Starting bankrolls and limits? | Amounts per role; per-bet cap; maker liability cap; top-ups. | Takers F$1,000, makers F$10,000 (matching the demo profiles). Per-bet and per-exchange-order cap F$100 (`MAX_STAKE`). Per-maker-market `max_liability` F$1,000. One bankroll per member across all venues. No top-ups except admin corrections with a reason. | Thu 1 Oct 18:00 PDT (ACC-4 and BOOK-3 build on it) | Early | open |
| DEC-6 | May makers quote exchange-listed markets at launch? | (a) Yes, paper quotes filled by the real tape. (b) No; makers quote the private book only. | (b) No. The fill loop sits inside `maker_replay`, the golden parity must hold, and trades are fetched only in the signals window. Target R19 or later (NEXT-1). | Wed 30 Sep 18:00 PDT | A | open |
| DEC-7 | Data terms: may players see Kalshi and Polymarket prices (and F1/OpenF1-derived data)? | (a) Signed-in players only, with source and timestamp. (b) Public pages. (c) Drop a venue whose terms forbid it. | (a) Prices only to signed-in players, attributed with the time fetched. No logged-out price pages, no API, no export. The owner reads Kalshi's and Polymarket's API/market-data terms on Thu 1 Oct (LEGAL-2a), before EXCH-1 starts. If Kalshi forbids third-party display, EXCH-1 builds Polymarket only and the launch is the private book plus Polymarket season markets. | Thu 1 Oct 18:00 PDT (EXCH-1 scope) | Early | open |
| DEC-8 | Run `vm.sh public on` for the launch? | (a) Never; launch through the Cloudflare tunnel only. (b) Run it (needs the owner's explicit sign-off in the same turn). | (a) Do not run it. It opens plain-HTTP tcp:8000 to the internet and bypasses Cloudflare: no TLS, no Turnstile or rate limits, and a spoofable CF-Connecting-IP header that the throttle trusts. The launch switch is `RACINGLINES_SIGNUP=invite` in `/etc/racinglines.env`. The go/no-go confirms `vm.sh public off` and that no tcp:8000 firewall rule exists. | Thu 8 Oct 12:00 PDT (go/no-go) | Go | open |
| DEC-9 | Which private book do human players use, and does the simulated crowd interact with them? | (a) The in-app DB book (`house_markets` / `house_bets`). (b) The file-based live book. (c) A new combined ledger. | (a) The in-app book for players. The live book stays the demo showcase, with the simulated crowd trading only against the demo maker, clearly labelled. | Wed 30 Sep 18:00 PDT | A | open |
| DEC-10 | What do the maker and taker roles mean for players, and how strict is the lock? | Hard lock / lock with admin override; player makers keep or lose Lab, forecast promotion and exchange sync. | Hard lock for the season, with an admin override that requires a written reason (`activity_log` `role_override`), meant for mistakes within 48 h of sign-up. Player makers generate, mirror, reprice and open/close private-book markets only. Lab launch, forecast promotion and exchange syncs become staff-only, because promoting a forecast changes prices for everyone. | Thu 1 Oct 18:00 PDT (ACC-4 and ROLE-1 build on it) | Early | open |
| DEC-11 | Who settles fantasy markets, and by which rules? | Admin click only / automatic timer / hybrid. | Hybrid. `racinglines-fantasy.timer` settles book markets from results (`settle_from_results`; private-book U8 rule: void on cancel, relocated R16 settles on the result) and exchange positions from the venue's own resolution (`resolved_yes`). Anything odd goes to the admin queue. Re-settle only through admin with a reason. The tick runs while a season is open, whatever `RACINGLINES_FANTASY` says. `RACINGLINES_CANCELLED_RACE_RULES` is not changed, so A/C/K are unaffected. | Thu 1 Oct 18:00 PDT (SETTLE-1 builds on it) | Early | open |
| DEC-12 | Sprint markets at R17 Singapore? | Include on exchange and book / exchange only / exclude. | Exchange taker trading on Kalshi sprint markets if Kalshi lists them: `RACINGLINES_KALSHI_SPRINTS=1` on the VM, settled on venue resolution. Exclude sprint kinds from the private book, which cannot settle them today. | Wed 7 Oct 12:00 PDT | C | open |
| DEC-13 | Scoring and leaderboards? | One board or separate maker/taker boards; rank metric; public or login-only. | Separate maker and taker boards (the book is zero-sum between them). Takers rank by equity (open positions marked at the venue bid) and makers by settled balance. A player needs 5 or more settled bets or fills to rank. Sharpe and drawdown are shown but not ranked. Boards are login-only and show handles only. | Thu 1 Oct 18:00 PDT (STAT-1 builds on it) | Early | open |
| DEC-14 | Trading while a session is running (in-play)? | Allowed at live venue prices / closed at session start. | Closed at the start of the session that decides the market (race kinds at lights out, pole at qualifying, sprint at the sprint start), for both exchange and book. This avoids latency games against a 10-second-stale book. | Thu 1 Oct 18:00 PDT (EXCH-1 and BOOK-3 build on it) | Early | open |
| DEC-15 | What happens to the demo accounts after launch? | Remove, keep as they are, or keep but separate. | Keep "Try the demo" on the login page with `account_type` demo, left out of leaderboards, stats and admin totals. Show the `demo_context` bubbles only to demo viewers (instead of deleting them), and label the demo taker's picks on `/live`. ROLE-1 builds this from Sat 3 Oct; a different answer on Mon is a small change. | Mon 5 Oct 18:00 PDT | B | open |
| DEC-16 | Bot and abuse protection for public forms? | None / Cloudflare Turnstile / Turnstile plus a Cloudflare rate-limiting rule. | Turnstile on `/signup` and `/password/forgot` and a Cloudflare rate-limiting rule on `/login`, `/signup` and `/password` if the plan allows one, plus app-level limits. The owner sets them up on Tue 6 Oct before STAGE-1 part A ([Turnstile](#turnstile-and-the-rate-limiting-rule-dec-16)). | Mon 5 Oct 18:00 PDT | B | open |
| DEC-17 | Resize the VM before launch? | Stay on e2-small (2 GB) / e2-medium (4 GB). | e2-medium during the Mon 5 Oct window (2-3 minutes of downtime), unless the R16 dry run shows memory peaks under 60% with swap unused. Players, Lab jobs, the recorder, signals, the Kalshi sync, Postgres and cloudflared share one shared-core box. | Mon 5 Oct 12:00 PDT | B | open |
| DEC-18 | Recovery targets for the soft launch? | RPO / RTO / availability levels. | RPO 24 h (nightly dump plus daily disk snapshot, plus a dump before every DB-writing change), RTO 4 h (restore or rebuild runbook, timed in the OPS-4 drill), 99% availability over the soft launch measured by the health log, deploys between sessions. | Thu 1 Oct 12:00 PDT | A | open |
| DEC-19 | Which bucket is authoritative for VM backups? | Old `gs://racinglines-data-650570086451` (cloud-session project) / new `racinglines-data-<num>` in project racinglines. | The new bucket in project racinglines, where the VM service account has `storage.objectUser`. The old bucket stays read-only for cloud sessions. After cutover, `bucket.sh push` of `db/` from the Mac is refused. | Thu 1 Oct 12:00 PDT | A | open |
| DEC-20 | Which markets are tradable at the soft launch ("more info coming")? | Per venue and kind: Kalshi F1 race and season, Polymarket F1 season (race markets if listed), OG.com, tape-only sports, private-book F1, downhill. | At launch: Kalshi F1 race markets for R17 (win, podium, top10, constructor_top, pole and h2h if listed; sprint per DEC-12) and F1 season futures on Kalshi and Polymarket, both for takers; private-book F1 R17 markets from the promoted forecast. Not at launch, shown as "coming soon": OG.com, NASCAR/MotoGP/IndyCar tapes (NEXT-2), downhill (no event until 2027). Each doc carries owner-input placeholders until this is final. | Wed 30 Sep 18:00 PDT for build scope; final list Wed 7 Oct 12:00 PDT | A, then C | open |
| DEC-21 | DMARC policy and where reports go? | `p=none` / `p=quarantine` / `p=reject`; `rua` to a mailbox or to Cloudflare DMARC Management. | Create `_dmarc` at `p=none` with `rua` to Cloudflare DMARC Management (free, on Cloudflare DNS) on Fri 2 Oct. Move to `p=quarantine` (`pct` left at its default, same `rua`) as soon as email-setup step 11 tests 3-4 and MAIL-2 step 7 show SPF/DKIM/DMARC PASS at Gmail and a second provider: target Tue 6 Oct, before STAGE-1 part A, and no later than the go/no-go. `p=reject` after the season. Reason: the soft launch sends password-reset links from a new domain, and at `p=none` a spoofed reset mail from noreply@racinglines.bet is delivered; only Proton sends as the domain, so quarantine is low-risk and testable first. | Wed 30 Sep 18:00 PDT (before the DNS records are added) | A | open |
| DEC-22 | Terms, privacy and age wording? | 18+ attestation or date of birth; jurisdiction limits; who reviews. | An 18+ attestation checkbox (no date of birth stored), "not available where prohibited" with no geo-blocking at the soft launch, one account per person, IPs kept 90 days, deletion = anonymise. A plain-language Claude draft that the owner reviews, with counsel if wanted. Not legal advice. | Tue 6 Oct 12:00 PDT (before LEGAL-1 deploys) | LEGAL-2 | open |
| DEC-23 | Launch date and fallback? | Soft launch Thu 8 Oct / slip to Thu 22 Oct. | Launch Thu 8 Oct 18:00 PDT only if every go/no-go line is signed. Otherwise R17 runs as closed dry run #2 with 25 or fewer testers, and the soft launch moves to Thu 22 Oct (before R18 FP1, Fri 23 Oct 17:30 UTC / 10:30 PDT). | Thu 8 Oct 12:00 PDT | Go | open |

## Owner command blocks

How every VM (production) block on this page runs. Open a shell on the VM from the Mac, then paste the helper
block once per ssh session. Each later block starts its own log with `startlog <name>` and tees to it as the
`racinglines` user, the same convention as block 0 in [VM reliability](vm-reliability.md). The helpers run commands
as the `racinglines` user with `/etc/racinglines.env` loaded, the same way `vm.sh` does. Secrets never go into a
log: no block prints a token, a password or an invite code into one.

```sh
# LOCAL (Mac) — open a shell on the VM
bash scripts/deploy/vm.sh ssh
```

```sh
# VM (production) — shell helpers, once per ssh session
startlog() { export LOG=/opt/racinglines/data/backups/$1-$(date -u +%Y%m%dT%H%M%SZ).log; sudo -u racinglines mkdir -p /opt/racinglines/data/backups && sudo -u racinglines touch "$LOG" && echo "logging to $LOG"; }
rl()    { sudo -u racinglines -H bash -c 'cd /opt/racinglines && set -a && . /etc/racinglines.env && set +a && exec .venv/bin/racinglines "$@"' rl "$@"; }
rlsql() { sudo -u racinglines -H bash -c 'cd /opt/racinglines && docker compose exec -T db psql -U racinglines -d racinglines -v ON_ERROR_STOP=1 -P pager=off'; }
setenv() { for kv in "$@"; do k=${kv%%=*}; sudo sed -i "/^${k}=/d" /etc/racinglines.env; echo "$kv" | sudo tee -a /etc/racinglines.env >/dev/null; done; }
```

`rl` runs the racinglines CLI, `rlsql` runs SQL from a heredoc (only `SELECT` statements on this page), and
`setenv KEY=value ...` replaces or adds lines in `/etc/racinglines.env` without printing them.

!!! note "New CLI flags"
    `racinglines fantasy season ...`, `racinglines fantasy invite ...`, `racinglines ops ...` and
    `racinglines mail ...` are new (ACC-4, OPS-3, OPS-2, MAIL-1). The subcommands here are the agreed names; the
    flag spellings follow the ACC-4 spec in [Fantasy accounts](fantasy-accounts.md). Run each command with
    `--help` during STAGE-1 part A and correct these blocks before launch day.

## Staging rehearsal

STAGE-1 runs on the VM in two parts, because the accounts batch deploys a day before the trading batch. It writes
test players to the production database in season `2026-dryrun`, so the backup comes first. Testers: the owner
plus up to four people the owner knows, T1 to T5, each on a different mail provider where possible (Gmail and at
least one other). Six codes are made: one each for T1-T5, and a spare (S) for the refusal checks. The Haiku scout
reads the log afterwards and lists every FAIL.

### Part A: accounts (Tue 6 Oct 18:00-20:00 PDT / Wed 7 Oct 01:00-03:00 UTC)

```sh
# VM (production) — STAGE-1 step 1: backup and log (⚠️ first step of a DB-writing change)
startlog staging
rl ops backup --label staging 2>&1 | sudo -u racinglines tee -a "$LOG"
rl db changes --add "STAGE-1 staging rehearsal: test players in season 2026-dryrun; backup racinglines-before-staging" 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — STAGE-1 step 2: the dry-run season (same values as 2026-s1, DEC-5)
rl fantasy season create 2026-dryrun --name "2026 dry run" --status open \
  --starts-at 2026-10-07T00:00:00Z --signup-opens-at 2026-10-07T00:00:00Z \
  --bankroll-taker 1000 --bankroll-maker 10000 --max-stake 100 --max-market-liability 1000 2>&1 | sudo -u racinglines tee -a "$LOG"
rl fantasy season list 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — STAGE-1 step 3: six codes (T1-T5 and a spare). The codes print once: copy them to the testers, do not tee them.
rl fantasy invite create --season 2026-dryrun --count 6 --label staging
rl fantasy invite list --season 2026-dryrun 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — STAGE-1 step 4A: switches for part A (accounts and mail only)
sudo cp -p /etc/racinglines.env /etc/racinglines.env.before-staging
setenv RACINGLINES_FANTASY=1 RACINGLINES_SIGNUP=invite RACINGLINES_SIGNUP_CAP=50 RACINGLINES_FANTASY_BOOK=0 \
       RACINGLINES_FANTASY_EXCHANGE=0 RACINGLINES_FANTASY_EXCHANGE_MAKERS=0 RACINGLINES_MAIL_BACKEND=smtp
sudo systemctl restart racinglines-web
sudo grep -E '^(RACINGLINES_(FANTASY|FANTASY_BOOK|FANTASY_EXCHANGE|FANTASY_EXCHANGE_MAKERS|SIGNUP|SIGNUP_CAP|MAIL_BACKEND)|POLYMARKET_TRADING_ENABLED|KALSHI_TRADING_ENABLED)=' /etc/racinglines.env | sudo -u racinglines tee -a "$LOG"
```

The script, run in a browser against https://racinglines.bet. The owner notes each result in the log
(`echo "PASS 5a ..." | sudo -u racinglines tee -a "$LOG"`) and screenshots the ones marked (S). `/fantasy` and
`/leaderboard` return 404 until part B deploys STAT-2; that is expected.

| # | Who | Action | Expected |
|---|---|---|---|
| 5a | T1 | Sign up as a taker with code 1, Gmail address | Verification mail within 2 minutes; Gmail "Show original" shows SPF, DKIM, DMARC PASS (S). After the link: F$1,000 granted, role locked |
| 5b | T2 | Sign up as a maker with code 2, a non-Gmail address | Verification mail arrives, not in spam (S); F$10,000 granted |
| 5c | owner | With the spare code: (i) reuse code 1; (ii) the spare with 18+ unticked; (iii) the spare with handle `admin`; (iv) if DEC-16 = yes, the spare submitted before the Turnstile widget completes, and 15 quick POSTs to `/login` from one IP | Each refused with a clear message, `signup_rejected` rows in `activity_log`, the spare still unused; the widget shows on `/signup` and `/password/forgot`; the rate-limiting rule blocks the burst |
| 5d | T3, T4, T5 | Sign up with codes 3, 4 and 5: T3 and T4 as takers, T5 as a maker | Three verified members; `rl fantasy invite list` shows codes 1-5 used and the spare unused |
| 5e | owner (admin) | Change T1's role without a reason, then with a reason, then back | Refused without a reason; allowed with one (`role_override` row) |
| 5f | T1 | `/password/forgot`, reset from the mail, then reload a second browser signed in as T1 | Reset works; the other session is signed out |

```sh
# VM (production) — STAGE-1 step 6A: switches off after part A; the season and the five testers stay for part B
setenv RACINGLINES_FANTASY=0 RACINGLINES_SIGNUP=off RACINGLINES_MAIL_BACKEND=log
sudo systemctl restart racinglines-web
sudo grep -E '^RACINGLINES_(FANTASY|SIGNUP|MAIL_BACKEND)=' /etc/racinglines.env | sudo -u racinglines tee -a "$LOG"
echo "STAGE-1 part A end $(date -u +%FT%TZ)" | sudo -u racinglines tee -a "$LOG"
```

### REPLAY-1: R16 settlement on a restored copy (Wed 7 Oct, after step 4 merges, before 17:00 PDT)

R16 is the only finished race with real results and a Kalshi resolution, and the fantasy code is not on the VM
during it. REPLAY-1 runs the real tick on it anyway, on the Mac, against a restored copy of the Wed 03:00 PDT
nightly dump. It writes the scratch database only. SETTLE-1's `scripts/ops/replay_settle.py` creates season
`2026-dryrun`, one private-book market on the R16 event with a taker bet, and one taker position on a
KXF1RACE-BAH26 market through the fantasy modules (not SQL), then runs `racinglines fantasy tick` twice.

```sh
# LOCAL (Mac) — REPLAY-1 step 1: the newest VM dump into racinglines_scratch, upgraded to head (scratch only)
git checkout main && git pull
bash scripts/ops/restore_scratch.sh
```

```sh
# LOCAL (Mac) — REPLAY-1 step 2: the real tick on R16, timed; use the scratch URL step 1 printed
mkdir -p data/backups
DATABASE_URL='<scratch URL from step 1>' python scripts/ops/replay_settle.py --event <R16 event key> \
  --kalshi-event KXF1RACE-BAH26 2>&1 | tee data/backups/replay-r16-$(date -u +%Y%m%dT%H%M%SZ).log
```

Pass: the book bet and the Kalshi position settle with the outcome that the R16 classification and
`market_links.resolved_yes` give, the payouts match by hand, the second tick changes nothing, and the elapsed time
is recorded. It is go/no-go line 19.

### Part B: trading, settlement, admin (Wed 7 Oct 17:00-21:00 PDT / Thu 8 Oct 00:00-04:00 UTC)

```sh
# VM (production) — STAGE-1 step 4B: every switch on for part B; the fantasy tick on (the backup was step 1)
startlog staging-b
setenv RACINGLINES_FANTASY=1 RACINGLINES_SIGNUP=invite RACINGLINES_FANTASY_BOOK=1 RACINGLINES_FANTASY_EXCHANGE=1 \
       RACINGLINES_FANTASY_EXCHANGE_MAKERS=0 RACINGLINES_MAIL_BACKEND=smtp
sudo systemctl restart racinglines-web
sudo systemctl enable --now racinglines-fantasy.timer
sudo grep -E '^(RACINGLINES_(FANTASY|FANTASY_BOOK|FANTASY_EXCHANGE|FANTASY_EXCHANGE_MAKERS|SIGNUP|SIGNUP_CAP|MAIL_BACKEND)|POLYMARKET_TRADING_ENABLED|KALSHI_TRADING_ENABLED)=' /etc/racinglines.env | sudo -u racinglines tee -a "$LOG"
```

| # | Who | Action | Expected |
|---|---|---|---|
| 5g | T2, T1 | T2 generates or mirrors an R17 private-book market; T1 bets F$50; T1 tries F$2,000; T1 bets past T2's capacity | F$50 debited; overdraft refused; over-capacity refused |
| 5h | T1 | Exchange order for F$20 on a Kalshi R17 market (or a season future if R17 is not listed) | Fills at the live ask; the Kalshi fee rounded up to the cent (S of the fill) |
| 5i | owner (admin) | Void the test book market; `rl fantasy tick` twice | T1's stake refunded once; the second tick changes nothing |
| 5j | owner | Set `RACINGLINES_FANTASY=0`, restart web, void a second test market, wait for the next timer tick, then set it back to 1 | The pages are hidden, and the tick still refunds the bet (the off switch does not stop settlement) |
| 5k | T1 | `/leaderboard`; the taker pages | Handles only; no staff, demo or system accounts; no fair value anywhere a taker can see (S) |
| 5l | owner (admin) | Suspend T3; adjust T4 by F$10 with a reason; revoke T5's sessions | Each works and writes an `activity_log` row with the reason; T5 is signed out |
| 5m | T5, owner | T5 signs in again and deletes their account; the owner anonymises T1-T4 through `/admin/fantasy` | Handles become `deleted-<id>`, emails NULL; ledger rows kept |
| 5n | anyone | "Try the demo" as maker and taker; `bash scripts/deploy/smoke.sh https://racinglines.bet` from the Mac | Both work; smoke passes |
| 5o | owner | OPS-11 load run 2 from the Mac: 25 sessions browsing, betting the book and placing exchange orders in `2026-dryrun` for 15 minutes; then the VM memory, OOM and 429 block ([Load run](vm-reliability.md#load-run-ops-11)) | Page p95 under 2 s, order p95 under 4 s, no 5xx, no 429, no OOM kill |

```sh
# VM (production) — STAGE-1 step 6B: switches back off; 2026-dryrun stays open until launch step 2
setenv RACINGLINES_FANTASY=0 RACINGLINES_SIGNUP=off RACINGLINES_FANTASY_BOOK=0 RACINGLINES_FANTASY_EXCHANGE=0 RACINGLINES_MAIL_BACKEND=log
sudo systemctl restart racinglines-web
rl fantasy invite revoke --season 2026-dryrun --all 2>&1 | sudo -u racinglines tee -a "$LOG"
sudo grep -E '^RACINGLINES_(FANTASY|SIGNUP|MAIL_BACKEND)=' /etc/racinglines.env | sudo -u racinglines tee -a "$LOG"
echo "STAGE-1 part B end $(date -u +%FT%TZ)" | sudo -u racinglines tee -a "$LOG"
```

`racinglines-fantasy.timer` stays enabled after the rehearsal. The tick gates on season status, so it keeps
settling `2026-dryrun` while `RACINGLINES_FANTASY=0`.

## Go / no-go

Thu 8 Oct 12:00 PDT (19:00 UTC). Fable reads the evidence and writes a verdict (GO-1); the owner signs each line.
One unsigned line means no-go. Evidence is saved under `/opt/racinglines/data/backups/gonogo-<UTC>.log` on the VM,
`data/backups/gonogo-local-<UTC>.log` on the Mac, and screenshots next to them.

| # | Check | Evidence | Signed |
|---|---|---|---|
| 1 | PR #71 merged; the running sha on the VM (`vm.sh status`) contains it and OPS-8; `/var/lib/racinglines/deploy-paused` is absent | LOCAL block (a): `vm.sh status`; VM block (c): `deploy-paused absent` | |
| 2 | `fantasy_schema_v1` applied on the VM (`alembic current` = its revision) after a `vm.sh deploy --migrate` dump; the `data_changes` row and [Data changes](data-changes.md) line name the dump; ACC-2's restored-copy trial log exists | VM block (c): `alembic current`; `rl db changes`; the ACC-2 log path | |
| 3 | On the deployed sha: `racinglines check`, `python -m pytest -m "not live"` and `mkdocs build --strict` green; `git diff --stat 1c417b2 -- tests/golden` empty | LOCAL block (b) output, last lines | |
| 4 | `POLYMARKET_TRADING_ENABLED` and `KALSHI_TRADING_ENABLED` absent or unset in `/etc/racinglines.env`; the fantasy import-guard test and `test_signal_code_never_touches_the_order_path` pass | VM block (c): the flag lines (expect none, or an empty value); LOCAL block (b) | |
| 5 | `vm.sh public off` confirmed: no firewall rule opens tcp:8000, racinglines-web listens on 127.0.0.1 only, and the site is reachable only at https://racinglines.bet through tunnel racinglines-vm (DEC-8 signed) | LOCAL block (a): `rl-test-web` NOT_FOUND; VM block (c): listeners on :8000 | |
| 6 | `APP_SECRET` is set: a web restart keeps an existing session signed in | VM block (c): count 1; screenshot of a page still signed in after `sudo systemctl restart racinglines-web` | |
| 7 | Email: Proton green for verification, MX, SPF, DKIM x3 and DMARC; mail-tester 9/10 or better; verification and reset mails from the VM reach Gmail and one other provider within 2 minutes with SPF/DKIM/DMARC pass | Screenshots: Proton domain page, mail-tester score; STAGE-1 5a, 5b, 5f | |
| 8 | Sign-up rehearsal passed: five invite sign-ups verified, granted F$ and locked the role (admin change refused without a reason); the refusals held and left the spare code unused; reset ends old sessions; `RACINGLINES_SIGNUP_CAP` set; Turnstile and the rate-limiting rule work if DEC-16 = yes | STAGE-1 part A log, lines 5a-5f | |
| 9 | `/terms`, `/privacy` and `/rules` live with TERMS_VERSION 2026-10-08; acceptance and the 18+ attestation stored; "paper money, no prizes, no cash value" on the sign-up page; DEC-1, DEC-7 and DEC-22 signed | LOCAL block (a): smoke output with the page checks on; screenshot of `/signup`; [Decisions](#decisions) | |
| 10 | Private book: a taker bet debits F$; an overdraft and a maker over capacity are refused; the market auto-closes at `closes_at`; a void refunds through the tick; re-settle refused without a reason | STAGE-1 5g and 5i; `tests/test_fantasy_book.py`, `tests/test_private_book.py` in block (b) | |
| 11 | Exchange paper trading: an order fills at the live ask with the Kalshi fee rounded up; a book older than 30 s is refused; orders refused after session start; a position settles from `resolved_yes` on a fixture; the R17 market list matches DEC-20/DEC-12 | STAGE-1 5h; `tests/test_fantasy_exchange.py`, `tests/test_fantasy_settle.py` in block (b); the OWNER-9 listings log | |
| 12 | Stats: `/leaderboard` shows only players, handles only, no fair values to takers; 3 spot-checked balances equal their `bankroll_entries` sums | STAGE-1 5k (S); VM block (d) | |
| 13 | Reliability: two consecutive nightly dumps in the bucket; a restore drill with a recorded RTO; snapshot schedule `racinglines-daily` attached; health timer green and a test alert reached the phone; Healthchecks.io dead-man and the Cloudflare tunnel notification configured; Kalshi sync under 35 min, recorder under 5 min, disk under 70%, swap on (or resized per DEC-17) | LOCAL block (a): bucket listing, snapshot policy, `/healthz`; VM block (c): timers, disk, memory, swap; the OPS-4 drill output; phone screenshot | |
| 14 | The R16 dry-run incidents closed or accepted in writing (DRY-2) | The DRY-2 section in [VM reliability](vm-reliability.md) | |
| 15 | Admin: the owner has suspended a test user, adjusted F$ with a reason, voided a market, revoked sessions and anonymised accounts on the VM | STAGE-1 5i, 5l and 5m; `activity_log` rows | |
| 16 | Rollback ready: the [off-switch block](#off-switch) pasted into the launch log; the tick settled with `RACINGLINES_FANTASY=0` (SETTLE-1's test and STAGE-1 5j); the previous good sha written down for `vm.sh deploy <sha>` | The launch log's first lines; STAGE-1 5j; block (b) | |
| 17 | Demo unaffected: the demo maker and taker one-click logins work, the demo bubbles are hidden from players, and `scripts/deploy/smoke.sh` passes against https://racinglines.bet | STAGE-1 5n; LOCAL block (a) | |
| 18 | The support@ inbox and the ntfy ops topic are monitored by the owner through Mon 12 Oct, with the saved replies in Proton ([P4](#p4-singapore-soft-launch-weekend-f1-r17-fri-9-oct-sun-11-oct)) | The owner's statement | |
| 19 | R16 settlement replay passed: the book bet and the KXF1RACE-BAH26 position settled with the right outcome, the second tick changed nothing, elapsed time recorded | The REPLAY-1 log on the Mac | |
| 20 | Cloudflare Access in front of `racinglines.bet/admin*`, or SEC-1's fallback: the staff lock keyed on username plus IP, and `/admin/sql` writes and `/admin/db` edits refused while `RACINGLINES_SIGNUP` is not `off` | A private window shows the Cloudflare login on `/admin`, or the SEC-1 tests in block (b); [VM reliability, go/no-go evidence](vm-reliability.md#gono-go-evidence-for-the-reliability-lines); [Fantasy accounts §14](fantasy-accounts.md#what-this-docs-tasks-put-on-the-gono-go) | |
| 21 | HSTS on | `curl -sI https://racinglines.bet/login` shows `strict-transport-security` ([evidence](vm-reliability.md#gono-go-evidence-for-the-reliability-lines)) | |
| 22 | DEC-16 resolved: Turnstile keys set and the widget shows on `/signup`, `/password/forgot` and `/verify/resend`; or DEC-16 recorded as "no" | Screenshots of the three pages, or the signed DEC-16 row; [Fantasy accounts §14](fantasy-accounts.md#what-this-docs-tasks-put-on-the-gono-go) | |
| 23 | The bucket's latest copy is scrubbed (manifest `"scrubbed": true`; no rows in `email_tokens`, `invite_codes` or `activity_log`; no player email) and uniform bucket-level access plus public-access prevention are on | `db/manifest.json`; the OPS-7 step 9a describe line ([evidence](vm-reliability.md#gono-go-evidence-for-the-reliability-lines)); [Fantasy accounts §14](fantasy-accounts.md#what-this-docs-tasks-put-on-the-gono-go) | |
| 24 | OPS-11 load run 2 passed: page p95 under 2 s, order p95 under 4 s, no 5xx, no 429, no OOM kill | STAGE-1 5o; the locust CSV and the VM block after it ([evidence](vm-reliability.md#gono-go-evidence-for-the-reliability-lines)) | |

**Evidence blocks.** Read-only. Replace the placeholders from `vm.sh status`.

```sh
# LOCAL (Mac) — go/no-go block (a): deployed sha, public port, bucket, snapshots, health, smoke
L=data/backups/gonogo-local-$(date -u +%Y%m%dT%H%M%SZ).log; mkdir -p data/backups
{ bash scripts/deploy/vm.sh status
  gcloud compute firewall-rules describe rl-test-web --project racinglines || echo "rl-test-web: NOT_FOUND (good)"
  gsutil ls -l "gs://$RACINGLINES_GCS_BUCKET/db/nightly/" | tail -3
  gcloud compute disks describe racinglines-vm --project racinglines --zone us-west1-b --format='value(resourcePolicies)'
  curl -s https://racinglines.bet/healthz
  bash scripts/deploy/smoke.sh https://racinglines.bet; } 2>&1 | tee "$L"
```

```sh
# LOCAL (Mac) — go/no-go block (b): the checks on the deployed sha (HEAD must equal the sha vm.sh status prints)
git checkout main && git pull && git rev-parse --short=12 HEAD
git merge-base --is-ancestor origin/work/deploy-pause HEAD && echo "PR #71 included" || echo "branch gone: check PR #71's merge commit by hand"
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
git diff --stat 1c417b2 -- tests/golden    # must print nothing
```

```sh
# VM (production) — go/no-go block (c): read-only state (after the helper block)
startlog gonogo
{ echo "== sha"; sudo -u racinglines -H git -C /opt/racinglines log -1 --format='%h %s'
  echo "== deploy-paused"; test -e /var/lib/racinglines/deploy-paused && echo PRESENT || echo absent
  echo "== alembic current"; sudo -u racinglines -H bash -c 'cd /opt/racinglines && set -a && . /etc/racinglines.env && set +a && .venv/bin/alembic current'
  echo "== trading flags (expect nothing, or an empty value)"; sudo grep -E '^(POLYMARKET|KALSHI)_TRADING_ENABLED=' /etc/racinglines.env || true
  echo "== APP_SECRET set (expect 1)"; sudo grep -c '^APP_SECRET=.' /etc/racinglines.env
  echo "== listeners on :8000 (expect 127.0.0.1 only)"; sudo ss -ltn | grep ':8000 '
  echo "== timers"; systemctl --no-pager list-timers 'racinglines-*'
  echo "== failed units"; systemctl --no-pager --failed 'racinglines-*'
  echo "== disk, memory, swap"; df -h /; free -m; swapon --show
  echo "== healthz"; curl -s http://127.0.0.1:8000/healthz; echo; } 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — go/no-go block (d): 3 ledger spot checks in 2026-dryrun (read-only)
rlsql <<'SQL' 2>&1 | sudo -u racinglines tee -a "$LOG"
SELECT f.user_id, f.balance, sum(b.amount) AS ledger_sum, f.balance = sum(b.amount) AS matches
FROM fantasy_stats f
JOIN fantasy_seasons s ON s.id = f.season_id
JOIN bankroll_entries b ON b.season_id = f.season_id AND b.user_id = f.user_id
WHERE s.slug = '2026-dryrun' AND f.venue = 'all'
GROUP BY f.user_id, f.balance ORDER BY random() LIMIT 3;
SQL
```

### Fallback

If any line is not signed at 12:00 PDT, DEC-23's fallback applies. R17 runs as **closed dry run #2**: season
`2026-dryrun` stays open, `2026-s1` is not created, and sign-up stays invite-only with 25 or fewer tester codes in
`2026-dryrun`, given to people the owner knows (not the public). The R17 live book and the paper engine run
unchanged. The failed lines get fixed during the week, and the soft launch moves to **Thu 22 Oct**, before R18
FP1 (Fri 23 Oct 17:30 UTC / 10:30 PDT), with a new go/no-go on Thu 22 Oct 12:00 PDT.

## Launch day

LAUNCH-1, Thu 8 Oct from 18:00 PDT (Fri 9 Oct 01:00 UTC), owner-run, about 45 minutes. One block per step, in
order, each tee'd to the launch log. `vm.sh public on` is **not** part of the launch (DEC-8): the site is live
through the Cloudflare tunnel, and the launch switch is `RACINGLINES_SIGNUP=invite`.

```sh
# VM (production) — step 0: the launch log (after bash scripts/deploy/vm.sh ssh and the helper block)
startlog launch
echo "launch start $(date -u +%FT%TZ); deployed $(sudo -u racinglines -H git -C /opt/racinglines rev-parse --short=12 HEAD)" | sudo -u racinglines tee -a "$LOG"
echo "previous good sha for rollback: <sha from the go/no-go>" | sudo -u racinglines tee -a "$LOG"
echo "off switch: setenv RACINGLINES_SIGNUP=off RACINGLINES_FANTASY=0 RACINGLINES_FANTASY_BOOK=0 RACINGLINES_FANTASY_EXCHANGE=0 && sudo systemctl restart racinglines-web" | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 1: backup before any launch write
# ⚠️ needs special attention: the first step of a production DB write
rl ops backup --label before-soft-launch 2>&1 | sudo -u racinglines tee -a "$LOG"
rl db changes --add "soft launch 2026-s1: backup racinglines-before-soft-launch; season, invites and switches follow" 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 2: close the dry-run season (left out of stats)
rl fantasy season close 2026-dryrun 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 3: create 2026-s1 with the DEC-4 dates and DEC-5 bankrolls
# ⚠️ needs special attention: writes fantasy_seasons; ends_at and signup_closes_at stay NULL (TBD, DEC-4)
rl fantasy season create 2026-s1 --name "2026 season 1" --status open \
  --starts-at 2026-10-09T01:00:00Z --signup-opens-at 2026-10-09T01:00:00Z \
  --bankroll-taker 1000 --bankroll-maker 10000 --max-stake 100 --max-market-liability 1000 2>&1 | sudo -u racinglines tee -a "$LOG"
rl fantasy season list 2>&1 | sudo -u racinglines tee -a "$LOG"
```

Step 4: deactivate the R16 testers. Their usernames are in the DRY-1 log (step 3). In a browser, for each one:
`/admin/users/<id>`, untick Active, save (the existing admin page, which writes an audit row); then end their
sessions with ADM-1's Revoke sessions. Then record the result:

```sh
# VM (production) — step 4: check the testers are inactive (read-only)
rlsql <<'SQL' 2>&1 | sudo -u racinglines tee -a "$LOG"
SELECT id, username, role, account_type, active FROM users
WHERE account_type = 'staff' AND role <> 'admin' ORDER BY id;
SQL
```

```sh
# VM (production) — step 5: invite codes for 2026-s1. The codes print once: copy them to your password
# manager or the invite mails, do not tee them. <N> is the first wave; sign-ups are capped at 50 in total.
rl fantasy invite create --season 2026-s1 --count <N> --label soft-launch-wave-1
rl fantasy invite list --season 2026-s1 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 6: set the switches
# ⚠️ needs special attention: switch flips on production. RACINGLINES_FANTASY_EXCHANGE=1 only if DEC-7 allows at
#    least one venue; the trading flags are not in this list and must not be.
sudo cp -p /etc/racinglines.env /etc/racinglines.env.before-soft-launch
setenv RACINGLINES_FANTASY=1 RACINGLINES_SIGNUP=invite RACINGLINES_SIGNUP_CAP=50 RACINGLINES_FANTASY_BOOK=1 \
       RACINGLINES_FANTASY_EXCHANGE=1 RACINGLINES_FANTASY_EXCHANGE_MAKERS=0 RACINGLINES_MAIL_BACKEND=smtp
sudo grep -E '^(RACINGLINES_(FANTASY|FANTASY_BOOK|FANTASY_EXCHANGE|FANTASY_EXCHANGE_MAKERS|SIGNUP|SIGNUP_CAP|MAIL_BACKEND|KALSHI_SPRINTS)|POLYMARKET_TRADING_ENABLED|KALSHI_TRADING_ENABLED)=' /etc/racinglines.env | sudo -u racinglines tee -a "$LOG"
```

```sh
# VM (production) — step 7: restart the web app; make sure the fantasy tick runs
sudo systemctl restart racinglines-web
sudo systemctl enable --now racinglines-fantasy.timer
systemctl --no-pager status racinglines-web | grep -E 'Active' | sudo -u racinglines tee -a "$LOG"
systemctl --no-pager list-timers 'racinglines-fantasy*' 2>&1 | sudo -u racinglines tee -a "$LOG"
```

```sh
# LOCAL (Mac) — step 8: smoke through Cloudflare, page checks on (OPS-9's arguments)
mkdir -p data/backups
bash scripts/deploy/smoke.sh https://racinglines.bet 2>&1 | tee data/backups/launch-smoke-$(date -u +%Y%m%dT%H%M%SZ).log
curl -s https://racinglines.bet/healthz
curl -s -o /dev/null -w '%{http_code} /signup\n' https://racinglines.bet/signup
```

Step 9: send the invites from admin@racinglines.bet in Proton, one mail per person with their code and a link to
https://racinglines.bet/signup. The reply-to for app mail is support@racinglines.bet.

```sh
# VM (production) — step 10, later that evening: the first players (read-only; no emails selected)
rlsql <<'SQL' 2>&1 | sudo -u racinglines tee -a "$LOG"
SELECT u.username, u.account_type, u.email_verified_at IS NOT NULL AS verified, m.role, m.locked_at,
       m.starting_bankroll, (SELECT sum(b.amount) FROM bankroll_entries b
                             WHERE b.season_id = m.season_id AND b.user_id = u.id) AS balance
FROM season_members m JOIN users u ON u.id = m.user_id JOIN fantasy_seasons s ON s.id = m.season_id
WHERE s.slug = '2026-s1' ORDER BY m.joined_at;
SQL
```

After launch night, add the [Data changes](data-changes.md) line naming the `before-soft-launch` dump (with the
REPORT-1 PR, or a small docs PR).

### Off switch

**The rule (decided here, built by SETTLE-1).** `racinglines fantasy tick` ignores `RACINGLINES_FANTASY`. It runs
while any fantasy season has status `open`, or has open positions or unsettled book markets, and exits 0 otherwise.
So the off switch closes sign-up, hides the fantasy pages and refuses new orders and bets, while open positions
keep settling and the health check keeps alarming if the tick heartbeat goes stale. SETTLE-1's done-when includes
a test for this in `tests/test_fantasy_settle.py`, STAGE-1 5j checks it on the VM, and
[Fantasy trading](fantasy-trading.md) must say the same.

It takes about 10 seconds and deletes nothing.

```sh
# VM (production) — OFF SWITCH (after bash scripts/deploy/vm.sh ssh and the helper block)
startlog offswitch
setenv RACINGLINES_SIGNUP=off RACINGLINES_FANTASY=0 RACINGLINES_FANTASY_BOOK=0 RACINGLINES_FANTASY_EXCHANGE=0
sudo systemctl restart racinglines-web
sudo grep -E '^RACINGLINES_(FANTASY|FANTASY_BOOK|FANTASY_EXCHANGE|SIGNUP)=' /etc/racinglines.env | sudo -u racinglines tee -a "$LOG"
systemctl --no-pager list-timers 'racinglines-fantasy*' 2>&1 | sudo -u racinglines tee -a "$LOG"    # the tick is still scheduled
```

Only if settlement itself is the problem, stop the tick as well and follow the
[fantasy tick stuck or settlement wrong](vm-reliability.md#fantasy-tick-stuck-or-settlement-wrong) runbook:

```sh
# VM (production) — stop the fantasy tick (settlement pauses; the health check will alarm on the stale heartbeat)
sudo systemctl disable --now racinglines-fantasy.timer
systemctl --no-pager list-timers 'racinglines-fantasy*' 2>&1 | sudo -u racinglines tee -a "$LOG"
```

### Rollback

A bad code deploy goes back by sha. After OPS-8, a target sha older than the database's Alembic revision deploys
with a warning and without running `alembic`, and the fantasy schema is additive, so older code runs on it
([the guard](vm-reliability.md#the-migration-guard-ops-8)). A true schema rollback is a database restore: the
[bad migration](vm-reliability.md#bad-migration) runbook.

```sh
# VM (production), via scripts/deploy/vm.sh from the Mac — ROLLBACK a bad deploy
# ⚠️ needs special attention: a production deploy; in a deploy window if a session is near
bash scripts/deploy/vm.sh deploy <previous good sha>
bash scripts/deploy/smoke.sh https://racinglines.bet
```

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Scope versus time: about 8 working days, every merge and VM write through one owner, and the fantasy code first on production on Tue 6 and Wed 7 Oct | An invite-gated F1-only launch, one-task branches tested together on `work/fantasy-integration`, reviewed pieces deployed as soon as they are ready, a two-part rehearsal, and a fallback (R17 as closed dry run #2, launch Thu 22 Oct) that is the expected outcome if STAGE-1 finds a P0 |
| Code-shaping decisions signed after the code is built | DEC-1, 5, 7, 10, 11, 13 and 14 answered by Thu 1 Oct; the rest built to the recommendation behind switches |
| Legal exposure: a public game quoting prices on real event contracts can look like bookmaking or an event-contract offering | Paper money F$, no prizes, no fees, 18+, terms reviewed by the owner and counsel if wanted (DEC-1, DEC-22); none of this is legal advice |
| Data terms: redistributing Kalshi/Polymarket prices and F1/OpenF1-derived data to third parties is unverified | Read on Thu 1 Oct before EXCH-1 starts; login-only display with attribution, no API; drop a venue if its terms forbid display (DEC-7) |
| Kalshi may not list R17 race or sprint markets in time, and R16 liquidity is thin (pole and h2h not listed) | Season futures on Kalshi and Polymarket plus the private book still give takers markets; the Wed 7 Oct check feeds the final market list |
| Settlement never ran on a real race before R17 | REPLAY-1 runs the real tick on R16's results and Kalshi resolution; go/no-go line 19 |
| A production migration on a DB with real rows; the Alembic downgrade has never been rehearsed on the VM | One additive revision, a restored-copy trial, an automatic pre-deploy dump through OPS-8, and rollback by restore |
| Risky changes on the VM the day before the R16 book opens | Only additive items (health, backup, Kalshi sync) before R16; OPS-6 and OPS-8 in the Mon 5 Oct window |
| Email deliverability through Proton SMTP: an undisclosed paid cap, reputation checks, and verification mail possibly in spam at launch | Invite cap of 50, `RACINGLINES_MAIL_DAILY_CAP`, an admin-verify fallback, and a transactional provider on a subdomain before open sign-up |
| Single VM (e2-small, 2 GB, one zone, one tunnel connector, one uvicorn process): memory pressure or a host fault takes the site down | Swap, a resize (DEC-17), the health timer plus an external dead-man, the daily snapshot, and a rebuild runbook with a measured RTO |
| Settlement mistakes are visible on real players' balances and leaderboards | An idempotent tick, the re-settle guard, the admin queue, a dump before settle-day writes, and ledger-vs-stats spot checks |
| The off switch silently stopping settlement | The tick gates on season status, not `RACINGLINES_FANTASY`; a test, STAGE-1 5j, and the health check on the tick heartbeat |
| Contamination of the frozen A/C/K records or the demo record through shared tables (`paper_positions` is deleted and rewritten per run) | Separate `fantasy_*` tables, U8 applied without touching `RACINGLINES_CANCELLED_RACE_RULES`, golden and parity tests unchanged |
| Public-surface security: bots, credential stuffing, a process-wide CSRF token and an in-memory throttle that resets on every deploy | SEC-1, Turnstile, a Cloudflare rate-limiting rule, invite codes, `session_epoch` revocation, and a Fable read of SEC-1, ACC-3 and ROLE-1 |
| Misuse of `vm.sh public on` would expose plain HTTP on tcp:8000 and let clients spoof CF-Connecting-IP | DEC-8 says never, and go/no-go line 5 checks it |
| Backup overwrite: a post-cutover `bucket.sh push` from the Mac could replace the VM's dump with a stale Mac database | The OPS-3 guard and DEC-19 |
| PII leakage: `activity_log` keeps IPs and typed usernames, and the MCP sql tool can read it | ADM-1 hides those tables, prunes IPs after 90 days, and anonymises on deletion |
| Owner attention collides: the cutover, the first live F1 book on the VM, R16, R17, two NASCAR Chase races and the launch fall within 13 days | Wed 30 Sep holds only PR #71, the cutover and batch A; Proton moved to the R16 weekend; dated decision batches, paste-ready blocks, Haiku log readback |
| A deploy during a live weekend restarts web for a few seconds and resets the in-memory throttle and demo sessions | Deploy only in the [deploy windows](vm-reliability.md#deploy-windows); PR #71 pauses and resumes timers |

## After the sprint

### REPORT-1: the soft-launch report

`reports/2026-10-11-singapore-fantasy/report.md`, charts and screenshots in `img/` next to it, drafted by Opus on
Mon 12 Oct with the verdict written by Fable. It matches the Whistler report's structure
(`reports/2026-09-27-whistler-live/report.md`) and the `CLAUDE.md` report bar: numbers over adjectives, every
setting named, a verdict. The worker reads a restored copy of the `after-r17-settle` dump (`racinglines_scratch`,
through `scripts/ops/restore_scratch.sh`), the health log and the launch and on-call logs; never production
directly. It shows handles only, never emails.

| Section | Content |
|---|---|
| Title and date line | "Singapore GP: fantasy soft launch", Sun 11 Oct 2026, F1 R17 (sprint), racinglines |
| Summary | One scene-setting paragraph, then a top-line table: invites sent and used, sign-ups, verified share, active players by role, exchange orders and fills, book bets, F$ turnover, P&L per board, median and max settle latency, uptime from the health log, incidents |
| What ran | The deployed sha, every switch value, the `2026-s1` values (DEC-4, DEC-5), the market list (DEC-20, DEC-12), the timers |
| Timeline (UTC) | Launch to last settlement, turning points in bold (first sign-up, book open, sessions, first fill, results, last settle, any incident) |
| Takers on the exchanges | Orders by venue and kind, fill rate, rejections by reason, fees, P&L; winners and losers tables with real numbers |
| Makers and the private book | Markets quoted, bets taken, liability used against `max_liability`, P&L per maker |
| Leaderboards | Top and bottom 5 per board with equity, ROI, bets and hit rate |
| Settlement | Latency per kind (race end to `settled_at`) against the REPLAY-1 time, manual-queue items and how each was resolved, re-settles with reasons |
| Operations and incidents | Uptime, alerts (count, noise), deploys and their windows, backups, mail sent and bounced, spam placement, support@ volume and reply times |
| What the app shows | Screenshots of `/signup`, `/fantasy`, `/fantasy/markets`, `/fantasy/book`, `/leaderboard` |
| What this does and doesn't show | A small invited audience, one weekend, paper money; what the numbers cannot say about open sign-up |
| Next | The open sign-up call, NEXT-1, NEXT-2, anything that failed |

```sh
# LOCAL (Mac) — render the report (HTML with the project's renderer, PDF with headless Chrome as live report does)
python -c "from racinglines.reporting.markdown_html import render; render('reports/2026-10-11-singapore-fantasy/report.md')"
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu --no-sandbox \
  --print-to-pdf="$PWD/reports/2026-10-11-singapore-fantasy/report.pdf" \
  "file://$PWD/reports/2026-10-11-singapore-fantasy/report.html"
```

### OWNER-10: retro decisions (Mon 12 Oct)

| Decision | Recommendation to discuss | Needed by |
|---|---|---|
| Open sign-up (`RACINGLINES_SIGNUP=open`) for R18 on Thu 22 Oct, or stay invite-only | Only if REPORT-1 shows no settlement error, mail in the inbox, and uptime at or above 99% | Mon 12 Oct |
| DMARC `p=reject` decision | Only after the season, and only if the reports show only Proton passing (DEC-21) | Wed 14 Oct |
| App mail: a transactional provider on a sending subdomain, or stay on Proton | Switch before open sign-up if volume passes about 100 mails a day or any mail landed in spam (DEC-3) | Before open sign-up |
| Go for NEXT-1 and NEXT-2 | Decide on the briefs below | Mon 12 Oct |

### NEXT-1 and NEXT-2 briefs

```text
# EST: XL · model: Fable (design), then Opus (build)
Task: NEXT-1 makers on exchange markets, target R19 (30 Oct - 1 Nov) or later
Scope: racinglines/markets/strategies/maker_replay.py (factor the fill loop into a function human quotes can call),
  racinglines/fantasy/exchange.py, a trades fetch from the Kalshi timer outside the signals window,
  RACINGLINES_FANTASY_EXCHANGE_MAKERS (stays 0 until the owner flips it)
Done when: tests/golden/f1_maker_replay.json is byte-identical; a player quote on a fixture tape fills exactly
  where the replay says it would
Verify: python -m pytest -m "not live"; git diff --stat 1c417b2 -- tests/golden prints nothing
Report: files changed, the verify command and its last line, what you did not check
⚠️ touches the replay the frozen profiles are scored with
```

```text
# EST: L · model: Opus
Task: NEXT-2 tape-only sports and OG.com for takers
Scope: a U9 tapes timer in deploy/vm/systemd/; NASCAR, MotoGP and IndyCar Kalshi taker trading settled on venue
  resolution in racinglines/fantasy/exchange.py; an OG.com venue class once its fee is confirmed (exchanges/og.toml)
Done when: each source was probed from the Mac first, its fixtures are in tests/fixtures/, and taker orders on a
  fixture fill and settle; every new market family is behind its own switch, off by default
Verify: python -m pytest -m "not live"
Report: files changed, the verify command and its last line, what you did not check
⚠️ new VM units and settlement sources
```

### Dates after the sprint

| When | What |
|---|---|
| Wed 14 Oct | DMARC `p=reject` decision (DEC-21, [Email setup](email-setup.md)) |
| Before open sign-up | Transactional mail provider on a subdomain if the retro says so (DEC-3) |
| Thu 22 Oct | Earliest open sign-up, or the fallback soft launch; go/no-go 12:00 PDT |
| Before 25 Oct | Freeze Kalshi maker profile K (existing item, [Kalshi history](kalshi-history.md#profile-k), [owner decisions](todo.md#owner-decisions)) |
| 23-25 Oct | F1 R18, United States GP: T1 with A, C and K on Kalshi (existing plan); the first fantasy weekend after the retro |

## Open items

- **Owner decisions:** batch A, the early answers (Thu 1 Oct), batch B, LEGAL-2, batch C and the go/no-go pair are
  all open.
- **New CLI flags.** The `racinglines fantasy season create` and `invite create|revoke` flags in the blocks above
  are the proposed spelling; ACC-4 fixes them and STAGE-1 part A checks them with `--help`.
- **Tasks outside the plan's merge order:** EXCH-0 and OPS-4 ride with the P1 ops batch, LEGAL-1 opens the Tue 6
  Oct accounts batch, DOC-1 and DOC-2 are docs-only. Confirm with FABLE-1a.
- **Stacked P2 branches.** ACC-1 reaches `main` only on Tue 6 Oct, so the P2 feature branches start from
  `work/acc-1` and rebase after OWNER-8. INT-1 carries any ACC-1 fix found at ACC-2 into the integration branch the
  same evening.
- **Agent count:** 49 spawns over the sprint, the largest wave 14 (under the ceiling of 30). Recount at FABLE-1a.
- **This branch** is one merge behind `main` (PR #70) and is rebased before its PR; the Fantasy nav
  section (the index, this runbook and the four detail pages) and the `docs/todo.md` links are in place.
