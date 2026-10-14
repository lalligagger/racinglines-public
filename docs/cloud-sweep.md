# Cloud sweeps

> Long, unattended settings searches in a Claude Code cloud session: a fresh VM, the database from the bucket, a queue of season sweeps run in parallel while the agent steers it.

A cloud session clones this repo, builds the database from the data bucket, and works through a queue of season
sweeps in parallel while the agent steers the queue. Results come back on the session's branch and through the
bucket. It has no Kalshi, Polymarket or OG.com network access: everything it prices is read from the archive.

!!! warning "Since 2026-10-01 the data is not in the repo"
    The live repo is the public `racinglines-public`, which tracks no `data/` (`.gitignore`), so a cloud session no
    longer finds the snapshot, the raw F1 files or the market archive in its clone, and `git add` of
    `data/runs/search` adds nothing. The data comes from the bucket (`scripts/cloud/start.sh` and `bucket.py pull`,
    with the environment's HMAC key), and results go back with `bucket.py push results/<session> data/runs/search/<name>`
    plus the leaderboard and `REPORT.md` copied into the PR or the project files. The bucket that key reaches was last
    pushed 2026-09-28, before the VM took over: refresh it before a sweep that needs current data
    ([VM deploy: Code from GitHub, data on the VM](vm-deploy.md#code-from-github-data-on-the-vm)).

| | |
|---|---|
| Machine | Anthropic-hosted VM: about 4 vCPUs, 16 GB RAM, 30 GB disk (no larger size) |
| Parallel sweeps | 3 (one core each, one left for PostgreSQL) |
| Speed | A 24-weekend sweep takes a few minutes on one core (GBM several times longer) |
| Cost | No compute charge; the session uses the account's Claude usage limits |
| Data | From the bucket: the database snapshot `data/archive/db/`, `data/raw/f1/`, the market archive `data/archive/markets/<exchange>/{prices,trades,links}/` |
| Network | PyPI, GitHub and `storage.googleapis.com`: the default **Trusted** network access is enough. No exchange API is reachable |
| Progress | Every `racinglines` command prints a `progress …` line to stderr at least every 5 minutes (`RACINGLINES_PROGRESS_SEC`, [`racinglines/progress.py`](https://github.com/lalligagger/racinglines-public/blob/main/racinglines/progress.py)); a quiet log for longer than that is worth a look |

## The pieces

- **The database snapshot.** `racinglines db snapshot-export` writes the tables the models and sweeps read
  (results, laps, track profiles, market links, …) to `data/archive/db/` as Parquet, **with their ids**.
  `racinglines db snapshot-import` loads it into a fresh database: an exact replica. Rebuilding from the raw files
  would give the same data under different ids, and the pricing code orders drivers by id in places, so seeded prices
  would then differ by simulation noise. With the snapshot they match the exporting machine's exactly. Web-app
  tables (users, books, bets, jobs) and model runs are never exported.
- **`scripts/cloud/prepare.sh`** (run locally before launching): moves every market row from the Postgres buffer
  into the Parquet archive, runs `db snapshot-export` and `f1 pm-links-export`, and checks that only allow-listed
  data would be committed.
- **`scripts/cloud/bucket.sh push|pull|ls|restore --yes`** (a machine with gcloud) and **`scripts/cloud/bucket.py`**
  (a cloud session, with the HMAC key): the data bucket, everything a session needs that isn't in git
  ([Data bucket](data.md#data-bucket)).
- **`scripts/cloud/start.sh`** brings up a fresh VM: Python 3.14 env, PostgreSQL, `db init`, then
  `db snapshot-import`. Market prices and trades are read straight from the Parquet archive, so the VM needs no
  exchange access. (Without a snapshot it falls back to `f1 ingest` from the FastF1 files and `f1 pm-links-import`.)
- **`racinglines strategy search f1 sweeps/<queue>.toml`** runs the queue: up to `parallel` sweeps at once, each
  saved as a normal sweep run. It **re-reads the queue file whenever a slot frees**, so editing pending `[[job]]`
  entries steers it. It stops starting jobs after `hours`. After every finished job it rewrites
  `data/runs/search/<name>/leaderboard.md` and `results.json`. A queue can mix sports: a job with `sport = "mtb_dh"`
  runs a walk-forward (`racinglines backtest walk-forward <sport>`, model only, scored per market kind); a job with
  `sport = "nascar"` (or `"motogp"`) and `kind = "sweep"` runs that sport's season sweep
  (`racinglines strategy sweep <sport>`, [`pipelines/season_sweep.py`](https://github.com/lalligagger/racinglines-public/blob/main/racinglines/pipelines/season_sweep.py))
  with `venue = "kalshi"` / `"polymarket"` / `"og"` where the sport lists it, and its own baseline (same sport,
  season and venue). `replicates = N` on any job runs it (and its season's baseline) at N seeds.
- **`racinglines strategy search-import f1 <results.json>`** loads a finished search's sweep runs into your local
  database (marked `params.source`), so they show up in the Lab's Edge Finder and Model variants.

## One-time setup

1. At [claude.ai/code](https://claude.ai/code), click the **cloud icon** in the row above the message box. It's
   labelled with the current environment's name, e.g. **Default**. Choose **Add cloud environment** (or hover over
   an existing one and click its settings icon to edit it):
    - **Name:** `racinglines`
    - **Network access:** the default **Trusted** is enough. It covers PyPI, GitHub and `storage.googleapis.com`
      (the [data bucket](data.md#data-bucket)).
    - **Environment variables:** `BASH_MAX_TIMEOUT_MS=1800000` (lets a command run 30 minutes), plus the data
      bucket's three variables. `pbcopy < ~/.config/racinglines/gcs-hmac.env` copies them without printing them;
      paste them on the lines below. They are visible to anyone using the environment.
    - **Setup script:** none. `start.sh` takes longer than the ~5 minutes a cached setup allows, so the session runs
      it.

    `/remote-env` in a local Claude Code session makes it the default for `claude --cloud`.

2. The GitHub connection must reach the repository: install the Claude GitHub App on it, or run `/web-setup` in a
   local Claude Code terminal.

!!! warning "Never paste the HMAC key into a doc, a commit or a PR"
    It lives in the cloud environment's variables and in `~/.config/racinglines/gcs-hmac.env` on the Mac, nowhere
    else.

## Launch

### Step 1: refresh the bucket

The session reads the bucket, not your checkout. From a machine with the data and gcloud:

```bash title="LOCAL (Mac)"
bash scripts/cloud/prepare.sh
bash scripts/cloud/bucket.sh push
```

### Step 2: push the branch and start the session

```bash title="LOCAL (Mac)"
git switch -c cloud/<name> && git push -u origin cloud/<name>
claude --cloud "Run the cloud sweep in docs/cloud-sweep.md with queue sweeps/<queue>.toml. Follow the Agent protocol section exactly."
```

Pick the `racinglines` environment if asked. Or start the session at claude.ai/code on that branch and environment,
with the same message. Watch or steer it from the browser or the Claude app; `claude -p "message" --cloud <session-id>`
sends it a message from any terminal.

## What a search is for

- **2026, the primary window:** every weekend of the 2026 calendar raced so far (the sweep default; never restrict
  rounds for a result that's reported). Goals: the best model × strategy combo for the **remaining races**, and how
  the **championship markets** would have gone if entered early (`kind = "checkpoints"` with early entries,
  `kind = "season_strategy"`).
- **2025, the secondary window:** "if we had been live from the first race of 2025". Every stage is priced strictly
  as of its moment (only earlier FastF1 data), against the real 2025 Polymarket markets. 2025 is the last season of
  the old rules; 2026 has new cars, so an edge that holds in both is **robust**, one that holds only in 2026 is
  **2026-specific** (legitimate for the remaining races), and one that holds only in 2025 is suspect.
- **Always against the baseline on the same data:** the search adds each season's default-settings baseline itself
  and runs it first; the leaderboard shows every combo's difference from it.

## The params-4h search

The first long run (2026-09-27): queue `sweeps/params-4h.toml`, 4 hours, 3 sweeps in parallel, **settings only** on
the existing 9 model variants × 9 strategies (no new variants, strategies or model code), 2026 tuned and 2025 held
out. 291 sweeps ran with no failures; the queue emptied about an hour before the cutoff. The findings, and the two
setups that became strategy profiles A and C, are in [Market making](market-making.md#cloud-settings-search-params-4h).
Report and data: `data/runs/search/params-4h/` (`REPORT.md`). Later searches ran on the VM instead
([Overnight VM run](overnight-vm-run.md)), where the data is current.

## Agent protocol

The session follows these steps. They're written for the agent.

### Step 1: bring-up

```bash title="CLOUD"
bash scripts/cloud/start.sh
```

Run it in the background and wait for `ready`. If a step fails, fix the cause (not the data), note it, and re-run:
the script is idempotent.

### Step 2: start the search

```bash title="CLOUD"
.venv/bin/racinglines strategy search f1 sweeps/<queue>.toml > data/runs/search/<name>.log 2>&1
```

In the background. Stay active until it prints `finished`: an idle session's VM is reclaimed and running work is
lost. The log carries a `progress …` line at least every 5 minutes.

### Step 3: every 10 minutes, steer the queue

Read `data/runs/search/<name>/leaderboard.md` and `state.json`, then edit pending `[[job]]` entries. Every edit gets
a `note` saying why.

- **Explore anything in the settings schema** (`racinglines/pipelines/sweep_settings.py`,
  `racinglines strategy sweep f1 -h`): model variant and switch combos, half-life, shrinkage, simulations, track
  features and practice prior, entry timing (`taker_stages`, `late_stages`), taker and maker parameters, market
  kinds and filters; and the championship jobs' variants and entry points.
- **New ideas in code are allowed** (a new model input, strategy rule or entry rule) under the roadmap's ground
  rules: behind a new setting in `sweep_settings.py` (or a switch in `models/variants.py`) whose default is today's
  behavior, with a test, so the baseline and every earlier result are unchanged (`python -m pytest -m "not live"`
  must pass). Commit code changes separately from results.
- **Replace what can't teach anything new:** drop a pending job whose question an earlier result already answered,
  and add a more informative one. Prefer small steps around the current best (one or two settings at a time) over
  random jumps.
- **Held-out rule:** a setting chosen by looking at one window must be checked on the other before it's reported as
  better. Label every claim robust / 2026-specific / not better.
- If a job fails, record why in its note and move on.

### Step 4: candidates

Add a `[[candidate]]` entry to the queue file for each combo worth loading into the Lab: `name`, `year`, `strategy`
(update, hold, last, early, maker, maker_flat, maker_skew, maker_widen, maker_all), `why` (with its label: robust /
2026-specific), and its settings. Keep it to the few best. They're imported as Lab candidates, loadable into the
Edge Finder sweep form.

### Step 5: every 30 minutes and at the end, save the results

```bash title="CLOUD"
python scripts/cloud/bucket.py push results/<session> data/runs/search/<name>
git add sweeps && git commit -m "search: <name> progress" && git push
```

The queue file is in git; the results folder is not (the warning at the top), so it goes to the bucket.

### Step 6: at the end, the report

```bash title="CLOUD"
.venv/bin/racinglines strategy search-report f1 sweeps/<queue>.toml
```

That gives the labels, noise floor, confirmations and candidates ([Backtest core](backtest-core.md#the-search-report));
to measure the noise floor rather than assume it, give the leading combos `replicates = 3` (their baseline gets the
same). Downhill jobs are reported in `data/runs/search/<name>/mtb_dh/`. Then write `data/runs/search/<name>/REPORT.md`:
what ran, the leaderboard, the best combo for the remaining 2026 races, what the early championship entries would
have made, what held in both windows and what didn't, every queue change with its reason, the candidates, and what
to run next. Push it to the bucket and copy it into the PR. Stop.

## Bring results home

`bucket.sh pull` and `bucket.py pull` sync only the data folders (`live`, `runs/f1`, `raw/mtb_dh`,
`archive/markets`), not `results/`, so copy a session's results down with gcloud (the same `gcloud storage` calls
`bucket.sh` makes) and import them:

```bash title="LOCAL (Mac)"
bash scripts/cloud/bucket.sh ls results/
gcloud storage rsync --recursive "gs://$RACINGLINES_GCS_BUCKET/results/<session>" data/runs/search/<name>
racinglines strategy search-import f1 data/runs/search/<name>/results.json
```

The imported runs appear in the Lab: every full-season configuration can be added to the Edge Finder, and the
search's candidates are listed under **Candidates**, each with **Load in Lab** (fills the Edge Finder sweep form with
its settings, to tweak and re-run). The pinned benchmark only ever uses default-settings baseline sweeps.

## Limits

- **One VM is about 4 cores.** More parallelism means more sessions, each with its own queue file (e.g. one per
  season or model family), all drawing on the same usage limits.
- **An idle session is reclaimed.** Work in progress on the VM is lost; pushed commits and bucket pushes aren't.
  The search can be restarted on the same queue: finished jobs are kept in `state.json` (if it was saved).
- **15-24 weekends per season are few.** A search tries many combinations; the best one looks better than it is.
  The held-out rule and the pinned benchmark are there for that.

## Next steps

<div class="grid cards" markdown>

- **Overnight VM run**

    ---

    The same searches on the VM, where the data is current, as a transient unit.

    [Overnight VM run](overnight-vm-run.md)

- **Backtest core**

    ---

    The search report, the noise floor and the labels.

    [Backtest core](backtest-core.md#the-search-report)

- **Market making**

    ---

    What the params-4h search found and the profiles it produced.

    [Market making](market-making.md#cloud-settings-search-params-4h)

</div>
