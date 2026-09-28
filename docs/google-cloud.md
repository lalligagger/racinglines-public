# Google Cloud proposal

A proposal for moving racinglines off the owner's Mac onto Google Cloud, where the
[data bucket](data.md#data-bucket) already lives. Nothing here is built yet: it's the plan and
a cost estimate for the owner to decide on. Written 2026-09-28 in the
[cloud build-out](cloud-buildout.md).

## What runs today

Everything runs on one Mac.

| Piece | How it runs | Schedule | State it keeps |
|---|---|---|---|
| Database | PostgreSQL (docker-compose, port 5433) | always | 106 MB (2026-09-28): results, model runs, signals, positions, books |
| Web app | `racinglines web` (FastAPI, server-rendered) | on demand | none (the database) |
| Market recorder | `markets record --interval 60`, LaunchAgent `bet.racinglines.recorder` (`KeepAlive`) | every minute, always | book snapshots (database), hourly Parquet archive (`data/archive/markets/`) |
| Signal engine | `f1 signals`, LaunchAgent `bet.racinglines.signals` | every 5 minutes | signals and paper positions (database) |
| Live events | `racinglines live run <spec>` (Track A), a LaunchAgent per event with a lock | F1: session ends; downhill: every 2–5 s during the event | run folder (`data/runs/live/<event>/`) |
| Sweeps and searches | the CLI, by hand or in cloud sessions | on demand | `data/runs/f1/`, `data/runs/search/` |
| Alerts | macOS notifications, ntfy, webhook, log | with the recorder | `data/runs/alerts/` |

The data folders git doesn't carry come to about 100 MB (`data/runs` 18 MB, `data/raw` 29 MB,
`data/archive` 51 MB).

## Proposed architecture

One project, one region (`us-west1`, where the bucket is), no service-account keys.

| Piece | Google Cloud service | Shape |
|---|---|---|
| Database | **Cloud SQL for PostgreSQL** (Enterprise edition) | `db-g1-small` to start, 10 GiB SSD, automated backups, point-in-time recovery; private IP |
| Web app | **Cloud Run service** | request-based billing, 1 vCPU / 1 GiB, 0 minimum instances (1 if cold starts bother the demo) |
| Market recorder | **Cloud Run job** + **Cloud Scheduler** | one recording pass per minute (needs `markets record --once`, below); or an always-on service |
| Signal engine | **Cloud Run job** + **Cloud Scheduler** | every 5 minutes; a no-op outside race weekends |
| Live events | **Cloud Run job** per event | F1: triggered by Scheduler at the event's cadence; downhill: one long job running `live run` for the event window (a task can run up to 24 h) |
| Sweeps and searches | **Cloud Run job**, run by hand | 4–8 vCPU, parallel tasks for a search's combos |
| Data layer | **Cloud Storage** (the existing bucket) | mounted into Cloud Run as a volume (Cloud Storage FUSE) at `RACINGLINES_DATA` |
| Secrets | **Secret Manager** | `ADMIN_PASSWORD`, the ntfy topic, the webhook URL; later the Polymarket key |
| Images | **Artifact Registry** | one image for every piece (the CLI), built from the repo |
| Deploys | **GitHub Actions** with Workload Identity Federation | build, push, `alembic upgrade head` as a job, then deploy; no keys stored in GitHub |

**Why this shape.**
- Everything except the database scales to zero. The app is idle most of the week and busy on
  race weekends.
- One image, many entry points. Every piece is already a `racinglines` subcommand, so each Cloud
  Run job is the same image with different arguments.
- The data root is already configurable (`RACINGLINES_DATA`, `racinglines/paths.py`), so the
  bucket mount needs no code change.
- Scheduler replaces the LaunchAgents one for one.

### Service identities (no keys)

Each workload runs as its own service account, attached to it by Cloud Run. Nothing downloads a key.

| Service account | Used by | Roles |
|---|---|---|
| `rl-web` | web app | Cloud SQL Client, Cloud SQL Instance User (IAM database login), Secret Accessor (admin password) |
| `rl-jobs` | recorder, signal engine, live events, sweeps | Cloud SQL Client, Cloud SQL Instance User, Storage Object User on the bucket, Secret Accessor (alert secrets) |
| `rl-scheduler` | Cloud Scheduler | Cloud Run Invoker on the jobs |
| `rl-deploy` | GitHub Actions (federated, no key) | Artifact Registry Writer, Cloud Run Developer, Service Account User on the two above |
| `racinglines-cloud` | Claude cloud sessions (exists) | Storage Object User on the bucket, through its HMAC key |

- **Database login by IAM.** The services sign in to Postgres as their service accounts
  (Cloud SQL IAM database authentication), so there's no database password to store.
- **The one key left** is the cloud sessions' HMAC key, under the project's org-policy
  exception ([Data](data.md#data-bucket)). It can go once cloud sessions support Workload Identity
  Federation. Until then it stays scoped to the bucket's objects.
- **Real trading** (not before the owner's approval, [F1-8](f1-roadmap.md)): the Polymarket key
  goes in Secret Manager, readable by a separate `rl-trader` account only.

### The bucket as the data layer

| Prefix | Today | On Google Cloud |
|---|---|---|
| `live/` | copied up by `bucket.sh push` | written in place by the live jobs (mounted) |
| `archive/markets/` | copied up | written in place by the recorder's hourly archive |
| `runs/f1/`, `results/` | copied up | written in place by sweep jobs |
| `db/` | a dump for cloud sessions | a nightly export from Cloud SQL (Cloud SQL export to Cloud Storage), so cloud sessions stay current without the owner |

Cloud Storage FUSE has no file locks. The live runner's lock file needs a replacement: one execution
at a time. Scheduler starts a new execution on every tick even if the last one is still running, so
each step takes a Postgres advisory lock and exits if another holds it.

## Cost estimate

Monthly, at **Google's list prices**, read from the pricing pages on 2026-09-28. The pages show
Iowa (`us-central1`) by default; `us-west1` is also a Tier 1 region, but check it in the
[pricing calculator](https://cloud.google.com/products/calculator) before deciding. Usage figures
are estimates, not measurements.

**Unit prices used:**

| Item | List price |
|---|---|
| Cloud SQL `db-f1-micro` / `db-g1-small` (shared core, no SLA) | $0.0105 / h / $0.035 / h |
| Cloud SQL dedicated core (Enterprise) | $0.0413 per vCPU-hour + $0.007 per GiB-hour |
| Cloud SQL SSD storage / backups | $0.000232877 / $0.000109589 per GiB-hour |
| Cloud Run jobs and instance-based services | $0.000018 per vCPU-second, $0.000002 per GiB-second; free: 240,000 vCPU-s and 450,000 GiB-s a month |
| Cloud Run request-based services | $0.000024 per vCPU-second, $0.0000025 per GiB-second, $0.40 per million requests; free: 180,000 vCPU-s, 360,000 GiB-s, 2 million requests |
| Cloud Scheduler | $0.10 per job per month; 3 jobs free per billing account |

**Estimate:**

| Piece | Assumption | $ / month |
|---|---|---|
| Cloud SQL `db-g1-small` | 730 h | 25.55 |
| Cloud SQL storage + backups | 10 GiB SSD, ~2 GiB of backups | 1.86 |
| Web app | ~20,000 requests, ~0.5 s each, 1 vCPU | 0 (free tier) |
| Signal engine | 8,640 runs × ~10 s × 1 vCPU, plus ~2 h of weekend pricing | ~1.9 before the free tier |
| Recorder, per-minute job | ~11,500 runs on race weekends (8 days) × ~20 s × 1 vCPU, 1 GiB | ~4.6 before the free tier |
| Live events | one downhill day (6 h × 1 vCPU) or one F1 weekend | ~0.4 per event |
| Scheduler | 5 jobs (2 over the free 3) | 0.20 |
| Bucket, Secret Manager, Artifact Registry, logs | < 1 GB stored, small counts | not priced here; expected to be cents |
| **Total** | the jobs' free tier covers most of the signal engine and recorder | **about $28–35** |

**Options that change it:**

| Change | Effect |
|---|---|
| `db-f1-micro` instead of `db-g1-small` (0.6 GiB RAM, no SLA) | −$18 (7.67 instead of 25.55) |
| A dedicated-core database (1 vCPU, 3.75 GiB) | +$24 (49.31 instead of 25.55); needed for the SLA |
| High availability | about ×2 on the database |
| Recorder always on (0.5 vCPU, 0.5 GiB, 730 h) instead of per-minute | about +$22 before the free tier ($26.28 for 1.31M vCPU-s and 1.31M GiB-s, against $4.61) |
| Web app with 1 minimum instance | the idle-instance rate applies; check the calculator |
| A 4-hour, 8-vCPU search | ~$2.50 (115,200 vCPU-s and 16 GiB × 14,400 s) |
| Committed-use discounts | lower rates on the pricing pages; only worth it once the shape is settled |

## Changes to the code

| Change | Why | Size |
|---|---|---|
| A `Dockerfile` (Python 3.14, `requirements.txt`, `pip install -e .`) | one image for everything | small |
| `markets record --once` | one recording pass per Scheduler run instead of a loop | small |
| Cloud SQL IAM login in `racinglines/db/config.py` behind a setting (`cloud-sql-python-connector`, `enable_iam_auth`), off by default | no database password | small |
| A Postgres advisory lock in `live step` / `live run` next to the lock file | FUSE has no file locks | small (Track A's files) |
| Alerts without macOS notifications | ntfy and the webhook already work; macOS ones are skipped off a Mac | none |
| The web app behind the domain | Cloud Run domain mapping or a load balancer for `racinglines.bet` | configuration |

## Migration, step by step

Each step can be undone by switching the Mac back on; the database moves last.

| Step | What | Undo |
|---|---|---|
| 0 | The data bucket | done (2026-09-28) |
| 1 | Artifact Registry, the image, GitHub Actions with Workload Identity Federation | delete the project's images |
| 2 | Cloud SQL; restore the latest dump; the web app on Cloud Run against it, read-only side by side with the Mac | stop the service |
| 3 | Sweeps and searches as Cloud Run jobs (no live state) | run them locally again |
| 4 | Cutover, outside a race weekend: stop the LaunchAgents, dump the Mac's database into Cloud SQL, start the recorder and signal engine jobs | dump Cloud SQL back to the Mac, reload the LaunchAgents |
| 5 | Live events as jobs, rehearsed on a simulated clock first | the LaunchAgent per event |
| 6 | Nightly Cloud SQL export to `db/` in the bucket, for cloud sessions | – |

## Open questions for the owner

- The database tier: shared core (cheapest, no SLA) or dedicated core (SLA, +$24).
- Recorder per minute (needs `--once`) or always on (+$22, no code change).
- The domain: Cloud Run domain mapping (simplest where available) or a load balancer.
- When: after the round 16–17 live tests, outside a race weekend.
