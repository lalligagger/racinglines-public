# Data off GitHub: plan

Status: **plan only** (2026-09-30). Nothing here has run. No stage starts until the overnight
Mac backfill and the F1 taker re-sweep have both finished (see [In-flight work](#in-flight-work)).

Committing data to git was a near-term patch so cloud sessions could run sweeps without network access
to the exchanges. The target is: **the VM's Postgres is the source of truth for tables, one GCS bucket
is the source of truth for files and for the copy cloud sessions read, and git carries code, docs and
pinned test fixtures only.**

**The rule (owner, 2026-09-30):** the bucket and the VM database are never down or migrating at the
same time. Every stage below changes exactly one of them, and starts only after the other one has been
checked intact. That way one of the two is always a complete, verified copy.

## How data reaches cloud sessions today

Checked on `main` at d484c07 and against the cloud bucket's listing on 2026-09-30.

| Path | What it carries | How a cloud session gets it |
|---|---|---|
| git: `data/raw/f1/fastf1/` (2020-2026) | FastF1 raw files, 1,235 files, 23 MB | the clone |
| git: `data/archive/markets/polymarket/{prices,trades}/` | Polymarket price and trade archive (Parquet), 34 MB | the clone |
| git: `data/archive/markets/kalshi/{prices,trades}/` | Kalshi price and trade archive (Parquet), 31 MB | the clone |
| git: `data/archive/db/` | `db snapshot-export`: results, laps, splits, market links and the rest of the model tables, with ids, 5.6 MB | the clone, then `db snapshot-import` in `scripts/cloud/start.sh` |
| git: `data/runs/search/<name>/` on a pushed branch | cloud sweep results (leaderboard, `results.json`, `REPORT.md`) coming *back* | `git push` every 30 minutes ([cloud sweep step 5](cloud-sweep.md#agent-protocol)) |
| old bucket `racinglines-data-650570086451` (project `project-977bffa3-…`) | `db/racinglines.sql.gz` (a **Mac** dump from 2026-09-28 02:04Z, Alembic head `e4c1a9b7d205`, before the VM existed), `live/`, `raw/mtb_dh/`, `runs/f1/`, `results/` | `scripts/cloud/bucket.py pull` with the HMAC key in the cloud environment; `start.sh` restores that dump in place of the snapshot |
| VM bucket `racinglines-data-384052502248` (project `racinglines`) | what `bucket.sh push` sent on 2026-09-28 for the VM's first restore | **not reachable** from cloud sessions (the HMAC key is scoped to the old bucket) |

Two things stand out:

- The old bucket has **no `archive/markets/` and no FastF1 files**, so today the market tapes and F1 raw
  data reach cloud sessions *only* through git. Removing them from git before the bucket carries them
  would break every sweep.
- The dump cloud sessions restore is the Mac's database from before the VM cutover. Nothing refreshes it
  from the VM ([VM deploy, Later](vm-deploy.md#later) lists the nightly push as not built).

## What lives on GitHub that shouldn't

In the tracked tree on `main` (1,378 files, 93 MB on disk; the `.git` folder is 86 MB):

- `data/raw/f1/fastf1/**`
- `data/archive/markets/polymarket/prices/**`, `…/trades/**` (and `links/` if present)
- `data/archive/markets/kalshi/prices/**`, `…/trades/**` (and `links/` if present)
- `data/archive/db/**` (the snapshot, including `market_links.parquet` and `laps.parquet`)
- `data/runs/search/**` on any sweep branch that pushed results
- every earlier version of the above in git history, on `main` and on the ~70 remote branches

Staying in git (owner, 2026-09-30): `tests/golden/` (152 KB) and `tests/fixtures/{f1,market,mtb}/`
(3 MB). They are pinned test inputs, not a data flow, and the tests must run without a bucket key.

## Target

| | Source of truth | Cloud sessions read |
|---|---|---|
| Tables (results, laps, links, model runs, books, recorded prices buffer) | VM Postgres | `db/racinglines.sql.gz` in the VM bucket, dumped nightly from the VM, with `db/manifest.json` (time, Alembic head, row counts) |
| Market tapes (Parquet archive) | VM disk, archived by the recorder; pushed to the bucket | `archive/markets/` in the VM bucket |
| FastF1 raw, downhill raw | the bucket (write once) | `raw/f1/`, `raw/mtb_dh/` |
| Cloud session output (sweep results, reports) | the bucket | written to `results/<session>/`, never to git |

Two buckets (owner, 2026-09-30): the VM project's `racinglines-data-384052502248` is the **primary**, and the
old `racinglines-data-650570086451` stays as the **backup bucket**, refreshed from the primary (stage 8). The
backup is a third copy, so a bad write to the primary never reaches the only other copy of the files. Cloud sessions get a new HMAC key for a new
service account in project `racinglines`, **read-only on the bucket plus create-only under `results/`** (an
IAM condition on the object name), so a cloud session can't overwrite the dump or the tapes. Object
versioning is already on for the VM bucket ([VM deploy step 2](vm-deploy.md)), which is what makes every
bucket stage below reversible.

**Restore recipe in a cloud session** (after stage 4's code change): `scripts/cloud/start.sh` runs
`bucket.py pull` (files and dump), checks `db/manifest.json`'s Alembic head against the checkout
(stops with a clear message on a mismatch, instead of loading a dump the code can't read), restores the dump,
then `db init`. No committed-snapshot fallback after stage 6.

One consequence to know before switching: the sweep code orders drivers by database id in places, so
seeded prices depend on ids. The VM's ids are not the Mac snapshot's ids, so **sweep numbers after the
switch are not byte-comparable with earlier cloud sweeps**. Stage 4 re-runs the baselines on the new data
so later comparisons are like for like.

## Stages

Each stage: what changes, which side stays frozen, the backup, the check, the rollback. "Frozen" means no
`vm.sh deploy` (it runs `alembic upgrade head`), no DB migration, no `link --apply` or ingest for the VM
database; and for the bucket, no uploads, deletes or key changes.

| # | Changes | Frozen and checked first | Backup | Done when | Rollback |
|---|---|---|---|---|---|
| 0 | this doc (docs PR) | nothing touched | none | merged | revert |
| 1 | nothing: inventory, read-only | both | none needed | the owner has a listing of the VM bucket, the VM's Alembic head and table row counts, and the git data file list with sizes | none |
| 2 | **bucket**: upload the git-held files (FastF1 raw, both market archives, the snapshot) to the VM bucket | VM DB (no deploy or ingest scheduled) | bucket object versioning, plus the stage 1 listing saved to `data/backups/` | a second `rsync --dry-run` reports nothing to copy; the file count per prefix matches git | restore the prior object generations, or delete the new prefixes; git still holds everything |
| 3 | **bucket**: nightly VM dump to `db/`, and VM tapes to `archive/markets/` (code PR: `bucket.sh push` using the compose `pg_dump` on Linux, a `--no-db` switch for Mac pushes, a `racinglines-bucket-push.timer`) | VM DB only read (`pg_dump` takes a consistent snapshot without locking writers) | a local VM dump in `data/backups/db/racinglines-before-bucket-push-<UTC>.sql.gz` from the first run; bucket versioning keeps each prior dump | three nightly runs land; `manifest.json` row counts match the VM | disable the timer; earlier dump generations stay in the bucket |
| 4 | cloud sessions read the VM bucket (code PR: `bucket.py pull` gains `raw/f1` and the manifest check; new service account and HMAC key; cloud environment variables switched) | VM DB (untouched); bucket (only read) | the old key and old bucket stay as they are | a cloud session with `data/raw/f1` and `data/archive/*` deleted from its checkout runs `start.sh`, `racinglines check --offline`, and a 2-job F1 baseline sweep on both venues; baselines recorded as the new reference | switch the three environment variables back to the old key; git still holds the files |
| 5 | sweep results go to `results/<name>/` in the bucket, not git (docs/cloud-sweep.md step 5 and 6, `f1 search` writes and pushes there) | both | none: it only adds objects | one cloud sweep pushes its progress to the bucket and `f1 search-import` loads it on the Mac | revert the docs PR; results can still be committed |
| 6 | git stops tracking data (code PR: `git rm -r --cached` on the allow-listed data paths, `.gitignore` allow-list removed, `tests/test_no_data_in_git.py` allows only `tests/`, `scripts/cloud/prepare.sh` rewritten as a bucket push, `start.sh` loses the snapshot fallback) | both | the files stay in history and in the bucket | a fresh cloud session passes stage 4's check again from a clean clone of `main` | revert the PR; the files come back from history |
| 7 | **git history**: remove the data paths from all history with `git filter-repo`, then force-push every branch (owner, 2026-09-30: yes) | both bucket and VM DB (git is the only thing changing) | a `git clone --mirror` kept off GitHub, plus the stage 2 bucket copy of the same files | a fresh clone has no `data/` paths in `git log --all`; `.git` drops by roughly 80 MB; tests pass on the rewritten `main` | push the mirror back (`git push --mirror --force`) |
| 8 | **backup bucket**: the old bucket becomes a copy of the primary; its cloud-session key is deleted (cloud sessions use stage 4's key) | VM DB, and the primary is only read | the backup's own object versioning; the old dump and prefixes are kept as noncurrent versions | a weekly `gcloud storage rsync` from primary to backup (no deletes) has run, from a `racinglines-backup-bucket.timer` on the VM (its service account gets write on the backup bucket only); the backup's `db/manifest.json` matches the primary's | recreate the old key; the backup's earlier versions are still there |

**Stage 7 needs its own go at the time it runs.** The owner agreed to it in the plan (2026-09-30), but it
rewrites published history with a force push, which the
[safety rails](https://github.com/lalligagger/racinglines/blob/main/CLAUDE.md#safety-rails-non-negotiable-carried-over-from-the-projects-own-rules)
allow only with the owner's explicit sign-off in the same conversation turn. It runs from the Mac, only after
stage 6 is merged and a cloud session has passed stage 4's check from a clean clone. Before it: merge or close
every open PR (rewritten history orphans their commits) and delete stale branches, so fewer branches need
rewriting. After it: every clone (the Mac, the VM's checkout, any Copilot workspace) is re-cloned, not pulled;
the VM's checkout is replaced by the next `vm.sh deploy` only after the owner re-clones it. The bucket and the
VM database are both untouched by this stage.

### Keeping the rule once this is running

- The bucket push timer is a `racinglines-*.timer`, so `vm.sh deploy` already pauses it for the length of a
  deploy and resumes it after (the same mechanism as the live-event and signals timers). A dump never runs
  during a migration.
- **Before any VM DB migration** (for example [engine task 3](engine-roadmap.md), the price-column
  migration), the latest nightly dump must be in the bucket and its manifest checked. The bucket is then the
  intact copy while the DB migrates.
- **Before any bucket restructure** (renaming prefixes, deleting old dumps, rotating keys), the VM DB must be
  healthy (`vm.sh status`) and no deploy, ingest or migration scheduled in the same window.
- A migration dry run goes on a restored copy of the bucket's dump first, never on the VM (standing practice
  in CLAUDE.md).

## In-flight work

Nothing above starts until both of these have finished.

- **F1 taker re-sweep** (a cloud session): it runs on the committed archives and the old bucket's dump, and
  pushes `data/runs/search/taker-resweep/` to its branch in git. Stages 4 to 6 change exactly those inputs
  and that output path, so they wait until its REPORT is pushed and its PR is open. Its results are the last
  ones to come back through git; stage 5 copies them to `results/taker-resweep/` in the bucket.
- **Overnight backfill** (the owner's Mac database, run from a Copilot handoff):
  it writes only the Mac database and reads the Mac's archives. Stage 2 uploads the Mac's archives, so it
  waits until the backfill is done. The backfilled model runs stay on the Mac; they reach the VM only with
  the owner's separate sign-off, as that handoff says, and after stage 3 that is a VM DB change (bucket frozen,
  dump checked first).
- **NASCAR VM runbook** (`nascar ingest`, `nascar link --apply`): these are VM DB writes. They must not share a
  window with stage 2 or 3. Order: finish the runbook steps the owner has signed off, then stage 2.

## What the owner runs (the cloud sandbox has no gcloud)

Stages 1 and 2 need only commands that exist today. Run them on the Mac (LOCAL), from `main`, after both
in-flight jobs are done. First the read-only inventory:

```
source .venv/bin/activate
git checkout main && git pull
export RACINGLINES_GCS_BUCKET=racinglines-data-384052502248
mkdir -p data/backups
UTC=$(date -u +%Y%m%dT%H%M%SZ)
gcloud storage ls --recursive --long "gs://$RACINGLINES_GCS_BUCKET/**" > data/backups/bucket-listing-before-git-data-$UTC.txt
git ls-files -s data > data/backups/git-data-files-$UTC.txt
bash scripts/deploy/vm.sh status
```

Then stage 2's dry run. It only lists what would be copied; check that no file under `archive/markets/`
would overwrite a newer VM copy before going on.

```
gcloud storage rsync --recursive --checksums-only --dry-run data/raw/f1 gs://$RACINGLINES_GCS_BUCKET/raw/f1
gcloud storage rsync --recursive --checksums-only --dry-run data/archive/markets gs://$RACINGLINES_GCS_BUCKET/archive/markets
gcloud storage rsync --recursive --checksums-only --dry-run data/archive/db gs://$RACINGLINES_GCS_BUCKET/archive/db
```

The same three lines without `--dry-run` do the upload (`rsync` without `--delete-unmatched-destination-objects`
never deletes), and running the dry run again afterwards must list nothing. Stages 3 to 6 need code PRs
first; each PR carries its own command blocks. Stage 4's key needs the owner in the Cloud console or with
`gcloud` (new service account, IAM condition, HMAC key, cloud environment variables).

## Owner decisions

Answered 2026-09-30: test fixtures and goldens stay in git; the old bucket is kept as a backup, not retired;
history is purged (stage 7), with the force push signed off by the owner when it runs.

Still open: how often the backup bucket is refreshed (default weekly, stage 8).
