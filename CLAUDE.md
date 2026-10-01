# Working with Claude Code on racinglines

This is the standing project note for Claude Code sessions on this repo. It sets the dev cycle, model/thread
allocation, command-formatting, merge, and reporting conventions. Read this first in every new session.
For the domain itself (phases, decisions, what's built), read [docs/todo.md](docs/todo.md) and
[docs/f1-roadmap.md](docs/f1-roadmap.md) next — this file is process, those are substance.

## Environments (always label commands with one of these)

| Label | Where | Notes |
|---|---|---|
| **LOCAL (Mac)** | This machine, `.venv` | Dev, tests, the demo maker/taker, `mkdocs serve` |
| **VM (production)** | `racinglines-vm`, via `scripts/deploy/vm.sh` | `racinglines.bet`. Never edited directly — only `vm.sh deploy` |
| **CLOUD (sweep)** | An ephemeral cloud session | Long searches (`f1 search`); no Kalshi network access; see [docs/cloud-sweep.md](docs/cloud-sweep.md) |

Every command block in a reply must be labeled with one of these, in the order they should run, one block per
step (not one giant script), so they can be run and checked one at a time.

## Model / thread allocation

**Goal:** keep bulky work and bulky tool output out of the most expensive context. Fable is the seat that plans,
decides, reviews and writes the final answer; Opus-, Sonnet- and Haiku-class workers do the work in their own
context and report back a short, evidenced footer. The cost of an agent session is not what the model writes, it
is the context it re-reads every turn, so a test log or a 40-file grep sitting in a Fable context is re-read at
Fable prices for the rest of the session. The goal is therefore *not* "use Fable more" or "use Fable less". An
earlier version of this note had that upside down: it routed the hardest hands-on tasks *to* Fable and asked
sessions to go looking for high-complexity work so the Fable budget would not sit idle. Fable's budget sitting
idle is fine. Fable doing hands-on work a worker could do, in a context Fable then re-reads, is the failure mode.

> **Source:** Wes Sander, "Fable Decides, Opus and Sonnet Do the Work: How I Route Claude Code Subagents",
> <https://x.com/ucsandman/status/2104795895053025310> (2026-09-28). The role split, the "work goes down,
> questions go up" graph, the size-based delegation rule, the worker footer, the fan-out arithmetic and the
> "brief, don't wall" lesson below are all from that post. The racinglines-specific examples are ours.

### Who does what

| Role | Model | Use for |
|---|---|---|
| **Decide / review** | `Fable` (pass as the literal model name) | Plan, resolve ambiguity, make the judgment calls (model/pricing methodology, settlement rules, order signing, trading flags, cross-cutting refactors touching 4+ modules, ambiguous roadmap items), review workers' footers, the final review pass before a merge batch, root cause after two fixes have already failed. Fable reads decisions and conclusions, not transcripts. |
| **Own** | Opus-class | A large or risky task end to end: a multi-file change, a repo sweep, a root-cause hunt. The only worker that may hand pieces further down. Routine main-loop work belongs here, not in Fable. |
| **Implement** | Sonnet-class | The decision is already made; write the code inside the scope given (a new sweep setting, a new venue path, a CLI subcommand, tests for either). In a fix loop it does not edit test files: a test that looks wrong comes back up as a decision, not bent until it passes. |
| **Scout** | Haiku-class | Read-only lookups (where is this defined, what calls it, how many are there) and mechanical work: doc sync, formatting, git housekeeping. If it cannot find something it says NOT FOUND and lists where it looked. |

**Name the model on every spawn.** Subagents inherit the parent's model, so an `Agent`/`agent()` call with no
model in a Fable session is a Fable worker. That single omission is how one workflow script spawned 110 copies
of Fable in the source post. A bare call is a bug, not a default.

### Work goes down, questions go up

- Delegation only goes down: Fable → Opus → Sonnet → Haiku. Haiku spawns nobody. Peers are not edges (a Sonnet
  worker handing its job to another Sonnet worker hides the work one level deeper), and a fork counts as a peer
  because it inherits the caller's model.
- The one thing that goes up is a question. A blocked worker asks one rung above itself (Sonnet asks Opus, Opus
  asks Fable) and gets an answer, not a takeover. A blocked question turns into a guess, and a guess mid-fix costs
  more than the advice.
- Depth two is the ceiling: Fable → Opus → Haiku, never deeper.
- Fan out from the highest level that can already write the brief. If Fable already knows the five files, it
  spawns five scouts, not one owner that goes and rediscovers them.

### Delegate by size, not by principle

Under about ten tool calls or eighty edited lines, do it inline, whoever is in the main loop. Delegation earns
its arrival cost (tens of thousands of tokens before the worker does anything) when the work is big, when the
pieces can run at the same time, or when the output is long and only the conclusion is needed. A one-line edit
delegated to a worker costs more than doing it by hand.

Every dispatch names its model, declares its size, and says what "done" and "verified" mean:

```
# EST: 14 calls, 3 files
Scope: racinglines/f1/pricing.py, racinglines/f1/settings.py, tests/f1/test_pricing.py
Done when: the new spread setting is off by default and the existing golden tests are byte-identical
Verify: python -m pytest tests/f1/test_pricing.py -m "not live"
Report: files changed, the verify command and its last line, what you did not check
```

**Every worker ends with the same footer:** what changed, the exact command that verified it, the paths it
checked, and what it did not check. A claim with no evidence line counts as unverified. That footer is what the
deciding seat reads, not the worker's transcript.

### Fan-outs and workflows

- Write the agent count down as arithmetic before launching (producers + items × verifiers + synthesizers), cap
  any term that depends on an earlier stage with a slice, and merge duplicates before any per-item stage. The
  ceiling is 30 agents; anything over 40 needs a written reason. A fan-out with no declared size does not run.
- Fable appears in a workflow only at the end, as the judge that reads everything and makes the call: a
  top-level `await` after the fan-out, never inside a `parallel`, a `map` or a loop, at most a few times per
  script.
- Concurrency limits only queue the rest; every agent still runs and still pays its arrival cost.

### Brief, don't wall

Hard blocks on routing mid-task get probed, not obeyed (the source post's edit-budget hook logged 714 overrides
in 1,046 events and once left a file half-edited). Block only the things that destroy state, which for us are the
safety rails at the bottom of this file. For routing, put the economics in front of the model once at the start
of the session, name the model on every spawn, and fix the call on the way through.

At the start of a session, state for each queued task which role owns it and why, before assigning models. If
nothing needs the deciding seat, say so and run the session on Opus-class or below. Never route work to Fable
to use the budget.

## Dev cycle

1. **Plan.** Restate the ask, resolve ambiguity, no code yet. Check `docs/todo.md` for whether this is already a
   tracked item (U-numbers, P0/P1/P2) and cite it.
2. **Develop roadmap.** Break the plan into ordered tasks. For each: owning role (decide / own / implement / scout), files/modules touched, and
   its test/doc obligations (`docs/f1-roadmap.md` "ground rules": golden
   tests, leakage-rule tests for new pricing/trading paths, `tests/test_no_data_in_git.py`).
3. **Implementation.** Only after the roadmap is confirmed (or the task is trivial and low-risk).
4. **Run one thread per task**, one task at a time, model per the role table above and named explicitly on
   every spawn, on the task's feature-track branch (see [Branches](#branches-feature-tracks)), not a new branch
   per small task.

   **Pre-deploy flow (final staging only):**
   - Keep reviewable work in one feature-track branch and split it into small, ordered PRs as needed; stacking
     PRs is fine when they are part of the same feature slice, but each PR must still be a clean, reviewable unit.
   - Do not deploy to the VM for every small PR or every intermediate commit. VM churn is expensive and noisy;
     a working branch gets local tests and code review first, then one final staging deploy when the slice is ready.
   - The deployment gate is: local green -> final staging gate -> one production deploy. The command is
     `bash scripts/deploy/predeploy.sh --staging <ref>` for the final branch checkpoint, and only then
     `bash scripts/deploy/predeploy.sh --prod <ref>` or `bash scripts/deploy/vm.sh deploy <ref>` on the final
     branch after the staging pass.

5. **Report back**, every check-in:
   - status per task (done / blocked / needs a decision),
   - open questions, especially anything the roadmap calls an "owner decision" (`docs/todo.md#owner-decisions`),
   - a sequenced git command block to merge, in the order that avoids conflicts (one branch per task), e.g.:

```
# LOCAL (Mac) — merge sequence, run in order
git checkout main && git pull
git merge --no-ff work/<task-1>          # ⚠️ touches settlement rules — read the diff first
git merge --no-ff work/<task-2>          # a later task's branch, if it is ready in the same batch
python -m pytest -m "not live"
git push
```

   Mark any merge touching money-adjacent code (settlement, order signing, trading flags, live-event units,
   VM systemd units, DB migrations) with **⚠️ needs special attention** and say why, right in the command block's
   comment, not just in prose above it.

**Before any merge is proposed, not after:**

```
# LOCAL (Mac)
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
```

Run the full suite too when the local database is up. `UPDATE_GOLDEN=1` only in a deliberate promotion change,
per the [F1 roadmap](docs/f1-roadmap.md#5-promotion-rule-when-a-challenger-becomes-the-default), with a decision
log entry in the same change.

**Deploys during live events.** `vm.sh deploy` doesn't wait for a live event: it pauses the VM's timers (live-event
steps, signals), deploys, and resumes them with one catch-up step each ([VM deploy](docs/vm-deploy.md#whats-in-the-repo)).
There is no `--force`. Don't hand-restart a live event's units around a deploy. If the update fails, the timers
stay paused on purpose: fix and redeploy, then check `vm.sh status`.

## Branches: feature tracks

Owner rule (2026-09-30). Too many standalone branches with one or two commits each (#98 to #112 were fifteen PRs in
two days, five of them "Overnight VM run: ..."). Group related small tasks on one **feature-track branch** off
`main`, and open one or more small PRs in a stack when the work naturally splits; merge the stack in order when the
batch is green and reviewed:

| Track | Branch | What goes on it (recent examples) |
|---|---|---|
| App | `track/app` | web app pages and the Markets board (#101, #103, #108, #110, #111) |
| Data | `track/data` | ingest, exchange schemas, syncs, backfills, data-change log entries (#89, #90, #91) |
| Models | `track/models` | pricing models, sweeps, replays, forecasts, decision-log entries (#85, #87, #93, #112) |
| Ops | `track/ops` | `scripts/vm`, `scripts/deploy`, `scripts/cloud`, runbooks, progress lines (#92, #94, #98 to #100, #102) |
| Docs | `track/docs` | reports, status matrices, roadmap and todo edits, CLAUDE.md (#104 to #106) |

- A track branch is short-lived per batch: cut it from `main`, add the batch's tasks as separate commits (one
  commit per task, its message naming the task), and open one or more small PRs from that branch in a stack when
  the workload is naturally split. Merge the PRs in order, and cut the next batch fresh from `main` under the same
  name when the batch is done. Never stack a new batch on already-merged history.
- A task that spans tracks goes on the track of its riskiest part (a money-adjacent change goes on its own track's
  PR with the ⚠️ note, never hidden in a docs batch).
- A standalone `work/<task>` branch is still right for: anything money-adjacent (settlement, order signing,
  trading flags, live-event units, VM systemd units, DB migrations), a hotfix that has to deploy before the
  track's batch is ready, and a long task another track must not wait on.
- Cloud threads get their branch name from the harness; use it for the batch and say which track it is in the PR
  title (`[ops] ...`).
- Staging is the final gate, not a deploy for every tiny PR. A feature branch or track batch gets one final
  `bash scripts/deploy/predeploy.sh --staging <ref>` check when it is ready; only then do we do the single
  production deploy (`bash scripts/deploy/predeploy.sh --prod <ref>` or `bash scripts/deploy/vm.sh deploy <ref>`).
  This keeps VM churn down while still giving us a real staging check before prod.

## Long-running jobs: a progress line every 5 minutes

Owner rule (2026-09-30), every context (cloud, the Mac, the VM) and every long job (downloads, backfills,
backtests, sweeps, replays): the job prints a flushed progress line at least every 5 minutes, with the elapsed time,
done/total and the current item where it has them. Built in: every `racinglines` command except `web` and `mcp`
runs a heartbeat ([racinglines/progress.py](racinglines/progress.py)) that prints
`progress <command>: <n> min elapsed · race 12 of 36 (...) · about 30 min left` to stderr every
`RACINGLINES_PROGRESS_SEC` (default 300; 0 turns it off), with stdout and stderr line-buffered. stdout and saved
outputs are unchanged. A new long loop reports its position with `progress.track(...)` or `progress.update(...)`.
Scripts set `PYTHONUNBUFFERED=1`, and `scripts/vm/overnight.sh` beats every `HEARTBEAT_MIN=5`. A new script or
one-off job (a `systemd-run` unit, a cloud sweep, a shell loop) must do the same before it is handed to the owner.

## Screenshots

Owner rule (2026-09-30), for every report, doc and handoff: take screenshots with the browser window at most
**1024 px wide** and the page zoom at **150%**, so text reads at report size. With Playwright:
`browser.new_page(viewport={"width": 683, "height": 900}, device_scale_factor=1.5)` (1024 / 1.5 = 683 CSS px,
saved at 1024 px wide), or in Chrome set the window to 1024 px and zoom to 150%.

## Report generation

**Already built, for live events:**

```
# LOCAL (Mac) or VM
racinglines live report <spec> --pdf
```

Produces `reports/<event>/report.md` (+ `img/` for charts) → `report.html` (`racinglines/reporting/markdown_html.py`)
→ `report.pdf` (weasyprint or a headless browser). Use this as-is for any completed live event.

**Not yet built, for other large updates** (a finished roadmap milestone, a sizing review, a season close): no
generic pipeline exists today — these have been ad hoc so far. Reuse the same `markdown_html.render` step: write
the report as Markdown with images saved under an `img/` folder next to it (plots, screenshots, tables as
Markdown tables), then render HTML → PDF the same way `live report` does. A real `racinglines report build
<folder>` command is planned (engine roadmap E6; the reproducibility plan is in
[todo: Reports](docs/todo.md#reports-consistency-and-reproducibility)). Until it exists, every report folder gets a
`SOURCES.md`: the commit it was built from, each query or command that produced a number or plot, the run ids and
data files it read, and the screenshot settings, so someone else can rebuild it.

**Quality bar, until then:** match the two existing reports, not a generic template.

- [reports/2026-09-27-whistler-live/report.md](reports/2026-09-27-whistler-live/report.md) (the Whistler live
  event): a one-paragraph scene-setter, a top-line summary table, a section per phase of the event, a timeline
  table with bolded turning points, winners/losers tables with real numbers (not rounded categories), and a
  named "what this does and doesn't show" caveat section. Every claim carries its number.
- `data/runs/search/<name>/REPORT.md` (a cloud sweep, spec in
  [docs/cloud-sweep.md](docs/cloud-sweep.md#agent-protocol) step 6): what ran, the leaderboard, the best combo
  for what's ahead, what held in both the primary and held-out windows and what didn't (labelled
  robust / 2026-specific / not better), every queue change with its reason, the candidates, and what to run
  next.

Both share: numbers over adjectives, every tuned or chosen setting named explicitly, and a closing section that
says what's next or what wasn't shown — never just a leaderboard or a wall of metrics with no verdict.

## Handoff to Copilot ("troubleshoot in Copilot")

When I say this, produce one dated Markdown file I can paste into VS Code Copilot, containing:

- **What's broken** — one paragraph.
- **Environment** — LOCAL / VM / CLOUD, branch, last commit.
- **What's been tried** — commands run and their result (trimmed, not full logs).
- **Relevant files** — as a list, so Copilot can jump straight there.
- **The exact question** — what you need Copilot's tools (terminal, editor diagnostics, browser) for that Claude
  Code's own tools couldn't resolve.

Default location: `reports/handoffs/<date>-<slug>.md`, **local only** (gitignored) — never commit or push these.

## Database writes and new data sources (every sport and exchange)

Standing practice from the owner (2026-09-29), applied to every task, not one pass:

- **Back up before any step that writes to a database.** A task plan lists the backup as its first step and the
  rollback as its last: migrations, seeds, syncs that add or retag links, recorder passes on a fresh database,
  history rebuilds. The dump goes in `data/backups/db/racinglines-before-<task>-<UTC time>.sql.gz`, and the same change
  adds a `data_changes` entry and a `docs/data-changes.md` line that name it. A migration is tried on a restored copy
  first. Read-only steps need no backup.
- **Probe a data source from the owner's machine before any full run.** For a new sport, exchange or results feed: a
  Remote Control session on the Mac (which has network access the cloud sandbox lacks) makes a small read-only probe
  (the endpoint answers, the shape matches, paging, caps and history depth, the terms of use). The responses become
  test fixtures and the findings go into the schema (caps as `limits`). Only then does the full run happen on the
  VM. Never run a full import against an unverified source, and never guess at a live API's behaviour from the cloud.

## Safety rails (non-negotiable, carried over from the project's own rules)

- Never flip `POLYMARKET_TRADING_ENABLED` / `KALSHI_TRADING_ENABLED`, run `vm.sh public on`, or run a DB migration
  against the VM without my explicit sign-off in the same conversation turn.
- Never `git push --force` or rewrite published history.
- Every tuned setting (spread, filter, model choice) needs a decision-log entry before it's treated as final —
  match the existing `docs/f1-roadmap.md` decision log format.
