# VM deploy

How racinglines.bet moves from the owner's Mac to a Compute Engine VM, and how every update reaches it.
It's a smaller first step than the Cloud Run plan in the [Google Cloud proposal](google-cloud.md). The VM
runs exactly what the Mac runs today: Postgres in docker, systemd units in place of the LaunchAgents, and
cloudflared in place of the Mac's tunnel. No code changes. Written 2026-09-28.

## The flow

Since 2026-10-01 the live repo is the public `lalligagger/racinglines-public` (base `main`) and **merging to
`main` deploys to the VM by itself**, through the GitHub Actions workflow `main-merge-gate`
(`.github/workflows/predeploy.yml`):

| Job | Runs on | What it does |
|---|---|---|
| `detect-docs-only` | every PR to `main` and every push to `main` | Lists the changed files (the PR's diff, or `HEAD^..HEAD` on a push). If every one is under `docs/` or ends in `.md` (README, CLAUDE.md, mkdocs.yml too), the change is docs-only and the two jobs below are skipped: **a docs-only merge deploys nothing** |
| `predeploy-staging` | PRs and pushes that are not docs-only | `scripts/deploy/predeploy.sh --staging <sha>`: the smoke check (`scripts/deploy/smoke.sh`, valid sign-ins only) against `https://staging.racinglines.bet`. A failure comments on the PR. It checks whatever staging serves (since PR 11 the staging instance, [Staging](#staging)); it does not deploy or run the PR's code |
| `deploy-production` | pushes to `main` only, after `predeploy-staging` passed | `scripts/deploy/predeploy.sh --prod <sha>`: `vm.sh deploy <sha>` (below), then the smoke check against `https://racinglines.bet`. Uses the `production` environment's secrets (`GCP_SERVICE_ACCOUNT_KEY`, `GCP_PROJECT_ID`, `VM_NAME`, `VM_ZONE`); without them the job prints a skip line and deploys nothing |

**CI runs no pytest, no `racinglines check` and no `mkdocs build`.** Those stay local (below) until STG-2's test job
lands ([todo](todo.md#staging-and-ci-deploys)). A PR that is green on GitHub has only passed the smoke check.

For every change:

1. **On a branch** (a feature-track branch: [CLAUDE.md](https://github.com/lalligagger/racinglines-public/blob/main/CLAUDE.md#branches-feature-tracks)):
   `racinglines check`, `python -m pytest -m "not live"`, `mkdocs build --strict`. Without `tests/fixtures/` (not in
   the public repo, see [Code from GitHub, data on the VM](#code-from-github-data-on-the-vm)) every golden test
   skips, so run them where the fixtures are (the owner's Mac) before merging anything that touches pricing.
2. **Open the PR** against `main`; `predeploy-staging` runs on it.
3. **Merge** (owner only, squash, `gh pr merge N --squash --delete-branch`). The merge is the deploy: CI runs
   `vm.sh deploy` on the merged commit, which pauses the live timers, checks out, installs, migrates, seeds,
   restarts and resumes the timers, then smoke-checks the site. Watch the run in the repo's Actions tab.
   **Merging a PR with an Alembic migration runs it on the VM** (`update.sh`, no extra backup step): take
   `vm.sh backup <purpose>` first and merge only with the owner's sign-off for that migration.
4. **By hand** (the same path, from the Mac) when CI can't: `bash scripts/deploy/predeploy.sh --prod main` or
   `bash scripts/deploy/vm.sh deploy <ref>`. A bad deploy is undone by deploying the previous commit.

Keep merges of code away from a live race window unless the owner says otherwise: the deploy pauses and resumes
the live timers (below), but the web app restarts for a few seconds.

The smoke check signs in as the demo accounts (`SMOKE_PASSWORD`, default the public demo password). It
checks `/login`, that a request without credentials gets 401, the main pages for maker and taker, and that
`/book/quotes` is maker-only. It makes GET requests only and never sends a wrong password (that would warm the
app's 15-minute failed-login throttle).

`staging.racinglines.bet` is the required public staging route. If the hostname is absent or misconfigured,
fix the tunnel / Cloudflare public hostname before a prod deploy. The temp trycloudflare URL is for
local ad hoc testing only, not the release path.

## What is Google, what is Cloudflare, what is neither

If the VM ever moves to another provider, only the first group changes. Written so the setup below can
be repeated without reading the whole page.

| Group | Steps | What it is |
|---|---|---|
| **Google Cloud** (`gcloud`) | 1–4, 6 (`bucket.sh`), `vm.sh public`, `vm.sh ssh`, `vm.sh deploy`'s transport | The project, the bucket the VM restores from, the service account, the VM itself, SSH through IAP, the firewall. On another provider: any Ubuntu 24.04 box with SSH, an object store for backups, and `remote()` in `vm.sh` rewritten for that provider's SSH. |
| **Cloudflare** | 7, 8, cutover step 4 | The `racinglines-vm` tunnel (outbound only: the VM opens no inbound port), one public hostname per service (`racinglines.bet` → `localhost:8000` at cutover, `mcp.racinglines.bet` → `localhost:8100`), the DNS records the dashboard creates for them. Independent of where the VM runs: the same `cloudflared service install <TOKEN>` on any machine attaches it to the same tunnel. |
| **Neither** | 5, `deploy/vm/*`, `update.sh`, the units, `/etc/racinglines.env`, the MCP token | Everything `vm.sh setup` puts on the box: the `racinglines` user, `/opt/racinglines`, the venv, Postgres in docker, the systemd units (web, recorder, signals, live-event templates, `racinglines-mcp`), and the app's own auth (web passwords, `racinglines mcp token`). |

## What's in the repo

| File | What it is |
|---|---|
| `scripts/deploy/vm.sh` | Run on your Mac (and by CI for `deploy`): `setup`, `restore`, `start [web]`, `deploy [ref]`, `backup <purpose>` (a database dump on the VM to `data/backups/db/racinglines-before-<purpose>-<UTC>.sql.gz`), `repoint` (one time: the checkout fetches from the public repo; `git remote set-url` and a fetch, no file touched), `live <event> [off]`, `record`, `switch`, `demo`, `public`, `status`, `logs [unit]`, `ssh` (SSH through IAP) |
| `scripts/deploy/predeploy.sh --staging\|--prod\|--all [ref]` | The gate CI runs: `--staging` smoke-checks staging, `--prod` runs `vm.sh deploy <ref>` then smoke-checks racinglines.bet |
| `deploy/vm/staging/`, `deploy/vm/systemd/racinglines-staging-web.service`, `deploy/ci/staging.yml` | Staging on the VM and its workflow ([Staging](#staging)) |
| `.github/workflows/predeploy.yml` | `main-merge-gate`, the CI workflow ([The flow](#the-flow)). Cloud sessions can't push changes to it (the token lacks the workflow scope): ship a patch for the owner |
| `scripts/deploy/smoke.sh <url>` | The smoke check (any machine with curl) |
| `vm.sh demo`, `demo extra`, `demo status` | The multi-sport demo. `demo`: writes `RACINGLINES_SPORT_STATUS=1` and `RACINGLINES_SPORT_PAPER=1` to `/etc/racinglines.env` (replacing any earlier lines for them), restarts the web app, then starts `scripts/vm/demo_setup.sh` as the transient unit `rl-demo` (refused while `rl-demo` is already running). The script refuses to start while a `racinglines-live-*` unit is active, backs up first (`data/backups/db/racinglines-before-demo-setup-<UTC>.sql.gz`, trailer checked), then for NASCAR and MotoGP (a sport with no settings grid under `data/runs/replay-grid/<sport>` is skipped with a `SKIP` line): the steps in `STEPS`, default `kalshi polymarket forecast`: `kalshi` prints the grid's selection and runs `demo-history --grid … --book best --users maker,taker` on Kalshi; `polymarket` the same on Polymarket's tape with the Kalshi grid's selection (`--venue polymarket --grid-venue kalshi`); `forecast` runs `<sport> forecast --save` (MotoGP has no scheduled race stored, so it stores nothing). `demo extra` runs only `polymarket forecast`. `demo status` shows the unit, the `demo-setup.done` / `.failed` markers and the latest log's key lines (`data/runs/logs/demo-setup-<UTC>.log`). Every write logs a `data_changes` row naming the backup; undo with `racinglines <sport> demo-history --reset --users maker,taker --backup FILE` (per venue) and `<sport> forecast --undo RUN_ID`. Touches no trading flag, migration or bucket, and never the F1 demo history ([Paper trading](paper-trading.md#nascar-and-motogp-demo-in-sample-off-by-default)) |
| `vm.sh switch <NAME> on\|off` | An app switch in `/etc/racinglines.env` (`RACINGLINES_*` only, e.g. `RACINGLINES_OG_VENUE`: the OG.com column and `/markets/og`), replacing any earlier line for it, then the web app restarted. Refuses any `*TRADING*` flag |
| `vm.sh record`, `record off`, `record status` | The Kalshi and OG.com recorder: enables `racinglines-record-venues.timer`, a pass of `scripts/vm/record_venues.sh` every 5 minutes. Each pass stores one order-book snapshot per open market for `kalshi:f1 og:f1 kalshi:nascar og:nascar kalshi:motogp` (`markets --exchange <x> --sport <s> books`) and, once an hour per pair, that pair's `sync` first (links and quotes upserted). Additive only, read-only APIs, no trading. The first pass on a box backs the database up (`data/backups/db/racinglines-before-record-venues-<UTC>.sql.gz`) and adds a `data_changes` note naming it. One line per pair per pass in the journal and `data/runs/logs/record-venues.log`; `record status` prints the last ones and the book snapshots stored per venue per 5 minutes. `vm.sh deploy` pauses and resumes it with the other timers |
| `deploy/vm/setup.sh` | One-time VM setup, run by `vm.sh setup`: packages, the `racinglines` user, a read-only deploy key, `/opt/racinglines` on `main`, a Python 3.14 venv (uv), Postgres, `/etc/racinglines.env`, the units |
| `deploy/vm/update.sh [ref]` | On the VM, run by `vm.sh deploy`: checkout, `pip install`, `alembic upgrade head`, `racinglines db seed` (reference rows for every sport schema, idempotent upserts). The only database writes a deploy makes |
| `deploy/vm/build_docs.sh` | Piped over ssh by `vm.sh deploy` (after the timers resume) and `vm.sh docs`: builds `site/`, which the app serves at `/docs`, from the checkout's `docs/` (installs `requirements-docs.txt` into the venv the first time). Fail-soft: a failure logs a `docs:` line and the old site stays. Touches only `site/` and the venv |
| `deploy/vm/untrack.sh <ref>` | Piped over ssh by `vm.sh deploy` before `update.sh`: files the VM's current commit tracks and `<ref>` doesn't are backed up to `data/backups/files/racinglines-before-untrack-<UTC>.tar.gz` and untracked with a local commit, so the checkout leaves them on disk. It moved the VM from the private history to the public one without deleting `data/`, the test fixtures or the pitch images |
| `deploy/vm/systemd/` | `racinglines-web`, `racinglines-recorder` (the Mac's recorder LaunchAgent), `racinglines-signals` + timer (every 5 min), `racinglines-record-venues` + timer (Kalshi and OG.com books every 5 min, enabled by `vm.sh record`), and per-event templates `racinglines-live-f1@<event>` + timer and `racinglines-live-dh@<event>` |
| `deploy/vm/compose.override.yml` | Postgres on the VM's loopback only |
| `deploy/vm/racinglines.env.example` | The VM's settings file (`/etc/racinglines.env`: the admin password, `APP_SECRET`, alerts) |
| `scripts/cloud/bucket.sh restore --yes` | Loads the bucket's database dump into the docker-compose Postgres, after backing up the current one to `data/backups/db/` |

`vm.sh deploy` never refuses for a live event, and has no `--force`. It pauses the VM's active timers (each
event's `racinglines-live-f1@<event>.timer` and `racinglines-signals.timer`) and waits up to 5 minutes for a step
already running. Then it deploys, runs each live event's catch-up step, and starts the timers again. Every step is
idempotent and catches up: an F1 live step does every update that fell due during the pause, its crowd batch covers
the whole window since the last update (`pipelines/live_f1.py` `due`, `_crowd`), and signals inserts with `ON
CONFLICT DO NOTHING`. The paused list is written to `/var/lib/racinglines/deploy-paused` on the VM before anything
stops, so a deploy that dies half-way leaves a record: `vm.sh status` shows it, and the next `vm.sh deploy` resumes
those timers too. If a step is still running after 5 minutes, or the connection drops while waiting, nothing is
deployed and the timers are resumed; the message names the stuck unit. If the update fails before the checkout
moves (a fetch, an unknown ref), nothing changed and the timers are resumed. If it fails after, the timers stay
paused (so no step runs on a half-updated checkout): fix and deploy again. Deploy refuses (nothing paused) until the
checkout fetches from the public repo: `vm.sh repoint` sets that once (`git remote set-url` and a fetch, no file
touched). Before each checkout, `deploy/vm/untrack.sh` backs up to `data/backups/files/` and untracks whatever the
current commit tracks and the new one doesn't, so moving from the private history keeps `data/` on disk. A running downhill loop
(`racinglines-live-dh@`) gets a warning, not a pause: deploy doesn't restart it, so it keeps the code it loaded. The
recorder's restart costs at most one order-book snapshot; prices and trades are unaffected, because they are fetched
from the exchanges' own history. Deploy restarts only the services that are already running, so a deploy before cutover never starts a second recorder.

## Code from GitHub, data on the VM

Owner rule (2026-10-01): **a deploy carries code only.** It never restores, overwrites or deletes anything under
`data/`, the pitch images or the database's rows. Data and the database change only through ssh and the scripts
below, or through the site's admin views. (A deploy's own database writes are `alembic upgrade head` and
`racinglines db seed`, both in `update.sh`.)

**Where each kind of file lives now** (checked 2026-10-01 against the public repo, the scripts and the data bucket):

| What | In the public repo? | On the VM | Off the VM (copy) | How it changes on the VM |
|---|---|---|---|---|
| Code, schemas (`sports/`, `exchanges/`), live specs (`live/`), sweeps, units, `pitch.html` | yes | the checkout | GitHub | a merge to `main` (CI deploy) |
| Database (results, links, model runs, positions, the hot market rows) | no | docker Postgres | **none from the VM**: no script or timer pushes a VM dump anywhere; the newest bucket dump a cloud session can read is the Mac's from 2026-09-28 | the timers and scripts (`vm.sh record`, `demo`, `overnight.sh`, live steps), admin views |
| Market history older than the hot window (`data/archive/markets/`, Parquet) | no | moved there from Postgres by the recorder's archive pass (`markets record`, `MS.archive(..., policy=True)`) | none from the VM; the old bucket has Polymarket only, to 2026-09-28 | the recorder, hourly. **The database dumps no longer hold these rows** (that's why they shrank from 118 MB to 56 MB), so a dump alone is not a full backup |
| Database dumps (`data/backups/db/`) and untrack tars (`data/backups/files/`) | no | yes | **none** | `vm.sh backup`, each writing script's first step |
| Raw inputs (`data/raw/f1` FastF1 cache, `nascar`, `motogp`, `mtb_dh`) | no | yes | old bucket: `mtb_dh` only | the live steps and ingest commands fetch them |
| Run folders (`data/runs/live`, `replay-grid`, `search`, `logs`) | no | yes | old bucket: `live`, `runs/f1` to 2026-09-28 | the units and scripts that write them |
| Built docs (`site/`, served at `/docs`) | no | built by every `vm.sh deploy` and by `vm.sh docs` (`deploy/vm/build_docs.sh`) | no (rebuilt from the checkout) | a code merge's deploy; a docs-only merge deploys nothing, so run `vm.sh docs` after one |
| Pitch images (`racinglines/web/static/pitch/*.jpg`, used by `/pitch`) | no (`*.jpg` is ignored) | yes, untracked (kept by `untrack.sh`) | the owner's Mac | by hand (scp) |
| Test fixtures (`tests/fixtures/`) | no; goldens (`tests/golden/`) yes | yes, untracked | the owner's Mac | `scripts/fetch_test_fixtures.py --refresh` (needs the exchanges and FastF1) |

**What follows from it:**

- **A rebuilt VM doesn't come back complete.** `vm.sh setup` + `vm.sh restore` loads whatever the bucket last
  received, and nothing has pushed there from the VM (the VM's bucket `racinglines-data-384052502248` was loaded from
  the Mac before cutover; the cloud can't list it to confirm). That means no Kalshi or OG.com books, no NASCAR or MotoGP data, no demo rows, no
  `/pitch` images, no `site/`. Until the VM pushes its dumps and `data/archive/markets` to the bucket, its disk
  is the only copy (owner decision: a nightly push, [todo](todo.md#staging-and-ci-deploys) STG-5).
- **Cloud sessions read stale data.** Their HMAC key reaches the old bucket (`racinglines-data-650570086451`, last
  push 2026-09-28) only, and `data/` is no longer in git, so the [cloud sweep](cloud-sweep.md) path of committing
  data and results to git doesn't work on the public repo. Results go back through `bucket.py push`.
- **Without `tests/fixtures/` every golden test skips** (`conftest.py` skips, not fails): on a fresh public checkout
  `pytest -m "not live"` reports about 50 fixture skips and still looks green.
- **Re-adding an untracked file to git can stop a deploy half-way.** If a commit starts tracking a path the VM keeps
  as an untracked file (the pitch images, `tests/fixtures/`), `git checkout` refuses ("untracked working tree files
  would be overwritten") after `untrack.sh`, and the timers stay paused. Before merging such a commit, move the VM's
  copies aside over ssh; then deploy.
- **New data a PR needs doesn't arrive with the merge.** A new sport's tape, a FastF1 backfill, a replay grid or a
  forecast is a VM step after the deploy (a script under `scripts/vm/` run as a transient unit, backup first), named
  in the PR and run by the owner. Schemas and seeds do arrive (`db seed` runs on every deploy).

## One-time setup (owner-only, your accounts)

Settings used below: project **`racinglines`** (if that ID is taken, pick another and set
`RL_GCP_PROJECT`), region `us-west1`, VM `racinglines-vm` in `us-west1-b`, **e2-small** (2 vCPU shared,
2 GB), Ubuntu 24.04, 30 GB balanced disk. Check the price in the
[calculator](https://cloud.google.com/products/calculator). It should be roughly $15–20 a month with the
disk and the external IP the VM needs for outbound traffic.

**1. Project, billing, APIs**
```sh
gcloud projects create racinglines --name=racinglines
gcloud billing accounts list
gcloud billing projects link racinglines --billing-account=<ACCOUNT_ID>
gcloud config set project racinglines
gcloud services enable compute.googleapis.com iap.googleapis.com storage.googleapis.com
```

**2. The new bucket** (the old bucket stays as it is for cloud sessions)
```sh
NUM=$(gcloud projects describe racinglines --format='value(projectNumber)')
export RACINGLINES_GCS_BUCKET=racinglines-data-$NUM
gcloud storage buckets create gs://$RACINGLINES_GCS_BUCKET --location=us-west1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$RACINGLINES_GCS_BUCKET --versioning
```

**3. The VM's service account** (it reads and writes the bucket; no keys)
```sh
gcloud iam service-accounts create racinglines-vm --display-name="racinglines VM"
gcloud storage buckets add-iam-policy-binding gs://$RACINGLINES_GCS_BUCKET \
  --member=serviceAccount:racinglines-vm@racinglines.iam.gserviceaccount.com --role=roles/storage.objectUser
gcloud projects add-iam-policy-binding racinglines \
  --member=serviceAccount:racinglines-vm@racinglines.iam.gserviceaccount.com --role=roles/logging.logWriter
```

**4. The VM, with SSH only through IAP**
```sh
gcloud compute instances create racinglines-vm --zone=us-west1-b --machine-type=e2-small \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-balanced --shielded-secure-boot \
  --service-account=racinglines-vm@racinglines.iam.gserviceaccount.com --scopes=cloud-platform
gcloud compute firewall-rules create allow-iap-ssh --network=default --allow=tcp:22 \
  --source-ranges=35.235.240.0/20
gcloud compute firewall-rules delete default-allow-ssh default-allow-rdp --quiet
```

**5. Set up the VM**
```sh
bash scripts/deploy/vm.sh setup     # prints a deploy key the first time
```
To try an unmerged branch first: `vm.sh setup <branch>`, then `vm.sh deploy <branch>`. The next
plain `vm.sh deploy` moves the VM back to `main`.
Add the key on GitHub (repo Settings > Deploy keys > Add, with write access off), then run
`vm.sh setup` again. Set the admin password with `bash scripts/deploy/vm.sh ssh`, then
`sudo nano /etc/racinglines.env`. `APP_SECRET` is already filled in.

**6. Copy the data and test the VM before it serves anything**
```sh
bash scripts/cloud/bucket.sh push       # on the Mac, with RACINGLINES_GCS_BUCKET set to the new bucket
bash scripts/deploy/vm.sh restore
bash scripts/deploy/vm.sh start web     # the web app only: the Mac keeps recording
bash scripts/deploy/vm.sh deploy        # runs the smoke check on the VM
gcloud compute ssh racinglines-vm --zone=us-west1-b --tunnel-through-iap -- -L 8001:127.0.0.1:8000 -N
                                        # then browse http://localhost:8001
```

**Public test port (until the handover).** To try the VM from any browser before racinglines.bet moves:
```sh
bash scripts/deploy/vm.sh public on      # opens tcp:8000 to everyone; prints http://<VM IP>:8000
bash scripts/deploy/vm.sh public off     # at the handover: closes the port, the app back on loopback only
```
It's plain HTTP, so passwords cross the internet unencrypted. Sign in with the demo accounts only, never
as admin. The sign-in throttle still applies.

**7. The VM's tunnel** (Cloudflare; done 2026-09-28). In the Cloudflare dashboard, open Zero Trust >
Networks > Tunnels > Create a tunnel, choose Cloudflared, name it `racinglines-vm`, and on the install
page pick Debian 64-bit, "Install and run a connector". Copy only the token (the long `eyJ...` string after
`cloudflared service install`; it is the same token whichever install option is shown). On the VM
(`vm.sh ssh`):
```sh
sudo cloudflared service install <TOKEN>          # cloudflared itself was installed by vm.sh setup
sudo systemctl status cloudflared --no-pager      # active; the dashboard shows the connector as connected
```
If it says a service already exists, `sudo cloudflared service uninstall` first. Don't give it
`racinglines.bet` yet: that hostname moves at the cutover below.

**Branch pre-deploy: staging first, then final production deploy.** The normal flow is a single gate:
```sh
bash scripts/deploy/predeploy.sh --staging main
bash scripts/deploy/predeploy.sh --prod main
```
The staging mode checks `https://staging.racinglines.bet` only. If the route is down or misconfigured, fix the
Cloudflare tunnel hostname before the prod deploy. The prod mode runs the VM deploy and then
`bash scripts/deploy/smoke.sh https://racinglines.bet`.

If you want the whole path in one command:
```sh
bash scripts/deploy/predeploy.sh --all main
```
This keeps the release path explicit: branch checks on staging, then the same final deploy + smoke flow on
`racinglines.bet`.

**Temporary local tunnel: ad hoc only.** The Mac should not keep a long-lived tunnel running. A short-lived
local check remains acceptable for debugging a branch locally:
```sh
bash scripts/deploy/staging.sh smoke 8010
```
This starts `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8010`, waits for the temporary
trycloudflare URL, runs `scripts/deploy/smoke.sh`, and exits cleanly. It is not the shipping path; the
shipping path is `staging.racinglines.bet` behind the tunnel.

**8. The MCP server's hostname** (Cloudflare + the VM; done 2026-09-28). [MCP server](mcp.md#giving-access-as-an-admin) has the admin and user guides and the troubleshooting table; this is the short form.
Issue the admin token and start the unit, on the VM:
```sh
sudo -u racinglines bash -c 'set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mcp token admin'
sudo systemctl enable --now racinglines-mcp
```
In the dashboard, on the tunnel `racinglines-vm` > Public hostnames (also called "published application
routes") > Add: subdomain `mcp`, domain `racinglines.bet`, path empty, type `HTTP`, URL `localhost:8100`.
Save creates a proxied CNAME `mcp` in the zone's DNS (check DNS > Records if it does not resolve after a
couple of minutes). No Access policy on it: clients send only the bearer token. Each hostname belongs to
one tunnel, so this touches nothing on the Mac's tunnel. From the Mac:
```sh
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp.racinglines.bet/mcp    # 401: tunnel and server up
curl -s -o /dev/null -w "%{http_code}\n" https://racinglines.bet/                    # 401: the app, unchanged
```

## Schedule: cutover before round 16 (owner's choice, 2026-09-28)

Round 16's book runs on the VM, so the VM has to be production before the book opens (Thu 1 Oct, 20:30 PDT).

| When | Step |
|---|---|
| Mon 28 – Tue 29 Sep | One-time setup 1–7, `vm.sh public on`, test in a browser |
| Tue 29 – Wed 30 Sep | Rehearse round 15 on the VM, on a simulated clock and without writing positions (below) |
| Wed 30 Sep | Cutover (below), `vm.sh public off` |
| Thu 1 Oct, before 20:30 PDT | `bash scripts/deploy/vm.sh live 2026-16` (enables `racinglines-live-f1@2026-16.timer` on the VM). Don't install the round's LaunchAgent on the Mac |

**Rehearsal on the VM** (as the `racinglines` user in `/opt/racinglines`, with `/etc/racinglines.env` loaded):
```sh
.venv/bin/racinglines live run live/f1/2026-15.toml --simulate --no-fetch --no-sync --no-alert
```

## Cutover

Two recorders would split the order-book history across two databases, so the Mac stops before the
final copy.

1. On the Mac, stop the recorder and signals:
   `launchctl bootout gui/$(id -u)/bet.racinglines.recorder` and `launchctl bootout gui/$(id -u)/bet.racinglines.signals`
   (`vm.sh start` also does this when run on the Mac).
2. `bash scripts/cloud/bucket.sh push`, then `bash scripts/deploy/vm.sh restore`, then `bash scripts/deploy/vm.sh start`.
3. Log it: on the VM, `racinglines db changes --add "production moved to the VM; restored from the Mac's dump"`,
   plus a line in [Data changes](data-changes.md).
4. **Point racinglines.bet at the VM.** How the Mac serves it today isn't in the repo. Check with
   `cloudflared tunnel list` and `ls ~/.cloudflared` on the Mac.
    - **A tunnel managed in the dashboard:** remove the `racinglines.bet` public hostname from the
      Mac's tunnel, then add it to `racinglines-vm` with the service `http://localhost:8000`.
    - **A tunnel managed locally** (`~/.cloudflared/config.yml`): add the hostname to `racinglines-vm` as
      above. The dashboard offers to replace the existing DNS record; accept. Then remove the
      hostname from the Mac's `config.yml`.
    - **A plain DNS record** (an A record to your home IP): delete it, then add the hostname to
      `racinglines-vm` as above.
5. `bash scripts/deploy/smoke.sh https://racinglines.bet`, then sign in by hand.

**Rollback.** Put the hostname back on the Mac's tunnel and reload the two LaunchAgents
(`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/bet.racinglines.recorder.plist`, and the
same for signals). Book snapshots the VM recorded in between would need copying back. A bad code
deploy is simpler to undo: `vm.sh deploy <previous commit>`.

## Live events on the VM

Each event's spec runs as a unit, in place of `racinglines live agent --install`, which is macOS only.
The run folder's lock works the same on the VM's disk.
From the Mac, `bash scripts/deploy/vm.sh live 2026-16` enables an F1 event's timer and `vm.sh live 2026-16 off`
disables it. On the VM itself:
```sh
sudo systemctl enable --now racinglines-live-f1@2026-16.timer     # F1: one step every 5 minutes
sudo systemctl enable --now racinglines-live-dh@<event>           # downhill: the poll loop
sudo systemctl disable --now racinglines-live-f1@2026-16.timer    # when the event is settled
```
**F1 sessions come from the Mac (since 3 Oct 2026).** F1's timing archive answers 403 to the VM's cloud address, so
FastF1 can't fetch there (the live step logs "waiting for the session's data" all weekend). During an F1 weekend, run
`bash scripts/deploy/f1_push.sh 2026-16` on the Mac: a look every 5 minutes fetches each started session, copies new
session files to the VM's `data/raw/f1/fastf1/<year>/` and starts the live step, until the race is in. A downhill
final's ChronoRace feed works from the VM.

Only `vm.sh start` (without `web`) enables the recorder and signals, and only `vm.sh live` (or the lines above)
enables an event's timer; `vm.sh deploy` never starts a unit that wasn't already running. A VM set up with
`vm.sh start web` before cutover therefore has no recorder and no timers until `vm.sh start` runs.
The recorder is Polymarket's F1 books only; Kalshi and OG.com are recorded by `vm.sh record` (a pass every 5 minutes, above).
Run an event on one machine only, the one whose database racinglines.bet reads.
`vm.sh deploy` pauses the event's timer and resumes it with a catch-up step (see [What's in the repo](#whats-in-the-repo)), so
deploys don't wait for the event to settle. The web app restarts for a few seconds, so between sessions is still the
kindest time.

## Staging

Since 2026-10-01 (PR 11) `staging.racinglines.bet` is **a second copy of the app on the same VM**, and **merging to
the `staging` branch deploys staging and nothing else**. `main` keeps deploying production ([The flow](#the-flow)).

| | Production | Staging |
|---|---|---|
| Branch that deploys it | `main` (`main-merge-gate`) | `staging` (`staging-deploy`, `.github/workflows/staging.yml`) |
| Checkout on the VM | `/opt/racinglines` | `/opt/racinglines-staging` |
| Web app | `racinglines-web`, 127.0.0.1:8000 | `racinglines-staging-web`, 127.0.0.1:8010 |
| Database | `racinglines` | `racinglines_staging`, in the same Postgres container, copied from production by `staging setup` / `staging reset` (`pg_dump \| psql`: production is only read) |
| Settings | `/etc/racinglines.env` | `/etc/racinglines-staging.env`: production's switches and admin password, its own `DATABASE_URL`, data folder (`/opt/racinglines-staging/data`, empty: no archive Parquet, no pitch images), `APP_SECRET`, `RACINGLINES_URL`, `RACINGLINES_ENV=staging`, `WEB_PORT=8010`; **no trading flags, no ntfy topic, no alert webhook** |
| Timers and other units | recorder, signals, live events, record-venues, MCP | only its own live events, by hand (`vm.sh staging live <event>`: `racinglines-staging-live-f1@` / `racinglines-staging-live-dh@`, its data folder and database); no recorder or signals (two recorders would split the book history) |
| Live timing button (F1, `/live`) | off (`RACINGLINES_F1_STREAM` unset) | on by default: an opt-in websocket per viewer polling FastF1, with a debug log (`racinglines/web/f1_live.py`) |
| Tells you which one you're on | nothing | the `X-Racinglines-Env: staging` response header and a STAGING pill in the top bar (`RACINGLINES_ENV`) |

**What a merge to `staging` does** (`deploy-staging` job): `vm.sh staging deploy <sha>`, which pipes
`deploy/vm/staging/update.sh` over ssh (fetch, checkout, pip, `alembic upgrade head` and `db seed` **against
`racinglines_staging` only**: it refuses any other `DATABASE_URL`), restarts `racinglines-staging-web`, and runs the smoke
check on the VM and then against `https://staging.racinglines.bet` with `SMOKE_EXPECT_ENV=staging`, which fails unless
the answer carries the staging header. It never calls `vm.sh deploy`, never reads the pause file, never stops a timer,
never runs `untrack.sh` or `docker compose up`, and never opens `/etc/racinglines.env` or the `racinglines` database
for writing (`tests/test_staging_deploy.py` pins this). A staging deploy is fine during a live window; only production
deploys stay out of it. `tests.yml` runs the suite on PRs into `staging` and pushes to it, as for `main`.

The `staging` concurrency group ensures that `vm.sh staging deploy` and a push to the `staging` branch share one queue
(GitHub Actions job serialization with `concurrency: group: staging`). Do not run both at once; push the branch and wait
for its workflow run to finish before running `vm.sh staging deploy` by hand from the Mac.

**Flow for a change:** branch off `main` → PR into `staging` (or push the branch's commits to `staging`) → the merge
deploys staging → look at `https://staging.racinglines.bet` → PR of the same branch into `main` → the merge deploys
production. Keep `staging` close to `main`: after a batch, reset it to `main` (`git push origin main:staging`; a
force push is fine there, `staging` is a deploy pointer, not history).

**`vm.sh staging` subcommands** (from the Mac, or by CI for `deploy`):

| Command | What it does |
|---|---|
| `staging setup [ref]` | One time, as root (piped `deploy/vm/staging/setup.sh`): the checkout at `ref` (default the `staging` branch, else `main`), its venv, `racinglines_staging` copied from production, `/etc/racinglines-staging.env`, the unit installed and started. Idempotent: re-running keeps the database and the env file |
| `staging deploy [ref]` | What CI runs on a merge to `staging` (above) |
| `staging status` | The staging checkout's commit, the unit, and `GET /login` with its env header |
| `staging logs` | `journalctl -u racinglines-staging-web` |
| `staging reset` | Drop `racinglines_staging` and copy production's rows and live run folders (`data/runs/live`) again (production only read) |
| `staging live <event> [off]` | Staging's own run of a live event (`live/f1/<event>.toml`: a step every 5 minutes; `live/mtb_dh/<event>.toml`: the poll loop), like `vm.sh live` for production; it carries on from the run folder `staging reset` copied |
| `staging off` | Stop and disable the unit; the checkout, database and env file stay |

**Owner's one-time steps** (in this order; nothing here touches production):

1. Cloudflare Zero Trust > Networks > Tunnels > `racinglines-vm` > Public hostnames: edit `staging.racinglines.bet`
   (today it points at the production app, `localhost:8000`) to `http://localhost:8010`. Until then
   `https://staging.racinglines.bet` serves production, and a staging deploy's last smoke step fails on the env
   header (the VM-side smoke on port 8010 passes: the deploy itself is fine).
2. Copy the workflow files into place on the PR branch (cloud sessions can't): `deploy/ci/staging.yml` to
   `.github/workflows/staging.yml` and `deploy/ci/tests.yml` over `.github/workflows/tests.yml`.
3. `bash scripts/deploy/vm.sh staging setup <branch>` from the Mac, with the PR branch while the PR is open.
4. Create the `staging` branch and merge into it; watch the `staging-deploy` run; `bash scripts/deploy/vm.sh status`
   shows production's commit and timers unchanged.

Not done yet: Cloudflare Access in front of staging (today it has the app's own login, as production), a docs build
for staging's `/docs` (`build_docs.sh` is production-only), the Mac's trycloudflare script (`scripts/deploy/staging.sh`,
ad hoc only).

## Later

- ~~`staging.racinglines.bet` on the Mac's tunnel, replacing the temp address.~~ Done 2026-10-01 on the VM ([Staging](#staging)).
- A nightly push from the VM to its bucket (the latest dump and `data/archive/markets`), so the VM's disk is not
  the only copy and cloud sessions stay current. `bucket.sh push` needs to use the docker-compose `pg_dump` on Linux
  (its `PG_BIN` default is the Mac's conda path), and the VM's service account needs write access to the bucket.
- `racinglines live agent --systemd`, writing the units above.
- ~~Deploys from GitHub Actions calling `vm.sh`.~~ Done 2026-10-01 ([The flow](#the-flow)).
