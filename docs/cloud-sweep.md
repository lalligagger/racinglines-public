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

## Code-only next-run planner (LOCAL)

`racinglines strategy search-plan f1 INPUT.json --budget N --dry-run` prints a JSON plan to stdout.
Step 1 never launches a sweep, connects to the database, writes files, or calls Jev, even without
`--dry-run`. The budget defaults to **0**. MCP and Lab integration are deferred for this local,
code-only step; the existing search runner and its defaults are unchanged.
The planner rejects `--demo` instead of building a synthetic database.

Supply a snapshot with one explicit `year`, `stored_keys` (the `params.settings_key` values of
already-stored F1 `kind='sweep'` runs for that year), and `candidates` (a list of settings dicts).
There is no automatic database query. Missing settings take the schema defaults. Deduplication uses
`Settings.from_dict(candidate).key` unchanged, including simulation count and seed. Stored keys
and earlier duplicate candidates are skipped; the first new occurrence wins, in input order.
Neither `data_key` nor weekends belong in settings. Research's `(config, taker mode)` identity and
seed-collapsed report ids are not sweep-run identities.

Example input (illustrative, not a tuned setting):

```json
{"year": 2026, "stored_keys": [], "candidates": [{}, {"min_edge": 0.08}]}
```

```bash title="LOCAL (Mac)"
.venv/bin/racinglines strategy search-plan f1 INPUT.json --budget 2 --dry-run
```

An optional `history` list contains chronological completed outcomes:
`{"settings_key": "...", "score": 12.0}`. Keys must be unique and belong to `stored_keys` for this
year. `--stop-after K` enables stopping; it requires `--best-score X`, the best **before** this
history. Higher scores are better. A score strictly more than `--margin M` above the running best
resets the consecutive-miss count; equality is a miss. Every gain updates the best, even below the
margin. The first K misses latch the stop and produce an empty plan; a later history entry cannot
restart it. Pending, unscored candidates never count as misses. Stopping defaults off. The caller
supplies the score metric and margin; no Jev scoring or noise-floor estimate is invented here.
This planning threshold does not replace the held-out and noise-floor reporting rules below.

The output carries the selected full settings and their keys, counts, running best, miss count,
stop status, and reason (`stop_rule`, `budget`, or `exhausted`), with `execution_enabled: false`.
It is a bounded candidate list for a later typed decision/scoring step, not a decision model.

## Local Jev-guided auto-sweeper (research MVP)

`scripts/research/auto_sweeper.py` adds the execution loop around a **finite, supplied pool**.
Jev makes a typed Choice over exact settings ids plus `STOP`; Python owns validation,
deduplication, budgets, scoring, process control and checkpoints. This matches the bounded
decision workflow, not open-ended parameter generation. No settings are promoted to profiles
or trading defaults. CLI-only research for now: MCP and Lab integration are deferred.

The pool is a JSON list of **1 to 254 settings dictionaries**, with one common ranking simulation
count and the default venue (Polymarket). Seed and simulations remain part of exact run identity.
Duplicate normalized configurations are rejected. Pool order is normalized by exact key, so
input reordering does not change warm-start compatibility. The target is 2026, held-out is 2025.
Automatic pool generation, other venues/sports and unlimited searches are out of this MVP.

### Plan without touching the database or Jev

The standalone script defaults to dry-run and prints the required jobs. Neither a journal nor
a lock is created, and no database, subprocess or SDK call is made. Without reading the database,
this is an **upper bound** on work, not a promise that all listed jobs are new.

```bash title="LOCAL (Mac)"
.venv/bin/python scripts/research/auto_sweeper.py POOL.json
```

### Execute only after a local backup

The first step is an operator-created backup of the **same local PostgreSQL database** the runner
will use. Use the local PostgreSQL dump/restore procedure, record the backup and task in the data-change
log, and keep the dump under `data/backups/db/`. The runner requires an existing nonempty backup file;
it cannot verify that the file is a valid dump or belongs to the selected database. It refuses remote
database URLs and demo stores. No VM command is involved.

Execution requires `--execute`. Both budgets initially default to **0**:

- `--budget N`: total sweep **attempts**, including missing baselines, both seasons and
  higher-simulation confirmations. A failed or interrupted attempt still spends budget.
- `--jev-budget N`: total chooser calls, counted before the request, with SDK retries disabled.
  Failed or interrupted calls still spend budget. Cached completed choices are not charged again.

```bash title="LOCAL (Mac)"
.venv/bin/python scripts/research/auto_sweeper.py POOL.json --execute --journal data/runs/auto-sweeper/state.json --budget 8 --jev-budget 1 --backup BACKUP.sql.gz
```

With an ordinary non-baseline config, eight missing sweeps cover candidate and same-seed baseline,
at ranking and confirmation fidelity, in both years. Shared or already-stored runs reduce that work.
Every launch uses the existing `strategy sweep f1 --no-fetch --save` path. Exact committed sweep keys
are reconciled before launches, including recovery when a child committed before its controller
checkpoint. Legacy F1 runs without an explicit sport field are included. An already-stored partial
sweep with a requested year/key **blocks execution**, unless a usable full-season counterpart exists;
it is never silently treated as new. Malformed metrics, missing strategy P&L or mismatched
candidate/baseline event coverage also block scoring rather than fabricating a result.
The runner does not rerun a configuration merely because the tape has changed; a separate
deliberate reproducibility study is needed for that.

### Interrupt and warm-start

Ctrl-C or SIGTERM terminates and reaps the directly owned sweep child and saves the journal.
Progress is flushed at least once a minute while waiting. Only one controller for this workspace
may execute at a time; a second journal or different working directory is not a way around that lock.
The child inherits the repository-root lock: after abrupt controller death, it prevents another runner
from starting until that child exits. Its PID is checkpointed as well; a possibly live/reused PID
blocks restart for operator inspection and is never killed automatically.

Resume with the **same pool, strategy, model, seasons, simulation counts, stop rule and journal**.
The cached choice stays active while its target/held-out/confirmation work is incomplete. Omitted
budgets keep their previous totals rather than resetting them:

```bash title="LOCAL (Mac)"
.venv/bin/python scripts/research/auto_sweeper.py POOL.json --execute --journal data/runs/auto-sweeper/state.json --backup BACKUP.sql.gz
```

After inspecting a failure or interruption, add `--retry-failed` to explicitly permit retry of
uncommitted work. Recovered committed work is reused, not relaunched. To extend an exhausted budget,
pass **new cumulative totals** and `--increase-budget`:

```bash title="LOCAL (Mac)"
.venv/bin/python scripts/research/auto_sweeper.py POOL.json --execute --journal data/runs/auto-sweeper/state.json --budget 24 --jev-budget 3 --increase-budget --backup BACKUP.sql.gz
```

The journal also binds to the local database host/port/name through a credential-free fingerprint
and pins reused run ids. Changing databases or deleting/replacing pinned runs blocks resume.
Do not delete or reset a journal to evade a budget. Pool changes require a new journal; exact stored
runs still deduplicate across journals. This is restartable at completed-run boundaries, not a
checkpoint of an individual Monte Carlo simulation. Abrupt process death can lose uncommitted compute
or an unanswered API call. Inspect the journal and process state before retrying.

### What guides Jev and what the output means

The controller reuses `search_report.stats` and `search_report.rank`. Its scalar objective is:

**target-season gain over the same-fidelity baseline + min(0, held-out gain over baseline)**.

This is the report's baseline-gain ranking branch, not raw P&L. Held-out gains cannot compensate
for weak target gains; held-out losses penalize the score. Existing verdicts and noise floors,
higher-simulation confirmation, drawdown and concentration remain visible as separate evidence.
Controller verdicts use the report's configured default noise floors ($150 taker / $350 maker),
not a changing replicate estimate, so accumulating replicates cannot retrospectively change the
controller's cached verdicts. The ordinary descriptive `search-report/` can measure replicate noise;
its verdicts may differ and are labelled separately. This fixed-floor choice is an MVP limitation,
not evidence that the default floor is sufficient for a particular search.
A positive score is **not** proof of profit or confirmation. In particular, `robust` with
`confirmed = no` must not be called a confirmed improvement. No metric or margin is tuned automatically.

`--strategy` selects one existing sweep strategy, default `update`. `--confirm-sims` defaults to
16,000 and must exceed the pool's ranking simulations. `--stop-after K` defaults off; after K
consecutive **fully evaluated** configurations fail to improve the running best by strictly more
than `--margin`, the loop stops. Small gains update the best without resetting the miss streak.
Incomplete pairs never count as failures. Jev can also select `STOP`; exhausting the pool ends the loop.

Next to the journal:

| Output | Purpose |
|---|---|
| `state.json` | Atomic, durable budgets, choices/evidence, active configuration, attempts, evaluations and stop state |
| `*.log` | Each sweep child's output, including failures |
| `leaderboard.md`, `leaderboard.csv` | Exact configuration leaderboard using the controller's baseline-gain objective |
| `search-report/` | Existing descriptive P&L report, curves, ranking, held-out and confirmation evidence |

Reports are rebuilt after completed evaluations and on restart; the journal is the resume authority,
not a partially written report. The search-report P&L ranking and the controller's gain ranking are
deliberately labelled separately. No report authorizes real trading or model promotion.

**Rollback is the final operator step if required:** stop the controller and its child, preserve the
journal/logs for diagnosis, then restore the pre-run local backup through the documented restore
procedure. The runner never restores or deletes database rows automatically. Inspect any journal
whose recorded runs disappeared after restore; it must not silently launch replacements.

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
