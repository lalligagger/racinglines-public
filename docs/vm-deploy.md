# VM deploy

How racinglines.bet moves from the owner's Mac to a Compute Engine VM, and how every update reaches it.
It's a smaller first step than the Cloud Run plan in the [Google Cloud proposal](google-cloud.md). The VM
runs exactly what the Mac runs today: Postgres in docker, systemd units in place of the LaunchAgents, and
cloudflared in place of the Mac's tunnel. No code changes. Written 2026-09-28.

## The flow

| Where | What it serves | Runs |
|---|---|---|
| **Your Mac** (staging) | the temp trycloudflare address, while that `cloudflared` process runs | any branch: `racinglines web` relaunched by hand, as today |
| **The VM** (production) | `racinglines.bet` | `main` only, deployed with `scripts/deploy/vm.sh deploy` |

For every change:

1. **On a branch, on the Mac:** `python -m pytest -m "not live"`, `python -m pytest`, then relaunch
   `racinglines web` and run the smoke check locally and through the temp address:
   ```sh
   bash scripts/deploy/smoke.sh http://127.0.0.1:8000
   bash scripts/deploy/smoke.sh https://<temp>.trycloudflare.com
   ```
2. **Merge** the PR into `live-event`, then `live-event` into `main`.
3. **Deploy** `main` to the VM. `vm.sh` pulls, installs, migrates, restarts, and runs the same smoke check on the VM:
   ```sh
   bash scripts/deploy/vm.sh deploy
   bash scripts/deploy/smoke.sh https://racinglines.bet
   ```

The smoke check signs in as the demo accounts (`SMOKE_PASSWORD`, default the public demo password). It
checks `/login`, that a request without credentials or with a wrong password gets 401, the main pages
for maker and taker, and that `/book/quotes` is maker-only. It makes GET requests only.

The temp address stays on the Mac: a trycloudflare address belongs to the `cloudflared` process that
made it and forwards only to that machine. It can't be moved to the VM or pointed at another host, and it
changes if that process restarts. A stable `staging.racinglines.bet` on the Mac's existing tunnel is the
cleaner later version.

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
| `scripts/deploy/vm.sh` | Run on your Mac: `setup`, `restore`, `start [web]`, `deploy [ref]`, `status`, `logs [unit]`, `ssh` (SSH through IAP) |
| `scripts/deploy/smoke.sh <url>` | The smoke check (any machine with curl) |
| `vm.sh demo`, `demo extra`, `demo status` | The multi-sport demo. `demo`: writes `RACINGLINES_SPORT_STATUS=1` and `RACINGLINES_SPORT_PAPER=1` to `/etc/racinglines.env` (replacing any earlier lines for them), restarts the web app, then starts `scripts/vm/demo_setup.sh` as the transient unit `rl-demo` (refused while `rl-demo` is already running). The script refuses to start while a `racinglines-live-*` unit is active, backs up first (`data/backups/db/racinglines-before-demo-setup-<UTC>.sql.gz`, trailer checked), then for NASCAR and MotoGP (a sport with no settings grid under `data/runs/replay-grid/<sport>` is skipped with a `SKIP` line): the steps in `STEPS`, default `kalshi polymarket forecast`: `kalshi` prints the grid's selection and runs `demo-history --grid … --book best --users maker,taker` on Kalshi; `polymarket` the same on Polymarket's tape with the Kalshi grid's selection (`--venue polymarket --grid-venue kalshi`); `forecast` runs `<sport> forecast --save` (MotoGP has no scheduled race stored, so it stores nothing). `demo extra` runs only `polymarket forecast`. `demo status` shows the unit, the `demo-setup.done` / `.failed` markers and the latest log's key lines (`data/runs/logs/demo-setup-<UTC>.log`). Every write logs a `data_changes` row naming the backup; undo with `racinglines <sport> demo-history --reset --users maker,taker --backup FILE` (per venue) and `<sport> forecast --undo RUN_ID`. Touches no trading flag, migration or bucket, and never the F1 demo history ([Paper trading](paper-trading.md#nascar-and-motogp-demo-in-sample-off-by-default)) |
| `vm.sh switch <NAME> on\|off` | An app switch in `/etc/racinglines.env` (`RACINGLINES_*` only, e.g. `RACINGLINES_OG_VENUE`: the OG.com column and `/markets/og`), replacing any earlier line for it, then the web app restarted. Refuses any `*TRADING*` flag |
| `vm.sh record`, `record off`, `record status` | The Kalshi and OG.com recorder: enables `racinglines-record-venues.timer`, a pass of `scripts/vm/record_venues.sh` every 5 minutes. Each pass stores one order-book snapshot per open market for `kalshi:f1 og:f1 kalshi:nascar og:nascar kalshi:motogp` (`markets --exchange <x> --sport <s> books`) and, once an hour per pair, that pair's `sync` first (links and quotes upserted). Additive only, read-only APIs, no trading. The first pass on a box backs the database up (`data/backups/db/racinglines-before-record-venues-<UTC>.sql.gz`) and adds a `data_changes` note naming it. One line per pair per pass in the journal and `data/runs/logs/record-venues.log`; `record status` prints the last ones and the book snapshots stored per venue per 5 minutes. `vm.sh deploy` pauses and resumes it with the other timers |
| `deploy/vm/setup.sh` | One-time VM setup, run by `vm.sh setup`: packages, the `racinglines` user, a read-only deploy key, `/opt/racinglines` on `main`, a Python 3.14 venv (uv), Postgres, `/etc/racinglines.env`, the units |
| `deploy/vm/update.sh [ref]` | On the VM, run by `vm.sh deploy`: checkout, `pip install`, `alembic upgrade head` |
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
deployed and the timers are resumed; the message names the stuck unit. If the update itself fails, the timers stay
paused (so no step runs on a half-updated checkout): fix and deploy again. A running downhill loop
(`racinglines-live-dh@`) gets a warning, not a pause: deploy doesn't restart it, so it keeps the code it loaded. The
recorder's restart costs at most one order-book snapshot; prices and trades are unaffected, because they are fetched
from the exchanges' own history. Deploy restarts only the services that are already running, so a deploy before cutover never starts a second recorder.

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
Only `vm.sh start` (without `web`) enables the recorder and signals, and only `vm.sh live` (or the lines above)
enables an event's timer; `vm.sh deploy` never starts a unit that wasn't already running. A VM set up with
`vm.sh start web` before cutover therefore has no recorder and no timers until `vm.sh start` runs.
The recorder is Polymarket's F1 books only; Kalshi and OG.com are recorded by `vm.sh record` (a pass every 5 minutes, above).
Run an event on one machine only, the one whose database racinglines.bet reads.
`vm.sh deploy` pauses the event's timer and resumes it with a catch-up step (see [What's in the repo](#whats-in-the-repo)), so
deploys don't wait for the event to settle. The web app restarts for a few seconds, so between sessions is still the
kindest time.

## Later

- `staging.racinglines.bet` on the Mac's tunnel, replacing the temp address.
- A nightly `bucket.sh push` from the VM, so cloud sessions stay current without the Mac. It needs
  `bucket.sh push` to use the docker-compose `pg_dump` on Linux.
- `racinglines live agent --systemd`, writing the units above.
- Deploys from GitHub Actions calling `vm.sh`.
